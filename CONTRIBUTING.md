# 贡献指南

感谢你对 tellagent 感兴趣。这是一个本地运行的市场研究工具，范围刻意保持很小；提交代码前请先理解下面几条边界，能省下双方很多来回。

## 开始之前

按顺序读这几份文档：

1. [`context.md`](context.md) —— 当前决策、术语和不可违背的边界；
2. [`prd.md`](prd.md) 与 [`spec.md`](spec.md) —— 用户体验与数据契约；
3. [`DEVELOPMENT.md`](DEVELOPMENT.md) —— 当前开发流程与验收标准；
4. [`plan.md`](plan.md) / [`ARCHITECTURE.md`](ARCHITECTURE.md) —— 按当前阶段选读。

若你的改动会扩大范围（见下），请先开 Issue 讨论，不要直接提大 PR。

## 当前范围

**保持**：Python 3.12 + `uv`、Coinbase/Deribit 公共数据、BTC/ETH、Jev 结构化判断、门控后才调用强模型、JSONL 记忆、Rich 报告。

**不做**：运行时虚构行情或 fixture 场景、数据库/向量数据库、Web 与后台 Worker、多 Agent 编排、链上数据、自动交易与收益预测、事件生命周期与自动复盘。

测试里可以构造结构化样本和 Mock HTTP 响应，但不能把它们当作产品运行入口。

## 环境准备

```bash
uv sync --dev
```

## 提交前必须通过

```bash
uv run pytest
uv run python -m tellagent research --cycles 1 --analyst none
```

`--analyst none` 路径不需要任何密钥，会跑通数据采集 + 确定性指标 + Jev 门控 + 记忆写入。若改动了远程 Analyst / Jev 逻辑，请额外用你自己的兼容端点做一次真实单轮验证。

## 代码边界

改动应落在对应模块内，不要越界：

- `data.py` 只处理真实公共 API；
- `metrics.py` 只做确定性计算；
- `observer.py` 提供本地规则 Observer 与可替换的远程 Jev Provider；
- `gate.py` 只做纯函数门控，不重新判断市场；
- `analyst.py` 只保留远程强 Analyst；
- `memory.py` 使用 append-only JSONL；
- `research.py` 是唯一的循环编排入口；
- `renderer.py` 只负责 Rich 输出；
- `cli.py` 只暴露 `research` 命令。

## 工作流

1. 先定义输入、输出和失败情况；
2. 更新 Pydantic schema；
3. 用纯函数实现确定性逻辑；
4. 用 Mock API 或结构化样本补测试；
5. 在同一个提交里更新相关文档；
6. 每个可验证的小模块单独提交。

提交信息遵循 [Conventional Commits](https://www.conventionalcommits.org/)：`feat:` / `fix:` / `docs:` / `refactor:` / `build:` / `test:`。

## Pull Request 清单

- [ ] `uv run pytest` 通过；
- [ ] 真实数据路径没有引入虚构数据；
- [ ] 失败会被清晰报告，而不是回退到编造的行情；
- [ ] 没有新增不必要的基础设施；
- [ ] 提交里不含密钥、`.env` 或 `.tellagent/` 记忆文件；
- [ ] 主要输入输出有 schema 校验和测试覆盖；
- [ ] 相关文档已同步更新。

## 报告问题

普通 Bug 和功能建议请开 GitHub Issue，说明复现步骤、期望行为与实际行为。安全问题请改走 [`SECURITY.md`](SECURITY.md) 的私下渠道。
