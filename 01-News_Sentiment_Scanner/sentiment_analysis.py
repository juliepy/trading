"""
sentiment_analysis.py
东方证券（600958）行情 + 新闻情感分析
"""

from scanner import fetch_news, fetch_stock_quote, analyze_sentiment, summarize_sentiments, CN_LABEL

STOCK_CODE = "002230"
STOCK_NAME = "科大讯飞"
NUM_ARTICLES = 15


def print_quote(quote: dict) -> None:
    if not quote:
        print("  [行情] 暂未获取到数据\n")
        return
    pct = quote.get("pct", 0)
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "—")
    print(f"  代码: {quote.get('code')}  名称: {quote.get('name')}")
    print(f"  最新价: {quote.get('last')}  {arrow} {pct}%  涨跌额: {quote.get('chg')}")
    print(f"  今开: {quote.get('open')}  最高: {quote.get('high')}  最低: {quote.get('low')}  昨收: {quote.get('prev_close')}")
    print(f"  成交量: {quote.get('volume')}  换手率: {quote.get('turnover')}%  市盈率(TTM): {quote.get('pe_ttm')}")
    print()


def main():
    # ── 1. 实时行情 ─────────────────────────────────────────────────────
    print(f"{'─'*55}")
    print(f"  {STOCK_NAME}（{STOCK_CODE}）实时行情")
    print(f"{'─'*55}")
    quote = fetch_stock_quote(STOCK_CODE)
    print_quote(quote)

    # ── 2. 新闻抓取 ─────────────────────────────────────────────────────
    print(f"{'─'*55}")
    print(f"  正在获取 [{STOCK_NAME}] 相关新闻（最多 {NUM_ARTICLES} 篇）...")
    print(f"{'─'*55}\n")
    articles = fetch_news(STOCK_NAME, NUM_ARTICLES)

    if not articles:
        print("  未获取到任何新闻，请检查网络连接。")
        return

    # ── 3. 逐条情感分析 ──────────────────────────────────────────────────
    for idx, article in enumerate(articles, 1):
        polarity, sentiment = analyze_sentiment(article["title"])
        arrow = "▲" if sentiment == "Positive" else ("▼" if sentiment == "Negative" else "■")
        print(f"[{idx:>2}] {arrow} {CN_LABEL[sentiment]:2}  分数: {polarity:+.2f}")
        print(f"      {article['title']}")
        print(f"      来源: {article.get('source', '未知')}  发布: {article.get('published', '—')}")
        print(f"      链接: {article.get('link', '')}")
        print()

    # ── 4. 情绪汇总 ──────────────────────────────────────────────────────
    summarize_sentiments(articles)


if __name__ == "__main__":
    main()
