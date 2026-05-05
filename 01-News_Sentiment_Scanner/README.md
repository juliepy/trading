# NewsSentimentScanner — 中国市场财经新闻情感分析

> 自动抓取中文财经新闻，使用 **GPT-4.1 / DeepSeek** 分析 A 股市场情绪，输出正面 / 负面 / 中性判断及分数。

---

## 功能特性

- **多源新闻抓取**：从东方财富（关键词搜索 + 个股专属新闻）获取最新财经资讯
- **双 LLM 后端**：支持 OpenAI GPT-4.1 与 DeepSeek（V3 / R1），通过 `LLM_MODEL` 一键切换
- **A 股行情快照**：支持按6位股票代码查询实时行情（价格、涨跌幅、PE、换手率等）
- **情感分析**：针对 A 股市场的专业中文情感打分（-1.0 ~ 1.0）
- **市场情绪汇总**：统计正面 / 负面 / 中性文章占比，输出整体市场情绪报告
- **交互式 Demo**：命令行菜单，支持自定义关键词或一键批量分析
- **可扩展关键词**：支持自定义搜索关键词（A股、科技股、新能源等）

---

## 项目结构

```
NewsSentimentScanner/
├── scanner/                    # 核心包
│   ├── __init__.py             # 对外暴露公共 API
│   ├── ai_client.py            # LLM 客户端初始化（GPT / DeepSeek）
│   ├── news_fetcher.py         # 新闻抓取（东方财富关键词 + 个股）+ 行情快照
│   └── sentiment.py            # 情感分析逻辑
├── demo.py                     # 交互式命令行 Demo
├── sentiment_analysis.py       # 批量运行入口
├── requirements.txt            # 依赖列表
├── .env                        # 环境变量（不提交到 Git）
├── .gitignore
└── README.md                   # 本文档
```

---

## 环境要求

- Python 3.9+
- OpenAI API Key **或** DeepSeek API Key（二选一）

---

## 安装

```bash
pip install -r requirements.txt
```

---

## 配置

在项目根目录创建 `.env` 文件（或直接设置 shell 环境变量）：

```dotenv
# ── 统一切换入口 ──────────────────────────────────────────
# 不填则自动根据哪个 Key 存在来决定后端
LLM_MODEL=deepseek-chat        # deepseek-chat | deepseek-reasoner | gpt-4.1 | ...

# ── DeepSeek（推荐，国内访问更稳定）──────────────────────
DEEPSEEK_API_KEY=sk-xxxx
# DEEPSEEK_BASE_URL=https://api.deepseek.com/v1   # 默认值，可不填
# DEEPSEEK_MODEL=deepseek-chat                    # 默认值，可不填

# ── OpenAI ────────────────────────────────────────────────
# OPENAI_API_KEY=sk-xxxx
# OPENAI_BASE_URL=https://api.openai.com/v1       # 默认值，可不填
# OPENAI_MODEL=gpt-4.1                            # 默认值，可不填
```

### 后端选择逻辑

| `LLM_MODEL` 值 | 使用后端 | 必填 Key |
|---|---|---|
| `deepseek-chat` | DeepSeek V3 | `DEEPSEEK_API_KEY` |
| `deepseek-reasoner` | DeepSeek R1 | `DEEPSEEK_API_KEY` |
| `gpt-4.1` 或其他 GPT | OpenAI | `OPENAI_API_KEY` |
| *(不填)* | 若存在 `DEEPSEEK_API_KEY` 则 DeepSeek，否则 GPT | 对应 Key |

---

## 使用方法

### 方式一：交互式 Demo（推荐）

```bash
python demo.py
```

启动后显示主菜单：

```
╔══════════════════════════════════════════════╗
║     中国市场财经新闻情感分析  (GPT-4)        ║
║     NewsSentimentScanner  —  Demo            ║
╚══════════════════════════════════════════════╝
请选择模式：
  1  输入自定义关键词进行分析
  2  使用默认关键词批量分析（A股、科技股、新能源等）
  0  退出
```

| 选项 | 说明 |
|---|---|
| `1` | 输入任意关键词（如"比亚迪"、"半导体"）或6位股票代码，自定义抓取数量（1~50 篇） |
| `2` | 一键批量分析 7 个默认关键词，输出整体市场情绪汇总 |
| `0` | 退出程序 |

### 方式二：直接运行主程序

```bash
python sentiment_analysis.py
```

### 示例输出

```
正在获取 'A股市场' 相关新闻...

  [  1] ▲ 正面  分数: +0.72  |  沪指震荡收涨，科技板块领涨
        来源: 东方财富  发布: 2026-03-25
        链接: https://www.eastmoney.com/...

--- 市场情绪汇总 ---
分析文章总数: 70
正面: 38 篇 (54.29%)
负面: 15 篇 (21.43%)
中性: 17 篇 (24.29%)
```

---

## 自定义关键词

修改 `sentiment_analysis.py` 中 `main()` 函数的 `queries` 列表：

```python
queries = [
    "A股市场",
    "上证指数",
    "科技股",
    "中国经济",
    "人民币汇率",
    "新能源",
    "房地产",
]
```

---

## 程序流程图

```
启动程序
    │
    ▼
显示主菜单
    │
    ├─── [1] 自定义关键词 ──────────────────────────────────┐
    │         │                                             │
    │         ▼                                             │
    │    输入关键词 + 数量                                   │
    │    （支持6位代码：追加个股专属新闻）                   │
    │         │                                             │
    │         ▼                                             │
    │    fetch_news() 抓取新闻                              │
    │    ┌──────────────────────────────┐                   │
    │    │ 东方财富 JSONP 关键词搜索接口 │                   │
    │    │ 东方财富 个股专属新闻接口     │                   │
    │    └──────────────────────────────┘                   │
    │         │                                             │
    │         ▼                                             │
    │    逐条 analyze_sentiment()                           │
    │    (GPT-4.1 / DeepSeek 打分 -1.0 ~ 1.0)             │
    │         │                                             │
    │         ▼                                             │
    │    输出情绪汇总 ◄─────────────────────────────────────┘
    │
    ├─── [2] 默认批量分析
    │         │
    │         ▼
    │    遍历 DEFAULT_QUERIES
    │    (A股/科技股/新能源等)
    │         │
    │         ▼
    │    逐个关键词 fetch_news() + analyze_sentiment()
    │         │
    │         ▼
    │    ┌─────────────────────────────┐
    │    │ 输出各板块情绪分析           │
    │    │ 输出总体情绪汇总（合并）     │
    │    └─────────────────────────────┘
    │
    └─── [0] 退出
```

---

## 核心模块说明

| 函数 | 说明 |
|---|---|
| `fetch_news_eastmoney()` | 调用东方财富 JSONP 搜索接口，返回标题、链接、摘要 |
| `fetch_stock_news_eastmoney()` | 调用东方财富个股新闻接口，获取指定股票的专属新闻 |
| `fetch_stock_quote()` | 从东方财富 push2 接口获取个股实时行情快照（价格、涨跌幅、PE 等） |
| `fetch_news()` | 统一入口，合并关键词搜索与个股专属新闻，控制总数量 |
| `analyze_sentiment()` | 调用 LLM（GPT / DeepSeek），返回 `(score, sentiment)` |
| `summarize_sentiments()` | 汇总所有文章的情感分布并打印报告 |

---

## 注意事项

- 东方财富的接口结构可能随其网站更新而变化，如抓取失败请检查请求参数
- LLM 每次调用会产生 API 费用，建议控制 `num_articles_per_query` 数量
- API Key 请勿提交到版本控制系统，请使用 `.env` 文件管理（已加入 `.gitignore`）
