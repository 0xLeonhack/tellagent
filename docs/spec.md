# tellagent Technical Specification

> **定位说明**：本文描述完整目标系统的技术契约，大部分尚未实现。当前 Demo 只实现了其中一小部分（见 [`DEVELOPMENT.md`](DEVELOPMENT.md)）；已实现 schema 的字段与命名可能与本文不同，未实现部分不要当作现状。

## 1. 运行结构

```text
collectors → raw repository → feature engine → MarketStateFrame
                                      ↓
                               Observer ModelClient
                                      ↓
                              ContinuousJudgment
                                      ↓
                          deterministic Jev Gate
                                      ↓
                               EvidenceBundle
                                      ↓
                            Investigator ModelClient
                                      ↓
                            MarketEvent + notification
```

所有步骤都可单独运行；每一步接收显式的 `as_of` 和 `run_id`，禁止隐式使用当前时间。

## 2. 数据契约

### Observation

```text
id: UUID
asset: BTC | ETH | ETH_BTC
source: coinbase | deribit
instrument: string
metric: string
value: decimal | null
source_time: UTC datetime
available_time: UTC datetime
received_time: UTC datetime
revision: positive int
quality_flags: string[]
payload_ref: string | null
collector_version: string
```

同一来源、标的、指标和 source_time 的修订必须新增 revision，不能 UPDATE 旧事实。

### MarketStateFrame

```text
id: UUID
asset: BTC | ETH | ETH_BTC
as_of: UTC datetime
schema_version: string
price_state: object
spot_state: object
leverage_state: object
volatility_state: object
cross_asset_state: object
anomalies: string[]
missing_inputs: string[]
quality_summary: object
feature_ids: UUID[]
```

frame 只能包含归一化数值、方向、历史百分位和必要质量说明，不包含未经限制的长时间序列。

### ContinuousJudgment

```text
frame_id: UUID
question_set_version: string
selected_value: string
probabilities: map[string, float 0..1]
confidence: float 0..1
supporting_roles: string[]
contradicting_roles: string[]
missing_roles: string[]
research_priority: silent | watch | significant | urgent
invalidation_conditions: string[]
provider: string
model_version: string
latency_ms: int
input_tokens: int
output_tokens: int
estimated_cost: decimal
created_at: UTC datetime
```

概率总和允许有小数误差，但必须在服务端归一化或拒绝；未知枚举值必须拒绝。

### EvidenceBundle

```text
event_key: string
frozen_at: UTC datetime
frame_ids: UUID[]
judgment_ids: UUID[]
anomaly_ids: UUID[]
supporting_evidence: Evidence[]
contradicting_evidence: Evidence[]
missing_evidence: Evidence[]
quality_summary: object
snapshot_hash: string
```

`snapshot_hash` 用于证明 Investigator 使用的是冻结输入。调查完成后不得修改 bundle。

### InvestigatorResult

```text
fact_summary: string
supporting_evidence: Evidence[]
contradicting_evidence: Evidence[]
missing_evidence: Evidence[]
data_limitations: string[]
invalidation_conditions: string[]
confidence_note: string
```

每条 evidence 必须引用 bundle 中的 feature、anomaly 或 observation；无法引用的句子必须被业务校验拒绝或标为未知。

## 3. 服务接口

### ModelClient

```python
async def observe(frame: MarketStateFrame) -> ContinuousJudgment: ...
async def investigate(bundle: EvidenceBundle) -> InvestigatorResult: ...
```

实现必须支持 fake client。超时、限流和网络错误可重试；schema 错误、权限错误和版本错误不可盲目重试。

### Jev Gate

输入：最近连续判断、确定性异常、质量摘要和当前 open events。

输出：`silent`、`update_event(event_key)` 或 `open_event(event_key)`。

Gate 必须是纯函数或等价的可回放逻辑，只读取 Jev 的结构化字段，不能读取模型自由文本决定是否调用强模型。

## 4. 状态和幂等

- collector 使用 `(source, instrument, metric, source_time, revision)` 幂等。
- frame 使用 `(asset, as_of, schema_version, feature_definition_version)` 幂等。
- event 使用稳定 `event_key`，重复 worker 只能更新同一事件。
- Investigator 通过 `snapshot_hash` 幂等；同一 bundle 不重复计费。
- 所有任务写入 `run_id`、开始时间、结束时间和错误状态。

## 5. 测试最低要求

- 时间窗口边界、时区、缺失值、重复值和 revision 的单元测试。
- 结构化真实形态样本：固定输入得到固定 frame 和 judgment。
- ModelClient schema 错误、超时、限流和重复响应测试。
- Jev Gate 的放行、阻止、状态变化和概率跃迁测试。
- 一条从 Mock 公共 API 到 `research` 管线的集成测试。

## 6. 配置与安全

- 所有密钥只从环境变量或未提交的本地配置读取。
- 默认只读 API 权限；系统不接受交易 API key。
- provider、model、interval、token limit、cost limit 和数据源全部配置化。
- 日志禁止输出密钥、完整 prompt、个人令牌和未经脱敏的原始认证响应。
