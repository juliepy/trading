# A 股 SuperTrend 分析

参照 [supertrend_yaya](../supertrend_yaya/)（黄金白银）项目结构，针对 A 股实现的 **SuperTrend 专用** 趋势分析与回测工具。

当前默认监控：**沪深300ETF**（宽基基准）+ **中国银行**（趋势型个股示例）。

---

## 监控标的（可在 `src/fetch_data.py` 修改）

| Key | 代码 | 名称 | 市场 |
|-----|------|------|------|
| HS300 | 510300 | 沪深300ETF | 上交所 |
| BOC | 601988 | 中国银行 | 上交所 |

```python
# src/fetch_data.py
SYMBOLS = {
    "HS300": {"code": "510300", "market": "1", "name": "沪深300ETF", "is_index": "0"},
    "BOC":   {"code": "601988", "market": "1", "name": "中国银行",   "is_index": "0"},
}
```

---

## 目录结构

```
A_Stock_Trend/
├── run.py               # 主入口：数据更新 + 回测 + 信号摘要
├── app.py               # Flask Web UI（端口 5001）
├── requirements.txt
├── src/
│   ├── fetch_data.py    # 东方财富 + 新浪 + akshare 数据
│   ├── indicators.py    # SuperTrend 指标
│   └── plotter.py       # K 线 + SuperTrend 可视化
├── templates/
│   └── index.html       # Web 页面
├── data/                # 本地 CSV 缓存（{Key}_daily.csv / {Key}_4h.csv）
├── charts/              # K 线图（gitignore）
└── results/             # 回测摘要 + 权益曲线 PNG
    └── results_summary.md
```

---

## 代码架构图

```
                              ┌─────────────────────────────────────┐
                              │              用户入口                │
                              └─────────────────────────────────────┘
                    ┌─────────────────┬─────────────────┬──────────────────┐
                    ▼                 ▼                 ▼                  │
              ┌──────────┐     ┌──────────┐     ┌──────────────┐          │
              │  run.py  │     │  app.py  │     │ src/plotter  │          │
              │ CLI 主入口│     │ Flask UI │     │  .py (CLI)   │          │
              └────┬─────┘     └────┬─────┘     └──────┬───────┘          │
                   │               │ subprocess          │                  │
                   │               │ --plot --charts     │                  │
                   └───────────────┴──────────┬──────────┘                  │
                                              ▼                             │
┌─────────────────────────────────────────────────────────────────────────────┤
│                              run.py 编排层                                   │
│  ┌─────────────┐   ┌─────────────┐   ┌──────────────┐   ┌───────────────┐ │
│  │download_all │ → │ strategy_   │ → │  run_all()   │ → │_print_current_│ │
│  │  数据更新    │   │ supertrend  │   │  向量化回测   │   │signals 信号摘要│ │
│  └─────────────┘   └─────────────┘   └──────────────┘   └───────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
         │                    │                    │                │
         ▼                    ▼                    ▼                ▼
┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐  ┌─────────────┐
│ src/fetch_data  │  │ src/indicators  │  │ src/plotter  │  │  templates/ │
│                 │  │                 │  │              │  │ index.html  │
│ SYMBOLS 标的配置 │  │ supertrend()    │  │ plot_chart() │  │  Web 页面   │
│ 东方财富 HTTP   │  │ ATR / trend     │  │ mplfinance   │  └──────┬──────┘
│ 新浪 HTTP 降级  │  │ buy/sell 信号   │  │ 蜡烛图+ST线  │         │
│ akshare 兜底    │  └────────┬────────┘  └──────┬───────┘         │
│ 增量合并 CSV    │           │                  │                  │
└────────┬────────┘           └────────┬─────────┘                  │
         │                             │                            │
         ▼                             ▼                            │
┌─────────────────┐          ┌─────────────────┐                   │
│    data/*.csv   │─────────→│  OHLCV DataFrame │                   │
│ daily / 4h      │          │  + ST 指标列     │                   │
└─────────────────┘          └────────┬────────┘                   │
                                      │                             │
                    ┌─────────────────┼─────────────────┐           │
                    ▼                 ▼                 ▼           │
            ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
            │ charts/*.png │  │results_summary│  │ results/*.png│   │
            │ K线 daily/4h │  │    .md       │  │  权益曲线     │   │
            └──────────────┘  └──────────────┘  └──────────────┘   │
                    ▲                 ▲                 ▲           │
                    └─────────────────┴─────────────────┴───────────┘
                                      app.py 读取并展示

外部数据源（逐级降级）
  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
  │ 东方财富      │ ──→ │ 新浪 HTTP    │ ──→ │   akshare    │
  │ push2his K线 │     │ getKLineData │     │ stock_zh_a_* │
  │ 日线 / 60min │     │ 单次 ~1023 根│     │ 前复权历史    │
  └──────────────┘     └──────────────┘     └──────────────┘
         │
         │ 60min 聚合
         ▼
      4h K 线
```

**数据流简述**

```
东方财富 → 新浪 → akshare
       ↓  download_all() 增量写入
   data/{标的}_{daily|4h}.csv
       ↓  supertrend(atr=10, mult=3.0)
   trend / buy_signal / sell_signal
       ├─→ plotter  → charts/{标的}_{daily|4h}_chart.png
       └─→ run.py   → results/results_summary.md + results/*.png
```

