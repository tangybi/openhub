# agent = llm + tool + while loop 上下文

import inspect
import json
import os, subprocess
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import cast
from pathlib import Path

from openai import OpenAI
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCall,
    ChatCompletionToolParam,
)

from dotenv import load_dotenv
from tavily import TavilyClient

try:
    import readline
    readline.parse_and_bind('set bind-tty-special-chars off')
    readline.parse_and_bind('set input-meta on')
    readline.parse_and_bind('set output-meta on')
    readline.parse_and_bind('set convert-meta off')
except ImportError:
    pass


load_dotenv()
def _get_env_or_exit(name: str) -> str:
    """提前读取环境变量，缺失时提示并终止运行。"""
    value = os.getenv(name)
    if not value:
        raise ValueError(f"未配置 {name}，请检查 .env 文件后重试")
    return value

tavily_api_key = _get_env_or_exit("TAVILY_API_KEY")
api_key = _get_env_or_exit("DEEPSEEK_API_KEY")
WORKDIR = Path.cwd()
SYSTEM = f"You are a coding agent at {WORKDIR}. Use tools to solve tasks. Act, don't explain"

client = OpenAI(
    api_key=api_key,
    base_url="https://api.deepseek.com")

def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"

def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escape workspace: {p}")
    return path

def run_read(path: str, limit: int | None = None) -> str:
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"
def run_write(path: str, content: str) -> str:
    try:
        file_path = safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return f"Written {path}"
    except Exception as e:
        return f"Error: {e}"
def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        file_path = safe_path(path)
        text = file_path.read_text()
        if old_text not in text:
            return f"Error: text not found in {path}"
        file_path.write_text(text.replace(old_text, new_text))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"

def run_glob(pattern: str) -> str:
    import glob as g
    try:
        results = []
        for match in g.glob(pattern, root_dir=WORKDIR):
            if (WORKDIR / match).resolve().is_relative_to(WORKDIR):
                results.append(match)
        return "\n".join(results) if results else "(no matched)"
    except Exception as e:
        return f"Error: {e}"

TOOLS: list[ChatCompletionToolParam] = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace exact text in a file once.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "Find files matching a glob pattern.",
            "parameters": {
                "type": "object",
                "properties": {"pattern": {"type": "string"}},
                "required": ["pattern"],
            },
        },
    },
]
TOOL_HANDLES = {"bash": run_bash, "read_file": run_read, "write_file": run_write, "edit_file": run_edit, "glob": run_glob}

# 允许并行的工具白名单：仅网络/外部 API/纯只读，且无交互确认(input)、不共享可变状态的工具。
# 批内所有工具都在名单里才会走线程池，否则退化为串行。
# 以后加 web_search / get_weather / fetch_url 等网络工具时记得加进这里。
PARALLEL_TOOLS = {"read_file", "glob"}

# 重试守卫：每轮用户提问允许的模型↔工具往返上限。
# 工具失败会回给模型自纠，但模型可能反复生成坏参数无限重试烧 token，
# 超过上限先注入提示要求收敛，仍不收敛则强制终止本轮。
MAX_TOOL_ROUNDS = 6

DENY_LIST = [
    "rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if=", "> /dev/sda",
]
def check_deny_list(command: str) -> str | None:
    for pattern in DENY_LIST:
        if pattern in command:
            return f"Blocked:'{pattern}' is on the deny list "
    return None
PERMISSION_RULES = [
    {
        "tools": ["write_file", "edit_file"],
        "check": lambda args: not (WORKDIR / args.get("path", "")).resolve().is_relative_to(WORKDIR),
        "message": "Writing outside workspace",
    },
    {
        "tools": ["bash"],
        "check": lambda args: any(kw in args.get("command", "") for kw in ["rm ", "> /etc/", "chmod 777"]),
        "message": "Potentially destructive command",
    },
]

def check_rules(tool_name: str, args: dict) -> str | None:
    for rule in PERMISSION_RULES:
        if tool_name in rule["tools"] and rule["check"](args):
            return rule["message"]
    return None
