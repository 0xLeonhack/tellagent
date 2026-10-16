<div align="center">

# tellagent

**BTC/ETH 持续市场研究 Agent**

真实行情 · 低成本状态判断 · 按需强模型分析 · 可回放研究账本

![Python](https://img.shields.io/badge/Python-3.12-blue)
![uv](https://img.shields.io/badge/managed%20by-uv-261230)
![status](https://img.shields.io/badge/status-demo-orange)
![license](https://img.shields.io/badge/license-MIT-green)

</div>

tellagent 每隔固定时间读取 Coinbase 现货和 Deribit 永续数据，由代码计算指标，由 Observer 判断市场状态，再由 Gate 决定是否调用 DeepSeek 等强模型。输出始终包含支持证据、反向证据、缺失数据和失效条件。

> 它生成研究报告和因子假设，不生成交易指令。

## 核心流程

```text
Coinbase / Deribit
        ↓
确定性指标与历史基线
        ↓
MarketStateFrame
        ↓
Observer（默认本地规则；Jev 可选）
        ↓
Gate（状态跃迁 / 概率跳变 / 优先级升级 / 冲突变化）
        ↓
强 Analyst（可选，OpenAI-compatible）
        ↓
Rich 报告 · JSONL 账本 · 自动复盘 · 因子假设
```

Observer 先拆分价格方向、价格强度、杠杆变化、现货确认、Funding、证据关系和数据质量，再派生 Regime：

| 状态 | 含义 |
| --- | --- |
| `spot_confirmed_up/down` | 上涨或下跌得到现货成交确认，杠杆变化有限 |
| `leverage_expansion_up/down` | 上涨或下跌伴随杠杆扩张，现货确认不足 |
| `position_unwind_up/down` | 价格变化伴随仓位收缩 |
| `broad_participation_up/down` | 现货活跃与杠杆扩张共同参与价格变化 |
| `quiet` | 价格、现货和杠杆活动均处于平静区间 |
| `conflicting` | 数据完整，但价格、现货与杠杆证据无法形成一致解释 |
| `insufficient_data` | 关键数据缺失，不能形成可靠判断 |

稳定状态不会重复调用强模型。只有状态、概率、研究优先级或冲突关系变化时，Gate 才重新放行。

## 已实现

- BTC/ETH 真实公共数据采集，不回退到虚构行情；
- 价格、成交量、Funding、Open Interest 与短周期 OI 变化；
- 本地规则 Observer 和可选 TypeSafe Jev Provider；
- 1/3/12 帧概率趋势、EWMA、持续帧数和状态翻转；
- 至少 24 个去重样本后启用有上下限的动态阈值；
- DeepSeek 等 OpenAI-compatible 强 Analyst；
- 稳定 Evidence ID，模型不能新增不存在的证据；
- Point-in-Time Frame/Judgment 账本；
- 6h、24h、7d 确定性 Outcome Review；
- JSONL 相近记忆、校准汇总、因子假设和 WorldQuant 研究草稿；
- Rich 终端报告。

## 快速开始

需要 Python 3.12 和 [`uv`](https://docs.astral.sh/uv/)。

```bash
uv sync --dev
```

复制 `.env.example` 为 `.env`，填入 DeepSeek Key 后可直接运行；`.env` 已被 Git 忽略。显式 `export` 的环境变量优先于 `.env`。

```bash
cp .env.example .env
```

### 无需密钥

使用真实行情、本地规则 Observer 和确定性报告：

```bash
uv run python -m tellagent research \
  --cycles 1 \
  --provider rule \
  --analyst none
```

### 接入 DeepSeek

```bash
export TELLAGENT_MODEL_API_URL="https://api.deepseek.com/chat/completions"
export TELLAGENT_MODEL_API_KEY="your-key"
export TELLAGENT_MODEL_NAME="deepseek-flash"

uv run python -m tellagent research \
  --cycles 1 \
  --provider rule \
  --analyst remote
```

强 Analyst 只在 Gate 放行时调用。模型只能引用冻结证据 ID，不能修改行情、来源或计算结果。

### 持续运行

```bash
uv run python -m tellagent research \
  --cycles 0 \
  --interval 300 \
  --provider rule \
  --analyst remote
```

`--cycles 0` 表示持续运行，使用 `Ctrl-C` 停止。黑客松 Demo 推荐 `--provider rule`；Jev API 不是运行前提。

## 可选 Jev Provider

官方 Jev System One 接口已经保留，但 Demo 默认不调用：

```bash
export TELLAGENT_JEV_API_KEY="your-key"
export TELLAGENT_JEV_MODEL="jev-latest"

uv run python -m tellagent research --cycles 1 --provider jev --analyst remote
```

| 环境变量 | 默认值 |
| --- | --- |
| `TELLAGENT_JEV_API_URL` | `https://api.typesafe.ai/v1/systemone` |
| `TELLAGENT_JEV_MODEL` | `jev-latest` |
| `TELLAGENT_JEV_API_KEY` | 必填 |

是否长期使用 Jev，应由它相对本地规则的提前量、误报率、成本和 Outcome 表现决定。

## 研究账本

所有运行数据写入 `.tellagent/`；`--memory-path` 的父目录决定账本位置。

| 文件 | 内容 |
| --- | --- |
| `frames/YYYY-MM-DD.jsonl` | 每帧指标、来源时间、响应哈希和数据质量 |
| `judgments/YYYY-MM-DD.jsonl` | 每次 Observer 概率、状态、优先级和延迟 |
| `memory.jsonl` | Gate 放行后的报告和相近上下文 |
| `events.jsonl` | 待复盘研究事件 |
| `outcomes/YYYY-MM-DD.jsonl` | 6h / 24h / 7d 确定性复盘 |
| `calibration_report.json` | 按状态与周期聚合的收益、波动和失效率 |
| `factor_hypotheses.jsonl` | 因子名称、输入、公式草稿、周期和测试计划 |
| `factor_results.jsonl` | 本地或外部回测结果契约 |
| `worldquant_drafts.md` | 带字段映射占位的 WorldQuant 研究草稿 |

这些文件均为 append-only 或可重建汇总，不要求数据库。

## CLI

```text
tellagent research [OPTIONS]
```

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--asset` | BTC + ETH | 只研究 `BTC` 或 `ETH` |
| `--cycles` | `0` | 迭代次数；`0` 表示持续运行 |
| `--interval` | `300` | 两轮之间的秒数 |
| `--timeout` | `8` | 公共 API 超时 |
| `--memory-path` | `.tellagent/memory.jsonl` | 记忆文件及账本目录 |
| `--provider` | `rule` | `rule` 或 `jev` |
| `--analyst` | `remote` | `remote` 或 `none` |

运行测试：

```bash
uv run pytest
```

## 当前限制

- 第一轮没有 OI 变化基线；第二轮起计算真实相邻采样变化；
- 1 小时 OI 变化没有历史源时保持缺失，不用短周期值冒充；
- 动态阈值需要至少 24 个去重样本，否则使用默认阈值；
- Outcome Review 需要进程持续运行，或之后重新启动并读取已有账本；
- WorldQuant 文件是研究草稿，必须映射平台字段并完成样本外验证；
- 系统不下单、不管理仓位、不承诺预测收益。

## 项目价值

- **压缩研究工作量**：把价格、现货成交、Funding 和 OI 组织成少量可检查的市场状态；
- **控制模型成本**：Observer 持续运行，Gate 只把真正变化的状态交给强模型；
- **约束模型幻觉**：强模型只能引用冻结的 Evidence ID，不能新增行情事实；
- **保留研究过程**：Frame、Judgment、报告、失效条件和 Outcome 都可回放；
- **形成可积累资产**：长期价值来自“当时看到了什么、如何判断、后来发生了什么”，而不是某个 Prompt；
- **连接主观研究与量化验证**：市场分析可以继续转化为结构化因子假设和测试计划。

## 可结合方向

| 方向 | tellagent 的作用 | 后续验证重点 |
| --- | --- | --- |
| 个人市场研究 | 过滤普通行情，只报告值得研究的状态变化 | 节省时间、误报率、报告可读性 |
| 策略 Regime Filter | 为趋势、Funding、套利等策略提供市场状态和风险开关 | 不同状态下的策略收益与回撤 |
| 因子研究 | 将杠杆主导、现货确认、去杠杆转成 `FactorHypothesis` | IC、Rank IC、换手率、成本后收益 |
| WorldQuant BRAIN | 导出表达式草稿和字段映射清单 | 平台字段适配、相关性、样本外表现 |
| 本地回测 | 用 Frame、Judgment 和 Outcome 构造状态标签与未来收益 | 数据泄漏、时间对齐、稳健性 |
| 风险监控 | 将高杠杆、证据冲突和数据缺失作为风险覆盖层 | 是否降低极端回撤和错误暴露 |
| 模型评估 | 对比规则 Observer、Jev 和其他模型 | 提前量、准确率、成本、延迟 |
| 通知系统 | Gate 放行后发送 Telegram、Slack、Email 或 Webhook | 告警密度和可操作性 |

最重要的研究闭环是：

```text
真实市场状态
  → 可证伪的研究判断
  → 因子或风险假设
  → 本地 / WorldQuant 验证
  → Outcome 写回
  → 校准 Observer、Gate 和策略
```

当前已经生成因子假设、结果契约和 WorldQuant 草稿，但尚未自动回测、自动提交 Alpha 或执行交易。下一阶段应优先积累真实判断与复盘样本，而不是增加币种、Agent 数量或界面。

## 文档

- [三分钟介绍](docs/PITCH.md)
- [当前决策](docs/context.md)
- [产品需求](docs/prd.md)
- [开发守则](docs/DEVELOPMENT.md)
- [架构与数据契约](docs/ARCHITECTURE.md)
- [产品假设与停止条件](docs/PRODUCT.md)
- [后续计划](docs/NEXT_STEPS.md)
- [贡献指南](CONTRIBUTING.md) · [安全策略](SECURITY.md) · [MIT License](LICENSE)
