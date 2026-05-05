"""
scanner/sentiment.py
情感分析模块 — 使用 GPT-4.1 分析中文财经新闻对 A 股市场的情感倾向
"""

import json
import re

from .ai_client import client, model

CN_LABEL = {"Positive": "正面", "Negative": "负面", "Neutral": "中性"}


def analyze_sentiment(text: str) -> tuple:
    """调用 LLM 分析单条新闻标题，返回 (score, sentiment)"""
    if not text or not text.strip():
        return 0.0, "Neutral"

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是专业的中国股市情感分析师。"
                        "分析以下财经新闻对 A 股市场的情感倾向，"
                        "仅返回 JSON（不要有其他文字）："
                        '{"sentiment": "正面/负面/中性", "score": 浮点数, "reason": "简短理由"}'
                        "score 范围：-1.0（极度负面）到 1.0（极度正面）。"
                    ),
                },
                {"role": "user", "content": f"新闻：{text}"},
            ],
            temperature=0.1,
            max_tokens=150,
        )
        raw = response.choices[0].message.content.strip()
        json_match = re.search(r"\{.*?\}", raw, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            score = float(result.get("score", 0.0))
            cn_to_en = {"正面": "Positive", "负面": "Negative", "中性": "Neutral"}
            sentiment = cn_to_en.get(result.get("sentiment", "中性"), "Neutral")
            return score, sentiment
    except Exception as exc:
        print(f"[LLM] 分析失败: {exc}")

    return 0.0, "Neutral"


def summarize_sentiments(articles: list) -> None:
    """汇总所有文章的情感分布并打印报告"""
    summary = {"Positive": 0, "Negative": 0, "Neutral": 0}
    for article in articles:
        _, sentiment = analyze_sentiment(article["title"])
        summary[sentiment] += 1

    total = len(articles)
    print("\n--- 市场情绪汇总 ---")
    print(f"分析文章总数: {total}")
    for sentiment, count in summary.items():
        percent = (count / total * 100) if total > 0 else 0
        print(f"{CN_LABEL[sentiment]}: {count} 篇 ({percent:.2f}%)")
