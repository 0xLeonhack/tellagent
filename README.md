# tellagent

> 面向 BTC/ETH 的市场矛盾检测器：持续整理证据，发现状态变化，并明确说明什么会推翻当前判断。

![Python](https://img.shields.io/badge/python-3.12-blue)
![managed by uv](https://img.shields.io/badge/managed%20by-uv-261230)
![status](https://img.shields.io/badge/status-demo-orange)
![license](https://img.shields.io/badge/license-MIT-green)

tellagent 是一个本地运行的加密市场研究工具。它把 Coinbase 现货与 Deribit 衍生品整理成结构化市场快照，先用低成本规则 Observer（Jev）判断状态与证据冲突，只在门控通过时再调用受约束的强模型，生成同时包含**正向、反向与缺失证据**的研究报告。

它不是交易机器人，也不承诺预测下一根 K 线。它首先要回答三个问题：

1. 当前市场更像什么状态？
2. 哪些数据支持或反驳这个判断？
3. 哪些新证据出现后，当前判断应该失效？

## 设计取向

| 是 | 不是 |
| --- | --- |
| 连续观察、发现跨来源证据冲突 | 价格方向预测 |
| 保存「当时实际看到了什么」 | 事后挑选支持某故事的证据 |
| 研究报告（含失效条件） | 交易信号或仓位建议 |
| 单进程 CLI，本地运行 | Web 平台 / 多 Agent 编排 |

## 工作原理

```text
Coinbase / Deribit 公共 API
      ↓
确定性指标计算          metrics.py  —— 收益、成交量变化、证据分类
      ↓
MarketStateFrame        observer.py —— 可回放的结构化状态快照
      ↓
Jev Observer            observer.py —— 本地规则 / 可选远程 Provider
      ↓
确定性 Gate             gate.py     —— 只在状态跃迁或高优先级时放行
      ↓
强 Analyst              analyst.py  —— OpenAI-compatible，只能选已有证据
      ↓
JSONL 相近记忆 + Rich 报告          memory.py / renderer.py
```

Observer 输出四种市场状态之一：

| 状态 | 含义 |
| --- | --- |
| `leverage_led` | 上涨可能主要由杠杆推动，现货确认不足 |
| `spot_confirmed` | 价格上涨得到现货成交确认 |
| `deleveraging` | 下跌伴随持仓收缩，市场可能正在去杠杆 |
| `uncertain` | 证据不足，无法确认主导状态 |

每次判断都附带概率分布、支持/反向/缺失角色、研究优先级（`silent` / `watch` / `significant` / `urgent`）和失效条件。

## 快速开始

需要 Python 3.12 与 [`uv`](https://docs.astral.sh/uv/)。

```bash
uv sync --dev
```

**无需任何密钥**即可运行：默认的 Jev Observer 是本地规则实现（`--provider rule`），只做确定性判断，不调用任何外部模型，所以不需要 key；`--analyst none` 只是跳过最贵的强 Analyst 这一步。

```bash
uv run python -m tellagent research --cycles 1 --analyst none
```

这一路径会真实采集 Coinbase/Deribit 数据、计算确定性指标、用本地规则做 Jev 判断与门控，并写入 JSONL 记忆，只是不生成强模型的成文报告。需要密钥的只有两个**可选**远程 Provider：远程 Analyst（`--analyst remote`）和远程 Jev（`--provider jev`）。

默认使用真实 Coinbase/Deribit 公共数据。当前实时模式能计算 Coinbase 最近完成小时 K 线的价格与现货成交量变化，并读取 Deribit 当前 funding；由于没有本地历史行情，open interest 变化会明确显示为**缺失**，而不是被模型隐藏。

启用远程强模型（任何 OpenAI-compatible JSON API）后运行：

```bash
export TELLAGENT_MODEL_API_URL="https://your-provider.example/v1/chat/completions"
export TELLAGENT_MODEL_API_KEY="your-key"
export TELLAGENT_MODEL_NAME="your-model"
uv run python -m tellagent research --cycles 1 --analyst remote
```

远程模型只接收已经计算好的快照、Jev 判断和相近记忆，只能**选择**代码生成的证据，不能覆盖资产、指标、时间或来源；一旦编造证据会直接报错。

持续研究循环（`--cycles 0` 持续运行直到 `Ctrl-C`）：

```bash
uv run python -m tellagent research --cycles 0 --interval 300 --analyst remote
```

## 配置

远程强 Analyst（`--analyst remote`）：

| 环境变量 | 说明 | 默认 |
| --- | --- | --- |
| `TELLAGENT_MODEL_API_URL` | Chat completions 端点 | 必填 |
| `TELLAGENT_MODEL_API_KEY` | Bearer 密钥 | 必填 |
| `TELLAGENT_MODEL_NAME` | 模型名 | `market-analyst` |

远程 Jev Observer（`--provider jev`）：

| 环境变量 | 说明 | 默认 |
| --- | --- | --- |
| `TELLAGENT_JEV_API_URL` | Jev 端点 | 必填 |
| `TELLAGENT_JEV_API_KEY` | Bearer 密钥 | 必填 |
| `TELLAGENT_JEV_MODEL` | 模型名 | `jev-observer` |

没有这些配置时，请使用默认的本地规则 Observer（`--provider rule`）。它实现与远程 Provider 相同的 `MarketStateFrame → ContinuousJudgment` 契约，但不调用外部模型。

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

## 记忆

记忆是轻量 **append-only JSONL**（`memory.jsonl`），不是向量数据库。它只保留通过门控的上下文，不保存每一帧原始行情；检索按资产、状态和标签重叠度做简单排序，把相近的历史判断作为上下文注入强模型。

## 项目结构

```text
tellagent/
  __init__.py      包版本
  __main__.py      模块入口
  cli.py           Typer 命令（只暴露 research）
  data.py          Coinbase / Deribit 公共数据适配
  metrics.py       确定性指标与证据分类
  observer.py      本地规则 Jev + 远程 Jev Provider + state frame 构建
  gate.py          evaluate_gate / should_investigate
  analyst.py       OpenAI-compatible 强 Analyst
  memory.py        append-only JSONL 记忆与检索
  research.py      唯一的循环编排入口
  renderer.py      Rich 报告 / JSON 序列化
  schemas.py       Pydantic 契约
tests/             19 个单元与集成测试
```

## 测试

```bash
uv run pytest
```

## 设计边界

**代码负责事实。** 时间对齐、窗口、收益率、波动率、百分位、异常检测、数据质量和结果评价必须由确定性代码（`metrics.py`）完成。

**Agent 负责关系。** Agent 只能阅读已经计算好的 JSON，判断市场状态、组织证据并给出有限文本摘要。它不能抓取数据、重新计算指标、搜索新闻、编造因果关系或输出交易指令。

**研究与执行隔离。** 系统不保存交易权限、不提供下单工具，也不把研究优先级自动转换成仓位建议。所有模型输出都必须经过 Pydantic schema 校验。

## 已知限制与非目标

当前 Demo 的限制：

- 实时模式没有本地历史存储，无法计算 open interest 小时变化，会明确显示为缺失；
- 远程 Analyst / Jev 需要用户自行提供兼容接口；
- 规则使用透明的演示阈值，尚未经过历史样本校准。

明确不做：自动交易与仓位管理、高频盘口策略、全币种扫描、新闻/社交情绪/钱包标签平台、无证据的价格方向预测、为演示而堆叠的 dashboard 或复杂基础设施。

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

## 技术栈

Python 3.12、[`uv`](https://docs.astral.sh/uv/)、Typer、Rich、httpx、Pydantic v2、pytest。MVP 保持为单个 Python 包，不提前引入 FastAPI、前端框架、队列、向量数据库或多 agent 编排框架。

## 开发原则

遇到实现选择时，优先级依次是：**可回放性、证据可追溯、失败可见、成本可测、实现简单、界面美观**。任何新功能都应能说明输入、输出、失败记录方式和未来验证方法。

## 贡献与许可

欢迎提交 Issue 和 Pull Request，请先阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md)；安全问题请按 [`SECURITY.md`](SECURITY.md) 私下报告。

本项目基于 [MIT License](LICENSE) 开源，Copyright (c) 2026 Leon (0xLeonhack)。
