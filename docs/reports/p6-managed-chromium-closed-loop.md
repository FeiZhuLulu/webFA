# P6 Managed Chromium BrowserHost Closed Loop

P6 validates that WebFA can keep Chromium/Blink/V8 as the web engine while
moving away from Playwright as the only control layer and away from Chrome UI as
the product shape.

## Scope

P6 adds an experimental managed Chromium path behind the existing WebFA browser
interfaces:

```text
REST: /v1/browser/open, /observe, /act, /tabs
MCP:  webfa.open_url, webfa.observe, webfa.act, webfa.get_tabs, webfa.switch_tab
```

Default behavior remains unchanged. Playwright is still the default stable
driver. The experimental path is enabled explicitly:

```powershell
$env:WEBFA_BROWSER_DRIVER = "managed-chromium"
$env:WEBFA_BROWSER_HEADLESS = "1"
```

## Architecture

```text
BrowserRuntime
  -> BrowserDriver
    -> BrowserHost
      -> ManagedChromiumHost
```

- `BrowserDriver` preserves WebFA semantics: `open`, `observe_raw`, `act`,
  `tabs`, `close`.
- `BrowserHost` is the low-level webpage host contract.
- `ManagedChromiumHost` launches a WebFA-managed Chromium process and uses an
  internal CDP channel. CDP is not exposed to REST, MCP, or agents.
- `OBSERVE_PROBE` is shared by Playwright and managed Chromium paths.

## Current Capability

Managed Chromium currently supports:

- `open_url`
- `observe_raw`
- `tabs`
- `close`
- `act`: `type`, `click`, `clear`, `focus`, `press`, `wait`, `wait_for_text`

It does not yet support:

- `switch_tab`
- `select`, `check`, `uncheck`, target scroll
- iframe/shadow DOM action routing
- downloads/uploads
- becoming the default driver

## Product Boundary

P6 does not replace Chromium. WebFA still needs a mature web engine to run the
modern web. P6 replaces the assumption that WebFA must be controlled through
Playwright and presented as a Chrome-like human browser window.

Desktop UI and Electron WebContents remain optional future hosts or visualizer
surfaces. Runtime Core does not depend on Electron.

## Validation

P6 acceptance requires:

- default Playwright path does not regress;
- managed Chromium path completes local fixture `open -> observe -> type ->
  click -> observe`;
- default MCP tools remain exactly the five browser tools;
- REST/MCP do not expose raw CDP, raw Playwright, selectors, XPath, locators, or
  evaluate;
- BrowserState does not expose cookies, storage, full DOM, or full HTML.

