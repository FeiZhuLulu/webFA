# WebFA P12 Multi Session / Multi Profile 完整设计

Status: frozen target architecture; P12.1-P12.3 implemented and accepted

Phase name:

```text
P12 Multi Session / Multi Profile
多 Session / 多 Profile 隔离运行时
```

Frozen on: 2026-07-13

Implementation status:

- P12.0 Definition Freeze: complete
- P12.1 Schema and Profile Catalog: complete
- P12.2 Profile Storage Isolation: complete
- P12.3 Session Runtime Extraction: complete
- P12.4 Supervisor and Global Routing: next
- P12.5-P12.8: not started

P12.1-P12.3 report: `docs/reports/P12_1_3_PROFILE_SESSION_FOUNDATION_REPORT.md`.

P12 建立 WebFA 的多互联网身份与多任务运行模型。它不是给传统浏览器增加“多开”功能，也不是把当前单例 Runtime 简单改成一个字典。P12 的目标是让 Agent 能够在多个彼此隔离、可持久化、可授权、可监控的互联网身份环境中独立工作，同时保持 WebFA 的 Agent 原生接口、安全契约和五工具公共表面。

---

## 1. Product Goal

WebFA 的核心目标是让 Agent 成为真正的互联网用户：Agent 能够自行访问、理解、操作和验证真实互联网，而不依赖传统人类浏览器形态。

P10 回答：

```text
Agent 如何通过 WebObjects 和语义操作使用真实网页？
```

P11 回答：

```text
Agent 如何在真实网页上保持自主性，同时遵守确定性安全边界？
```

UI-1B 回答：

```text
人类如何观察并临时接管同一个 BrowserHost，而不创建第二个真实页面？
```

P12 回答：

```text
WebFA 如何同时承载多个互联网身份、多个 Agent 任务和多个独立运行上下文，
并保证身份、状态、操作、授权、监控和副作用不发生串线？
```

目标结构：

```text
Agent connections
  -> five MCP browser tools
  -> BrowserRuntimeSupervisor
       -> BrowserProfile A
            -> BrowserSession A
                 -> dedicated ManagedChromiumHost A
                 -> multiple Tabs
                 -> isolated ObjectRegistry
                 -> isolated Session safety state
                 -> AgentSessionLease
                 -> HumanControlLease
                 -> Monitor projection
       -> BrowserProfile B
            -> BrowserSession B
                 -> dedicated ManagedChromiumHost B
                 -> ...
```

---

## 2. Frozen Architecture Decisions

以下决策已经冻结，后续实现阶段不得重新发明相互冲突的临时模型。

### 2.1 Persistent Profile topology

```text
一个活动的持久 BrowserProfile
=
一个独立 WebFA user-data-dir
=
一个独立 ManagedChromiumHost 进程
=
同一时间最多一个活动的可写 BrowserSession
=
一个 Session 内可以存在多个 Tab
```

多个不同 Profile 可以并发运行。

同一个 Profile 不允许由多个独立 Chromium 进程同时打开。对同一 Profile 的额外观察者必须通过现有 Session 的 Monitor projection、SessionEventBus 和 VisualStreamHub 接入，而不是启动第二个页面副本或第二个 Host。

### 2.2 Profile and Session semantics

```text
BrowserProfile = 长期互联网身份与持久浏览器状态容器
BrowserSession = 使用某个 Profile 开展一次活动任务的运行实例
Tab            = Session 内的页面目标
```

Profile 不是 Tab，Session 不是账号，Monitor 不是 Session。

### 2.3 Agent public surface

默认 MCP 工具仍然严格保持五个：

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

P12 不增加 `create_profile`、`list_profiles`、`create_session`、`import_cookies` 或原始浏览器管理工具。Profile 创建、删除、策略编辑、Cookie 导入和维护操作属于本地受保护控制面。

五工具可以扩展可选参数和返回结构，但不得暴露 selector、XPath、DOM、CDP、Cookie、存储、Token、密码或本地路径。

### 2.4 Cookie import boundary

Cookie 导入不是 P12 Core 的先决实现项。

P12 Core 必须先完成：

- 真实 Profile 持久化；
- user-data-dir 隔离；
- Profile 锁；
- Session Supervisor；
- Agent/Profile/Session 路由；
- Monitor 与安全状态隔离。

Cookie 导入作为后续 `Profile Bootstrap` 能力消费这些基础。设计必须预留接口和锁约束，但 P12 Core 可以在 Cookie 导入完成前独立验收。

### 2.5 No disposable public model

P12 可以分阶段实现，但最终对象模型、公共协议、生命周期、隔离规则和验收标准在编码前一次性定义完整。实现覆盖不足不能被包装为一个临时、以后必然重写的产品模型。

---

## 3. Scope

P12 Core 包含：

- 持久 `BrowserProfile` 实体；
- Profile Catalog、Repository 和本地控制面；
- 独立 Chromium user-data-dir；
- 跨进程 `ProfileProcessLock`；
- `BrowserRuntimeSupervisor`；
- 多 `BrowserSessionRuntime`；
- Agent connection context；
- Agent/Profile grant；
- Session-exclusive Agent lease；
- 全局 Session、Tab 和 WebObject 路由；
- 多 Session MonitorGateway；
- Session-scoped HumanControlLease；
- P11 状态的正确重新定域；
- Profile 和 Session 生命周期；
- 并发、崩溃、隔离和迁移验收。

P12 Core 不包含：

- P13 Durable Trace / Resume；
- 浏览器进程崩溃后的页面级任务恢复；
- 多设备或远程 WebFA 集群；
- 云端 Profile 同步；
- 反检测或反机器人绕过；
- 从用户已安装 Chrome 的默认数据目录直接接管 Profile；
- 向 Agent 暴露 Cookie、localStorage、IndexedDB 或原始身份材料；
- 站点专用账号识别器；
- 让两个 Agent 同时写入同一个 Profile；
- 共享进程的持久 BrowserContext 优化。

