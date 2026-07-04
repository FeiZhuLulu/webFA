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
  };
  security: BrowserUrlSecurity;
  dialogs: BrowserDialog[];
  frames: BrowserFrame[];
  error: BrowserStateError | null;
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
  };
  agent: {
    active_agent_id: string | null;
    lease_expires_at: string | null;
  };
  profile: {
    profile_id: string;
    shared: boolean;
  };
  page: {
    url: string;
    title: string;
    status: "idle" | "loading";
    auth: BrowserAuthState;
  };
  browser_state: BrowserState | null;
  preview: {
    format: "png";
    data_url: string | null;
    captured_at: string | null;
  };
  auth_surface: {
    active: boolean;
    url: string | null;
    mode: "electron" | "legacy";
  };
  recent_actions: VisualizerActionEntry[];
  errors: Array<{ code: string; message: string }>;
};