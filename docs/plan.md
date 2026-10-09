# tellagent Development Plan

## 已完成

- Python 3.12 隔离环境；
- Coinbase/Deribit 真实公共数据采集；
- 价格、成交量、funding、open interest 指标；
- 进程内滚动 OI 变化；
- `MarketStateFrame`；
- 本地规则 Jev 和可选远程 Jev Provider；
- Jev 门控；
- OpenAI-compatible 强 Analyst；
- 相近 JSONL 记忆；
- Rich 报告；
- 研究建议与因子候选输出；
- 单一 `research` 持续循环入口；
- 核心自动测试。

## 当前运行方式

只运行 Jev 和记忆门控：

```bash
uv run python -m tellagent research --cycles 1 --analyst none
```

使用强模型分析：

```bash
uv run python -m tellagent research --cycles 1 --analyst remote
```

每 5 分钟持续运行：

```bash
uv run python -m tellagent research --cycles 0 --interval 300 --analyst remote
```

## 下一步

1. 真实运行测量 Jev 调用成本、延迟和门控通过率；
2. 根据数据分布校准状态阈值和概率，而不是继续增加硬编码规则；
3. 用真实样本验证研究建议和因子候选，而不是直接转成交易信号；
4. 改进 JSONL 记忆排序和去重；
5. 定义供因子研究消费的稳定 JSON 输出；
6. 用历史真实数据验证状态判断与后续市场结果的关系。

## 停止扩张项

在核心循环产生真实验证结果之前，不增加数据库、Web、多 Agent、链上数据、自动交易或复杂事件系统。
