export type BrowserAuthState = {
  surface_detected: boolean;
  takeover: "none" | "visible_window" | "auth_surface";
  reason: string[];
  user_action_required: boolean;
};

export type BrowserUrlSecurity = {
  url_class: "public" | "private" | "local" | "file" | "blocked";
  risk_flags: string[];
  policy: "allow" | "warn" | "block";
  message?: string | null;
};

export type BrowserStateError = {
  code: string;
  message: string;
  recover_hint?: string | null;
};

export type BrowserDialog = {
  id: string;
  type: "alert" | "confirm" | "prompt";
  message: string;
  default_value: string;
  user_action_required: boolean;
};

export type BrowserFrame = {
  id: string;
  parent_id: string | null;
  url: string;
  title: string;
  same_origin: boolean;
  visible: boolean;
  security: BrowserUrlSecurity;
};

export type BrowserElement = {
  id: string;
  role: string;
  tag: string;
  name: string;
  text: string;
  value: string;
  placeholder: string;
  input_type?: string | null;
  frame_id?: string | null;
  visible: boolean;
  enabled: boolean;
  actions: string[];
};

export type BrowserContentBlock = {
  id: string;
  type: string;
  text: string;
  element_ids: string[];
  frame_id?: string | null;
};

export type AccountOwner = "agent_owned" | "user_owned" | "shared" | "unknown";
export type TrustMode = "trusted_agent" | "host_attested" | "guarded";
export type UnknownEffectPolicy = "allow_with_audit" | "require_assertion" | "require_step_up" | "deny";

export type BrowserState = {
  session_id: string;
  url: string;
  title: string;
  page_status: "idle" | "loading";
  focused_element_id: string | null;
  tabs: Array<{ id: string; url: string; title: string; active: boolean }>;
  visible_text: string;
  content_blocks: BrowserContentBlock[];
  forms: Array<Record<string, unknown>>;
  interactive_elements: BrowserElement[];
  auth: BrowserAuthState;
  agent: {
    active_agent_id: string | null;
    agent_lease_expires_at: string | null;
    profile_shared: boolean;
    profile_id: string;
    profile_owner: AccountOwner;
    trust_mode: TrustMode;
    unknown_external_effect_policy: UnknownEffectPolicy;
  };
  security: BrowserUrlSecurity;
  dialogs: BrowserDialog[];
  frames: BrowserFrame[];
  error: BrowserStateError | null;
};

export type HumanTakeoverReason =
  | "authentication"
  | "captcha"
  | "payment_verification"
  | "biometric_verification"
  | "opaque_surface"
  | "high_risk_confirmation"
  | "permission_request"
  | "file_selection"
  | "ambiguous_state"
  | "manual_identity_confirmation";

export type HumanTakeoverState = {
  required: boolean;
  reason: HumanTakeoverReason | null;
  target: string | null;
  origin: string;
  resume_operation: "observe";
};

export type WebObjectProjection = {
  id: string;
  projection: "summary" | "full";
  category: string;
  role: string;
  name: string;
  capabilities: string[];
  version: number;
  state_summary?: string[];
  opaque_reason?: string | null;
};

export type WebState = {
  session_id: string;
  document_id: string;
  document_revision: number;
  url: string;
  title: string;
  status: "idle" | "loading" | "error";
  objects: WebObjectProjection[];
  object_count: number;
  takeover: HumanTakeoverState;
  auth: BrowserAuthState;
};

export type LocalResourceGrantState = {
  grant: {
    resource_ref: string;
    display_name: string;
    owner: "agent" | "user" | "shared";
    purpose: string;
    allowed_origins: string[];
    bound_agent_ids: string[];
    bound_profile_ids: string[];
    expires_at: string | null;
    max_uses: number;
  };
  status: "active" | "consumed" | "expired" | "revoked";
  remaining_uses: number;
  size_bytes: number;
  created_at: string;
};

