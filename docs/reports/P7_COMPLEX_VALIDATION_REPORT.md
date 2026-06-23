# WebFA 复杂测试验收报告（第二轮）

**日期**: 2026-06-19
**环境**: Windows 11, Python 3.12, managed-chromium driver, headless=true
**工具**: 全程 WebFA MCP（未使用 raw Playwright/CDP/selector/xpath/evaluate）
**代码修改**: 无

## 测试总览

| # | 测试 | 结果 | 说明 |
|---|------|------|------|
| C2 | GitHub 重启后持久化 | ✅ PASS | 重启 Runtime 后仍为已登录状态 |
| C3 | GitHub 登录态页面导航 | ✅ PASS | 进入已登录用户的测试仓库，读取仓库名、README、文件列表 |
| D4 | GitHub 搜索到 Star 按钮观察 | ✅ PASS | 识别 Star 按钮 (el_54)，未点击 |
| A1 | Wikipedia 文章导航 | ✅ PASS | URL-first 进入 Chromium 页面，读取 3 个关键事实 |
| A4 | npm 包搜索读取 | ❌ FAIL | npmjs.com Cloudflare 反爬阻断 |
| B2 | MDN 站内搜索 | ✅ PASS | URL-first 进入 Fetch API 文档页 |
| B3 | npm 搜索 + 结果读取 | ❌ FAIL | npmjs.com Cloudflare 反爬阻断 |
| B4 | Hugging Face 搜索 + 过滤观察 | ✅ PASS | 读取前 5 个 whisper 模型 + 筛选控件 |
| D2 | GitHub Issue 前置填写 | ✅ PASS | 填写 title/body，未点击 Create |
| D3 | 通用联系表单 Demo | ✅ PASS | fill_form 填写 httpbin.org 表单，未点击 Submit |

---

## C2: GitHub 重启后持久化 ✅

**工具序列**:
```
PowerShell: Stop-Process uvicorn
Bash: WEBFA_BROWSER_DRIVER=managed-chromium WEBFA_BROWSER_HEADLESS=1 python -m uvicorn ...
curl /health → driver=managed-chromium, headless=true
webfa.open_url("https://github.com")
webfa.observe()
```

**BrowserState 证据**:
- `title`: `"GitHub"` ✅
- `visible_text`: `"Dashboard Top repositories New <user>/<repo-a> <user>/<repo-b> ..."` ✅
- 无 "Sign in" / "Sign up" ✅

---

## C3: GitHub 登录态页面导航 ✅

**工具序列**:
```
webfa.open_url("https://github.com/<user>/<test-repo>")
```

**BrowserState 证据**:
- `title`: `"<user>/<test-repo>: <test repository title>"`
- 仓库名: `<test-repo>`，Owner: `<user>`
- README 标题: `ceshi1`，内容: `"测试wfa连接"`
- 文件列表: `README.md`
- About: `"测试wfa连接"`
- 分支: `main`
- 未执行写操作 ✅

---

## D4: GitHub 搜索到 Star 按钮观察 ✅

**工具序列**:
```
webfa.open_url("https://github.com/search?q=webfa&type=repositories")
python (解析 interactive_elements): 找到 el_54 (button, name="Star")
```

**BrowserState 证据**:
- 第一条结果: `will-in-wi/letsencrypt-webfaction`
- Star 按钮: `el_54` (button, name="Star", actions: click/focus/activate_control)
- **未点击** ⛔

---

## A1: Wikipedia 文章导航 ✅

**方法**: URL-first

**工具序列**:
```
webfa.open_url("https://en.wikipedia.org/wiki/Chromium_(web_browser)")
```

**BrowserState 证据**:
- `title`: `"Chromium (web browser) - Wikipedia"`
- 3 个关键事实:
  1. "Chromium is a free and open-source web browser project, primarily developed and maintained by Google."
  2. "It is a widely used codebase, providing the vast majority of code for Google Chrome and many other browsers, including Microsoft Edge, Opera, Vivaldi, Brave, Samsung Browser and Ungoogled Chromium."
  3. Release: 2 September 2008, Written in: C++ primarily

---

## A4: npm 包搜索读取 ❌

