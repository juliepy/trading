"""
NewsSentimentScanner — 交互式命令行 Demo
用法：python demo.py
"""

from scanner import fetch_news, analyze_sentiment, summarize_sentiments, CN_LABEL

BANNER = """
╔══════════════════════════════════════════════╗
║     中国市场财经新闻情感分析  (GPT-4)        ║
║     NewsSentimentScanner  —  Demo            ║
╚══════════════════════════════════════════════╝
"""

DEFAULT_QUERIES = [
    "A股市场", "上证指数", "科技股",
    "中国经济", "人民币汇率", "新能源", "房地产",
]


def print_article(idx: int, article: dict, polarity: float, sentiment: str) -> None:
    label = CN_LABEL.get(sentiment, sentiment)
    bar = "▲" if sentiment == "Positive" else ("▼" if sentiment == "Negative" else "■")
    print(f"  [{idx:>3}] {bar} {label:2}  分数: {polarity:+.2f}  |  {article['title']}")
    print(f"        来源: {article.get('source', '未知'):6}  发布: {article.get('published', '—')}")
    print(f"        链接: {article['link']}")
    print()


def run_single_query(keyword: str, num: int) -> list:
    """抓取并逐条分析，返回带情感结果的文章列表"""
    print(f"\n正在获取 [{keyword}] 相关新闻（最多 {num} 篇）...\n")
    articles = fetch_news(keyword, num)

    if not articles:
        print("  未获取到任何新闻，请检查网络或更换关键词。\n")
        return []

    results = []
    for idx, article in enumerate(articles, 1):
        polarity, sentiment = analyze_sentiment(article["title"])
        article["_polarity"] = polarity
        article["_sentiment"] = sentiment
        print_article(idx, article, polarity, sentiment)
        results.append(article)

    return results


def run_batch(queries: list, num_per_query: int) -> None:
    """批量搜索多个关键词，最后统一输出各板块情绪分析及总体汇总"""
    bucket: dict[str, list] = {}
    for q in queries:
        articles = run_single_query(q, num_per_query)
        if articles:
            bucket[q] = articles

    if not bucket:
        return

    print("\n" + "═" * 50)
    print("  各板块情绪分析")
    print("═" * 50)
    all_articles = []
    for q, articles in bucket.items():
        print(f"\n── [{q}] ──")
        summarize_sentiments(articles)
        all_articles.extend(articles)

    print("\n" + "═" * 50)
    print("  总体情绪汇总（所有板块合并）")
    print("═" * 50)
    summarize_sentiments(all_articles)


def interactive_menu() -> None:
    print(BANNER)

    while True:
        print("请选择模式：")
        print("  1  输入自定义关键词进行分析")
        print("  2  使用默认关键词批量分析（A股、科技股、新能源等）")
        print("  0  退出")
        choice = input("\n请输入选项 [0/1/2]：").strip()

        if choice == "0":
            print("再见！")
            break

        elif choice == "1":
            keyword = input("请输入搜索关键词（例如：比亚迪、半导体、沪深300）：").strip()
            if not keyword:
                print("关键词不能为空，请重新输入。\n")
                continue
            try:
                num_str = input("获取文章数量（默认 10）：").strip()
                num = int(num_str) if num_str else 10
                num = max(1, min(num, 50))  # 限制 1~50
            except ValueError:
                num = 10

            articles = run_single_query(keyword, num)
            if articles:
                summarize_sentiments(articles)

        elif choice == "2":
            try:
                num_str = input(f"每个关键词获取文章数量（默认 5）：").strip()
                num = int(num_str) if num_str else 5
                num = max(1, min(num, 20))
            except ValueError:
                num = 5

            print(f"\n将搜索以下关键词：{', '.join(DEFAULT_QUERIES)}\n")
            run_batch(DEFAULT_QUERIES, num)

        else:
            print("无效选项，请输入 0、1 或 2。\n")

        print("\n" + "─" * 50 + "\n")


if __name__ == "__main__":
    interactive_menu()
