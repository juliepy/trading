# 实时A股数据采集 & AI深度分析工具

> 基于 GPT-4.1 + 东方财富/腾讯实时行情接口，采集 A 股结构化数据并生成专业分析师风格的深度研究报告。

---

## 功能概览

| 功能 | 说明 |
| --- | --- |
| 实时行情快照 | 通过东方财富 push2 接口获取个股最新价、涨跌幅、换手率、量比、PE等 |
| 日 K 线指标 | 通过腾讯 fqkline 接口获取前复权日 K，自动计算 MA5/MA10/MA20、5d/10d/20d 回报 |
| 指数宽度基线 | 拉取上证/深成/创业板指数，包含上涨/下跌家数 |
| GPT-4.1 分析报告 | 将结构化数据发送给 GPT-4.1，输出带检索过程纪要、双逻辑判断、三情景操作的深度报告 |
| 流式输出 | `--stream` 支持逐 token 流式打印，减少等待感 |
| Web 聊天界面 | Streamlit 页面：输入股票名称/代码 → 自动生成 K 线图 → GPT-4.1 流式分析 |

## 程序架构图

```
用户
  │
  ├──── CLI ──────────────────────────────────────────────────
  │       │
  │       ▼
  │     demo.py
  │       ├─── [模式 1] 行情快照（无需 API Key）
  │       │         └── a_share_snapshot.py
  │       │               ├── fetch_quotes()         ← 东方财富 push2 API
  │       │               ├── fetch_index_baseline()  ← 东方财富 指数宽度
  │       │               └── fetch_kline()           ← 腾讯 fqkline API
  │       │
  │       └─── [模式 2] GPT-4.1 深度分析（需要 CI_TOKEN）
  │                 ├── a_share_snapshot.py（同上）
  │                 └── gpt41_analyst.py
  │                       └── OpenAI Client → GPT-4.1（流式）
  │
  └──── Web ──────────────────────────────────────────────────
          │
          ▼
        streamlit_app.py  （streamlit run streamlit_app.py）
          │
          ├── 输入股票名称 / 代码
          ├── a_share_snapshot.py → 抓取行情 + K线 + 指数
          ├── matplotlib → 生成暗色 K 线蜡烛图（st.image）
          └── gpt41_analyst.py → GPT-4.1 流式输出（st.empty）
```

---

## 代码逻辑图

```
                        ┌──────────────┐
                        │   demo.py    │  python demo.py
                        │  主菜单入口   │
                        └──────┬───────┘
                               │
               ┌───────────────┴────────────────┐
               │                                │
               ▼                                ▼
   ┌───────────────────────┐       ┌────────────────────────┐
   │  模式 1：行情快照      │       │  模式 2：AI 深度分析    │
   │  run_snapshot()       │       │  run_ai_analysis()     │
   └──────────┬────────────┘       └───────────┬────────────┘
              │                                │
              ▼                                ▼
   ┌───────────────────────────────────────────────────────┐
   │              a_share_snapshot.py  （数据层）           │
   │                                                       │
   │  parse_codes()  ──►  normalize_code()                 │
   │                                                       │
   │  fetch_quotes()        ──►  东方财富 push2 API         │
   │  fetch_index_baseline() ──►  东方财富 指数宽度          │
   │  fetch_kline()          ──►  腾讯 fqkline（前复权日K） │
   │    └─ _ma()  _ret()         均线 & N日回报             │
   └────────────────────────┬──────────────────────────────┘
                            │ 结构化 JSON 数据
              模式1          │          模式2
    ┌──────────────────────────┐    ┌──────────────────────┐
    │  终端打印 / 保存 JSON      │    │  gpt41_analyst.py    │
    │                          │    │                      │
    │  print_quote()           │    │  _build_user_message │
    │  print_kline_metrics()   │    │        │             │
    │  print_index()           │    │        ▼             │
    └──────────────────────────┘    │  OpenAI Client       │
                                    │  CI_TOKEN ← .env     │
                                    │        │             │
                                    │        ▼             │
                                    │     GPT-4.1          │
                                    │        │             │
                                    │        ▼             │
                                    │  深度研报（流式输出）  │
                                    └──────────────────────┘

                        ┌───────────────────────────┐
                        │     streamlit_app.py       │  streamlit run
                        │   st.chat_input() 输入     │
                        └──────────────┬─────────────┘
                                       │
                                       ▼
                        ┌──────────────────────────────┐
                        │     a_share_snapshot.py      │
                        │  fetch_quotes / kline / idx  │
                        └──────────────┬───────────────┘
                                       │ 结构化 JSON 数据
                         ┌─────────────┴──────────────┐
                         ▼                             ▼
              ┌───────────────────────┐   ┌────────────────────────┐
              │     make_chart()      │   │  stream_gpt_analysis() │
              │  matplotlib K线蜡烛图  │   │  gpt41_analyst.py      │
              │  → st.image()         │   │  → st.empty() 流式输出  │
              └───────────────────────┘   └────────────────────────┘
                                       │
                                       ▼
                        ┌──────────────────────────────┐
                        │       _save_outputs()         │
                        │  outputs/YYYYMMDD_codes.json  │
                        │  outputs/YYYYMMDD_code.png    │
                        │  outputs/YYYYMMDD_report.md   │
                        └──────────────────────────────┘
```

