# WebFA MCP 测试报告

## 一、测试环境

| 项目 | 配置/值 |
|---|---|
| 测试日期 | 2026-06-21 |
| WebFA 项目路径 | `E:/项目库/webFA/webfa-phase1` |
| WebFA Runtime | `http://127.0.0.1:8787` |
| MCP Server 命令 | `E:/项目库/webFA/webfa-phase1/.venv/Scripts/webfa-mcp.exe` |
| MCP 配置文件 | `C:/Users/Lulufeizhu/.kimi-code/mcp.json` |
| 可用 WebFA 工具 | `webfa.open_url`、`webfa.observe`、`webfa.act`、`webfa.get_tabs`、`webfa.switch_tab` |
| 浏览器会话 | `default` |
| GitHub 账号 | `FeiZhuLulu` |

## 二、接入验证

在 Kimi Code CLI 中配置 MCP 后，客户端重启后显示：

```
MCP server 'webfa' connected · 5 tools (stdio)
```

运行 `webfa doctor` 全绿，Runtime 与 MCP server 通信正常。

## 三、测试任务明细

### 任务 1：打开 aihot 网站，读取最近三个热点

#### 3.1.1 首次尝试（失败）

由于用户未提供准确网址，首轮尝试访问了多个候选域名：

| 尝试域名 | 结果 |
|---|---|
| `aihot.cn` | 不可访问 |
| `aihot.com` | 不可访问 |
| `aihot.top` | 可访问，但内容为无关 WordPress 博客 |
| `aihot.io` | 不可访问 |
| `aihot.net` | 不可访问 |
| `aihotnews.com` | 不可访问 |
| `aihot.github.io` | 不可访问 |

结论：无法定位正确站点，任务 1 初测 **FAIL**。

#### 3.1.2 重新测试（通过）

用户提供正确地址：`https://aihot.virxact.com/`

使用 `webfa.open_url` 打开并 `webfa.observe` 等待加载完成，页面信息如下：

- 标题：AI HOT — AI 行业动态聚合 · 每日精选与 AI 日报
- 日期：6月21日 · 周日

读取到的最近三个热点：

1. **John Jumper 离开 Google DeepMind 加入 Anthropic**（今日热点 TOP 1）
   - 信源：6 个 · 20小时前
   - 摘要：John Jumper 曾领导 AlphaFold 团队攻克 50 年蛋白质结构预测难题，此次离职 DeepMind 转投 Anthropic，被视为顶级 AI 人才在安全与对齐领域重新站队的信号。

2. **美团 tabbit 国际版免费接入 GPT-5.5 / Claude Opus 4.8 等旗舰模型**（热度 78）
   - 时间：6月21日 19:05
   - 摘要：tabbit 国际版一次性接入三家旗舰模型并全免费，对不想开多订阅的用户是实用降本方案。

3. **腾讯元宝父亲节活动：上传照片生成与年轻爸爸的合影**（热度 64）
   - 时间：6月21日 13:00
   - 摘要：元宝的父亲节营销活动，合影生成指令写得具体可复现，比普通 AI 写真教程更接地气。

结论：任务 1 复测 **PASS**。

---

### 任务 2：打开 inkcraft.cc，判断项目功能和评价

使用 `webfa.open_url` 打开 `https://inkcraft.cc/`，页面加载后读取内容。

- 标题：Inkcraft — AI 写作工作台
- 版本：v0.5.1 公测

#### 功能判断

Inkcraft 是一款面向**长篇网文作者**的 AI 写作工作台，核心功能包括：

1. **AI 续写与润色**：基于上下文生成剧情段落、对话和描写。
2. **世界观与角色管理**：支持创建和维护小说世界观、角色卡、关系图谱。
3. **灵感助手**：提供剧情灵感、冲突设计、伏笔建议等创意辅助。
4. **章节大纲与结构管理**：可拆分卷章、管理写作大纲。
5. **多模型支持**：接入多个主流大模型供作者选择。

#### 评价

- **产品定位清晰**：聚焦网文创作这一垂直场景，功能贴合作者需求。
- **仍处于早期**：v0.5.1 公测版本，界面和功能完善度尚在迭代中。
- **差异化价值**：相比通用 AI 聊天工具，Inkcraft 在角色一致性、世界观沉淀、长文上下文管理方面有专门设计。
- **潜在挑战**：长篇生成的一致性和付费模型成本控制，是后续需要重点验证的方向。

结论：任务 2 **PASS**（仅读取，未进行写操作）。

---

### 任务 3：检查并可能取消 star `anthropics/skills`

使用 `webfa.open_url` 打开 `https://github.com/anthropics/skills`。

