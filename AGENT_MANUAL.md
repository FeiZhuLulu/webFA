# WebFA Agent Manual

This manual is for agents that use WebFA through MCP.

WebFA is an agent browser runtime, not a human browser automation wrapper. Use it to access web pages in ways that are natural for an agent.

The default runtime path uses WebFA-managed Chromium. Treat the browser engine
as an implementation detail: agents should rely on WebFA's page state and
object actions, not Chrome UI, DevTools, CDP, or Playwright concepts.

## Core Loop

Use this loop by default:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.observe
```

Only use these public tools:

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

Do not use raw selectors, XPath, Playwright, CDP, browser devtools, site APIs, or site-specific wrappers.

## Reading Page Content

After `webfa.observe`, the state has both `visible_text` and `content_blocks`.

`visible_text` is one flat string for the whole page. `content_blocks` is a list of smaller, more stable text blocks, each with the `element_ids` of the interactive elements inside it:

```text
{ "id": "block_1", "type": "heading", "text": "alpha/webfa-one", "element_ids": ["el_7"] }
```

For real listing pages (search results, dashboards, feeds), read `content_blocks` first, then fall back to `visible_text`. Pick the `element_id` you need from a block's `element_ids` instead of re-scanning the whole page.

## Object Operations

Prefer object-level actions when WebFA exposes the needed page object:

```text
fill_form(form_id, fields)
submit_form(form_id)
follow_link(element_id)
activate_control(element_id)
choose_option(element_id, value)
read_list(block_id)
inspect_block(block_id)
```

Use them through `webfa.act`:

```json
{ "action": "fill_form", "target": "form_1", "payload": { "fields": { "name": "Fei" } } }
```

```json
{ "action": "submit_form", "target": "form_1" }
```

Use `click`, `type`, and `press` as fallback primitives when the page object is not clear enough.
Use `double_click` only when the page clearly requires row-style double-click
activation, such as legacy mail or file-list UIs.

## Auth Takeover

WebFA may mark a page as requiring human auth takeover when it looks like a
login, QR-code, verification-code, 2FA, or authorization surface.

When `state.auth.surface_detected` is true and
`state.auth.takeover == "auth_surface"`, a human is expected to finish the
credential step in the WebFA UI takeover area. Do not ask the user for
passwords, verification codes, cookies, storage values, or tokens in chat. Do
not try to fill password fields yourself.

After the user finishes signing in or approving access, continue with:

```text
webfa.observe
```

If the page is still a login or verification page, report the current state and
wait for the user to finish. If the page changed to the authenticated app, keep
working from the new BrowserState.

## Runtime Safety (Developer Preview)

P9.2 adds structured errors, URL metadata, dialog handling, and frame metadata.
This is **developer-preview hardening**, not production-grade network isolation.
The default driver is WebFA-managed Chromium. `WEBFA_BROWSER_DRIVER=playwright`
is a legacy fallback for basic `open_url` / `observe` / `act` only; do not
expect dialog, iframe, or URL-policy parity on Playwright.

## URL Safety

`state.security` reports URL class, policy, and risk flags. When navigation is
blocked, WebFA returns a structured error such as `private_url_blocked` or
`sensitive_url_blocked` with a `recover_hint`. Do not bypass policy by guessing
alternate hosts or embedding credentials in query strings.

Policy is **lightweight**: it classifies the URL string (hostname, scheme,
sensitive query keys). It does not resolve DNS or normalize exotic IP literal
forms. Hostnames that resolve to loopback or private networks may still be
reachable under `block` until a later hardening phase.

## JavaScript Dialogs

When a page opens `alert`, `confirm`, or `prompt`, WebFA exposes it in
`state.dialogs` and blocks ordinary `webfa.act` calls with `dialog_required`.
Resolve the dialog through `webfa.act`:

```json
{ "action": "dismiss_dialog", "target": "dialog_1" }
```

```json
{ "action": "accept_dialog", "target": "dialog_1" }
```

Call `webfa.observe` after handling the dialog before continuing with page
actions.

Dialog support is an **MVP on managed Chromium**:

- `alert` and `confirm` are supported.
- `prompt` is detected, but `accept_dialog` cannot supply custom prompt text yet.
- Very slow or delayed dialogs may occasionally be missed before the next act.

## Frames

`state.frames` lists frame metadata. Same-origin iframe elements may include a
`frame_id`. Cross-origin iframe contents are not exposed; do not try to act on
hidden cross-origin elements. Only top-level iframes are scanned; nested iframes
are not supported in this phase.

## URL-First Navigation

Do not blindly copy human browser behavior. Humans click through menus because URLs and page state are awkward for them. Agents can read and modify structured text.

Consider these routes and choose based on the task and current page state:

```text
URL navigation when the target is encoded in the URL
form object operations when WebFA exposes a clear form
type/press/click primitives when object operations are not enough
fresh observe after dynamic page changes
```

Good URL-first candidates:

```text
search pages
filters and sort options
pagination
documentation anchors
known user, repository, issue, or pull request paths
```

Avoid guessed URLs for:

```text
creating resources
deleting resources
payments
login or authorization
sending messages
POST/CSRF form submissions
```

## Example: GitHub Repository Search

Task:

```text
Search GitHub repositories for "webfa".
```

Human-style route:

```text
open github.com
click search
type webfa
press Enter
observe results
```

Agent-native route:

```text
webfa.open_url("https://github.com/search?q=webfa&type=repositories")
webfa.observe()
```

The second route is valid because the search target is fully represented by the URL. It is not a GitHub API call and it is not a site-specific wrapper; it is normal web navigation.

## Handling Dynamic Pages

Modern web pages can change their DOM after every input. Element IDs may become stale after navigation or major UI changes.

Use this pattern:

```text
1. observe
2. act on an element_id
3. read the returned state
4. if the target changed or disappeared, observe again and pick a fresh element_id
```

For search boxes and comboboxes, prefer:

```text
webfa.act({ "action": "type", "target": "el_*", "text": "query" })
webfa.act({ "action": "press", "target": "el_*", "key": "Enter" })
```

Avoid dynamic autocomplete suggestions unless WebFA exposes them in `interactive_elements`.

## Safety

Do not perform irreversible account actions unless the user explicitly asked for them and approval is clear in the current task.

Examples that should stop before final submit:

```text
create repository
send message
delete file
purchase item
change settings
publish post
```

For these tasks, fill or inspect the page, then stop before the final write action.
