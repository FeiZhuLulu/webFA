# WebFA P11 详细实施方案

Status: approved plan; implementation not started

Phase name:

```text
P11 Agent Safety Contract & Hard Boundaries
Agent 安全契约与硬边界
```

本方案冻结以下三项产品决策：

1. `trusted_agent` 作为默认信任模式。
2. Agent 自有 Profile 中的 `unknown_external_effect` 默认 `allow_with_audit`。
3. 第一阶段支付后端优先采用“商户已保存支付方式 + 系统/令牌化支付”，暂不以本地原始银行卡 Vault 为主路径。

P11 不把 WebFA 变成一个内置 LLM 的审批 Agent。WebFA 仍然不读取或解释用户与 Agent 的自然语言对话，也不判断用户的真实意图。P11 建立一套确定性安全协议：Agent 负责理解用户授权，WebFA 返回通用安全义务，Agent 对义务作出声明，WebFA 只执行自身能够机械判断的硬边界。

---

## 1. 目标

P10 解决：

```text
Agent 如何通过 WebObjects 理解和操作真实网页？
```

P11 解决：

```text
Agent 如何在真实互联网中自由行动，同时获得一致的安全提醒，并遵守少量可强制执行的用户边界？
```

目标链路：

```text
User instruction in Agent layer
  -> SafetyDeclaration
  -> SafetyTemplateRegistry
  -> SafetyContract
  -> AgentAssertions
  -> HardBoundaryEngine
  -> Semantic WebOperation
  -> SafetyReceipt
```

P11 必须满足：

- 不为淘宝、京东、亚马逊等网站维护不同购买流程白名单；
- 不为 Gmail、GitHub、社交平台维护站点专用审批脚本；
- 不增加默认 MCP 工具数量；
- 不让 WebFA 解释用户自然语言；
- 默认路径保持 Agent 自主，而不是强制二次审批；
- 高风险凭据、认证、支付验证、本地文件和资金额度由 WebFA 硬性守边界。

---

## 2. 核心原则

### 2.1 用户授权发生在 Agent 层

用户在对话中告诉 Agent：

```text
帮我在淘宝购买 A 商品，最多 300 元，并完成支付。
```

Agent 负责理解：

- 用户是否明确授权购买；
- 用户是否明确授权支付；
- 金额、数量和对象范围；
- 是否允许订阅、自动续费或转账；
- 应使用 Agent 账号还是用户账号。

WebFA 不重复理解这段话。

### 2.2 WebFA 返回安全义务，不返回业务判断

Agent 声明任务涉及：

```text
identity_context
financial_commitment
```

WebFA 返回：

```text
必须确认用户明确授权购买；
必须确认用户明确授权支付；
必须确认实际金额未超范围；
必须确认没有未授权的周期性扣费。
```

这些义务同时以两种形式返回：

- 给 Agent 阅读的自然语言提示；
- 机器可读的 assertion 列表。

### 2.3 默认信任 Agent 的声明

默认：

```text
trust_mode = trusted_agent
```

Agent 可以声明用户已经明确授权。WebFA 记录该声明，但不在 UI 中重复弹出“是否确定”。

这是显式信任模型，不是对 Agent 理解正确性的证明。

### 2.4 WebFA 只执行确定性硬边界

硬边界必须满足两个条件：

1. 不需要 LLM；
2. Runtime 能机械判断或由用户预配置。

包括：

- 凭据不可泄露；
- 密码、2FA、CAPTCHA、生物识别和支付挑战必须 Human Takeover；
- Profile 与 Agent 绑定；
- 本地文件只能通过 Resource Broker；
- 用户自定义资金额度；
- 周期性承诺单独授权；
- PaymentInstrument 以受保护引用使用；
- 明确 deny policy。

### 2.5 不维护站点操作列表

禁止把安全规则建模为：

```text
淘宝点击“提交订单”前审批
京东点击“去支付”前审批
亚马逊点击“Place order”前审批
```

P11 只统一风险维度和硬边界。具体网站流程继续由 Agent 根据 P10 WebObjects 自主完成。

### 2.6 默认 MCP 保持五个工具

```text
webfa.open_url
webfa.observe
webfa.act
webfa.get_tabs
webfa.switch_tab
```

禁止增加默认：

```text
webfa.approve
webfa.pay
webfa.authorize
```

P11 通过现有请求和响应 envelope 承载 SafetyContext。

---

## 3. 责任边界

### 3.1 User

用户负责：

- 在 Agent 对话中授权任务；
- 配置长期 WebFA 硬边界；
- 选择 Agent/Profile/支付工具/文件资源；
- 完成人类专属认证和支付验证；
- 为信任的 Agent 选择宽松策略。

