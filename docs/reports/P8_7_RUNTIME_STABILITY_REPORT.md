# P8.7 Runtime Stability and Post-Login Usability Report

## Goal

P8.7 addresses issues found in the DeepSeek, Xiaohongshu, and QQ Mail login
validation run.

## Changes

- CDP client reconnects once after a receive failure such as a keepalive timeout.
- Auth detection is less text-triggered, reducing false positives on logged-in
  pages that contain words like password or verification code.
- `webfa.act` accepts `double_click` for row-style legacy UIs.
- Observe probe treats generic rows/list items/options/table rows as
  addressable elements and binds their ids into content blocks.
- Managed Chromium typing uses the native input/textarea value setter before
  dispatching input/change events, improving React-style controlled inputs.

## Boundaries

- No anti-detect or platform risk bypass.
- No site-specific parser for Xiaohongshu, QQ Mail, or DeepSeek.
- No custom WebFA Visualizer yet; visible auth takeover still uses the current
  managed Chromium window.

## Automated Verification

```text
python -m pytest tests/unit/test_managed_chromium_cdp.py tests/unit/test_schemas.py tests/unit/test_agent_view.py tests/integration/test_managed_chromium_driver.py -q
  -> 38 passed
```

```text
python -m pytest -q
  -> 187 passed, 2 warnings

npm run typecheck:renderer
  -> passed

npm run typecheck:electron
  -> passed

python -m build
  -> built sdist and wheel
```