---

## 4. Terminology

### BrowserProfile

WebFA 管理的长期互联网身份容器。持久 Profile 承载 Chromium 用户数据、登录状态、网站权限、Profile 安全策略以及 Agent 使用边界。

### BrowserSession

在一个 Profile 上运行的活动任务环境。一个 Session 拥有独立的 WebState、ObjectRegistry、SessionEventBus、租约、安全上下文、视觉绑定和 Tab 集合。

### ProfileRuntime

Profile 被激活后的进程级运行实体，包括 Profile 锁、Managed Chromium Host、活动 Session 和运行健康状态。

### BrowserSessionRuntime

当前 `BrowserRuntime` 中真正负责页面操作的 Session 级 Runtime。

### BrowserRuntimeSupervisor

应用级总控。管理 Profile Catalog、活动 ProfileRuntime、BrowserSessionRuntime、Agent connection、全局路由和资源限制。它自身不编译网页对象，也不直接执行页面操作。

### AgentConnectionContext

一个 MCP server 进程或其他受信 Agent 接入连接的运行上下文。它记录 `agent_id`、`connection_id`、当前 Session、已授权 Profile、持有的 Session lease 和连接级序列化锁。

### AgentProfileGrant

允许特定 Agent connection 在限定目的、Origin、期限和策略下使用某个 Profile 的授权。

### AgentSessionLease

允许特定 Agent connection 对一个活动 Session 执行写入型网页操作的排他租约。

### ProfileProcessLock

阻止同一个 Profile 的 user-data-dir 被多个 Chromium 实例同时打开的跨进程锁。

### ProfileMutationLease

Cookie 导入、清理站点数据、克隆、删除、恢复等离线 Profile 修改使用的排他维护租约。

### Runtime generation

一次 Session Runtime 实例化的不可复用代次标识。Session 重建后 generation 改变，用于阻止旧 Tab、WebObject、Monitor Grant、Step-up 或其他授权跨实例重放。

---

## 5. Target Architecture

```text
Electron Control Center
  -> protected local control API
  -> BrowserRuntimeSupervisor
       -> ProfileRepository
       -> ProfileStorageManager
       -> ProfileLockManager
       -> SessionManager
       -> AgentConnectionRegistry
       -> GlobalRouteRegistry
       -> MonitorGatewayRouter
       -> RuntimeResourceGovernor

MCP connection A
  -> AgentConnectionContext A
  -> current Session A
  -> BrowserSessionRuntime A
       -> SessionWorker
       -> BrowserSession
       -> BrowserDriver
       -> ManagedChromiumHost
       -> ObjectRegistry
       -> WebObserveService
       -> SemanticOperationExecutor
       -> SessionEventBus
       -> VisualStreamHub
       -> HumanControlLeaseManager
       -> Session-scoped P11 state

MCP connection B
  -> AgentConnectionContext B
  -> current Session B
  -> BrowserSessionRuntime B
       -> ...
```

核心原则：

```text
Supervisor routes.
SessionRuntime operates.
Profile owns identity.
Session owns task state.
Host owns the only real page instance.
Monitor only projects that instance.
```

---

## 6. BrowserProfile Model

建议新增公共内部 schema：

```text
BrowserProfile
  profile_id: opaque stable id
  agent_alias: unique Agent-visible alias
  display_name: local-control-plane-only name
  persistence: persistent | ephemeral
  owner: user_owned | agent_owned | shared
  trust_mode: trusted_agent | guarded_agent
  bound_agent_ids: list[str]
  allowed_origins: list[str]
  unknown_external_effect_policy
  safety_policy_id
  financial_policy_id
  storage_ref: opaque internal reference
  bootstrap_source: blank | human_login | imported | cloned | restored
  catalog_state: ready | archived | deleting | error
  version: integer
  created_at
  updated_at
  last_used_at
```

### 6.1 Agent-visible versus local-only metadata

Agent 可见：

- `profile_id`；
- `agent_alias`；
- owner；
- trust mode；
- 当前是否可用、忙碌或需要授权；
- 被明确配置为 Agent 可见的非秘密说明。

仅本地控制面可见：

- 人类显示名称；
- 账号邮箱或用户名；
- Profile 存储路径；
- Cookie 数量和网站存储统计；
- 导入来源文件；
- 本地维护记录；
- 任何身份秘密。

`agent_alias` 由用户明确配置，例如 `personal`、`work`、`automation-test`。WebFA 不应自动把邮箱、用户名或网页抓取出的身份信息暴露为 Agent alias。

### 6.2 Profile storage

持久 Profile 目录：

```text
webfa-data/
  profiles/
    <profile_id>/
      chromium-user-data/
      downloads/
      maintenance/
      profile.lock
```

Agent 永远不能看到该路径。

### 6.3 Persistent and ephemeral profiles

P12 Core 以持久 Profile 为正式路径。

完整模型预留：

```text
persistent
  独立 user-data-dir
  可保留登录状态
  默认 dedicated process

ephemeral
  临时身份环境
  关闭后清理
  未来可以映射为独立临时 user-data-dir 或共享进程 BrowserContext
```

P12 Core 不依赖共享 BrowserContext 才能成立。

---

## 7. BrowserSession Model

```text
BrowserSession
  session_id: opaque stable id
  profile_id
  runtime_generation
  lifecycle: created | starting | running | stopping | closed | crashed | interrupted
  control_state: idle | agent_controlled | human_controlled
  health: healthy | degraded | failed
  active_tab_id
  created_by_agent_id
  created_by_connection_id
  created_at
  started_at
  last_activity_at
  stopped_at
  close_reason
```

### 7.1 Relationship rules

