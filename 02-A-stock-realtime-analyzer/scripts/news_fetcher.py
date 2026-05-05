"""
scripts/news_fetcher.py
新闻抓取模块 — 从东方财富获取中文财经新闻；
           支持按关键词搜索及按股票代码抓取个股新闻

依赖 curl_cffi 模拟 Chrome TLS 指纹，绕过反爬检测。
"""

import json
import re
import time
import urllib.parse
from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup


def _strip_html(text: str) -> str:
    return BeautifulSoup(text, "html.parser").get_text()


CHROME = "chrome120"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


# ---------------------------------------------------------------------------
# 东方财富关键词搜索新闻（模拟 Chrome TLS 指纹）
# ---------------------------------------------------------------------------
def fetch_news_eastmoney(keyword: str, num_articles: int = 10) -> list:
    """从东方财富搜索财经新闻（curl_cffi 模拟 Chrome）"""
    articles = []
    try:
        param_data = {
            "uid": "",
            "keyword": keyword,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {
                "cmsArticleWebOld": {
                    "from": 0,
                    "size": num_articles,
                    "oneImageFlow": True,
                }
            },
        }
        params = {
            "param": json.dumps(param_data, ensure_ascii=False),
            "cb": "cb",
            "_": str(int(time.time() * 1000)),
        }
        resp = cffi_requests.get(
            "https://search-api-web.eastmoney.com/search/jsonp",
            params=params,
            headers={**HEADERS, "Referer": "https://www.eastmoney.com/"},
            timeout=10,
            impersonate=CHROME,
        )
        resp.encoding = "utf-8"
        match = re.search(r"\((.+)\)\s*$", resp.text, re.DOTALL)
        if match:
            data = json.loads(match.group(1))
            raw = data.get("result", {}).get("cmsArticleWebOld", [])
            if isinstance(raw, list):
                items = raw
            elif isinstance(raw, dict):
                items = raw.get("data", [])
            else:
                items = []
            for item in items:
                articles.append({
                    "title": _strip_html(item.get("title", "")),
                    "link": item.get("url", ""),
                    "published": item.get("date", ""),
                    "source": "东方财富",
                    "content": _strip_html(item.get("digest", "")),
                })
    except Exception as exc:
        print(f"[东方财富] 获取失败: {exc}")
    return articles


# ---------------------------------------------------------------------------
# 东方财富个股专属新闻（以股票代码为关键词）
# ---------------------------------------------------------------------------
def fetch_stock_news_eastmoney(code6: str, num_articles: int = 10) -> list:
    """从东方财富关键词搜索接口抓取个股新闻"""
    return fetch_news_eastmoney(code6, num_articles)


def fetch_news(keyword: str, num_articles: int = 10) -> list:
    """统一入口：先用关键词搜索，不足时补充个股专属新闻（若 keyword 为6位代码）"""
    articles = fetch_news_eastmoney(keyword, num_articles)
    if len(articles) < num_articles and re.fullmatch(r"\d{6}", keyword.strip()):
        extra = fetch_stock_news_eastmoney(keyword.strip(), num_articles - len(articles))
        articles += extra
    return articles[:num_articles]
