# tellagent Development Guide

当前项目只维护一条真实数据研究链路：

```text
Coinbase / Deribit
  → 确定性指标
  → Jev Observer
  → Jev Gate
  → DeepSeek / 强 Analyst
  → JSONL 相近记忆
  → Rich 市场报告
```

## 当前范围

必须保持：

- Python 3.12 和 `uv`；
- Coinbase、Deribit 公共数据；
- BTC、ETH；
- 5 分钟级循环；
- Jev 结构化判断；
- 只有门控通过才调用强模型；
- 只保存重要判断和分析结果；
- Rich 报告；
- JSONL 记忆，不使用数据库。

当前不做：

- Fake Analyst；
- 运行时虚构行情或 Fixture 场景；
- 数据库、向量数据库和外部记忆服务；
- Web、后台 Worker、多 Agent 编排；
- 链上数据、自动交易和收益预测；
- 事件生命周期和自动复盘。

测试中可以构造结构化样本和 Mock HTTP 响应，但不能把它们作为产品运行入口。

## Agent 职责

```text
代码       采集、时间窗口、指标、质量检查
Jev        判断市场状态、概率、冲突、研究优先级
Gate       根据 Jev 输出决定是否调用强模型
强 Analyst 组织证据、检索上下文、生成研究报告
Memory     保存并检索通过门控的上下文
```

`Gate` 不是另一个 Agent，也不重新判断市场。它是纯函数策略，只读取 Jev 的 `ContinuousJudgment` 和上一条判断，检测状态变化、概率跃迁和研究优先级。

## 代码边界

- `data.py` 只处理真实公共 API；
- `metrics.py` 只做确定性计算；
- `observer.py` 提供本地规则 Observer 和可替换远程 Jev Provider；
- `gate.py` 提供 `evaluate_gate` 和 `should_investigate`；
- `analyst.py` 只保留远程强 Analyst；
- `memory.py` 使用 append-only JSONL；
- `research.py` 是唯一的循环编排入口；
- `renderer.py` 只负责 Rich 输出；
- `cli.py` 只暴露 `research` 命令。

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
```

## 提交标准

一个提交只完成一个小模块，提交前必须确认：

- 测试通过；
- 真实数据路径没有引入虚构运行数据；
- 失败会被清晰报告；
- 没有新增不必要的基础设施；
- 工作区不包含密钥或 `.tellagent/` 记忆文件。