def ask_user(tool_name: str, args: dict, reason: str) -> str:
    print(f"{reason}")
    print(f" Tool: {tool_name}({args})")
    choice = input(" Allow?[y/N]").strip().lower()
    return "allow" if choice in ("y", "yes") else "deny"

def check_permission(block: ChatCompletionMessageToolCall) -> bool:
    name = block.function.name
    try:
        args = json.loads(block.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}
    if name == "bash":
        reason = check_deny_list(args.get("command", ""))
        if reason:
            print(f"\n {reason}")
            return False
    reason = check_rules(name, args)
    if reason:
        decision = ask_user(name, args, reason)
        if decision == "deny":
            return False
    return True

HOOKS = {
    "UserPromptSubmit": [],
    "PreToolUse": [],
    "PostToolUse": [],
    "Stop": [],
}

def register_hook(event: str, callback):
    HOOKS[event].append(callback)

def trigger_hooks(event: str, *args):
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:   # 返回值 ≠ None → hook 说"停"
            return result
    return None

def context_inject_hook(query: str) -> str | None:
    """Inject current working directory info into every prompt."""
    print(f"\033[90m[HOOK] UserPromptSubmit: working in {WORKDIR}\033[0m")
    return None   # return None = no modification, let prompt through

register_hook("UserPromptSubmit", context_inject_hook)

# PreToolUse: 权限检查（s03 的逻辑，从循环移到 hook）
def permission_hook(block):
    # ChatCompletionMessageToolCall 只有 function.name / function.arguments
    name = block.function.name
    args, parse_err = _safe_parse_args(block)
    if parse_err or args is None:
        return None  # 参数解析不了就不做权限判断，错误会由 _run_tool 回给模型
    if name == "bash":
        for pattern in DENY_LIST:
            if pattern in args.get("command", ""):
                return "Permission denied by deny list"
    if name in ("write_file", "edit_file"):
        path = args.get("path", "")
        if not (WORKDIR / path).resolve().is_relative_to(WORKDIR):
            choice = input("   Allow? [y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                return "Permission denied by user"
    return None

# PreToolUse: 日志
def log_hook(block):
    print(f"[HOOK] {block.function.name}(...)")

# PostToolUse: 大文件提醒
def large_output_hook(block, output):
    if len(str(output)) > 100000:
        print(f"[HOOK] ⚠ Large output from {block.function.name}")

register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook)
register_hook("PostToolUse", large_output_hook)

def summary_hook(messages: list) -> str | None:
    """Print a summary when the loop is about to stop."""
    # messages 里混着 dict(用户/tool)和 pydantic 的 ChatCompletionMessage(assistant),
    # 后者没有 .get,不能假设都能 dict 访问;tool 结果是 {"role": "tool", ...} 形状
    tool_count = sum(1 for m in messages
                     if isinstance(m, dict) and m.get("role") == "tool")
    print(f"\033[90m[HOOK] Stop: session used {tool_count} tool calls\033[0m")
    return None   # return None = allow stop, return string = force continuation

register_hook("Stop", summary_hook)


def _safe_parse_args(tool_call: ChatCompletionMessageToolCall) -> tuple[dict | None, str | None]:
    """安全解析模型生成的工具参数。

    Returns:
        (args, None) 解析成功;
        (None, 错误信息) 解析失败,错误信息会作为 tool_result 回给模型让它自纠。
    """
    raw = tool_call.function.arguments or "{}"
    try:
        args = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"参数 JSON 解析失败: {e}  原始: {raw[:100]!r}"
    if not isinstance(args, dict):
        return None, f"参数必须是 JSON 对象,实际是 {type(args).__name__}: {raw[:100]!r}"
    return args, None


def _validate_args(fn, args: dict) -> str | None:
    """按函数签名校验参数,返回错误信息或 None。比裸 TypeError 给模型更清晰的反馈。"""
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return None  # 拿不到签名就跳过,交给运行时兜底
    params = sig.parameters
    # 有 **kwargs 时不再把未知参数当错误
    has_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    if not has_var_kw:
        unknown = set(args) - set(params)
        if unknown:
            return f"未知参数: {', '.join(sorted(unknown))}"
    missing = [
        name for name, p in params.items()
        if p.default is inspect.Parameter.empty
        and name not in args
        and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    ]
    if missing:
        return f"缺少必需参数: {', '.join(missing)}"
    return None


