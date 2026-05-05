#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 深度分析模块 — 支持 GPT-4.1（Responses API）和 DeepSeek（Chat API）

环境变量（读自 .env 或 shell）：
  CI_TOKEN             GPT Bearer Token
  OPENAI_BASE_URL      GPT 代理地址（可选）
  OPENAI_MODEL         GPT 模型名（可选，默认 gpt-4.1）

  DEEPSEEK_API_KEY     DeepSeek API Key
  DEEPSEEK_BASE_URL    DeepSeek 地址（可选，默认 https://api.deepseek.com/v1）
  DEEPSEEK_MODEL       DeepSeek 模型名（可选，默认 deepseek-chat）

  LLM_MODEL            统一切换入口（可选）
    LLM_MODEL=gpt-4.1           → 使用 GPT（需要 CI_TOKEN）
    LLM_MODEL=deepseek-chat     → 使用 DeepSeek（需要 DEEPSEEK_API_KEY）
    LLM_MODEL=deepseek-reasoner → 使用 DeepSeek R1
"""

import datetime as dt
import json
import os
from pathlib import Path
from typing import Generator, Union

# ── 自动加载 .env ─────────────────────────────────────────────────────────
_env_path = Path(__file__).resolve().parents[1] / ".env"
if not _env_path.exists():
    _env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# ── 配置 ──────────────────────────────────────────────────────────────────
_BASE_URL    = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
_API_KEY     = os.environ.get("CI_TOKEN") or os.environ.get("OPENAI_API_KEY", "")
_GPT_MODEL   = os.environ.get("OPENAI_MODEL", "gpt-4.1")
_APP_NAME    = "a-stock-selector"
_DS_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
_DS_API_KEY  = os.environ.get("DEEPSEEK_API_KEY", "")
_DS_MODEL    = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

# ── 后端 & 模型（模块加载时解析一次）─────────────────────────────────────
def _resolve_backend() -> tuple[str, str]:
    """优先级：LLM_MODEL > DEEPSEEK_API_KEY 存在 > 默认 GPT"""
    m = os.environ.get("LLM_MODEL", "").strip()
    if m.lower().startswith("deepseek"):
        return "deepseek", m
    if m:
        return "gpt", m
    return ("deepseek", _DS_MODEL) if _DS_API_KEY else ("gpt", _GPT_MODEL)

_BACKEND, _MODEL = _resolve_backend()

# ── 客户端懒加载单例 ──────────────────────────────────────────────────────
_gpt_client = None
_ds_client  = None


def _get_gpt_client():
    global _gpt_client
    if _gpt_client is None:
        if not _API_KEY:
            raise RuntimeError("未设置 CI_TOKEN 或 OPENAI_API_KEY，无法调用 GPT。")
        from openai import OpenAI
        _gpt_client = OpenAI(
            base_url=_BASE_URL,
            api_key=_API_KEY,
            default_headers={"x-cisco-app": _APP_NAME},
        )
    return _gpt_client


def _get_deepseek_client():
    global _ds_client
    if _ds_client is None:
        if not _DS_API_KEY:
            raise RuntimeError("未设置 DEEPSEEK_API_KEY，无法调用 DeepSeek。")
        from openai import OpenAI
        _ds_client = OpenAI(base_url=_DS_BASE_URL, api_key=_DS_API_KEY)
    return _ds_client


# ── System Prompt ─────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
你是一位专业的A股分析师，遵循严格的"证据优先、过程透明"分析原则。
本次任务为**单只股票深度研报**。
请严格根据用户提供的结构化数据进行分析，所有结论必须有数据依据，不得捏造或假设任何未在数据中出现的数字。

## 核心原则
1. **证据绑定**：每个关键结论必须引用传入数据中的具体字段值，禁止无依据的主观猜测。
2. **双逻辑分离**：判断必须拆分为 交易逻辑（技术+资金） + 选股逻辑（评分+信号） 两层。
3. **三情景输出**：给出 强/中/弱 三个价格情景及对应操作动作，触发条件须为具体价位或指标值。
4. **不确定性标注**：置信度低于"中"时，必须明确写出不确定因素与修正计划。

## 报告结构（按顺序输出）

### 0) 数据摘要
- 时间戳、股票代码与名称、市场情绪评分。
- 核心行情数据（价格、涨跌幅、量比、PE、市值）。
- 技术指标一览（MA5/10/20/60、RSI、MACD、KDJ、BOLL、ATR）。
- 资金流向（主力净流入、超大单/大单占比、连续净流入天数）。
- 选股器评分（若数据中包含 selector_score / selector_rating / buy_signals，在此列出并解读含义）。

### 1) 市场情绪底色
- 根据传入的情绪评分（score / level）解读当前市场阶段。
- 结合情绪对本只股票的整体影响（顺风 / 逆风 / 中性）。

### 2) 技术面深度解读
- MA5/MA10/MA20/MA60 多空排列；当前价格相对各均线的位置（上方/下方/刚穿越）。
- RSI 超买超卖状态；MACD 金叉/死叉/背离；KDJ 钝化/交叉信号。
- BOLL 开口/收口，价格所处通道位置（上轨/中轨/下轨附近）。
- 量比异动分析；基于均线与 BOLL 通道估算参考压力位 / 支撑位 / 失效位（三档，注明为快照估算）。

### 3) 资金面深度解读
- 主力净流入/流出趋势，超大单/大单结构拆解。
- 连续净流入/流出天数及加速/减速判断。
- 量化短线评分与中长线评分（若数据中有 short_score / long_score）。

### 4) 选股器信号解读
- 解读 selector_score / selector_rating 的含义与强弱。
- 列出 buy_signals 中每条信号的触发原因。
- 结合止损位（stop_loss）、止盈位（take_profit）、风险回报比（risk_reward_ratio）给出风控建议。
- 若以上字段不存在，本节注明"选股器数据未提供"。

### 5) 双逻辑判断
- **交易逻辑**（技术面 + 资金面）：成立 / 弱化 / 失效（附具体数据依据）
- **选股逻辑**（评分 + 信号）：成立 / 弱化 / 失效（附具体数据依据）

### 6) 明日三情景动作
| 情景 | 触发条件（具体价位或指标值） | 动作 | 目标位 / 止损位 |
|------|--------------------------|------|----------------|
| 强情景 | 填入具体条件 | 买入/加仓 | 填入具体价位 |
| 中情景 | 填入具体条件 | 持有/观望 | 填入具体价位 |
| 弱情景 | 填入具体条件 | 减仓/止损 | 填入具体价位 |

### 7) 证据卡片
- E1 行情数据
- E2 技术指标数据
- E3 资金流向数据
- E4 选股器评分与信号（若无则注明）

### 8) 置信度与不确定性
- 综合置信度：高 / 中 / 低（附原因）
- 最不确定的 2~3 个点
- 可能导致错判的条件
- 建议用户补充的数据项

### 9) 总结
输出 3~5 句话的综合结论，涵盖以下要点：
1. 以 **「股票代码 公司名称：当前状态 — 建议动作」** 作为开篇句。
2. 说明技术面与选股逻辑是否共振，以及最关键的支撑/压力位。
3. 点明核心风险或不确定因素（若置信度为低/中，须明确指出）。
4. 给出具体的持仓建议（轻仓/半仓/满仓/观望/止损）及止损触发条件。

## 注意事项
- 所有章节严格基于传入的结构化数据，不引用任何外部或训练知识补充内容。
- 支撑/压力位仅基于当前快照的均线与 BOLL 数据估算，不代表历史形态分析。
- 如果结构化数据存在缺失字段，在"不确定性"章节说明并建议补充。
- 输出语言：中文为主，技术指标名词可中英混写。
- 报告末尾必须有"总结"章节。
"""