- 一个 Session 必须绑定且只能绑定一个 Profile；
- Session 运行期间不能切换 Profile；
- 一个 Profile 同一时间最多一个活动 Session；
- 一个 Session 可拥有多个 Tab；
- Session 关闭后不能重新进入 `running`；
- 同一 Profile 再次启动时创建新 Session 和新 runtime generation；
- P13 之前不承诺恢复旧 Session 的页面、ObjectRegistry 或任务进度。

### 7.2 Session persistence

P12 可以持久化 Session 元数据和终态，用于 Control Center、审计和故障说明，但不持久化足以恢复任务的完整运行状态。

Runtime 启动时，数据库中遗留的 `starting`、`running` 或 `stopping` Session 必须被确定性标记为：

```text
interrupted
```

P13 才定义是否以及如何恢复。

---

## 8. ProfileRuntime and Host Topology

### 8.1 Launch specification

`ManagedChromiumHost` 不再自行推导全局默认目录。它必须接收明确的内部启动规格：

```text
ProfileLaunchSpec
  profile_id
  user_data_dir
  downloads_dir
  headless
  runtime_instance_id
  runtime_generation
  optional network policy
```

`create_default_driver_factory()` 必须由 Session/Profile 上下文构造，而不是返回一个不含 Profile 信息的全局 lambda。

### 8.2 One Profile, one Host

持久 Profile 激活时：

```text
acquire ProfileProcessLock
  -> create ProfileRuntime
  -> start ManagedChromiumHost with explicit user-data-dir
  -> create BrowserSessionRuntime
  -> publish session_started
```

关闭时：

```text
stop accepting new operations
  -> release HumanControlLease
  -> synthesize missing input releases
  -> close Monitor connections and visual stream
  -> revoke Session-scoped grants
  -> close BrowserSessionRuntime
  -> close ManagedChromiumHost
  -> mark Session terminal state
  -> release ProfileProcessLock
```

### 8.3 BrowserContext boundary

CDP `Target.createBrowserContext` 创建的是新的空 BrowserContext，官方描述为类似无痕 Profile。它适合未来的临时隔离，但不是 P12 持久账号的默认模型。

P12 持久 Profile 使用独立 user-data-dir，因为 Chromium 的用户数据目录承载 Cookie、历史、书签和其他本地状态，而且两个运行中的 Chromium 实例不能安全共享同一个 user-data-dir。

---

## 9. BrowserRuntimeSupervisor

新增应用级组件：

```text
BrowserRuntimeSupervisor
```

职责：

- 读取和持久化 Profile Catalog；
- 创建、归档和删除 Profile；
- 启动、查找、停止和回收 Session；
- 管理活动 ProfileRuntime；
- 管理 Agent connection；
- 建立 Profile grant 和 Session lease；
- 将五工具请求路由到正确 SessionRuntime；
- 管理全局 Tab/WebObject 路由；
- 路由 Monitor Grant；
- 执行资源上限和空闲回收；
- 隔离单个 Session 故障；
- 提供本地 Control Center 状态。

Supervisor 不负责：

- 采集 DOM/AX/Raw Snapshot；
- 编译 WebObjects；
- 执行语义网页操作；
- 直接发送 CDP 页面命令；
- 解释用户自然语言；
- 读取 Cookie 或网页秘密并返回 Agent。

---

## 10. BrowserSessionRuntime

当前 `BrowserRuntime` 的页面运行职责下沉为：

```text
BrowserSessionRuntime
```

每个 SessionRuntime 独立拥有：

- `SessionWorker` 和 job queue；
- `BrowserSession`；
- `ObjectRegistry`；
- `AgentViewBuilder` / `WebObjectCompiler`；
- `WebObserveService`；
- `SemanticOperationExecutor`；
- `RuntimeEvidenceResolver`；
- `SessionEventBus`；
- `VisualStreamHub`；
- `HumanControlLeaseManager`；
- `SafetyContextManager`；
- `StepUpManager`；
- `SafetyReceiptStore`；
- `LocalResourceBroker` 或 Session-bound grant view；
- selected payment reference；
- Session operation lock；
- visual/document binding；
- pressed key and pointer state。

`_web_operation_lock` 必须从全局 Runtime 下沉到每个 Session。Session A 的长操作不能阻塞 Session B。

---

## 11. Agent Connection Model

### 11.1 Connection identity

MCP server 进程启动时生成高熵：

```text
connection_id
```

Runtime client 在所有五工具 HTTP 请求中发送内部头：

```text
X-WebFA-Agent-Id
X-WebFA-Connection-Id
X-WebFA-MCP-Tool
```

`connection_id` 不需要由 Agent 模型填写，也不进入工具 schema。

### 11.2 AgentConnectionContext

```text
AgentConnectionContext
  connection_id
  agent_id
  current_session_id
  current_profile_id
  authorized_profile_ids
  leased_session_ids
  binding_revision
  created_at
  last_seen_at
  expires_at
  operation_lock
```

一个 connection 可以在多个已授权 Profile 上保留活动 Session，但任一时刻有一个 current Session，五工具默认操作该 Session。

### 11.3 Connection serialization

为避免同一 MCP connection 并发执行 `switch_tab`、跨 Profile `open_url` 与 `act` 时发生 current-session 竞态，所有浏览器工具调用必须经过 connection-level sequencing。

这不阻止：

- 不同 MCP connection 并发；
- 不同 Agent 并发；
- 不同 Profile 的 SessionRuntime 并发；
- Monitor 读取多个 Session。

未来如需一个 Agent connection 内真正并行操作多个 Session，应通过明确的并行上下文协议扩展，而不是让隐式 current-session 指针发生竞态。

### 11.4 Disconnect and expiry

HTTP 本身不能可靠感知 Agent 进程崩溃，因此：

