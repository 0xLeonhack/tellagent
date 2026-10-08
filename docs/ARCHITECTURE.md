# ARCHITECTURE

tellagent 的技术设计。产品定位见 [../README.md](../README.md)。

---

## 一、六条设计原则

### 原则一：代码计算，Jev 判断

```text
代码负责：采集 · 去重 · 时间对齐 · 窗口计算 · 百分位 · 异常检测 · 结果评估
Jev 负责：状态判断 · 证据关系 · 显著性 · 研究优先级
LLM 负责：基于固定证据撰写短摘要
```

收益率、波动率、相关性、百分位和变化点都是确定性计算，不能交给模型。

### 原则二：让 Jev 持续看，而不是偶尔看

Jev 快、便宜、输出结构化概率，它最适合做持续判断层。

每 5 分钟生成一份紧凑的 `MarketStateFrame`，BTC 和 ETH 各调用一次 Jev。系统保存每个问题的完整概率，而不只保存最终选项，由此形成 `JudgmentStream`。

事件触发依据不只是“本次答案是什么”，还包括：

- 概率在短时间内显著跃迁
- 某种状态连续多帧维持高概率
- 两种互斥解释同时升高
- Jev 判断与确定性 detector 发生冲突
- 判断置信度持续下降

昂贵的 investigator 只在事件越过 policy 时运行。

### 原则三：原始观测不可变，修订产生新版本

系统必须保存“当时看到了什么”。同一来源对历史值的修订不能覆盖旧值，只能创建新 revision。

所有判断都记录原始观测、特征定义、detector、问题集、模型与 policy 的版本。

### 原则四：事件来自证据关系，不来自单指标阈值

单指标异常只是 `Anomaly`。只有多个异常形成支持、反向或缺失关系，或者 JudgmentStream 本身发生状态转换后，才能生成 `MarketEvent`。

### 原则五：每个结论可证伪、可复盘

研究摘要必须给出支持证据、反向证据、缺失证据、数据限制和失效条件。事件在未来固定 horizon 自动复盘，失败样本不得删除。

### 原则六：研究与执行隔离

系统不保存交易权限，不提供下单工具，也不把研究优先级自动翻译成仓位建议。

---

## 二、系统边界

### 首版资产

- BTC
- ETH
- ETH/BTC 相对关系

### 数据域

| 数据域 | 首选来源 | 首版指标 |
|---|---|---|
| 现货 | Coinbase | OHLCV、trade、bid/ask |
| 永续与期货 | Deribit | mark、index、funding、open interest、volume、basis |
| Bitcoin 链上 | Bitcoin Core | block、mempool、fee、difficulty |
| Ethereum 链上 | Execution/Beacon API | block、gas、base fee、blob、validator 状态 |

链上数据放在阶段 3。阶段 0–2 先证明现货、衍生品与持续判断流有价值。

### 非目标

- 毫秒级或盘口级高频策略
- 全币种扫描器
- 钱包地址标签平台
- 新闻聚合和社交情绪
- 自动交易与组合管理
- 无证据的价格方向预测

---

## 三、总体架构

```text
                         ┌─────────────────────┐
Coinbase ─┐              │ immutable raw store │
Deribit  ─┼→ collectors ─┤ observations        │
BTC node ─┤              │ source revisions    │
ETH node ─┘              └──────────┬──────────┘
                                    ▼
                          normalization + QA
                                    ▼
                        feature engine + baseline
                                    ▼
                           MarketStateFrame
                              ┌─────┴─────┐
                              ▼           ▼
                    deterministic       Jev continuous
                       detectors         judgment
                              └─────┬─────┘
                                    ▼
                       evidence graph + event builder
                                    ▼
                     policy ────────┬───────────┐
                                    ▼           ▼
                              investigator    silent log
                                    ▼
                           inbox / daily brief
                                    ▼
                      6h / 24h / 7d outcome review
                                    ▼
                           calibration reports
```

首版使用模块化单体。采集、Jev、门控、强分析和 JSONL 记忆共享同一代码库和 schema，不拆微服务，也不要求数据库。

---

## 四、核心数据模型

### `Observation`

不可变的原始观测。

```text
id
asset                 BTC | ETH | ETH/BTC
source                coinbase | deribit | bitcoin_core | ethereum
instrument
metric
value
source_time
available_time        系统首次可以看到它的时间
received_time
revision
quality_flags[]
payload_ref
collector_version
```