# ── 字段常量 ──────────────────────────────────────────────────────────────
_QUOTE_FIELDS = (
    "price", "change_pct", "change_amount", "open", "high", "low",
    "volume", "turnover", "volume_ratio", "pe_ttm", "market_cap", "update_time",
)
_TECH_FIELDS = (
    "ma5", "ma10", "ma20", "ma60", "rsi", "dif", "dea",
    "kdj_k", "kdj_d", "kdj_j", "boll_upper", "boll_mid", "boll_lower",
    "atr", "short_score", "long_score",
)
_FUND_FIELDS = (
    "main_net_inflow", "main_net_inflow_pct", "main_ratio",
    "super_large_net", "large_net", "medium_net", "small_net", "days_continuous",
)
_SELECTOR_FIELDS = (
    "selector_score", "selector_rating", "buy_signals",
    "stop_loss", "take_profit", "stop_loss_pct", "take_profit_pct", "risk_reward_ratio",
)


# ── 数据构建 ──────────────────────────────────────────────────────────────
def _build_prompt(code: str, sentiment: dict, stock_data: dict) -> str:
    """将单只股票数据组装成用户消息"""
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    s  = stock_data
    ti = s.get("tech_indicators") or {}
    ff = s.get("fund_flow") or {}

    payload = {
        "timestamp": ts,
        "code": code,
        "name": s.get("name", ""),
        "market_sentiment": {
            **{k: sentiment.get(k) for k in ("score", "level", "emoji", "description")},
            "stats": sentiment.get("stats", {}),
        },
        "quote":           {k: s.get(k)  for k in _QUOTE_FIELDS},
        "tech_indicators": {**{k: ti.get(k) for k in _TECH_FIELDS}, "macd_hist": ti.get("macd")} if ti is not None else {},
        "fund_flow":       {k: ff.get(k) for k in _FUND_FIELDS} if ff is not None else {},
        **{k: s[k] for k in _SELECTOR_FIELDS if k in s},
    }

    return (
        "## 单股深度分析请求\n"
        f"- 时间戳：{ts}\n"
        f"- 分析标的：{code}  {s.get('name', '')}\n\n"
        "## 结构化市场数据（JSON）\n"
        "```json\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n```\n\n"
        "请按照单股报告结构输出完整深度分析。"
    )