- MCP server 正常退出时执行 best-effort connection release；
- 每次工具调用续租 connection 和 Session lease；
- 异常断开依赖 TTL 到期；
- Session 可以在 Agent lease 释放后保持 idle；
- 另一个有权限的 Agent 可在旧 lease 失效后取得控制；
- Profile Host 的空闲回收由 Supervisor 策略决定。

---

## 12. Profile Authorization and Session Control

P12 采用三层模型。

### 12.1 ProfilePolicy

长期持久化策略：

```text
profile_id
owner
trust_mode
bound_agent_ids
allowed_origins
unknown_external_effect_policy
safety_policy_id
financial_policy_id
```

### 12.2 AgentProfileGrant

连接或任务级授权：

```text
AgentProfileGrant
  grant_id
  agent_id
  connection_id
  profile_id
  purpose
  allowed_origins
  issued_at
  expires_at
  max_sessions
  status
```

行为：

- `agent_owned` 且明确绑定 Agent 的 Profile 可以按策略自动授予；
- `shared` Profile 根据配置授予；
- `user_owned` Profile 默认需要本地控制面预授权或 step-up；
- Agent 不能从一个低权限 Profile 静默移动到更受保护的 Profile；
- Grant 不包含 Cookie、密码或任何身份秘密。

### 12.3 AgentSessionLease

```text
AgentSessionLease
  lease_id
  agent_id
  connection_id
  session_id
  profile_id
  runtime_generation
  issued_at
  expires_at
  status
```

规则：

- 一个 Session 同一时间最多一个有效写入 AgentSessionLease；
- 一个 connection 可持有多个不同 Session 的 lease；
- 所有写操作必须验证 Agent、connection、Session、Profile 和 generation；
- `observe` 可以在当前持有 lease 或明确授权的受保护只读路径中运行；
- HumanControlLease 生效时 Agent 写操作暂停，但 AgentSessionLease 不转移给人类；
- lease 到期后旧 Agent 请求确定性失败，不得继续使用缓存对象。

---

## 13. Five-Tool Routing Contract

### 13.1 `webfa.open_url`

新增可选字段：

```text
profile_ref: string | null
```

语义：

```text
open_url(url)
  -> 在 connection 当前 Session 中导航
  -> 没有当前 Session 时使用被配置的默认 Profile 创建 Session

open_url(url, profile_ref="work")
  -> 解析 Agent 可见 Profile alias 或授权的 profile_id
  -> 验证 ProfilePolicy 和 AgentProfileGrant
  -> 如 Profile 无活动 Session则创建
  -> 如已有活动 Session且 lease 可取得则绑定
  -> 设置为 connection 当前 Session
  -> 在该 Session 中导航
```

确定性错误：

```text
profile_not_found
profile_access_denied
profile_authorization_required
profile_archived
profile_busy
profile_start_failed
session_lease_busy
runtime_capacity_reached
```

`profile_ref` 不能是文件路径、Chrome Profile 目录或任意 user-data-dir。

### 13.2 `webfa.observe`

默认读取 connection 当前 Session。

返回 WebState 必须包含：

```text
session_id
runtime_generation or equivalent binding marker
agent.profile_id
agent profile alias projection
```

没有 current Session 时返回确定性 `session_not_selected`，而不是隐式创建不明身份的 Session。

### 13.3 `webfa.act`

始终作用于 connection 当前 Session，并验证：

- 当前 Session lease；
- target WebObject 的 Session namespace；
- runtime generation；
- document revision；
- object version；
- P11 SafetyContext、ProfilePolicy 和其他授权绑定。

跨 Session 或旧 generation 的对象必须返回专用错误，而不是在另一个 ObjectRegistry 中碰巧命中相同字符串。

### 13.4 `webfa.get_tabs`

工具名保持不变，但返回升级为 Agent 的浏览上下文总览：

```json
{
  "current_session_id": "session_...",
  "current_profile_id": "profile_...",
  "sessions": [
    {
      "session_id": "session_...",
      "profile": {
        "profile_id": "profile_...",
        "profile_ref": "work",
        "owner": "user_owned",
        "trust_mode": "guarded_agent"
      },
      "control_state": "agent_controlled",
      "tabs": [
        {
          "id": "tab_...",
          "session_id": "session_...",
          "url": "https://example.com/",
          "title": "Example",
          "active": true
        }
      ]
    }
  ],
  "available_profiles": [
    {
      "profile_id": "profile_...",
      "profile_ref": "personal",
      "availability": "inactive"
    }
  ]
}
```

只返回该 Agent connection 有权知道的 Profile，不暴露人类显示名、邮箱、Cookie、存储统计或路径。

### 13.5 `webfa.switch_tab`

`tab_id` 全局唯一并可跨 Session 路由：

```text
tab_id
  -> GlobalRouteRegistry
  -> session_id
  -> profile_id
  -> runtime_generation
  -> BrowserSessionRuntime
```

切换另一个 Session 的 Tab 时：

- 验证 AgentProfileGrant；
- 获取或续租目标 AgentSessionLease；
- 更新 AgentConnectionContext current Session；
- 激活目标 Tab；
- 返回目标 Session WebState。

如果目标 Session 被其他 Agent 排他控制，返回 `session_lease_busy`。

---

## 14. Identity and Route Namespacing

P12 必须消除当前单 Session 下可接受、在多 Session 下危险的局部 ID。

以下 ID 必须具备 Session/generation 绑定：

- WebObject ID；
- Tab ID；
- Document ID；
- ChangeSet reference；
- Step-up grant；
- LocalResourceGrant；
- SafetyContext；
- SafetyReceipt；
- Monitor Grant；
- HumanControlLease；
- visual frame binding；
- selected payment reference binding。

推荐形式：

```text
opaque random id + server-side route metadata
```

不要求把原始 `session_id` 明文拼入 ID，但服务器必须能够确定性验证归属。

