# WebFA

**Language**: [中文](https://github.com/FeiZhuLulu/webFA/blob/main/README.md) | English

WebFA is a local **agent-native browser runtime**: it gives agents a native interface to the web, so they can browse, act on, and verify real websites as first-class internet users.

```text
agent -> webfa.open_url -> webfa.observe -> webfa.act -> webfa.observe
```

The agent makes the decisions; WebFA does the work: opening real pages, keeping website login identities in isolated Profiles, returning structured page state, and executing semantic web-object operations. The human UI (Control Center / Session Monitor) is a monitoring, approval, and takeover surface — not the product itself.

WebFA is not: a traditional browser with automation attached, a collection of site-specific API wrappers, or a desktop app with a built-in agent.

Status: **Developer Preview**. APIs and behavior may change.

## How It Works

Agents work with **web objects**, not the DOM:

```text
real web page -> WebObjectCompiler -> WebState (WebObjects / Capabilities) -> Agent semantic operations
```

`webfa.observe` returns a structured `WebState`: operable web objects, their state and relations, available operations, document revisions, and change sets. `webfa.act` accepts only the semantic operations declared by objects (e.g. `open`, `set_value`, `submit`, `choose`). DOM, selectors, coordinates, mouse/keyboard events, and CDP are internal Runtime details and never enter the public protocol. Full design: `docs/P10_WEBFA_OBJECT_MODEL_DESIGN.md`.

## Quick Start

Requirements: Python 3.12+, with Chrome or Edge installed locally.

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
webfa doctor        # local self-test
```

Generate an MCP config for your agent:

```powershell
webfa mcp-config --agent-id <your-agent-name>
```

Once the agent connects over MCP stdio, `webfa-mcp` automatically reuses or starts the local Runtime (default `http://127.0.0.1:8787`) — no manual process management. Each agent should use a distinct `WEBFA_AGENT_ID`; different Profiles can be used concurrently by different agents.

Integration guides: [opencode](docs/agent-integrations/opencode.md) · [Kimi Code](docs/agent-integrations/kimi-code.md) · [Claude Code](docs/agent-integrations/claude-code.md) · [Codex](docs/agent-integrations/codex.md)

## Login & Human Takeover

Agents should not type passwords, verification codes, or 2FA codes. When a page enters a login, QR-code, or authorization flow, the user acquires a time-bounded human-control lease in the Session Monitor and operates the very same page the agent is using, then hands control back. The agent calls `observe` again before continuing.

You can also preload login state via CLI:

```powershell
webfa login github
webfa login --url https://example.com/login
```

## Capabilities

- Exactly 5 MCP tools: `open_url`, `observe`, `act`, `get_tabs`, `switch_tab`.
- Managed Chromium runtime with an isolated browser identity directory per Profile; no Playwright dependency.
- Concurrent multi-Profile sessions; at most one writable Session per Profile at a time.
- Profile Bootstrap: human login, cookie import, and export/restore of encrypted `.webfa-profile` identity bundles.
- High-risk operations are constrained by SafetyContext, Runtime evidence, and safety receipts; exact-scope, single-use-by-default human Step-up is required only when an operation exceeds the configured autonomy boundary.
- Optional Runtime Manager desktop app: monitor Agents/Sessions, approve, take over, generate MCP configs.

## Safety Boundary

Never exposed to agents by default: cookies, localStorage/sessionStorage values, tokens and authorization headers, password values, full DOM/HTML, selector/XPath/evaluate escape hatches, raw CDP. See `docs/P11_AGENT_SAFETY_CONTRACT_DESIGN.md`.

## Current Limits

- One writable Session per Profile at a time (different Profiles run concurrently).
- No bypassing of anti-bot, CAPTCHA, risk-control, or platform security systems.
- `open_url` and link opening have navigation semantics; if a site abuses GET navigation to perform an external write, Runtime cannot infer that business side effect from protocol semantics alone.
- Active Sessions and task execution state do not survive a Runtime restart (durable resume is the deferred P13 phase).
- The Runtime Manager is a monitoring and takeover surface, not a full desktop browser, and contains no built-in agent.

## Development

```powershell
python -m pytest -q          # Python tests
npm install                  # optional: human control surface (Renderer + Electron)
npm run dev                  # start Visualizer, default http://127.0.0.1:8788
npm run typecheck:renderer
npm run typecheck:electron
```

Common environment variables: see `.env.example`. Source runs store data in `%APPDATA%\WebFA` by default.

## Documentation

- Roadmap: `docs/browser-runtime-roadmap.md`
- Object Model design: `docs/P10_WEBFA_OBJECT_MODEL_DESIGN.md`
- Safety Contract design: `docs/P11_AGENT_SAFETY_CONTRACT_DESIGN.md`
- Multi-Session / Multi-Profile design: `docs/P12_MULTI_SESSION_MULTI_PROFILE_DESIGN.md`
- Desktop distribution architecture: `docs/DESKTOP_DISTRIBUTION_ARCHITECTURE.md`
- Open-source Runtime readiness: `docs/OPEN_SOURCE_READINESS.md`
- Candidate release gates: `RELEASE_CHECKLIST.md`
- Current phase and evidence matrix: `docs/reports/PRE_P13_COMPLETION_EVIDENCE_MATRIX_21.md`
- Historical reports guide: `docs/reports/README.md` (old reports are point-in-time engineering evidence only)

## License

MIT. See `LICENSE`.
