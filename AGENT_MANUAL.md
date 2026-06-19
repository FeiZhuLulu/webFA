# WebFA Agent Manual

This manual is for agents that use WebFA through MCP.

WebFA is an agent browser runtime, not a human browser automation wrapper. Use it to access web pages in ways that are natural for an agent.

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

## URL-First Navigation

Do not blindly copy human browser behavior. Humans click through menus because URLs and page state are awkward for them. Agents can read and modify structured text.

Prefer this order:

```text
1. If the target page can be expressed as a URL, use webfa.open_url directly.
2. If the page has a normal form, use observe -> type -> press Enter.
3. If Enter does not work, use observe -> click the stable submit button.
4. Avoid clicking dynamic suggestions unless they appear as interactive_elements.
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