### 3.2 Agent

Agent 负责：

- 理解用户自然语言；
- 选择网站与执行路径；
- 声明任务安全维度；
- 阅读 WebFA 返回的安全合同；
- 判断 assertion 是否成立；
- 无法确定时停止并询问用户；
- 对任务语义和业务判断负责。

### 3.3 Agent Host

Agent Host 可选提供更高 assurance：

- agent_id；
- conversation_id/task_id；
- user_turn_ref；
- 时间戳与有效期；
- 本地 attestation 或签名。

P11 不要求所有客户端必须具备签名能力。

### 3.4 Web content

网页内容一律是 `untrusted`，不能：

- 授予 Agent 新权限；
- 修改 SafetyContext；
- 满足 assertion；
- 索取支付秘密；
- 扩大本地文件访问；
- 提高资金额度；
- 改变 Profile 所有权。

### 3.5 WebFA Runtime

WebFA 负责：

- SafetyTemplateRegistry；
- SafetyContext 生命周期；
- HardBoundaryEngine；
- 凭据、支付和文件 Broker；
- Agent/Profile/origin 绑定；
- secret-free receipt。

---

## 4. 总体架构

```text
Agent / Agent Host
  |
  | SafetyDeclaration + WebOperation
  v
SafetyContextManager
  |
  +--> SafetyTemplateRegistry
  |
  +--> RuntimeEvidenceResolver
  |
  +--> HardBoundaryEngine
  |
  +--> Protected Resource Brokers
  |      CredentialBroker
  |      PaymentInstrumentBroker
  |      LocalResourceBroker
  |
  +--> SafetyDecision
  v
SemanticOperationExecutor
  v
SafetyReceiptStore
```

### 4.1 SafetyContextManager

维护任务级安全状态，绑定：

```text
runtime_session_id
agent_id
profile_id
origin_scope
created_at
expires_at
max_uses
```

职责：

- 接收 declaration；
- 生成 contract；
- 接收 assertions；
- 跟踪 pending obligations；
- 失效和消费 context；
- 向 WebState 输出 compact safety projection。

### 4.2 SafetyTemplateRegistry

版本化、确定性、站点无关。

模板不得包含：

- selector；
- XPath；
- URL path；
- 按钮文本；
- 站点专用操作顺序。

### 4.3 RuntimeEvidenceResolver

从 P10 与 BrowserHost 收集机械证据：

- origin/frame origin；
- P10 capability effect；
- form / submit-control relation；
- upload target；
- password / protected field；
- Payment Request；
- Secure Payment Confirmation；
- WebAuthn challenge；
- card autocomplete metadata；
- 当前 Profile 与 owner；
- resource_ref；
- 可可靠观察的金额和币种。

它不能推断任意业务语义。

### 4.4 HardBoundaryEngine

输入：

```text
SafetyContext
AgentAssertions
RuntimeEvidence
ProfilePolicy
FinancialPolicy
ResourceGrants
```

输出：

```text
inform
require_assertion
allow
allow_with_audit
require_step_up
require_takeover
deny
```

### 4.5 Protected Resource Brokers

Agent 只接触 opaque reference，不接触底层秘密。

---

## 5. 安全维度

完整公共 Schema 一次定义八个维度。首批工程优先实现前三个，但不得设计成临时模型。

### 5.1 `identity_context`

```text
account_owner:
  agent_owned
  user_owned
  shared
  unknown

action:
  use_existing_account
  sign_in
  switch_account
  create_account
  authorize_third_party
```

常见 assertions：

```text
current_identity_matches_task
user_authorized_use_of_user_identity
no_unapproved_identity_switch
```

硬边界：

- 凭据不返回 Agent；
- 认证挑战 Human Takeover；
- Profile 切换满足绑定策略。

### 5.2 `financial_commitment`

```text
kind:
  one_time_purchase
  transfer
  refund
  bid
  donation
  paid_service
  cash_equivalent
  unknown_financial_commitment
```

字段：

```text
currency
estimated_amount
maximum_amount
merchant
item_summary
quantity
payment_instrument_ref
```

Assertions：

```text
user_explicitly_authorized_purchase
user_explicitly_authorized_payment
actual_amount_within_authorized_scope
merchant_and_subject_match_task
```

硬边界：

- PaymentInstrument policy；
- 用户定义金额限制；
- 支付验证 Human Takeover；
- transfer/cash equivalent 默认关闭。

### 5.3 `local_data_egress`

描述本地或用户控制的数据离开设备：

```text
source_owner
resource_refs
destination_origin
purpose
```

