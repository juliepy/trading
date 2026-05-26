# A股量化选股神器 V2.0

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-2.0+-green.svg)](https://flask.palletsprojects.com)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)]()
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()

> 基于 Flask + 东方财富/腾讯 HTTPS 接口（主）+ 新浪/akshare（备），支持扫描**沪深300**（约250只）、**中证500**（约500只）、**创业板/科创板**（创业板指+科创50成分股），多策略智能选股、**新闻情绪分析** 与 Web 可视化看板。

---



## 版本说明

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-04-20 | 初始版本 |
| v1.1 | 2026-05-05 | 修正数据获取 bug，优化 prompt，界面优化，deepseek-v4 |
| v2.0 | 2026-05-23 | 增加对中证500、创业板/科创板选股的支持；指数池策略推荐标签；AI 分析改为新闻情绪分析（仿 01-News_Sentiment_Scanner）：抓取个股新闻 → 逐条 LLM 情绪打分 → 综合技术指标输出情绪卡片 |

---

## 功能概览

| 功能 | 说明 |
| --- | --- |
| 短线选股（1-5 日） | 基于**历史K线**（近30日）计算 RSI / MACD / KDJ / 布林带 / 量价共振，多指标共振评分 |
| 中长线选股（20-180 日） | 基于**历史K线**（近120日）计算 MA 趋势 / 动量 / OBV / ADX / ATR / 偏离 等 7 维评分 |
| **📰 新闻情绪分析** | 点击「情绪分析」按钮，自动抓取个股相关新闻 → 逐条调用 LLM 打分（仿 01-News_Sentiment_Scanner）→ 综合技术指标生成情绪卡片（正面/负面/中性 + 评分 + 新闻列表）|
| **多指数选股范围** | 页面下拉框切换：**沪深300**（主板蓝筹）/ **中证500**（中盘成长）/ **创业板/科创板**（创业板指+科创50），附策略推荐提示标签 |


---

## 目录结构

```
scripts/
  app/
    selector_app.py          # Flask 入口 (端口 5001)
    llm_analyst.py           # LLM 分析模块（深度研报 + 新闻情绪分析）
    templates/
      index.html             # 主界面
      login.html             # 登录页
  data/
    config.py                # 选股阈值 & 扫描指数配置
    smart_data_source.py     # 数据源适配器
    hybrid_data_source.py    # 多来源行情融合
    stock_cache_db.py        # SQLite 缓存层（stocks/fund_flow/lhb/tech_indicators/history_kline/fundamental）
    lhb_fetcher.py           # 龙虎榜数据
    eastmoney_api.py         # 东方财富 API
  selectors/
    short_term_selector.py   # 短线引擎
    long_term_selector.py    # 中长线引擎
    enhanced_long_term_selector.py  # 增强版（含基本面）
  utils/
    is_trading_time.py       # 交易时段判断
```



## 数据源优先级

| 场景 | 优先顺序 |
|------|----------|
| 实时行情（单只/批量，仅用于展示现价） | 东方财富 HTTPS → 腾讯 HTTPS → 新浪 → akshare |
| 历史K线（**用于选股指标计算**，非实时） | 腾讯 fqkline HTTPS → 东方财富 → akshare |
| 成分股列表 | 东方财富 `index_stock_cons` → 中证官网（备用）；创业板/科创板分别拉取 399006/000688 后合并 |
| 基础信息缓存 miss | 东方财富实时接口自动补填 SQLite 缓存 |
| 基本面数据（ROE/PE/股息率等） | 同花顺 THS 财务接口 → 东方财富个股信息 → **SQLite 缓存 24 小时** |

> **注意**：选股的技术指标（RSI / MACD / KDJ / 布林带等）均基于**历史收盘K线**计算，并非实时 tick 数据。
> 同一天内多次运行选股时，历史K线数据会**自动复用当天内存缓存**，无需重复抓取，显著提速。

> **基本面缓存**：`FundamentalData` 首次查询每只股票时调用同花顺/东方财富接口（约 20s/
 SQLite `fundamental` 表，之后 24 小时内复用缓存（≈0s），大幅加速批量选股。

> 注：新浪/akshare 仅作兜底，服务器需保留系统代理以访问外网。

---


```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python app/selector_app.py
# 访问 http://localhost:5001  
```

### LLM 环境变量示例

```bash
# 二选一：gpt-4.1 / deepseek
LLM_MODEL=deepseek-v4-pro

# DeepSeek（可选）
DEEPSEEK_API_KEY=sk-xxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

# GPT 官方（可选）
# OPENAI_API_KEY=sk-xxxx
# OPENAI_BASE_URL=https://api.openai.com/v1
# OPENAI_MODEL=gpt-4.1

# 企业代理（可选）
# CI_TOKEN=xxxx
# OPENAI_BASE_URL=https://llm-proxy.us-east-2.int.infra.intelligence.webex.com/openai/v1
```

> `app/gpt_analyst.py` 会按 `LLM_MODEL` 自动选择后端。  
> GPT 路径默认优先 Responses API，失败时会自动回退到 Chat Completions API。



## 选股策略说明

| 策略 | type 参数 | 推荐阈值 | 维度 |
|------|-----------|----------|------|
| 短线 | `short` | ≥60分 & 信号≥2 | RSI/KDJ/MACD/布林/量价/资金 |
| 中长线 | `long` | ≥70分 | 趋势/动量/OBV/ADX/ATR/偏离/资金 |
| 增强版 | `enhanced` | ≥65分 | 中长线+基本面+PEG+DMI（基本面数据 SQLite 缓存 24h）|

---

## 代码设计

```
┌─────────────────────────────────────────────────────────────────┐
│                        浏览器 / API 客户端                       │
└──────────┬───────────────────────────┬──────────────────────────┘
           │ POST /api/selector/run    │ POST /api/selector/sentiment
           │ POST /api/selector/report │   (点击「📰 情绪分析」按钮)
           ▼                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     selector_app.py  (Flask)                     │
│  登录鉴权  →  解析 type / top_n  →  实例化对应 Selector          │
└──────┬────────────────┬──────────────────────┬───────────────────┘
       │ type=short     │ type=long             │ type=enhanced
       ▼                ▼                       ▼
┌────────────┐  ┌────────────────┐  ┌─────────────────────────┐
│ ShortTerm  │  │   LongTerm     │  │  EnhancedLongTerm        │
│ Selector   │  │   Selector     │  │  Selector                │
└─────┬──────┘  └──────┬─────────┘  └───────────┬─────────────┘
      │                │                         │
      └────────────────┴────────────┬────────────┘
                                    │ get_index_stocks()
                                    ▼
                        ┌─────────────────────────────┐
                        │   成分股范围（前端下拉选择）   │
                        │  沪深300  ≈250只（主板）      │
                        │  中证500  ≈500只（中盘）      │
                        │  创业板+科创板（成长板块）     │
                        └─────────────┬───────────────┘
                                    │ 逐股 analyze_single_stock()
                                    ▼
              ┌─────────────────────────────────────────────┐
              │               数据获取层                      │
              │                                             │
              │  SmartDataSource                            │
              │    ├─ is_trading_time()  判断交易时段         │
              │    └─ HybridDataSource                      │
              │          ├─ 东方财富 HTTPS (实时主源)        │
              │          ├─ 腾讯 fqkline HTTPS (历史K线)      │
              │          ├─ 新浪财经  (备用)                  │
              │          └─ akshare    (兜底)                  │
              │                                             │
              │  StockCache  (SQLite)                       │
              │    ├─ stock_info      名称/价格/涨跌幅        │
              │    ├─ fund_flow       主力净流入              │
              │    ├─ history_kline   历史K线 (当天复用)       │
              │    └─ fundamental     基本面 (24h TTL)        │
              └─────────────────────┬───────────────────────┘
                                    │
                                    ▼
              ┌─────────────────────────────────────────────┐
              │               指标计算层                      │
              │                                             │
              │  ShortTermIndicators                        │
              │    RSI / KDJ / MACD / 布林带 / 量价 / 资金   │
              │                                             │
              │  AdvancedIndicators  (中长线)                │
              │    趋势 / 动量 / OBV / ADX / ATR / 偏离       │
              │                                             │
              │  AdvancedLongTermIndicators  (增强版技术面)   │
              │    DMI / PEG / 综合信号优化                   │
              │                                             │
              │  FundamentalData  (增强版基本面)              │
              │    ROE / 利润增长 / 股息率 / PEG              │
              └─────────────────────┬───────────────────────┘
                                    │ 评分 → 排序 → TOP N
                                    ▼
                        ┌───────────────────────┐
                        │   选股结果 JSON        │
                        └───────────┬───────────┘
                                    │
               ┌────────────────────┴──────────────────────────┐
               │ 直接返回浏览器                                  │ POST /api/selector/sentiment
               ▼                                               ▼
   ┌───────────────────────┐              ┌────────────────────────────────────┐
   │   JSON 响应返回浏览器   │              │          llm_analyst.py            │
   └───────────────────────┘              │                                    │
                                          │  Step 1  _fetch_stock_news()       │
                                          │    东方财富搜索（curl_cffi Chrome） │
                                          │                                    │
                                          │  Step 2  _analyze_single_news()    │
                                          │    逐条新闻 LLM 情绪打分            │
                                          │    prompt 仿 01-News_Sentiment     │
                                          │    → {sentiment, score, reason}    │
                                          │                                    │
                                          │  Step 3  综合情绪 LLM              │
                                          │    新闻汇总 + 技术指标/资金流/评分  │
                                          │    → {sentiment, score,            │
                                          │       news_summary, tech_alignment,│
                                          │       conclusion, articles[]}      │
                                          └────────────────────────────────────┘
```

---

## AI 综合分析方案（01 + 02 + 03 融合设计，已对齐最新 Prompt）

> 当前「📰 情绪分析」功能已整合 **01** 的新闻情绪流程。
> 下方为三个子项目能力融合后的完整升级方案，供后续迭代参考。

### 三层分析流水线

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Layer 1  数据收集（并行抓取，尽量无阻塞）                               │
│                                                                         │
│  [01] _fetch_stock_news(股票名, 8条)   ──→  articles[]                  │
│  [04] 技术指标（选股器已算）           ──→  RSI/MACD/KDJ/BOLL/ATR       │
│  [04] 资金流向（东方财富补充）         ──→  主力净流入/超大单/连续天数    │
│  [02] fetch_index_baseline()（可选）  ──→  上证/深成/创业板涨跌宽度      │
│  [02] fetch_kline(code, 60)（可选）   ──→  日K线原始数据                 │
└───────────────────────────┬─────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Layer 2  预处理（轻量 LLM + 纯计算，快速）                              │
│                                                                         │
│  [01] _analyze_single_news(title)  ──→  每条新闻 {sentiment,score}      │
│  [01] 情绪汇总                     ──→  正面N/负面N/中性N / 均分         │
│  [03] calc_pivots(H, L, C)         ──→  P / R1~R3 / S1~S3 支撑阻力位    │
│  [03] calc_score(rsi, pivot…)      ──→  影响评分 + 置信度               │
└───────────────────────────┬─────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Layer 3  综合 LLM 分析（主力 LLM，深度研报）                            │
│                                                                         │
│  输入：Layer 1 原始数据 + Layer 2 预处理结果                             │
│  Prompt 原则：证据优先·不编造数字·风险显式提示                             │
│                                                                         │
│  输出结构（对应最新 AI 个股分析 Prompt）：                                │
│    1) 今日行情概览      — 开/收/高/低、涨跌幅、成交量/换手率、指数对比     │
│    2) 今日关键新闻事件  — 公司公告 + 行业/宏观 + 社媒/论坛情绪亮点         │
│    3) 资金与情绪面      — 主力净流入/流出、北向/南向、融资融券变化          │
│    4) 技术面简析        — MA5/10/20/60 位置 + MACD/RSI/KDJ 短期信号       │
│    5) 综合判断与风险    — 1~3日多空倾向 + 风险点 + 是否等待确认信号         │
│                                                                         │
│  结构化输出字段（JSON）：                                                 │
│    sentiment / score / reason                                            │
│    news_summary_text / technical_analysis / fund_flow_analysis           │
│    industry_logic_status / industry_logic_reason                         │
│    trading_logic_status / trading_logic_reason                           │
│    scenario_strong / scenario_mid / scenario_weak                        │
│    impact_score / confidence / confidence_reason                          │
│    one_line_conclusion / tech_alignment / conclusion                     │
└─────────────────────────────────────────────────────────────────────────┘
```

### 各子项目能力映射

| 来源 | 贡献能力 | 在方案中的位置 |
|------|----------|--------------|
| **01** News_Sentiment_Scanner | 新闻抓取（curl_cffi）+ 逐条情绪 LLM 打分 | Layer 1 数据收集 + Layer 2 预处理 |
| **02** Realtime_Analyzer | 实时行情/K线抓取 + 结构化研报输出经验 + 流式输出 | Layer 1（可选行情补充）+ Layer 3 输出组织 |
| **03** Daily_News | Pivot 支撑阻力位计算 + 影响评分公式 + 置信度评估 | Layer 2 纯计算 + Layer 3 证据补充 |
| **04** Stock_Selector | 选股评分/技术指标/资金流（已有）+ Web 展示层 | 数据入口 + 最终呈现 |

### AI个股分析 Prompt（最新）

```text
你是一名专业的股票分析师。请帮我分析 [股票代码或名称]（[市场，如 A股/港股/美股]）在 [今天的日期] 的行情与相关新闻。

