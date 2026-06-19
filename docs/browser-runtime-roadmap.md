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
  Browser Runtime Core.
  Keep public WebFA APIs unchanged.
  Confine Playwright calls to PlaywrightBrowserDriver.
  Generate BrowserState through AgentViewBuilder.
  Track current-page element ids through ElementRegistry.
  Keep one default BrowserSession/Profile.

P5.5
  Content Blocks MVP.
  Goal: BrowserState.content_blocks stops being empty; agents get a more stable
  reading structure than one flat visible_text blob.
  Route: RawPageSnapshot -> raw content block candidates -> AgentViewBuilder ->
  BrowserState.content_blocks, each block carrying {id, type, text, element_ids}.
  Collect generic DOM blocks (h1/h2/h3, p, li, article, form, nav, role=listitem),
  cap text length and count, bind nearby data-webfa-id element ids.
  Public MCP/REST tools are unchanged. No HTML, no DOM path, no site rules,
  no LLM summaries, no suggested actions, no Visualizer, no new MCP tools.
  Status: done — BrowserContentBlock schema, AgentViewBuilder mapping, observe
  script collection, search-results integration test, security contract.

P6
  Alternative Driver Experiment.
  Prove WebFA Runtime Core can run on a second driver path before building product UI on top.
  Try a minimal CDP or Electron WebContents driver for open_url and observe_raw.
  Keep PlaywrightBrowserDriver as the stable default until the experiment passes.

P7
  Headless / Non-Chrome-UI Runtime.
  Move the default runtime shape away from a visible Chromium browser window.
  Keep a real browser engine, but stop presenting Chrome UI as WebFA's product surface.

P8
  WebFA Visualizer.
  Show WebFA's own runtime state: URL, title, BrowserState, content_blocks, elements, screenshots, highlights, action log, and takeover controls.
  Do not clone Chrome address bar, tabs, or general human-browser UI.

P9
  Element Registry v2.
  Reduce dependence on data-webfa-id injection with role/name/text/tag/dom_path/bbox/nearby_text hints.

P10
  Multi Session / Multi Profile.
  Expose session_id/profile_id only after default session is stable.

P11
  Real Task Safety Layer.
  Add human confirmation before final high-risk writes such as send, create, delete, purchase, publish, or settings changes.

Long term
  Replace Playwright where useful.
  Do not clone Chrome UI.
  Keep WebFA centered on agent-readable state and object-level web actions.
```

## Constraints

WebFA should not expose raw Playwright, raw CDP, selectors, XPath, or site-specific API wrappers as the main agent interface.

The browser engine may remain Chromium/Blink/V8 or another real web engine. The goal is to remove Chrome product shape and Playwright automation assumptions, not to reimplement the modern web engine from scratch.