Assertions：

```text
user_authorized_specific_resources
user_authorized_destination
resource_use_matches_task
```

硬边界：

- upload 只接受 LocalResourceBroker reference；
- 拒绝任意 raw path；
- 执行 origin、用途、有效期和次数限制。

### 5.4 `external_representation`

```text
kind:
  email
  direct_message
  public_post
  comment
  application
  form_submission
  support_request
  legal_or_policy_acknowledgement
```

Assertions：

```text
user_authorized_external_communication
identity_and_audience_match_task
content_or_subject_is_within_scope
```

Agent 自有通信账号默认可宽松配置。

### 5.5 `destructive_change`

```text
resource_owner
resource_ref
reversible
recovery_window
```

Assertions：

```text
user_authorized_destructive_effect
resource_matches_task
recovery_expectation_is_understood
```

Agent 自有临时资源可默认 `allow_with_audit`。

### 5.6 `authority_change`

```text
kind:
  add_member
  change_role
  grant_admin
  create_credential
  authorize_application
  change_security_setting
  change_recovery_method
  make_public
```

Assertions：

```text
user_authorized_authority_change
new_principal_and_scope_match_task
```

账号恢复方式、凭据创建等可要求 step-up 或 takeover。

### 5.7 `recurring_commitment`

```text
kind:
  subscription
  automatic_renewal
  installment_plan
  recurring_donation
  recurring_service

interval
amount_per_interval
minimum_term
cancellation_terms_known
```

一次性购买永远不能自动授权周期性承诺。

Assertions：

```text
user_explicitly_authorized_recurring_commitment
interval_and_amount_match_scope
cancellation_terms_are_within_scope
```

### 5.8 `unknown_external_effect`

WebFA 知道操作改变外部世界，但无法可靠分类时使用。

冻结默认：

```text
agent_owned profile -> allow_with_audit
shared profile -> require_assertion
user_owned protected profile -> require_step_up
```

未知不等于禁止。

---

## 6. 与 P10 CapabilityEffect 的关系

P10 effect 保持底层最小效果：

```text
read
navigation
local_state_change
external_write
external_send
download
upload
destructive
permission_change
unknown
```

P11 safety dimensions 是独立层，不向 P10 enum 塞入 purchase、subscription 等业务语义。

示例：

```text
P10 operation: activate
P10 effect: external_write
Agent declaration: financial_commitment(one_time_purchase)
Runtime evidence: payment surface + CNY 279
Effective dimensions: identity_context + financial_commitment
```

有效维度：

```text
declared dimensions
UNION runtime-detected dimensions
UNION profile-policy-required dimensions
```

Runtime 可以增加风险维度，不能静默删除 Agent 已声明风险。

---

## 7. Agent Safety Handshake

### 7.1 Declaration

```json
{
  "principal": {
    "agent_id": "shopping-agent",
    "profile_id": "profile-agent-shopping",
    "account_owner": "agent_owned"
  },
  "task": {
    "intent": "purchase_product",
    "subject": "A商品"
  },
  "dimensions": [
    {
      "type": "identity_context",
      "account_owner": "agent_owned",
      "action": "use_existing_account"
    },
    {
      "type": "financial_commitment",
      "kind": "one_time_purchase",
      "currency": "CNY",
      "maximum_amount": "300.00",
      "quantity": 1
    }
  ],
  "authorization_claim": {
    "status": "explicit",
    "source_ref": "user_turn_42"
  },
  "expires_in_seconds": 3600,
  "max_uses": 1
}
```

`intent` 和 `subject` 用于记录与提示，不由 WebFA 语义验证。

### 7.2 Contract

```json
{
  "context_id": "sctx_01",
  "status": "assertion_required",
  "templates": [
    "identity_context.v1",
    "financial_commitment.v1"
  ],
  "required_assertions": [
    "current_identity_matches_task",
    "user_explicitly_authorized_purchase",
    "user_explicitly_authorized_payment",
    "actual_amount_within_authorized_scope",
    "no_unapproved_recurring_commitment"
  ],
  "hard_boundaries": [
    "credential_secrecy",
    "financial_policy",
    "payment_challenge_takeover"
  ],
  "instruction": "该任务涉及真实身份和资金承诺……"
}
```

### 7.3 Assertions

```json
{
  "context_id": "sctx_01",
  "assertions": {
    "current_identity_matches_task": true,
    "user_explicitly_authorized_purchase": true,
    "user_explicitly_authorized_payment": true,
    "actual_amount_within_authorized_scope": true,
    "no_unapproved_recurring_commitment": true
  },
  "authorization_source": "user_turn_42"
}
```