---

## 快速开始

```bash
cd A_Stock_Trend
pip install -r requirements.txt

# 日常看信号 + K 线图（不跑回测）
python run.py --charts

# 完整回测（增量更新数据 + 写入 results_summary.md）
python run.py

# 回测 + 权益曲线 PNG
python run.py --plot

# 强制全量重新下载（换标的或 4H 数据异常时用）
python run.py --force

# 仅更新数据
python run.py --data-only

# Web UI
python app.py
# 浏览器打开 http://127.0.0.1:5001
```

### CLI 参数一览

| 参数 | 说明 |
|------|------|
| （无） | 增量更新数据 + 回测 + 打印当前信号 |
| `--charts` | 更新数据 + 刷新 K 线图（`charts/`） |
| `--plot` | 回测时额外保存权益曲线 PNG（`results/`） |
| `--force` | 忽略缓存，全量重新下载 |
| `--data-only` | 只更新 CSV，不跑回测 |

> Web UI 点击「运行」等价于 `python run.py --plot --charts`（完整流水线）。

### 单独绘制 K 线图

```bash
python src/plotter.py                  # 全部标的，daily
python src/plotter.py --symbol BOC     # 指定标的
python src/plotter.py --tf 4h          # 4H 周期
python src/plotter.py --bars 100       # 最近 100 根
python src/plotter.py --show           # 弹出预览窗口
```

---

## Web UI

| 功能 | 说明 |
|------|------|
| 回测表格 | 读取 `results/results_summary.md` |
| K 线图 | `charts/{Key}_{daily\|4h}_chart.png` |
| 权益曲线 | `results/` 下 PNG（需 `--plot` 生成） |
| 运行按钮 | 后台执行完整流水线，SSE 实时日志 |
| 启动补图 | `charts/` 为空但 `data/` 有 CSV 时，自动 `--charts` |

---

## SuperTrend 参数

| 参数 | 默认值 |
|------|--------|
| ATR 周期 | 10 |
| ATR 倍数 | 3.0 |
| ATR 算法 | Wilder 平滑 |

**信号规则：** 趋势由空转多 → `buy_signal`；由多转空 → `sell_signal`。

**回测规则：** 仅做多；信号确认后 **下一根 K 线开盘价** 全仓进出。

---

## 数据说明

| 周期 | 来源顺序 | 覆盖范围 | 说明 |
|------|----------|----------|------|
| daily | 东方财富 → 新浪 → akshare | 约 5 年（~1023 根） | 新浪为未复权，与东财前复权略有偏差 |
| 4h | 60min 聚合 | 约 1 年（~512 根 4H） | 新浪单次最多 ~1023 根 60min |

- 本地 CSV 缓存，默认 **4 小时** 内走增量更新
- 4H 不足 **250 根** 时，回测自动 **SKIP**（避免短样本误导）
- 代理环境下东方财富/akshare 可能失败，新浪 HTTP（禁用代理）通常可用

---

## 回测组合

```
SuperTrend × [HS300 | BOC] × [Daily | 4H]  = 4 组
```

结果写入 `results/results_summary.md`；`--plot` 时各组合权益曲线保存为 `results/*.png`。

### 最新回测摘要（2022-03 ~ 2026-05，daily 约 1023 根）

| 策略 | 收益% | 年化% | 回撤% | 胜率% | 交易次 | 夏普 |
|------|------:|------:|------:|------:|-------:|-----:|
| HS300 daily | +28.2 | +9.3 | -21.5 | 46.2 | 13 | 0.58 |
| HS300 4h | +15.7 | +10.9 | -8.7 | 50.0 | 6 | 1.13 |
| BOC daily | +56.5 | +17.3 | -14.7 | 60.0 | 10 | 0.87 |
| BOC 4h | -4.0 | -2.9 | -16.0 | 33.3 | 9 | -0.19 |

> 4H 样本区间短于日线（约 1 年），与 daily 结果不可直接对比。换标的后请重新 `python run.py --force` 刷新数据与结果。

---

## 添加自定义股票

编辑 `src/fetch_data.py` 中的 `SYMBOLS`：

```python
"BYD": {"code": "002594", "market": "0", "name": "比亚迪", "is_index": "0"},
```

| 交易所 | 代码前缀 | `market` |
|--------|----------|----------|
| 上交所 | 6xxxxx、5xxxxx | `"1"` |
| 深交所 | 0xxxxx、3xxxxx | `"0"` |

修改后执行：

```bash
python run.py --force --charts   # 全量拉数据 + 出图
python run.py                    # 回测并更新 results_summary.md
```

---

## 与 supertrend_yaya 的差异

| 项目 | supertrend_yaya | A_Stock_Trend |
|------|-----------------|---------------|
| 标的 | 黄金 / 白银期货 | A 股 ETF + 个股 |
| 指标 | SuperTrend + Yata + Fib | **仅 SuperTrend** |
| 周期 | daily / 4h / 1h | **daily / 4h** |
| 数据源 | Yahoo / akshare | 东方财富 + 新浪 + akshare |
| Web 端口 | 5000 | **5001** |
