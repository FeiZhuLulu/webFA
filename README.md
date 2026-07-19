# WebFA

**语言 / Language**：中文 | [English](https://github.com/FeiZhuLulu/webFA/blob/main/README.en.md)

WebFA 是一个本地运行的 **agent-native browser runtime**。

它的目标不是做一个“更适合 agent 操作的传统浏览器”，而是给 agent 一个原生的网页访问接口：

```text
agent -> webfa.open_url -> webfa.observe -> webfa.act -> webfa.observe
```

WebFA 不是传统浏览器 UI，不是站点 API wrapper，也不是内置智能体。
agent 决定要做什么；WebFA 负责打开真实网页、在隔离 Profile 中维护本地网站身份、返回结构化页面状态，并执行通用网页对象操作。

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
- 使用本地 Managed Chromium runtime；每个持久 Profile 使用独立的 Chromium 身份目录与 BrowserSession，不依赖 Playwright。
- 返回 agent 可读的 `WebState`，包含 WebObjects、对象关系、capabilities、document revision、ChangeSet、登录与 takeover 状态。
- `webfa.act` 只接受对象声明的 semantic operation；click/type/press 等浏览器原语只存在于 Runtime 内部实现。
- Session Monitor 投影 Agent 正在使用的同一个 BrowserHost 页面；用户取得限时、Session-scoped `HumanControlLease` 后，可以在该页面完成登录、扫码、验证码、2FA 和授权。
- 通过连接级 Profile Grant 和 SessionLease 限制同一 Profile 同时最多一个 agent 写入；不同 Profile 可以并发运行。
- 提供可选的轻量 WebFA Runtime Manager，用于查看 Runtime 状态、外部 Agent/Session、当前页面投影、Profile Bootstrap、Safety Center、Step-up 和安全回执；它不运行 Agent。Visualizer、Profile、Provider 凭据管理和人工审批决策使用独立高熵本地控制 Token，与 Agent REST/MCP 隔离；审批状态读取仍可供 Agent 轮询。
- P11 对高风险语义操作执行 SafetyContext、Runtime 证据提升、Profile/Origin 绑定、精确单次 Step-up、凭据接管、资源授权和金融策略。

## 当前限制

- Control Center 与 Session Monitor 是观察、管理和受限接管面，不是完整桌面浏览器；登录/扫码应在目标 Session 的 Monitor 中通过 HumanControl 接管完成。
- 同一持久 Profile 同时最多有一个可写 BrowserSession；不同 Profile 可以并发运行。
- WebFA 不绕过反爬、验证码、风控或平台安全系统。
- 活跃 Monitor/Profile Grant、任务 Trace 和可恢复执行状态不会跨 Runtime 重启保留；旧 Session 会被标记为 `interrupted`。Durable Trace / Resume 属于暂缓的 P13。
- `open_url`/链接导航仍按导航语义处理；站点若滥用 GET 导航产生外部写入，Runtime 无法仅凭协议确定其业务副作用，这是当前已知边界。
- 仓库里仍保留少量历史 transaction/provider 代码作为 legacy；默认 MCP surface 不会暴露这些能力。原始 BrowserAction REST 默认禁用。

## 安装

### 源码安装（推荐）

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
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

`webfa-mcp` 会复用已经运行且身份匹配的 Runtime；只有当 `WEBFA_RUNTIME_URL` 是 loopback HTTP 地址且端点不可达时，才会自动启动 Runtime。跨进程端点锁负责合并并发启动，每个 MCP client 持有独立 lease；最后一个 client 退出时，只会停止由 MCP auto-start 所拥有的 Runtime，绝不会停止 Desktop 或外部启动的 Runtime。

如需开发可选的人类控制面，再安装 Node 依赖并启动 Visualizer（Renderer + Electron；Electron 负责生成控制 Token 并启动 Runtime）：

```powershell
npm install
npm run dev
```

`npm run dev:renderer` 只启动静态 Renderer，不具备安全注入的 Visualizer 控制 Token，因此不能作为完整控制面使用。

默认访问：

```text
http://127.0.0.1:8788
```

### 可选：Windows x64 Runtime Manager 预览

仓库可以生成一个 Windows x64 developer-preview。它只是 WebFA Runtime 的本地宿主和人类管理面：负责启动 Runtime、展示外部 Agent/Session、生成 MCP 客户端配置以及提供监控、审批和 HumanControl；它不包含模型、规划器、任务循环或内置 Agent。每个外部 Agent 仍自行启动并持有自己的 MCP stdio 连接。

该预览内置 PyInstaller `onedir` sidecar，因此不要求系统安装 Python，但仍需要本机 Chrome 或 Edge。它不是当前开源 Runtime 源码/wheel 发布的前置条件，也尚未作为正式 Windows 产品发布。桌面打包、验证和未来正式发行门槛见 `docs/DESKTOP_DISTRIBUTION_ARCHITECTURE.md` 与 `RELEASE_CHECKLIST.md`。

## 接入 Agent

生成标准 MCP 配置：

```powershell
webfa mcp-config --agent-id codex
```

生成 opencode 配置：

```powershell
webfa mcp-config --client opencode --agent-id opencode
```

每个 agent 应该配置独立的 `WEBFA_AGENT_ID`。写权限不是全局单 agent 锁：同一 Profile 同时只能有一个可写 BrowserSession，同一 Session 的写操作由独占 Agent Lease 保护；其他 agent 仍可 observe，并能在 `WebState` 和 `/health` 中看到当前 lease。不同 Profile 的 Session 可以由不同 agent 并发运行。

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

Developer Preview 的主路径是 Session Monitor 对同一 BrowserHost 页面的投影。agent 不应该输入密码、验证码或 2FA；当页面进入登录、扫码、验证码、2FA 或授权流程时，用户在目标 Session 的 Monitor 中取得限时 `HumanControlLease` 并直接操作同一页面。页面键盘捕获期间按 Esc 会返回 Monitor 的“页面键盘”按钮，但不会释放租约；可按 Enter 重新进入，或 Tab 到“完成并归还 Agent”后归还控制权。接管期间只暂停该 Session 的 Agent 写入；释放、过期、撤销或断开连接后，agent 先调用新的 `webfa.observe` 再继续。

`webfa login` 仍保留为受保护的手动预登录工具。旧 duplicate-page Electron AuthSurface 已永久退休，不会关闭或重启 BrowserHost，也不会创建第二个页面；`WEBFA_AUTH_SURFACE_MODE=legacy` 只保留历史兼容用途，不是 packaged Desktop 的认证主路径。

## 环境变量

如有需要，可以复制 `.env.example` 作为本地记录。常用变量：

```powershell
$env:WEBFA_RUNTIME_URL="http://127.0.0.1:8787"
$env:WEBFA_AGENT_ID="opencode"
$env:WEBFA_BROWSER_DRIVER="managed-chromium"  # 唯一支持的 BrowserHost 路径
$env:WEBFA_BROWSER_HEADLESS="0"
$env:WEBFA_AUTH_TAKEOVER="auto"  # 仅 legacy visible-host 兼容路径
$env:WEBFA_AGENT_LEASE_TTL_SECONDS="600"
# 独立 Runtime 若需要本地人类控制面，必须显式提供高熵随机值（沿用此变量名）：
$env:WEBFA_VISUALIZER_CONTROL_TOKEN="<random-secret>"
# 仅历史测试使用；生产环境不要启用：
# $env:WEBFA_ENABLE_UNSAFE_LEGACY_BROWSER_API="1"
```

`WEBFA_AGENT_LEASE_TTL_SECONDS` 同时约束 P12 的连接独占 Session Lease。
仍在有效期内的连接每次成功使用五工具都会续租；过期 Lease 不会因只读调用而复活。

源码运行和独立 CLI 在 Windows 上如果没有设置 `WEBFA_HOME`，默认使用 `%APPDATA%\WebFA`。

以上变量面向源码运行、独立 CLI 和开发环境。Packaged Desktop 不把父进程中的任意 `WEBFA_*` 配置直接传给 sidecar：它只继承严格的操作系统环境白名单，校验 API host 只能是 loopback，并把 sidecar 的 `WEBFA_HOME` 强制设置为 Electron `app.getPath("userData")`，因此父进程提供的 `WEBFA_HOME` 不会改变 packaged Profile/Session 数据根。它还会注入确切的 Runtime 地址、版本/实例身份与浏览器模式。每次启动 owned Runtime 时，Desktop 都会生成新的高熵本地控制 Token，并把 Console/Monitor origin 精确绑定到本次本地 Renderer；packaged 模式忽略外部提供的固定控制 Token 和开发 Renderer URL。该 Token 通过 `X-WebFA-Visualizer-Token` 发送，只用于人类控制面，不进入 agent 的 MCP 配置。OpenAPI 将这些操作声明为 `VisualizerControlToken` API-key security scheme；普通 Agent Runtime 操作不声明或接收该凭据。

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

阶段完成状态、现行实现入口、维护中的测试门槛与历史报告之间的对应关系，见 `docs/reports/PRE_P13_COMPLETION_EVIDENCE_MATRIX_21.md`；阅读旧报告前先看 `docs/reports/README.md`，旧报告只代表当时的工程证据，不自动证明新的发布候选。

当前阶段：P10 WebFA Object Model、P11 Agent Safety Contract、P12 Multi Session / Multi Profile Core 与 Post-Core Profile Bootstrap 均已完成。P12 已建立持久 Profile Catalog、独立 Chromium Host 与跨进程锁、BrowserSessionRuntime、并发多 Profile SessionManager/Supervisor、连接级 Profile Grant、Session 独占 Lease、全局 Tab/WebObject 路由、保持五工具的 `profile_ref` 集成、指定 Session Monitor、VisualStreamHub、独立 HumanControl，以及 SafetyContext、Step-up、本地资源、支付授权和 SafetyReceipt 的连接/Session/generation 权限定域。Profile Bootstrap 已包含人工登录、Cookie import，以及面向 Agent 互联网身份的 Profile clone 和 Scrypt + AES-256-GCM 加密 `.webfa-profile` Bundle。Clone/Bundle 只迁移 Default Profile 的网站身份状态，明确排除历史、书签、密码/自动填充数据库、打开标签页、扩展和其他 Chrome 子 Profile；恢复只声明 browser storage restored，不承诺登录恢复。所有 Bootstrap 能力都只存在于受保护本地控制面，不进入 MCP、WebState、Monitor 或审计回执。设计见 `docs/P12_MULTI_SESSION_MULTI_PROFILE_DESIGN.md`，审查见 `docs/reports/PROFILE_BOOTSTRAP_ADVERSARIAL_REVIEW.md`。

当前工作：P13 暂缓。先完成 P1–P12 与 Post-Core Profile Bootstrap 的系统性收尾、维护和对抗性审查，并持续优化 Control Center 与 Session Monitor 的美观性、可用性、可访问性和响应式表现。

暂缓的后续方向：

- P13 Durable Trace / Resume

## License

MIT. See `LICENSE`.