缺失或为 false 的 assertion 保持 pending。Agent 应停止并询问用户。

### 7.4 Operation reference

```json
{
  "target": "obj_confirm_order",
  "operation": "activate",
  "safety": {
    "context_id": "sctx_01"
  }
}
```

### 7.5 Fast path

在 `trusted_agent` 模式下，Agent 可一次提交 declaration + assertions。WebFA 内部仍生成同一份 contract，并返回结果和 receipt，避免额外往返。

### 7.6 Context invalidation

以下变化必须重新计算：

- agent_id 变化；
- profile_id 变化；
- account_owner 变化；
- origin 超出 scope；
- 金额或币种变化；
- 新增 recurring commitment；
- 新增本地资源；
- 过期；
- 次数耗尽；
- Runtime 发现新的硬边界。

---

## 8. 生命周期

```text
undeclared
  -> assertion_required
  -> ready
  -> operation_allowed
  -> active / partially_consumed
  -> consumed / expired

assertion_required
  -> step_up_required
  -> takeover_required
  -> blocked
```

状态：

```text
undeclared
assertion_required
ready
step_up_required
takeover_required
blocked
consumed
expired
```

决策：

```text
inform
require_assertion
allow
allow_with_audit
require_step_up
require_takeover
deny
```

正常自主路径应主要落在 `allow_with_audit`。

---

## 9. 公共协议

### 9.1 `webfa.open_url`

可选接受初始 declaration：

```json
{
  "url": "https://example.com",
  "safety": {
    "declaration": {}
  }
}
```

### 9.2 `webfa.act`

接受：

```text
safety.declaration
safety.assertions
safety.context_id
```

风险操作缺少安全状态时不执行，返回缺失 contract 或 boundary。

### 9.3 `webfa.observe`

保持只读，返回当前 safety projection：

```json
{
  "safety": {
    "context_id": "sctx_01",
    "status": "ready",
    "active_dimensions": [
      "identity_context",
      "financial_commitment"
    ],
    "pending_assertions": [],
    "hard_boundary": null
  }
}
```

### 9.4 `WebOperationRequest`

扩展目标：

```text
target
operation
arguments
expected_object_version
expected_document_revision
safety
```

禁止通用 `approve=true`。授权必须是 typed、scoped、expiring、auditable。

---

## 10. Schema 目标

### 10.1 Principal

```text
SafetyPrincipalRef
  agent_id
  profile_id
  account_owner
```

### 10.2 Declaration

```text
SafetyDeclaration
  principal
  task
  dimensions[]
  authorization_claim
  origin_scope[]
  expires_at / expires_in_seconds
  max_uses
```

### 10.3 Contract

```text
SafetyContract
  context_id
  template_versions[]
  required_assertions[]
  instruction
  hard_boundaries[]
  status
```

### 10.4 Assertions

```text
SafetyAssertionSet
  context_id
  assertions: map<string, boolean>
  authorization_source
  host_attestation?
```

### 10.5 State

```text
SafetyContextState
  context_id
  principal
  active_dimensions[]
  status
  pending_assertions[]
  expires_at
  remaining_uses
  last_decision
```

### 10.6 Receipt

```text
SafetyReceipt
  receipt_id
  context_id
  agent_id
  profile_id
  origin
  target_object_id
  operation
  p10_effect
  safety_dimensions[]
  assertion_refs[]
  hard_boundary_decision
  final_decision
  before_revision
  after_revision
  result
  timestamp
```

Receipt 绝不能包含：

- 密码；
- Cookie；
- Token；
- 完整卡号；
- CVV；
- 支付密码；
- 2FA 内容；
- 任意本地绝对路径。

---

## 11. 硬边界

### 11.1 Credential secrecy

不得进入 Agent-visible state、MCP、日志、receipt、Agent 可读截图：

- password；
- cookies；
- auth token；
- session storage secret；
- 2FA seed/recovery code；
- payment password；
- CVV；
- bank authentication material；
- private key。

Agent 只能通过 reference 使用绑定身份或资源。

### 11.2 Human authentication and verification

以下必须 Human Takeover：

- 用户或受保护账号密码；
- SMS/Authenticator 2FA；
- CAPTCHA；
- 生物识别；
- Security Key touch/PIN；
- QR 登录；
- 账号恢复；
- 3-D Secure；
- 银行 App 确认；
- 支付密码。

Takeover 是完成认证，不是重复判断用户是否授权任务。

### 11.3 Profile/identity boundary

每个 Profile 定义：

```text
profile_id
owner
bound_agent_ids
allowed_origins
safety_policy_id
financial_policy_id
```