export type FinancialPolicy = {
  policy_id: string;
  currency: string;
  autonomy_limit: string;
  step_up_limit: string;
  absolute_limit: string;
  daily_limit: string | null;
  monthly_limit: string | null;
  subscriptions_allowed: boolean;
  transfers_allowed: boolean;
  cash_equivalents_allowed: boolean;
  minimum_assurance: "agent_asserted" | "runtime_observed" | "provider_verified" | "user_confirmed";
};

export type PaymentInstrumentState = {
  instrument: {
    instrument_id: string;
    owner: "agent" | "user" | "shared";
    profile_id: string;
    type: "merchant_saved" | "system_wallet" | "tokenized_wallet" | "issuer_virtual_card" | "prepaid_card_reference" | "local_protected_card";
    brand: string;
    last4: string;
    currency: string;
    policy_id: string;
    bound_agent_ids: string[];
    allowed_origins: string[];
    display_name: string;
  };
  status: "active" | "revoked";
  created_at: string;
};

export type StepUpRequestState = {
  request: {
    step_up_id: string;
    reason: "financial_limit" | "financial_assurance" | "identity_switch" | "profile_scope" | "unknown_external_effect" | "policy_escalation";
    context_id: string | null;
    agent_id: string;
    profile_id: string;
    origin: string;
    target_object_id: string;
    operation: string;
    message: string;
    current_scope: Record<string, string | number | boolean>;
    requested_scope: Record<string, string | number | boolean>;
    created_at: string;
    expires_at: string;
  };
  status: "pending" | "approved" | "rejected" | "expired" | "consumed";
  approved_scope: Record<string, string | number | boolean>;
  decided_by: string | null;
  decision_note: string;
  decided_at: string | null;
  remaining_uses: number;
};

export type SafetyReceipt = {
  receipt_id: string;
  context_id: string;
  agent_id: string;
  profile_id: string;
  origin: string;
  target_object_id: string;
  operation: string;
  p10_effect: string;
  safety_dimensions: string[];
  assertion_refs: string[];
  hard_boundary_decision: string;
  final_decision: string;
  before_revision: number;
  after_revision: number;
  result: "executed" | "not_executed" | "takeover" | "denied" | "failed";
  message: string;
  authority_source: string | null;
  step_up_id: string | null;
  metadata: Record<string, string | number | boolean>;
  timestamp: string;
};

export type VisualizerActionEntry = {
  timestamp: string;
  tool: string;
  status: "ok" | "error";
  code: string | null;
  message: string;
  agent_id: string | null;
};

export type VisualizerState = {
  runtime: {
    online: boolean;
    driver: string;
    headless: boolean;
    host_status: string;
    visible_window: boolean;
    executable_found: boolean | null;
    executable_name: string | null;
    last_error: string | null;
  };
  agent: {
    active_agent_id: string | null;
    lease_expires_at: string | null;
  };
  profile: {
    profile_id: string;
    shared: boolean;
    owner: AccountOwner;
    trust_mode: TrustMode;
    unknown_external_effect_policy: UnknownEffectPolicy;
    bound_agent_ids: string[];
    allowed_origins: string[];
    safety_policy_id: string | null;
    financial_policy_id: string | null;
  };
  page: {
    url: string;
    title: string;
    status: "idle" | "loading";
    auth: BrowserAuthState;
  };
  browser_state: BrowserState | null;
  web_state: WebState | null;
  preview: {
    format: "png";
    data_url: string | null;
    captured_at: string | null;
  };
  auth_surface: {
    active: boolean;
    url: string | null;
    mode: "monitor" | "electron" | "legacy";
  };
  takeover_surface: {
    active: boolean;
    url: string | null;
    mode: "monitor" | "electron" | "legacy";
    reason: HumanTakeoverReason | null;
    target: string | null;
    origin: string;
  };
  local_resources: LocalResourceGrantState[];
  financial_policies: FinancialPolicy[];
  payment_instruments: PaymentInstrumentState[];
  step_ups: StepUpRequestState[];
  safety_receipts: SafetyReceipt[];
  recent_actions: VisualizerActionEntry[];
  errors: Array<{ code: string; message: string }>;
};
