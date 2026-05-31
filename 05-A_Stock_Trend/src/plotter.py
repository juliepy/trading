"""
plotter.py — A 股 SuperTrend K 线图（TradingView 深色风格）

支持周期: daily（日线）、4h（4 小时）

用法:
    python src/plotter.py                  # 全部标的 daily + 4h
    python src/plotter.py --symbol HS300   # 指定标的
    python src/plotter.py --tf 4h          # 仅 4H
    python src/plotter.py --show           # 弹出预览
"""

import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.indicators import supertrend
from src.fetch_data import SYMBOLS

_ROOT      = os.path.dirname(os.path.dirname(__file__))
DATA_DIR   = os.path.join(_ROOT, "data")
CHARTS_DIR = os.path.join(_ROOT, "charts")

_BG       = "#131722"
_GRID     = "#1e222d"
_TEXT     = "#b2b5be"
_BULL_C   = "#26a69a"
_BEAR_C   = "#ef5350"
_ST_BULL  = "#26a69a"
_ST_BEAR  = "#ef5350"
_VOL_BULL = "#1a6060"
_VOL_BEAR = "#6b2020"
_COL_BUY  = "#00e676"
_COL_SELL = "#ff5252"

CHART_TIMEFRAMES = ("daily", "4h")


def _normalize_tf(timeframe: str) -> str:
    tfl = timeframe.lower()
    if tfl in ("4h", "4hour"):
        return "4h"
    if tfl in ("daily", "d", "1d"):
        return "daily"
    raise ValueError(f"不支持的周期: {timeframe}，仅支持 daily / 4h")


def load_data(symbol: str, timeframe: str) -> pd.DataFrame:
    key = symbol.upper()
    if key not in SYMBOLS:
        raise ValueError(f"未知标的: {symbol}，可选: {', '.join(SYMBOLS)}")

    tf = _normalize_tf(timeframe)
    path = os.path.join(DATA_DIR, f"{key}_{tf}.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到数据: {path}，请先运行 python run.py --data-only")
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    return df[df["Close"] > 0].sort_index()


def _make_style():
    mc = mpf.make_marketcolors(
        up=_BULL_C, down=_BEAR_C,
        edge={"up": _BULL_C, "down": _BEAR_C},
        wick={"up": _BULL_C, "down": _BEAR_C},
        volume={"up": _VOL_BULL, "down": _VOL_BEAR},
    )
    return mpf.make_mpf_style(
        marketcolors=mc,
        base_mpl_style="dark_background",
        gridstyle="--",
        gridcolor=_GRID,
        gridaxis="both",
        facecolor=_BG,
        figcolor=_BG,
        rc={
            "axes.labelcolor": _TEXT,
            "xtick.color":     _TEXT,
            "ytick.color":     _TEXT,
            "axes.edgecolor":  _GRID,
        },
    )


def _signal_label(ax, x, y, label, price, dt, color, n_bars, is_buy, timeframe):
    price_str = f"{price:,.2f}" if price >= 10 else f"{price:.3f}"
    try:
        dt_str = dt.strftime("%Y-%m-%d") if timeframe == "daily" else dt.strftime("%m-%d %H:%M")
    except Exception:
        dt_str = str(dt)[:10]

    va_box = "bottom" if is_buy else "top"
    ax.annotate(
        label, xy=(x, y), xycoords="data",
        ha="center", va=va_box, fontsize=7, fontweight="bold",
        color="white",
        bbox=dict(boxstyle="round,pad=0.3", facecolor=color, edgecolor="white",
                  linewidth=0.6, alpha=0.92),
    )
    ax.annotate(
        price_str, xy=(x, y), xycoords="data",
        xytext=(6, 0), textcoords="offset points",
        ha="left", va="center", fontsize=6.5, fontweight="bold", color=color,
    )
    ax.annotate(
        dt_str, xy=(x, y), xycoords="data",
        xytext=(0, -8 if is_buy else 8), textcoords="offset points",
        ha="center", va="top" if is_buy else "bottom",
        fontsize=5.5, color=_TEXT, alpha=0.85,
    )
    ax.hlines(y=y, xmin=x, xmax=n_bars - 1, colors=color,
              linewidths=0.5, linestyles="dashed", alpha=0.35)