P11 先实现绑定元数据与基础检查，P12 实现完整多 Profile 隔离。

Agent 不得静默从 Agent Profile 切换到用户 Profile。

### 11.4 Local resource boundary

上传必须使用：

```text
LocalResourceGrant
  resource_ref
  owner
  purpose
  allowed_origins
  expires_at
  max_uses
```

公共 Agent 协议拒绝 raw local path。

### 11.5 Financial boundary

由用户配置：

```text
autonomy_limit
step_up_limit
absolute_limit
daily_limit
monthly_limit
currency rules
transaction types
recurring policy
assurance requirement
```

WebFA 不硬编码“大额”的统一数值。

### 11.6 Recurring boundary

一次性购买不能覆盖：

```text
subscription
automatic renewal
installment
recurring donation
```

### 11.7 Explicit deny policy

用户可明确关闭：

```text
transfers
cash equivalents
subscriptions
production deletion
credential creation
external file upload
```

P11 不内置统一道德/业务审查。

---

## 12. 支付架构

### 12.1 产品模型

WebFA 支持受保护支付工具，使 Agent 能完成低风险真实购买。

```text
Agent chooses PaymentInstrumentRef
PaymentInstrumentBroker verifies policy
Broker activates or supplies instrument internally
Agent never receives payment secrets
```

### 12.2 Payment instrument types

完整目标：

```text
merchant_saved
system_wallet
tokenized_wallet
issuer_virtual_card
prepaid_card_reference
local_protected_card
```

冻结的第一阶段顺序：

1. `merchant_saved`；
2. `system_wallet` / `tokenized_wallet`；
3. `issuer_virtual_card`；
4. `local_protected_card` 仅在独立安全评审后考虑。

### 12.3 PaymentInstrumentRef

Agent-visible projection：

```json
{
  "instrument_id": "pay_agent_01",
  "owner": "agent",
  "profile_id": "profile-agent-shopping",
  "type": "issuer_virtual_card",
  "brand": "visa",
  "last4": "4821",
  "currency": "CNY",
  "policy_id": "financial-policy-01"
}
```

禁止返回：

- full PAN；
- CVV；
- payment password；
- wallet token；
- OTP；
- bank secret。

### 12.4 Protected capability

定义受保护语义能力：

```text
provide_payment_instrument
```

区别：

```text
set_value:
  Agent 知道并提交值

provide_payment_instrument:
  Agent 只提交 instrument_id
  WebFA/Provider 内部处理秘密
```

支付秘密字段不得向 Agent 暴露普通 `set_value`。

### 12.5 FinancialPolicy

```json
{
  "policy_id": "financial-policy-01",
  "currency": "CNY",
  "one_time_purchase": {
    "autonomy_limit": "300.00",
    "step_up_limit": "2000.00",
    "absolute_limit": "10000.00"
  },
  "daily_limit": "1000.00",
  "monthly_limit": "3000.00",
  "subscriptions_allowed": false,
  "transfers_allowed": false,
  "cash_equivalents_allowed": false,
  "minimum_assurance": "runtime_observed"
}
```

这些数字只是示例，实际由用户配置。

### 12.6 Assurance levels

```text
agent_asserted
runtime_observed
provider_verified
user_confirmed
```

建议：

```text
Agent 自有小额卡：agent_asserted 可接受
用户支付工具：至少 runtime_observed
大额交易：provider_verified 或 user_confirmed
```

### 12.7 Financial decision

```text
actual <= autonomy_limit
+ assertions valid
+ instrument/profile match
+ no recurring commitment
+ no payment challenge
  -> allow_with_audit

actual > autonomy_limit
and actual <= step_up_limit
  -> require_step_up

actual > absolute_limit
  -> deny

payment verification challenge
  -> require_takeover
```

### 12.8 卡片存储原则

第一阶段不以“WebFA 保存完整银行卡”为目标。

推荐：

- 商户账号已保存支付方式；
- 系统钱包；
- 令牌化钱包；
- 发卡方虚拟卡引用；
- 小额预付卡引用。

未来本地保护卡片后端必须：

- 运行在隔离 Broker；
- 使用 OS 受保护存储；
- 不持久化 CVV；
- 不持久化支付密码；
- 不持久化 OTP；
- 不暴露给 Agent；
- 通过独立威胁建模和安全审计。

### 12.9 用户手册要求

必须明确建议：

- 使用 Agent 专用虚拟卡或预付卡；
- 使用低额度；
- 开启即时交易通知；
- 默认禁止自动续费；
- 默认禁止转账和现金等价物；
- 不使用工资卡或高额度主信用卡。