错误类型至少包括：

```text
object_session_mismatch
tab_session_mismatch
stale_runtime_generation
session_not_selected
session_closed
session_interrupted
profile_binding_mismatch
```

---

## 15. Locking Model

### 15.1 Lock order

统一锁顺序，避免死锁：

```text
Supervisor registry lock
  -> ProfileProcessLock / ProfileMutationLease
  -> AgentConnectionContext lock
  -> Session operation lock
  -> Session-local subsystem lock
```

任何实现不得反向长期持锁。

### 15.2 ProfileProcessLock

目标：防止相同 user-data-dir 被多个 WebFA Runtime 或残留进程同时使用。

要求：

- 使用 OS 级文件描述符锁或等价可靠机制；
- 锁文件元数据不是锁本身；
- 进程崩溃后 OS 自动释放锁；
- 元数据可记录 runtime instance、PID、进程启动标识、generation 和时间；
- 不得只看到旧 PID 就删除锁；
- 获取锁失败返回 `profile_locked`，不得强行启动 Chromium；
- Profile 路径不进入 Agent 错误消息。

### 15.3 ProfileMutationLease

用于：

- Cookie 导入；
- Profile 克隆；
- 清除站点数据；
- Profile Bundle 恢复；
- Profile 删除；
- 底层存储迁移。

约束：

```text
存在 active Session 或 active ProfileProcessLock
  -> MutationLease 获取失败
```

维护任务不能与页面运行并发修改同一 Profile。

### 15.4 Session operation lock

每个 Session 独立序列化会改变页面或绑定状态的操作：

- open；
- act；
- tab switch；
- Host restart；
- HumanControlLease acquire/release；
- human input；
- visual binding transition。

不同 Session 不共享此锁。

---

## 16. Lifecycle

### 16.1 Profile catalog state

```text
ready
archived
deleting
error
```

### 16.2 Profile runtime state

```text
inactive
starting
active
stopping
crashed
```

Catalog state 和 Runtime state 分开。一个 ready Profile 可以 inactive 或 active。

### 16.3 Session lifecycle

```text
created
  -> starting
  -> running
  -> stopping
  -> closed

starting | running | stopping
  -> crashed

Runtime restart detects non-terminal record
  -> interrupted
```

### 16.4 Session control state

```text
idle
agent_controlled
human_controlled
```

### 16.5 Session health

```text
healthy
degraded
failed
```

不要把生命周期、控制者和健康状态压缩成一个枚举。

### 16.6 Profile deletion

删除流程：

```text
mark deleting
  -> reject new grants and sessions
  -> require no active Session
  -> acquire ProfileMutationLease
  -> revoke Profile grants
  -> detach protected references
  -> remove storage through bounded local operation
  -> write secret-free audit record
  -> delete catalog record or preserve tombstone
```

删除失败时 Profile 进入 `error` 或保留 `deleting` 供恢复，不得部分删除后重新标为 ready。

---

## 17. Persistence Model

P12 使用现有 SQLite / SQLAlchemy 基础持久化 Profile 和 Session 元数据。

建议新增表：

```text
browser_profiles
  id
  agent_alias
  display_name
  persistence
  owner
  trust_mode
  allowed_origins_json
  unknown_effect_policy
  safety_policy_id
  financial_policy_id
  storage_key
  bootstrap_source
  catalog_state
  version
  created_at
  updated_at
  last_used_at

browser_profile_agent_bindings
  profile_id
  agent_id
  binding_mode
  created_at

browser_sessions
  id
  profile_id
  runtime_generation
  lifecycle
  control_state
  health
  created_by_agent_id
  created_by_connection_id
  created_at
  started_at
  last_activity_at
  stopped_at
  close_reason

browser_profile_runtime_events
  id
  profile_id
  session_id
  event_type
  safe_metadata_json
  created_at
```

### 17.1 Secret-free database rule

这些表不得存储：

- Cookie 值；
- localStorage/sessionStorage 值；
- Authorization Token；
- 密码；
- OTP；
- Profile 的绝对路径；
- HumanControl 输入值；
- 原始导入文件内容。

`storage_key` 是内部相对引用，不是 Agent 可见路径。

### 17.2 Session state boundary

P12 持久化 Session 元数据和审计终态，不持久化足以恢复以下内容的完整状态：

- ObjectRegistry；
- WebState revisions；
- tab page history；
- pending operation continuation；
- HumanControlLease；
- AgentSessionLease；
- Monitor connection；
- Step-up continuation。

这些属于 P13 或安全上应 fail closed 的短期状态。

---

## 18. P11 State Re-scoping

P12 必须对 P11 组件重新定域，而不是把当前全局 Store 共享给所有 Session。

### 18.1 Supervisor/global scope

- ProfileRepository；
- ProfilePolicy definitions；
- protected PaymentInstrument catalog；
- Runtime instance identity；
- global resource limits；
- local Control Center authority。

### 18.2 Profile scope

- Profile ownership；
- bound agents；
- Origin policy；
- trust mode；
- unknown-effect policy；
- financial policy；
- permitted protected instrument references。

### 18.3 Connection scope

- AgentProfileGrant；
- current Session binding；
- connection operation sequence；
- connection TTL。

### 18.4 Session scope

- AgentSessionLease；
- SafetyContext；
- Runtime evidence state；
- Step-up grant；
- SafetyReceipt；
- LocalResourceGrant usage；
- selected payment reference；
- ObjectRegistry；
- SessionEventBus；
- HumanControlLease；
- visual stream and document binding。

### 18.5 Cross-session replay protection

以下对象必须同时绑定：

```text
agent_id
connection_id where applicable
profile_id
session_id
runtime_generation
origin where applicable
document_id where applicable
object version or operation target where applicable
expiry and use count
```

