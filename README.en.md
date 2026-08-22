<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/webfa-mark-light.svg">
    <img src="docs/assets/webfa-mark.svg" width="42" height="42" valign="middle" alt="WebFA">
  </picture>
  WebFA
</h1>

<p align="center"><strong>A local internet runtime for agents</strong></p>
<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="MIT License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.12+-green.svg?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12+"></a>
  <img src="https://img.shields.io/badge/Status-Developer%20Preview-yellow.svg?style=for-the-badge" alt="Developer Preview">
</p>
<p align="center"><a href="README.md">中文</a></p>

---

WebFA runs a real browser on your machine and hands the page to an external agent over MCP. The agent decides. The runtime executes.

```text
webfa.open_url → webfa.observe → webfa.act → webfa.observe
```

| Tool | What it does |
| --- | --- |
| `webfa.open_url` | Open a URL, optionally on a Profile |
| `webfa.observe` | Return operable objects, their state, and available actions |
| `webfa.act` | Run an action the object declares (fill, choose, submit, open) |
| `webfa.get_tabs` | List tabs |
| `webfa.switch_tab` | Switch tabs |

`observe` returns page objects, not the DOM, selectors, or coordinates. `act` cannot do anything an object did not declare. Cookies, tokens, passwords, full HTML, and CDP are not given to the agent by default.

Preload login with the CLI. Agents do not type passwords, CAPTCHAs, or 2FA:

```powershell
webfa login github
webfa login --url https://example.com/login
```

Different Profiles can run at the same time. One Profile has at most one writable Session. No CAPTCHA, anti-bot, or risk-control bypass. Active sessions do not continue after the runtime exits.

## Install

Python 3.12+, plus Chrome or Edge on the machine.

```powershell
git clone https://github.com/FeiZhuLulu/webFA.git
cd webFA
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
webfa doctor
webfa mcp-config --agent-id my-agent
```

Connecting over MCP starts the local runtime (default `http://127.0.0.1:8787`). Give each agent its own `WEBFA_AGENT_ID`.

[OpenCode](docs/agent-integrations/opencode.md) · [Kimi Code](docs/agent-integrations/kimi-code.md) · [Claude Code](docs/agent-integrations/claude-code.md) · [Codex](docs/agent-integrations/codex.md)

```powershell
python -m pytest -q
```

See `.env.example` for env vars. Data defaults to `%APPDATA%\WebFA`. [Roadmap](docs/browser-runtime-roadmap.md) · [MIT](LICENSE)