`source_time` 与 `available_time` 必须分开。历史回放只能读取 `available_time <= replay_time` 的数据。

### `Feature`

```text
id
asset
feature_name
window
value
as_of
observation_ids[]
definition_version
quality_flags[]
```

### `MarketStateFrame`

Jev 每次看到的完整、紧凑、可重放状态。

```text
id
asset
as_of
price_state
spot_state
leverage_state
volatility_state
cross_asset_state
onchain_state
anomalies[]
missing_inputs[]
quality_summary
feature_ids[]
schema_version
```

Frame 只包含归一化数值、方向、历史百分位和必要说明，不包含长时间序列。

### `ContinuousJudgment`

```text
frame_id
question_id
selected_value
probabilities
confidence
latency_ms
input_tokens
estimated_cost
provider
model_version
question_set_version
created_at
```

连续判断是一级数据资产，必须像行情一样可查询和回放。

### `Anomaly`

```text
feature_id
detector
direction
severity
historical_percentile
robust_zscore
started_at
persistence
baseline_version
```

### `MarketEvent`

```text
id
asset
event_type
opened_at
updated_at
status                open | developing | resolved | invalidated
anomaly_ids[]
judgment_ids[]
supporting_evidence[]
contradicting_evidence[]
missing_evidence[]
quality_summary
snapshot_id
```

### `OutcomeReview`

```text
event_id
horizon               6h | 24h | 7d
reviewed_at
realized_return
realized_volatility
max_adverse_move
max_favorable_move
oi_change
funding_change
event_persisted
event_invalidated
review_version
```

---

## 五、采集与数据质量

### Provider 接口

```python
class MarketDataProvider(Protocol):
    def fetch_backfill(self, request: BackfillRequest) -> list[RawRecord]: ...
    def fetch_incremental(self, cursor: Cursor) -> FetchResult: ...
    def health(self) -> ProviderHealth: ...
```

业务代码不能依赖 Coinbase 或 Deribit 的原始字段名。provider 只负责保真抓取并转换为统一 Observation。

### 幂等与补数

幂等键至少包含：

```text
source + instrument + metric + source_time + revision
```

采集器必须处理重复消息、WebSocket 断线、REST 补数、时间戳乱序、延迟到达、历史修订和空窗口。

缺失值不做静默前向填充。每次填充都必须成为显式 Feature，并携带质量标记。

### 数据质量门

以下情况禁止产生高优先级事件：

- 关键来源在窗口内缺失
- 现货与衍生品时钟偏差超过阈值
- 单一交易所出现无法交叉验证的极值
- 回补数据在事件时间之后才可用
- 指标定义或合约规格发生变化

---

## 六、特征引擎

首版只使用易解释、可回放的特征。

### 价格与现货

- log return：5m、1h、6h、24h、7d
- realized volatility：6h、24h、7d
- volume change 与历史百分位
- bid/ask spread
- spot volume share
- BTC/ETH return correlation
- ETH/BTC relative strength

### 衍生品

- open interest change：1h、6h、24h
- funding 当前值、变化和历史百分位
- perpetual premium
- annualized futures basis
- derivatives volume / spot volume
- price 与 OI 的联合状态

### 链上（阶段 3）

BTC：

- mempool size 与 fee pressure
- mean block interval
- difficulty 与 hash-rate proxy
- transaction count / volume 的稳健变化

ETH：

- gas used 与 base fee
- burn 与净发行
- blob gas 与 blob usage
- validator entry / exit 状态
- staking deposit / withdrawal

### 基线

每个特征至少维护 30 天与 180 天滚动分布、同一 UTC 小时的季节性基线、median/MAD、percentile 和数据覆盖率。

均值和标准差可以作为辅助，但不应成为厚尾市场的唯一异常依据。

---

## 七、Jev 持续判断层

### 调用节奏

默认每 5 分钟、每个资产调用一次。两种资产每天最多产生 576 次常规调用。BTC 与 ETH 的问题可以共享 schema，但输入状态独立。

实际成本、延迟和限流必须通过 telemetry 测量，不能只依赖供应商标价。系统设置每日调用预算；预算不足时自动降频到 15 分钟，但不丢失确定性特征和 detector。

### 问题集

每个问题独立判断，代码组合概率：

