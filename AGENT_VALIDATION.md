# WebFA P4.5 Agent Validation Harness

P4.5 validates that WebFA can be used by an external agent as an agent-native browser runtime.

Agents should read `AGENT_MANUAL.md` before validation. It describes WebFA-specific browser strategy, including when direct URL navigation is better than human-style clicking.

The target loop is:

```text
external agent / MCP client
  -> webfa.open_url
  -> webfa.observe
  -> webfa.act
  -> webfa.observe
```

This phase does not add site-specific tools, task planning, LLM summaries, multi-session support, or GitHub/Hugging Face business actions.

## Required Runtime Setup

Install dependencies and Chromium once:

```powershell
pip install -e ".[dev]"
python -m playwright install chromium
npm install
```

Start the desktop stack:

```powershell
npm run dev
```

Or start only the Runtime:

```powershell
python -m uvicorn apps.runtime.main:app --host 127.0.0.1 --port 8787
```

The MCP server is started by the MCP client with:

```powershell
python -m apps.runtime.mcp.server
```

Use this environment variable when launching MCP from an external agent:

```powershell
$env:WEBFA_RUNTIME_URL="http://127.0.0.1:8787"
```

## Expected MCP Tools

By default the agent should only see:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

The agent should not see:

```text
webfa.plan
webfa.preview
webfa.execute
webfa.get_proof
github.*
hf.*
raw_playwright
raw_cdp
selector/xpath/locator/evaluate tools
```

Legacy transaction tools only appear if explicitly enabled:

```powershell
$env:WEBFA_ENABLE_LEGACY_TRANSACTION="1"
```

## Level 0: REST Local Page

Goal: prove Runtime browser primitives work without MCP.

Use:

```text
tests/fixtures/agent_validation_page.html
```

Expected flow:

```text
POST /v1/browser/open
GET  /v1/browser/observe
POST /v1/browser/act  { action: "type", target: "el_*", text: "Fei" }
POST /v1/browser/act  { action: "click", target: "el_*" }
GET  /v1/browser/observe
```

Expected result:

```text
Hello Fei
```

Automated test:

```powershell
pytest tests/integration/test_browser_api.py -q
```

## Level 1: MCP Stdio Local Page

Goal: prove the real agent entrypoint works.

Automated test:

```powershell
pytest tests/integration/test_mcp_stdio_browser.py -q
```

This starts a real Runtime server, starts `python -m apps.runtime.mcp.server` over stdio, lists MCP tools, and runs:

```text
webfa.open_url
webfa.observe
webfa.act(type)
webfa.act(click)
webfa.observe
```

## Level 2: External Agent Local Page

Goal: prove an LLM agent can read `BrowserState` and choose element actions.

Recommended prompt:

```text
Use WebFA as your browser. Open the local validation page at <file-url>.
Find the name input, type "Fei", click Submit, then observe the page and report the result text.
Use only webfa.open_url, webfa.observe, and webfa.act.
Do not use selectors, raw Playwright, CDP, GitHub tools, or site-specific APIs.
```

Expected tool sequence:

```text
webfa.open_url
webfa.observe
webfa.act(type)
webfa.act(click)
webfa.observe
```

Pass condition:

```text
The agent reports "Hello Fei" from the page state.
```

## Level 3: Simple Real Website

Goal: test WebFA against low-risk public pages.

Use simple pages first:

```text
documentation search
public GitHub pages
public Hugging Face search
basic form demos
```

Do not log in, submit sensitive data, create repositories, post messages, or perform account actions at this level.

## Level 4: Persistent Profile

Goal: verify WebFA can reuse user login state.

Manual flow:

```text
1. Start WebFA in headful mode.
2. Open a site such as github.com.
3. User logs in manually in the Chromium window.
4. Stop and restart Runtime.
5. Open the same site through WebFA.
6. Observe whether the page state indicates the user is still logged in.
```

Pass condition:

```text
Login survives Runtime restart through WEBFA_HOME/browser/profile-default.
```

Do not expose cookies, localStorage, sessionStorage, IndexedDB, or token values to the agent.

## Level 5: Real Task Preflight

Goal: validate realistic pages without committing irreversible actions.

Example:

```text
Open GitHub new repository page.
Fill repository name and description.
Select public/private.
Stop before clicking final Create, or require explicit human confirmation.
```

This level validates WebFA as a browser runtime. It still should not add `github.create_repo`, `weibo.reply_dm`, or other site-specific tools.

## Current Acceptance Gate

P4.5 is acceptable when:

```text
pytest -q
npm run typecheck:renderer
npm run typecheck:electron
```

all pass, and the MCP stdio test proves:

```text
webfa.open_url -> webfa.observe -> webfa.act -> webfa.observe
```

against `tests/fixtures/agent_validation_page.html`.
