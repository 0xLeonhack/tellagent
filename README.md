<div align="center">

# tellagent

**BTC/ETH 持续市场研究 Agent**

真实行情 · 低成本状态判断 · 按需强模型分析 · 可回放研究账本

![Python](https://img.shields.io/badge/Python-3.12-blue)
![uv](https://img.shields.io/badge/managed%20by-uv-261230)
![status](https://img.shields.io/badge/status-demo-orange)
![license](https://img.shields.io/badge/license-MIT-green)

</div>

tellagent 每隔固定时间读取 Coinbase 现货和 Deribit 永续数据，由代码计算指标，由 Observer 判断市场状态，再由 Gate 决定是否唤醒研究 Agent。Agent 只能从 6 个动作和 6 个静态注册工具里选择下一步，输出始终包含支持证据、反向证据、缺失数据和失效条件。

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
┌─ workflow 模式（research）：直接调用强 Analyst
└─ agent 模式（agent）：Agent 在动作白名单内选下一步
       monitor / investigate / compare_history / generate_factor
       / wait_for_confirmation / finish   → 6 个静态注册工具
        ↓
Rich 报告 · JSONL 账本 · AgentTrace · 自动复盘 · 因子假设
```

两种模式共用同一条流水线和同一套账本。区别只有一个：**“什么状态值得研究”由 Gate 决定，
“下一步做什么研究动作”在 agent 模式里由 Agent 决定**——所以 Agent 可以在状态变化后仍然
判断“不值得研究”，从而省下强模型调用。Agent 的每一步（动作、理由、工具、参数、结果、错误）
都写进可回放的 AgentTrace。

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

## 受约束 Agent

Agent 的动作是静态白名单，代码拥有事实、工具执行、步数预算和模型调用预算：

| 动作 | 含义 |
| --- | --- |
| `monitor` | 状态平静，不值得研究（终止，不写报告） |
| `wait_for_confirmation` | 关键证据缺失，等待确认（终止，不写报告） |
| `investigate` | 需要更多事实，调用只读工具 |
| `compare_history` | 对比历史判断、记忆或复盘校准 |
| `generate_factor` | 把当前状态转成可验证的因子假设 |
| `finish` | 研究动作完成，生成完整报告（终止） |

| 工具 | 作用 |
| --- | --- |
| `read_recent_judgments` | 近期 Observer 判断 |
| `read_similar_memory` | 相近状态的历史研究记忆 |
| `read_outcome_calibration` | 按状态与周期聚合的确定性复盘 |
| `read_recent_outcomes` | 该资产的 6h / 24h / 7d 复盘 |
| `read_evidence_catalog` | 当前帧的冻结 Evidence 目录 |
| `create_factor_hypothesis` | 写入一个白名单因子假设（唯一写入工具） |

工具没有交易、Shell、Python 和网络出口；模型驱动的 Agent 每轮最多 3 步、最多 3 次决策调用；
若终端动作是 `finish` 或 `generate_factor`，再调用 1 次强 Analyst 生成报告（最多共 4 次模型调用）。
模型失败或返回非法决策时，账本记录 `rejected` 与错误原因，不重试、不伪造结果。

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
- 受约束 Agent 循环：6 动作白名单、6 个静态注册工具、步数与模型调用预算；
- 可回放的 AgentTrace 与 `agent-stats` 行为统计；
- 对已记录帧离线回放（`replay`），工具按 `as_of` 截断，不看未来数据；
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

### Agent 模式

把“下一步做什么研究动作”交给 Agent，而不是固定流水线：

```bash
uv run python -m tellagent agent --cycles 2 --interval 20 --provider rule --analyst none
```

`--agent-provider rule` 用本地确定性策略（无密钥可跑），`--agent-provider remote` 让模型自己选步骤。
`--always-investigate` 会绕过 Gate 冷却，把每一帧都交给 Agent，用于评估 Agent 自己的判断。

### 回放已记录帧

不需要网络，也不会改动原账本，只追加新的 trace：

```bash
cp -r examples/demo-ledger /tmp/tellagent-demo
uv run python -m tellagent replay --frames 3 --asset BTC \
  --memory-path /tmp/tellagent-demo/memory.jsonl --analyst none
```

`--frame-id` 可以精确回放某一帧。回放时工具只能看到该帧 `as_of` 之前已记录的内容。

### 查看 Agent 行为统计

```bash
uv run python -m tellagent agent-stats
```

### 审计数据与判断

```bash
# 离线：重算帧 ID/哈希、校验时间与概率、从冻结帧复现每条判断
uv run python -m tellagent audit --limit 200

# 联网：重新请求 Coinbase/Deribit，用独立实现重算全部指标，
# 并用公开 K 线回查每一帧记录时的现货指标
uv run python -m tellagent audit --limit 200 --live
```

审计失败时命令以退出码 1 结束。它不信任流水线自己的记账：帧 ID 由帧字段重算，
判断由另一条代码路径复现，实盘指标由独立公式重算。详见
[docs/ACCURACY.md](docs/ACCURACY.md)。

### 经验校准与 Gate 对照

```bash
uv run python -m tellagent evaluate --days 30
```

该命令下载 30 天公共小时 K 线和 funding 历史，输出真实特征分位数、前向信息检验，
以及同一批实盘判断上旧 Gate 与新 Gate 的升级/误报对照。历史 OI 不可得，
因此不做全状态回测，系统也不会编造这段数据。

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
| `agent_traces/YYYY-MM-DD.jsonl` | 每次 Agent 运行的完整 Trace：每步动作、理由、工具、参数、结果、终止与错误 |
| `factor_hypotheses.jsonl` | 因子名称、输入、公式草稿、周期和测试计划 |
| `factor_results.jsonl` | 本地或外部回测结果契约 |
| `worldquant_drafts.md` | 带字段映射占位的 WorldQuant 研究草稿 |

这些文件均为 append-only 或可重建汇总，不要求数据库。

## CLI

```text
tellagent research | agent | replay | agent-stats | audit | evaluate
```

`research` 与 `agent` 共有：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--asset` | BTC + ETH | 只研究 `BTC` 或 `ETH` |
| `--cycles` | `0` | 迭代次数；`0` 表示持续运行 |
| `--interval` | `300` | 两轮之间的秒数 |
| `--timeout` | `8` | 公共 API 超时 |
| `--memory-path` | `.tellagent/memory.jsonl` | 记忆文件及账本目录 |
| `--provider` | `rule` | Observer：`rule` 或 `jev` |
| `--analyst` | `remote` | 强 Analyst：`remote` 或 `none` |

`agent` 与 `replay` 额外支持：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--agent-provider` | `rule` | Agent 决策方：`rule` 或 `remote` |
| `--agent-steps` | `3` | 每帧最多步数（1–10） |

`agent` 额外支持：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--always-investigate` | 关闭 | 绕过 Gate 冷却，每帧都交给 Agent（评估开关） |

`replay` 额外支持：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--frames` | `1` | 回放最近的 N 个记录帧 |
| `--frame-id` | 无 | 精确回放某一个记录帧 |

`agent-stats` 支持 `--asset` 与 `--memory-path`。

`audit` 支持 `--asset`、`--limit`、`--live`、`--timeout` 与 `--memory-path`；
`evaluate` 支持 `--days`（7–90）、`--asset`、`--memory-path` 与 `--json`。

运行测试：

```bash
uv run pytest
```

## 当前限制

- 第一轮没有 OI 变化基线；第二轮起计算真实相邻采样变化；
- Coinbase 最新小时 K 线会等 5 分钟结算后再使用，避免交易所修订期的收盘价和成交量污染判断；
- 1 小时 OI 变化没有历史源时保持缺失，不用短周期值冒充；区间 OI 变化先归一化为每小时变化率；
- 公开接口没有历史 OI，因此无法做全状态历史回测；阈值基于可获得的真实价格、
  成交量和 funding 分布校准，见 [docs/ACCURACY.md](docs/ACCURACY.md)；
- Observer 输出的是证据加权 softmax 分布，不是经过概率校准的预测；UI 标记为“启发式分数”；
- 动态阈值需要至少 24 个去重样本，否则使用默认阈值；
- Outcome Review 需要进程持续运行，或之后重新启动并读取已有账本；
- 新账本的头几帧通常是 `insufficient_data` / `quiet`，要看到 Agent 的升级链路需要状态发生变化
  （用 `replay` 或已有账本演示更稳定）；
- 文件账本适合单机持续运行，不是并发多实例的存储层；
- WorldQuant 文件是研究草稿，必须映射平台字段并完成样本外验证；
- 系统不下单、不管理仓位、不承诺预测收益。

## 项目价值

- **压缩研究工作量**：把价格、现货成交、Funding 和 OI 组织成少量可检查的市场状态；
- **控制模型成本**：Observer 持续运行，Gate 只唤醒 Agent，Agent 还会自己判断是否值得研究；
- **可评估的自主性**：Agent 的动作、工具、理由和终止原因全部入账，`agent-stats` 给出步数、工具成功率、升级率和分布；
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

- [三分钟演示脚本](docs/DEMO.md)
- [三分钟介绍](docs/PITCH.md)
- [当前决策](docs/context.md)
- [产品需求](docs/prd.md)
- [开发守则](docs/DEVELOPMENT.md)
- [架构与数据契约](docs/ARCHITECTURE.md)
- [产品假设与停止条件](docs/PRODUCT.md)
- [后续计划](docs/NEXT_STEPS.md)
- [Agent 重构计划](docs/PLAN4AGENT.md)
- [贡献指南](CONTRIBUTING.md) · [安全策略](SECURITY.md) · [MIT License](LICENSE)
