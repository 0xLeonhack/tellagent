# tellagent Development Guide

这是一份面向当前 Hackathon Demo 的开发守则。它补充 `prd.md`、`plan.md` 和 `spec.md`，不替代产品设计或长期架构文档。

## 1. 当前目标

当前 Demo 已完成。它可以离线生成 BTC/ETH 市场矛盾报告：

```bash
uv run python -m tellagent demo --fixture
```

演示者应在 30 秒内看到：

- 数据时间和来源；
- BTC/ETH 的关键指标；
- 一句市场判断；
- 支持证据；
- 反向证据；
- 缺失数据；
- 失效条件。

项目首先证明“指标可以被组织成一条可质疑的研究判断”，不证明预测收益，也不提供交易建议。

## 2. 当前范围

### 必须完成

- Python CLI；
- BTC 和 ETH；
- Coinbase 现货数据结构；
- Deribit 永续数据结构；
- 固定 JSON fixture；
- 价格变化、现货成交量、funding、open interest 等少量指标；
- 一个 Market Analyst；
- Pydantic 输入输出校验；
- Rich 终端报告；
- 离线测试。

### 暂不实现

- 数据库和持久化服务；
- 后台常驻 worker 或定时任务；
- Web 前端和 dashboard；
- 多 Agent 编排；
- 链上数据；
- 全币种支持；
- 新闻或社交情绪分析；
- 用户系统和通知；
- 自动交易、仓位建议或收益预测；
- 复杂的事件生命周期、历史回放和自动复盘。

这些能力属于后续版本。不要为了“以后可能需要”提前加入基础设施。

## 3. 核心职责边界

```text
代码       读取数据、计算指标、检查质量、生成确定性证据
Agent      判断市场状态、组织支持/反向证据、写有限摘要
CLI        编排流程、校验结果、展示报告
```

代码必须负责：

- 时间窗口和变化率；
- 波动率、百分位或简单异常规则；
- 缺失值和异常值处理；
- 输入输出校验。

Agent 只能阅读已经计算好的结构化 JSON。Agent 不得：

- 自己抓取数据；
- 自己重新计算指标；
- 搜索或编造新闻原因；
- 把相关性写成因果关系；
- 输出买入、卖出或仓位指令；
- 在数据不足时假装确定。

## 4. 单个功能的开发流程

每个功能按照下面的顺序实现：

1. 先写清楚输入、输出和失败情况。
2. 先定义或更新 Pydantic schema。
3. 用纯函数实现确定性逻辑。
4. 用 fixture 跑通离线流程。
5. 为正常、缺失和异常情况补测试。
6. 再接入真实 API 或模型。
7. 更新 CLI、README 和必要的配置说明。

不要一开始同时接 API、模型和终端渲染。出现问题时，应该能够明确知道是数据、指标、模型还是展示层出了问题。

## 5. 模块拆分与渐进开发顺序

按照下面的阶段推进。每个阶段都先完成一个可运行的小闭环，再进入下一阶段。

### 阶段 0：项目骨架

文件：`pyproject.toml`、`tellagent/__init__.py`、`tellagent/__main__.py`

工作内容：配置 Python 3.12 和 `uv`，添加 Typer、Rich、Pydantic、httpx、pytest，并让 `python -m tellagent --help` 正常运行。

完成条件：项目可以安装，入口命令可以启动，尚无业务逻辑。

### 阶段 1：数据契约

文件：`tellagent/schemas.py`

工作内容：定义 `AssetSnapshot`、`MarketSnapshot`、`EvidenceBundle` 和 `MarketReport`，校验必填字段、枚举值和 confidence 范围。

完成条件：合法数据可以解析，非法数据会得到清晰的校验错误。

### 阶段 2：Fixture 数据

文件：`tellagent/fixtures/demo_snapshot.json`、`demo_leverage_led.json`、`demo_spot_confirmed.json`

工作内容：提供 BTC 和 ETH 的固定快照，覆盖“杠杆主导”和“现货确认”两个场景，并写明数据时间和来源。

完成条件：不访问网络也可以读取并通过 schema 校验。

### 阶段 3：确定性指标和证据

文件：`tellagent/metrics.py`

工作内容：计算 1h/6h 价格变化、现货成交量变化，检查 funding 和 open interest，判断价格、现货和杠杆是否背离，并输出支持、反向和缺失证据。

完成条件：相同输入始终产生相同结果，且不依赖模型或网络。

### 阶段 4：Fake Analyst

文件：`tellagent/analyst.py`

工作内容：接收已计算的结构化证据，用简单规则生成 `MarketReport`，并明确生成失效条件。此阶段不调用真实模型。

完成条件：Fixture 可以得到完整、稳定、可测试的报告。

### 阶段 5：终端渲染与 Demo 命令

文件：`tellagent/renderer.py`、`tellagent/cli.py`、`tellagent/__main__.py`

工作内容：增加 `demo` 命令，支持默认 fixture，使用 Rich 展示报告，并对数据错误输出可理解的信息。

完成条件：下面的命令可以离线完成一次完整演示：

```bash
python -m tellagent demo --fixture
```

### 阶段 6：测试

文件：`tests/test_schemas.py`、`tests/test_metrics.py`、`tests/test_demo.py`

工作内容：测试正常指标、缺失和异常数据、非法 Agent 输出，以及从 Fixture 到 CLI 的完整链路。

完成条件：`pytest` 通过，Demo 结果可重复。

