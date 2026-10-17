# 三分钟 Demo 脚本

面向黑客松评委：不需要密钥也能跑完主流程，需要密钥时展示模型自主决策。

```bash
uv sync --dev
```

## 0. 一句话定位

> tellagent 把 Coinbase 现货与 Deribit 永续的真实数据，压缩成少量可检查的市场状态；
> 状态变化时唤醒一个**受约束的研究 Agent**，它只能从 6 个动作和 6 个工具里选择下一步，
> 产出带支持证据、反向证据、缺失数据和失效条件的研究报告与因子假设，全过程可回放。

## 1. 不需要密钥：确定性主流程（约 40 秒）

**工作流模式**（固定流水线，Gate 放行就直接写报告）：

```bash
uv run python -m tellagent research --cycles 2 --interval 20 --provider rule --analyst none
```

**Agent 模式**（Gate 只决定“什么时候唤醒 Agent”，Agent 自己决定“做什么研究动作”）：

```bash
uv run python -m tellagent agent --cycles 2 --interval 20 --provider rule --analyst none
```

看点：终端会先打印 `Observer 判断` 和 `研究建议`。Gate 静默时不会启动 Agent，
因此没有 `Agent 轨迹`；Gate 放行后才显示 Agent 的动作与工具。第 2 节的回放会绕过实时 Gate，
可以稳定展示 Agent 对 quiet 帧自主选择 `monitor`。

## 2. 断网也能复现：回放真实记录帧（约 30 秒）

`examples/demo-ledger/` 是 2026-10-16 用真实公开数据记录下来的账本（frames + judgments），
回放不重新抓行情，也不会改动原账本。先复制一份，保证仓库干净：

```bash
cp -r examples/demo-ledger /tmp/tellagent-demo
uv run python -m tellagent replay --frames 3 --asset BTC \
  --memory-path /tmp/tellagent-demo/memory.jsonl --analyst none
```

稳定复现三种行为：

| 记录帧状态 | Agent 轨迹 | 结果 |
| --- | --- | --- |
| `quiet` / `silent` | `1. monitor` | 不生成报告 |
| `conflicting` / `watch` | `1. investigate → read_recent_judgments`；`2. generate_factor → create_factor_hypothesis`；`3. finish` | 生成报告 + 因子假设 |

回放同时验证了 Point-in-Time 纪律：工具只能看到 `as_of` 之前已记录的内容，看不到未来数据。

### 为什么不能靠现场等事件

默认 Observer（`--provider rule`）是本地规则代码，不调用模型；只有 Gate 发现新的材料性信号后，
才会调用远程 Agent，强 Analyst 是否调用再由 Agent 决定。真实市场大多数时间平静，所以现场演示的期望是：

- 多数五分钟采样不会产生新的材料性状态；
- Gate 只在新状态或证据关系发生材料变化时放行；
- 3–10 分钟的现场窗口不能保证刚好命中事件。

这不是缺陷，而是 Gate 的目的：过滤噪声、控制成本。演示时把“现场静默”当作第一幕，
用第 2 节的真实记录帧回放展示完整链路；不要为了现场效果调低阈值或伪造行情。

如果使用 `--provider jev`，Observer 本身每帧每资产调用一次模型：60 秒间隔即 120 次/小时
（两个资产），300 秒间隔为 24 次/小时。因此默认使用 `rule`，Jev 只按需启用。

## 3. 接入模型：让模型自己决策（需要 `TELLAGENT_MODEL_API_KEY`）

```bash
uv run python -m tellagent replay --frame-id 9e873b25ef278057 \
  --memory-path /tmp/tellagent-demo/memory.jsonl \
  --agent-provider remote --analyst none
```

模型会在允许的动作与工具中自己选步骤，并给出理由；它也可以选择 `monitor` 而不升级报告：

```text
Agent 轨迹  BTC:9e873b25ef278057 · 决策方 remote-agent · 2 步 · 模型调用 2 次
  1. compare_history  ... need historical calibration for conflicting BTC states ...
     工具 read_outcome_calibration → ok 缺失
  2. monitor  冲突状态持续，但历史校准数据不可用……不值得生成完整研究报告
  终止: monitor · confidence 82%
```

对比同一条数据、`--agent-provider rule`（第 2 节）会走完 `investigate → generate_factor → finish`
并生成报告。**同一帧、两套决策方，结果不同，过程都留在账本里**——这正是可评估的地方。

完整 Agent 模式（Agent 决策 + 强 Analyst 写报告）：

```bash
uv run python -m tellagent agent --cycles 2 --interval 20 \
  --provider rule --agent-provider remote --analyst remote
```

## 4. 评估视图：Agent 到底做了什么（约 10 秒）

```bash
uv run python -m tellagent agent-stats
```

```text
tellagent · Agent 行为统计
来自 .tellagent/agent_traces 的可回放记录。
  运行次数 / 平均步数 / 平均工具调用 / 平均模型调用 / 升级报告比例 / 工具成功率
动作分布  finish · generate_factor · investigate · monitor
工具分布  create_factor_hypothesis · read_recent_judgments
终止动作  finish · monitor
```

每次运行的完整 `AgentTrace`（每一步的动作、理由、工具、参数、结果、错误）写在
`.tellagent/agent_traces/YYYY-MM-DD.jsonl`，`--asset` 可以只看一个币种。

## 5. 评委常问的几个问题

**这是不是只是把 Prompt 包装成 Agent？**
不是。代码拥有事实、工具执行、动作白名单、步数预算和模型调用预算；模型只能从
`monitor / investigate / compare_history / generate_factor / wait_for_confirmation / finish`
里选一个，从 6 个静态注册工具里选一个，并用固定 Evidence ID 引用证据。

**怎么防止它胡说或偷偷下单？**
工具里没有交易、Shell、Python 和网络出口；`create_factor_hypothesis` 只能写白名单因子；
模型报错时账本记录错误并保留 `terminal_action=rejected`，绝不会用编造结果顶上。

**为什么值得信？**
报告必须同时给出支持证据、反向证据、缺失数据和失效条件；判断和复盘都是确定性的，
`.tellagent/` 里的 Frame、Judgment、AgentTrace、Outcome 都可以重放。

**成本和延迟？**
Observer 和 Gate 在本地跑，稳定状态不唤醒 Agent；模型驱动的 Agent 每轮最多 3 次决策调用，
步数上限默认 3（`--agent-steps`）；若终端动作是 `finish` 或 `generate_factor`，再调用 1 次
强 Analyst 写报告（最多共 4 次）。`agent-stats` 里的“平均模型调用”包含报告调用，就是这笔账。

**和 workflow 模式（`research`）的关系？**
同一条流水线、同一套账本。`research` 是确定性流水线；`agent` 把“下一步做什么研究”交给 Agent，
所以 Agent 可以在状态变化后仍然判断“不值得研究”，省下强模型调用。

## 6. 诚实说明的边界

- 只做研究与因子假设，不下单、不管理仓位、不承诺收益；
- `examples/demo-ledger/` 是真实数据的**离线快照**，只用于回放，不参与实时运行；
- 新账本的头几帧一般是 `insufficient_data` / `quiet`，要看到升级链路需要状态发生变化，
  所以推荐用 `replay` 或已有账本演示；
- 远程模型在 `conflicting / watch` 帧上偏向 `monitor`（第 3 节对比可见），这是被记录、被统计的
  行为差异，而不是隐藏的失败；
- 模型失败时该帧没有报告，账本里留下 `rejected` 或错误信息，不重试、不修补。
