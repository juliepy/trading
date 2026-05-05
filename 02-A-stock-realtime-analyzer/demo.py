#!/usr/bin/env python3
"""
A股数据采集 & AI深度分析工具 — 交互式统一入口
用法：python demo.py
"""

import datetime as dt
import json
import os
import sys
from pathlib import Path

# 自动加载 .env 文件
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# Allow importing from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))

from a_share_snapshot import fetch_index_baseline, fetch_kline, fetch_quotes, parse_codes, search_stock_by_name

BANNER = """
╔══════════════════════════════════════════════════╗
║   A股数据采集 & AI深度分析工具                   ║
║   A-Share Snapshot + GPT-4.1 Analyst  —  Demo   ║
╚══════════════════════════════════════════════════╝
"""


# ─────────────────────────────────────────────────────────────
# 行情快照打印
# ─────────────────────────────────────────────────────────────

def print_quote(q: dict) -> None:
    pct = q.get("pct", 0) or 0
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "—")
    print(f"  [{q.get('code')}] {q.get('name')}  "
          f"最新: {q.get('last')}  {arrow} {pct}%  涨跌额: {q.get('chg')}")
    print(f"  今开: {q.get('open')}  最高: {q.get('high')}  "
          f"最低: {q.get('low')}  昨收: {q.get('prev_close')}")
    print(f"  成交量: {q.get('volume')}  换手率: {q.get('turnover')}%  "
          f"量比: {q.get('volume_ratio')}  PE(TTM): {q.get('pe_ttm')}")
    print()


def print_kline_metrics(code: str, km: dict) -> None:
    m = km.get("metrics", {})
    print(f"  [{code}] K线指标  ({m.get('latest_date', '—')})")
    print(f"  收盘: {m.get('close')}  "
          f"MA5: {m.get('ma5')}  MA10: {m.get('ma10')}  MA20: {m.get('ma20')}")
    print(f"  5d回报: {m.get('ret_5d_pct')}%  "
          f"10d回报: {m.get('ret_10d_pct')}%  "
          f"20d回报: {m.get('ret_20d_pct')}%")
    print(f"  10日高: {m.get('high_10d')}  10日低: {m.get('low_10d')}")
    print()


def print_index(idx: dict) -> None:
    pct = idx.get("pct", 0) or 0
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "—")
    up = idx.get("up_count", "—")
    down = idx.get("down_count", "—")
    print(f"  [{idx.get('code')}] {idx.get('name')}  "
          f"{idx.get('last')}  {arrow} {pct}%  ↑{up} ↓{down}")


# ─────────────────────────────────────────────────────────────
# 输入辅助
# ─────────────────────────────────────────────────────────────

def _resolve_token(token: str):
    """将单个输入（代码或名称）解析为 6 位股票代码，失败返回 None"""
    import re as _re
    # 尝试直接解析为代码
    try:
        from a_share_snapshot import normalize_code
        return normalize_code(token)
    except ValueError:
        pass
    # 含中文或字母 → 当作名称搜索
    results = search_stock_by_name(token)
    if not results:
        print(f"  未找到 [{token}] 相关股票，请检查名称或代码。")
        return None
    if len(results) == 1:
        code, name = results[0]
        print(f"  [{token}] → {code} {name}")
        return code
    # 多个结果，让用户选择
    print(f"  找到以下相关股票，请选择：")
    for i, (code, name) in enumerate(results, 1):
        print(f"    {i}.  {code}  {name}")
    while True:
        sel = input(f"  请输入序号 [1-{len(results)}]：").strip()
        if sel.isdigit() and 1 <= int(sel) <= len(results):
            code, name = results[int(sel) - 1]
            print(f"  已选择：{code} {name}")
            return code
        print("  无效序号，请重新输入。")


def ask_codes() -> list:
    while True:
        raw = input("请输入股票代码或名称（逗号/空格分隔，例如 000001,比亚迪）：").strip()
        if not raw:
            print("  不能为空，请重新输入。\n")
            continue
        import re as _re
        tokens = [t for t in _re.split(r"[,，\s]+", raw) if t]
        codes = []
        for tok in tokens:
            code = _resolve_token(tok)
            if code and code not in codes:
                codes.append(code)
        if codes:
            print(f"  已解析代码：{', '.join(codes)}\n")
            return codes
        print("  未能解析任何有效代码，请重新输入。\n")