```text
market_stress         Score: calm / watch / stressed / extreme
leverage_dominance    Noul: 当前变化是否主要由衍生品杠杆驱动
spot_confirmation     Score: absent / weak / partial / strong
signal_conflict       Score: aligned / mixed / conflicting / sharply_conflicting
state_persistence     Choice: transient / developing / persistent / unclear
research_priority     Score: background / monitor / investigate_now
```

问题使用带语义锚点的等级，不使用无定义的 1–10 分。

### 判断流特征

事件引擎对 JudgmentStream 再做确定性计算：

- probability delta：1 帧、3 帧、12 帧
- probability EWMA
- 连续越线帧数
- 状态翻转次数
- confidence trend
- Jev 与 rule-based detector 的 disagreement

单次高概率不直接叫醒 investigator。至少满足“跃迁、持续、冲突”之一，并通过数据质量门。

### Provider 抽象

```python
class JudgmentProvider(Protocol):
    def judge(self, frame: MarketStateFrame) -> list[ContinuousJudgment]: ...
```

实现至少包括：

- `JevProvider`
- `RuleBasedProvider`
- `RecordedProvider`，用于可重复测试
- 可选通用 LLM baseline

Jev 处于 early-access 阶段，架构不能把它变成不可替换的基础设施。

---

## 八、事件检测

### 1. 杠杆驱动上涨或下跌

```text
价格显著变化
+ OI 同方向快速增长
+ funding / premium 进入极端区间
+ derivatives volume 增长快于 spot
+ leverage_dominance 概率持续升高
```

反向证据：现货成交同步显著扩大。

### 2. 去杠杆

```text
价格快速变化
+ OI 明显下降
+ funding 回归中性或反转
```

### 3. 现货与衍生品背离

spot 与 perpetual 的成交、价格或基差不同步，且 signal_conflict 持续升高。

### 4. 波动率扩张

短窗口 realized volatility 穿越长期高百分位并得到成交量确认。期权接入后增加 implied / realized divergence。

### 5. BTC/ETH 分化

ETH/BTC 异常变化，同时 BTC、ETH 自身趋势或波动结构不同。

### 6. 链上与市场背离

价格或杠杆显著变化，但链上使用、费用或资金活动没有确认。

detector 只产生事实与证据关系，不产生“应该买入/卖出”的结论。

---

## 九、证据图与事件生命周期

```text
Observation → Feature → Anomaly ───────────┐
                                           ▼
MarketStateFrame → ContinuousJudgment → MarketEvent
                                           ↑
                              supports | contradicts | missing
```

事件不是每 5 分钟重复创建。相同资产、类型和方向在冷却窗口内合并更新：

```text
open → developing → resolved
                  ↘ invalidated
```

事件更新时保存新 snapshot，历史 snapshot 不覆盖。

---

## 十、策略与 investigator

### PolicyEngine

PolicyEngine 综合以下信息决定动作：

- research priority 的概率及变化速度
- materiality 和 persistence
- 数据完整度
- 事件是否首次出现或继续发展
- 用户的提醒预算
- 同类事件最近的误报率

低优先级事件仍然保存，只是不主动通知。后台保持高召回，前台用 Top-K 和通知预算控制噪音。

### Investigator 工具

```text
read_event(event_id)
read_evidence(event_id, snapshot_id)
compare_history(event_type, asset, window)
read_judgment_stream(question_id, asset, range)
read_metric(metric, asset, range)
```

investigator 不直接访问开放网页，不临时寻找新闻原因，也不修改证据。

### 输出契约

```text
标题
事实摘要
当前判断
支持证据
反向证据
缺失证据
数据限制
失效条件
来源与时间
```

每个自然语言断言必须引用一个 evidence ID。无法引用的句子不能进入最终摘要。

---

## 十一、自动复盘

`OutcomeReviewer` 在事件开始后的 6h、24h 和 7d 运行。它不判定“预测涨跌是否正确”，而是评价原始命题。

| 事件 | 主要评价问题 |
|---|---|
| 杠杆拥挤 | OI/funding 是否继续极端，是否发生去杠杆 |
| 去杠杆 | OI 是否完成收缩，波动是否恢复 |
| 波动扩张 | 后续实现波动率是否保持高位 |
| 跨资产分化 | ETH/BTC 分化是否持续或均值回归 |
| 链上背离 | 链上证据是否后来确认市场变化 |

聚合报告按资产、事件类型和市场状态展示样本数、持续率、失效率、结果分布及平均最大有利/不利变动。

结果不能只保留成功事件。

---

