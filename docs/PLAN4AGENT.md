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
- `read_similar_outcomes`；
- `read_calibration`；
- `create_factor_hypothesis`；
- `finish_report`。

工具只读写项目账本，不访问交易权限。

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

### 阶段 1：研究工具

实现只读工具：

- 最近 Judgment；
- 相近 Memory；
- Outcome Calibration；
- 当前 Evidence Catalog。

验收：工具可独立测试，输入输出不依赖模型。

### 阶段 2：本地 Agent Loop

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

### 阶段 3：接入 DeepSeek Agent Observer

DeepSeek 负责选择 Regime、研究动作和下一步工具。代码继续负责：

- 事实计算；
- 工具执行；
- Action 白名单；
- 成本和步数限制；
- Evidence ID 校验。

验收：终端显示 Provider、Action、ToolCall、ToolResult、是否结束和最终报告。

### 阶段 4：Agent Memory 和 Outcome 反馈

- Agent 读取相近历史上下文；
- Agent 读取相似 Outcome；
- 复盘结果写回上下文；
- 记录完整 Agent Trace；
- 统计动作选择和研究结果。

验收：同类状态可以检索历史判断和结果，且不读取未来数据。

### 阶段 5：因子研究 Agent

Agent 选择 `generate_factor` 时：

- 生成 `FactorHypothesis`；
- 写入 `factor_hypotheses.jsonl`；
- 生成 WorldQuant expression 草稿；
- 等待本地或外部回测结果。

验收：因子假设包含来源 Frame、Regime、输入、公式、周期和失效条件。

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

- 工具调用是否必要；
- 平均模型调用次数；
- Action 选择准确率；
- 证据引用准确率；
- 状态变化提前量；
- 普通行情误报率；
- Outcome Review 成立率；
- 因子假设样本外表现。

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

