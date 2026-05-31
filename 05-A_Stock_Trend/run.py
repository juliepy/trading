"""
A 股 SuperTrend 分析 — 主入口

运行组合:
  SuperTrend × [HS300 | BOC] × [Daily | 4H]

用法:
    python run.py                 # 增量更新数据 + 回测
    python run.py --force         # 强制全量重新下载
    python run.py --plot          # 保存权益曲线 PNG
    python run.py --data-only     # 仅更新数据
    python run.py --charts        # 更新数据 + 刷新 K 线图
"""

import argparse
import os
import sys
import warnings

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Callable

sys.path.insert(0, os.path.dirname(__file__))
from src.fetch_data import (
    download_all, SYMBOLS, DOWNLOAD_TIMEFRAMES,
    _4h_cache_insufficient, MIN_4H_BARS,
)
from src.indicators import supertrend

warnings.filterwarnings("ignore")

_ROOT       = os.path.dirname(__file__)
RESULTS_DIR = os.path.join(_ROOT, "results")
SUMMARY_MD  = os.path.join(_ROOT, "results", "results_summary.md")


@dataclass
class BacktestResult:
    label:         str
    total_return:  float
    annual_return: float
    max_drawdown:  float
    win_rate:      float
    num_trades:    int
    sharpe:        float
    period_start:  str = ""
    period_end:    str = ""
    equity:        pd.Series = field(repr=False, default_factory=pd.Series)


def _fmt_index_date(ts) -> str:
    if isinstance(ts, (int, np.integer)):
        return str(ts)
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def _run_backtest(
    df: pd.DataFrame,
    signal_func: Callable[[pd.DataFrame], pd.DataFrame],
    label: str,
    initial_capital: float = 100_000.0,
) -> BacktestResult:
    """向量化多头回测：信号次 bar 开盘价全仓进出。"""
    df = signal_func(df).copy()
    df = df.dropna(subset=["Open", "Close"])
    df = df[(df["Open"] > 0) & (df["Close"] > 0)]
    period_start = _fmt_index_date(df.index[0])
    period_end   = _fmt_index_date(df.index[-1])
    df = df.reset_index(drop=True)

    opens    = df["Open"].to_numpy(dtype=float)
    buy_sig  = df["buy_signal"].to_numpy(dtype=bool)
    sell_sig = df["sell_signal"].to_numpy(dtype=bool)
    n        = len(df)

    capital     = initial_capital
    in_trade    = False
    entry_price = 0.0
    shares      = 0.0
    equity_curve = np.full(n, capital)
    trades: list[tuple[float, float]] = []

    for i in range(1, n):
        if in_trade:
            equity_curve[i] = shares * opens[i] + (capital - shares * entry_price)
        else:
            equity_curve[i] = capital

        if not in_trade and buy_sig[i - 1]:
            entry_price = opens[i]
            shares      = capital / entry_price
            in_trade    = True
        elif in_trade and sell_sig[i - 1]:
            exit_price = opens[i]
            capital    = shares * exit_price
            trades.append((entry_price, exit_price))
            in_trade        = False
            shares          = 0.0
            equity_curve[i] = capital

    if in_trade:
        capital = shares * opens[-1]
        trades.append((entry_price, opens[-1]))
        equity_curve[-1] = capital

    equity = pd.Series(equity_curve, index=df.index)
    total_return = (equity.iloc[-1] / initial_capital - 1) * 100

    if isinstance(df.index[-1], (int, np.integer)):
        days = len(df)
    else:
        days = max((df.index[-1] - df.index[0]).days, 1)
    years = max(days / 365.25, 0.01)
    annual_return = ((equity.iloc[-1] / initial_capital) ** (1 / years) - 1) * 100

    rolling_max  = equity.cummax()
    max_drawdown = ((equity - rolling_max) / rolling_max * 100).min()

    num_trades = len(trades)
    win_rate   = sum(1 for e, x in trades if x > e) / num_trades * 100 if num_trades > 0 else 0.0

    pct_ret       = equity.pct_change().dropna()
    bars_per_year = max(len(df) / years, 1)
    sharpe        = (pct_ret.mean() / pct_ret.std() * np.sqrt(bars_per_year)) if pct_ret.std() > 0 else 0.0

    return BacktestResult(
        label=label,
        total_return=round(total_return, 2),
        annual_return=round(annual_return, 2),
        max_drawdown=round(max_drawdown, 2),
        win_rate=round(win_rate, 1),
        num_trades=num_trades,
        sharpe=round(sharpe, 2),
        period_start=period_start,
        period_end=period_end,
        equity=equity,
    )


def strategy_supertrend(df: pd.DataFrame) -> pd.DataFrame:
    return supertrend(df, atr_period=10, multiplier=3.0)


def _ensure_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()
        for col in ("Datetime", "Date", "datetime", "date"):
            if col in df.columns:
                return df.set_index(col)
    return df


def run_all(data: dict[str, pd.DataFrame], save_plots: bool = False) -> list[BacktestResult]:
    os.makedirs(RESULTS_DIR, exist_ok=True)

    timeframes = list(DOWNLOAD_TIMEFRAMES)
    results: list[BacktestResult] = []

    for sym, info in SYMBOLS.items():
        for tf in timeframes:
            key    = f"{sym}_{tf}"
            df_raw = data.get(key)
            if df_raw is None or df_raw.empty:
                print(f"  [SKIP] 无数据: {key}")
                continue

            df = _ensure_datetime_index(df_raw.copy())
            if tf == "4h" and _4h_cache_insufficient(df):
                span = (df.index.max() - df.index.min()).days
                print(f"  [SKIP] {key} 数据不足（{len(df)} 根 / {span} 天，"
                      f"需 ≥{MIN_4H_BARS} 根），4H 回测暂无意义")
                continue

            label = f"SuperTrend | {sym} {info['name']} | {tf}"
            print(f"  {label} ({len(df)} bars) …", end=" ", flush=True)

            try:
                res = _run_backtest(df, strategy_supertrend, label)
                results.append(res)
                print(f"收益={res.total_return:+.1f}%  交易={res.num_trades}  夏普={res.sharpe:.2f}")
            except Exception as exc:
                print(f"ERROR: {exc}")

            if save_plots and results:
                _save_equity_plot(results[-1])

    return results


