# Legacy: Transaction Gateway Route

这条路线已从 WebFA 主线移出。

旧定义：

```text
WebFA = Local Agent Action Transaction Gateway
plan -> preview -> approval -> execute -> verify -> proof -> audit
```

移出原因：

- 它容易把 WebFA 做成站点 API wrapper。
- GitHub/Hugging Face provider adapter 会把产品重心拉向业务动作库。
- approval/proof/audit 事务闭环不是 agent browser 的第一性原理。

保留原因：

- Electron shell 可复用。
- FastAPI Runtime 可复用。
- MCP stdio 可复用。
- `WEBFA_HOME`、SQLite、测试基础设施可复用。

默认行为：

- Console 不显示 transaction 主流程。
- MCP 不注册 transaction tools。
- 只有设置 `WEBFA_ENABLE_LEGACY_TRANSACTION=1` 时，旧 MCP tools 才作为 legacy 出现。

旧 P4 `github.patch_and_open_pr` worktree 不合并。
