# WebFA Desktop 路线与冻结约束

## 方向冻结

WebFA 是 **agent-native browser runtime**。

它的职责是：

```text
打开真实网站
保持用户登录态
返回 agent 可读的 page_state
把网页元素转换成 element_id
执行 agent 发出的网页对象级动作
```

它不做：

```text
站点 API wrapper
站点业务动作
内置 agent
任务规划
LLM summary
raw Playwright/CDP 暴露
反检测/多账号运营
```

核心循环：

```text
observe -> act -> observe -> act
```

不是旧的：

```text
preview -> approval -> execute -> verify -> proof
```

## P4 — Agent Browser Runtime MVP

状态：active

目标：

```text
agent -> open_url -> observe page_state -> act on element_id -> observe updated page_state
```

交付物：

- Browser Runtime：内部使用 Playwright Chromium persistent context。
- Agent View：DOM + accessibility/ARIA + visible text + forms + tabs 多源融合。
- Element Registry MVP：临时使用 `data-webfa-id`，导航后要求重新 observe。
- Browser REST API：`open / observe / act / tabs / switch_tab`。
- MCP browser tools：`open_url / observe / act / get_tabs / switch_tab`。
- Browser Debug Console。

冻结约束：

- P4 只做一个 `default` session。
- 默认 headful，支持用户登录、验证码、2FA、观察和接管。
- Playwright 是内部实现细节，不进入公共 API。
- REST/MCP 不接受 selector/xpath/locator/evaluate/raw CDP。
- 默认不返回完整 DOM/HTML。
- 默认不返回 cookies/storage/token 明文。
- 不注册旧 transaction MCP tools，除非 `WEBFA_ENABLE_LEGACY_TRANSACTION=1`。
- Console 不显示 GitHub PAT、provider cards、approval/proof。

## P4.5 — Agent Validation Harness

状态：active next

目标：

```text
验证外部 agent 通过 MCP stdio 能把 WebFA 当浏览器使用。
```

交付物：

- 固定本地验证页：`tests/fixtures/agent_validation_page.html`。
- REST 层验证：打开页面、observe、type、click、observe。
- MCP stdio 验证：真实 MCP client 调用 `webfa.open_url / observe / act`。
- Agent 接入文档：`AGENT_VALIDATION.md`。

冻结约束：

- P4.5 不新增站点业务工具。
- P4.5 不做 GitHub/微博/登录真实任务。
- P4.5 不做多 session、inspect_element、LLM summary、自研 driver。
- 默认 MCP 工具列表必须只有 browser tools。
- 旧 transaction 测试只能作为 legacy 保留，不能代表主线验收。

## Legacy

旧 Phase 1-3 的 transaction gateway 代码保留为 legacy，因为其中的 Electron shell、FastAPI Runtime、MCP stdio、storage 路径仍可复用。

旧路线不再作为产品主线：

- GitHub PR Transaction
- Hugging Face Transaction
- provider adapter
- plan/preview/approval/execute/proof/audit 事务闭环

详情见 `docs/abandoned/transaction-gateway.md`。