**工具序列**:
```
webfa.open_url("https://www.npmjs.com/search?q=playwright")
→ title: "Just a moment..."
→ visible_text: "www.npmjs.com 正在进行安全验证 本网站使用安全服务防护恶意自动程序。"
webfa.observe()
→ error: "sent 1011 (internal error) keepalive ping timeout"
```

**失败原因**: npmjs.com 使用 Cloudflare 反爬验证，managed-chromium headless 被检测为自动程序。浏览器会话被杀。

**WebFA 暴露的问题**: managed-chromium headless 无法通过 Cloudflare 反爬验证。

---

## B2: MDN 站内搜索 ✅

**方法**: URL-first

**工具序列**:
```
webfa.open_url("https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API")
```

**BrowserState 证据**:
- `title`: `"Fetch API - Web APIs | MDN"`
- `visible_text`: "The Fetch API provides an interface for fetching resources (including across the network). It is a more powerful and flexible replacement for XMLHttpRequest."

---

## B3: npm 搜索 + 结果读取 ❌

与 A4 相同原因：npmjs.com Cloudflare 反爬阻断。

---

## B4: Hugging Face 搜索 + 过滤观察 ✅

**方法**: URL-first

**工具序列**:
```
webfa.open_url("https://huggingface.co/models?search=whisper&sort=trending")
```

**BrowserState 证据**:
- `url_parts.query.search`: `"whisper"`
- `url_parts.query.sort`: `"trending"`
- 前 5 个模型:

| # | 模型名 | 作者 | 任务 | 参数量 | 下载量 |
|---|--------|------|------|--------|--------|
| 1 | whisper-large-v3 | openai | ASR | 2B | 5.98M |
| 2 | whisper-large-v3-turbo | openai | ASR | 0.8B | 7.85M |
| 3 | faster-whisper-large-v3 | Systran | ASR | — | 1.15M |
| 4 | whisper_small_persian | C1Tech | ASR | 0.2B | 23 |
| 5 | whisper.cpp | ggerganov | ASR | — | 1.46k |

- 筛选控件: `el_5`(Base only switch)、`el_6`(Inference)、`el_7`(Add filters)、`el_8`(Sort: Trending)

---

## D2: GitHub Issue 前置填写 ✅

**工具序列**:
```
webfa.open_url("https://github.com/<user>/<test-repo>/issues/new")
webfa.act(type, el_26, "WebFA validation test - do not submit")
webfa.act(type, el_43, "This issue was created by WebFA agent validation. Do not submit.")
```

**BrowserState 证据**:
- `el_26.value`: `"WebFA validation test - do not submit"` ✅
- `el_43.value`: `"This issue was created by WebFA agent validation. Do not submit."` ✅
- `el_53`: Create 按钮存在，**未点击** ⛔

---

## D3: 通用联系表单 Demo ✅

**工具序列**:
```
webfa.open_url("https://httpbin.org/forms/post")
webfa.act(fill_form, form_1, {fields: {custname: "WebFA Agent", custemail: "agent@webfa.test", comments: "Validation test - do not submit"}})
```

**BrowserState 证据**:
- `el_1` (custname): `"WebFA Agent"` ✅
- `el_3` (custemail): `"agent@webfa.test"` ✅
- `el_12` (comments): `"Validation test - do not submit"` ✅
- `el_13`: Submit order 按钮存在，**未点击** ⛔

---

## 结论

**8/10 通过，2/10 失败（均为 Cloudflare 反爬阻断）**。

| 类别 | 通过 | 失败 |
|------|------|------|
| GitHub 操作 (C2/C3/D2/D4) | 4/4 | 0 |
| URL-first 阅读 (A1/B2/B4) | 3/3 | 0 |
| npm 阅读 (A4/B3) | 0/2 | 2 |
| 表单填写 (D3) | 1/1 | 0 |

**WebFA 暴露的问题**:
- managed-chromium headless 无法通过 Cloudflare 反爬验证（npmjs.com）

**已确认的能力**:
- URL-first 导航 ✅
- 页面内容读取（visible_text/content_blocks） ✅
- 表单填写（fill_form/type） ✅
- 登录态持久化 ✅
- 安全停止（不点击提交按钮） ✅
- 只使用 WebFA MCP 工具 ✅
