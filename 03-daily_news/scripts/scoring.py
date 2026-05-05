"""
A股 Scoring Calculator
======================
实现 scoring.md 中的全套固定评分公式。

Usage
-----
python scoring.py --rsi 48.7 --above-pivot \\
    --available 14 --total 20 \\
    --consistent 10 --verifiable 12 \\
    --gaps 2 --divergences 1 \\
    --macro-bull 1 --commodity-bear 1

Run `python scoring.py --help` for the full argument list.
"""

from __future__ import annotations
import argparse
import sys


# ─────────────────────────────────────────────
# Core formula helpers
# ─────────────────────────────────────────────

def clamp(value: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, value))


def calc_technical_strength(
    above_ma20: bool,
    above_ma50: bool,
    above_ma200: bool,
    rsi: float,
    macd_positive: bool,
    above_pivot: bool,
) -> float:
    """技术结构强度 (0–100, before penalties)."""
    ma_score = (10 if above_ma20 else 0) + (10 if above_ma50 else 0) + (10 if above_ma200 else 0)

    if rsi < 40:
        rsi_score = 8
    elif rsi <= 60:
        rsi_score = 15
    else:
        rsi_score = 25

    macd_score = 25 if macd_positive else 10
    pivot_score = 20 if above_pivot else 8

    return float(ma_score + rsi_score + macd_score + pivot_score)


def calc_risk_appetite(
    breadth_available: bool,
    breadth_score_raw: float,
    etf_change_pct: float,
    news_risk_adj: float,
) -> tuple[float, str]:
    """风险偏好温度 (0–100, before penalties), (label)."""
    if breadth_available:
        base = clamp(breadth_score_raw, 0, 60)
        label = "广度口径"
    else:
        # Map ETF daily % change: -3% → 0, 0% → 20, +3% → 40
        base = clamp(20.0 + (etf_change_pct / 3.0) * 20.0, 0, 40)
        label = "代理口径"

    return clamp(base + news_risk_adj, 0, 100), label


def calc_signal_dim(base: float, bullish: int, bearish: int) -> float:
    """宏观/商品/事件 三项维度 (0–100, before penalties)."""
    return clamp(base + 10 * bullish - 10 * bearish)


def apply_penalties(raw: float, gap_count: int, div_count: int) -> float:
    """缺口与分歧惩罚后的最终分."""
    penalty = min(25, 5 * gap_count) + min(20, 5 * div_count)
    return clamp(raw - penalty)


def calc_composite_env(tech: float, risk: float, macro: float, commodity: float, event: float) -> float:
    """综合环境分."""
    return round(0.30 * tech + 0.20 * risk + 0.20 * macro + 0.15 * commodity + 0.15 * event, 1)


def calc_confidence(
    data_completeness: float,
    source_consistency: float,
    tech_clarity: float,
    event_explain: float,
) -> float:
    """置信度总分."""
    return round(
        0.35 * data_completeness
        + 0.25 * source_consistency
        + 0.25 * tech_clarity
        + 0.15 * event_explain,
        1,
    )


def confidence_level(score: float) -> str:
    if score >= 75:
        return "High"
    elif score >= 55:
        return "Medium"
    return "Low"


# ─────────────────────────────────────────────
# Pretty output
# ─────────────────────────────────────────────

def _bar(score: float, width: int = 20) -> str:
    filled = round(score / 100 * width)
    return "█" * filled + "░" * (width - filled)


