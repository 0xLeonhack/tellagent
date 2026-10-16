# tellagent 下一步开发计划

当前核心链路已经可运行：

```text
真实市场数据 → 指标 → Observer → Gate → 强 Analyst → JSONL 记忆 → Rich 报告
```

下一阶段不继续堆叠状态、数据源或 Agent，而是补齐“判断之后发生了什么”的验证闭环。

## 当前进度

- [x] 按日 `frames/*.jsonl` Point-in-Time 账本；
- [x] 按日 `judgments/*.jsonl` 完整判断流；
- [x] Gate 使用真正相邻的 Judgment；
- [x] 1 / 3 / 12 帧概率趋势、EWMA、持续性和翻转次数；
- [x] 6h / 24h / 7d 确定性 Outcome Review；
- [x] `events.jsonl` 与 `outcomes/*.jsonl`；
- [x] 历史 median / MAD / percentile / robust z-score 基线上下文；
- [x] 稳定 Evidence ID；
- [x] `factor_hypotheses.jsonl` 和 `factor_results.jsonl` 数据契约；
- [x] 用达到覆盖要求的历史基线替换对应固定阈值；
- [ ] RuleBased 与远程 Jev 影子对比；
- [x] Outcome 校准汇总报告；
- [x] WorldQuant expression 草稿导出；
- [x] 受约束 Agent 循环：6 动作白名单、6 个静态注册工具、步数与模型调用预算；
- [x] 可回放 AgentTrace 与 `agent-stats` 行为统计；
- [x] 对已记录帧离线回放（`replay`），工具按 `as_of` 截断。

黑客松 Demo 默认使用本地规则 Observer。远程 Jev 接口保留，但 Jev 不是项目运行前提；只有真实对比证明有增益后，才考虑让它参与正式门控。

