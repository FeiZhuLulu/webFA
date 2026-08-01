# WebFA

**语言 / Language**：中文 | [English](https://github.com/FeiZhuLulu/webFA/blob/main/README.en.md)

WebFA 是一个本地运行的 **agent-native browser runtime**：给 agent 一套原生的网页访问接口，让 agent 像真实互联网用户一样浏览、操作和验证网页。

```text
agent -> webfa.open_url -> webfa.observe -> webfa.act -> webfa.observe
```

Agent 负责决策，WebFA 负责执行：打开真实网页、在隔离 Profile 中维护网站登录身份、返回结构化页面状态、执行语义化网页操作。人类 UI（Control Center / Session Monitor）只是监控、审批和接管面，不是产品主体。

WebFA 不是：传统浏览器加自动化、站点 API wrapper 的集合、内置智能体的桌面应用。

当前状态：**Developer Preview**，API 和行为仍可能变化。

## 工作原理

Agent 面对的是**网页对象**，不是 DOM：

```text
真实网页 -> WebObjectCompiler -> WebState（WebObjects / Capabilities）-> Agent 语义操作
```

`webfa.observe` 返回结构化的 `WebState`：可操作的网页对象、对象状态与关系、可用操作、文档版本和变更集。`webfa.act` 只接受对象声明的语义操作（如 `open`、`set_value`、`submit`、`choose`）。DOM、selector、坐标、鼠标键盘事件、CDP 都是 Runtime 内部实现，不进入公共协议。完整设计见 `docs/P10_WEBFA_OBJECT_MODEL_DESIGN.md`。

## 快速开始

环境要求：Python 3.12+，本机安装 Chrome 或 Edge。

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
webfa doctor        # 本地自检
```

生成 MCP 配置接入你的 agent：

```powershell
webfa mcp-config --agent-id <your-agent-name>
```

Agent 通过 MCP stdio 连接后，`webfa-mcp` 会自动复用或启动本地 Runtime（默认 `http://127.0.0.1:8787`），无需手动管理进程。各 agent 应使用独立的 `WEBFA_AGENT_ID`；不同 Profile 可以由不同 agent 并发使用。

接入指南：[opencode](docs/agent-integrations/opencode.md) · [Kimi Code](docs/agent-integrations/kimi-code.md) · [Claude Code](docs/agent-integrations/claude-code.md) · [Codex](docs/agent-integrations/codex.md)

## 登录与人工接管

Agent 不应该输入密码、验证码或 2FA。当页面进入登录、扫码或授权流程时，用户在 Session Monitor 中取得限时人工控制租约，直接在 Agent 正在使用的同一个页面上完成操作，然后归还控制权。Agent 之后重新 `observe` 再继续。

也可以用 CLI 预置登录态：

```powershell
webfa login github
webfa login --url https://example.com/login
```

## 能力一览

- 5 个 MCP 工具：`open_url`、`observe`、`act`、`get_tabs`、`switch_tab`，不多不少。
- Managed Chromium runtime，每个 Profile 独立的浏览器身份目录，不依赖 Playwright。
- 多 Profile 并发；同一 Profile 同时只允许一个可写 Session。
- Profile Bootstrap：人工登录、Cookie 导入、加密 `.webfa-profile` 身份包的导出与恢复。
- 高风险操作受 SafetyContext、Runtime 证据和安全回执约束；超出已配置自治边界时，才触发精确作用域、默认单次使用的 Step-up 人工确认。
- 可选的 Runtime Manager 桌面应用：监控 Agent/Session、审批、接管、生成 MCP 配置。

## 安全边界

默认不向 agent 暴露：cookies、localStorage/sessionStorage 值、token 与 authorization header、密码值、完整 DOM/HTML、selector/XPath/evaluate 逃生口、raw CDP。详见 `docs/P11_AGENT_SAFETY_CONTRACT_DESIGN.md`。

## 当前限制

- 同一 Profile 同时只有一个可写 Session（不同 Profile 可并发）。
- 不绕过反爬、验证码、风控或平台安全系统。
- `open_url` 和链接打开属于导航语义；如果网站滥用 GET 导航产生外部写入，Runtime 无法仅凭协议确定该业务副作用。
- 活跃 Session 和任务执行状态不跨 Runtime 重启保留（Durable Resume 属暂缓的 P13）。
- Runtime Manager 是监控和接管面，不是完整桌面浏览器，也不包含内置 Agent。

## 开发

```powershell
python -m pytest -q          # Python 测试
npm install                  # 可选：人类控制面（Renderer + Electron）
npm run dev                  # 启动 Visualizer，默认 http://127.0.0.1:8788
npm run typecheck:renderer
npm run typecheck:electron
```

常用环境变量见 `.env.example`；源码运行时数据默认存放在 `%APPDATA%\WebFA`。

## 文档

- 路线图：`docs/browser-runtime-roadmap.md`
- Object Model 设计：`docs/P10_WEBFA_OBJECT_MODEL_DESIGN.md`
- 安全契约设计：`docs/P11_AGENT_SAFETY_CONTRACT_DESIGN.md`
- 多 Session / 多 Profile 设计：`docs/P12_MULTI_SESSION_MULTI_PROFILE_DESIGN.md`
- 桌面分发架构：`docs/DESKTOP_DISTRIBUTION_ARCHITECTURE.md`
- 开源 Runtime 就绪状态：`docs/OPEN_SOURCE_READINESS.md`
- 候选发布门禁：`RELEASE_CHECKLIST.md`
- 当前阶段与证据矩阵：`docs/reports/PRE_P13_COMPLETION_EVIDENCE_MATRIX_21.md`
- 历史报告阅读须知：`docs/reports/README.md`（旧报告只代表当时的工程证据）

## License

MIT，见 `LICENSE`。
