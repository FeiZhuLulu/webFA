<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/webfa-mark-light.svg">
    <img src="docs/assets/webfa-mark.svg" width="42" height="42" valign="middle" alt="">
  </picture>
  WebFA
</h1>

<p align="center"><strong>Give your AI agent a real way onto the internet</strong></p>
<p align="center">It runs on your machine: open real pages, see what can be done, act, and check the result</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="MIT License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.12+-green.svg?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12+"></a>
  <img src="https://img.shields.io/badge/Status-Developer%20Preview-yellow.svg?style=for-the-badge" alt="Developer Preview">
</p>

<p align="center">
  <a href="#why-webfa">Why</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#what-it-can-do">What it can do</a> ·
  <a href="README.md">中文</a>
</p>

---

WebFA runs on your computer. Your agent uses it to work with real websites: open a page, see what is available, take an action, and check what changed.

The agent decides. WebFA does the work.

```text
open → observe → act → observe again
```

This is a **Developer Preview**. The interface may still change.

## Why WebFA?

Agents can already write code, edit documents, and make calls. Asking them to use the web like a person usually goes one of two ways — both miss:

| Common approach | What you actually get |
| --- | --- |
| Wrap a browser with automation | The agent hunts for button positions and page structure. One redesign and it breaks |
| Wrap each site in a custom API | That is not using the internet. That is calling the few sites you wired up |
| Drive a browser built for humans | The agent orbits a human UI instead of having its own way onto the web |

So it is not a regular browser with automation bolted on, not a pile of per-site APIs, and not a desktop browser with an AI built in.

It opens real pages and tells the agent what is there and what can be done. Your agent decides. WebFA goes and does it.

## What it can do

- Open real websites in a local browser
- See buttons, fields, and links, and whether they can be used right now
- Fill in, choose, submit, and open
- List and switch tabs
- Keep different accounts apart
- Leave passwords, CAPTCHAs, and two-factor checks to a person

The agent has five actions: open a page, observe, act, list tabs, switch tabs.

## Quick Start

You need Python 3.12+ and Chrome or Edge installed locally.

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
webfa doctor
```

Generate a config for your agent:

```powershell
webfa mcp-config --agent-id <your-agent-name>
```

After the agent connects, the local service starts on its own. Give each agent its own name. Different accounts can be used at the same time.

[OpenCode](docs/agent-integrations/opencode.md) · [Kimi Code](docs/agent-integrations/kimi-code.md) · [Claude Code](docs/agent-integrations/claude-code.md) · [Codex](docs/agent-integrations/codex.md)

## Sign in

Do not let the agent type passwords, CAPTCHA codes, or two-factor codes. Prepare login yourself:

```powershell
webfa login github
webfa login --url https://example.com/login
```

If a site needs a person to confirm, stop, finish that step yourself, then let the agent look at the page again.

## What the agent does not get

By default the agent does not receive login cookies, local storage, tokens, passwords, or the full page HTML. It also cannot drive the page through selectors or the browser debug channel.

## What it will not do

- It will not bypass CAPTCHAs, bot checks, or site risk controls
- One account can only be written to from one place at a time
- Work in progress does not continue after you quit

## Development

```powershell
python -m pytest -q
```

See `.env.example` for environment variables. Runtime data defaults to `%APPDATA%\WebFA`.

The [roadmap](docs/browser-runtime-roadmap.md) is the place for what comes next.

## License

MIT. See [`LICENSE`](LICENSE).