def plot_chart(
    symbol:    str  = "HS300",
    timeframe: str  = "daily",
    n_bars:    int  = 150,
    show:      bool = False,
    save:      bool = True,
) -> str:
    sym_key = symbol.upper()
    tf = _normalize_tf(timeframe)
    info = SYMBOLS.get(sym_key, {"name": sym_key})
    sym_label = f"{info['name']} ({info.get('code', sym_key)})"

    df_full = load_data(sym_key, tf)
    df = df_full.tail(n_bars).copy()
    if len(df) < 20:
        raise ValueError(f"数据不足 ({len(df)} 行)")

    df_st = supertrend(df, atr_period=10, multiplier=3.0)
    st_bull = df_st["up_band"].where(df_st["trend"] == 1)
    st_bear = df_st["dn_band"].where(df_st["trend"] == -1)

    n = len(df_st)
    ap = []
    if st_bull.notna().any():
        ap.append(mpf.make_addplot(st_bull, type="line", color=_ST_BULL, width=1.5, panel=0))
    if st_bear.notna().any():
        ap.append(mpf.make_addplot(st_bear, type="line", color=_ST_BEAR, width=1.5, panel=0))

    title = f"{sym_label}  {tf.upper()}  — SuperTrend  (last {n_bars} bars)"
    fig, axes = mpf.plot(
        df_st, type="candle", style=_make_style(), title=title,
        volume=True, addplot=ap, panel_ratios=(4, 1),
        figsize=(16, 8), returnfig=True, warn_too_much_data=9999, tight_layout=True,
    )
    ax = axes[0]

    price_arr = df_st["Close"].to_numpy()
    high_arr  = df_st["High"].to_numpy()
    low_arr   = df_st["Low"].to_numpy()
    atr_arr   = df_st["atr"].fillna(0).to_numpy()
    dates     = df_st.index

    for i in range(n):
        off = max(atr_arr[i] * 0.5, price_arr[i] * 0.004)
        dt  = dates[i]

        if df_st["buy_signal"].iloc[i]:
            entry = df_st["Open"].iloc[i + 1] if i + 1 < n else price_arr[i]
            _signal_label(ax, i, low_arr[i] - off * 3.0,
                          "ST Buy", entry, dt, _COL_BUY, n, True, tf)
        if df_st["sell_signal"].iloc[i]:
            entry = df_st["Open"].iloc[i + 1] if i + 1 < n else price_arr[i]
            _signal_label(ax, i, high_arr[i] + off * 3.0,
                          "ST Sell", entry, dt, _COL_SELL, n, False, tf)

    # 当前趋势状态标注
    last = df_st.iloc[-1]
    trend_txt = "多头 ▲" if last["trend"] == 1 else "空头 ▼"
    trend_col = _ST_BULL if last["trend"] == 1 else _ST_BEAR
    ax.text(
        0.01, 0.98, f"当前: {trend_txt}  收盘 {last['Close']:.2f}",
        transform=ax.transAxes, fontsize=10, fontweight="bold",
        color=trend_col, va="top",
        bbox=dict(boxstyle="round,pad=0.4", facecolor=_GRID, alpha=0.8),
    )

    legend_items = [
        mpatches.Patch(color=_ST_BULL, label="SuperTrend 多头"),
        mpatches.Patch(color=_ST_BEAR, label="SuperTrend 空头"),
        mpatches.Patch(color=_COL_BUY,  label="ST Buy（趋势转多）"),
        mpatches.Patch(color=_COL_SELL, label="ST Sell（趋势转空）"),
    ]
    ax.legend(handles=legend_items, loc="upper left", fontsize=7,
              facecolor=_GRID, edgecolor=_GRID, labelcolor=_TEXT, framealpha=0.8)

    out_path = ""
    if save:
        os.makedirs(CHARTS_DIR, exist_ok=True)
        out_path = os.path.join(CHARTS_DIR, f"{sym_key}_{tf}_chart.png")
        fig.savefig(out_path, dpi=130, bbox_inches="tight", facecolor=_BG)
        print(f"Chart saved -> {out_path}")

    if show:
        matplotlib.use("TkAgg")
        plt.show()

    plt.close(fig)
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A 股 SuperTrend K 线图")
    parser.add_argument("--symbol", default="all", help="HS300 / BOC / all")
    parser.add_argument("--tf",     default="all", help="daily / 4h / all")
    parser.add_argument("--bars",   type=int, default=150)
    parser.add_argument("--show",   action="store_true")
    args = parser.parse_args()

    symbols = list(SYMBOLS.keys()) if args.symbol.lower() == "all" else [args.symbol.upper()]
    if args.tf.lower() == "all":
        timeframes = list(CHART_TIMEFRAMES)
    else:
        timeframes = [_normalize_tf(args.tf)]

    print(f"生成图表：{len(symbols) * len(timeframes)} 张...")
    for sym in symbols:
        for tf in timeframes:
            try:
                plot_chart(symbol=sym, timeframe=tf, n_bars=args.bars, show=args.show, save=True)
            except Exception as e:
                print(f"  [{sym} {tf}] 跳过: {e}")

    print("\n完成！图表保存在 charts/ 目录")
