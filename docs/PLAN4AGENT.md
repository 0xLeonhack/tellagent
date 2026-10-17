# tellagent Agent 重构计划

## 目标

把当前的确定性市场研究工作流升级为一个受约束、可回放、可评估的研究 Agent：

```text
真实市场
  → Agent 判断状态与研究意图
  → 选择允许的研究动作
  → 代码执行工具
  → Agent 读取工具结果
  → 继续判断或生成报告
  → 保存记忆、Trace 和 Outcome
```

Agent 不执行交易、不修改账户、不自由浏览互联网，也不负责重新计算市场事实。

## 实施状态（2026-10-17）

阶段 0–6 已全部实现并接入 CLI；本文档保留为设计蓝图，实现细节与偏离见文末「实施决策与偏离」。

| 阶段 | 状态 | 交付物 |
| --- | --- | --- |
| 0 契约和工具边界 | 已完成 | `agent_schemas.py`（`AgentAction` / `AgentDecision` / `ToolCall` / `ToolResult` / `AgentTrace` / `AgentRunSummary` / `AgentStats`）、动作与终止动作白名单、`tools.py` |
| 1 研究工具 | 已完成 | `agent_tools.py`：6 个静态注册工具，唯一写入工具是 `create_factor_hypothesis` |
| 2 本地 Agent Loop | 已完成 | `agent_loop.py`：步数预算、工具执行、自身上下文回灌、Trace |
| 3 接入模型 Provider | 已完成 | `agent_provider.py` + `agent_policy.py`，`cli.py agent` 命令 |
| 4 Memory / Outcome 反馈与 Trace | 已完成 | `agent_research.py`、`agent_trace.py`、`cli.py agent-stats`、`research.py replay` |
| 5 因子研究 Agent | 已完成 | `create_factor_hypothesis` 写入 `factor_hypotheses.jsonl`（白名单因子） |
| 6 双模式运行 | 已完成 | `research`（workflow）与 `agent`（agent）共用同一流水线与账本 |

## 当前问题

当前系统已经有真实数据、指标、Observer、Gate、强 Analyst、Memory、Outcome Review 和因子假设。但默认路径仍然是：

```text
代码规则决定是否调用模型
  → 模型只生成最终报告
```

模型还没有真正决定下一步研究动作，也没有通过工具结果进行多步判断。因此当前是 Agent-ready 的工作流，还不是完整 Agent。

## Agent 闭环

### Perceive

代码获取真实数据并生成：

- MarketSnapshot；
- MarketStateFrame；
- 历史基线；
- 数据质量；
- Evidence ID。

### Interpret

Observer 读取结构化状态，输出：

- 当前 Regime；
- 分数或 Jev 概率；
- 证据关系；
- 缺失数据；
- 研究优先级。

Observer 可以是本地规则、远程 Jev 或 DeepSeek，但必须实现统一 Provider 契约。

### Decide

Agent 返回有限的 `AgentAction`：

```text
monitor
investigate
compare_history
generate_factor
wait_for_confirmation
finish
```

Action 必须经过 Pydantic 校验和代码白名单检查。模型不能返回任意 Shell、Python 或交易指令。

### Act

代码通过 `ToolRegistry` 执行静态注册工具：

- `read_recent_judgments`；
- `read_similar_memory`；
- `read_outcome_calibration`；
- `read_recent_outcomes`；
- `read_evidence_catalog`；
- `create_factor_hypothesis`。

工具只读写项目账本，不访问交易权限。报告不是工具：`finish` 这个终止动作由 `AgentResearchRunner`
在循环结束后调用强 Analyst 生成，模型不能自己拼装报告内容。

### Observe Result

工具结果重新进入 Agent 上下文。Agent 可以继续调查、改变研究重点、生成因子假设、结束报告或等待下一轮数据。

### Remember / Reflect

Frame、Judgment、Event、Memory、Outcome 和 Factor 账本继续使用 JSONL。Outcome 的事实由代码计算，Agent 只能解释结果。

## 模块拆分

第一版可以先使用平面模块：

```text
tellagent/
  agent_schemas.py
  tools.py
  agent_loop.py
  agent_trace.py
```

接口稳定后再拆成 `tellagent/agent/` 子目录。

## 开发阶段

### 阶段 0：契约和工具边界

- 定义 `AgentAction`；
- 定义 `ToolCall`、`ToolResult`、`AgentDecision`；
- 定义动作白名单；
- 定义单轮最多步数和调用预算；
- 不改变现有 `research` 命令。

