export type BrowserProfileCatalogItem = {
  profile_id: string;
  agent_alias: string;
  display_name: string;
  agent_description: string;
  persistence: "persistent" | "ephemeral";
  bootstrap_source: "blank" | "human_login" | "imported" | "cloned" | "restored";
  catalog_state: "ready" | "archived" | "deleting" | "error";
  version: number;
};

export type CookieImportWarning = {
  code: string;
  count: number;
};

export type CookieImportPreview = {
  preview_token: string;
  profile_id: string;
  profile_version: number;
  source_format: "json" | "netscape";
  total_entries: number;
  accepted_count: number;
  rejected_count: number;
  domain_count: number;
  domains: string[];
  secure_count: number;
  http_only_count: number;
  session_count: number;
  persistent_count: number;
  partitioned_count: number;
  warnings: CookieImportWarning[];
  expires_at: string;
};

export type CookieImportResult = {
  status: "cookies_imported";
  profile_id: string;
  profile_version: number;
  source_format: "json" | "netscape";
  imported_count: number;
  verified_count: number;
  domain_count: number;
  occurred_at: string;
};

export type ProfileSessionCloseResult = {
  status: "session_closed" | "already_inactive";
  profile_id: string;
  session_id: string | null;
};

export type ProfileClonePreview = {
  preview_token: string;
  source_profile_id: string;
  source_profile_version: number;
  source_agent_alias: string;
  file_count: number;
  total_bytes: number;
  excluded_count: number;
  expires_at: string;
};

export type ProfileCloneTargetPayload = {
  agent_alias: string;
  display_name: string;
  agent_description?: string;
  owner?: "user_owned" | "agent_owned" | "shared";
  trust_mode?: "guarded" | "trusted_agent" | "direct_user";
};

export type ProfileCloneResult = {
  status: "profile_cloned";
  source_profile_id: string;
  target_profile_id: string;
  target_agent_alias: string;
  target_profile_version: number;
  file_count: number;
  total_bytes: number;
  occurred_at: string;
};

export type ProfileBundleExportPreview = {
  preview_token: string;
  source_profile_id: string;
  source_profile_version: number;
  source_agent_alias: string;
  source_display_name: string;
  file_count: number;
  total_bytes: number;
  excluded_count: number;
  suggested_filename: string;
  expires_at: string;
};

export type ProfileBundleRestorePreview = {
  preview_token: string;
  bundle_format_version: number;
  source_agent_alias: string;
  source_display_name: string;
  source_bootstrap_source: string;
  source_platform: string;
  current_platform: string;
  restoration_scope: "browser_storage_only";
  compatibility_warning: string;
  file_count: number;
  total_bytes: number;
  created_at: string;
  expires_at: string;
};

export type ProfileBundleRestoreResult = {
  status: "profile_restored";
  target_profile_id: string;
  target_agent_alias: string;
  target_profile_version: number;
  file_count: number;
  total_bytes: number;
  occurred_at: string;
};
