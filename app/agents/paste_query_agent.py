"""粘贴查询 Agent：把自然语言问题转成结构化查询意图，查 pastes / paste_files 元数据并返回结果。

安全：LLM 只输出查询意图（表/字段/筛选/排序/limit），不输出 SQL；
后端在 services/paste_query.py 用白名单列 + 参数绑定构建查询并只读执行。
正文对象在 R2 不在数据库 —— 只能查元数据（标题/语言/浏览数/过期时间/附件名/大小等）。
支持拼接完整的能访问的短链接，需要根据content_type，文本形式如：https://{R2_PUBLIC_BASE_URL}/{R2_BUCKET}/{id}/content，附件形式：https://{R2_PUBLIC_BASE_URL}/{R2_BUCKET}/{id}/file

不覆写 ask_stream：走 base.Agent 默认包装（先 sources 再整段 delta），查询为单次 DB 往返。
"""

from __future__ import annotations

from ..config import settings
from ..logger_config import get_logger
from ..services import paste_query as pq
from ..services.llm import LLMError, chat_json
from .base import Agent

logger = get_logger()

_SCHEMA_PROMPT = """你是粘贴库查询助手。用户会提出关于已保存粘贴的问题，你需要把问题转成结构化查询意图（不是 SQL）。

可查的两张表（只含元数据，正文不在数据库里）：

1. pastes —— 粘贴本体元数据
   - id: 短码（字符串，主键，形如 aB3x9K）
   - title: 标题（字符串）
   - language: 代码语言（字符串，可为空）
   - view_count: 浏览次数（整数）
   - expires_at: 过期时间（ISO 时间字符串，可为空；null = 永不过期）
   - created_at: 创建时间（ISO 时间字符串）

2. paste_files —— 粘贴的附件
   - id: 附件 id（整数）
   - paste_id: 所属粘贴的短码（字符串）
   - name: 文件名（字符串）
   - content_type: 文件类型（字符串，如 image/png）
   - size: 文件大小字节数（整数）
   - created_at: 创建时间（ISO 时间字符串）

可用的筛选操作符（op），按字段类型：
- 字符串字段：eq / neq / contains（包含）/ starts_with / ends_with
- 整数字段：eq / neq / gt（大于）/ gte（大于等于）/ lt / lte
- 时间字段：gt / gte / lt / lte
- 任意字段：is_null（value 为 true = 查为空，false = 查非空；「永不过期」即 expires_at is_null true）

输出要求：只输出一个 JSON 对象，不要多余文字。格式：
{
  "queryable": true 或 false（问题与粘贴库有关就 true；无关如天气/新闻就 false）,
  "table": "pastes 或 paste_files",
  "fields": ["要返回的字段名列表，默认给全部可读字段"],
  "filters": [{"column": "字段名", "op": "操作符", "value": 值}, ...],
  "order_by": {"column": "排序字段", "direction": "asc 或 desc"},
  "limit": 整数（默认 20，最大 50）,
  "note": "用一句话复述你对问题的理解"
}

规则：
- 只能查上面列出的字段，不能虚构字段。
- 值直接用字面量（数字/字符串/布尔），字符串如 "python"、时间如 "2026-01-01"。
- 例：「标题含 python 的粘贴」→ table=pastes, filters=[{"column":"title","op":"contains","value":"python"}], order_by={"column":"created_at","direction":"desc"}
- 例：「浏览量超过 100 的」→ pastes, filters=[{"column":"view_count","op":"gt","value":100}]
- 例：「永不过期的」→ pastes, filters=[{"column":"expires_at","op":"is_null","value":true}]
- 例：「超过 1MB 的附件」→ paste_files, filters=[{"column":"size","op":"gte","value":1048576}]
"""


class PasteQueryAgent(Agent):
    name = "paste"
    label = "粘贴查询"
    category = "查询"
    description = "用自然语言查询已保存的粘贴（标题/语言/浏览量/过期时间/附件等元数据）"

    async def ask(self, question: str, *, user_id: str = "", session_id: str = "") -> dict:
        if not settings.deepseek_api_key:
            return {
                "answer": "粘贴查询需要 DEEPSEEK_API_KEY 才能工作，请先配置。",
                "sources": [],
            }

        try:
            raw = await chat_json(
                [
                    {"role": "system", "content": _SCHEMA_PROMPT},
                    {"role": "user", "content": question},
                ],
                temperature=0.2,
                user_id=user_id,
                session_id=session_id,
            )
        except LLMError as e:
            logger.warning("粘贴查询 LLM 调用失败：%s", e)
            return {
                "answer": "抱歉，暂时没能理解这个问题，请换个问法再试一次。",
                "sources": [],
            }

        try:
            spec = pq.validate_spec(raw)
        except pq.InvalidQuery as e:
            return {"answer": str(e), "sources": []}

        try:
            columns, rows = await pq.run_query(spec)
        except RuntimeError as e:  # DATABASE_URL 未配置
            logger.warning("粘贴查询数据库未配置：%s", e)
            return {
                "answer": "数据库未配置，无法查询粘贴库。请先配置 DATABASE_URL。",
                "sources": [],
            }
        except Exception:
            logger.exception("粘贴查询执行失败")
            return {"answer": "查询执行失败，请换个问法再试。", "sources": []}

        answer = pq.format_answer(spec, columns, rows, spec.note)
        return {"answer": answer, "sources": []}
