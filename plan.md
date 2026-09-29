# tellagent Hackathon MVP Plan

## 目标

在黑客松期间做出一个能现场演示的 BTC/ETH 市场矛盾检测器：

```text
获取一份当前市场快照
→ 计算少量确定性指标
→ Agent 判断市场叙事和矛盾
→ 输出支持证据、反向证据和失效条件
```

MVP 的成功标准不是预测价格，而是让观众在 2 分钟内看懂：系统能把多个市场指标组织成一个可质疑的研究事件。

## 只做这些

### 数据

- 默认使用 Coinbase 和 Deribit 的实时 API。
- 如果网络或 API 不稳定，使用一份固定 JSON fixture 保证演示可运行。
- 只支持 BTC 和 ETH，优先支持 ETH。

### 确定性计算

计算少量指标即可：

- 1h/6h 价格变化；
- 现货成交量变化；
- funding；
- open interest；
- ETH/BTC 变化；
- 简单的指标分位或 z-score。

### 一个 Agent

只实现一个 `Market Analyst` agent，不拆 Observer、Investigator、Review 三个 agent。

输入结构化 JSON，输出严格 JSON：

```json
{
  "headline": "上涨主要由杠杆推动，现货确认不足",
  "state": "leverage_led",
  "confidence": 0.78,
  "supporting_evidence": ["open interest 处于高位", "funding 快速上升"],
  "contradicting_evidence": ["现货成交量也有所扩大"],
  "missing_evidence": ["没有链上数据"],
  "invalidation_condition": "open interest 回落而现货成交继续扩大"
}
```

### 一个入口

优先做 CLI：

```bash
python -m tellagent demo
```

输出清晰的终端报告即可。时间允许时，再加一个极简 FastAPI 页面或静态 HTML，不做完整 dashboard。

## 不做

- 不做 5 分钟常驻 worker。
- 不做不可变数据库、历史回放和数据 revision。
- 不做自动事件生命周期和 6h/24h/7d 复盘。
- 不做链上数据、全币种、用户账户和公网部署。
- 不做自动交易、收益预测或复杂通知系统。
- 不做多 agent 编排框架。

## 推荐实现顺序

1. 写一个 fixture，包含 BTC/ETH 的价格、成交量、funding 和 OI。
2. 写纯函数计算变化率和异常标记。
3. 写一个模型调用函数，把结构化指标交给 agent。
4. 对 agent 返回值做 JSON/Pydantic 校验；失败时显示原始错误。
5. 用 Rich 输出“事实、判断、支持、反向、缺失、失效条件”。
6. 用真实 API 替换 fixture，并保留 `--fixture` 演示模式。
7. 最后再考虑网页。

## 黑客松验收

- 一条命令可以在 30 秒内完成演示。
- 无网络时 fixture 模式仍可运行。
- 输出中同时出现支持证据和反向证据。
- Agent 不负责计算指标，所有数值在调用前已经算好。
- 能明确展示“证据不足”而不是编造原因。

## 后续方向

黑客松演示成功后，再从现有详细文档中恢复：持久化、point-in-time 回放、Observer/Investigator 分层、事件复盘和本地 Web。
