"""数据源定义：直接抓取原生 RSS 源，无第三方依赖。

按源容错：单个源失败只跳过该源，不影响整体抓取。
新增数据源只需在 DIRECT_FEEDS 里加一条。
"""

from __future__ import annotations

# 原生 RSS 源（直接抓取）
DIRECT_FEEDS: list[dict] = [
    {"name": "少数派", "category": "科技", "url": "https://sspai.com/feed"},
    {"name": "36氪", "category": "科技", "url": "https://36kr.com/feed"},
    {"name": "虎嗅", "category": "科技", "url": "https://www.huxiu.com/rss/0.xml"},
    {"name": "IT之家", "category": "科技", "url": "https://www.ithome.com/rss/"},
    {"name": "cnBeta", "category": "科技", "url": "https://www.cnbeta.com.tw/backend.php"},
    {"name": "FT中文网", "category": "财经", "url": "https://www.ftchinese.com/rss/feed"},
    {"name": "澎湃新闻", "category": "社会", "url": "https://www.thepaper.cn/rss_news"},
    {"name": "BBC中文", "category": "国际", "url": "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml"},
]


def get_feed_targets() -> list[dict]:
    """返回带完整 url 的抓取目标列表（直接 RSS）。"""
    return DIRECT_FEEDS