def ask_bool(prompt: str, default: bool = False) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    val = input(f"{prompt} {hint}：").strip().lower()
    if not val:
        return default
    return val in ("y", "yes", "1")


def ask_int(prompt: str, default: int, lo: int, hi: int) -> int:
    val = input(f"{prompt}（{lo}~{hi}，默认 {default}）：").strip()
    if not val:
        return default
    try:
        n = int(val)
        return max(lo, min(hi, n))
    except ValueError:
        return default


# ─────────────────────────────────────────────────────────────
# 模式 1 — 仅抓取数据快照
# ─────────────────────────────────────────────────────────────

def run_snapshot() -> None:
    print("\n── 模式 1：行情数据快照 ──\n")
    codes = ask_codes()
    with_indices = ask_bool("是否包含大盘指数（上证/深成/创业板）？", default=True)
    with_kline = ask_bool("是否包含日K线及均线指标？", default=False)
    kline_days = 60
    if with_kline:
        kline_days = ask_int("K线回望天数", default=60, lo=10, hi=250)

    print("\n正在抓取行情数据...\n")
    result = {
        "timestamp": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "codes": codes,
        "quotes": fetch_quotes(codes),
    }

    print(f"{'─'*52}")
    print(f"  实时行情  {result['timestamp']}")
    print(f"{'─'*52}\n")
    for q in result["quotes"]:
        print_quote(q)

    if with_indices:
        result["indices"] = fetch_index_baseline()
        print(f"{'─'*52}")
        print("  大盘指数")
        print(f"{'─'*52}")
        for idx in result["indices"]:
            print_index(idx)
        print()

    if with_kline:
        kline = {}
        print(f"{'─'*52}")
        print(f"  K线指标（近 {kline_days} 日）")
        print(f"{'─'*52}\n")
        for c in codes:
            try:
                kd = fetch_kline(c, days=kline_days)
                kline[c] = kd
                print_kline_metrics(c, kd)
            except Exception as e:
                print(f"  [{c}] K线抓取失败：{e}\n")
                kline[c] = {"error": str(e)}
        result["kline"] = kline

    save = ask_bool("是否将结果保存为 JSON 文件？", default=False)
    if save:
        fname = f"snapshot_{'_'.join(codes)}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n  已保存至：{fname}\n")


# ─────────────────────────────────────────────────────────────
# 模式 3 — 快照 JSON 可视化图表
# ─────────────────────────────────────────────────────────────

def _ma_series(closes, n):
    result = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        result[i] = sum(closes[i - n + 1 : i + 1]) / n
    return result