风险提示不能替代架构限制。

---

## 13. Local Resource Broker

### 13.1 注册资源

```json
{
  "resource_ref": "file_approved_01",
  "display_name": "resume.pdf",
  "owner": "user",
  "purpose": "job_application",
  "allowed_origins": ["https://jobs.example.com"],
  "max_uses": 1
}
```

### 13.2 Agent surface

Agent 只看到 metadata 和 opaque ref，不看到无限制文件系统路径。

### 13.3 Upload

`upload` 接受 `resource_ref`。Broker 检查：

- agent；
- profile；
- destination origin；
- purpose；
- expiry；
- remaining uses。

### 13.4 内容检查

P11 不要求 WebFA 用 LLM 理解文件内容。后续可增加 malware scan/classification，但不改变 grant 模型。

---

## 14. 确定性决策规则

### 14.1 软合同

```text
无相关维度
  -> allow

有相关维度但 assertions 缺失
  -> require_assertion

assertions 完整且无硬边界
  -> allow_with_audit
```

### 14.2 硬边界

```text
auth/payment challenge
  -> require_takeover

amount > autonomy and <= step_up
  -> require_step_up

amount > absolute
  -> deny

unapproved resource/origin
  -> deny

profile ownership mismatch
  -> require_step_up or deny
```

### 14.3 不确定 evidence

WebFA 不得把不确定证据伪装成 verified。

Policy 选择最低 assurance：

```text
agent_asserted
runtime_observed
provider_verified
user_confirmed
```

Agent-owned Profile 默认允许更宽松策略。

---

## 15. UI 设计

P11 UI 是策略、step-up 和 takeover 界面，不是审批队列。

### 15.1 Agent identity policy

配置：

- agent_id；
- bound profiles；
- account ownership；
- optional allowed origins；
- trust mode；
- unknown effect policy。

### 15.2 Payment instruments

只显示安全 metadata：

```text
Visa •••• 4821
Owner: shopping-agent
Autonomy limit: CNY 300
Daily: CNY 279 / 1000
Monthly: CNY 1279 / 3000
Subscriptions: blocked
```

### 15.3 Resource grants

用户选择文件或目录，生成 scoped reference。

### 15.4 Step-up card

仅在范围扩大时出现：

```text
原自主额度：CNY 300
当前订单：CNY 329
请求：仅本次提升至 CNY 329
```

不是再次问“是否确定购买”。

### 15.5 Human Takeover

用于：

- password；
- 2FA；
- CAPTCHA；
- biometric；
- payment challenge；
- account recovery。

### 15.6 Activity/receipt

显示：

- Agent；
- Profile/identity；
- origin；
- operation；
- safety dimensions；
- authority source ref；
- boundary decision；
- outcome。

---

## 16. Trust Modes

### 16.1 `trusted_agent`

冻结为默认模式：

```text
Agent assertion accepted
Hard boundaries enforced
No duplicate WebFA approval
```

### 16.2 `host_attested`

Host 将 assertions 绑定到 conversation/task，并保护声明完整性。

### 16.3 `guarded`

指定风险维度或 Profile 即使 Agent 声明，也要求 WebFA step-up。

由用户主动选择，不全局强制。

---

## 17. 默认策略

### 17.1 全局默认

```text
trust_mode = trusted_agent
```

### 17.2 Agent-owned Profile

```text
external_representation -> allow_with_audit
unknown_external_effect -> allow_with_audit
financial_commitment -> assertion + financial policy
recurring_commitment -> separate assertion + explicit policy
```

### 17.3 User-owned Profile

```text
external_representation -> assertion + audit
unknown_external_effect -> step_up
financial_commitment -> assertion + stronger assurance
identity switch -> step_up
```

### 17.4 Payment default

```text
subscriptions = disabled
transfers = disabled
cash_equivalents = disabled
payment challenge = Human Takeover
autonomy limit = user configured
```

### 17.5 Local resource default

```text
public Agent protocol accepts resource_ref only
raw filesystem path rejected
```

---

## 18. 威胁模型

P11 处理：

- 网页通过 prompt injection 扩大权限；
- 使用错误 Profile；
- 上传未授权文件；
- 超额度支付；
- 隐藏订阅；
- secret 泄露；
- Agent 穿过 human-only challenge；
- 支付工具无限使用。

P11 不完全防止：

- trusted Agent 错误理解用户；
- malicious Agent 在 trusted 模式撒谎；
- 无可靠证据时商户误导商品或金额；
- 银行、卡组织、商户层面的欺诈和争议；
- 用户主动配置过于宽松的策略。

