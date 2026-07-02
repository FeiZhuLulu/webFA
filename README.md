# WebFA

**语言 / Language**：中文 | [English](README.en.md)

WebFA 是一个本地运行的 **agent-native browser runtime**。

它的目标不是做一个“更适合 agent 操作的传统浏览器”，而是给 agent 一个原生的网页访问接口：

```text
agent -> webfa.open_url -> webfa.observe -> webfa.act -> webfa.observe
```

WebFA 不是传统浏览器 UI，不是站点 API wrapper，也不是内置智能体。
agent 决定要做什么；WebFA 负责打开真实网页、维护本地用户登录态、返回结构化页面状态，并执行通用网页对象操作。

当前状态：**Developer Preview**。API 和行为仍可能变化。

## 当前能力

- 通过 MCP stdio 接入外部 agent。
- 默认只暴露 5 个 MCP 工具：
  - `webfa.open_url`
  - `webfa.observe`
  - `webfa.act`
  - `webfa.get_tabs`
  - `webfa.switch_tab`
- 使用本地 managed Chromium runtime，并持久化默认用户 profile。
- 返回 agent 可读的 `BrowserState`，包含 URL 结构、表单、元素、内容块、登录状态、active agent lease 等信息。
- 支持通用网页对象动作，包括表单、链接、控件、列表、内容块，以及 click/type/press 等 fallback primitive。
- 默认使用可见 managed Chromium host，方便用户完成登录、扫码、验证码、2FA 和授权。
- 通过 active agent lease 限制同一时间只有一个 agent 修改浏览器状态，避免多个 agent 同时抢同一个页面。

## 当前限制

- 当前可见窗口仍是 managed Chromium window。后续会用 WebFA Visualizer 替换面向用户的接管界面。
- 连接同一个 Runtime 和 `WEBFA_HOME` 的所有 agent 默认共享同一个浏览器 profile，也就是共享同一组网站登录态。
- 多 profile、多 session 隔离尚未实现。
- WebFA 不绕过反爬、验证码、风控或平台安全系统。
- 发送、删除、购买、发布、修改设置等高风险最终动作还没有完整的人类确认层。
- 仓库里仍保留少量历史 transaction/provider 代码作为 legacy；默认 MCP surface 不会暴露这些能力。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
npm install
```

运行本地自检：

```powershell
webfa doctor
```

手动启动 Runtime：

```powershell
webfa-runtime
```

启动 MCP stdio server：

```powershell
webfa-mcp
```

`webfa-mcp` 会复用已经运行的 Runtime。如果 `WEBFA_RUNTIME_URL` 指向的位置没有可用 Runtime，它会自动启动一个。

## 接入 Agent

生成标准 MCP 配置：

```powershell
webfa mcp-config --agent-id codex
```

生成 opencode 配置：

```powershell
webfa mcp-config --client opencode --agent-id opencode
```

每个 agent 应该配置独立的 `WEBFA_AGENT_ID`。WebFA 同一时间只允许一个 active agent 修改浏览器状态。其他 agent 仍然可以 observe，并会在 `BrowserState` 和 `/health` 中看到当前 active lease。

接入文档：

- `docs/agent-integrations/opencode.md`
- `docs/agent-integrations/kimi-code.md`
- `docs/agent-integrations/claude-code.md`
- `docs/agent-integrations/codex.md`

## 登录

为默认 WebFA profile 打开手动登录窗口：

```powershell
webfa login github
webfa login --url https://example.com/login
```

Developer Preview 默认使用可见 managed Chromium host。agent 不应该输入密码、验证码或 2FA。用户在可见窗口中手动完成认证，之后 agent 继续调用 `webfa.observe` 读取登录后的页面状态。

如果用户在任务中关闭了可见窗口，当前 browser host 会结束。此时 `webfa.observe`、`webfa.act`、`webfa.get_tabs` 和 `webfa.switch_tab` 会返回 `browser_host_closed`。再次调用 `webfa.open_url` 会用同一个默认 profile 重新启动 host，但页面内存状态和旧 element id 会失效。

## 环境变量

如有需要，可以复制 `.env.example` 作为本地记录。常用变量：

```powershell
$env:WEBFA_RUNTIME_URL="http://127.0.0.1:8787"
$env:WEBFA_AGENT_ID="opencode"
$env:WEBFA_BROWSER_DRIVER="managed-chromium"
$env:WEBFA_BROWSER_HEADLESS="0"
$env:WEBFA_AUTH_TAKEOVER="auto"
$env:WEBFA_AGENT_LEASE_TTL_SECONDS="600"
```

Windows 上如果没有设置 `WEBFA_HOME`，WebFA 默认使用 `%APPDATA%\WebFA`。

## 本地开发

```powershell
python -m pytest -q
npm run typecheck:renderer
npm run typecheck:electron
python -m build
```

## 安全边界

WebFA 默认不应该向 agent 暴露：

- cookies
- localStorage / sessionStorage 值
- token 或 authorization header
- password value
- raw Playwright
- raw CDP
- selector / XPath / evaluate escape hatch
- 完整 DOM / HTML

默认 MCP 工具必须保持为 5 个 browser tools。历史 transaction MCP tools 只有在显式开启时才会出现：

```powershell
$env:WEBFA_ENABLE_LEGACY_TRANSACTION="1"
```

## 路线图

见 `docs/browser-runtime-roadmap.md`。

近期方向：

- P9 WebFA Visualizer
- P10 Element Registry v2
- P11 Multi Session / Multi Profile
- P12 Real Task Safety Layer

## License

MIT. See `LICENSE`.
