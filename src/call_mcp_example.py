# MCP 客户端示例: 连接 src/tool_mcp.py 服务器,列工具并调用
#
# 用法:
#   src/.venv/bin/python src/call_mcp_example.py                  # 演示 web_search + get_weather
#   src/.venv/bin/python src/call_mcp_example.py "大模型新闻"      # 自定义搜索词
#   src/.venv/bin/python src/call_mcp_example.py --figma-key abc123DEF  # 附带演示 Figma get_file
#
# 原理: 客户端通过 stdio 拉起服务器子进程,JSON-RPC 握手后即可 tools/call。
# 服务器自己的密钥从根 .env 读取,客户端不需要 key。

import argparse
import asyncio
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_PY = os.path.join(SRC_DIR, "tool_mcp.py")
PYTHON = os.path.join(SRC_DIR, ".venv", "bin", "python")


def server_params() -> StdioServerParameters:
    """拉起 src/.venv 里的 python 去跑服务器脚本。"""
    return StdioServerParameters(command=PYTHON, args=[SERVER_PY])


async def list_tools(session: ClientSession) -> None:
    tools = await session.list_tools()
    print(f"共 {len(tools.tools)} 个工具:")
    for t in tools.tools:
        desc = (t.description or "").splitlines()[0]
        print(f"  - {t.name}: {desc}")


async def call(session: ClientSession, name: str, args: dict) -> None:
    print(f"\n>>> 调用 {name}({args})")
    result = await session.call_tool(name, args)
    for block in result.content:
        if block.type == "text":
            print(block.text[:800])
    if result.isError:
        print("!! 工具返回错误,请检查参数或密钥")


async def main() -> None:
    parser = argparse.ArgumentParser(description="调用 tool-mcp 服务器的示例客户端")
    parser.add_argument("query", nargs="?", default="2026年大模型最新进展", help="搜索词")
    parser.add_argument("--location", default="杭州", help="天气查询地点")
    parser.add_argument("--figma-key", default=None, help="Figma 文件 key,提供则顺带演示 get_file")
    args = parser.parse_args()

    async with stdio_client(server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await list_tools(session)

            await call(session, "web_search", {"query": args.query, "max_results": 3})
            await call(session, "get_weather", {"location": args.location, "days": 3})

            if args.figma_key:
                await call(session, "get_file", {"file_key": args.figma_key})


if __name__ == "__main__":
    asyncio.run(main())
