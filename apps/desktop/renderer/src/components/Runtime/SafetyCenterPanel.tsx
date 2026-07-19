"use client";

import { useEffect, useMemo, useState } from "react";
import {
  approveStepUp,
  createFinancialPolicy,
  createPaymentInstrument,
  rejectStepUp,
  revokePaymentInstrument,
  updateProfilePolicy,
} from "../../lib/visualizer-api";
import type {
  AccountOwner,
  FinancialPolicy,
  PaymentInstrumentState,
  SafetyReceipt,
  StepUpRequestState,
  TrustMode,
  UnknownEffectPolicy,
  VisualizerState,
} from "../../types/visualizer";

type SafetyCenterPanelProps = {
  apiUrl: string;
  profile: VisualizerState["profile"];
  activeAgentId: string | null;
  pageUrl: string;
  financialPolicies: FinancialPolicy[];
  paymentInstruments: PaymentInstrumentState[];
  stepUps: StepUpRequestState[];
  receipts: SafetyReceipt[];
  disabled?: boolean;
  onChanged: () => Promise<void> | void;
  onMessage: (message: string) => void;
  onError: (message: string) => void;
};

export function SafetyCenterPanel({
  apiUrl,
  profile,
  activeAgentId,
  pageUrl,
  financialPolicies,
  paymentInstruments,
  stepUps,
  receipts,
  disabled = false,
  onChanged,
  onMessage,
  onError,
}: SafetyCenterPanelProps) {
  const [busy, setBusy] = useState(false);
  const [owner, setOwner] = useState<AccountOwner>(profile.owner);
  const [trustMode, setTrustMode] = useState<TrustMode>(profile.trust_mode);
  const [unknownPolicy, setUnknownPolicy] = useState<UnknownEffectPolicy>(profile.unknown_external_effect_policy);
  const [allowedOrigins, setAllowedOrigins] = useState("");
  const [financialPolicyId, setFinancialPolicyId] = useState("");

  const [newPolicyId, setNewPolicyId] = useState("agent-shopping");
  const [currency, setCurrency] = useState("CNY");
  const [autonomyLimit, setAutonomyLimit] = useState("300.00");
  const [stepUpLimit, setStepUpLimit] = useState("2000.00");
  const [absoluteLimit, setAbsoluteLimit] = useState("10000.00");
  const [dailyLimit, setDailyLimit] = useState("1000.00");
  const [monthlyLimit, setMonthlyLimit] = useState("3000.00");
  const [minimumAssurance, setMinimumAssurance] = useState<FinancialPolicy["minimum_assurance"]>("runtime_observed");

  const [instrumentId, setInstrumentId] = useState("pay-agent-01");
  const [instrumentType, setInstrumentType] = useState<PaymentInstrumentState["instrument"]["type"]>("merchant_saved");
  const [instrumentOwner, setInstrumentOwner] = useState<"agent" | "user" | "shared">("agent");
  const [brand, setBrand] = useState("Visa");
  const [last4, setLast4] = useState("");
  const [displayName, setDisplayName] = useState("Agent shopping card");
  const [instrumentPolicyId, setInstrumentPolicyId] = useState("");

  useEffect(() => {
    setOwner(profile.owner);
    setTrustMode(profile.trust_mode);
    setUnknownPolicy(profile.unknown_external_effect_policy);
    setAllowedOrigins(profile.allowed_origins.join(", "));
    setFinancialPolicyId(profile.financial_policy_id ?? "");
  }, [profile]);

  useEffect(() => {
    if (!instrumentPolicyId && financialPolicies[0]) {
      setInstrumentPolicyId(financialPolicies[0].policy_id);
    }
  }, [financialPolicies, instrumentPolicyId]);

  const pendingStepUps = useMemo(
    () => stepUps.filter((item) => item.status === "pending" || item.status === "approved"),
    [stepUps],
  );

  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
      await onChanged();
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function saveProfile() {
    await run(async () => {
      await updateProfilePolicy(apiUrl, {
        profile_id: profile.profile_id,
        owner,
        bound_agent_ids: profile.bound_agent_ids,
        allowed_origins: splitValues(allowedOrigins),
        safety_policy_id: profile.safety_policy_id,
        financial_policy_id: financialPolicyId || null,
        trust_mode: trustMode,
        unknown_external_effect_policy: unknownPolicy,
      });
      onMessage("Profile 安全策略已更新");
    });
  }

  async function addPolicy() {
    await run(async () => {
      await createFinancialPolicy(apiUrl, {
        policy_id: newPolicyId.trim(),
        currency: currency.trim().toUpperCase(),
        autonomy_limit: autonomyLimit,
        step_up_limit: stepUpLimit,
        absolute_limit: absoluteLimit,
        daily_limit: dailyLimit || null,
        monthly_limit: monthlyLimit || null,
        subscriptions_allowed: false,
        transfers_allowed: false,
        cash_equivalents_allowed: false,
        minimum_assurance: minimumAssurance,
      });
      setFinancialPolicyId(newPolicyId.trim());
      setInstrumentPolicyId(newPolicyId.trim());
      onMessage("金融策略已注册");
    });
  }

  async function addInstrument() {
    if (!instrumentPolicyId) {
      onError("请先创建或选择金融策略");
      return;
    }
    if (last4 && !/^\d{4}$/.test(last4)) {
      onError("尾号必须是 4 位数字");
      return;
    }
    await run(async () => {
      await createPaymentInstrument(apiUrl, {
        instrument_id: instrumentId.trim(),
        owner: instrumentOwner,
        profile_id: profile.profile_id,
        type: instrumentType,
        brand: brand.trim(),
        last4: last4.trim(),
        currency: currency.trim().toUpperCase(),
        policy_id: instrumentPolicyId,
        bound_agent_ids: activeAgentId ? [activeAgentId] : [],
        allowed_origins: originFromUrl(pageUrl) ? [originFromUrl(pageUrl)] : [],
        display_name: displayName.trim(),
      });
      onMessage("支付工具引用已注册");
    });
  }

  return (
    <div className="viz-column-content viz-column-content-tight-top">
      <Section id="safety-step-ups" title={`Step-up 请求 (${pendingStepUps.length})`}>
        {pendingStepUps.length === 0 ? (
          <Hint>当前没有需要扩大授权范围的操作。</Hint>
        ) : (
          pendingStepUps.map((item) => (
            <Card key={item.request.step_up_id} accent={item.status === "pending"}>
              <strong>{labelReason(item.request.reason)}</strong>
              <div>{item.request.message}</div>
              <Small>{item.request.agent_id} · {item.request.profile_id} · {item.request.operation}</Small>
              <Scope title="当前范围" value={item.request.current_scope} />
              <Scope title="请求范围" value={item.request.requested_scope} />
              <Small>有效至 {new Date(item.request.expires_at).toLocaleTimeString()}</Small>
              {item.status === "pending" ? (
                <div className="viz-management-actions">
                  <button
                    type="button"
                    className="viz-btn viz-btn-primary"
                    disabled={busy || disabled}
                    onClick={() => void run(async () => {
                      await approveStepUp(apiUrl, item.request.step_up_id, "Approved in WebFA Safety Center");
                      onMessage("已批准本次范围升级；外部 Agent 可使用同一 step_up_id 重试");
                    })}
                  >
                    仅批准本次
                  </button>
                  <button
                    type="button"
                    className="viz-btn viz-btn-warning"
                    disabled={busy || disabled}
                    onClick={() => void run(async () => {
                      await rejectStepUp(apiUrl, item.request.step_up_id, "Rejected in WebFA Safety Center");
                      onMessage("已拒绝本次范围升级");
                    })}
                  >
                    拒绝
                  </button>
                </div>
              ) : (
                <Small>已批准，等待外部 Agent 重试后自动消费。</Small>
              )}
            </Card>
          ))
        )}
      </Section>

      <Section id="safety-profile-policy" title="Profile 策略">
        <div className="viz-control-stack">
          <div
            className="viz-management-hint"
            data-ui="profile-policy-effect"
          >
            保存后立即作用于当前 Profile。收紧 Agent binding 或 Origin 范围会使不再符合策略的活动授权在下次操作时失败；Cookie、克隆和 Bundle 等身份存储维护仍要求先关闭 Session。
          </div>
          <Field label="Profile 所有者">
            <select className="viz-input" aria-label="Profile 所有者" value={owner} onChange={(event) => setOwner(event.target.value as AccountOwner)} disabled={busy || disabled}>
              <option value="agent_owned">外部 Agent 自有</option>
              <option value="user_owned">用户所有</option>
              <option value="shared">共享</option>
              <option value="unknown">未知</option>
            </select>
          </Field>
          <Field label="信任模式">
            <select className="viz-input" aria-label="Profile 信任模式" value={trustMode} onChange={(event) => setTrustMode(event.target.value as TrustMode)} disabled={busy || disabled}>
              <option value="trusted_agent">trusted_agent</option>
              <option value="host_attested">host_attested</option>
              <option value="guarded">guarded</option>
            </select>
          </Field>
          <Field label="未知外部效果">
            <select className="viz-input" aria-label="未知外部效果策略" value={unknownPolicy} onChange={(event) => setUnknownPolicy(event.target.value as UnknownEffectPolicy)} disabled={busy || disabled}>
              <option value="allow_with_audit">允许并审计</option>
              <option value="require_assertion">要求外部 Agent 声明</option>
              <option value="require_step_up">要求范围升级</option>
              <option value="deny">拒绝</option>
            </select>
          </Field>
          <Field label="允许的 Origins">
            <input className="viz-input" aria-label="Profile 允许的 Origins" value={allowedOrigins} onChange={(event) => setAllowedOrigins(event.target.value)} placeholder="逗号分隔；留空表示不限制" disabled={busy || disabled} />
          </Field>
          <Field label="绑定的金融策略">
            <select className="viz-input" aria-label="Profile 绑定的金融策略" value={financialPolicyId} onChange={(event) => setFinancialPolicyId(event.target.value)} disabled={busy || disabled}>
              <option value="">不绑定金融策略</option>
              {financialPolicies.map((item) => <option key={item.policy_id} value={item.policy_id}>{item.policy_id}</option>)}
            </select>
          </Field>
          <button type="button" className="viz-btn viz-btn-primary" disabled={busy || disabled} onClick={() => void saveProfile()}>保存 Profile 策略</button>
        </div>
      </Section>

      <Section id="safety-financial-policy" title="金融策略">
        <div className="viz-control-stack">
          <Field label="策略 ID">
            <input className="viz-input" aria-label="金融策略 ID" value={newPolicyId} onChange={(event) => setNewPolicyId(event.target.value)} placeholder="policy_id" disabled={busy || disabled} />
          </Field>
          <div className="viz-management-grid viz-management-grid-policy">
            <Field label="币种">
              <input className="viz-input" aria-label="金融策略币种" value={currency} onChange={(event) => setCurrency(event.target.value)} placeholder="CNY" disabled={busy || disabled} />
            </Field>
            <Field label="最低保证级别">
              <select className="viz-input" aria-label="金融策略最低保证级别" value={minimumAssurance} onChange={(event) => setMinimumAssurance(event.target.value as FinancialPolicy["minimum_assurance"])} disabled={busy || disabled}>
                <option value="agent_asserted">agent_asserted</option>
                <option value="runtime_observed">runtime_observed</option>
                <option value="provider_verified">provider_verified</option>
                <option value="user_confirmed">user_confirmed</option>
              </select>
            </Field>
          </div>
          <LimitGrid label="自主 / Step-up / 绝对" fieldLabels={["自主额度", "Step-up 额度", "绝对额度"]} values={[autonomyLimit, stepUpLimit, absoluteLimit]} setters={[setAutonomyLimit, setStepUpLimit, setAbsoluteLimit]} disabled={busy || disabled} />
          <LimitGrid label="每日 / 每月" fieldLabels={["每日额度", "每月额度"]} values={[dailyLimit, monthlyLimit]} setters={[setDailyLimit, setMonthlyLimit]} disabled={busy || disabled} />
          <Hint>订阅、转账和现金等价物默认关闭。大额标准完全由这些额度决定。</Hint>
          <button type="button" className="viz-btn viz-btn-primary" disabled={busy || disabled || !newPolicyId.trim()} onClick={() => void addPolicy()}>注册金融策略</button>
        </div>
      </Section>

      <Section id="safety-payment-instruments" title="支付工具引用">
        <div className="viz-control-stack">
          <Field label="引用 ID">
            <input className="viz-input" aria-label="支付工具引用 ID" value={instrumentId} onChange={(event) => setInstrumentId(event.target.value)} placeholder="instrument_id" disabled={busy || disabled} />
          </Field>
          <Field label="工具类型">
            <select className="viz-input" aria-label="支付工具类型" value={instrumentType} onChange={(event) => setInstrumentType(event.target.value as PaymentInstrumentState["instrument"]["type"])} disabled={busy || disabled}>
              <option value="merchant_saved">商户已保存方式</option>
              <option value="system_wallet">系统钱包</option>
              <option value="tokenized_wallet">令牌化钱包</option>
            </select>
          </Field>
          <Field label="所有者">
            <select className="viz-input" aria-label="支付工具所有者" value={instrumentOwner} onChange={(event) => setInstrumentOwner(event.target.value as "agent" | "user" | "shared")} disabled={busy || disabled}>
              <option value="agent">外部 Agent 专用</option>
              <option value="user">用户所有</option>
              <option value="shared">共享</option>
            </select>
          </Field>
          <div className="viz-management-grid viz-management-grid-instrument">
            <Field label="品牌">
              <input className="viz-input" aria-label="支付工具品牌" value={brand} onChange={(event) => setBrand(event.target.value)} placeholder="Visa" disabled={busy || disabled} />
            </Field>
            <Field label="尾号">
              <input className="viz-input" aria-label="支付工具尾号" value={last4} onChange={(event) => setLast4(event.target.value)} placeholder="4 位数字" maxLength={4} disabled={busy || disabled} />
            </Field>
          </div>
          <Field label="安全显示名称">
            <input className="viz-input" aria-label="支付工具安全显示名称" value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="不会显示完整支付信息" disabled={busy || disabled} />
          </Field>
          <Field label="绑定的金融策略">
            <select className="viz-input" aria-label="支付工具绑定的金融策略" value={instrumentPolicyId} onChange={(event) => setInstrumentPolicyId(event.target.value)} disabled={busy || disabled}>
              <option value="">选择金融策略</option>
              {financialPolicies.map((item) => <option key={item.policy_id} value={item.policy_id}>{item.policy_id}</option>)}
            </select>
          </Field>
          <Hint>仅保存支付工具引用、品牌和尾号。完整卡号、CVV、支付密码和钱包 Token 不进入 WebFA Agent 协议。</Hint>
          <button type="button" className="viz-btn viz-btn-primary" disabled={busy || disabled || !instrumentId.trim()} onClick={() => void addInstrument()}>注册支付工具引用</button>
        </div>
        {paymentInstruments.filter((item) => item.status === "active").map((item) => (
          <Card key={item.instrument.instrument_id}>
            <strong>{item.instrument.display_name || item.instrument.instrument_id}</strong>
            <div>{item.instrument.type} · {item.instrument.brand} •••• {item.instrument.last4 || "—"}</div>
            <Small>{item.instrument.policy_id} · {item.instrument.currency}</Small>
            <button type="button" className="viz-btn viz-btn-warning" disabled={busy || disabled} onClick={() => void run(async () => {
              await revokePaymentInstrument(apiUrl, item.instrument.instrument_id);
              onMessage("支付工具引用已撤销");
            })}>撤销</button>
          </Card>
        ))}
      </Section>

      <Section id="safety-receipts" title={`安全回执 (${receipts.length})`}>
        {receipts.length === 0 ? <Hint>尚无安全回执。</Hint> : receipts.slice(0, 20).map((receipt) => (
          <Card key={receipt.receipt_id}>
            <strong>{receipt.final_decision} · {receipt.result}</strong>
            <div>{receipt.operation} · {receipt.origin || "local"}</div>
            <Small>{receipt.agent_id} · {new Date(receipt.timestamp).toLocaleString()}</Small>
            {receipt.message && <Small>{receipt.message}</Small>}
            {receipt.step_up_id && <Small>step-up: {receipt.step_up_id}</Small>}
            <Small breakable>{receipt.receipt_id}</Small>
          </Card>
        ))}
      </Section>
    </div>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return <section className="viz-management-section" aria-labelledby={id}><h3 id={id} className="viz-management-heading">{title}</h3>{children}</section>;
}

function Card({ children, accent = false }: { children: React.ReactNode; accent?: boolean }) {
  return <div className={`viz-management-card${accent ? " viz-management-card-accent" : ""}`}>{children}</div>;
}

function Hint({ children }: { children: React.ReactNode }) {
  return <div className="viz-management-hint">{children}</div>;
}

function Small({ children, breakable = false }: { children: React.ReactNode; breakable?: boolean }) {
  return <div className={`viz-management-small${breakable ? " viz-management-breakable" : ""}`}>{children}</div>;
}

function Scope({ title, value }: { title: string; value: Record<string, string | number | boolean> }) {
  return <div className="viz-management-scope"><Small>{title}</Small><code>{JSON.stringify(value)}</code></div>;
}

function LimitGrid({ label, fieldLabels, values, setters, disabled }: { label: string; fieldLabels: string[]; values: string[]; setters: Array<(value: string) => void>; disabled: boolean }) {
  return <div className="viz-limit-group"><Small>{label}</Small><div className="viz-limit-grid">{values.map((value, index) => <Field key={fieldLabels[index]} label={fieldLabels[index]} compact><input className="viz-input" aria-label={fieldLabels[index]} value={value} onChange={(event) => setters[index](event.target.value)} inputMode="decimal" disabled={disabled} /></Field>)}</div></div>;
}

function Field({ label, children, compact = false }: { label: string; children: React.ReactNode; compact?: boolean }) {
  return <label className={`viz-management-field${compact ? " viz-management-field-compact" : ""}`}><span>{label}</span>{children}</label>;
}

function splitValues(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function originFromUrl(value: string): string {
  if (!value) return "";
  try {
    const parsed = new URL(value);
    return parsed.protocol === "file:" ? "file://" : parsed.origin;
  } catch {
    return "";
  }
}

function labelReason(reason: StepUpRequestState["request"]["reason"]): string {
  const labels: Record<StepUpRequestState["request"]["reason"], string> = {
    financial_limit: "资金范围升级",
    financial_assurance: "支付证据升级",
    identity_switch: "用户身份切换",
    profile_scope: "Profile 范围升级",
    unknown_external_effect: "未知外部效果",
    policy_escalation: "策略范围升级",
  };
  return labels[reason];
}