请按以下结构输出分析：

1. **今日行情概览**
   - 开盘价、收盘价、最高/最低价
   - 涨跌幅、成交量与换手率
   - 与所属指数（如上证/恒生/标普500）的对比表现

2. **今日关键新闻与事件**
   - 公司公告（业绩、增减持、重大合同等）
   - 行业政策或宏观新闻
   - 社交媒体/论坛情绪亮点（如雪球、推特等）

3. **资金与情绪面**
   - 主力资金净流入/流出
   - 北向/南向资金动向（如适用）
   - 近期融资融券变化

4. **技术面简析**
   - 当前处于主要均线（5/10/20/60日）的位置
   - MACD、RSI或KDJ指标的短期信号

5. **综合判断与风险提示**
   - 短期（1-3日）多空倾向
   - 重点关注的风险点（如解禁、监管、汇率等）
   - 是否需要等待更明确信号

请基于可靠公开信息（如财联社、同花顺、东方财富、Reuters、Bloomberg等），并明确说明数据的假设来源或建议用户自行核实。
```

### 实现优先级建议

| 优先级 | 功能 | 涉及改动 |
|--------|------|---------|
| ★★★ 高 | Layer 2 加入 Pivot 计算（纯 Python，无 LLM 消耗） | 引入 `03/scripts/pivot.py` → `llm_analyst.py` |
| ★★★ 高 | Layer 3 prompt 更新为“今日行情 + 新闻事件 + 资金情绪 + 技术简析 + 风险提示”结构 | 更新 `_STOCK_SENTIMENT_SYSTEM` |
| ★★☆ 中 | Layer 1 并行抓取（news + 行情同时发出） | `asyncio` / `ThreadPoolExecutor` |
| ★☆☆ 低 | 可选接入 02 的大盘指数基线（市场情绪底色） | 新增开关参数 `with_indices` |

---

## 故障排查 / FAQ

### 1. 数据源获取失败

| 现象 | 原因 | 解决方案 |
|------|------|----------|
| `HTTPConnectionPool timeout` | 网络连接超时 | 检查网络连接，或更换数据源优先级 |
| `akshare` 接口返回空 | 数据源临时维护 | 等待片刻后重试，或切换到腾讯/东方财富源 |
| 实时行情延迟 | 非交易时间或数据源限制 | 交易时间（9:30-11:30, 13:00-15:00）重试 |

### 2. 选股结果为空

```bash
# 检查是否交易日
python -c "from utils.is_trading_time import is_trading_day; print(is_trading_day())"