这些限制必须在文档中明确。

---

## 19. 非目标

P11 不做：

- 内置 LLM；
- 解析完整用户对话；
- 站点专用购买脚本；
- 内容质量或社交适当性判断；
- 通用欺诈检测；
- 绕过认证、支付验证、CAPTCHA 或平台风控；
- 向 Agent 暴露支付/身份秘密；
- 替代 P12 多 Profile；
- 替代 P13 持久 Trace；
- 站点专用事务 API wrapper。

---

## 20. 工程阶段

### P11.0 Definition Freeze

状态：完成。

冻结：

- 目标模型；
- 八类安全维度；
- 生命周期；
- decision enum；
- 五工具集成；
- trusted_agent 默认；
- Agent-owned unknown effect 默认 allow_with_audit；
- 支付首批后端方向。

### P11.1 Schema Foundation

新增完整 Schema：

- SafetyDimension union；
- SafetyDeclaration；
- SafetyContract；
- SafetyAssertionSet；
- SafetyContextState；
- SafetyDecision；
- SafetyReceipt；
- ProfileOwnershipMetadata；
- FinancialPolicy；
- PaymentInstrumentRef；
- LocalResourceGrant。

本阶段不实现 policy behavior。

验收：

- strict schema；
- discriminated union；
- JSON schema/MCP schema 稳定；
- 完整目标模型一次定义。

### P11.2 Template Registry & Contract Compiler

实现：

- 版本化模板注册表；
- machine-readable assertions；
- localized instruction；
- 模板组合；
- deterministic contract compiler。

验收：

- 不包含站点流程；
- 相同 financial template 可用于不同购物网站；
- contract 输出稳定可测试。

### P11.3 SafetyContext Handshake

实现：

- SafetyContextManager；
- declaration/assertion envelope；
- WebState safety projection；
- trusted fast path；
- expiry/max uses；
- invalidation。

验收：

- 默认五 MCP tools 不变；
- 已授权任务不触发重复 UI 审批；
- Context 与 agent/profile/origin 绑定。

### P11.4 Runtime Evidence & Mismatch Detection

实现：

- P10 effects 到最低风险维度映射；
- upload/protected credential/identity/payment surface 检测；
- declaration incomplete；
- effect mismatch；
- assurance metadata。

验收：

- Runtime 只能增加风险，不能降低声明风险；
- 不进行任意业务推理；
- 不确定 evidence 明确标记。

### P11.5 Credential & Human Takeover Boundary

实现：

- protected-field handling；
- password/2FA/CAPTCHA/biometric/payment challenge takeover；
- secret redaction；
- screenshot/log/receipt 检查。

验收：

- secret 不进入 WebState、MCP、日志、receipt；
- takeover 后通过 observe 恢复。

### P11.6 Local Resource Broker

实现：

- opaque resource refs；
- origin/purpose/expiry/use-count；
- upload 只接受 resource_ref；
- Visualizer resource grant UI。

验收：

- raw local path 被拒绝；
- 跨 origin 使用被拒绝；
- resource receipt 不暴露绝对路径。

### P11.7 Identity & Profile Policy

实现：

- profile owner；
- agent/profile binding；
- identity switch boundary；
- trust mode policy；
- unknown effect policy。

验收：

- Agent-owned unknown effect 默认 allow_with_audit；
- user-owned identity switch 默认 step-up；
- 与 P12 兼容。

### P11.8 Financial Policy & Payment Instrument Contract

实现：

- autonomy/step-up/absolute/daily/monthly limits；
- recurring/transfer/cash-equivalent policy；
- assurance levels；
- PaymentInstrumentRef；
- PaymentInstrumentBroker interface；
- provide_payment_instrument protected capability。

验收：

- 无 raw-card requirement；
- 金额由用户配置；
- 一次性购买不覆盖 subscription；
- receipt 不含支付秘密。

### P11.9 Payment Backend MVP

暂定实现：

1. merchant-saved payment method selection；
2. system/tokenized payment path；
3. payment challenge takeover；
4. Runtime 可观察金额时执行 policy；
5. secret-free payment receipt。

本阶段不要求：

- 完整本地 card vault；
- 覆盖所有支付平台；
- 自动绕过 3DS/银行验证。

### P11.10 Step-up UI, Audit & Final Acceptance

实现：

- boundary escalation card；
- policy pages；
- payment instrument UI；
- receipt viewer；
- real-task regression；
- docs/manual；
- migration cleanup。

---

## 21. 测试策略

### 21.1 Schema tests

- strict extra forbid；
- discriminated SafetyDimension；
- financial decimal/currency validation；
- expiry/max uses；
- invalid assertion key；
- secret field prohibition。

