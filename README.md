<div align="center">

# tellagent

**面向 BTC/ETH 的市场矛盾检测器**

持续整理证据 · 发现状态变化 · 明确说明什么会推翻当前判断

![Python](https://img.shields.io/badge/python-3.12-blue)
![managed by uv](https://img.shields.io/badge/managed%20by-uv-261230)
![status](https://img.shields.io/badge/status-demo-orange)
![license](https://img.shields.io/badge/license-MIT-green)

</div>

---

## 它是什么

一个**本地运行**的加密市场研究工具。它把 Coinbase 现货与 Deribit 衍生品整理成结构化市场快照，先用低成本规则 Observer（Jev）判断状态与证据冲突，**只在门控通过时**才调用受约束的强模型，生成同时包含正向、反向与缺失证据的研究报告。

它不是交易机器人，也不承诺预测下一根 K 线。它首先要回答三个问题：

- 当前市场更像什么状态？
- 哪些数据支持或反驳这个判断？
- 哪些新证据出现后，当前判断应该失效？

> 输出是**研究报告**，不是交易信号。

---

## 工作原理

```text
  Coinbase / Deribit 公共 API                      data.py
            │
            ▼
  确定性指标（收益 · 成交量变化 · 证据分类）         metrics.py
            │
            ▼
  MarketStateFrame（可回放的结构化快照）           observer.py
            │
            ▼
  Jev Observer（默认本地规则，可选远程）           observer.py
            │
            ▼
  确定性 Gate（只在状态跃迁或高优先级时放行）       gate.py
            │
            ▼
  强 Analyst（OpenAI-compatible，只能选已有证据）   analyst.py
            │
            ▼
  JSONL 相近记忆  +  Rich 报告           memory.py · renderer.py
```

每次输出还会给出结构化研究建议：`investigate_now`、`monitor` 或 `wait_for_confirmation`，包含研究重点、因子候选和失效条件。这些是研究动作，不是买入、卖出或仓位建议。Gate 会对持续不变的判断去抖，只有状态、概率、优先级或冲突角色变化时才再次调用强模型。

Observer 输出四种市场状态之一：

| 状态 | 含义 |
| --- | --- |
| `leverage_led` | 上涨可能主要由杠杆推动，现货确认不足 |
| `spot_confirmed` | 价格上涨得到现货成交确认 |
| `deleveraging` | 下跌伴随持仓收缩，市场可能正在去杠杆 |
| `uncertain` | 证据不足，无法确认主导状态 |

每次判断都附带概率分布、支持 / 反向 / 缺失角色、研究优先级（`silent` → `watch` → `significant` → `urgent`）和失效条件。

> **记忆**是轻量 append-only JSONL（`memory.jsonl`），只保留通过门控的上下文，不保存每一帧原始行情；检索按资产、状态与标签重叠度排序，把相近的历史判断注入强模型。

---

## 快速开始

需要 **Python 3.12** 与 [`uv`](https://docs.astral.sh/uv/)。

```bash
uv sync --dev
```

### 方式一 · 无需密钥

默认的 Jev Observer 是本地规则实现（`--provider rule`），只做确定性判断，不调用任何外部模型；`--analyst none` 跳过最贵的强 Analyst。

```bash
uv run python -m tellagent research --cycles 1 --analyst none
```

这一路径会真实采集数据、计算确定性指标、用本地规则做 Jev 判断与门控；门控通过时生成一份由代码计算的确定性报告（不调用任何外部模型）并写入 JSONL 记忆。

### 方式二 · 接入远程强模型

任何 OpenAI-compatible JSON API 都可以：

```bash
export TELLAGENT_MODEL_API_URL="https://your-provider.example/v1/chat/completions"
export TELLAGENT_MODEL_API_KEY="your-key"
export TELLAGENT_MODEL_NAME="your-model"

uv run python -m tellagent research --cycles 1 --analyst remote
```

远程模型只能**选择**代码生成的证据，不能覆盖资产、指标、时间或来源；一旦编造证据会直接报错。

### 持续运行

`--cycles 0` 会一直运行，直到 `Ctrl-C`：

```bash
uv run python -m tellagent research --cycles 0 --interval 300 --analyst remote
```

> **数据说明**　默认使用真实 Coinbase / Deribit 公共数据。实时模式会读取 Deribit 当前 open interest，并从第二轮开始用进程内上一轮真实值计算短周期变化；进程重启后的第一轮没有基线，会明确显示为缺失。1 小时 OI 变化仍不伪造。

---

## 配置

需要密钥的只有两个**可选**远程 Provider。

**远程强 Analyst**（`--analyst remote`）

| 环境变量 | 说明 | 默认 |
| --- | --- | --- |
| `TELLAGENT_MODEL_API_URL` | Chat completions 端点 | 必填 |
| `TELLAGENT_MODEL_API_KEY` | Bearer 密钥 | 必填 |
| `TELLAGENT_MODEL_NAME` | 模型名 | `market-analyst` |

**远程 Jev Observer**（`--provider jev`）

| 环境变量 | 说明 | 默认 |
| --- | --- | --- |
| `TELLAGENT_JEV_API_URL` | Jev 端点 | 必填 |
| `TELLAGENT_JEV_API_KEY` | Bearer 密钥 | 必填 |
| `TELLAGENT_JEV_MODEL` | 模型名 | `jev-observer` |

没有配置时使用默认本地规则 Observer，它实现与远程 Provider 相同的 `MarketStateFrame → ContinuousJudgment` 契约，但不调用外部模型。

---

## CLI 参考

```text
tellagent research [OPTIONS]
```

| 选项 | 说明 | 默认 |
| --- | --- | --- |
| `--asset TEXT` | 只研究单个资产，如 `ETH` | 全部 |
| `--cycles INT` | 迭代次数；`0` 表示持续运行直到中断 | `0` |
| `--interval FLOAT` | 迭代间隔（秒） | `300.0` |
| `--timeout FLOAT` | 公共 API 超时（秒） | `8.0` |
| `--memory-path PATH` | JSONL 记忆路径 | `.tellagent/memory.jsonl` |
| `--analyst TEXT` | 强 Analyst：`remote` 或 `none` | `remote` |
| `--provider TEXT` | Observer Provider：`rule` 或 `jev` | `rule` |

---

## 项目结构

```text
tellagent/
  cli.py          Typer 命令（只暴露 research）
  data.py         Coinbase / Deribit 公共数据适配
  metrics.py      确定性指标与证据分类
  observer.py     本地规则 Jev + 远程 Jev Provider + state frame 构建
  gate.py         evaluate_gate / should_investigate
  analyst.py      OpenAI-compatible 强 Analyst
  memory.py       append-only JSONL 记忆与检索
  research.py     唯一的循环编排入口
  renderer.py     Rich 报告
  schemas.py      Pydantic 契约
tests/            20 个单元与集成测试
```

运行测试：

```bash
uv run pytest
```

---

## 设计边界

**代码负责事实**　时间对齐、窗口、收益率、波动率、百分位、异常检测、数据质量和结果评价，全部由确定性代码（`metrics.py`）完成。

**Agent 负责关系**　Agent 只能阅读已经计算好的 JSON，判断市场状态、组织证据并给出有限文本摘要；不能抓取数据、重算指标、搜索新闻、编造因果或输出交易指令。

**研究与执行隔离**　系统不保存交易权限、不提供下单工具、不把研究优先级转换成仓位建议；所有模型输出都必须通过 Pydantic schema 校验。

---

## 已知限制与非目标

**当前 Demo 的限制**

- 实时模式没有历史数据库，只能在进程内计算相邻轮次的 open interest 变化；1 小时变化仍会明确显示为缺失；
- 远程 Analyst / Jev 需要自行提供兼容接口；
- 规则使用透明的演示阈值，尚未经过历史样本校准。

**明确不做**

- 自动交易与仓位管理
- 高频盘口策略
- 全币种扫描
- 新闻 / 社交情绪 / 钱包标签平台
- 无证据的价格方向预测
- 为演示而堆叠的 dashboard 或复杂基础设施

---

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [`context.md`](docs/context.md) | 当前决策、术语、不可违背的边界和未知项（建议先读） |
| [`prd.md`](docs/prd.md) | Hackathon MVP 的用户体验、技术选择和完成定义 |
| [`DEVELOPMENT.md`](docs/DEVELOPMENT.md) | 当前 Demo 的开发流程、范围、守则和验收标准 |
| [`plan.md`](docs/plan.md) | MVP 的实现顺序、范围和验收标准 |
| [`ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 长期系统架构、数据模型、接口契约和设计原则 |
| [`intend.md`](docs/intend.md) | 系统与各类 agent 的核心意图、取舍和拒绝项 |
| [`PRODUCT.md`](docs/PRODUCT.md) | 产品定位、竞品边界、创新假设和停止条件 |

建议顺序：`context.md` → `prd.md` → `plan.md` 或 `ARCHITECTURE.md`。

---

## 技术栈

Python 3.12 · [`uv`](https://docs.astral.sh/uv/) · Typer · Rich · httpx · Pydantic v2 · pytest

保持为单个 Python 包，不提前引入 FastAPI、前端框架、队列、向量数据库或多 agent 编排框架。

## 开发原则

遇到实现选择时，优先级依次是：**可回放性 → 证据可追溯 → 失败可见 → 成本可测 → 实现简单 → 界面美观**。任何新功能都应能说明输入、输出、失败记录方式和未来验证方法。

## 贡献与许可

欢迎提交 Issue 和 Pull Request，请先阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md)；安全问题请按 [`SECURITY.md`](SECURITY.md) 私下报告。

本项目基于 [MIT License](LICENSE) 开源 · Copyright (c) 2026 Leon (0xLeonhack)
