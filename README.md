<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/webfa-mark-light.svg">
    <img src="docs/assets/webfa-mark.svg" width="42" height="42" valign="middle" alt="">
  </picture>
  WebFA
</h1>

<p align="center"><strong>给你的 AI Agent 真正上网的能力</strong></p>
<p align="center">在你自己的电脑上打开真实网页，看清能做什么，再去操作并核对结果</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="MIT License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.12+-green.svg?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12+"></a>
  <img src="https://img.shields.io/badge/Status-Developer%20Preview-yellow.svg?style=for-the-badge" alt="Developer Preview">
</p>

<p align="center">
  <a href="#为什么需要-webfa">为什么需要</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="#它能做什么">它能做什么</a> ·
  <a href="README.en.md">English</a>
</p>

---

WebFA 跑在你本机。你的 Agent 通过它使用真实网站：打开页面、看这一页上有什么能用、执行操作、再看结果对不对。

想事的是 Agent，办事的是 WebFA。

```text
打开页面 → 观察 → 操作 → 再观察
```

现在是 **Developer Preview**，接口和行为还可能变。

## 为什么需要 WebFA？

Agent 已经能写代码、改文档、做判断。但要它像人一样上网，常见两条路都会走偏：

| 常见做法 | 实际得到的 |
| --- | --- |
| 给 Agent 套一层网页自动化 | 它去找按钮位置和页面结构，网站一改就失效 |
| 给每个网站单独包接口 | 不是在上网，是在调你写死的几个站 |
| 让 Agent 去操作给人看的浏览器 | Agent 围着人的界面转，自己并没有上网能力 |

所以它不是在常用浏览器上再挂一套自动点击，也不是给每个网站各包一层接口，更不是自带 AI 的桌面浏览器。

它打开真网页，告诉 Agent 这一页上有什么、能做什么。想办法的是你的 Agent，WebFA 只负责去网上把事做完。

## 它能做什么

- 用本机浏览器打开真实网站
- 看清页面上的按钮、输入框、链接，以及现在能不能用
- 填写、选择、提交、打开
- 查看和切换标签页
- 不同账号分开存放，互不串号
- 密码、验证码、二次验证交给人，不让 Agent 填

Agent 只用五个动作：打开页面、观察、操作、查看标签、切换标签。

## 快速开始

需要 Python 3.12+，以及本机已安装的 Chrome 或 Edge。

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
webfa doctor
```

给 Agent 生成接入配置：

```powershell
webfa mcp-config --agent-id <your-agent-name>
```

连上之后会自动启动本机服务，不用自己管进程。每个 Agent 用自己的名字；不同账号可以同时用。

[OpenCode](docs/agent-integrations/opencode.md) · [Kimi Code](docs/agent-integrations/kimi-code.md) · [Claude Code](docs/agent-integrations/claude-code.md) · [Codex](docs/agent-integrations/codex.md)

## 登录

不要让 Agent 输入密码、验证码或二次验证。需要登录的网站，先自己准备好：

```powershell
webfa login github
webfa login --url https://example.com/login
```

遇到必须本人确认的步骤，停下来人来完成，再让 Agent 重新看页面。

## 不会交给 Agent 的东西

默认不把这些给 Agent：登录 Cookie、本地存储、令牌、密码、整页 HTML。它也不能靠选择器或浏览器调试通道直接操作页面。

## 现在还做不到

- 不帮你过验证码、反爬和风控
- 同一个账号同一时间只能有一处在改页面
- 关掉之后，进行中的操作不会接着跑

## 开发

```powershell
python -m pytest -q
```

环境变量见 `.env.example`。运行数据默认在 `%APPDATA%\WebFA`。

想看后面怎么走，见 [路线图](docs/browser-runtime-roadmap.md)。

## License

MIT，见 [`LICENSE`](LICENSE)。
