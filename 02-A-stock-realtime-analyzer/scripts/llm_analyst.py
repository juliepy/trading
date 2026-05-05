#!/usr/bin/env python3
"""
A股分析师 — 由 GPT 或 DeepSeek 驱动。

抓取东方财富/腾讯实时行情与K线，可选抓取东方财富财经新闻，
然后调用配置好的 LLM 生成分析师级别的研报。

环境变量（写入 .env 或 shell）：
  # GPT
  OPENAI_API_KEY       OpenAI API Key（GPT 必填）
  OPENAI_MODEL         GPT 模型名（可选，默认 gpt-4.1）

  # DeepSeek
  DEEPSEEK_API_KEY     DeepSeek API Key（DeepSeek 必填）
  DEEPSEEK_MODEL       DeepSeek 模型名（可选，默认 deepseek-chat）

  # 统一切换入口
  LLM_MODEL            设置此变量即可切换后端：
                         LLM_MODEL=gpt-4.1            → GPT
                         LLM_MODEL=deepseek-chat      → DeepSeek V3
                         LLM_MODEL=deepseek-reasoner  → DeepSeek R1

用法示例：
  python scripts/llm_analyst.py --codes 603618,002149 --with-kline --with-indices
  python scripts/llm_analyst.py --codes 000001 --with-kline --with-news --stream
"""

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

# Allow `from a_share_snapshot import ...` when running from any cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from a_share_snapshot import fetch_index_baseline, fetch_kline, fetch_quotes, parse_codes

# ---------------------------------------------------------------------------
# 自动加载项目根目录的 .env 文件
# ---------------------------------------------------------------------------
_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# ---------------------------------------------------------------------------
# LLM 配置（对齐 ai_client.py 模式）
# ---------------------------------------------------------------------------
_LLM_MODEL = os.environ.get("LLM_MODEL", "")
_GPT_KEY   = os.environ.get("OPENAI_API_KEY", "")
_GPT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1")
_DS_KEY    = os.environ.get("DEEPSEEK_API_KEY", "")
_DS_MODEL  = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")


def _resolve() -> tuple:
    """返回 (client, model_name)，根据环境变量自动选择后端"""
    from openai import OpenAI
    m = _LLM_MODEL.strip()
    if m.lower().startswith("deepseek") or (not m and _DS_KEY):
        model = m if m else _DS_MODEL
        if not _DS_KEY:
            raise RuntimeError("未设置 DEEPSEEK_API_KEY")
        return OpenAI(base_url="https://api.deepseek.com/v1", api_key=_DS_KEY), model
    # 默认 GPT
    model = m if m else _GPT_MODEL
    if not _GPT_KEY:
        raise RuntimeError("未设置 OPENAI_API_KEY")
    return OpenAI(base_url="https://api.openai.com/v1", api_key=_GPT_KEY), model


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """\
你是一位专业的A股分析师，遵循严格的"证据优先、过程透明"分析原则。

## 核心原则
1. **证据绑定**：每个关键结论必须附有来源/数据依据，禁止无依据主观猜测。
2. **双逻辑分离**：所有股票判断必须拆分为 产业逻辑 + 交易逻辑 两层。
3. **三情景输出**：每只股票给出 强/中/弱 三个价格情景及对应操作动作。
4. **不确定性标注**：置信度低于"中"时，必须明确写出不确定因素与修正计划。

## 分析报告必须包含以下结构（按顺序）

### 0) 数据摘要（Data Summary）
- 展示从调用方提供的结构化数据中读取到的关键指标。
- 时间戳，代码列表，盘口数据，指数状况，K线指标（如有）。

### 1) 市场情绪底色
- 指数涨跌（上证/深成/创业板）+ 宽度（上涨/下跌家数）
- 成交风格：缩量/放量；题材主导 or 权重主导
- 一句话结论：普涨 / 分化 / 退潮 / 修复

### 2) 逐股深度分析（每只股票必须包含以下子节）
1. 公司业务定位（主营、核心产品、产业链位置）
2. 当前市场叙事与阶段（启动/强化/分歧/退潮）
3. 行业龙头与板块阶段
4. 技术面（MA5/MA10/MA20/MA60、关键压力位/支撑位/失效位）
5. 舆情与事件面（利多/利空/争议点，结合新闻数据）
6. 双逻辑判断
   - 产业逻辑：在 / 弱化 / 失效（附原因）
   - 交易逻辑：在 / 弱化 / 失效（附原因）
7. 明日三情景动作
   - 强情景：触发条件 → 动作
   - 中情景：触发条件 → 动作
   - 弱情景：触发条件 → 动作
8. 证据卡片（E1 行情数据 / E2 官方披露 / E3 主流媒体 / E4 板块验证）
9. 置信度（高/中/低 + 原因）

### 3) 组合分层建议（若涉及多只股票）
- A组（产业+交易逻辑同向）/ B组（产业在/交易弱）/ C组（交易逻辑受损）
- 风险集中度说明

### 4) 不确定性与自我修正
- 本轮最不确定的 2~3 个点
- 可能导致错判的条件
- 下一轮补证据与阈值修正计划

### 5) 一句话总结
> 用一句话（≤30字）概括本次分析的核心结论，格式：**「{股票}：{状态} — {建议动作}」**，多只股票依次列出。

## 注意事项
- 仅基于调用方提供的结构化数据写作"数据摘要"；基本面部分须明确标注"需联网核实"。
- 如果提供了新闻数据，请在"舆情与事件面"中直接引用新闻标题/摘要作为证据。
- 如果结构化数据不足（如K线缺失），在不确定性部分说明并建议补充。
- 输出语言：中文为主，技术指标名词可中英混写。
"""


