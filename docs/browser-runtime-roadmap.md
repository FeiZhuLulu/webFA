# Browser Runtime Roadmap

WebFA is not Chrome, and Playwright is not the product boundary.

Current P4/P4.5 implementation uses Playwright with a headful Chromium persistent profile because it is the shortest way to validate the agent browser loop against real websites.

## Runtime Layers

WebFA should keep these layers separate:

```text
Agent Interface
  MCP / REST / Console calls: open_url, observe, act, tabs

WebFA Browser Runtime
  sessions, page_state, element ids, action model, safety contracts

Browser Driver
  current: PlaywrightBrowserDriver
  future: CDP / Electron WebContents / other native driver

Browser Engine
  runs real HTML, CSS, JavaScript, storage, cookies, and web APIs
```

## Roadmap

```text
P4/P4.5
  Playwright + headful Chromium for validation.
  Chrome-like UI is only a debug surface.

P5
  Add a BrowserDriver boundary.
  Keep public WebFA APIs unchanged.
  Confine Playwright calls to one driver implementation.

P6
  Move toward headless browser runtime plus WebFA Visualizer.
  The visualizer shows page state, screenshots, highlighted elements, agent actions, and takeover controls.

Long term
  Replace Playwright where useful.
  Do not clone Chrome UI.
  Keep WebFA centered on agent-readable state and object-level web actions.
```

## Constraints

WebFA should not expose raw Playwright, raw CDP, selectors, XPath, or site-specific API wrappers as the main agent interface.

The browser engine may remain Chromium/Blink/V8 or another real web engine. The goal is to remove Chrome product shape and Playwright automation assumptions, not to reimplement the modern web engine from scratch.