# 清空缓存重新扫描
rm data/stock_cache.db  # 删除 SQLite 缓存文件
```

### 3. LLM / 情绪分析报错

| 错误信息 | 解决方案 |
|----------|----------|
| `401 Unauthorized` | 检查 `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY` 是否正确设置 |
| `RateLimitError` | API 速率限制，等待 60 秒后重试 |
| `Connection timeout` | 检查代理配置或更换 `BASE_URL` |
| 情绪分析返回「暂无新闻数据」 | `curl_cffi` 未安装或东方财富搜索接口超时，运行 `pip install curl_cffi beautifulsoup4` 后重试 |

### 4. 性能优化建议

```bash
# 首次运行较慢（需构建基本面缓存），后续加速 10x+
# 查看缓存状态
python -c "
from data.stock_cache_db import StockCacheDB
db = StockCacheDB()
stats = db.get_cache_stats()
print(f'股票缓存: {stats[\"stock_count\"]} 条')
print(f'基本面缓存: {stats[\"fundamental_count\"]} 条')
"
```

### 5. 常见问题

**Q: 支持哪些选股范围？**  
A: 页面顶部下拉框可直接切换：**沪深300**（默认，主板蓝筹约250只）、**中证500**（中盘成长约500只）、**创业板/科创板**（创业板指+科创50成分股）。每个指数池旁有策略推荐标签（如「推荐短线」），供参考但不限制组合选择。也可修改 `data/config.py` 中的 `SCAN_INDEX` 永久更改默认值。

**Q: 情绪分析需要什么额外依赖？**  
A: 新闻抓取依赖 `curl_cffi`（模拟 Chrome TLS 指纹）和 `beautifulsoup4`，安装命令：
```bash
pip install curl_cffi beautifulsoup4
```
若未安装，点击「📰 情绪分析」时新闻列表为空，但仍会基于技术指标给出降级情绪评分。

**Q: 缓存数据多久更新？**  
A: 基本面数据缓存 24 小时，历史K线当天复用，实时行情无缓存（每次请求最新）。

---



## 免责声明

本工具仅供学习和研究使用，不构成任何投资建议。股市有风险，投资需谨慎。使用本工具产生的任何盈亏均由使用者自行承担。