def print_results(args: argparse.Namespace) -> None:
    # ── Technical strength ──────────────────
    tech_raw = calc_technical_strength(
        args.above_ma20, args.above_ma50, args.above_ma200,
        args.rsi, args.macd_positive, args.above_pivot,
    )
    tech = apply_penalties(tech_raw, args.gaps, args.divergences)

    # ── Risk appetite ────────────────────────
    risk_raw, risk_label = calc_risk_appetite(
        args.breadth_available, args.breadth_score, args.etf_change, args.news_risk_adj,
    )
    risk = apply_penalties(risk_raw, args.gaps, args.divergences)

    # ── Signal dimensions ────────────────────
    macro_raw = calc_signal_dim(50, args.macro_bull, args.macro_bear)
    macro = apply_penalties(macro_raw, args.gaps, args.divergences)

    commodity_raw = calc_signal_dim(50, args.commodity_bull, args.commodity_bear)
    commodity = apply_penalties(commodity_raw, args.gaps, args.divergences)

    event_raw = calc_signal_dim(50, args.event_bull, args.event_bear)
    event = apply_penalties(event_raw, args.gaps, args.divergences)

    # ── Data quality ─────────────────────────
    data_completeness = round(100 * args.available / args.total) if args.total else 0
    source_consistency = round(100 * args.consistent / args.verifiable) if args.verifiable else 0

    # ── Composite ────────────────────────────
    composite = calc_composite_env(tech, risk, macro, commodity, event)
    tech_clarity = round(0.5 * tech + 0.5 * risk)
    confidence = calc_confidence(data_completeness, source_consistency, tech_clarity, event)
    level = confidence_level(confidence)

    # ── Print ─────────────────────────────────
    sep = "─" * 52

    print(f"\n{'═'*52}")
    print("  A股评分计算器  (scoring.py)")
    print(f"{'═'*52}")

    print(f"\n{sep}")
    print("  评分输入摘要")
    print(sep)
    ma_status = (
        f"{'20✓' if args.above_ma20 else '20✗'}  "
        f"{'50✓' if args.above_ma50 else '50✗'}  "
        f"{'200✓' if args.above_ma200 else '200✗'}"
    )
    print(f"  均线对齐        {ma_status}")
    print(f"  RSI(14)         {args.rsi:.1f}")
    print(f"  MACD 柱体       {'正 ▲' if args.macd_positive else '负 ▼'}")
    print(f"  Pivot 位置      {'价在 Pivot 上方 ✓' if args.above_pivot else '价在 Pivot 下方 ✗'}")
    print(f"  风险偏好口径    {risk_label}")
    print(f"  可用项/应有项   {args.available}/{args.total}")
    print(f"  双源一致/可验   {args.consistent}/{args.verifiable}")
    print(f"  缺口项/分歧项   {args.gaps}/{args.divergences}")

    print(f"\n{sep}")
    print("  影响评分（0–100）")
    print(sep)
    dims = [
        ("技术结构强度", tech),
        ("风险偏好温度", risk),
        ("宏观与流动性支持", macro),
        ("商品与通胀扰动", commodity),
        ("事件冲击可控度", event),
    ]
    for name, score in dims:
        tag = "强" if score >= 70 else ("中性" if score >= 50 else "弱")
        print(f"  {name:<12}  {score:5.1f}  {_bar(score, 16)}  {tag}")
    print(f"  {'─'*48}")
    print(f"  综合环境分       {composite:5.1f}  {_bar(composite, 16)}")

    print(f"\n{sep}")
    print("  置信度分解")
    print(sep)
    conf_dims = [
        ("数据完整性", data_completeness),
        ("多源一致性", source_consistency),
        ("技术信号清晰度", tech_clarity),
        ("事件可解释性", event),
    ]
    for name, score in conf_dims:
        print(f"  {name:<12}  {score:5.1f}  {_bar(score, 16)}")
    print(f"  {'─'*48}")
    print(f"  置信度总分       {confidence:5.1f}  [{level}]")

    # Warn if Low
    if level == "Low":
        print("\n  ⚠ 置信度 Low — 数据严重缺失，请以实盘行情终端数据为准。")

    print(f"\n{'═'*52}\n")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="scoring.py",
        description="A股影响评分与置信度计算器（固定公式，对应 scoring.md）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scoring.py --rsi 48.7 --above-pivot --above-ma20 \\
      --available 14 --total 20 \\
      --consistent 10 --verifiable 12 \\
      --gaps 2 --divergences 1 \\
      --macro-bull 1 --commodity-bear 2
        """,
    )

    tech = p.add_argument_group("技术面输入")
    tech.add_argument("--above-ma20", action="store_true", help="收盘价在 20MA 上方")
    tech.add_argument("--above-ma50", action="store_true", help="收盘价在 50MA 上方")
    tech.add_argument("--above-ma200", action="store_true", help="收盘价在 200MA 上方")
    tech.add_argument("--rsi", type=float, required=True, help="RSI(14) 数值")
    tech.add_argument("--macd-positive", action="store_true", help="MACD 柱体 > 0")
    tech.add_argument("--above-pivot", action="store_true", help="收盘价 >= Pivot")

    risk = p.add_argument_group("风险偏好输入")
    risk.add_argument("--breadth-available", action="store_true", help="广度数据可得")
    risk.add_argument("--breadth-score", type=float, default=30.0,
                      help="广度原始分 0–60（breadth-available 为 True 时使用）")
    risk.add_argument("--etf-change", type=float, default=0.0,
                      help="300ETF 日涨跌 %% （breadth-available 为 False 时使用）")
    risk.add_argument("--news-risk-adj", type=float, default=0.0,
                      help="新闻风险修正 -20 到 +20")

    signals = p.add_argument_group("宏观/商品/事件证据计数")
    signals.add_argument("--macro-bull", type=int, default=0, help="宏观正向证据数")
    signals.add_argument("--macro-bear", type=int, default=0, help="宏观负向证据数")
    signals.add_argument("--commodity-bull", type=int, default=0, help="商品正向证据数")
    signals.add_argument("--commodity-bear", type=int, default=0, help="商品负向证据数")
    signals.add_argument("--event-bull", type=int, default=0, help="事件正向证据数（可控）")
    signals.add_argument("--event-bear", type=int, default=0, help="事件负向证据数（不可控）")

    data = p.add_argument_group("数据质量")
    data.add_argument("--available", type=int, required=True, help="可用数据项数量")
    data.add_argument("--total", type=int, required=True, help="应有数据项总数")
    data.add_argument("--consistent", type=int, required=True, help="双源一致项数量")
    data.add_argument("--verifiable", type=int, required=True, help="可校验（双源）项数量")
    data.add_argument("--gaps", type=int, default=0, help="关键缺口项数")
    data.add_argument("--divergences", type=int, default=0, help="明显分歧项数")

    return p


if __name__ == "__main__":
    parser = build_parser()
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)
    print_results(parser.parse_args())