Session A 的 Step-up、文件授权、支付授权、Monitor Token 或对象引用不能在 Session B 使用，即使两个 Session 访问同一 Origin。

---

## 19. Monitor and Human Control

### 19.1 Monitor routing

新增：

```text
MonitorGatewayRouter
  session_id -> SessionMonitorGateway
```

Monitor Grant 必须绑定：

```text
session_id
profile_id
tab_id or allowed tab scope
runtime_generation
permissions
expires_at
```

P12 后禁止使用“当前全局 Runtime”“默认 Session”“默认 Profile”推导 Monitor 目标。

### 19.2 VisualStreamHub

当前一个 Managed Chromium Host 只能有一条 `Page.startScreencast`。P12 在每个 Session 内增加：

```text
VisualStreamHub
```

```text
ManagedChromiumHost
  -> one host screencast
  -> VisualStreamHub
       -> Monitor connection A
       -> Monitor connection B
       -> Control Center preview
```

视觉消费者共享一条 Host Screencast。慢消费者使用有界 lossy frame queue；关键租约和控制消息继续走独立可靠优先队列。

### 19.3 HumanControlLease

- 一个 Session 同一时间最多一个 HumanControlLease；
- 一个 Profile 的人工接管不暂停其他 Profile；
- lease 验证 Session、Profile、Tab、connection、generation；
- 人工输入只进入目标 Session 的 BrowserHost；
- 断线、过期、撤销、Host 崩溃和 Runtime 关闭时确定性合成输入释放；
- Agent observe 可按现有受保护规则继续；
- Agent 写操作只暂停目标 Session。

### 19.4 Control Center

Control Center 至少提供：

- Profile 列表；
- Profile owner / trust / Agent binding；
- Profile runtime 状态；
- 活动 Session 和 Agent；
- 启动/停止 Session；
- 打开目标 Session Monitor；
- 归档/删除 Profile；
- 后续 Profile Bootstrap 入口。

Monitor 窗口必须显示明确的 Profile alias 和 Session 标识，防止用户在错误账号上接管。

---

## 20. Failure Isolation and Recovery

### 20.1 Host crash

Session A Host 崩溃：

```text
mark Session failed/crashed
  -> stop new operations
  -> release HumanControlLease
  -> synthesize key/mouse release where possible
  -> close visual stream and Monitor connections
  -> revoke Session grants and leases
  -> clear route entries
  -> close worker resources
  -> release ProfileProcessLock after process exit is confirmed
```

Session B 必须继续运行。

### 20.2 Worker crash

Worker 线程异常退出不能导致 Supervisor 崩溃。Supervisor 标记对应 Session failed，执行同样的清理路径。

### 20.3 Runtime restart

- Profile Catalog 保留；
- Chromium user-data-dir 保留；
- 活动 Agent lease、HumanControlLease、Monitor Grant 和 Session continuation 不恢复；
- 遗留 Session 记录标为 interrupted；
- ProfileProcessLock 必须由 OS 锁状态确认；
- 用户或 Agent 后续启动同一 Profile 时创建新 Session generation；
- 登录状态可由持久 Profile 自然保留。

### 20.4 Partial startup failure

如果 Profile 锁成功但 Chromium 启动失败：

- Session 标为 crashed 或 failed；
- 关闭部分资源；
- 释放 Profile 锁；
- 不创建可路由 Tab；
- 返回无路径、无 Token 的确定性错误。

### 20.5 Capacity failure

达到活动 Profile/Chromium 资源上限时：

- 不随机终止其他 Session；
- 返回 `runtime_capacity_reached`；
- Control Center 可显示空闲 Session；
- 自动回收只允许针对无 Agent lease、无人类接管、无进行中操作的 idle Session；
- 数值默认值通过 P12 性能验证确定，不进入公共协议。

---

## 21. Default Profile Migration

当前路径：

```text
webfa-data/browser/managed-chromium-profile-default
```

P12 迁移目标：

```text
webfa-data/profiles/default/chromium-user-data
```

迁移要求：

1. Runtime 和 Chromium 必须完全停止；
2. 创建 `default` BrowserProfile catalog 记录；
3. 将现有 Profile policy 元数据写入持久化存储；
4. 在同一数据卷内优先使用原子 rename；
5. 写入可重复执行的 migration marker；
6. 目标已存在时不合并两个 Cookie 数据库；
7. 迁移失败时保留源目录并 fail closed；
8. 不把绝对路径写入 Agent 日志；
9. 迁移完成后真实验证已有登录状态仍可使用；
10. 保留 `default` alias 作为兼容入口，但新 Profile 使用 opaque ID。

迁移不能复制或导出 Cookie 内容到 WebFA 数据库。

---

## 22. Local Control Plane API

这些 API 不属于 Agent MCP。它们只允许 Electron Control Center 或明确受保护的本地管理调用。

建议：

```text
GET    /v1/control/profiles
POST   /v1/control/profiles
GET    /v1/control/profiles/{profile_id}
PATCH  /v1/control/profiles/{profile_id}
POST   /v1/control/profiles/{profile_id}/archive
DELETE /v1/control/profiles/{profile_id}

GET    /v1/control/sessions
POST   /v1/control/profiles/{profile_id}/sessions
POST   /v1/control/sessions/{session_id}/stop
GET    /v1/control/sessions/{session_id}
POST   /v1/control/sessions/{session_id}/monitor-grants
```

安全要求：

- 复用 Visualizer/Control Center 本地高权限 Token；
- Origin Lock；
- Electron IPC sender 校验；
- 不允许外部导航；
- 不返回 Cookie、存储值或 Profile 路径；
- 所有破坏性 Profile 操作需要本地明确确认；
- Agent caller headers 不能调用 control endpoints。

---

## 23. Profile Bootstrap Compatibility

P12 Core 预留：

```text
ProfileBootstrapService
ProfileMutationLease
ProfileMaintenanceHost
```

