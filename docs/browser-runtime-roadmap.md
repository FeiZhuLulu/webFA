# Browser Runtime Roadmap

WebFA is not Chrome, and Playwright is not the product boundary.

Current P4/P4.5 implementation uses Playwright with a headful Chromium persistent profile because it is the shortest way to validate the agent browser loop against real websites.

## Runtime Layers

WebFA should keep these layers separate:

```text
Agent Interface
  MCP / REST / Console calls: open_url, observe, act, tabs

WebFA Browser Runtime
  sessions, page_state, element ids, agent-native web operations, safety contracts

Browser Driver
  current stable: PlaywrightBrowserDriver
  current experiment: ManagedChromiumHost through HostBrowserDriver
  future: other BrowserHost implementations

Browser Engine
  runs real HTML, CSS, JavaScript, storage, cookies, and web APIs
```

Driver work must not become a Playwright clone. WebFA uses browser engines and
host protocols as implementation details, but its product surface should move
toward agent-native web operations: URL navigation, readable page objects,
forms, links, controls, lists, and safe object-level actions.

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
  Managed Chromium BrowserHost Closed Loop.
  Keep Chromium/Blink/V8 as the web engine, but prove WebFA can run without
  Playwright as the control layer and without treating Chrome UI as the product
  surface.
  Add a BrowserHost layer under BrowserDriver. The first experimental host is
  ManagedChromiumHost, which launches a WebFA-managed Chromium process and uses
  an internal CDP channel for navigate/evaluate/actions.
  Keep PlaywrightBrowserDriver as the stable default. Enable the experiment with
  WEBFA_BROWSER_DRIVER=managed-chromium.
  Status: done — host contract, shared observe probe, managed Chromium
  open/observe/tabs/close, and minimal type/click/press/clear/wait closed loop.

P7
  Agent-Native Web Operations.
  Move beyond low-level click/type as the primary abstraction without copying
  Playwright. Improve BrowserState and action semantics around generic web
  objects: URL affordances, forms, links, controls, lists, and content blocks.
  Candidate operations include fill_form, submit_form, follow_link,
  activate_control, choose_option, read_list, and inspect_block. These are
  generic webpage operations, not site-specific APIs and not LLM suggestions.
  Existing click/type/press remain as fallback primitives.

P8
  Plugin-first Packaging / Agent Entry Package.
  Make WebFA easy for external agents to install and use through MCP/local
  plugin/CLI entry points. Desktop remains optional.

P9
  WebFA Visualizer.
  Show WebFA's own runtime state: URL, title, BrowserState, content_blocks, elements, screenshots, highlights, action log, and takeover controls.
  Do not clone Chrome address bar, tabs, or general human-browser UI.

P10
  Element Registry v2.
  Reduce dependence on data-webfa-id injection with role/name/text/tag/dom_path/bbox/nearby_text hints.

P11
  Multi Session / Multi Profile.
  Expose session_id/profile_id only after default session is stable.

P12
  Real Task Safety Layer.
  Add human confirmation before final high-risk writes such as send, create, delete, purchase, publish, or settings changes.

Long term
  Do not turn WebFA into a Playwright replacement.
  Keep mature web engines such as Chromium/Blink/V8 where useful.
  Remove Playwright and Chrome UI assumptions from the product boundary.
  Keep WebFA centered on agent-readable state, URL-native navigation, and
  generic web-object operations.
```

## Constraints

WebFA should not expose raw Playwright, raw CDP, selectors, XPath, or site-specific API wrappers as the main agent interface.

The browser engine may remain Chromium/Blink/V8 or another real web engine. The goal is to remove Chrome product shape and Playwright automation assumptions, not to reimplement the modern web engine from scratch.