验收：非法动作、未知工具和错误参数都会被拒绝。

**状态：已完成。** 验收由 `tests/test_agent_loop.py`、`tests/test_agent_provider.py`、
`tests/test_agent_tools.py` 覆盖：非法终止动作带工具、未注册工具、非白名单因子名都会被拒绝。

### 阶段 1：研究工具

实现只读工具：

- 最近 Judgment；
- 相近 Memory；
- Outcome Calibration；
- 当前 Evidence Catalog。

验收：工具可独立测试，输入输出不依赖模型。

**状态：已完成。** 共 6 个工具；`tests/test_agent_tools.py` 直接调用 `registry.execute` 验证输入输出。

### 阶段 2：本地 Agent Loop

运行时骨架已实现为 `agent_loop.py`，包含最大步数、ToolRegistry 执行和 AgentTrace。

实现有限步循环：

```text
MarketStateFrame + Judgment
  → AgentDecision
  → ToolRegistry
  → ToolResult
  → 下一轮 AgentDecision
```

第一版最多执行 3 步，防止循环失控。

验收：`monitor`、`compare_history`、`finish` 三类流程可回放，并记录每一步 Trace。

**状态：已完成。** 除步数预算外，每步都会把 `steps_remaining`、`previous_steps` 和上一步
`ToolResult` 回灌给下一次决策，因此 Agent 能看到自己做过什么（见「实施决策与偏离」第 3 条）。

### 阶段 3：接入 DeepSeek Agent Observer

结构化 DeepSeek Agent Provider 已实现，下一步将它接入 AgentLoop 和 CLI agent mode。

DeepSeek 负责选择 Regime、研究动作和下一步工具。代码继续负责：

- 事实计算；
- 工具执行；
- Action 白名单；
- 成本和步数限制；
- Evidence ID 校验。

验收：终端显示 Provider、Action、ToolCall、ToolResult、是否结束和最终报告。

**状态：已完成。** `RemoteAgentProvider` 只负责把模型输出变成合法的 `AgentDecision`；它会校验步号、
工具名是否在上下文给出的白名单内、以及最后一步必须是终止动作。无密钥时用 `RuleBasedAgentProvider`
（`--agent-provider rule`）作为确定性基线，两种决策方共用 `agent_traces` 账本，可直接对比。

### 阶段 4：Agent Memory 和 Outcome 反馈

- Agent 读取相近历史上下文；
- Agent 读取相似 Outcome；
- 复盘结果写回上下文；
- 记录完整 Agent Trace；
- 统计动作选择和研究结果。

验收：同类状态可以检索历史判断和结果，且不读取未来数据。

**状态：已完成。** `AgentRunSummary` + `AgentStats` 给出步数、工具调用、模型调用、升级率、
工具成功率、动作/工具/终止分布；`cli.py agent-stats` 聚合展示。回放（`replay` 命令）会把工具的
可见范围截断到该帧 `as_of`，使「不读取未来数据」在离线重跑时同样成立。

### 阶段 5：因子研究 Agent

Agent 选择 `generate_factor` 时：

- 生成 `FactorHypothesis`；
- 写入 `factor_hypotheses.jsonl`；
- 生成 WorldQuant expression 草稿；
- 等待本地或外部回测结果。

验收：因子假设包含来源 Frame、Regime、输入、公式、周期和失效条件。

**状态：已完成。** 因子只能取自 `factors.py` 的白名单定义（名称、输入、公式草稿、方向、周期、测试计划），
Agent 只能选择名字和备注，不能自造公式；`worldquant_drafts.md` 在每次写入假设时自动重建。

Market State v2 的本地 Observer 已使用连续 Regime 分数和质量/冲突修正的 confidence，Jev Provider 继续使用独立的概率协议。

### 阶段 6：双模式运行

```text
workflow mode
  本地规则 Observer → Gate → Analyst

agent mode
  DeepSeek Observer → AgentAction → Tools → DeepSeek Analyst
```

黑客松 Demo 默认展示 `agent mode`；没有 API Key 时仍可使用 `workflow mode` 测试。

## 安全边界