def plot_snapshot_file(filepath: str) -> None:
    try:
        import matplotlib
        matplotlib.rcParams["font.family"] = ["WenQuanYi Micro Hei", "SimHei",
                                               "Noto Sans CJK SC", "DejaVu Sans"]
        matplotlib.rcParams["axes.unicode_minus"] = False
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        from matplotlib.gridspec import GridSpec
    except ImportError:
        print("  [错误] 请先安装 matplotlib：pip install matplotlib\n")
        return

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    kline_data = data.get("kline", {})
    if not kline_data:
        print("  快照中无 K线数据，请重新生成含 K线的快照。\n")
        return

    for code, kd in kline_data.items():
        if "error" in kd:
            print(f"  [{code}] K线数据异常：{kd['error']}\n")
            continue

        klines = kd.get("klines", [])
        if not klines:
            continue

        # 找到对应 quote
        quote = next((q for q in data.get("quotes", []) if q["code"] == code), {})
        name = quote.get("name", code)

        dates   = [k["date"] for k in klines]
        opens   = [k["open"] for k in klines]
        closes  = [k["close"] for k in klines]
        highs   = [k["high"] for k in klines]
        lows    = [k["low"] for k in klines]
        vols    = [k["volume"] for k in klines]
        xs      = list(range(len(dates)))

        ma5  = _ma_series(closes, 5)
        ma10 = _ma_series(closes, 10)
        ma20 = _ma_series(closes, 20)

        fig = plt.figure(figsize=(14, 8))
        fig.patch.set_facecolor("#0d1117")
        gs = GridSpec(3, 1, figure=fig, height_ratios=[3, 1, 1], hspace=0.08)

        ax1 = fig.add_subplot(gs[0])   # 蜡烛图 + MA
        ax2 = fig.add_subplot(gs[1], sharex=ax1)  # 成交量
        ax3 = fig.add_subplot(gs[2])   # 大盘指数摘要（文字）

        for ax in [ax1, ax2]:
            ax.set_facecolor("#0d1117")
            ax.tick_params(colors="#aaaaaa", labelsize=8)
            ax.spines[:].set_color("#333333")

        # ── 蜡烛图
        for i, x in enumerate(xs):
            o, c, h, l = opens[i], closes[i], highs[i], lows[i]
            color = "#ef5350" if c >= o else "#26a69a"
            ax1.plot([x, x], [l, h], color=color, linewidth=0.8)
            ax1.bar(x, abs(c - o) or 0.01, bottom=min(o, c),
                    color=color, width=0.6, linewidth=0)

        # ── MA 线
        def _plot_ma(ax, series, color, label):
            xs_valid = [i for i, v in enumerate(series) if v is not None]
            ys_valid = [v for v in series if v is not None]
            if xs_valid:
                ax.plot(xs_valid, ys_valid, color=color, linewidth=1, label=label)

        _plot_ma(ax1, ma5,  "#ffd700", "MA5")
        _plot_ma(ax1, ma10, "#ff9800", "MA10")
        _plot_ma(ax1, ma20, "#e040fb", "MA20")

        ax1.legend(framealpha=0, labelcolor="white", fontsize=8, loc="upper left")
        ax1.set_title(f"{name}（{code}）  K线走势  {dates[0]} ~ {dates[-1]}",
                      color="white", fontsize=12, pad=8)
        ax1.set_ylabel("价格（元）", color="#aaaaaa", fontsize=8)
        ax1.yaxis.tick_right()
        ax1.yaxis.set_label_position("right")
        ax1.tick_params(labelbottom=False)

        # 当前价格标注
        last_close = closes[-1]
        ax1.axhline(last_close, color="#ffffff", linewidth=0.5, linestyle="--", alpha=0.4)
        ax1.annotate(f" {last_close}", xy=(xs[-1], last_close),
                     color="white", fontsize=8, va="center")

        # ── 成交量
        for i, x in enumerate(xs):
            color = "#ef5350" if closes[i] >= opens[i] else "#26a69a"
            ax2.bar(x, vols[i], color=color, width=0.6, linewidth=0)
        ax2.set_ylabel("成交量（手）", color="#aaaaaa", fontsize=7)
        ax2.yaxis.tick_right()
        ax2.yaxis.set_label_position("right")
        ax2.tick_params(labelbottom=False)
        ax2.set_facecolor("#0d1117")

        # X 轴日期刻度（每 10 个点显示一个）
        tick_step = max(1, len(xs) // 10)
        ax2.set_xticks(xs[::tick_step])
        ax2.set_xticklabels([dates[i] for i in range(0, len(dates), tick_step)],
                            rotation=30, ha="right", color="#aaaaaa", fontsize=7)
        ax2.tick_params(labelbottom=True)

        # ── 大盘 + 个股摘要
        ax3.set_facecolor("#0d1117")
        ax3.axis("off")
        m = kd.get("metrics", {})
        pct = quote.get("pct", 0) or 0
        arrow = "▲" if pct > 0 else "▼"
        color_pct = "#ef5350" if pct > 0 else "#26a69a"

        lines = [
            f"{name}  最新: {last_close}  {arrow} {pct}%  "
            f"MA5:{m.get('ma5')}  MA10:{m.get('ma10')}  MA20:{m.get('ma20')}  "
            f"5d:{m.get('ret_5d_pct')}%  10d:{m.get('ret_10d_pct')}%  20d:{m.get('ret_20d_pct')}%"
        ]
        indices = data.get("indices", [])
        if indices:
            idx_strs = []
            for idx in indices:
                ip = idx.get("pct", 0) or 0
                ia = "▲" if ip > 0 else "▼"
                idx_strs.append(f"{idx['name']} {idx['last']} {ia}{ip}%  "
                                f"↑{idx.get('up_count','?')} ↓{idx.get('down_count','?')}")
            lines.append("  |  ".join(idx_strs))

        ax3.text(0.01, 0.7, lines[0], transform=ax3.transAxes,
                 color=color_pct, fontsize=8.5, va="top")
        if len(lines) > 1:
            ax3.text(0.01, 0.2, lines[1], transform=ax3.transAxes,
                     color="#aaaaaa", fontsize=8, va="top")

        plt.tight_layout()
        out = f"chart_{code}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        plt.savefig(out, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
        print(f"  图表已保存：{out}")
        plt.show()
        plt.close()


def run_visualize() -> None:
    print("\n── 模式 3：快照 JSON 可视化图表 ──\n")
    import glob
    snapshots = sorted(glob.glob("snapshot_*.json"), reverse=True)
    if snapshots:
        print("  检测到以下快照文件：")
        for i, f in enumerate(snapshots[:10], 1):
            print(f"    {i}.  {f}")
        sel = input("  请输入序号或直接输入文件路径（回车选第1个）：").strip()
        if not sel:
            filepath = snapshots[0]
        elif sel.isdigit() and 1 <= int(sel) <= len(snapshots):
            filepath = snapshots[int(sel) - 1]
        else:
            filepath = sel
    else:
        filepath = input("  请输入快照 JSON 文件路径：").strip()

    if not filepath or not os.path.exists(filepath):
        print(f"  文件不存在：{filepath}\n")
        return

    plot_snapshot_file(filepath)




def run_ai_analysis() -> None:
    print("\n── 模式 2：GPT-4.1 深度分析报告 ──\n")

    # 延迟导入，避免未安装 openai 时崩溃
    try:
        from llm_analyst import run_analysis
    except ImportError as e:
        print(f"  [错误] 无法导入分析模块：{e}")
        print("  请先运行：pip install openai\n")
        return

    if not (os.environ.get("CI_TOKEN") or os.environ.get("OPENAI_API_KEY")):
        print("  [错误] 未设置 API Key。")
        print("  请先执行：export CI_TOKEN='eyJ...'  或  export OPENAI_API_KEY='sk-...'\n")
        return

    codes = ask_codes()
    with_indices = ask_bool("是否包含大盘指数宽度数据？", default=True)
    with_kline = ask_bool("是否包含日K线及均线指标？", default=True)
    kline_days = 60
    if with_kline:
        kline_days = ask_int("K线回望天数", default=60, lo=10, hi=250)
    stream = ask_bool("是否启用流式输出（逐 token 打印）？", default=True)

    print(f"\n{'═'*52}")
    print("  正在生成 GPT-4.1 深度分析报告...")
    print(f"{'═'*52}\n")

    run_analysis(
        codes=codes,
        with_kline=with_kline,
        kline_days=kline_days,
        with_indices=with_indices,
        stream=stream,
    )


# ─────────────────────────────────────────────────────────────
# 主菜单
# ─────────────────────────────────────────────────────────────

def interactive_menu() -> None:
    print(BANNER)

    while True:
        print("请选择模式：")
        print("  1  行情数据快照（实时行情 + K线，输出结构化数据，无需 API Key）")
        print("  2  GPT-4.1 深度分析报告（调用 LLM，需要 API Key）")
        print("  3  快照 JSON 可视化图表（K线 + MA + 成交量 + 大盘，需要 matplotlib）")
        print("  0  退出")
        choice = input("\n请输入选项 [0/1/2/3]：").strip()

        if choice == "0":
            print("再见！")
            break
        elif choice == "1":
            run_snapshot()
        elif choice == "2":
            run_ai_analysis()
        elif choice == "3":
            run_visualize()
        else:
            print("无效选项，请输入 0、1、2 或 3。\n")

        print("\n" + "─" * 52 + "\n")


if __name__ == "__main__":
    interactive_menu()
