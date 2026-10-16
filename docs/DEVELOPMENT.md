# tellagent Development Guide

当前项目只维护一条真实数据研究链路，它有两种运行模式：

```text
Coinbase / Deribit
  → 确定性指标
  → Observer
  → Deterministic Gate
  → workflow 模式：强 Analyst
     agent 模式：受约束 Agent（动作白名单 + 静态工具）→ 强 Analyst
  → JSONL 相近记忆 · AgentTrace
  → Rich 市场报告
```

## 当前范围

必须保持：

- Python 3.12 和 `uv`；
- Coinbase、Deribit 公共数据；
- BTC、ETH；
- 5 分钟级循环；
- Observer 结构化判断；
- 只有门控通过才调用强模型；
- 只保存重要判断和分析结果；
- Rich 报告；
- JSONL 记忆，不使用数据库。

当前不做：

- Fake Analyst；
- 运行时虚构行情或 Fixture 场景；
- 数据库、向量数据库和外部记忆服务；
- Web、后台 Worker、多 Agent 投票与任意编排（已实现的是单个受约束 Agent 循环）；
- 链上数据、自动交易和收益预测。

已实现（不再是非目标）：事件生命周期、6h/24h/7d 自动复盘、受约束 Agent 循环与可回放 Trace。

测试中可以构造结构化样本和 Mock HTTP 响应，但不能把它们作为产品运行入口。

## Agent 职责

```text
代码       采集、时间窗口、指标、质量检查、工具执行、预算和白名单
Observer   判断市场状态、概率、冲突、研究优先级
Gate       根据 Observer 输出决定何时唤醒 Agent / 调用强模型
Agent      在白名单内选择下一步研究动作（agent 模式）
强 Analyst 组织证据、检索上下文、生成研究报告
Memory     保存并检索通过门控的上下文
```

`Gate` 不是另一个 Agent，也不重新判断市场。它是纯函数策略，只读取 Observer 的 `ContinuousJudgment` 和上一条判断，检测状态变化、概率跃迁和研究优先级。

Agent 也不是事实来源：它不计算指标、不抓数据、不下单，只能从 6 个动作和 6 个静态注册工具中选择下一步。

## 代码边界

- `data.py` 只处理真实公共 API，以及进程内滚动采样（不落库）；
- `metrics.py` 只做确定性计算；
- `observer.py` 提供本地规则 Observer 和可替换远程 Jev Provider；
- `gate.py` 提供 `evaluate_gate` 和 `should_investigate`；
- `analyst.py` 只保留远程强 Analyst；
- `memory.py` 使用 append-only JSONL；
- `research.py` 是唯一的循环编排入口，并承载对已记录帧的回放（`replay_recorded_frames`）；
- `renderer.py` 只负责 Rich 输出；
- `cli.py` 暴露 `research`、`agent`、`replay`、`agent-stats` 四个命令，不包含研究逻辑；
- `agent_schemas.py` 只定义契约：动作白名单、`AgentAction`、`AgentTrace`、`AgentRunSummary`、`AgentStats`；
- `agent_loop.py` 是唯一的有界循环：步数预算、工具执行、上下文回灌，不含任何研究判断；
- `tools.py`、`agent_tools.py` 只做静态工具注册与账本读写映射，工具没有交易、Shell、Python、网络出口；
- `agent_policy.py` 是无密钥的确定性决策基线，不得引入模型调用；
- `agent_provider.py` 只负责把模型输出规范化为合法决策，并做白名单、步号和终止动作校验；
- `agent_research.py` 把一帧变成一个 Agent 运行：构建上下文、跑循环、调用强 Analyst、写 Trace 与总结；
- `agent_trace.py` 只做 append-only Trace 读写和 `AgentStats` 聚合，不改写历史。

## 开发步骤

1. 先定义输入、输出和失败情况。
2. 更新 Pydantic schema。
3. 用纯函数实现确定性逻辑。
4. 用 Mock API 或结构化测试样本验证。
5. 验证 Jev、门控、强模型和记忆之间的边界。
6. 运行完整测试和一次真实 API 单轮检查。
7. 更新文档。
8. 每完成一个可验证模块就提交并推送。

## 运行和验收

配置真实强模型：

```bash
export TELLAGENT_MODEL_API_URL="https://provider.example/v1/chat/completions"
export TELLAGENT_MODEL_API_KEY="your-key"
export TELLAGENT_MODEL_NAME="deepseek-chat"
```

运行一次：

```bash
uv run python -m tellagent research --cycles 1 --analyst remote
```

持续运行：

```bash
uv run python -m tellagent research --cycles 0 --interval 300 --analyst remote
```

只运行 Jev 和记忆门控：

```bash
uv run python -m tellagent research --cycles 1 --analyst none
```

每次修改至少运行：

```bash
uv run pytest
uv run python -m tellagent research --cycles 1 --analyst none
uv run python -m tellagent agent --cycles 1 --analyst none
```

## 提交标准

一个提交只完成一个小模块，提交前必须确认：

- 测试通过；
- 真实数据路径没有引入虚构运行数据（`examples/demo-ledger/` 是真实记录帧的离线快照，只用于回放，
  不得作为运行入口）；
- Agent 路径没有新增超出白名单的动作、工具或写入范围；
- 失败会被清晰报告；
- 没有新增不必要的基础设施；
- 工作区不包含密钥或 `.tellagent/` 记忆文件。
