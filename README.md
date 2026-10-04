# tellagent

> 面向 BTC/ETH 的市场矛盾检测器：持续整理证据，发现状态变化，并明确说明什么会推翻当前判断。

tellagent 是一个本地运行的加密市场研究工具。它把 Coinbase 现货、Deribit 衍生品（后续再加入链上数据）整理成结构化市场快照，再由受约束的 agent 生成一份包含正向、反向和缺失证据的研究报告。

它不是交易机器人，也不承诺预测下一根 K 线。它首先要回答的是：

1. 当前市场更像什么状态？
2. 哪些数据支持或反驳这个判断？
3. 哪些新证据出现后，当前判断应该失效？

## 当前状态

仓库目前已经完成 **Hackathon MVP 的离线闭环**，并增加了轻量实时数据适配：固定 Fixture、Coinbase/Deribit 公共 API、确定性指标、Fake Analyst、Pydantic 校验、Rich CLI 和基础测试均已实现。真实模型适配仍在后续阶段。

安装依赖并运行离线 Demo：

```bash
uv sync --dev
uv run python -m tellagent demo --fixture
```

也可以只查看 ETH：

```bash
uv run python -m tellagent demo --fixture --asset ETH
```

需要给脚本或后续界面使用时，可以输出经过校验的 JSON：

```bash
uv run python -m tellagent demo --fixture --json
```

Fixture 模式不依赖网络；真实模型接入完成后，仍会保留 Fixture 和实时 API 模式。

使用公共 API 获取当前快照：

```bash
uv run python -m tellagent demo --live
```

实时模式目前能计算 Coinbase 最近两根小时 K 线的价格和现货成交量变化，并读取 Deribit 当前 funding。由于还没有本地历史存储，open interest 变化会明确显示为缺失；网络或 API 失败时请使用 `--fixture` 离线演示。

可选的远程 Analyst 使用 OpenAI-compatible JSON API。配置后运行：

```bash
export TELLAGENT_MODEL_API_URL="https://your-provider.example/v1/chat/completions"
export TELLAGENT_MODEL_API_KEY="your-key"
export TELLAGENT_MODEL_NAME="your-model"
uv run python -m tellagent demo --fixture --analyst remote
```

远程模型只接收已经计算好的快照和证据；未配置这些变量时，`demo` 仍使用本地 Fake Analyst。

## 为什么做它

市场数据并不稀缺，困难在于把不同来源拼成一个可检查的结论：

- 价格上涨不一定代表现货需求，可能只是杠杆扩张；
- funding、open interest、成交量等单指标阈值容易误报；
- AI 摘要容易只寻找支持某个故事的证据；
- 提醒发出后，产品通常不会持续记录判断是否成立。

tellagent 的重点不是再做一个图表终端，而是把“事实 → 判断 → 反驳条件”保存成可回放的研究事件。

## MVP 做什么

MVP 只覆盖 BTC、ETH 和 ETH/BTC，优先使用 Coinbase 现货与 Deribit 永续数据，先完成一次快照分析：

```text
fixture / API
    ↓
数据适配器
    ↓
确定性指标计算（收益率、成交量、funding、OI、简单异常）
    ↓
MarketSnapshot JSON
    ↓
一个受约束的 Market Analyst agent
    ↓
校验后的 Report JSON
    ↓
CLI 报告
```

报告至少包含：数据时间与来源、关键指标、事实摘要、市场状态、支持证据、反向证据、缺失数据和失效条件。数据不足时必须明确说“不确定”，不能编造原因。

## 设计边界

### 代码负责事实

时间对齐、窗口、收益率、波动率、百分位、异常检测、数据质量和结果评价必须由确定性代码完成。

### Agent 负责关系

Agent 只能阅读已经计算好的 JSON，判断市场状态、组织证据并给出有限文本摘要。它不能抓取数据、重新计算指标、搜索新闻、编造因果关系或输出交易指令。

### 研究与执行隔离

系统不保存交易权限、不提供下单工具，也不把研究优先级自动转换成仓位建议。所有模型输出都必须经过 schema 校验。

## 计划中的长期架构

MVP 验证后，再逐步恢复持续运行能力：

```text
采集器 → 不可变原始观测 → 特征引擎 → MarketStateFrame
                                      ↓
                               Observer / Jev
                                      ↓
                              ContinuousJudgment
                                      ↓
                              确定性 EventPolicy
                                      ↓
                               冻结 EvidenceBundle
                                      ↓
                                Investigator 摘要
                                      ↓
                           MarketEvent 与 6h/24h/7d 复盘
```

长期版本计划每 5 分钟观察一次状态，只在概率跃迁、持续异常或跨来源证据冲突时调用更昂贵的调查模型。原始观测使用 append-only 版本保存，并区分 `source_time` 与 `available_time`，确保历史回放不会读到未来修订数据。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [`DEVELOPMENT.md`](DEVELOPMENT.md) | 当前 Demo 的开发流程、范围、守则和验收标准 |
| [`context.md`](context.md) | 当前决策、术语、不可违背的边界和未知项 |
| [`intend.md`](intend.md) | 系统与各类 agent 的核心意图、取舍和拒绝项 |
| [`prd.md`](prd.md) | Hackathon MVP 的用户体验、技术选择和完成定义 |
| [`plan.md`](plan.md) | MVP 的实现顺序、范围和验收标准 |
| [`spec.md`](spec.md) | 数据契约、接口、幂等、配置与测试要求 |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | 长期系统架构、数据模型和设计原则 |
| [`PRODUCT.md`](PRODUCT.md) | 产品定位、竞品边界、创新假设和停止条件 |

建议阅读顺序：先读 `context.md`，再读 `prd.md` 和 `spec.md`，最后根据当前阶段查看 `plan.md` 或 `ARCHITECTURE.md`。

## 技术方向

当前实现使用 Python 3.12、`uv`、Typer、Rich、httpx、Pydantic v2 和 pytest。MVP 保持为一个简单的 Python 包，不提前引入 FastAPI、前端框架、队列、向量数据库或多 agent 编排框架。

推荐的最小目录如下：

```text
tellagent/
  __main__.py
  cli.py
  data.py
  metrics.py
  analyst.py
  schemas.py
  fixtures/demo_snapshot.json
  fixtures/demo_leverage_led.json
  fixtures/demo_spot_confirmed.json
tests/
```

## 验收标准

MVP 只有在以下条件同时满足时才算完成：

- 一条命令可以完成演示；
- 无网络时 fixture 模式仍然可用；
- 报告同时展示支持证据和反向证据；
- 指标在 agent 调用前已经计算完成；
- 缺失数据会降低确定性，而不是被模型隐藏；
- 主要输入输出有 Pydantic schema 和测试覆盖。

后续版本再验证连续观察是否比静态阈值更早、更少误报，以及自动复盘是否真正提升研究质量。投资收益不是第一阶段的唯一成功标准。

## 非目标

- 自动交易或仓位管理
- 高频盘口策略
- 全币种扫描
- 新闻、社交情绪或钱包标签平台
- 无证据的价格方向预测
- 为了演示而堆叠 dashboard 或复杂基础设施

## 开发原则

遇到实现选择时，优先级依次是：**可回放性、证据可追溯、失败可见、成本可测、实现简单、界面美观**。任何新功能都应能说明输入、输出、失败记录方式和未来验证方法。
