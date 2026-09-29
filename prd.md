# tellagent Hackathon MVP PRD

## 一句话

把 BTC/ETH 的几项市场指标交给一个受约束的 agent，让它生成一条包含正反证据的“市场矛盾报告”。

## 用户体验

用户运行：

```bash
python -m tellagent demo
```

系统展示：

1. 当前数据时间和数据来源；
2. BTC/ETH 的关键指标；
3. 一句市场判断；
4. 支持证据；
5. 反向证据；
6. 缺失数据；
7. 失效条件；
8. 数据不足时的明确声明。

## 产品故事

传统提醒会说“funding 很高”。tellagent 要演示的是：

> 价格上涨、OI 和 funding 同时扩张，但现货确认不足，因此上涨可能主要由杠杆推动；如果现货继续放量且 OI 回落，这个判断就失效。

这是研究提示，不是买卖建议。

## MVP 架构

```text
fixture/API
  ↓
data adapter
  ↓
metric calculator
  ↓
MarketSnapshot JSON
  ↓
one Market Analyst agent
  ↓
validated Report JSON
  ↓
CLI renderer
```

整个 MVP 可以是一个 Python 包、几个模块和一个命令，不需要服务拆分或数据库。

## 技术选择

- Python 3.12。
- `uv` 管理依赖。
- Typer + Rich：命令和终端报告。
- httpx：调用数据 API 和模型 API。
- Pydantic v2：输入输出校验。
- pytest：测试指标计算和 fixture 模式。
- 模型供应商通过一个很薄的 `generate_report(snapshot)` 函数隔离。

不使用 FastAPI、前端框架、SQLAlchemy、队列、向量数据库或 agent 编排框架，除非演示效果明确需要。

## Agent 约束

Agent 只能：

- 阅读已经计算好的 JSON；
- 选择市场状态；
- 组织支持、反向、缺失证据；
- 写出失效条件。

Agent 不能：

- 自己抓取数据；
- 自己计算收益率、百分位或相关性；
- 自己编造新闻和因果关系；
- 输出交易指令；
- 在缺失数据时装作确定。

## 最小目录

```text
tellagent/
  __main__.py
  cli.py
  data.py
  metrics.py
  analyst.py
  schemas.py
  fixtures/demo_snapshot.json
tests/
```

## Vibe coding 规则

- 先让 fixture 模式跑通，再接实时 API。
- 先定义 Pydantic schema，再让模型生成实现。
- 指标计算写成无副作用纯函数，方便快速测试。
- 所有外部调用都要有 fake 版本，不能让演示依赖网络。
- 每次只改一个垂直功能，并立即运行 `pytest`。
- 不为了“未来扩展”提前加入抽象层、数据库或多 agent。
- 任何模型输出都必须校验；解析失败要显示可理解的错误。
- 报告必须同时包含支持和反向证据；没有反向证据时必须写明“未发现/数据不足”。
- 所有提示词、模型名称和 API 地址放在配置中，不散落在业务代码里。

## 完成定义

演示者在没有额外说明的情况下运行命令，30 秒内看到一条完整报告；断网时使用 fixture 仍然成功；报告能让观众看出“指标 → 判断 → 反驳条件”的关系。
