"""粘贴（pastebin）路由：multipart 创建 / 短链 302 直出 / 元数据 / 凭 token 删除。

- `router`（/api/pastes）提供创建、详情、删除等 API。
- `public_router`（/p）提供公开短链，302 重定向到 R2 自定义域名直出。
"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse

from ..config import settings
from ..db import Paste
from ..logger_config import get_logger
from ..models import PasteCreateResponse, PasteDetailResponse, PasteFileInfo, PasteLink
from ..services import pastes as paste_svc
from ..storage import PasteStore, get_paste_store

logger = get_logger()

router = APIRouter(prefix="/api/pastes", tags=["pastes"])
public_router = APIRouter(prefix="/p", tags=["pastes"])


def _require_r2() -> PasteStore:
    """R2 未配置 → 503（含缺失变量提示）；否则返回 store。"""
    store = get_paste_store()
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="对象存储 R2 未配置，粘贴功能不可用。请配置 "
                   "R2_ACCESS_KEY / R2_SECRET_KEY / R2_ENDPOINT / R2_BUCKET / R2_PUBLIC_BASE_URL。",
        )
    return store


async def _get_live_paste(code: str) -> Paste:
    """存在性 + 过期检查：缺失 404，过期 410，DB 未配置 503。"""
    try:
        paste = await paste_svc.get_paste(code)
    except RuntimeError as e:  # DATABASE_URL 未配置
        raise HTTPException(status_code=503, detail=str(e))
    if paste is None:
        raise HTTPException(status_code=404, detail=f"粘贴不存在或已被删除: {code}")
    if paste_svc.is_expired(paste):
        raise HTTPException(status_code=410, detail="粘贴已过期")
    return paste


@router.post(
    "",
    response_model=PasteCreateResponse,
    status_code=201,
    # FastAPI 对 list[UploadFile] 生成的 files schema 是 contentMediaType，
    # Swagger UI 只认 format: binary 才渲染「选择文件」控件——这里显式覆盖。
    # openapi_extra 里已声明的字段会保留，标题/语言/正文/过期时间由 FastAPI 自动补齐。
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "标题（可选）", "maxLength": 200},
                            "language": {"type": "string", "description": "代码语言（可选）", "maxLength": 32},
                            "content": {"type": "string", "description": "正文（纯文本，1MB 上限）"},
                            "expires_in": {"type": "integer", "description": "过期秒数；0 = 永不过期", "minimum": 0},
                            "files": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                                "description": "附件（可多个，单个 10MB / 总 20MB）；不传视为无附件",
                            },
                        },
                    },
                }
            }
        }
    },
)
async def create_paste_endpoint(
    request: Request,
    title: str = Form(default="", max_length=200),
    language: str = Form(default="", max_length=32),
    content: str = Form(default=""),
    expires_in: int = Form(default=0, ge=0),  # 秒；0 = 永不过期
    files: list[UploadFile] = File(default=[]),  # 可选附件，可多个；不传视为无附件
    x_device_id: str | None = Header(default=None),  # 创建者身份，可选
):
    """创建粘贴（multipart/form-data）。成功返回 {code, url, short_url, delete_token, expires_at, files}。"""
    _require_r2()  # 尽早报 503，避免读完大 body 才失败

    if expires_in > paste_svc.MAX_EXPIRES_IN:
        raise HTTPException(status_code=400, detail="expires_in 超出上限（最长 1 年）")
    content_bytes = content.encode("utf-8")
    if len(content_bytes) > paste_svc.MAX_CONTENT_BYTES:
        raise HTTPException(status_code=413, detail="正文超出 1MB 大小限制")
    if len(files) > paste_svc.MAX_FILES:
        raise HTTPException(status_code=413, detail=f"附件数量超出上限（{paste_svc.MAX_FILES} 个）")
    if not content and not files:
        raise HTTPException(status_code=400, detail="正文与附件不能同时为空")

    # 可选创建者身份：X-Device-Id 存在则惰性注册用户；解析失败按匿名继续
    user_id = ""
    if x_device_id:
        try:
            from ..db import get_or_create_user

            user = await get_or_create_user(x_device_id.strip())
            user_id = user.id
        except Exception:
            logger.warning("解析创建者身份失败，按匿名处理", exc_info=True)

    try:
        result = await paste_svc.create_paste(
            title=title,
            language=language,
            content_bytes=content_bytes,
            files=files,  # 直接传 UploadFile；读取与大小校验在 service 内完成
            expires_in=expires_in,
            user_id=user_id,
        )
    except paste_svc.PasteLimitError as e:
        raise HTTPException(status_code=413, detail=str(e))
    except (paste_svc.PasteStorageError, RuntimeError) as e:
        raise HTTPException(status_code=503, detail=str(e))

    # 短链列表：正文 + 每个附件各一条可独立分享的短链（CF/R2 一个对象对应一个 URL）。
    # 优先 APP_BASE_URL，否则按请求 Host 推导。
    base = settings.app_base_url.rstrip("/") if settings.app_base_url else str(request.base_url).rstrip("/")
    code = result["code"]
    links: list[PasteLink] = [PasteLink(id="content", name="正文", url=f"{base}/p/{code}")]
    for i, f in enumerate(result["files"]):
        links.append(PasteLink(id=f"f-{i}", name=f["name"], url=f"{base}/p/{code}/f/{i}"))
    result["short_url"] = links[0].url  # 兼容字段：正文短链
    result["links"] = links
    return PasteCreateResponse(**result)


@public_router.get("/{code}")
async def paste_redirect(code: str):
    """公开短链：302 直出到 R2 正文对象。缺失 404，过期 410。"""
    paste = await _get_live_paste(code)
    store = _require_r2()
    await paste_svc.increment_view_count(code)
    return RedirectResponse(url=store.public_url(paste.content_key), status_code=302)


@public_router.get("/{code}/f/{index}")
async def paste_file_redirect(code: str, index: int):
    """附件短链：302 到该附件 R2 直出。index 为创建时的附件序号（0-based）。缺失 404，过期 410。"""
    await _get_live_paste(code)  # 存在性 + 过期检查（缺失 404 / 过期 410）
    store = _require_r2()
    files = await paste_svc.get_paste_files(code)
    if index < 0 or index >= len(files):
        raise HTTPException(status_code=404, detail=f"附件不存在: {code}/f/{index}")
    f = files[index]
    return RedirectResponse(url=store.public_url(f.key), status_code=302)


@router.get("/{code}", response_model=PasteDetailResponse)
async def paste_detail(code: str, request: Request):
    """元数据 + 正文文本（从 R2 读取回填编辑器），附件带 R2 直出 URL 与短链。"""
    paste = await _get_live_paste(code)
    store = _require_r2()
    content = await paste_svc.load_content(store, paste.content_key)
    files = await paste_svc.get_paste_files(code)
    base = settings.app_base_url.rstrip("/") if settings.app_base_url else str(request.base_url).rstrip("/")
    links: list[PasteLink] = [PasteLink(id="content", name="正文", url=f"{base}/p/{code}")]
    for i, f in enumerate(files):
        links.append(PasteLink(id=f"f-{i}", name=f.name, url=f"{base}/p/{code}/f/{i}"))
    return PasteDetailResponse(
        code=paste.id,
        title=paste.title,
        language=paste.language,
        content=content,
        expires_at=paste.expires_at.isoformat() if paste.expires_at else None,
        view_count=paste.view_count,
        created_at=paste.created_at.isoformat(),
        files=[
            PasteFileInfo(
                name=f.name,
                content_type=f.content_type,
                size=f.size,
                url=store.public_url(f.key),
            )
            for f in files
        ],
        links=links,
    )


@router.delete("/{code}")
async def paste_delete(code: str, token: str = Query(...)):
    """凭 delete_token 删除：token 错误 403，不存在 404。"""
    try:
        ok = await paste_svc.delete_paste(code, token)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:  # DATABASE_URL 未配置
        raise HTTPException(status_code=503, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail=f"粘贴不存在或已被删除: {code}")
    return {"deleted": True, "code": code}
