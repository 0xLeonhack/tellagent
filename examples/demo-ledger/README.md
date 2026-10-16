# demo-ledger

2026-10-16 用真实公开数据（Coinbase 现货 + Deribit 永续）记录下来的点时间账本快照，
包含 `frames/` 与 `judgments/`，用于离线、可重复地演示 Agent 回放。

它不参与实时运行，也不会被实时运行修改。用法见 [docs/DEMO.md](../../docs/DEMO.md)：

```bash
cp -r examples/demo-ledger /tmp/tellagent-demo
uv run python -m tellagent replay --frames 3 --asset BTC \
  --memory-path /tmp/tellagent-demo/memory.jsonl --analyst none
```

复制到 `/tmp` 再跑，是为了让回放新写入的 trace 和因子假设不落在仓库里。
