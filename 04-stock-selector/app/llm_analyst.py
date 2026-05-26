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


# ── System Prompts ────────────────────────────────────────────────────────

_SYSTEM_PROMPT_SHORT = """\
你是一位专业的A股**短线交易**分析师，遵循严格的"证据优先、过程透明"分析原则。
本次任务为**单只股票短线深度研报**，时间维度为 **1~5 个交易日**。
请严格根据用户提供的结构化数据进行分析，所有结论必须有数据依据，不得捏造或假设任何未在数据中出现的数字。

## 核心原则
1. **证据绑定**：每个关键结论必须引用传入数据中的具体字段值，禁止无依据的主观猜测。
2. **双逻辑分离**：判断必须拆分为 交易逻辑（技术+资金） + 选股逻辑（评分+信号） 两层。
3. **三情景输出**：给出 强/中/弱 三个价格情景及对应操作动作，触发条件须为具体价位或指标值。
4. **不确定性标注**：置信度低于"中"时，必须明确写出不确定因素与修正计划。
5. **ATR 风控优先**：止损以 ATR 为基准（2×ATR），止盈以 3×ATR 为目标，风险回报比须 ≥ 1.5。

## 报告结构（按顺序输出）

### 0) 数据摘要
- 时间戳、股票代码与名称、市场情绪评分。
- 核心行情数据（价格、涨跌幅、量比、PE、市值）。
- 技术指标一览（MA5/10/20、RSI、MACD、KDJ、BOLL、ATR 及 ATR%）。
- 资金流向（主力净流入、超大单/大单净额及占比、连续净流入天数）。
- 短线选股评分（selector_score / selector_rating / buy_signals）。

### 1) 市场情绪底色
- 根据传入的情绪评分（score / level）解读当前市场阶段（亢奋/平稳/恐慌）。
- 短线操作中情绪的顺风/逆风/中性影响，说明是否适合进场。

### 2) 技术面短线解读
- MA5/MA10/MA20 多空排列与价格位置（上方/下方/刚穿越）；MA60 作为中期参考。
- RSI 超买（>70）/超卖（<30）/中性区间及背离信号。
- MACD 金叉/死叉、柱状线收缩/放大；KDJ 交叉与钝化。
- BOLL 开口/收口，价格所处通道位置（上轨突破 / 中轨支撑 / 下轨反弹）。
- 量比异动解读；基于 ATR 给出**次日参考止损价**（现价 − 2×ATR）与**目标价**（现价 + 3×ATR）。
- 估算压力位 / 支撑位 / 失效位（三档，注明为快照估算）。

### 3) 资金面短线解读
- 超大单/大单结构：机构/游资性质判断。
- 主力净流入趋势及连续天数：是否出现加速或减速迹象。
- short_score（若有）解读：短线动量强弱定性。

### 4) 选股器信号解读
- 解读 selector_score / selector_rating 的含义与强弱。
- 列出 buy_signals 中每条信号的触发原因及短线意义。
- 给出 ATR 止损价、ATR 止盈价、风险回报比，并说明是否值得介入。
- 若以上字段不存在，本节注明"选股器数据未提供"。

### 5) 双逻辑判断
- **交易逻辑**（技术面 + 资金面）：成立 / 弱化 / 失效（附具体数据依据）
- **选股逻辑**（评分 + 信号）：成立 / 弱化 / 失效（附具体数据依据）

### 6) 明日三情景动作（1~3 日视角）
| 情景 | 触发条件（具体价位或指标值） | 动作 | 目标位 / 止损位 |
|------|--------------------------|------|----------------|
| 强情景 | 填入具体条件 | 买入/加仓 | 填入具体价位 |
| 中情景 | 填入具体条件 | 持有/观望 | 填入具体价位 |
| 弱情景 | 填入具体条件 | 减仓/止损 | 填入具体价位 |

### 7) 证据卡片
- E1 行情数据（价格/量比/涨跌幅）
- E2 技术指标数据（ATR 及关键均线值须列出具体数字）
- E3 资金流向数据（超大单/大单金额须列出）
- E4 短线选股评分与信号（若无则注明）

### 8) 置信度与不确定性
- 综合置信度：高 / 中 / 低（附原因）
- 最不确定的 2~3 个点
- 可能导致错判的条件（如隔夜利空、大盘跳空等）
- 建议用户补充的数据项

### 9) 总结
输出 3~5 句话的综合结论：
1. 以 **「股票代码 公司名称：当前状态 — 短线建议动作」** 作为开篇句。
2. 说明技术面与选股逻辑是否共振，ATR 止损/止盈价位。
3. 点明短线核心风险（量能不足 / 指标背离 / 市场情绪逆风等）。
4. 给出具体持仓建议（轻仓试探/半仓/观望/止损离场）及触发条件。

## 注意事项
- 所有章节严格基于传入的结构化数据，不引用任何外部或训练知识补充内容。
- 支撑/压力位仅基于当前快照估算，不代表历史形态分析。
- 如果结构化数据存在缺失字段，在"不确定性"章节说明并建议补充。
- 输出语言：中文为主，技术指标名词可中英混写。
- 报告末尾必须有"总结"章节。
"""