### 阶段 7：实时数据适配器

文件：`tellagent/data.py`

工作内容：增加 Coinbase 现货和 Deribit 永续适配，将 API 响应转换为统一的 `MarketSnapshot`，并保留 Fixture 作为离线回退。

完成条件：实时 API 可用时读取实时数据，API 失败时不破坏离线 Demo。

### 阶段 8：真实模型适配

文件：`tellagent/analyst.py`

工作内容：增加一个真实模型 Client，集中管理 provider、model、API 地址和超时，只发送结构化快照和确定性证据，并对返回 JSON 做 Pydantic 校验。Fake Analyst 继续保留。

完成条件：模型失败、超时或返回非法 JSON 时，程序能安全失败并给出明确错误。

### 阶段 9：演示打磨

工作内容：准备多个固定演示场景，调整终端输出，更新安装和运行说明，确保观众能在两分钟内看懂“指标 → 证据关系 → 判断 → 失效条件”。

### 阶段依赖

```text
项目骨架 → 数据契约 → Fixture → 指标计算 → Fake Analyst
    → CLI 渲染 → 测试 → 实时 API → 真实模型 → 演示打磨
```

在阶段 6 的离线闭环稳定之前，不进入实时 API 和真实模型开发。

当前进度：阶段 0–9 已完成，并已增加轻量 Observer、JSONL 判断流、纯函数事件策略和可选远程 Jev Provider。后续修改仍需遵守小模块、先验证、再提交的流程，不在 Demo 分支继续加入数据库、Web、后台 worker 或多 Agent。

## 6. 推荐模块边界

```text
tellagent/
  __main__.py    Python 模块入口
  cli.py         Typer 命令和流程编排
  data.py        fixture/API 数据适配
  metrics.py     纯函数指标和证据计算
  analyst.py     Fake Analyst 与真实模型适配
  schemas.py     Pydantic 数据模型
  renderer.py    Rich 终端输出
  fixtures/      离线演示数据
tests/           单元测试和集成测试
```

模块之间通过明确的数据模型通信。不要让 CLI 直接访问模型响应字段，也不要让 Agent 模块直接读取原始 API 响应。

## 7. Fixture 优先

Fixture 是 Demo 的默认保障，不是临时测试文件。

要求：

- 无网络时可以完成完整演示；
- 数据时间和来源写在 fixture 中；
- fixture 结果稳定、可重复；
- 至少准备“杠杆主导”和“现货确认”两个场景；
- API 字段变化不能破坏 fixture 模式。

实时 API 失败时，应允许用户明确切换回 fixture，并输出可理解的错误信息。

## 8. Agent 输出规则

Agent 输出必须是严格 JSON，并通过 Pydantic 校验。报告至少需要：

```text
headline
state
confidence
supporting_evidence
contradicting_evidence
missing_evidence
invalidation_condition
```

如果没有反向证据，必须明确写出“未发现反向证据”或“数据不足”，不能返回空白字段来掩盖问题。

模型调用失败、超时、非法 JSON 和 schema 错误都必须变成用户能理解的错误。不能静默吞掉错误，也不能用未经校验的模型文本继续渲染报告。

## 9. 代码风格

- 使用 Python 类型注解；
- 指标计算优先使用无副作用纯函数；
- 函数保持短小，业务逻辑不堆进 CLI；
- 不为未来扩展提前增加抽象层；
- 不引入当前 Demo 不需要的框架；
- 注释只解释不明显的原因；
- 面向用户的输出保持清晰，避免堆叠内部术语；
- 所有时间使用明确的 UTC 表示；
- 不把“模型置信度”写成“预测正确率”。

## 10. 配置和安全

- 默认优先使用 fixture；
- API Key 只从环境变量或本地未提交配置读取；
- 不提交 `.env`、密钥或交易权限；
- 只使用只读市场数据权限；
- 日志不得输出密钥、完整 Prompt 或认证响应；
- provider、model、API 地址和超时应集中配置，不散落在业务代码中。

## 11. 测试和验收

每次完成一个垂直功能后，至少运行：

```bash
uv run pytest
uv run python -m tellagent demo --fixture
```

测试应覆盖：

- 价格上涨但 OI 增长更快；
- 价格上涨且现货成交同步确认；
- Funding 或 OI 缺失；
- 零值、异常值和边界窗口；
- 非法 Agent JSON；
- confidence 超出 0 到 1；
- 从 fixture 到 CLI 报告的完整流程。

MVP 完成前必须满足：

- 离线 Demo 可以运行；
- BTC 和 ETH 都有可读结果；
- 报告有支持证据；
- 报告有反向证据或明确的数据不足说明；
- 报告有失效条件；
- 主要输入输出经过 schema 校验；
- 测试通过；
- README 包含实际安装和运行方式。

## 12. Git 提交

每次提交尽量只完成一个小功能，推荐使用下面的前缀：

```text
feat: add demo fixture
feat: add metric calculation
feat: add analyst schema validation
fix: handle missing funding data
test: add fixture integration test
docs: update development guide
```

提交前检查：

```bash
git status
pytest
python -m tellagent demo --fixture
```

## 13. 开发判断准则

遇到取舍时，按以下顺序判断：

```text
可回放性
→ 证据可追溯
→ 失败可见
→ 成本可测
→ 实现简单
→ 界面美观
```

如果一个功能不能清楚回答“输入是什么、输出是什么、失败如何记录、未来如何验证”，它还不应该进入当前 Demo。