### 21.2 Template tests

- 单维度；
- 多维度组合；
- 模板版本；
- localized instruction；
- 不含站点字符串。

### 21.3 Context tests

- declare -> assert -> ready；
- fast path；
- expiry；
- use count；
- origin invalidation；
- profile invalidation；
- recurring dimension elevation。

### 21.4 Hard-boundary tests

- password takeover；
- 2FA takeover；
- payment challenge takeover；
- biometric takeover；
- raw path deny；
- wrong profile deny/step-up；
- amount autonomy/step-up/absolute；
- hidden recurring commitment。

### 21.5 Secret leakage tests

扫描：

- WebState；
- MCP response；
- REST response；
- logs；
- SafetyReceipt；
- Visualizer Agent projection；
- exception strings。

### 21.6 Real-browser tests

至少验证：

- 两种不同结构的模拟购物流程使用同一 financial template；
- Agent-owned 低金额直接 allow_with_audit；
- 超自主额度 step-up；
- 支付 challenge takeover；
- 本地资源 grant；
- external representation；
- unknown external effect policy。

### 21.7 Regression

P10 全部测试必须继续通过：

- WebObjects；
- Queryable Observe；
- Semantic Operations；
- ChangeSets；
- Opaque Takeover；
- five-tool MCP contract。

---

## 22. 最终验收标准

P11 只有同时满足以下条件才算完成：

1. WebFA 无 LLM，不解析用户对话。
2. 通用 financial template 可跨不同网站流程使用。
3. 不需要站点操作白名单。
4. trusted Agent 在有效 assertion 和额度内可完成购买，不触发重复 WebFA 审批。
5. Agent-owned `unknown_external_effect` 默认 `allow_with_audit`。
6. 密码、2FA、CAPTCHA、生物识别、支付验证始终 Human Takeover。
7. secret 不进入 WebState、MCP、日志、receipt 或 Agent-readable screenshot。
8. upload 使用 scoped resource_ref，不接受任意本地路径。
9. autonomy/step-up/absolute/daily/monthly limit 可机械执行。
10. 一次性购买不能授权周期性承诺。
11. Agent-owned Profile 可比 user-owned Profile 更宽松。
12. 默认 MCP 仍然严格为五个工具。
13. P10 WebObjects 与 Semantic Operations 仍是唯一网页操作模型。
14. 所有重要安全决策生成 secret-free receipt。
15. PaymentInstrument 只以受保护引用对 Agent 暴露。
16. 第一阶段支付后端完成 merchant-saved + system/tokenized 路径中的至少一条真实闭环。
17. 不引入 disposable public model。

---

## 23. 实施约束

- 先完成 P11.1 Schema，再写 Runtime behavior。
- 每个阶段必须向完整目标模型收敛。
- 禁止为了早期演示缩减公共 Schema。
- 禁止把业务语义塞回 P10 CapabilityEffect。
- 禁止用 selector/site adapter 作为安全核心。
- 可选 evidence adapter 只能提高事实验证质量，不能成为 Agent 操作网站的前提。
- 不 push，除非用户明确要求。
- 每个阶段完成后写独立 report 和 progress entry。

---

## 24. 参考标准

P11 不是 OAuth 或支付处理器实现，但以下标准支撑其设计方向：

- RFC 9396 OAuth 2.0 Rich Authorization Requests：结构化、细粒度授权详情。
- W3C Payment Request API：浏览器作为商户、付款人与支付方式之间的中介。
- W3C Secure Payment Confirmation：将用户验证绑定到具体交易详情。
- WebAuthn：生物识别和用户验证留在认证器安全边界内。
- PCI DSS：处理原始持卡人数据会显著扩大安全和合规范围。

因此，P11 优先选择 reference、tokenized wallet、merchant-saved method、issuer virtual card，而不是 raw-card vault。

---

## 25. 最终决策摘要

P11 不是审批墙，而是：

```text
Agent Safety Contract
  + Agent self-assertion
  + deterministic hard boundaries
  + protected resource brokers
  + optional scope escalation
  + secret-free audit receipts
```

总原则：

> WebFA 告诉 Agent 必须确认什么；Agent 根据用户上下文作出判断；WebFA 记录 Agent 的声明，并只执行能够机械判断的边界。

支付原则：

> WebFA 可以代表 Agent 使用受保护支付工具，但绝不能把支付秘密交给 Agent。

默认策略：

```text
trusted_agent = default
agent_owned unknown_external_effect = allow_with_audit
payment MVP = merchant_saved + system/tokenized path
```