_SYSTEM_PROMPT_LONG = """\
你是一位专业的A股**中长线价值投资**分析师，遵循严格的"证据优先、过程透明"分析原则。
本次任务为**单只股票中长线深度研报**，时间维度为 **1~3 个月**。
请严格根据用户提供的结构化数据进行分析，所有结论必须有数据依据，不得捏造或假设任何未在数据中出现的数字。

## 核心原则
1. **证据绑定**：每个关键结论必须引用传入数据中的具体字段值，禁止无依据的主观猜测。
2. **双逻辑分离**：判断必须拆分为 基本面逻辑（估值+成长） + 趋势逻辑（均线+资金） 两层。
3. **三情景输出**：给出 强/中/弱 三个中线价格情景，触发条件须为具体价位或基本面指标值。
4. **不确定性标注**：置信度低于"中"时，必须明确写出不确定因素与修正计划。
5. **宽止损原则**：中长线止损以 **−8%** 为参考（跌破关键支撑则考虑减仓），止盈目标 **+20%**，
   不以单日 ATR 作为止损依据，避免被正常波动震出。

## 报告结构（按顺序输出）

### 0) 数据摘要
- 时间戳、股票代码与名称、市场情绪评分。
- 核心行情数据（价格、涨跌幅、PE_TTM、市值）。
- 基本面一览（ROE、股息率、PEG；若数据中无此字段则注明缺失）。
- 技术趋势一览（MA20/MA60、MACD、BOLL 中轨位置）。
- 资金流向摘要（主力净流入趋势、连续天数）。
- 中长线选股评分（selector_score / selector_rating / buy_signals）。

### 1) 市场情绪底色
- 根据传入的情绪评分（score / level）解读当前市场阶段（牛市/震荡/熊市）。
- 中长线视角下情绪的影响：是否处于布局期、追涨期或观望期。

### 2) 基本面分析
- PE_TTM 横向比较：高估 / 合理 / 低估（以传入数据为准，不引用行业平均值）。
- 股息率（若有）：是否具备持有价值。
- 市值规模：大盘蓝筹 / 中盘 / 小盘，流动性风险评估。
- buy_signals 中基本面类信号（ROE、PEG、股息率等）重点解读。

### 3) 技术趋势分析（中线视角）
- MA20/MA60 多空排列与价格位置；MA60 是否形成支撑或压力。
- MACD 月/周维度趋势研判（以日线数据近似判断）；BOLL 中轨上方/下方。
- 量能结构：近期成交量是否支撑趋势延续。
- 关键支撑位（−8% 止损参考位）与目标压力位（+20% 目标参考位）。

### 4) 资金面中线解读
- 主力连续净流入/流出天数：机构是否在持续建仓或出货。
- 大单/超大单结构：是否有机构性买盘特征。
- long_score（若有）解读：中长线资金认可度定性。

### 5) 选股器信号解读
- 解读 selector_score / selector_rating 的含义与强弱。
- 列出 buy_signals 中每条信号的触发原因及中长线意义。
- 给出中线止损价（现价 × 0.92，即 −8%）、目标价（现价 × 1.20，即 +20%）
  及风险回报比（2.5:1），说明是否值得中线持有。
- 若以上字段不存在，本节注明"选股器数据未提供"。

### 6) 双逻辑判断
- **基本面逻辑**（估值 + 股息 + 成长信号）：成立 / 弱化 / 失效（附具体数据依据）
- **趋势逻辑**（均线 + 资金 + 量能）：成立 / 弱化 / 失效（附具体数据依据）

### 7) 未来 1~3 个月三情景
| 情景 | 触发条件（具体价位或基本面变化） | 动作 | 目标位 / 止损位 |
|------|-------------------------------|------|----------------|
| 强情景 | 填入具体条件 | 建仓/加仓 | 填入具体价位 |
| 中情景 | 填入具体条件 | 持有/定投 | 填入具体价位 |
| 弱情景 | 填入具体条件 | 减仓/止损 | 填入具体价位（−8% 参考） |

### 8) 证据卡片
- E1 行情与基本面数据（PE、市值、价格须列出具体数字）
- E2 技术趋势数据（MA20/MA60/BOLL 中轨须列出具体值）
- E3 资金流向数据（主力净额及连续天数须列出）
- E4 中长线选股评分与信号（若无则注明）

### 9) 置信度与不确定性
- 综合置信度：高 / 中 / 低（附原因）
- 最不确定的 2~3 个点
- 可能导致错判的条件（如业绩变脸、行业政策、市场系统性风险等）
- 建议用户补充的数据项（如季报 ROE、行业景气度等）

### 10) 总结
输出 3~5 句话的综合结论：
1. 以 **「股票代码 公司名称：当前估值状态 — 中线建议动作」** 作为开篇句。
2. 说明基本面逻辑与趋势逻辑是否共振，关键支撑（−8% 止损位）与目标价（+20%）。
3. 点明中线核心风险（估值偏高 / 趋势未确立 / 资金持续流出等）。
4. 给出具体持仓建议（轻仓布局/分批建仓/持有/观望）及止损触发条件。

## 注意事项
- 所有章节严格基于传入的结构化数据，不引用任何外部或训练知识补充内容。
- 中长线止损以 −8% 为参考，不以单日 ATR 为依据，防止正常波动触发止损。
- 支撑/压力位仅基于当前快照的均线与 BOLL 数据估算，不代表历史形态分析。
- 如果结构化数据存在缺失字段，在"不确定性"章节说明并建议补充。
- 输出语言：中文为主，技术指标名词可中英混写。
- 报告末尾必须有"总结"章节。
"""

# 向后兼容别名（旧代码若直接引用 _SYSTEM_PROMPT 仍可用）
_SYSTEM_PROMPT = _SYSTEM_PROMPT_LONG

# ── 字段常量 ──────────────────────────────────────────────────────────────
_QUOTE_FIELDS = (
    "price", "change_pct", "change_amount", "open", "high", "low",
    "volume", "turnover", "volume_ratio", "pe_ttm",
    "market_cap", "float_market_cap",   # 总市值 + 流通市值
    "update_time",
)
_FUNDAMENTAL_FIELDS = (
    "roe",            # 净资产收益率（%）
    "dividend_yield", # 股息率（%）
    "revenue_growth", # 营收同比增长率（%）
    "profit_growth",  # 净利润同比增长率（%）
)
_TECH_FIELDS = (
    "ma5", "ma10", "ma20", "ma60", "rsi", "dif", "dea",
    "kdj_k", "kdj_d", "kdj_j", "boll_upper", "boll_mid", "boll_lower",
    "atr", "short_score", "long_score",
)
_FUND_FIELDS = (
    "main_net_inflow", "main_net_inflow_pct", "main_ratio",
    "super_large_net", "large_net", "medium_net", "small_net",
    "days_continuous",  # 连续净流入/流出天数（正=流入，负=流出）
    "main_net_5day",    # 近5个交易日主力净流入累计（元）
)
_SELECTOR_FIELDS = (
    "selector_score", "selector_rating", "buy_signals",
    "stop_loss", "take_profit", "stop_loss_pct", "take_profit_pct", "risk_reward_ratio",
)