#### 操作前状态

页面显示仓库已处于 **starred** 状态（按钮显示为可取消 star）。

#### 执行操作

1. 使用 `webfa.act(click)` 点击 star 按钮，执行取消 star。
2. 首次点击返回的状态仍有延迟，未立即反映未 star 状态。
3. 使用 `webfa.observe` 刷新页面状态后，确认按钮已变为 **“Star”**，表示当前账号未 star 该仓库。

#### 操作后状态

- 按钮文本：`Star`
- Star 数量：未显示为已 star 状态
- 结论：成功取消 star。

结论：任务 3 **PASS**。

---

### 任务 4：在 GitHub 创建公开仓库 `webFA` 并写入 README `Hello world`

#### 4.4.1 首次填表尝试（遇到 WebFA 限制）

打开 `https://github.com/new` 后，尝试使用 `webfa.act(type)` 在 Repository name 输入框填入 `webFA`。虽然输入框的 `value` 属性显示为 `webFA`，但 GitHub 的 React 受控表单未触发 `onChange` 事件，表单持续提示：

```
Name cannot be blank
```

尝试过的方法：
- `type` 直接输入
- `clear` 后重新 `type`
- `press(Tab)` 切换焦点
- `focus` 聚焦
- `press(Enter)`

均未能使 GitHub 表单验证通过。判断为 WebFA 的 `type` 动作对 React 受控输入框的事件触发存在兼容性问题。

#### 4.4.2 解决方案：URL 预填参数

改用 GitHub 支持的 URL 查询参数预填表单：

```
https://github.com/new?name=webFA&visibility=public&readme=true
```

效果：
- Repository name 自动填充为 `webFA`
- 表单验证通过，显示 `webFA is available`
- Visibility 默认为 Public
- 手动点击开启 `Add README` 开关

#### 4.4.3 创建仓库

点击 `Create repository` 按钮，页面进入 `Creating repository…` 状态，随后重定向至：

```
https://github.com/FeiZhuLulu/webFA
```

仓库创建成功，可见：
- 仓库名：`FeiZhuLulu/webFA`
- 可见性：`Public`
- 默认分支：`main`
- 初始文件：`README.md`

#### 4.4.4 编辑 README

1. 打开编辑页：`https://github.com/FeiZhuLulu/webFA/edit/main/README.md`
2. 使用 `webfa.act(click)` 聚焦代码编辑器（contenteditable div）
3. 使用 `webfa.act(clear)` 清空默认内容 `# webFA`
4. 使用 `webfa.act(type)` 输入 `Hello world`
5. 点击 `Commit changes...`，在弹出的 commit 对话框中确认：
   - Commit message：`Replace project title with 'Hello world'`（Copilot 自动生成）
   - Commit 方式：`Commit directly to the main branch`
6. 点击 `Commit changes` 提交

#### 4.4.5 结果验证

页面提交后跳转至：

```
https://github.com/FeiZhuLulu/webFA/blob/main/README.md
```

验证信息：

- 文件内容：`Hello world`
- 文件大小：12 Bytes，1 line
- 最新 commit：`Replace project title with 'Hello world'`（`a200af4`）
- 仓库主页再次确认：`webFA Public`，README 区域显示 `Hello world`

结论：任务 4 **PASS**。

## 四、遇到的问题与 workaround

| 问题 | 场景 | 解决方案 |
|---|---|---|
| React 受控输入框无法触发验证 | GitHub 新建仓库表单 | 使用 URL 查询参数 `?name=webFA&visibility=public&readme=true` 预填 |
| Star 状态更新有延迟 | GitHub 仓库 star/unstar | 执行点击后调用 `webfa.observe` 刷新状态再确认 |
| aihot 正确网址未知 | 任务 1 首次尝试 | 用户提供 `https://aihot.virxact.com/` 后复测通过 |

## 五、测试结论

| 任务 | 初测 | 复测/最终结果 |
|---|---|---|
| 1. aihot 读取最近三个热点 | FAIL | **PASS** |
| 2. inkcraft.cc 功能与评价 | — | **PASS** |
| 3. anthropics/skills 取消 star | — | **PASS** |
| 4. 创建 GitHub 公开仓库 `webFA` 并写 README | — | **PASS** |

所有任务最终均通过 WebFA MCP 工具完成。测试过程中暴露出 WebFA 对 React 受控组件的 `type` 事件触发不够完善，可通过 URL 参数或直接访问编辑页等方式绕过。

## 六、产物链接

- GitHub 仓库：`https://github.com/FeiZhuLulu/webFA`
- README 文件：`https://github.com/FeiZhuLulu/webFA/blob/main/README.md`
