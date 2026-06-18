# WebFA Desktop

WebFA Desktop 是一个本地运行的 **agent-native browser runtime**。

一句话定义：

> WebFA 把真实网站转换成 agent 可读、可操作、可持续访问的联网环境。

WebFA 不是 GitHub/Hugging Face API wrapper，不是站点动作库，不是内置 agent，也不替 agent 做任务规划。Agent 负责理解目标和决定下一步；WebFA 负责打开网页、保持登录态、返回结构化页面状态，并按 element id 执行网页对象级动作。

## 当前主线

```text
v0.1.5  Phase 1: Runtime Core                 legacy
v0.2.0  Phase 2: MCP stdio                    legacy shell reused
v0.3.0  Phase 3: GitHub Read Context          legacy
v0.4.0  Phase 4: Agent Browser Runtime MVP    active
```

P4 核心闭环：

```text
agent -> open_url -> observe page_state -> act on element_id -> observe updated page_state
```

## Architecture

```text
Agent
  ↓ MCP stdio / local REST
WebFA Runtime
  ↓ BrowserDriver (internal Playwright Chromium)
Real websites
```

```text
webfa/
  apps/
    desktop/
      electron/          # Electron shell: window, tray, process managers
      renderer/          # Browser Debug Console
    runtime/
      api/routes/        # REST API endpoints
      mcp/               # MCP stdio server + HTTP client
      main.py            # FastAPI app

  packages/
    webfa-core/
      browser/           # Agent browser runtime
    schemas/
      browser.py         # BrowserState / BrowserAction contracts
    storage/             # SQLite + WEBFA_HOME paths
```

旧 transaction/provider/proof/audit 代码暂时保留为 legacy，默认 MCP 和 Console 不再走这条主线。

## Browser REST API

```text
POST /v1/browser/open
GET  /v1/browser/observe
POST /v1/browser/act
GET  /v1/browser/tabs
POST /v1/browser/tabs/switch
```

示例：

```json
{
  "action": "type",
  "target": "el_1",
  "text": "webfa"
}
```

约束：

- 对外只接受网页对象级动作。
- 不接受 raw Playwright、raw CDP、selector、xpath、locator、evaluate。
- 默认不返回完整 DOM/HTML。
- 默认不返回 cookies、localStorage、sessionStorage、IndexedDB、token 明文。

## MCP Tools

默认工具：

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

旧 transaction MCP tools 只有在显式设置时才注册：

```powershell
$env:WEBFA_ENABLE_LEGACY_TRANSACTION="1"
```

## Local Development

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
python -m playwright install chromium

npm install
npm run dev
```

Runtime only:

```powershell
python -m uvicorn apps.runtime.main:app --host 127.0.0.1 --port 8787 --reload
```

Check:

```powershell
pytest -q
npm run typecheck:renderer
npm run typecheck:electron
```

## Product Rules

- WebFA 是 agent browser，不是 API wrapper。
- WebFA 是工具，不是 agent。
- 智能在 agent，不在 WebFA。
- WebFA 不内置大模型。
- WebFA 不封装具体网站业务动作。
- WebFA 不主动破解网站接口。
- WebFA 不以截图为主路径。
- WebFA 以结构化页面状态为主输出。
- WebFA 以网页对象级动作为主操作方式。
- WebFA 必须支持用户登录态和持续 session。