# ── 数据构建 ──────────────────────────────────────────────────────────────
def _build_prompt(code: str, sentiment: dict, stock_data: dict,
                  selector_type: str = "long") -> str:
    """将单只股票数据组装成用户消息"""
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    s  = stock_data
    ti = s.get("tech_indicators") or {}
    ff = s.get("fund_flow") or {}

    fd = s.get("fundamental") or {}
    payload = {
        "timestamp": ts,
        "code": code,
        "name": s.get("name", ""),
        "analysis_mode": "短线（1~5日）" if selector_type == "short" else "中长线（1~3月）",
        "market_sentiment": {
            **{k: sentiment.get(k) for k in ("score", "level", "emoji", "description")},
            "stats": sentiment.get("stats", {}),
        },
        "quote":       {k: s.get(k) for k in _QUOTE_FIELDS},
        "fundamental": {k: fd.get(k) for k in _FUNDAMENTAL_FIELDS},
        "tech_indicators": {**{k: ti.get(k) for k in _TECH_FIELDS}, "macd_hist": ti.get("macd")} if ti is not None else {},
        "fund_flow":   {k: ff.get(k) for k in _FUND_FIELDS} if ff is not None else {},
        **{k: s[k] for k in _SELECTOR_FIELDS if k in s},
    }

    mode_label = "短线" if selector_type == "short" else "中长线"
    return (
        f"## 单股{mode_label}深度分析请求\n"
        f"- 时间戳：{ts}\n"
        f"- 分析标的：{code}  {s.get('name', '')}\n"
        f"- 分析模式：{mode_label}\n\n"
        "## 结构化市场数据（JSON）\n"
        "```json\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n```\n\n"
        f"请按照{mode_label}单股报告结构输出完整深度分析。"
    )


# ── 公共入口 ──────────────────────────────────────────────────────────────
def run_single_analysis(
    code: str,
    sentiment: dict,
    stock_data: dict,
    stream: bool = False,
    selector_type: str = "long",
) -> Union[str, Generator[str, None, None]]:
    """
    针对单只股票执行 LLM 深度分析。

    参数：
        code          — 股票代码，如 "600519"
        sentiment     — 市场情绪字典（score / level / description / stats）
        stock_data    — 单只股票数据字典（包含 quote / tech_indicators / fund_flow 等）
        stream        — True 时返回 Generator[str, None, None]，False 时返回完整报告字符串
        selector_type — "short" 使用短线 Prompt；"long"/"enhanced" 使用中长线 Prompt
    """
    mode = "短线" if selector_type == "short" else "中长线"
    print(f"[LLM-单股] 后端={_BACKEND} 模型={_MODEL} 标的={code} 模式={mode}", flush=True)

    system_prompt = _SYSTEM_PROMPT_SHORT if selector_type == "short" else _SYSTEM_PROMPT_LONG
    user_msg = _build_prompt(code, sentiment, stock_data, selector_type)

    if _BACKEND == "deepseek":
        return _run_deepseek(_MODEL, user_msg, stream, system_prompt)
    return _run_gpt(_MODEL, user_msg, stream, system_prompt)