## 十二、存储与运行

### 技术栈

当前 Demo 只用 Python 3.12 + 门控后的 JSONL 记忆，不引入数据库（见 [`context.md`](context.md)）。下列数据库与批处理组件属于长期阶段，仅在规模或查询需求证明必要时才引入：

- Python 3.12+
- 门控后的 append-only JSONL 记忆；需要时再引入 PostgreSQL + TimescaleDB，本地开发允许 DuckDB
- Parquet 保存批量原始数据与回放快照
- Pydantic 定义跨模块契约
- Polars 进行批量特征计算
- APScheduler 或简单 worker loop 调度
- Typer 构建 CLI

不在首版引入 Kafka、微服务或 Kubernetes。

### CLI 草案

```console
tell collect --source coinbase --asset BTC --asset ETH
tell backfill --from 2025-01-01 --to 2026-01-01
uv run python -m tellagent research --cycles 1
tell inbox --since 24h
tell show <event-id>
tell replay --from 2026-01-01 --to 2026-06-30
tell evaluate --horizon 24h
```

所有命令都支持固定 `--as-of`，保证可重复运行。

---

## 十三、评估

### 数据层

- Observation 完整率、重复率和延迟
- 补数成功率
- 跨来源时间偏差
- Point-in-Time 回放一致性

### 连续判断层

- 每日调用次数、成本、P50/P95 延迟和失败率
- 相同 Frame 重试的一致性
- 普通时期概率稳定性
- 已知事件前后的概率变化
- Jev 相对 RuleBasedProvider 和通用模型的增益

### 事件层

- 已知重大行情召回率与提前量
- 普通时期每周事件数量
- 事件合并准确率
- 人工研究优先级的 Recall@K / NDCG

### 产品层

- 用户标记“值得研究”的比例
- 提醒后查看证据的比例
- mute / dismiss 比例
- 每周节省的研究时间

### 投资研究层

只有前述指标通过后，才进行策略评估：

- walk-forward 和完全样本外测试
- 严禁使用 `available_time` 之后的数据
- 计入手续费、滑点和资金费率
- 与 buy-and-hold 及简单波动率策略比较
- 同时报告收益、最大回撤、Sharpe、换手率和样本数

---

## 十四、主要风险

### 风险 1：持续调用只制造昂贵噪音

对策：记录每次调用的成本与边际信息增益；比较 5m、15m、1h 三种频率。若 5m 判断流没有更早发现状态变化，就自动降频。

### 风险 2：把 Jev 概率误当真实概率

对策：在自己的 BTC/ETH 历史样本上做校准；概率只参与排序和状态转换，不直接映射交易动作。

### 风险 3：做成普通行情摘要

对策：没有证据关系、反向证据和失效条件的输出不得成为 MarketEvent。

### 风险 4：回测泄漏

对策：使用 `available_time`、不可变 revision 和 snapshot；回放只能读取当时可见数据。

### 风险 5：单一来源异常

对策：数据质量门、provider health 和交叉来源确认；无法确认时明确降级。

### 风险 6：过拟合历史行情

对策：少量易解释 detector、walk-forward、锁定最终测试区间、报告所有失败样本。

### 风险 7：AI 编造因果

对策：investigator 只能读取内部证据，逐句引用，禁止开放式新闻归因。

### 风险 8：模型供应商依赖

对策：JudgmentProvider 抽象、规则基线、缓存与 RecordedProvider。

---

## 十五、实施顺序

1. 定义 schema、时间语义和 raw snapshot。
2. 接入 Coinbase、Deribit，并完成历史 backfill。
3. 建立数据质量报告和 Point-in-Time replay。
4. 实现特征引擎及 RuleBasedProvider。
5. 生成 MarketStateFrame，跑通 Jev 每 5 分钟持续判断。
6. 测量成本、延迟、稳定性，并比较 5m/15m/1h 频率。
7. 实现 JudgmentStream 的跃迁、持续和冲突 detector。
8. 实现五类非链上 MarketEvent 与生命周期。
9. 实现证据摘要、CLI inbox 和通知预算。
10. 实现 OutcomeReviewer 和校准报告。
11. 最后接入 Bitcoin 与 Ethereum 链上数据。

核心验收不是“生成了一段像分析师的话”，而是：

> 对任意历史时点，系统能用当时真实可见的数据重建连续判断，解释状态为何变化、展示反向证据，并在未来固定时间诚实评价这次判断。