# ── 公共入口 ──────────────────────────────────────────────────────────────
def run_single_analysis(
    code: str,
    sentiment: dict,
    stock_data: dict,
    stream: bool = False,
) -> Union[str, Generator[str, None, None]]:
    """
    针对单只股票执行 LLM 深度分析。

    参数：
        code       — 股票代码，如 "600519"
        sentiment  — 市场情绪字典（score / level / description / stats）
        stock_data — 单只股票数据字典（包含 quote / tech_indicators / fund_flow 等）
        stream     — True 时返回 Generator[str, None, None]，False 时返回完整报告字符串
    """
    print(f"[LLM-单股] 使用后端={_BACKEND} 模型={_MODEL} 标的={code}", flush=True)
    user_msg = _build_prompt(code, sentiment, stock_data)
    if _BACKEND == "deepseek":
        return _run_deepseek(_MODEL, user_msg, stream)
    return _run_gpt(_MODEL, user_msg, stream)


# ── GPT (Responses API + Chat Completions 兜底) ───────────────────────────
def _run_gpt(model: str, user_msg: str, stream: bool) -> Union[str, Generator[str, None, None]]:
    client = _get_gpt_client()
    responses_msgs = [
        {"role": "system", "content": [{"type": "input_text", "text": _SYSTEM_PROMPT}]},
        {"role": "user",   "content": [{"type": "input_text", "text": user_msg}]},
    ]
    chat_msgs = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": user_msg},
    ]
    if stream:
        return _gpt_stream(client, model, responses_msgs, chat_msgs)
    try:
        resp = client.responses.create(model=model, input=responses_msgs)
        return resp.output[0].content[0].text
    except Exception:
        resp = client.chat.completions.create(model=model, messages=chat_msgs, stream=False)
        return resp.choices[0].message.content


def _gpt_stream(client, model: str, responses_msgs: list, chat_msgs: list) -> Generator[str, None, None]:
    try:
        with client.responses.stream(model=model, input=responses_msgs) as s:
            for event in s:
                if hasattr(event, "delta") and hasattr(event.delta, "text"):
                    yield event.delta.text
                elif getattr(event, "type", None) == "response.output_text.delta":
                    yield getattr(event, "delta", "")
        return
    except Exception as e:
        print(f"[LLM] Responses API 流失败，回退 Chat Completions：{e}", flush=True)

    for chunk in client.chat.completions.create(model=model, messages=chat_msgs, stream=True):
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            yield delta.content


# ── DeepSeek (Chat Completions API) ──────────────────────────────────────
def _run_deepseek(model: str, user_msg: str, stream: bool) -> Union[str, Generator[str, None, None]]:
    client = _get_deepseek_client()
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": user_msg},
    ]
    if stream:
        return _deepseek_stream(client, model, messages)
    resp = client.chat.completions.create(model=model, messages=messages, stream=False)
    return resp.choices[0].message.content


def _deepseek_stream(client, model: str, messages: list) -> Generator[str, None, None]:
    for chunk in client.chat.completions.create(model=model, messages=messages, stream=True):
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            yield delta.content


# ── 连通性测试 ────────────────────────────────────────────────────────────
def test_connection() -> bool:
    """发送一条极简请求，验证 API Key 和网络是否正常。"""
    print(f"Backend  : {_BACKEND}")
    print(f"Model    : {_MODEL}")

    if _BACKEND == "gpt":
        print(f"BASE_URL : {_BASE_URL}")
        print(f"API_KEY  : {'已设置 (' + _API_KEY[:8] + '...)' if _API_KEY else '❌ 未设置'}")
        if not _API_KEY:
            print("❌ 未设置 CI_TOKEN 或 OPENAI_API_KEY，请先配置环境变量或 .env 文件。")
            return False
        try:
            resp = _get_gpt_client().responses.create(
                model=_MODEL,
                input=[{"role": "user", "content": [{"type": "input_text", "text": "reply with: ok"}]}],
            )
            print(f"✅ GPT 连通正常，模型回复：{resp.output[0].content[0].text.strip()!r}")
            return True
        except Exception as e:
            print(f"❌ 连接失败：{e}")
            return False
    else:
        print(f"DS_URL   : {_DS_BASE_URL}")
        print(f"DS_KEY   : {'已设置 (' + _DS_API_KEY[:8] + '...)' if _DS_API_KEY else '❌ 未设置'}")
        if not _DS_API_KEY:
            print("❌ 未设置 DEEPSEEK_API_KEY。")
            return False
        try:
            resp = _get_deepseek_client().chat.completions.create(
                model=_MODEL, stream=False,
                messages=[{"role": "user", "content": "reply with: ok"}],
            )
            print(f"✅ DeepSeek 连通正常，模型回复：{resp.choices[0].message.content.strip()!r}")
            return True
        except Exception as e:
            print(f"❌ 连接失败：{e}")
            return False


if __name__ == "__main__":
    test_connection()
