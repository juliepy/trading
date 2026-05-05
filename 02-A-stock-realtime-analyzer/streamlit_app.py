#!/usr/bin/env python3
"""
A股实时分析助手 — Streamlit 聊天页面
用法：streamlit run streamlit_app.py
"""

import datetime as dt
import io
import json
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import streamlit as st

# ── 环境 & 路径 ────────────────────────────────────────────────────────────
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
from a_share_snapshot import (
    fetch_index_baseline, fetch_kline, fetch_quotes,
    parse_codes, search_stock_by_name,
)

# ── 页面配置 ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="A股实时分析助手",
    page_icon="📈",
    layout="wide",
)

# ── 中文字体（只使用系统中实际存在的字体）────────────────────────────────
import warnings as _warnings
_available_fonts = {f.name for f in matplotlib.font_manager.fontManager.ttflist}
_cjk_candidates = [
    "WenQuanYi Micro Hei", "WenQuanYi Zen Hei", "Noto Sans CJK JP",
    "Noto Serif CJK JP", "Droid Sans Fallback", "DejaVu Sans",
]
matplotlib.rcParams["font.family"] = [f for f in _cjk_candidates if f in _available_fonts] or ["DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False
# 屏蔽字体未找到的 findfont 警告
_warnings.filterwarnings("ignore", message="findfont")

# ── 常量 ───────────────────────────────────────────────────────────────────
KLINE_DAYS = 60
OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════
# 数据 & 图表
# ═══════════════════════════════════════════════════════════════════════════

def _ma_series(closes, n):
    result = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        result[i] = sum(closes[i - n + 1: i + 1]) / n
    return result


@st.cache_data(ttl=60, show_spinner=False)
def fetch_market_data(codes_tuple, with_news: bool = True, news_count: int = 5):
    codes = list(codes_tuple)
    data = {
        "timestamp": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "codes": codes,
        "quotes": [],
        "indices": [],
        "kline": {},
    }
    try:
        data["quotes"] = fetch_quotes(codes)
    except Exception as e:
        raise RuntimeError(f"行情数据获取失败（可能是网络超时）：{e}") from e
    try:
        data["indices"] = fetch_index_baseline()
    except Exception:
        pass  # 指数宽度失败不阻断主流程
    for c in codes:
        try:
            data["kline"][c] = fetch_kline(c, days=KLINE_DAYS)
        except Exception as e:
            data["kline"][c] = {"error": str(e)}
    if with_news:
        try:
            from scripts.news_fetcher import fetch_news
            data["news"] = {c: fetch_news(c, news_count) for c in codes}
        except Exception:
            pass  # 新闻抓取失败不阻断主流程
    return data


def _save_outputs(ts_tag, codes_tag, data, chart_bufs, report):
    """将 JSON、PNG 图表、GPT 报告保存到 outputs/ 目录，返回保存路径列表。"""
    saved = []
    # JSON
    json_path = OUTPUT_DIR / f"{ts_tag}_{codes_tag}.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    saved.append(json_path)
    # 图表 PNG
    for code, buf in chart_bufs.items():
        if buf is not None:
            png_path = OUTPUT_DIR / f"{ts_tag}_{code}.png"
            png_path.write_bytes(buf.getvalue())
            saved.append(png_path)
    # GPT 报告
    if report:
        md_path = OUTPUT_DIR / f"{ts_tag}_{codes_tag}_report.md"
        md_path.write_text(report, encoding="utf-8")
        saved.append(md_path)
    return saved


def make_chart(data, code):
    kd = data["kline"].get(code, {})
    klines = kd.get("klines", [])
    if not klines:
        return None

    quote = next((q for q in data["quotes"] if q["code"] == code), {})
    name = quote.get("name", code)

    dates  = [k["date"] for k in klines]
    opens  = [k["open"] for k in klines]
    closes = [k["close"] for k in klines]
    highs  = [k["high"] for k in klines]
    lows   = [k["low"] for k in klines]
    vols   = [k["volume"] for k in klines]
    xs     = list(range(len(dates)))
    ma5    = _ma_series(closes, 5)
    ma10   = _ma_series(closes, 10)
    ma20   = _ma_series(closes, 20)

    fig = plt.figure(figsize=(12, 7))
    fig.patch.set_facecolor("#0d1117")
    gs = GridSpec(3, 1, figure=fig, height_ratios=[3, 1, 0.7], hspace=0.06)
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax3 = fig.add_subplot(gs[2])

    for ax in [ax1, ax2]:
        ax.set_facecolor("#0d1117")
        ax.tick_params(colors="#aaaaaa", labelsize=8)
        ax.spines[:].set_color("#333333")

    # 蜡烛图
    for i, x in enumerate(xs):
        o, c, h, l = opens[i], closes[i], highs[i], lows[i]
        color = "#ef5350" if c >= o else "#26a69a"
        ax1.plot([x, x], [l, h], color=color, linewidth=0.8)
        ax1.bar(x, abs(c - o) or 0.01, bottom=min(o, c),
                color=color, width=0.6, linewidth=0)

    def _plot_ma(ax, series, color, label):
        xs_v = [i for i, v in enumerate(series) if v is not None]
        ys_v = [v for v in series if v is not None]
        if xs_v:
            ax.plot(xs_v, ys_v, color=color, linewidth=1, label=label)

    _plot_ma(ax1, ma5,  "#ffd700", "MA5")
    _plot_ma(ax1, ma10, "#ff9800", "MA10")
    _plot_ma(ax1, ma20, "#e040fb", "MA20")
    ax1.legend(framealpha=0, labelcolor="white", fontsize=8, loc="upper left")
    ax1.set_title(f"{name}（{code}）  K线走势  {dates[0]} ~ {dates[-1]}",
                  color="white", fontsize=11, pad=6)
    ax1.set_ylabel("价格（元）", color="#aaaaaa", fontsize=8)
    ax1.yaxis.tick_right()
    ax1.yaxis.set_label_position("right")
    ax1.tick_params(labelbottom=False)
    last_close = closes[-1]
    ax1.axhline(last_close, color="#ffffff", linewidth=0.5, linestyle="--", alpha=0.4)
    ax1.annotate(f" {last_close}", xy=(xs[-1], last_close),
                 color="white", fontsize=8, va="center")

    # 成交量
    for i, x in enumerate(xs):
        color = "#ef5350" if closes[i] >= opens[i] else "#26a69a"
        ax2.bar(x, vols[i], color=color, width=0.6, linewidth=0)
    ax2.set_ylabel("成交量", color="#aaaaaa", fontsize=7)
    ax2.yaxis.tick_right()
    ax2.yaxis.set_label_position("right")
    ax2.set_facecolor("#0d1117")
    tick_step = max(1, len(xs) // 10)
    ax2.set_xticks(xs[::tick_step])
    ax2.set_xticklabels([dates[i] for i in range(0, len(dates), tick_step)],
                        rotation=30, ha="right", color="#aaaaaa", fontsize=7)

    # 大盘摘要
    ax3.set_facecolor("#0d1117")
    ax3.axis("off")
    m = kd.get("metrics", {})
    pct = quote.get("pct", 0) or 0
    color_pct = "#ef5350" if pct > 0 else "#26a69a"
    arrow = "▲" if pct > 0 else "▼"
    summary = (f"{name}  最新: {last_close}  {arrow} {pct}%  "
               f"MA5:{m.get('ma5')}  MA10:{m.get('ma10')}  MA20:{m.get('ma20')}  "
               f"5d:{m.get('ret_5d_pct')}%  10d:{m.get('ret_10d_pct')}%  20d:{m.get('ret_20d_pct')}%")
    ax3.text(0.01, 0.75, summary, transform=ax3.transAxes,
             color=color_pct, fontsize=8.5, va="top")
    indices = data.get("indices", [])
    if indices:
        idx_str = "  |  ".join(
            f"{idx['name']} {idx['last']} {'▲' if (idx.get('pct') or 0) > 0 else '▼'}"
            f"{idx.get('pct')}%  ↑{idx.get('up_count','?')} ↓{idx.get('down_count','?')}"
            for idx in indices
        )
        ax3.text(0.01, 0.25, idx_str, transform=ax3.transAxes,
                 color="#aaaaaa", fontsize=8, va="top")

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150,
                bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════════════════════════════
# GPT 分析（流式）
# ═══════════════════════════════════════════════════════════════════════════

def _resolve_codes(raw: str):
    """输入股票名称或代码，返回 (codes, display_names) 列表"""
    import re
    tokens = [t for t in re.split(r"[,，\s]+", raw.strip()) if t]
    codes, names = [], []
    for tok in tokens:
        try:
            from a_share_snapshot import normalize_code
            code = normalize_code(tok)
            codes.append(code)
            names.append(tok)
        except ValueError:
            results = search_stock_by_name(tok)
            if results:
                code, name = results[0]
                codes.append(code)
                names.append(name)
            else:
                st.warning(f"未找到股票：{tok}")
    return codes


def stream_gpt_analysis(data):
    """调用 LLM 流式分析，generator 逐 token yield（支持 GPT / DeepSeek）"""
    try:
        from openai import OpenAI
    except ImportError:
        yield "❌ 请先安装 openai：`pip install openai`"
        return

    sys.path.insert(0, str(Path(__file__).parent / "scripts"))
    from llm_analyst import _SYSTEM_PROMPT, _build_user_message, _resolve

    try:
        client, model = _resolve()
    except RuntimeError as e:
        yield f"❌ {e}"
        return

    user_msg = _build_user_message(data["codes"], data)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": user_msg},
    ]

    try:
        resp = client.chat.completions.create(model=model, messages=messages, stream=True)
        for chunk in resp:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content
    except Exception as e:
        yield f"\n\n❌ LLM 调用失败：{e}"


# ═══════════════════════════════════════════════════════════════════════════
# Streamlit UI
# ═══════════════════════════════════════════════════════════════════════════

st.markdown("""
<h1 style='text-align:center; color:#e0e0e0;'>📈 A股实时分析助手</h1>
<p style='text-align:center; color:#888; margin-top:-10px;'>
输入股票代码或名称，自动生成K线图并由 GPT-4.1 进行深度分析
</p>
""", unsafe_allow_html=True)

st.divider()

# ── 聊天记录 session state ─────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "你好！请输入要分析的股票代码或名称（支持多个，用逗号分隔），例如：`科大讯飞` 或 `000001,600036`"}
    ]

