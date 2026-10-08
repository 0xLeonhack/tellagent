# tellagent PRD

## 一句话

每 5 分钟获取 BTC/ETH 真实市场数据，由 Jev 低成本判断状态和研究价值；只有重要判断才调用 DeepSeek 等强模型，并使用相近历史上下文生成可反驳的研究报告。

## 用户入口

```bash
uv run python -m tellagent research --cycles 0 --interval 300 --analyst remote
```

系统输出：

1. 数据时间与真实来源；
2. 价格、现货成交、funding 和 open interest 指标；
3. Jev 状态、概率、冲突角色和研究优先级；
4. 强模型生成的事实摘要；
5. 支持、反向和缺失证据；
6. 失效条件；
7. 检索到的相近研究上下文。

## 核心流程

```text
Coinbase / Deribit
  → 确定性指标
  → MarketStateFrame
  → Jev Observer
  → Jev Gate
  → DeepSeek / 强 Analyst
  → JSONL Memory
  → Rich MarketReport
```

## 产品约束

- 运行时只使用真实公共市场数据，不提供虚构行情入口；
- 代码负责指标计算，Jev 不重新计算事实；
- Jev 是市场判断器，Gate 只是调用强模型的确定性门控；
- 强模型不能抓取行情、编造新闻或新增不存在的证据；
- 只保存通过门控的重要上下文；
- 输出是研究支持，不是交易指令。

## 当前技术栈

- Python 3.12；
- `uv`；
- Typer + Rich；
- httpx；
- Pydantic v2；
- pytest；
- append-only JSONL memory。

## 非目标

- 数据库和向量数据库；
- Web、用户系统和通知；
- 多 Agent 编排框架；
- 自动交易和仓位管理；
- 新闻、社交和链上数据；
- 完整事件生命周期和自动复盘。

## 完成定义

- 单个 `research` 命令可以持续运行；
- Coinbase/Deribit 失败时明确报错，不回退到虚构行情；
- Jev 未通过门控时不调用强模型；
- Jev 通过门控时，强模型收到当前判断和相近记忆；
- 只有重要判断进入 JSONL memory；
- Rich 报告包含支持、反向、缺失证据和失效条件；
- 测试和真实 API 单轮验证通过。