# ---------------------------------------------------------------------------
# Helper: build human message with structured data
# ---------------------------------------------------------------------------
def _build_user_message(codes: list, market_data: dict) -> str:
    lines = [
        "## 分析请求",
        f"- 时间戳：{market_data.get('timestamp', dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}",
        f"- 分析标的：{', '.join(codes)}",
        "",
        "## 结构化市场数据（JSON）",
        "```json",
        json.dumps(market_data, ensure_ascii=False, indent=2),
        "```",
        "",
        "请严格按照『分析报告结构』输出完整报告。",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core analysis function
# ---------------------------------------------------------------------------
def run_analysis(
    codes: list,
    with_kline: bool = False,
    kline_days: int = 60,
    with_indices: bool = False,
    with_news: bool = False,
    news_count: int = 5,
    stream: bool = False,
):
    client, model = _resolve()

    # 1. 抓取行情数据 ---------------------------------------------------------
    print("[1/3] 正在抓取实时行情...", file=sys.stderr)
    market_data = {
        "timestamp": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "codes": codes,
        "quotes": fetch_quotes(codes),
    }

    if with_indices:
        print("[2/3] 正在抓取大盘指数...", file=sys.stderr)
        market_data["indices"] = fetch_index_baseline()
    else:
        print("[2/3] 跳过大盘指数（使用 --with-indices 开启）。", file=sys.stderr)

    if with_kline:
        print(f"[2/3] 正在抓取K线数据（{kline_days}日）...", file=sys.stderr)
        kline = {}
        for c in codes:
            try:
                kline[c] = fetch_kline(c, days=kline_days)
            except Exception as exc:
                kline[c] = {"error": str(exc)}
        market_data["kline"] = kline

    # 2. 抓取新闻（可选）-----------------------------------------------------
    if with_news:
        print(f"[2/3] 正在抓取财经新闻...", file=sys.stderr)
        try:
            from news_fetcher import fetch_news
            news = {}
            for c in codes:
                news[c] = fetch_news(c, news_count)
            market_data["news"] = news
        except ImportError:
            print("[警告] news_fetcher 未找到，跳过新闻抓取。", file=sys.stderr)
        except Exception as exc:
            print(f"[警告] 新闻抓取失败：{exc}", file=sys.stderr)

    # 3. 构建 prompt ----------------------------------------------------------
    user_msg = _build_user_message(codes, market_data)

    # 4. 调用 LLM -------------------------------------------------------------
    print(f"[3/3] 正在调用 LLM（{model}）...", file=sys.stderr)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": user_msg},
    ]

    if stream:
        resp = client.chat.completions.create(model=model, messages=messages, stream=True)
        for chunk in resp:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                print(delta.content, end="", flush=True)
        print()
    else:
        resp = client.chat.completions.create(model=model, messages=messages, stream=False)
        print(resp.choices[0].message.content)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="A股分析师 — 由 GPT / DeepSeek 驱动",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--codes", required=True,
        help="逗号/空格分隔的6位A股代码，如 603618,002149",
    )
    parser.add_argument(
        "--with-kline", action="store_true",
        help="包含日K线 + 均线/涨幅指标",
    )
    parser.add_argument(
        "--kline-days", type=int, default=60,
        help="K线回望天数（默认 60）",
    )
    parser.add_argument(
        "--with-indices", action="store_true",
        help="包含上证/深成/创业板指数宽度数据",
    )
    parser.add_argument(
        "--with-news", action="store_true",
        help="抓取东方财富财经新闻并纳入分析",
    )
    parser.add_argument(
        "--news-count", type=int, default=5,
        help="每只股票抓取新闻条数（默认 5）",
    )
    parser.add_argument(
        "--stream", action="store_true",
        help="流式输出 LLM 回复",
    )
    parser.add_argument(
        "--model", default=None,
        help="覆盖模型/后端（如 deepseek-chat、deepseek-reasoner、gpt-4.1）",
    )
    args = parser.parse_args()

    global _LLM_MODEL
    if args.model:
        _LLM_MODEL = args.model

    codes = parse_codes(args.codes)
    run_analysis(
        codes=codes,
        with_kline=args.with_kline,
        kline_days=args.kline_days,
        with_indices=args.with_indices,
        with_news=args.with_news,
        news_count=args.news_count,
        stream=args.stream,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