# 渲染历史消息
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if "image" in msg:
            st.image(msg["image"], use_container_width=True)
        st.markdown(msg["content"])

# ── 输入框 ─────────────────────────────────────────────────────────────────
if user_input := st.chat_input("输入股票代码或名称，如：科大讯飞 / 002230"):
    # 显示用户消息
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 解析股票代码
    with st.spinner("正在解析股票..."):
        codes = _resolve_codes(user_input)

    if not codes:
        err = "❌ 未能识别任何有效股票，请检查输入。"
        st.session_state.messages.append({"role": "assistant", "content": err})
        with st.chat_message("assistant"):
            st.markdown(err)
        st.stop()

    # ── 1. 抓取数据 ──────────────────────────────────────────────────────
    with st.spinner(f"正在抓取行情数据 & 新闻：{', '.join(codes)}..."):
        try:
            data = fetch_market_data(tuple(codes), with_news=True, news_count=5)
        except RuntimeError as e:
            err = f"❌ {e}\n\n请检查网络连接后重试。"
            st.session_state.messages.append({"role": "assistant", "content": err})
            with st.chat_message("assistant"):
                st.error(err)
            st.stop()

    ts_tag = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    codes_tag = "_".join(codes)
    chart_bufs = {}  # code -> BytesIO

    # ── 2. 生成 K 线图 & 展示新闻 ──────────────────────────────────────
    with st.chat_message("assistant"):
        for code in codes:
            chart_buf = make_chart(data, code)
            chart_bufs[code] = chart_buf
            if chart_buf:
                st.image(chart_buf, use_container_width=True)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"📊 **{code}** K线图（近 {KLINE_DAYS} 日）",
                    "image": chart_buf,
                })
            else:
                st.warning(f"[{code}] 暂无K线数据")

            # 展示新闻摘要
            news_list = data.get("news", {}).get(code, [])
            if news_list:
                with st.expander(f"📰 {code} 近期新闻（{len(news_list)} 条）", expanded=False):
                    for n in news_list:
                        title = n.get("title", "")
                        link  = n.get("link", "")
                        pub   = n.get("published", "")
                        digest = n.get("content", "")
                        st.markdown(
                            f"**[{title}]({link})**  \n"
                            f"<span style='color:#888;font-size:0.8em'>{pub}</span>  \n"
                            f"{digest}",
                            unsafe_allow_html=True,
                        )
                        st.divider()

        # ── 3. GPT 流式分析 ──────────────────────────────────────────
        st.markdown("---\n**GPT-4.1 深度分析报告**")
        report_placeholder = st.empty()
        full_report = ""
        for chunk in stream_gpt_analysis(data):
            full_report += chunk
            report_placeholder.markdown(full_report + "▌")
        report_placeholder.markdown(full_report)

        # ── 4. 保存到本地 outputs/ ────────────────────────────────────
        saved_paths = _save_outputs(ts_tag, codes_tag, data, chart_bufs, full_report)
        saved_names = ", ".join(p.name for p in saved_paths)
        st.caption(f"💾 已保存到 outputs/：{saved_names}")

    st.session_state.messages.append({
        "role": "assistant",
        "content": full_report,
    })