---


├── README.md                   # 本文件
├── demo.py                     # 交互式 CLI 统一入口
├── streamlit_app.py            # Web 聊天界面（推荐）
├── requirements.txt            # 依赖列表
├── scripts/
│   ├── a_share_snapshot.py     # 行情数据抓取（无第三方依赖，Python 3.6+）
│   └── gpt41_analyst.py        # GPT-4.1 分析主程序
└── references/
    ├── eastmoney-fields.md     # 东方财富字段速查
    ├── report-template.md      # 报告模板（分析师长版）
    ├── search-depth-protocol.md# 检索深度协议
    └── source-checklist.md     # 数据源优先级与证据质量分级
```

---

## 快速开始

### 环境要求

- Python 3.8+
- `openai` Python SDK（`gpt41_analyst.py` / 模式2 / Streamlit 页面需要）
- `matplotlib`（K 线图生成需要）
- `streamlit`（Web 界面需要）

```bash
pip install -r requirements.txt
```

### 配置 API 凭证

在项目根目录的 `.env` 文件中填入 Token（程序启动时自动加载）：

```bash
# .env
CI_TOKEN=eyJ...    # JWT Bearer Token（唯一必填项）
```

> `.env` 已加入 `.gitignore`，请勿将真实 Token 提交到版本库。

---

## 使用方法

### Web 聊天界面（推荐）

```bash
streamlit run streamlit_app.py
```

浏览器自动打开后，在底部输入框输入股票名称或代码（支持中文名称、6位代码、多个用逗号分隔），页面将自动：

1. 抓取实时行情 + 近 60 日 K 线 + 大盘指数
2. 渲染暗色主题蜡烛图（含 MA5/10/20、成交量、大盘摘要）
3. GPT-4.1 流式输出深度分析报告

所有历史对话保留在页面上，可继续输入新的股票。

---

### 交互式 CLI 入口

```bash
python demo.py
```

启动后显示主菜单：

```
╔══════════════════════════════════════════════════╗
║   A股数据采集 & AI深度分析工具                   ║
║   A-Share Snapshot + GPT-4.1 Analyst  —  Demo   ║
╚══════════════════════════════════════════════════╝
请选择模式：
  1  行情数据快照（实时行情 + K线，输出结构化数据，无需 API Key）
  2  GPT-4.1 深度分析报告（调用 LLM，需要 API Key）
  0  退出
```

| 选项 | 说明 |
| --- | --- |
| `1` | 输入股票代码，交互式选择是否包含指数/K线，可将结果保存为 JSON |
| `2` | 输入股票代码，交互式配置参数，调用 GPT-4.1 生成深度研报（支持流式输出） |
| `0` | 退出程序 |

---

### 命令行直接调用（高级用法）

**GPT-4.1 端到端分析：**

```bash
python scripts/gpt41_analyst.py \
  --codes 603618,002149,002506 \
  --with-indices --with-kline --kline-days 60 --stream
```

**仅抓取结构化数据（不调用 LLM）：**

```bash
python scripts/a_share_snapshot.py \
  --codes 603618,002149 \
  --with-indices --with-kline --kline-days 60 --pretty
```

**CLI 参数说明：**

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--codes` | 逗号/空格分隔的 6 位股票代码（必填） | — |
| `--with-kline` | 包含日 K 线与 MA/回报指标 | 关闭 |
| `--kline-days` | K 线回望天数 | `60` |
| `--with-indices` | 包含上证/深成/创业板基线与宽度 | 关闭 |
| `--stream` | 流式打印 GPT-4.1 输出（仅 gpt41_analyst） | 关闭 |
| `--pretty` | JSON 美化输出（仅 a_share_snapshot） | 关闭 |

---

## 代码格式支持

`--codes` 参数支持多种格式，内部统一归一化为 6 位数字：

```
603618          # 纯数字
SH603618        # 加交易所前缀
603618.SH       # 常见带后缀格式
603618,002149   # 逗号分隔
"603618 002149" # 空格分隔
```

---

## 报告结构

GPT-4.1 生成的报告遵循以下结构（详见 [references/report-template.md](references/report-template.md)）：

1. **数据摘要** — 结构化行情数据确认
2. **市场情绪底色** — 指数涨跌 + 宽度 + 风格判断
3. **逐股深度分析** — 公司定位 → 市场叙事 → 技术面 → 双逻辑 → 三情景操作 → 证据卡片 → 置信度
4. **组合分层建议** — A/B/C 分层 + 风险集中度
5. **不确定性与自我修正** — 薄弱点 + 下轮修正计划

---

## 数据来源

| 数据 | 来源 | 接口 |
| --- | --- | --- |
| 实时行情 | 东方财富 | `push2.eastmoney.com/api/qt/ulist.np/get` |
| 日 K 线（前复权） | 腾讯财经 | `web.ifzq.gtimg.cn/appstock/app/fqkline/get` |

> 字段说明详见 [references/eastmoney-fields.md](references/eastmoney-fields.md)

---

## 安全说明

- 所有 API 密钥通过环境变量注入，不存储在代码或文件中。
- `a_share_snapshot.py` 无需 API 密钥，仅使用公开行情接口。
- `gpt41_analyst.py` 读取 `CI_TOKEN` 或 `OPENAI_API_KEY`，启动前请确保已设置。