def agent_loop(messages):
    tool_rounds = 0    # 本轮用户提问的工具往返计数
    force_stop = False # 已要求收敛但仍继续调工具 → 下一轮强制终止
    while True:
        # 用户输入后 hook
        trigger_hooks("UserPromptSubmit", messages)
        response = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=messages,
            tools=TOOLS,
            max_tokens=8000,
        )
        messages.append(response.choices[0].message)
        print(response.choices[0].message.content)

        if not response.choices[0].message.tool_calls:
            # 退出前 hook
            force = trigger_hooks("Stop", messages)   # ← 退出之前
            if force:
                # hook returned a message → inject it and continue
                messages.append({"role": "user", "content": force})
                continue
            return messages

        # 重试守卫：模型持续调工具不收敛时兜底
        tool_rounds += 1
        if force_stop:
            print(f"\033[90m[GUARD] 工具调用超 {MAX_TOOL_ROUNDS} 轮仍未收敛,强制终止本轮\033[0m")
            messages.append({"role": "assistant",
                             "content": "⚠️ 已达到工具调用轮次上限,本轮已终止。"})
            return messages
        if tool_rounds > MAX_TOOL_ROUNDS:
            force_stop = True
            print(f"\033[90m[GUARD] 超过 {MAX_TOOL_ROUNDS} 轮,注入提示要求模型收敛\033[0m")
            messages.append({
                "role": "system",
                "content": (f"工具调用已超过 {MAX_TOOL_ROUNDS} 轮仍未收敛。"
                            "请停止调用工具,基于现有信息直接给出最终回答。"),
            })
            continue

        # 工具循环调用（并行执行，按原顺序回填结果）
        tool_calls = response.choices[0].message.tool_calls

        def _run_tool(block) -> dict:
            """执行单个工具调用，返回 role=tool 消息；解析失败/被拒/异常都回给模型自纠。"""
            tool_call = cast(ChatCompletionMessageToolCall, block)
            # 1. 安全解析参数：JSON 坏掉或不是对象不会崩,而是把原因回给模型
            func_args, parse_err = _safe_parse_args(tool_call)
            if parse_err:
                return {"role": "tool", "tool_call_id": block.id,
                        "content": json.dumps({"error": parse_err}, ensure_ascii=False)}
            assert func_args is not None  # parse_err 为 None 时解析必成功,供类型收窄
            # 2. 工具调用前 hook 先检查权限，被拒则把原因回给模型
            blocked = trigger_hooks("PreToolUse", block)
            if blocked:
                return {"role": "tool", "tool_call_id": block.id,
                        "content": str(blocked)}
            # 3. 找工具，并按签名校验参数（缺参/未知参数给出清晰错误）
            fn = TOOL_HANDLES.get(tool_call.function.name)
            if fn is None:
                result = {"error": f"未知工具: {tool_call.function.name}"}
            else:
                sig_err = _validate_args(fn, func_args)
                if sig_err:
                    result = {"error": sig_err}
                else:
                    try:
                        result = fn(**func_args)
                    except Exception as e:
                        result = {"error": f"工具执行失败: {e}"}
            # 4. 工具调用后 hook
            trigger_hooks("PostToolUse", block, result)
            return {"role": "tool", "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str)}

        # 批内工具全部在白名单里才并行，否则串行；结果始终按 tool_calls 顺序回填
        if all(cast(ChatCompletionMessageToolCall, t).function.name in PARALLEL_TOOLS
               for t in tool_calls):
            with ThreadPoolExecutor(max_workers=min(len(tool_calls), 5)) as executor:
                messages.extend(executor.map(_run_tool, tool_calls))
        else:
            messages.extend(_run_tool(b) for b in tool_calls)

if __name__ == "__main__":
    
    user_input = []
    while True:
        user = input().strip()
        if user == "bye":
            break
        user_input.append({
            "role": "user",
            "content": user
        })
        agent_loop(user_input)



