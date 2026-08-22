<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/webfa-mark-light.svg">
    <img src="docs/assets/webfa-mark.svg" width="42" height="42" valign="middle" alt="WebFA">
  </picture>
  WebFA
</h1>

<p align="center"><strong>本机 Agent 互联网运行时</strong></p>
<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="MIT License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.12+-green.svg?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12+"></a>
  <img src="https://img.shields.io/badge/Status-Developer%20Preview-yellow.svg?style=for-the-badge" alt="Developer Preview">
</p>
<p align="center"><a href="README.en.md">English</a></p>

---

WebFA 在本机跑真实浏览器，通过 MCP 把网页交给外部 Agent。Agent 决策，Runtime 执行。

```text
webfa.open_url → webfa.observe → webfa.act → webfa.observe
```

| 工具 | 做什么 |
| --- | --- |
| `webfa.open_url` | 打开网址，可指定 Profile |
| `webfa.observe` | 返回当前页可操作对象、状态和可用动作 |
| `webfa.act` | 对指定对象执行它声明的操作（填写、选择、提交、打开） |
| `webfa.get_tabs` | 列出标签页 |
| `webfa.switch_tab` | 切换标签页 |

`observe` 给的是页面对象，不是 DOM / selector / 坐标。`act` 不能越权做对象没声明的事。Cookie、令牌、密码、整页 HTML、CDP 默认不给 Agent。

登录用 CLI 预置，Agent 不填密码、验证码、2FA：

```powershell
webfa login github
webfa login --url https://example.com/login
```

不同 Profile 可并发；同一 Profile 同时只能有一个可写 Session。不绕过验证码、反爬、风控。关掉 Runtime，进行中的会话不会接着跑。

## 安装

Python 3.12+，本机 Chrome 或 Edge。

```powershell
git clone https://github.com/FeiZhuLulu/webFA.git
cd webFA
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
webfa doctor
webfa mcp-config --agent-id my-agent
```

连上 MCP 后会自动拉起本机 Runtime（默认 `http://127.0.0.1:8787`）。每个 Agent 用自己的 `WEBFA_AGENT_ID`。

[OpenCode](docs/agent-integrations/opencode.md) · [Kimi Code](docs/agent-integrations/kimi-code.md) · [Claude Code](docs/agent-integrations/claude-code.md) · [Codex](docs/agent-integrations/codex.md)

```powershell
python -m pytest -q
```

环境变量见 `.env.example`，数据目录默认 `%APPDATA%\WebFA`。[路线图](docs/browser-runtime-roadmap.md) · [MIT](LICENSE)
