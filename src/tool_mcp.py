# MCP 工具服务器: Tavily(搜索/天气) + Figma(只读)
#
# 给 Claude Code / Claude Desktop 当 stdio MCP server 用:
#   - mcp.run() 走标准输入输出,客户端通过根目录 .mcp.json 拉起本进程
#   - 密钥从根 .env 读取(FIGMA_TOKEN、TAVILY_API_KEY),缺失时报错退出
#
# 依赖(已写入 src/pyproject.toml): mcp<2, httpx, python-dotenv, tavily

import asyncio
import os
import urllib.parse

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from tavily import TavilyClient

load_dotenv()


def _get_env_or_exit(name: str) -> str:
    """提前读取环境变量,缺失时提示并终止运行。"""
    value = os.getenv(name)
    if not value:
        raise ValueError(f"未配置 {name},请检查 .env 文件后重试")
    return value


tavily_api_key = _get_env_or_exit("TAVILY_API_KEY")
figma_token = _get_env_or_exit("FIGMA_TOKEN")

tavily_client = TavilyClient(api_key=tavily_api_key)

# 并发策略: 限制对第三方 API 的同时请求数,避免触发 Tavily / Figma 限流。
# 值按实际额度调: 越大并行越快,越容易撞限流。
_tavily_sem = asyncio.Semaphore(4)
_figma_sem = asyncio.Semaphore(4)

mcp = FastMCP("tool-mcp")


# ---------------------------------------------------------------------------
# Tavily: 网络搜索 + 天气
# ---------------------------------------------------------------------------

@mcp.tool()
async def web_search(
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",
    days: int = 30,
    include_answer: bool = True,
) -> dict:
    """搜索最新的网络信息,返回结构化结果(含答案摘要与来源链接)。

    Args:
        query: 搜索关键词。
        max_results: 返回结果条数,默认 5。
        search_depth: "basic" 或 "advanced",advanced 更准但更慢。
        days: 只返回最近 N 天内的结果,默认 30。
        include_answer: 是否附带 Tavily 生成的答案摘要,默认 True。
    """
    async with _tavily_sem:
        # Tavily 是同步客户端,丢进线程执行,避免阻塞事件循环(阻塞会串行化所有并发调用)
        return await asyncio.to_thread(
            tavily_client.search,
            query=query,
            search_depth=search_depth,
            max_results=max_results,
            include_answer=include_answer,
            days=days,
            sort_by="date",
        )


@mcp.tool()
async def get_weather(location: str, days: int = 7) -> dict:
    """查询指定地点未来一周的天气情况。

    Args:
        location: 地点,例如 "杭州" 或 "San Francisco"。
        days: 查询未来几天的天气,默认 7。
    """
    async with _tavily_sem:
        search_query = f"查询最新{location}未来{days}天的天气"
        return await asyncio.to_thread(
            tavily_client.search,
            query=search_query,
            search_depth="basic",
            max_results=5,
            include_answer=True,
            days=30,
            sort_by="date",
        )


# ---------------------------------------------------------------------------
# Figma: 只读
# ---------------------------------------------------------------------------

FIGMA_API = "https://api.figma.com/v1"


async def _figma_get(path: str) -> dict:
    """GET Figma API,自动带上鉴权头。"""
    headers = {"X-Figma-Token": figma_token}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{FIGMA_API}{path}", headers=headers)
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def get_file(file_key: str) -> dict:
    """读取 Figma 文件(设计稿)的完整结构,含所有页面、节点与样式信息。

    Args:
        file_key: Figma 文件 URL 里斜杠后那串 ID,例如 "abc123DEF"。
    """
    async with _figma_sem:
        return await _figma_get(f"/files/{file_key}")


@mcp.tool()
async def get_file_nodes(file_key: str, node_ids: str) -> dict:
    """读取 Figma 文件中指定节点的子树,只取需要的部分,避免整份文件过大。

    Args:
        file_key: Figma 文件 URL 里的 ID。
        node_ids: 节点 ID,多个用英文逗号分隔,例如 "0:1,0:2"。
    """
    async with _figma_sem:
        encoded = urllib.parse.quote(node_ids, safe=",")
        return await _figma_get(f"/files/{file_key}/nodes?ids={encoded}")


@mcp.tool()
async def get_comments(file_key: str) -> dict:
    """读取 Figma 文件上的评论列表。

    Args:
        file_key: Figma 文件 URL 里的 ID。
    """
    async with _figma_sem:
        return await _figma_get(f"/files/{file_key}/comments")


if __name__ == "__main__":
    mcp.run()