# ── GPT (Responses API + Chat Completions 兜底) ───────────────────────────
def _run_gpt(model: str, user_msg: str, stream: bool,
             system_prompt: str = _SYSTEM_PROMPT_LONG) -> Union[str, Generator[str, None, None]]:
    client = _get_gpt_client()
    responses_msgs = [
        {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
        {"role": "user",   "content": [{"type": "input_text", "text": user_msg}]},
    ]
    chat_msgs = [
        {"role": "system", "content": system_prompt},
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
def _run_deepseek(model: str, user_msg: str, stream: bool,
                  system_prompt: str = _SYSTEM_PROMPT_LONG) -> Union[str, Generator[str, None, None]]:
    client = _get_deepseek_client()
    messages = [
        {"role": "system", "content": system_prompt},
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


# ── 股票情绪分析（仿 01-News_Sentiment_Scanner 风格）────────────────────────

# 1) 单条新闻情绪（与 01/scanner/sentiment.py 完全一致）
_NEWS_SENTIMENT_SYSTEM = (
    "你是专业的中国股市情感分析师。"
    "分析以下财经新闻对 A 股市场的情感倾向，"
    "仅返回 JSON（不要有其他文字）："
    '{"sentiment": "正面/负面/中性", "score": 浮点数, "reason": "简短理由(30字内)"}'
    "score 范围：-1.0（极度负面）到 1.0（极度正面）。"
)

# 2) 综合情绪（新闻汇总 + 技术指标 + 双逻辑 + 三情景）
_STOCK_SENTIMENT_SYSTEM = (
    "你是一名专业的股票分析师。"
    "请帮我分析 [股票代码或名称]（[市场，如 A股/港股/美股]）在 [今天的日期] 的行情与相关新闻。"
    "请按以下结构完成分析："
    "1. 今日行情概览：开盘价、收盘价、最高/最低价；涨跌幅、成交量与换手率；与所属指数对比表现。"
    "2. 今日关键新闻与事件：公司公告（业绩、增减持、重大合同等）；行业政策或宏观新闻；社交媒体/论坛情绪亮点。"
    "3. 资金与情绪面：主力资金净流入/流出；北向/南向资金动向（如适用）；近期融资融券变化。"
    "4. 技术面简析：当前处于主要均线（5/10/20/60日）的位置；MACD、RSI或KDJ指标的短期信号。"
    "5. 综合判断与风险提示：短期（1-3日）多空倾向；重点风险点（如解禁、监管、汇率等）；是否需要等待更明确信号。"
    "请基于可靠公开信息（如财联社、同花顺、东方财富、Reuters、Bloomberg等），并明确说明数据的假设来源或建议用户自行核实。"
    "所有关键判断必须引用输入中的具体数字或字段，不得编造数据。"
    "仅返回单个 JSON 对象（不要 markdown、不要额外文字）。"
    "JSON 必须包含以下字段（全部必填，缺失时写'数据不足'）："
    "{"
    "\"sentiment\":\"正面/负面/中性\","
    "\"score\":-1.0到1.0浮点数,"
    "\"reason\":\"综合判断核心依据（40字内）\","
    "\"news_summary_text\":\"对应第2部分关键新闻与事件（含信息来源与核实提醒，120字内）\","
    "\"technical_analysis\":\"对应第4部分技术面简析（120字内）\","
    "\"fund_flow_analysis\":\"对应第3部分资金与情绪面（120字内）\","
    "\"industry_logic_status\":\"成立/弱化/失效\","
    "\"industry_logic_reason\":\"产业/宏观逻辑判断依据（60字内）\","
    "\"trading_logic_status\":\"成立/弱化/失效\","
    "\"trading_logic_reason\":\"短期交易逻辑判断依据（60字内）\","
    "\"scenario_strong\":\"强情景：触发条件→动作→目标位\","
    "\"scenario_mid\":\"中情景：触发条件→动作\","
    "\"scenario_weak\":\"弱情景：触发条件→动作→止损位\","
    "\"impact_score\":\"影响评分（0-100）\","
    "\"confidence\":\"高/中/低\","
    "\"confidence_reason\":\"置信度说明（40字内）\","
    "\"one_line_conclusion\":\"代码 名称：状态 — 建议动作\","
    "\"tech_alignment\":\"第1部分行情与第4部分技术信号的一致性简评\","
    "\"conclusion\":\"对应第5部分综合判断与风险提示（120字内）\""
    "}"
    "输出示例（字段名必须完全一致）："
    "{\"sentiment\":\"中性\",\"score\":0.12,\"reason\":\"量价配合一般，消息面中性\","
    "\"news_summary_text\":\"今日公告平淡，行业消息偏中性（来源示例：东方财富/Reuters，需用户复核）\","
    "\"technical_analysis\":\"价格位于MA10上方MA20附近，MACD柱体收敛，RSI中位\","
    "\"fund_flow_analysis\":\"主力小幅净流入，北向资金无明显增量，融资融券变化有限\","
    "\"industry_logic_status\":\"弱化\",\"industry_logic_reason\":\"缺少增量基本面催化\","
    "\"trading_logic_status\":\"成立\",\"trading_logic_reason\":\"短线仍在震荡上沿\","
    "\"scenario_strong\":\"放量突破前高→轻仓跟随→看前高上方\","
    "\"scenario_mid\":\"区间震荡→持有观望\","
    "\"scenario_weak\":\"跌破近两日低点→减仓止损\","
    "\"impact_score\":\"62\",\"confidence\":\"中\",\"confidence_reason\":\"关键字段齐全但趋势不强\","
    "\"one_line_conclusion\":\"000001 平安银行：震荡偏多 — 轻仓跟踪\","
    "\"tech_alignment\":\"行情与技术信号基本一致\","
    "\"conclusion\":\"短期偏震荡偏多，关注放量突破与资金持续性，未确认前不追高\"}"
)

# 分段 Prompt：将大任务拆分为小输出，降低 length 截断概率
_STOCK_PROMPT_NEWS = (
    "你是股票分析师。仅基于输入信息，输出单个 JSON（不要 markdown）。"
    "字段仅包含："
    "{\"sentiment\":\"正面/负面/中性\","
    "\"score\":-1.0到1.0浮点数,"
    "\"reason\":\"20-40字核心依据\","
    "\"news_summary_text\":\"今日关键新闻与事件摘要（含来源与需核实提醒，120字内）\"}"
)

_STOCK_PROMPT_TECH_FUND = (
    "你是股票分析师。仅基于输入信息，输出单个 JSON（不要 markdown）。"
    "字段仅包含："
    "{\"technical_analysis\":\"技术面简析（均线/MACD/RSI/KDJ，120字内）\","
    "\"fund_flow_analysis\":\"资金与情绪面（主力/北南向/两融，120字内）\","
    "\"tech_alignment\":\"行情与技术信号一致性简评（60字内）\"}"
)

_STOCK_PROMPT_DECISION = (
    "你是股票分析师。仅基于输入信息，输出单个 JSON（不要 markdown）。"
    "字段仅包含："
    "{"
    "\"industry_logic_status\":\"成立/弱化/失效\","
    "\"industry_logic_reason\":\"产业/宏观逻辑依据（60字内）\","
    "\"trading_logic_status\":\"成立/弱化/失效\","
    "\"trading_logic_reason\":\"交易逻辑依据（60字内）\","
    "\"scenario_strong\":\"强情景：触发条件→动作→目标位\","
    "\"scenario_mid\":\"中情景：触发条件→动作\","
    "\"scenario_weak\":\"弱情景：触发条件→动作→止损位\","
    "\"impact_score\":\"0-100\","
    "\"confidence\":\"高/中/低\","
    "\"confidence_reason\":\"置信度说明（40字内）\","
    "\"one_line_conclusion\":\"代码 名称：状态 — 建议动作\","
    "\"conclusion\":\"综合判断与风险提示（120字内）\""
    "}"
)


def _llm_call(messages: list, max_tokens: int = 300) -> str:
    """统一 LLM 调用（非流式），返回文本内容字符串。"""
    if _BACKEND == "deepseek":
        client = _get_deepseek_client()
        resp = client.chat.completions.create(
            model=_MODEL, messages=messages, stream=False,
            temperature=0.1, max_tokens=max_tokens,
        )
        finish_reason = getattr(resp.choices[0], "finish_reason", "")
        text = (resp.choices[0].message.content or "").strip()
        print(
            f"[LLM] backend=deepseek model={_MODEL} finish_reason={finish_reason} "
            f"len={len(text)} max_tokens={max_tokens}",
            flush=True,
        )
        if _is_potentially_truncated_json(text):
            retry_tokens = min(max_tokens + 220, 1400)
            print(
                f"[LLM] deepseek 返回疑似截断/空串，重试一次 max_tokens={retry_tokens}",
                flush=True,
            )
            resp2 = client.chat.completions.create(
                model=_MODEL, messages=messages, stream=False,
                temperature=0.1, max_tokens=retry_tokens,
            )
            finish_reason2 = getattr(resp2.choices[0], "finish_reason", "")
            text2 = (resp2.choices[0].message.content or "").strip()
            print(
                f"[LLM] deepseek retry finish_reason={finish_reason2} len={len(text2)}",
                flush=True,
            )
            if text2:
                return text2
        return text
    # GPT：优先 Responses API，失败回退 Chat
    client = _get_gpt_client()
    try:
        resp = client.responses.create(
            model=_MODEL,
            input=[
                {"role": m["role"],
                 "content": [{"type": "input_text", "text": m["content"]}]}
                for m in messages
            ],
        )
        status = getattr(resp, "status", "")
        text = ""
        try:
            text = (resp.output[0].content[0].text or "").strip()
        except Exception:
            text = ""
        print(
            f"[LLM] backend=gpt-responses model={_MODEL} status={status} "
            f"len={len(text)} max_tokens={max_tokens}",
            flush=True,
        )
        if _is_potentially_truncated_json(text):
            retry_tokens = min(max_tokens + 220, 1400)
            print(
                f"[LLM] gpt responses 返回疑似截断/空串，改用 chat 重试 max_tokens={retry_tokens}",
                flush=True,
            )
            resp2 = client.chat.completions.create(
                model=_MODEL, messages=messages, stream=False,
                temperature=0.1, max_tokens=retry_tokens,
            )
            finish_reason2 = getattr(resp2.choices[0], "finish_reason", "")
            text2 = (resp2.choices[0].message.content or "").strip()
            print(
                f"[LLM] gpt chat retry finish_reason={finish_reason2} len={len(text2)}",
                flush=True,
            )
            if text2:
                return text2
        return text
    except Exception as exc:
        print(f"[LLM] gpt responses 失败，回退 chat: {exc}", flush=True)
        resp = client.chat.completions.create(
            model=_MODEL, messages=messages, stream=False,
            temperature=0.1, max_tokens=max_tokens,
        )
        finish_reason = getattr(resp.choices[0], "finish_reason", "")
        text = (resp.choices[0].message.content or "").strip()
        print(
            f"[LLM] backend=gpt-chat model={_MODEL} finish_reason={finish_reason} "
            f"len={len(text)} max_tokens={max_tokens}",
            flush=True,
        )
        if _is_potentially_truncated_json(text):
            retry_tokens = min(max_tokens + 220, 1400)
            print(
                f"[LLM] gpt chat 返回疑似截断/空串，重试一次 max_tokens={retry_tokens}",
                flush=True,
            )
            resp2 = client.chat.completions.create(
                model=_MODEL, messages=messages, stream=False,
                temperature=0.1, max_tokens=retry_tokens,
            )
            finish_reason2 = getattr(resp2.choices[0], "finish_reason", "")
            text2 = (resp2.choices[0].message.content or "").strip()
            print(
                f"[LLM] gpt chat retry finish_reason={finish_reason2} len={len(text2)}",
                flush=True,
            )
            if text2:
                return text2
        return text


def _debug_preview(text: str, limit: int = 220) -> str:
    """调试日志预览：压缩换行并截断，避免日志过长。"""
    if text is None:
        return ""
    one_line = " ".join(str(text).split())
    return one_line[:limit] + ("..." if len(one_line) > limit else "")


def _is_potentially_truncated_json(text: str) -> bool:
    """粗略判断返回是否像被截断的 JSON。"""
    if not text:
        return True
    cleaned = text.strip()
    if not cleaned:
        return True
    if cleaned.startswith("{") and not cleaned.endswith("}"):
        return True
    if cleaned.startswith("[") and not cleaned.endswith("]"):
        return True
    return False


def _parse_sentiment_json(raw: str) -> dict:
    """从 LLM 回复中提取结构化结果，优先 JSON，失败时退化为文本提取。"""
    import re as _re

    def _normalize_result(result: dict) -> dict:
        # 兼容新旧字段命名，避免前端因字段缺失只显示新闻评分
        return {
            "sentiment": result.get("sentiment", "中性"),
            "score": round(float(result.get("score", 0.0)), 2),
            "reason": result.get("reason", ""),
            "news_summary_text": result.get(
                "news_summary_text",
                result.get("news_summary", result.get("key_news_events", "")),
            ),
            "technical_analysis": result.get(
                "technical_analysis",
                result.get("tech_analysis", result.get("technical_brief", "")),
            ),
            "fund_flow_analysis": result.get(
                "fund_flow_analysis",
                result.get("funds_and_sentiment", ""),
            ),
            "industry_logic_status": result.get("industry_logic_status", ""),
            "industry_logic_reason": result.get("industry_logic_reason", ""),
            "trading_logic_status": result.get("trading_logic_status", ""),
            "trading_logic_reason": result.get("trading_logic_reason", ""),
            "scenario_strong": result.get("scenario_strong", ""),
            "scenario_mid": result.get("scenario_mid", ""),
            "scenario_weak": result.get("scenario_weak", ""),
            "impact_score": str(result.get("impact_score", "")),
            "confidence": result.get("confidence", ""),
            "confidence_reason": result.get("confidence_reason", ""),
            "one_line_conclusion": result.get("one_line_conclusion", ""),
            "tech_alignment": result.get(
                "tech_alignment",
                result.get("market_tech_alignment", ""),
            ),
            "conclusion": result.get(
                "conclusion",
                result.get("final_judgement", result.get("risk_and_judgement", "")),
            ),
        }

    print(f"[解析-综合] 原始返回预览: {_debug_preview(raw)}", flush=True)

    # 1) 清理 markdown 代码块
    cleaned = raw.strip()
    cleaned = _re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = _re.sub(r"\s*```$", "", cleaned)

    # 2) 优先尝试直接解析完整文本
    for candidate in (cleaned,):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                print("[解析-综合] 命中路径: 直接 JSON 解析成功", flush=True)
                return _normalize_result(obj)
        except Exception:
            pass

    # 3) 再尝试提取最外层 JSON 片段
    m = _re.search(r"\{[\s\S]*\}", cleaned)
    if m:
        frag = m.group()
        try:
            obj = json.loads(frag)
            if isinstance(obj, dict):
                print("[解析-综合] 命中路径: JSON 片段提取解析成功", flush=True)
                return _normalize_result(obj)
        except Exception:
            pass

    # 4) JSON 失败：从文本中做最小可用提取，尽量填充前端区块
    def _pick(pattern: str, default: str = "") -> str:
        mm = _re.search(pattern, cleaned, _re.I | _re.M)
        if not mm:
            return default
        return (mm.group(1) or "").strip()

    score_txt = _pick(r"score\s*[:：]\s*(-?\d+(?:\.\d+)?)", "0")
    try:
        score = round(float(score_txt), 2)
    except Exception:
        score = 0.0

    sentiment = _pick(r"sentiment\s*[:：]\s*(正面|负面|中性)", "")
    if not sentiment:
        sentiment = "正面" if score > 0.1 else ("负面" if score < -0.1 else "中性")

    # 按新版结构标题抓取段落
    news_summary_text = _pick(r"(?:今日关键新闻与事件|关键新闻与事件)\s*[:：]\s*(.+)")
    technical_analysis = _pick(r"(?:技术面简析|技术面分析)\s*[:：]\s*(.+)")
    fund_flow_analysis = _pick(r"(?:资金与情绪面|资金面分析)\s*[:：]\s*(.+)")
    conclusion = _pick(r"(?:综合判断与风险提示|综合结论|结论)\s*[:：]\s*(.+)")
    one_line_conclusion = _pick(r"(?:一句话结论|one_line_conclusion)\s*[:：]\s*(.+)")

    # 如果标题提取不到，退化为前几行摘要（避免把半截 JSON 当成结论）
    lines = [ln.strip("-* \t") for ln in cleaned.splitlines() if ln.strip()]
    first_line = lines[0] if lines else ""
    second_line = lines[1] if len(lines) > 1 else ""
    looks_like_json_fragment = first_line.startswith("{") or first_line.startswith('"')
    if not one_line_conclusion and lines and not looks_like_json_fragment:
        one_line_conclusion = lines[0][:100]
    if not conclusion and len(lines) > 1 and not second_line.startswith('"'):
        conclusion = lines[1][:140]

    print("[解析-综合] 命中路径: 文本降级提取", flush=True)
    result = {
        "sentiment": sentiment,
        "score": score,
        "reason": "非标准 JSON，已按文本降级提取",
        "news_summary_text": news_summary_text,
        "technical_analysis": technical_analysis,
        "fund_flow_analysis": fund_flow_analysis,
        "industry_logic_status": "",
        "industry_logic_reason": "",
        "trading_logic_status": "",
        "trading_logic_reason": "",
        "scenario_strong": "",
        "scenario_mid": "",
        "scenario_weak": "",
        "impact_score": "",
        "confidence": "",
        "confidence_reason": "",
        "one_line_conclusion": one_line_conclusion,
        "tech_alignment": "",
        "conclusion": conclusion,
    }
    print(
        "[解析-综合] 降级结果字段: "
        f"sentiment={result['sentiment']} score={result['score']} "
        f"news_summary_text={'Y' if bool(result['news_summary_text']) else 'N'} "
        f"technical_analysis={'Y' if bool(result['technical_analysis']) else 'N'} "
        f"fund_flow_analysis={'Y' if bool(result['fund_flow_analysis']) else 'N'} "
        f"conclusion={'Y' if bool(result['conclusion']) else 'N'}",
        flush=True,
    )
    return result


def _parse_news_sentiment_json(raw: str) -> dict:
    """单条新闻专用解析器，避免误把半截 JSON 注入综合字段。"""
    import re as _re
    cleaned = raw.strip()
    cleaned = _re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = _re.sub(r"\s*```$", "", cleaned)

    # 直接 JSON
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            sentiment = obj.get("sentiment", "中性")
            score = round(float(obj.get("score", 0.0)), 2)
            reason = str(obj.get("reason", "")).strip()
            if sentiment not in {"正面", "负面", "中性"}:
                sentiment = "正面" if score > 0.1 else ("负面" if score < -0.1 else "中性")
            return {"sentiment": sentiment, "score": score, "reason": reason}
    except Exception:
        pass

    # JSON 片段
    m = _re.search(r"\{[\s\S]*\}", cleaned)
    if m:
        try:
            obj = json.loads(m.group())
            if isinstance(obj, dict):
                sentiment = obj.get("sentiment", "中性")
                score = round(float(obj.get("score", 0.0)), 2)
                reason = str(obj.get("reason", "")).strip()
                if sentiment not in {"正面", "负面", "中性"}:
                    sentiment = "正面" if score > 0.1 else ("负面" if score < -0.1 else "中性")
                return {"sentiment": sentiment, "score": score, "reason": reason}
        except Exception:
            pass

    # 文本兜底（只保留最小字段）
    mm_score = _re.search(r"score\s*[:：]\s*(-?\d+(?:\.\d+)?)", cleaned, _re.I)
    mm_sent = _re.search(r"sentiment\s*[:：]\s*(正面|负面|中性)", cleaned, _re.I)
    score = round(float(mm_score.group(1)), 2) if mm_score else 0.0
    sentiment = mm_sent.group(1) if mm_sent else ("正面" if score > 0.1 else ("负面" if score < -0.1 else "中性"))
    return {"sentiment": sentiment, "score": score, "reason": "新闻情绪解析降级"}


def _merge_non_empty(base: dict, patch: dict) -> dict:
    """将 patch 的非空字段合并进 base。"""
    out = dict(base)
    for k, v in (patch or {}).items():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        out[k] = v
    return out


def _fetch_stock_news(keyword: str, num: int = 8) -> list:
    """
    从东方财富抓取个股相关新闻（与 01/scanner/news_fetcher.py 逻辑相同）。
    返回 [{"title": str, "published": str, "source": str}, ...]
    失败时返回空列表。
    """
    import time as _time
    import urllib.parse as _up

    try:
        from curl_cffi import requests as _cffi
        param_data = {
            "uid": "", "keyword": keyword,
            "type": ["cmsArticleWebOld"],
            "client": "web", "clientType": "web", "clientVersion": "curr",
            "param": {"cmsArticleWebOld": {"from": 0, "size": num, "oneImageFlow": True}},
        }
        params = {
            "param": json.dumps(param_data, ensure_ascii=False),
            "cb": "cb",
            "_": str(int(_time.time() * 1000)),
        }
        resp = _cffi.get(
            "https://search-api-web.eastmoney.com/search/jsonp",
            params=params,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
                "Referer": "https://www.eastmoney.com/",
            },
            timeout=10,
            impersonate="chrome120",
        )
        import re as _re2
        match = _re2.search(r"\((.+)\)\s*$", resp.text, _re2.DOTALL)
        if match:
            data = json.loads(match.group(1))
            raw_list = data.get("result", {}).get("cmsArticleWebOld", [])
            items = raw_list if isinstance(raw_list, list) else raw_list.get("data", [])
            return [
                {
                    "title":     item.get("title", "").strip(),
                    "published": item.get("date", ""),
                    "source":    "东方财富",
                }
                for item in items if item.get("title")
            ][:num]
    except Exception as exc:
        print(f"[新闻] 抓取失败({keyword}): {exc}", flush=True)
    return []


def _analyze_single_news(title: str) -> dict:
    """对单条新闻标题做情绪分析（与 01/scanner/sentiment.py 完全一致）。"""
    if not title.strip():
        return {"sentiment": "中性", "score": 0.0, "reason": ""}
    try:
        raw = _llm_call([
            {"role": "system", "content": _NEWS_SENTIMENT_SYSTEM},
            {"role": "user",   "content": f"新闻：{title}"},
        ], max_tokens=300)
        result = _parse_news_sentiment_json(raw)
        print(
            "[解析-新闻] "
            f"title={_debug_preview(title, 36)} "
            f"sentiment={result.get('sentiment')} "
            f"score={result.get('score')} "
            f"reason={_debug_preview(result.get('reason', ''), 60)}",
            flush=True,
        )
        return result
    except Exception as exc:
        print(f"[LLM-新闻情绪] 分析失败: {exc}", flush=True)
        return {"sentiment": "中性", "score": 0.0, "reason": "分析失败"}


def analyze_stock_sentiment(
    code: str,
    stock_data: dict,
    selector_type: str = "long",
    num_news: int = 8,
) -> dict:
    """
    仿 01-News_Sentiment_Scanner 完整流程，对单只股票做综合情绪分析：
      1. 用股票名称抓取相关新闻
      2. 逐条调用 LLM 分析新闻情绪（与 01 sentiment.py 相同 prompt）
      3. 汇总新闻情绪分布
      4. 结合技术指标/资金流/评分，调用 LLM 生成综合情绪结论

    返回：
        {
          "sentiment": "正面|负面|中性",
          "score": float,
          "reason": str,
          "news_score": float,          # 新闻平均分
          "news_summary": {"正面":n, "负面":n, "中性":n},
          "articles": [{"title", "published", "sentiment", "score", "reason"}, ...]
        }
    """
    s = stock_data
    name = s.get("name") or code
    ti = s.get("tech_indicators") or {}
    ff = s.get("fund_flow") or {}
    mode = "短线（1~5日）" if selector_type == "short" else "中长线（1~3月）"

    # ── Step 1: 抓新闻 ────────────────────────────────────────────────────────
    print(f"[情绪分析] {code} {name} 正在抓取新闻…", flush=True)
    articles = _fetch_stock_news(name, num_news)
    if not articles:
        # 备用：用股票代码再搜一次
        articles = _fetch_stock_news(code, num_news)
    print(f"[情绪分析] {code} 获取到 {len(articles)} 条新闻", flush=True)

    # ── Step 2: 逐条情绪分析（与 01 完全一致）────────────────────────────────
    news_summary = {"正面": 0, "负面": 0, "中性": 0}
    analyzed_articles = []
    scores = []
    for art in articles:
        result = _analyze_single_news(art["title"])
        label = result["sentiment"]
        news_summary[label] = news_summary.get(label, 0) + 1
        scores.append(result["score"])
        analyzed_articles.append({**art, **result})
        arrow = "▲" if label == "正面" else ("▼" if label == "负面" else "■")
        print(f"  [{arrow} {label}  {result['score']:+.2f}] {art['title'][:40]}", flush=True)

    news_score = round(sum(scores) / len(scores), 2) if scores else 0.0
    print(f"[情绪分析] {code} 新闻均分={news_score}  分布={news_summary}", flush=True)

    # ── Step 3: 综合情绪（新闻 + 技术指标）──────────────────────────────────
    tech_summary = (
        f"现价：{s.get('price')}  涨跌幅：{s.get('change_pct')}%\n"
        f"RSI：{ti.get('rsi')}  MACD柱：{ti.get('macd')}  "
        f"KDJ-K：{ti.get('kdj_k')}  布林上轨：{ti.get('boll_upper')} 下轨：{ti.get('boll_lower')}\n"
        f"主力净流入：{ff.get('main_net_inflow')}元  连续：{ff.get('days_continuous')}天\n"
        f"选股评分：{s.get('selector_score')}  评级：{s.get('selector_rating')}  "
        f"策略：{mode}"
    )
    combined_msg = (
        f"股票：{code} {name}\n\n"
        f"【新闻情绪汇总】共{len(articles)}条  "
        f"正面{news_summary['正面']}条 负面{news_summary['负面']}条 中性{news_summary['中性']}条  "
        f"新闻平均分：{news_score:+.2f}\n\n"
        f"【技术指标与评分】\n{tech_summary}"
    )
    print(
        f"[LLM-综合情绪] {code} 提示词用户输入预览: {_debug_preview(combined_msg, 420)}",
        flush=True,
    )
    try:
        # A) 新闻与总体情绪
        msg_news = (
            f"股票：{code} {name}\n"
            f"新闻汇总：正面{news_summary['正面']} 负面{news_summary['负面']} 中性{news_summary['中性']} "
            f"新闻均分={news_score:+.2f}\n"
            f"新闻标题列表：\n" + "\n".join([f"- {a.get('title', '')}" for a in analyzed_articles[:8]])
        )
        raw_news = _llm_call(
            [
                {"role": "system", "content": _STOCK_PROMPT_NEWS},
                {"role": "user", "content": msg_news},
            ],
            max_tokens=700,
        )
        print(f"[LLM-综合情绪] {code} 分段A原始预览: {_debug_preview(raw_news, 280)}", flush=True)
        part_news = _parse_sentiment_json(raw_news)

        # B) 技术与资金
        msg_tech_fund = (
            f"股票：{code} {name}\n"
            f"{tech_summary}\n"
            "请输出技术面简析 + 资金与情绪面 + 技术一致性简评。"
        )
        raw_tech = _llm_call(
            [
                {"role": "system", "content": _STOCK_PROMPT_TECH_FUND},
                {"role": "user", "content": msg_tech_fund},
            ],
            max_tokens=760,
        )
        print(f"[LLM-综合情绪] {code} 分段B原始预览: {_debug_preview(raw_tech, 280)}", flush=True)
        part_tech = _parse_sentiment_json(raw_tech)

        # C) 判断、情景与风险
        msg_decision = (
            f"股票：{code} {name}\n"
            f"已知情绪结论：sentiment={part_news.get('sentiment')} score={part_news.get('score')} "
            f"reason={part_news.get('reason')}\n"
            f"已知技术结论：{part_tech.get('technical_analysis', '')}\n"
            f"已知资金结论：{part_tech.get('fund_flow_analysis', '')}\n"
            "请给出短期1-3日综合判断、风险提示与三情景。"
        )
        raw_decision = _llm_call(
            [
                {"role": "system", "content": _STOCK_PROMPT_DECISION},
                {"role": "user", "content": msg_decision},
            ],
            max_tokens=900,
        )
        print(f"[LLM-综合情绪] {code} 分段C原始预览: {_debug_preview(raw_decision, 280)}", flush=True)
        part_decision = _parse_sentiment_json(raw_decision)

        # 合并分段结果
        overall = {}
        overall = _merge_non_empty(overall, part_news)
        overall = _merge_non_empty(overall, part_tech)
        overall = _merge_non_empty(overall, part_decision)

        # 保证基础情绪字段存在
        if not overall.get("sentiment"):
            overall["sentiment"] = "正面" if news_score > 0.1 else ("负面" if news_score < -0.1 else "中性")
        if overall.get("score", 0.0) == 0.0 and news_score != 0.0:
            overall["score"] = news_score
        if not overall.get("reason"):
            overall["reason"] = f"综合分析部分降级，参考新闻均分 {news_score:+.2f}"

        print(
            f"[LLM-综合情绪] {code} 解析后: "
            f"sentiment={overall.get('sentiment')} score={overall.get('score')} "
            f"reason={_debug_preview(overall.get('reason', ''), 70)} "
            f"news_summary_text={'Y' if bool(overall.get('news_summary_text')) else 'N'} "
            f"technical_analysis={'Y' if bool(overall.get('technical_analysis')) else 'N'} "
            f"fund_flow_analysis={'Y' if bool(overall.get('fund_flow_analysis')) else 'N'} "
            f"conclusion={'Y' if bool(overall.get('conclusion')) else 'N'}",
            flush=True,
        )
    except Exception as exc:
        print(f"[LLM-综合情绪] {code} 失败: {exc}", flush=True)
        # 降级：直接用新闻分
        overall = {
            "sentiment": "正面" if news_score > 0.1 else ("负面" if news_score < -0.1 else "中性"),
            "score": news_score,
            "reason": f"新闻均分 {news_score:+.2f}，技术分析暂不可用",
            "news_summary_text": "",
            "technical_analysis": "",
            "fund_flow_analysis": "",
            "industry_logic_status": "数据不足",
            "industry_logic_reason": "综合分析失败，无法判定",
            "trading_logic_status": "数据不足",
            "trading_logic_reason": "综合分析失败，无法判定",
            "scenario_strong": "",
            "scenario_mid": "",
            "scenario_weak": "",
            "impact_score": "",
            "confidence": "低",
            "confidence_reason": "综合分析调用失败，降级为新闻均分",
            "one_line_conclusion": f"{code} {name}：中性 — 观望",
            "tech_alignment": "",
            "conclusion": f"新闻均分 {news_score:+.2f}，技术分析暂不可用",
        }
        print(f"[LLM-综合情绪] {code} 触发异常降级，使用新闻均分回退", flush=True)

    final_result = {
        "sentiment":    overall["sentiment"],
        "score":        overall["score"],
        "reason":       overall["reason"],
        "news_summary_text": overall.get("news_summary_text", ""),
        "technical_analysis": overall.get("technical_analysis", ""),
        "fund_flow_analysis": overall.get("fund_flow_analysis", ""),
        "industry_logic_status": overall.get("industry_logic_status", ""),
        "industry_logic_reason": overall.get("industry_logic_reason", ""),
        "trading_logic_status": overall.get("trading_logic_status", ""),
        "trading_logic_reason": overall.get("trading_logic_reason", ""),
        "scenario_strong": overall.get("scenario_strong", ""),
        "scenario_mid": overall.get("scenario_mid", ""),
        "scenario_weak": overall.get("scenario_weak", ""),
        "impact_score": overall.get("impact_score", ""),
        "confidence": overall.get("confidence", ""),
        "confidence_reason": overall.get("confidence_reason", ""),
        "one_line_conclusion": overall.get("one_line_conclusion", ""),
        "tech_alignment": overall.get("tech_alignment", ""),
        "conclusion": overall.get("conclusion", ""),
        "news_score":   news_score,
        "news_summary": news_summary,
        "articles":     analyzed_articles,
    }
    print(
        f"[LLM-综合情绪] {code} 最终返回: "
        f"sentiment={final_result['sentiment']} score={final_result['score']} "
        f"news_score={final_result['news_score']} articles={len(final_result['articles'])}",
        flush=True,
    )
    return final_result


if __name__ == "__main__":
    test_connection()