后续可支持：

- blank Profile；
- human login；
- Cookie import；
- Profile clone；
- restored WebFA Profile Bundle。

Cookie 导入目标流程：

```text
local user selects input
  -> parse in protected local process
  -> show redacted summary
  -> select inactive target Profile
  -> acquire ProfileMutationLease
  -> launch bounded Maintenance Host
  -> Storage.setCookies
  -> close Maintenance Host
  -> release lock
  -> start normal Session
  -> verify actual website auth state
```

导入只能声明：

```text
cookies_imported
```

不能直接声明：

```text
login_restored
```

Agent 不获得 Cookie 导入工具，也不能读取导入结果中的 Cookie 名称和值。

---

## 24. Code Migration Map

| Current | P12 target |
|---|---|
| application singleton `BrowserRuntime` | `BrowserRuntimeSupervisor` facade plus multiple `BrowserSessionRuntime` instances |
| `_BrowserWorker` | per-Session `SessionWorker` |
| `BrowserSession(session_id="default", profile_id="default")` | explicit Session model constructed from Profile and generation |
| global `_jobs` queue | one queue per SessionRuntime |
| global `_web_operation_lock` | connection sequencing plus per-Session operation lock |
| global `AgentLease` | per-Session `AgentSessionLeaseManager` |
| in-memory `ProfilePolicyStore` | persistent ProfileRepository projection plus Session evaluation |
| hard-coded `managed-chromium-profile-default` | `ProfileLaunchSpec.user_data_dir` |
| app state `browser_runtime` | app state `browser_runtime_supervisor` |
| single MonitorGateway | `MonitorGatewayRouter` plus Session gateways |
| single visual provider | per-Session `VisualStreamHub` |
| local `tab_1` style IDs | globally routed opaque Tab IDs |
| Session-local repeated WebObject IDs | Session/generation-bound opaque WebObject IDs |
| implicit default Session REST routing | AgentConnectionContext current-session routing |

Compatibility facade can temporarily preserve the class name `BrowserRuntime` for single-session tests, but no new public behavior may depend on that facade. It must delegate to the final Supervisor/Session model rather than maintain a second architecture.

---

## 25. Engineering Phases

### P12.0 Definition Freeze

- approve this document；
- freeze topology、对象模型、工具路由、锁顺序、生命周期和验收标准；
- no implementation behavior yet。

### P12.1 Schema and Profile Catalog

- BrowserProfile schemas；
- ProfileRepository；
- SQLite migrations；
- Profile CRUD local control API；
- agent_alias and visibility rules；
- persist P11 Profile policy metadata；
- unit and contract tests。

### P12.2 Profile Storage Isolation

- `ProfileLaunchSpec`；
- explicit per-Profile user-data-dir；
- ProfileProcessLock；
- ProfileStorageManager；
- default Profile migration；
- two persistent Profile real-Chromium isolation validation。

### P12.3 Session Runtime Extraction

- extract BrowserSessionRuntime；
- one worker/queue/registry/event bus/operation lock per Session；
- Session lifecycle and metadata persistence；
- isolate Host crash；
- preserve all single-session behavior through Supervisor。

### P12.4 Supervisor and Global Routing

- BrowserRuntimeSupervisor；
- SessionManager；
- AgentConnectionRegistry；
- GlobalRouteRegistry；
- global Tab and WebObject identity；
- multi-Profile concurrent execution tests。

### P12.5 Agent Grant and Five-Tool Integration

- MCP connection ID；
- AgentConnectionContext；
- AgentProfileGrant；
- AgentSessionLease；
- optional `profile_ref` on open_url；
- upgraded get_tabs response；
- cross-Session switch_tab；
- exact five-tool contract validation。

### P12.6 Monitor and Human Control Isolation

- MonitorGatewayRouter；
- per-Session Monitor grants；
- VisualStreamHub；
- multi-Session Control Center；
- independent HumanControlLease；
- frame/input/session cross-talk adversarial tests。

### P12.7 P11 Re-scoping and Security Review

- Profile/Connection/Session scope migration；
- Step-up replay protection；
- LocalResourceGrant replay protection；
- payment reference binding；
- Runtime generation validation；
- secret-free multi-Profile audit；
- adversarial review。

### P12.8 Core Final Acceptance

- full Python, contract, MCP, Electron and renderer validation；
- real multi-account Chromium scenarios；
- default Profile migration validation；
- crash and lease race review；
- documentation and maintenance review。

### Post-Core: Profile Bootstrap

- Cookie import；
- Profile clone；
- Profile bundle restore；
- maintenance locks and verification。

Profile Bootstrap consumes P12 Core and must not delay or reshape Core acceptance。

---

## 26. Test Strategy

### 26.1 Unit tests

- Profile schema validation；
- agent_alias uniqueness and visibility；
- Profile lifecycle transitions；
- Session lifecycle transitions；
- AgentProfileGrant；
- AgentSessionLease expiry and takeover；
- runtime generation mismatch；
- route registry；
- lock ordering and release；
- migration idempotency；
- secret redaction。

### 26.2 Integration tests

- two ProfileRuntime instances start concurrently；
- same Profile second startup fails closed；
- two Sessions have independent ObjectRegistry；
- connection current-session switching；
- cross-Session tab routing；
- Session A human takeover does not pause Session B；
- Session A crash does not close Session B；
- one Agent cannot use another Agent's Session lease；
- old generation grants are rejected；
- Monitor frame and input cannot cross Session boundary。

### 26.3 Real Chromium tests

At minimum：

1. Profile A and B visit same Origin；
2. each writes different Cookie, localStorage and IndexedDB values through test pages；
3. values remain isolated；
4. each Profile restarts and retains only its own persistent state；
5. both run concurrently；
6. closing one does not affect the other；
7. same Profile cannot be launched twice；
8. multi-Tab behavior remains inside one Profile/Session；
9. screencast and HumanControl target the correct Host。