- 不允许下单、转账或修改账户；
- 不允许执行任意 Shell、Python 或网络请求；
- 工具必须静态注册；
- 每轮最多 3 个 Agent 步骤；
- 每次运行有模型调用预算；
- 证据只能引用当前 Frame 的 Evidence ID；
- Agent 不能修改历史 Frame、Judgment、Outcome；
- 模型失败时保留错误，不伪造结果；
- Action、ToolCall、ToolResult 全部写入可回放 Trace。

## 评估指标

已由 `agent-stats` / `AgentStats` 直接给出：

- 运行次数、平均步数、平均工具调用、平均模型调用；
- 升级报告比例（`finish` / `generate_factor` 占比）与工具成功率；
- 动作分布、工具分布、终止动作分布，可按 `--asset` 过滤。

仍需外部验证（不在当前范围内）：

- Action 选择准确率与证据引用准确率（需要人工标注或更强的判据）；
- 状态变化提前量、普通行情误报率；
- Outcome Review 成立率；
- 因子假设的样本外表现。

基线对比方式：对同一批记录帧分别用 `--agent-provider rule` 和 `--agent-provider remote` 回放，
比较两者在 `agent-stats` 中的终止分布、步数与模型调用。

## 暂时不做

- 自动交易 Agent；
- 无限循环；
- 多 Agent 投票；
- 自由浏览互联网；
- 自动修改策略代码；
- 自动提交 WorldQuant Alpha；
- 向量数据库；
- 用模型 confidence 代替真实回测。

## 完成定义

一次运行应能展示：

```text
真实 Frame
  → Agent 判断
  → Agent Action
  → ToolCall
  → ToolResult
  → 下一步判断
  → 研究报告 / 因子假设
  → Memory 和 Trace
```

达到这个闭环，项目才从“带模型节点的工作流”升级为“受约束、可回放、可评估的研究 Agent”。

## 实施决策与偏离

实现过程中对蓝图做了以下明确取舍，均在代码注释和测试中留有记录：

1. **Gate 决定“何时唤醒”，Agent 决定“做什么”**。Gate 仍然拥有成本闸门（避免稳定状态反复消耗模型），
   但被唤醒后 Agent 可以自己降级为 `monitor` / `wait_for_confirmation`，此时不生成报告、不写记忆、
   不调用强 Analyst。
2. **最后一步自动收口**。若 Agent 在第 N 步（`N = max_steps`）仍然调用了工具，循环会把该决策标记为
   `finished=True` 并在 `within_budget=False` 下结束，然后按终止动作处理，而不是抛异常丢掉整轮研究；
   只有既非终止、又没调用工具的死循环才会触发 `RuntimeError`。
3. **把 Agent 自己的历史回灌给它**。每步上下文包含 `steps_remaining`、`previous_steps`（含工具参数与结果摘要）
   和完整的上一步 `ToolResult`（超长内容截断）。这是实测中发现的问题：模型看不到自己做过什么时会重复
   同一个工具调用直到耗尽预算。系统提示同时要求最后一步必须选终止动作，Provider 端也做二次校验。
4. **`--always-investigate` 是评估开关，不是默认行为**。它绕过 Gate 冷却把每一帧都交给 Agent，
   用于观察 Agent 自身的判断分布；默认关闭，避免把成本闸门当成摆设。
5. **因子覆盖面对齐 workflow 模式**。`RuleBasedAgentProvider` 不为 `generate_factor` 设置额外的优先级门槛，
   理由与 workflow 模式一致：假设先记录下来，再由回测淘汰；否则规则基线的覆盖率会低于确定性流水线，
   造成“Agent 模式更弱”的假象。
6. **模型驱动的 Agent 每轮最多 3 次模型调用**（`MAX_MODEL_CALLS_PER_RUN`），步数上限默认 3、可调到 10。
   超出即构造期报错，而不是运行时才发现超预算。
7. **失败即记录**。模型返回非法 JSON 结构、选择未注册工具、或强 Analyst 失败时，账本写入
   `terminal_action=rejected` / `error`，不重试、不修补、不用编造内容生成报告。Provider 只修复 JSON
   **形状**（例如把 `tool_args` 的 JSON 字符串解析成对象），不放松任何真实约束。
8. **新增 `replay` 命令**。为了让“可回放”变成可操作能力：对账本里已记录的帧离线重跑 Agent，
   不重新抓行情、不改写原账本，只追加新 Trace 与因子假设。回放时工具按该帧 `as_of` 截断可见范围。
9. **账本是文件而非数据库**。适合单机持续运行；并发多实例写入不在当前范围内。