def _save_equity_plot(res: BacktestResult) -> None:
    try:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 4))
        res.equity.plot(ax=ax, color="steelblue", linewidth=1.2)
        ax.set_title(f"Equity Curve — {res.label}")
        ax.set_ylabel("Portfolio Value (¥)")
        ax.grid(True, alpha=0.3)
        safe = res.label.replace(" ", "_").replace("|", "")
        path = os.path.join(RESULTS_DIR, f"{safe}.png")
        plt.tight_layout()
        plt.savefig(path, dpi=120)
        plt.close(fig)
        print(f"    图表 → {path}")
    except Exception as exc:
        print(f"    图表保存失败: {exc}")


def _print_summary(results: list[BacktestResult]) -> None:
    if not results:
        print("No results.")
        return
    header = f"{'策略':<42} {'收益%':>8} {'年化%':>8} {'回撤%':>8} {'胜率%':>9} {'交易次':>7} {'夏普':>7}"
    sep    = "─" * len(header)
    print(f"\n{sep}\n{header}\n{sep}")
    for r in results:
        print(
            f"{r.label:<42} {r.total_return:>+8.1f} {r.annual_return:>+8.1f} "
            f"{r.max_drawdown:>8.1f} {r.win_rate:>9.1f} {r.num_trades:>7d} {r.sharpe:>7.2f}"
        )
    print(sep)


def _save_markdown(results: list[BacktestResult]) -> None:
    lines = [
        "# Backtest Results — SuperTrend (A 股)\n",
        "| 策略 | 回测区间 | 收益% | 年化% | 回撤% | 胜率% | 交易次 | 夏普 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        period = f"{r.period_start} ~ {r.period_end}"
        lines.append(
            f"| {r.label} | {period} | {r.total_return:+.1f} | {r.annual_return:+.1f} "
            f"| {r.max_drawdown:.1f} | {r.win_rate:.1f} | {r.num_trades} | {r.sharpe:.2f} |"
        )
    with open(SUMMARY_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n结果已保存 → {SUMMARY_MD}")


def _print_current_signals(data: dict[str, pd.DataFrame]) -> None:
    """输出各标的最新 SuperTrend 状态（日常分析用）。"""
    print("\n── 当前 SuperTrend 信号 ──")
    print(f"{'标的':<20} {'周期':<6} {'趋势':<6} {'收盘':>10} {'ST线':>10} {'最近信号':<12}")
    print("─" * 72)
    for sym, info in SYMBOLS.items():
        for tf in DOWNLOAD_TIMEFRAMES:
            key = f"{sym}_{tf}"
            df_raw = data.get(key)
            if df_raw is None or df_raw.empty:
                continue
            df = _ensure_datetime_index(df_raw.copy())
            df = supertrend(df, atr_period=10, multiplier=3.0)
            last = df.iloc[-1]
            trend = "多头" if last["trend"] == 1 else "空头"
            st_line = last["up_band"] if last["trend"] == 1 else last["dn_band"]

            recent = "—"
            for i in range(len(df) - 1, max(len(df) - 30, 0), -1):
                if df["buy_signal"].iloc[i]:
                    recent = f"Buy {str(df.index[i])[:10]}"
                    break
                if df["sell_signal"].iloc[i]:
                    recent = f"Sell {str(df.index[i])[:10]}"
                    break

            name = f"{sym} {info['name']}"
            print(f"{name:<20} {tf:<6} {trend:<6} {last['Close']:>10.2f} {st_line:>10.2f} {recent:<12}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A 股 SuperTrend 分析")
    parser.add_argument("--force",     action="store_true", help="强制全量重新下载数据")
    parser.add_argument("--plot",      action="store_true", help="保存权益曲线 PNG")
    parser.add_argument("--data-only", action="store_true", help="仅更新数据")
    parser.add_argument("--charts",    action="store_true", help="更新数据 + 刷新 K 线图")
    args = parser.parse_args()

    print("=" * 60)
    print("  A 股 SuperTrend 分析")
    print("=" * 60)

    print("\n[1/2] 数据更新 …")
    data = download_all(force=args.force)

    if args.data_only:
        _print_current_signals(data)
        print("\n已完成数据更新（--data-only 模式）")
        sys.exit(0)

    if args.charts:
        from src.plotter import plot_chart, CHART_TIMEFRAMES
        print("\n[2/2] 刷新 K 线图 …")
        for sym in SYMBOLS:
            for tf in CHART_TIMEFRAMES:
                try:
                    plot_chart(symbol=sym, timeframe=tf, n_bars=150, save=True)
                except Exception as e:
                    print(f"  [{sym} {tf}] 跳过: {e}")
        _print_current_signals(data)
        print(f"\n完成！K 线图已保存到 charts/")
        if not args.plot:
            sys.exit(0)

    print("\n[2/2] 运行回测 …")
    results = run_all(data, save_plots=args.plot)
    _print_summary(results)
    _save_markdown(results)
    _print_current_signals(data)