### 26.4 Security contract tests

Verify Agent cannot obtain：

- Cookie values；
- storage values；
- authorization headers；
- Profile paths；
- local display names not marked Agent-visible；
- another Profile's tabs, objects, grants or receipts；
- HumanControl input values。

### 26.5 MCP contract tests

- default tools exactly five；
- open_url optional profile_ref only；
- no management or Cookie tools；
- connection ID is internal header, not model argument；
- current Session behavior deterministic；
- get_tabs only lists authorized contexts；
- cross-Session switch_tab works；
- profile/session busy errors are structured。

---

## 27. Core Acceptance Criteria

P12 Core 只有在以下全部成立时才算完成：

1. WebFA 可以创建至少两个持久 BrowserProfile；
2. 每个 Profile 使用独立 user-data-dir 和独立 ManagedChromiumHost；
3. 同一 Profile 不能被两个 Host 同时打开；
4. 不同 Profile 的 Cookie、localStorage、IndexedDB、Cache/Service Worker 状态和网站权限不存在已知串线；
5. 同一个网站可以在 Profile A 和 B 中保留不同登录身份；
6. 两个不同 Agent 可以并发使用两个不同 Profile；
7. 第二个 Agent 不能绕过 lease 控制已被占用的 Session；
8. 一个 Agent connection 可以在已授权 Profile 的 Session 间切换；
9. `get_tabs` 和 `switch_tab` 能正确跨 Session 路由；
10. Tab ID 和 WebObject ID 不会跨 Session 错配；
11. Session A 的 Step-up、资源授权、支付授权和 Monitor Grant 不能在 Session B 重放；
12. HumanControlLease A 只暂停和控制 Session A；
13. Session A 崩溃不影响 Session B；
14. Runtime 重启后 Profile 登录状态仍可保留；
15. Runtime 重启后旧活动 Session 被标记 interrupted，而不是伪恢复；
16. Agent 永远看不到 Cookie、存储、Token、密码、Profile 路径或人类输入；
17. 默认 MCP 工具仍严格是五个；
18. P10 WebObjects 和语义操作仍是唯一 Agent 页面操作模型；
19. UI-1B Monitor 仍然只是同一 Host 的 projection；
20. 旧 default Profile 可以安全迁移且登录状态不被无故丢失；
21. 多 Session 下所有关键清理、租约过期和崩溃路径确定性通过；
22. Cookie 导入尚未实现时，P12 Core 仍能独立满足以上标准。

---

## 28. Hard Security Invariants

1. Agent 不能直接指定或读取 user-data-dir。
2. Agent 不能读取、导出或修改原始 Cookie/Storage。
3. Agent 不能通过管理 API 创建、删除、克隆或导入 Profile。
4. Profile 选择必须经过 ProfilePolicy 和 AgentProfileGrant。
5. Session 运行期间 Profile 不可改变。
6. 同一 Profile 同时最多一个活动可写 Session。
7. 同一 Session 同时最多一个 Agent 写 lease 和一个 HumanControlLease；二者按既有规则互斥。
8. Monitor 永远不创建目标网页副本。
9. 所有授权对象必须绑定 Session、Profile 和 runtime generation。
10. 旧 Session 引用不能在新 generation 中重新生效。
11. 单 Session 故障不能升级为全局 Runtime 故障。
12. 管理面和 Agent 面必须保持不同鉴权与路由。
13. Profile 锁不能仅依赖内存或 PID 文本文件。
14. 删除或维护 Profile 时必须没有活动 Session。
15. 所有 Agent-visible 错误保持 secret-free 和 path-free。

---

## 29. External Technical Basis

P12 的底层拓扑依据以下 Chromium/CDP 行为：

- Chromium user data directory 存储历史、书签、Cookie 和其他本地状态；每个 Chrome Profile 是该目录下的子目录；`--user-data-dir` 可以显式覆盖目录；两个运行中的 Chrome 实例不能共享同一个 user data directory：
  https://chromium.googlesource.com/chromium/src/+/main/docs/user_data_dir.md
- CDP `Target.createBrowserContext` 创建新的空 BrowserContext，官方描述为类似 incognito Profile，并支持在创建 Target 时指定 `browserContextId`。这适合未来临时隔离，但不改变 P12 持久 Profile 使用独立 user-data-dir 的冻结决策：
  https://chromedevtools.github.io/devtools-protocol/tot/Target/
- CDP Storage domain 提供按 BrowserContext 操作 Cookie 和存储的底层能力，可被未来受保护的 Profile Bootstrap 使用，但不进入 Agent 公共协议：
  https://chromedevtools.github.io/devtools-protocol/tot/Storage/

这些协议均是 BrowserHost 内部实现细节，不是 WebFA Agent 产品模型。

---

## Decision Summary

P12 的最终模型是：

```text
BrowserProfile
  = durable internet identity and browser storage

BrowserSession
  = active task runtime bound to one Profile

BrowserRuntimeSupervisor
  = routes Agents, Profiles, Sessions and Monitors

BrowserSessionRuntime
  = owns WebObjects, operations, events, safety state and one real Host
```

冻结拓扑：

```text
one active persistent Profile
  -> one dedicated user-data-dir
  -> one dedicated ManagedChromiumHost
  -> at most one active writable BrowserSession
  -> multiple Tabs

multiple different Profiles
  -> may run concurrently
```

治理原则：

> Profile 隔离互联网身份，Session 隔离任务运行状态，Lease 隔离控制权，runtime generation 隔离时间上的旧权限，Monitor 只投影同一个真实页面。WebFA 在此基础上让 Agent 像真正的互联网用户一样安全地使用多个账号和多个互联网环境，而不会退化为传统浏览器多开或原始自动化接口。
