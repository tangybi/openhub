"""看板日志统计：解析 `log/app_YYYYMMDD.log` 聚合 UV / PV / 接口响应时长 / 错误详情。

日志行统一前缀（logger_config 格式）：
    `2026-08-12 09:31:57 | INFO    | app | trace=... span=... | <message>`

message 里 SPAN / 前端SPAN / 前端异常 的字段统一用「空格 + 小写 `key=`」边界分词：
错误体值本身含空格（如 `{"detail":"bad input: {'name': 'x', ...}"}` 的 `', '`），
不能用 `\\S+` 逐字段正则，否则 body 会在第一个空格处被截断。

口径：
- UV = 前端 span 上去重 `device_id`（前端改动后所有 span 都带）；旧日志没有 → 回退业务行去重 `user=`。
- PV = `前端SPAN name=page_view` 条数。
- 响应时长 = 后端 server span 的 `dur`（排除 OPTIONS 与看板自身请求）。
- 错误 = 后端 `http.status_code>=400`（含 request/response body）+ 前端 `前端异常` 行。
- token 用量 = `LLM 用量` / `Embedding 用量` 行（llm.py / embedding.py 上报的 usage）：
  prompt_tokens / completion_tokens 只统计 LLM，embed_tokens 只统计 embedding。
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from ..config import settings

MAX_ERRORS = 50  # 错误详情条数上限（按时间倒序取）

# 行前缀分隔符：`时间 | LEVEL | name | trace= span= | message`
_PREFIX_SEP = " | "

# 边界分词：空格后紧跟「小写字母开头的 key=」即字段边界。值可含空格，
# 只要不含「空格 + 小写 key=」就不会误切（错误体里的 `', '` 后是引号，安全）。
_ATTR_SPLIT = re.compile(r" (?=[a-z][a-z0-9._-]*=)")

# 业务行的 user= 标记（LLM 回答 / 记忆检索 / paste 创建）；空 user（`user= files=1]`）不匹配。
_USER_RE = re.compile(r"user=([^\s\]}\|]+)")


def _message(line: str) -> str:
    """取日志行前缀之后的消息体（找不到分隔符时整行当 message）。"""
    parts = line.split(_PREFIX_SEP, 4)
    return parts[4] if len(parts) == 5 else line


def _line_time(line: str) -> str:
    """日志行前缀里的时间 `YYYY-MM-DD HH:MM:SS`。"""
    return line.split(_PREFIX_SEP, 1)[0]


def _classify(msg: str) -> str:
    """消息体分类：frontend_span / frontend_error / server_span / legacy / outbound / usage / business。"""
    if msg.startswith("前端SPAN "):
        return "frontend_span"
    if msg.startswith("前端异常 "):
        return "frontend_error"
    if msg.startswith("LLM 用量 ") or msg.startswith("Embedding 用量 "):
        return "usage"  # LLM / embedding 的 token 用量（看板聚合）
    if msg.startswith("SPAN "):
        if "asgi.event.type" in msg:
            return "legacy"  # 旧版 ASGI 逐帧噪音子 span，忽略
        if "http.route=" in msg:
            return "server_span"
        return "outbound"  # httpx 的 LLM/embedding 调用（无 http.route），忽略
    return "business"


def _attrs(msg: str) -> dict[str, str]:
    """按边界分词解析 `k=v` 字段（值可含空格）。"""
    out: dict[str, str] = {}
    for tok in _ATTR_SPLIT.split(msg):
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
    return out


def _num(s: str | None) -> float | None:
    """`1.6ms` → 1.6；解析失败返回 None。"""
    if s is None:
        return None
    try:
        return float(s.removesuffix("ms"))
    except ValueError:
        return None


def _int(s: str | None) -> int | None:
    """`123` → 123；解析失败返回 None（token 用量字段）。"""
    if s is None:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    """无统计库的百分位：排序后按 ceil(p*n)-1 取索引。"""
    if not sorted_vals:
        return None
    idx = math.ceil(p * len(sorted_vals)) - 1
    return sorted_vals[idx]


def _each_day(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _daily_files(start: date, end: date) -> list[tuple[date, Path]]:
    """按日取日志文件：主目录 settings.log_dir，缺失的日子回退 CWD/log；同名主目录优先。"""
    dirs = [Path(settings.log_dir)]
    cwd_log = Path.cwd() / "log"
    if cwd_log.resolve() not in {d.resolve() for d in dirs}:
        dirs.append(cwd_log)

    found: dict[date, Path] = {}
    for d in dirs:
        for day in _each_day(start, end):
            if day in found:
                continue
            f = d / f"app_{day:%Y%m%d}.log"
            if f.is_file():
                found[day] = f
    return sorted(found.items(), key=lambda kv: kv[0])


def compute_stats(start: date, end: date, include_errors: bool = True) -> dict:
    """解析 start..end 区间所有日志文件，聚合成 DashboardStats 对应的 dict。"""
    durations: list[float] = []
    by_endpoint: dict[tuple[str, str], list[float]] = defaultdict(list)
    endpoint_errors: dict[tuple[str, str], int] = defaultdict(int)
    total_requests = 0
    backend_errors = 0
    frontend_errors = 0
    devices: set[str] = set()
    users: set[str] = set()
    pv = 0
    ask_count = 0
    errors: list[dict] = []
    llm_calls = 0
    prompt_tokens = 0
    completion_tokens = 0
    embed_tokens = 0

    for _, path in _daily_files(start, end):
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                msg = _message(line)
                kind = _classify(msg)
                t = _line_time(line)

                if kind == "server_span":
                    a = _attrs(msg)
                    method = a.get("http.method", "")
                    route = a.get("http.route", "")
                    # OPTIONS（CORS 预检）与看板自身请求不参与统计
                    if method == "OPTIONS" or route == "/api/dashboard/stats":
                        continue
                    dur = _num(a.get("dur"))
                    status = int(a.get("http.status_code") or 0)
                    if dur is not None:
                        durations.append(dur)
                        by_endpoint[(method, route)].append(dur)
                    total_requests += 1
                    if status >= 400:
                        backend_errors += 1
                        endpoint_errors[(method, route)] += 1
                        if include_errors:
                            errors.append(
                                {
                                    "time": t,
                                    "source": "backend",
                                    "method": method,
                                    "route": route,
                                    "status_code": status,
                                    "span_status": a.get("status", ""),
                                    "request_body": a.get("http.request.body", ""),
                                    "response_body": a.get("http.response.body", ""),
                                    "message": "",
                                    "trace_id": a.get("trace", ""),
                                }
                            )
                elif kind == "frontend_span":
                    a = _attrs(msg)
                    if a.get("device_id"):
                        devices.add(a["device_id"])
                    name = a.get("name", "")
                    if name == "page_view":
                        pv += 1
                    elif name == "ask":
                        ask_count += 1
                elif kind == "frontend_error":
                    frontend_errors += 1
                    if include_errors:
                        a = _attrs(msg)
                        errors.append(
                            {
                                "time": t,
                                "source": "frontend",
                                "method": "",
                                "route": "",
                                "status_code": None,
                                "span_status": "",
                                "request_body": "",
                                "response_body": "",
                                "message": a.get("msg", ""),
                                "trace_id": a.get("trace", ""),
                            }
                        )
                elif kind == "usage":
                    a = _attrs(msg)
                    if msg.startswith("Embedding 用量 "):
                        embed_tokens += _int(a.get("total")) or _int(a.get("prompt")) or 0
                    else:
                        llm_calls += 1
                        prompt_tokens += _int(a.get("prompt")) or 0
                        completion_tokens += _int(a.get("completion")) or 0
                elif kind == "business":
                    for m in _USER_RE.finditer(msg):
                        token = m.group(1)
                        if token and token != "-":
                            users.add(token)

    # UV：device_id 优先，旧日志回退去重 user=
    if devices:
        uv, uv_source = len(devices), "device_id"
    elif users:
        uv, uv_source = len(users), "user_token"
    else:
        uv, uv_source = 0, "none"

    avg = round(sum(durations) / len(durations), 1) if durations else None
    sorted_d = sorted(durations)
    p95 = round(_percentile(sorted_d, 0.95), 1) if sorted_d else None
    mx = round(max(durations), 1) if durations else None
    error_rate = round(backend_errors / total_requests * 100, 1) if total_requests else 0.0

    endpoints: list[dict] = []
    for (method, route), vals in by_endpoint.items():
        sv = sorted(vals)
        endpoints.append(
            {
                "method": method,
                "route": route,
                "count": len(vals),
                "avg_latency_ms": round(sum(vals) / len(vals), 1),
                "p95_latency_ms": round(_percentile(sv, 0.95), 1),
                "max_latency_ms": round(sv[-1], 1),
                "error_count": endpoint_errors[(method, route)],
            }
        )
    endpoints.sort(key=lambda e: (e["p95_latency_ms"] or 0, e["count"]), reverse=True)

    errors.sort(key=lambda e: e["time"], reverse=True)
    errors = errors[:MAX_ERRORS]

    files = _daily_files(start, end)
    return {
        "range": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": (end - start).days + 1,
        },
        "overview": {
            "uv": uv,
            "uv_source": uv_source,
            "user_count": len(users),
            "pv": pv,
            "ask_count": ask_count,
            "total_requests": total_requests,
            "avg_latency_ms": avg,
            "p95_latency_ms": p95,
            "max_latency_ms": mx,
            "error_count": backend_errors + frontend_errors,
            "error_rate": error_rate,
            "llm_calls": llm_calls,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "embed_tokens": embed_tokens,
            "total_tokens": prompt_tokens + completion_tokens + embed_tokens,
        },
        "endpoints": endpoints,
        "errors": errors,
        "files_parsed": [f.name for _, f in files],
        "log_dir": str(files[0][1].parent) if files else str(Path(settings.log_dir)),
    }
