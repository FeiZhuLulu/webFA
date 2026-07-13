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

## P10 WebFA Object Model

WebFA 当前默认 Agent 接口已经迁移到正式的 **WebFA Object Model**，不再以 `click/type` 类浏览器自动化动作作为公共协议：

```text
真实网页
  -> WebObjectCompiler
  -> WebState / WebObjects / Capabilities
  -> Agent Semantic Operations
```

Agent 的正式目标接口是网页对象、对象状态、对象关系和语义操作。DOM、selector、坐标、鼠标键盘事件、CDP 和浏览器引擎协议都属于 Runtime 内部实现。

默认 MCP 已支持可查询的 `observe(page/object/query/changes)`、稳定对象身份、对象版本、文档 revision、ChangeSet、结构化集合/表格/表单，以及 `opaque_surface` 和 Human Takeover。旧 `BrowserState` / P7 action 仅保留为默认禁用的历史回归层；除非显式设置危险开关，否则返回 `410 legacy_browser_api_disabled`。完整设计见 `docs/P10_WEBFA_OBJECT_MODEL_DESIGN.md`。

## 当前能力

- 通过 MCP stdio 接入外部 agent。
- 默认只暴露 5 个 MCP 工具：
  - `webfa.open_url`
  - `webfa.observe`
  - `webfa.act`
  - `webfa.get_tabs`
  - `webfa.switch_tab`
- 使用本地 Managed Chromium runtime，并持久化默认用户 profile；不依赖 Playwright。
- 返回 agent 可读的 `WebState`，包含 WebObjects、对象关系、capabilities、document revision、ChangeSet、登录与 takeover 状态。
- `webfa.act` 只接受对象声明的 semantic operation；click/type/press 等浏览器原语只存在于 Runtime 内部实现。
- 默认使用 WebFA-owned Auth Surface，方便用户在 WebFA 接管区完成登录、扫码、验证码、2FA 和授权。
- 通过 active agent lease 限制同一时间只有一个 agent 修改浏览器状态，避免多个 agent 同时抢同一个页面。
- 提供 WebFA Visualizer MVP，用于查看 Runtime 状态、当前页面预览、Agent View、Safety Center、Step-up 和安全回执；完整 `/v1/visualizer/*` 控制面使用独立高熵 Token，与 Agent REST/MCP 隔离。
- P11 对高风险语义操作执行 SafetyContext、Runtime 证据提升、Profile/Origin 绑定、精确单次 Step-up、凭据接管、资源授权和金融策略。

## 当前限制

- Visualizer 目前是观察和接管面板，不是完整桌面浏览器；登录/扫码应在 WebFA 接管区完成。
- 连接同一个 Runtime 和 `WEBFA_HOME` 的所有 agent 默认共享同一个浏览器 profile，也就是共享同一组网站登录态。
- 多 profile、多 session 隔离尚未实现。
- WebFA 不绕过反爬、验证码、风控或平台安全系统。
- SafetyContext、Step-up、金融 usage、资源授权和 SafetyReceipt 当前仍是 session-local；崩溃恢复与持久化属于 P13。
- `open_url`/链接导航仍按导航语义处理；站点若滥用 GET 导航产生外部写入，Runtime 无法仅凭协议确定其业务副作用，这是当前已知边界。
- 仓库里仍保留少量历史 transaction/provider 代码作为 legacy；默认 MCP surface 不会暴露这些能力。原始 BrowserAction REST 默认禁用。

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

启动完整开发版 Visualizer（Renderer + Electron；Electron 负责生成控制 Token 并启动 Runtime）：

```powershell
npm run dev
```

`npm run dev:renderer` 只启动静态 Renderer，不具备安全注入的 Visualizer 控制 Token，因此不能作为完整控制面使用。

默认访问：

```text
http://127.0.0.1:8788
```

## 接入 Agent

生成标准 MCP 配置：

```powershell
webfa mcp-config --agent-id codex
```

生成 opencode 配置：

```powershell
webfa mcp-config --client opencode --agent-id opencode
```

每个 agent 应该配置独立的 `WEBFA_AGENT_ID`。WebFA 同一时间只允许一个 active agent 修改浏览器状态。其他 agent 仍然可以 observe，并会在 `WebState` 和 `/health` 中看到当前 active lease。

接入文档：

- `docs/agent-integrations/opencode.md`
- `docs/agent-integrations/kimi-code.md`
- `docs/agent-integrations/claude-code.md`
- `docs/agent-integrations/codex.md`

## 登录

为默认 WebFA profile 预置登录态：

```powershell
webfa login github
webfa login --url https://example.com/login
```

Developer Preview 的主路径是 WebFA-owned Auth Surface。agent 不应该输入密码、验证码或 2FA；当页面进入登录、扫码、验证码、2FA 或授权流程时，用户应在 WebFA UI 中央的“接管区”完成认证，之后 agent 继续调用 `webfa.observe` 读取登录后的页面状态。

`webfa login` 仍保留为手动预登录工具。独立可见 host 只作为 legacy fallback，需要显式设置 `WEBFA_AUTH_SURFACE_MODE=legacy`。

## 环境变量

如有需要，可以复制 `.env.example` 作为本地记录。常用变量：

```powershell
$env:WEBFA_RUNTIME_URL="http://127.0.0.1:8787"
$env:WEBFA_AGENT_ID="opencode"
$env:WEBFA_BROWSER_DRIVER="managed-chromium"  # 唯一支持的 BrowserHost 路径
$env:WEBFA_BROWSER_HEADLESS="0"
$env:WEBFA_AUTH_TAKEOVER="auto"
$env:WEBFA_AGENT_LEASE_TTL_SECONDS="600"
# 独立 Runtime 若需要 Visualizer 控制面，必须显式提供高熵随机值：
$env:WEBFA_VISUALIZER_CONTROL_TOKEN="<random-secret>"
# 仅历史测试使用；生产环境不要启用：
# $env:WEBFA_ENABLE_UNSAFE_LEGACY_BROWSER_API="1"
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

当前阶段：P10 WebFA Object Model、P11 Agent Safety Contract、P12 Multi Session / Multi Profile Core 与 Post-Core Profile Bootstrap 均已完成。P12 已建立持久 Profile Catalog、独立 Chromium Host 与跨进程锁、BrowserSessionRuntime、并发多 Profile SessionManager/Supervisor、连接级 Profile Grant、Session 独占 Lease、全局 Tab/WebObject 路由、保持五工具的 `profile_ref` 集成、指定 Session Monitor、VisualStreamHub、独立 HumanControl，以及 SafetyContext、Step-up、本地资源、支付授权和 SafetyReceipt 的连接/Session/generation 权限定域。Profile Bootstrap 已包含人工登录、Cookie import、Profile clone，以及 Scrypt + AES-256-GCM 加密的 `.webfa-profile` Bundle 导出/恢复；真实 Chromium 已验证多 Profile 存储隔离、Cookie 导入、身份克隆和加密 Bundle 往返。所有 Bootstrap 能力都只存在于受保护本地控制面，不进入 MCP、WebState、Monitor 或审计回执。设计见 `docs/P12_MULTI_SESSION_MULTI_PROFILE_DESIGN.md`，Bundle 报告见 `docs/reports/PROFILE_BOOTSTRAP_BUNDLE_REPORT.md`。

后续方向：

- P13 Durable Trace / Resume

## License

MIT. See `LICENSE`.