Agent 部分的设计与实现决策见 [PLAN4AGENT.md](PLAN4AGENT.md#实施决策与偏离)。下一步的 Agent 相关工作只剩“用 rule 与 remote 两套决策方回放同一批记录帧并比较统计”，不需要新的模块。

## 一、最高优先级：Point-in-Time 判断流

当前 `memory.jsonl` 只保存通过 Gate 的重要判断，适合上下文记忆，但不适合重建完整的连续判断轨迹。

需要拆分为三个轻量 JSONL 账本：

```text
.tellagent/
  frames/2026-10-12.jsonl
  judgments/2026-10-12.jsonl
  memory.jsonl
```

### `frames.jsonl`

每一轮采集都保存：

- `frame_id`；
- `asset`；
- `source_time`；
- `available_time`；
- `received_time`；
- 原始响应摘要或哈希；
- 计算后的指标；
- 数据质量标志；
- schema 和指标版本。

### `judgments.jsonl`

每一帧 Observer 判断都保存，包括没有通过 Gate 的普通判断：

- 完整概率分布；
- selected state；
- confidence；
- research priority；
- 冲突角色；
- 缺失输入；
- provider、model version 和 latency。

这样才能计算：

- 相邻帧概率变化；
- 3 帧、12 帧概率趋势；
- 状态持续时间；
- 状态翻转次数；
- Jev 与规则基线的差异；
- Gate 的真实通过率。

### `memory.jsonl`

继续只保存 Gate 放行后的研究上下文、强模型报告和相近记忆，不保存每一帧原始行情。

## 二、最高优先级：自动 Outcome Review

每次 Gate 放行后创建待复盘记录：

```text
event_id
asset
opened_at
original_frame
original_judgment
report
review_due_at: 6h / 24h / 7d
```

复盘事实必须由代码计算：

- 未来收益；
- 最大有利和不利波动；
- 实现波动率；
- Open Interest 后续变化；
- Funding 是否回归；
- 现货成交是否确认；
- 原始失效条件是否触发。

对于 `leverage_expansion_up/down`，不能只用“之后涨了还是跌了”评价，而应检查：

- 杠杆是否继续扩张；
- 现货是否后来确认；
- OI 是否先于价格回落；
- 波动和回撤是否扩大；
- 判断何时失效。

模型只能解释复盘事实，不能负责计算复盘指标。

建议输出：

```text
.tellagent/outcomes/2026-10-12.jsonl
```

## 三、中高优先级：校准判断策略

当前阈值是 Demo 规则，不是经过历史校准的概率模型：

```text
价格变化 > 2%
成交量变化 > 5%
OI 变化 > 8%
```

下一步使用历史分布替代固定阈值：

- 价格变化 / 近期实现波动率；
- 成交量历史百分位；
- Funding 30 天百分位；
- OI 变化 robust z-score；
- 同 UTC 小时季节性基线；
- 数据覆盖率和质量门。

目标不是增加更多规则，而是让相同规则适应不同市场 regime。

## 四、中高优先级：验证 Jev 是否真的有增益

RuleBased Observer 和远程 Jev 应对同一份 `MarketStateFrame` 同时运行，先做影子对比，不立即让 Jev 独占控制流。

比较：

- 状态一致率；
- 首次触发提前量；
- 正常时期误报数量；
- Gate 通过率；
- 单日调用成本；
- latency；
- Outcome Review 的成立率。

如果 Jev 相对规则没有可测增益，就按停止条件降频或移除，而不是继续增加提示词和 detector。

## 五、中优先级：Evidence ID 化

当前强模型通过完整字符串匹配选择证据。后续应使用稳定的证据 ID：

```json
{
  "evidence_id": "ETH:20261012:oi_interval",
  "role": "supporting",
  "metric": "open_interest_change_interval",
  "value": 0.021
}
```

强模型返回证据 ID：

```json
{
  "supporting_evidence_ids": ["ETH:20261012:oi_interval"]
}
```

这样可以避免语言、标点或格式变化导致校验失败，并增强证据可追溯性。

## 六、中优先级：因子研究闭环

新增两个轻量 JSONL 文件：

```text
.tellagent/factor_hypotheses.jsonl
.tellagent/factor_results.jsonl
```

因子假设至少包含：

- 名称；
- 适用市场状态；
- 输入字段；
- 公式草稿；
- 预期方向；
- 预测周期；
- 研究理由；
- 失效条件；
- 来源事件 ID；
- 测试计划。

验证结果至少包含：

- IC / Rank IC；
- 分组收益；
- 换手率；
- 成本后收益；
- 最大回撤；
- 样本内 / 样本外；
- 适用 regime。

WorldQuant BRAIN 可以作为外部验证端。tellagent 负责生成带上下文的因子假设和表达式草稿，不负责复制 BRAIN 的回测平台，也不自动提交 Alpha。

## 七、建议开发顺序

```text
1. frames.jsonl 与 judgments.jsonl
2. Gate 改用真正相邻的 Judgment
3. 6h / 24h / 7d Outcome Review
4. outcomes.jsonl
5. 历史百分位和阈值校准
6. RuleBased 与 Jev 影子对比
7. Evidence ID 化
8. FactorHypothesis 和本地验证格式
9. WorldQuant expression 草稿导出（已完成；保留字段映射占位，不自动提交）
10. 受约束 Agent 循环与 Trace（已完成；见 PLAN4AGENT.md）
11. 记录帧回放与 rule / remote 决策方对比（机制已完成，等待样本积累）
```

## 八、暂时不要做

在上述闭环产生真实验证结果之前，暂时不增加：

- Web Dashboard；
- 自动交易；
- 自动提交 WorldQuant Alpha；
- 更多币种；
- 多 Agent 投票；
- 向量数据库；
- 更多硬编码市场状态；
- 为了“智能感”增加自由文本。

## 最终目标

项目的长期资产不是某个状态标签，而是完整的研究账本：

```text
当时看到了什么
→ 当时如何判断
→ 为什么触发研究
→ 提出了什么假设
→ 后来发生了什么
→ 哪些状态和因子真正有效
```
