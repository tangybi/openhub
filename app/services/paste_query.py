"""粘贴语义查询：把 LLM 输出的结构化查询意图（QuerySpec）构建成参数化查询并只读执行。

安全模型：
- 表名 / 字段名 / 操作符全部走白名单，值全部走绑定参数（含 ILIKE pattern）。
- 执行时事务内先 `SET LOCAL statement_timeout`（限成本）再 `SET LOCAL TRANSACTION READ ONLY`
  （只读兜底；asyncpg 下异常则跳过，结构上已不可能写入）。
- limit 强制 clamp 到 1..50。

正文对象在 R2，不在数据库 —— 只能查元数据（标题/语言/浏览数/过期时间/创建时间/附件名/大小等）。
`delete_token` / `content_key` 属于敏感/内部字段，不在白名单内。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Select, asc, desc, select, text

from ..config import settings
from ..db import Paste, PasteFile, get_sessionmaker
from ..logger_config import get_logger

logger = get_logger()

# 操作符白名单（按字段类型定义；is_null 通用）
_STR_OPS = {"eq", "neq", "contains", "starts_with", "ends_with"}
_NUM_OPS = {"eq", "neq", "gt", "gte", "lt", "lte"}
_DT_OPS = {"gt", "gte", "lt", "lte"}
_OPS_BY_TYPE: dict[str, set[str]] = {
    "str": _STR_OPS | {"is_null"},
    "int": _NUM_OPS | {"is_null"},
    "datetime": _DT_OPS | {"is_null"},
}

# 可查询字段白名单：列名 → (ORM 属性, 类型)。类型决定可用操作符。
_COLUMNS: dict[str, dict[str, tuple]] = {
    "pastes": {
        "id": (Paste.id, "str"),  # 短码
        "title": (Paste.title, "str"),
        "language": (Paste.language, "str"),
        "view_count": (Paste.view_count, "int"),
        "expires_at": (Paste.expires_at, "datetime"),  # null = 永不过期
        "created_at": (Paste.created_at, "datetime"),
    },
    "paste_files": {
        "id": (PasteFile.id, "int"),
        "paste_id": (PasteFile.paste_id, "str"),  # 所属粘贴短码
        "name": (PasteFile.name, "str"),
        "content_type": (PasteFile.content_type, "str"),
        "size": (PasteFile.size, "int"),  # 字节数
        "created_at": (PasteFile.created_at, "datetime"),
    },
}
_MODEL: dict[str, type] = {"pastes": Paste, "paste_files": PasteFile}

MAX_LIMIT = 50
DEFAULT_LIMIT = 20


class InvalidQuery(Exception):
    """语义无法映射到合法查询（表/字段/操作符非法，或问题与本库无关）。"""


@dataclass
class FilterClause:
    column: str
    op: str
    value: object = None


@dataclass
class QuerySpec:
    table: str = "pastes"
    fields: list[str] = field(default_factory=list)  # 空 = 全部白名单列
    filters: list[FilterClause] = field(default_factory=list)
    order_by: str | None = None  # 空 = 默认 created_at
    order_dir: str = "desc"
    limit: int = DEFAULT_LIMIT
    note: str = ""  # LLM 对问题理解的复述（仅展示）


def validate_spec(raw: dict) -> QuerySpec:
    """LLM 返回的 JSON → 校验后的 QuerySpec。非法字段/操作符丢弃并记日志。"""
    if raw.get("queryable") is False:
        raise InvalidQuery(
            "这个问题的语义无法映射到粘贴库查询。\n"
            "可以这样问：\n"
            "· 标题含 python 的粘贴\n"
            "· 浏览量超过 100 的\n"
            "· 永不过期的\n"
            "· 超过 1MB 的附件"
        )

    table = raw.get("table")
    if table not in _COLUMNS:
        raise InvalidQuery("无法识别要查询的数据表，请换个问法（只能查粘贴或附件）。")
    cols = _COLUMNS[table]

    fields: list[str] = []
    for f in raw.get("fields") or []:
        if isinstance(f, str) and f in cols:
            fields.append(f)

    filters: list[FilterClause] = []
    for fc in raw.get("filters") or []:
        if not isinstance(fc, dict):
            continue
        column, op = fc.get("column"), fc.get("op")
        if column not in cols:
            logger.warning("丢弃非法筛选字段: %s", fc)
            continue
        ctype = cols[column][1]
        if op not in _OPS_BY_TYPE[ctype]:
            logger.warning("丢弃非法筛选操作符: %s", fc)
            continue
        filters.append(FilterClause(column=column, op=op, value=fc.get("value")))

    order_col, order_dir = None, "desc"
    ob = raw.get("order_by")
    if isinstance(ob, dict):
        order_col = ob.get("column")
        order_dir = "asc" if str(ob.get("direction", "desc")).lower() == "asc" else "desc"
    if order_col not in cols:
        order_col = None  # 默认 created_at desc 由 build_select 处理

    try:
        limit = int(raw.get("limit") or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(1, min(MAX_LIMIT, limit))

    return QuerySpec(
        table=table,
        fields=fields,
        filters=filters,
        order_by=order_col,
        order_dir=order_dir,
        limit=limit,
        note=str(raw.get("note") or ""),
    )


def _apply_filter(column, fc: FilterClause):
    """映射操作符 → SQLAlchemy 表达式。值全部作为绑定参数，永不拼进 SQL 文本。"""
    op, v = fc.op, fc.value
    if op in _STR_OPS:
        v = str(v)
    if op == "eq":
        return column == v
    if op == "neq":
        return column != v
    if op == "contains":
        return column.ilike(f"%{v}%")
    if op == "starts_with":
        return column.ilike(f"{v}%")
    if op == "ends_with":
        return column.ilike(f"%{v}")
    if op == "gt":
        return column > v
    if op == "gte":
        return column >= v
    if op == "lt":
        return column < v
    if op == "lte":
        return column <= v
    if op == "is_null":
        is_null = str(v).strip().lower() in ("1", "true", "yes")
        return column.is_(None) if is_null else column.isnot(None)
    raise InvalidQuery(f"不支持的操作符: {op}")


def build_select(spec: QuerySpec) -> Select:
    """按白名单构建参数化 SELECT（不执行）。"""
    cols = _COLUMNS[spec.table]
    sel_cols = [cols[f][0] for f in (spec.fields or list(cols))]
    stmt = select(*sel_cols)
    for fc in spec.filters:
        stmt = stmt.where(_apply_filter(cols[fc.column][0], fc))
    order_col = cols.get(spec.order_by, cols["created_at"])[0]
    direction = asc if spec.order_dir == "asc" else desc
    return stmt.order_by(direction(order_col)).limit(spec.limit)


async def run_query(spec: QuerySpec) -> tuple[list[str], list[dict]]:
    """只读执行，返回 (列名列表, 行 dict 列表)。"""
    stmt = build_select(spec)
    sm = get_sessionmaker()
    async with sm() as db:
        await db.execute(text("SET LOCAL statement_timeout = '10000'"))
        try:
            await db.execute(text("SET LOCAL TRANSACTION READ ONLY"))
        except Exception:
            logger.warning("SET LOCAL TRANSACTION READ ONLY 失败，已跳过（结构上本就只读）", exc_info=True)
        result = await db.execute(stmt)
        rows = [dict(row._mapping) for row in result]
    columns = spec.fields or list(_COLUMNS[spec.table])
    return columns, rows


def to_display_sql(spec: QuerySpec) -> str:
    """人类可读 SQL（值插值仅展示；实际执行是参数绑定）。"""
    cols = spec.fields or list(_COLUMNS[spec.table])
    lines = [f"SELECT {', '.join(cols)}", f"FROM {spec.table}"]
    wheres = [_display_filter(fc) for fc in spec.filters]
    if wheres:
        lines.append("WHERE " + "\n  AND ".join(wheres))
    lines.append(f"ORDER BY {spec.order_by or 'created_at'} {spec.order_dir.upper()}")
    lines.append(f"LIMIT {spec.limit}")
    return "\n".join(lines)


def _display_filter(fc: FilterClause) -> str:
    op, v = fc.op, fc.value
    if op == "is_null":
        is_null = str(v).strip().lower() in ("1", "true", "yes")
        return f"{fc.column} IS {'NOT ' if not is_null else ''}NULL"
    if op in ("contains", "starts_with", "ends_with"):
        s = str(v).replace("'", "''")  # 单引号转义（仅展示）
        pat = {"contains": f"%{s}%", "starts_with": f"{s}%", "ends_with": f"%{s}"}[op]
        return f"{fc.column} ILIKE '{pat}'"
    if isinstance(v, str):
        v = f"'{v}'"
    op_sql = {
        "eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=",
    }.get(op, op)
    return f"{fc.column} {op_sql} {v}"


def _cell(v: object) -> str:
    if v is None:
        return "-"
    if isinstance(v, datetime):
        return v.isoformat(timespec="seconds").replace("+00:00", " UTC")
    return str(v)


def _fmt_rows(columns: list[str], rows: list[dict]) -> str:
    """对齐纯文本表格（前端 pre-wrap 直显，不解析 markdown）。"""
    data = [[_cell(r.get(c)) for c in columns] for r in rows]
    widths = [len(c) for c in columns]
    for row in data:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(columns))]
    lines.append("  ".join("-" * w for w in widths))
    lines.extend("  ".join(c.ljust(widths[i]) for i, c in enumerate(row)) for row in data)
    return "\n".join(lines)


def format_answer(spec: QuerySpec, columns: list[str], rows: list[dict], note: str = "") -> str:
    """结果 → 可读文本：复述 + 对齐表格 + 短链 + 生成 SQL。"""
    note = (note or "查询结果").rstrip("。．.!！?？ ")  # LLM note 常带句尾标点，避免拼出「。，」
    lines = [f"{note}，共 {len(rows)} 条匹配（表 {spec.table}）：\n"]
    if not rows:
        lines.append("没有匹配的记录。")
    else:
        lines.append(_fmt_rows(columns, rows))
        # 短链脚注：pastes 用 id，paste_files 用 paste_id
        key = "id" if spec.table == "pastes" else "paste_id"
        base = settings.app_base_url.rstrip("/") if settings.app_base_url else ""
        if key in columns:
            lines.append("")
            lines.append("短链：" + "  ".join(f"{base}/p/{r[key]}" for r in rows))
    lines.append("")
    lines.append("生成 SQL：")
    lines.append(to_display_sql(spec))
    return "\n".join(lines)
