# A股晨会简报 Skill

面向 A 股交易者的晨会简报生成技能。支持三种报告类型，涵盖日内交易、波段交易和完整全景分析。

---

## 目录结构

```
a-share/
├── SKILL.md                          # AI Agent 入口，路由逻辑与执行流程
├── README.md                         # 本文件
│
├── rules/                            # 通用规则（所有报告类型共用）
│   ├── data-rules.md                 # 数据来源、新鲜度、缺口处理、可读性规则
│   └── scoring.md                    # 影响评分与置信度分解的固定公式
│
├── prompts/                          # 报告规格（按类型选取其一）
│   ├── intraday.md                   # A档 — 日内交易报告规格
│   ├── swing.md                      # B档 — 波段交易报告规格
│   └── full.md                       # C档 — 全量市场框架报告规格
│
├── templates/                        # 输出模板
│   ├── A股晨会简报_A_高可读模板.md
│   ├── A股晨会简报_B_波段模板.md
│   └── A股晨会简报_C_全量模板.md
│
└── scripts/                          # 辅助计算脚本
    ├── pivot.py                      # 经典 Pivot 支撑阻力位计算
    └── scoring.py                    # 完整影响评分 + 置信度计算
```

---

## 报告类型

| 类型 | 适用场景 | 规格文件 |
| ---- | -------- | -------- |
| **A — 日内交易** | 赚钱效应、风格强弱、主线板块、关键位、当日新闻 | `prompts/intraday.md` |
| **B — 波段交易** | 周趋势、板块轮动、北向资金、融资融券、周度新闻 | `prompts/swing.md` |
| **C — 全量报告** | 日内 + 周度 + 衍生品 + 资金 + 事件完整全景 | `prompts/full.md` |

---

## 脚本使用

### Pivot 支撑阻力位

输入前一交易日的最高价、最低价、收盘价，输出 P / R1~R3 / S1~S3：

```bash
python .github/skills/a-share/scripts/pivot.py <high> <low> <close>

# 示例
python .github/skills/a-share/scripts/pivot.py 4622.83 4509.12 4563.54
```

也可作为模块导入：

```python
from scripts.pivot import calc_pivots
levels = calc_pivots(4622.83, 4509.12, 4563.54)
```

### 影响评分 + 置信度

```bash
python .github/skills/a-share/scripts/scoring.py \
  --rsi 48.7 --above-pivot \
  --available 14 --total 20 \
  --consistent 10 --verifiable 12 \
  --gaps 2 --divergences 1 \
  --macro-bull 1 --commodity-bear 1

# 查看全部参数
python .github/skills/a-share/scripts/scoring.py --help
```

---

## 通用约束

- 先结论，后展开。
- 不编造数据，不留无来源数字。
- 缺失项集中披露，不在每个字段重复写"暂缺"。
- 只做市场环境解读，不给买卖建议。
