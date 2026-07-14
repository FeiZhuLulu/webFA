import type {
  BrowserProfileCatalogItem,
  CookieImportPreview,
  CookieImportResult,
  ProfileBundleExportPreview,
  ProfileBundleRestorePreview,
  ProfileBundleRestoreResult,
  ProfileClonePreview,
  ProfileCloneResult,
  ProfileCloneTargetPayload,
  ProfileSessionCloseResult,
} from "../types/profile-bootstrap";
import type {
  AccountOwner,
  FinancialPolicy,
  LocalResourceGrantState,
  PaymentInstrumentState,
  StepUpRequestState,
  TrustMode,
  UnknownEffectPolicy,
  VisualizerState,
} from "../types/visualizer";

const API_FALLBACK = "http://127.0.0.1:8787";
let visualizerControlToken = "";

export function setVisualizerControlToken(token: string | null | undefined): void {
  visualizerControlToken = token?.trim() ?? "";
}

function controlHeaders(json = false): HeadersInit {
  if (!visualizerControlToken) {
    throw new Error("Visualizer control token is unavailable");
  }
  return {
    ...(json ? { "Content-Type": "application/json" } : {}),
    "X-WebFA-Visualizer-Token": visualizerControlToken,
  };
}

export function resolveApiUrl(preferred?: string | null): string {
  return preferred || API_FALLBACK;
}

async function readApiError(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string | { code?: string; message?: string } };
    const detail = body.detail;
    if (typeof detail === "string" && detail) return detail;
    if (detail && typeof detail === "object") {
      const code = detail.code ? `[${detail.code}] ` : "";
      return `${code}${detail.message || fallback}`;
    }
  } catch {
    // ignore parse errors
  }
  if (response.status === 404) {
    return "Visualizer API 不存在，请重启 Runtime 到最新版本";
  }
  return `${fallback} (${response.status})`;
}

export async function fetchVisualizerState(apiUrl: string): Promise<VisualizerState> {
  const response = await fetch(`${apiUrl}/v1/visualizer/state`, {
    cache: "no-store",
    headers: controlHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Visualizer state failed"));
  }
  return (await response.json()) as VisualizerState;
}

export async function fetchProfiles(apiUrl: string): Promise<BrowserProfileCatalogItem[]> {
  const response = await fetch(`${apiUrl}/v1/profiles`, {
    cache: "no-store",
    headers: controlHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Load profiles failed"));
  }
  const body = (await response.json()) as { profiles: BrowserProfileCatalogItem[] };
  return body.profiles;
}

export async function closeProfileSession(
  apiUrl: string,
  profileId: string,
): Promise<ProfileSessionCloseResult> {
  const response = await fetch(
    `${apiUrl}/v1/profiles/${encodeURIComponent(profileId)}/session/close`,
    { method: "POST", headers: controlHeaders() },
  );
  if (!response.ok) {
    throw new Error(await readApiError(response, "Close profile session failed"));
  }
  return (await response.json()) as ProfileSessionCloseResult;
}

export async function previewCookieImport(
  apiUrl: string,
  profileId: string,
  profileVersion: number,
  file: File,
): Promise<CookieImportPreview> {
  const query = new URLSearchParams({
    expected_version: String(profileVersion),
    format: "auto",
  });
  const response = await fetch(
    `${apiUrl}/v1/profiles/${encodeURIComponent(profileId)}/bootstrap/cookies/preview?${query}`,
    {
      method: "POST",
      headers: {
        ...controlHeaders(),
        "Content-Type": "application/octet-stream",
      },
      body: await file.arrayBuffer(),
    },
  );
  if (!response.ok) {
    throw new Error(await readApiError(response, "Preview cookie import failed"));
  }
  return (await response.json()) as CookieImportPreview;
}

export async function cancelCookieImport(
  apiUrl: string,
  profileId: string,
  previewToken: string,
): Promise<void> {
  const response = await fetch(
    `${apiUrl}/v1/profiles/${encodeURIComponent(profileId)}/bootstrap/cookies/cancel`,
    {
      method: "POST",
      headers: controlHeaders(true),
      body: JSON.stringify({ preview_token: previewToken }),
    },
  );
  if (!response.ok) {
    throw new Error(await readApiError(response, "Cancel cookie import failed"));
  }
}

export async function commitCookieImport(
  apiUrl: string,
  preview: CookieImportPreview,
): Promise<CookieImportResult> {
  const response = await fetch(
    `${apiUrl}/v1/profiles/${encodeURIComponent(preview.profile_id)}/bootstrap/cookies/import`,
    {
      method: "POST",
      headers: controlHeaders(true),
      body: JSON.stringify({
        preview_token: preview.preview_token,
        expected_version: preview.profile_version,
      }),
    },
  );
  if (!response.ok) {
    throw new Error(await readApiError(response, "Import cookies failed"));
  }
  return (await response.json()) as CookieImportResult;
}

export async function previewProfileClone(
  apiUrl: string,
  sourceProfileId: string,
  sourceProfileVersion: number,
): Promise<ProfileClonePreview> {
  const query = new URLSearchParams({ expected_version: String(sourceProfileVersion) });
  const response = await fetch(
    `${apiUrl}/v1/profiles/${encodeURIComponent(sourceProfileId)}/bootstrap/clone/preview?${query}`,
    { method: "POST", headers: controlHeaders() },
  );
  if (!response.ok) {
    throw new Error(await readApiError(response, "Preview Profile clone failed"));
  }
  return (await response.json()) as ProfileClonePreview;
}

export async function cancelProfileClone(
  apiUrl: string,
  sourceProfileId: string,
  previewToken: string,
): Promise<void> {
  const response = await fetch(
    `${apiUrl}/v1/profiles/${encodeURIComponent(sourceProfileId)}/bootstrap/clone/cancel`,
    {
      method: "POST",
      headers: controlHeaders(true),
      body: JSON.stringify({ preview_token: previewToken }),
    },
  );
  if (!response.ok) {
    throw new Error(await readApiError(response, "Cancel Profile clone failed"));
  }
}

export async function commitProfileClone(
  apiUrl: string,
  preview: ProfileClonePreview,
  targetProfile: ProfileCloneTargetPayload,
): Promise<ProfileCloneResult> {
  const response = await fetch(
    `${apiUrl}/v1/profiles/${encodeURIComponent(preview.source_profile_id)}/bootstrap/clone`,
    {
      method: "POST",
      headers: controlHeaders(true),
      body: JSON.stringify({
        preview_token: preview.preview_token,
        expected_source_version: preview.source_profile_version,
        target_profile: targetProfile,
      }),
    },
  );
  if (!response.ok) {
    throw new Error(await readApiError(response, "Clone Profile failed"));
  }
  return (await response.json()) as ProfileCloneResult;
}

export async function previewProfileBundleExport(
  apiUrl: string,
  sourceProfileId: string,
  sourceProfileVersion: number,
): Promise<ProfileBundleExportPreview> {
  const query = new URLSearchParams({ expected_version: String(sourceProfileVersion) });
  const response = await fetch(
    `${apiUrl}/v1/profiles/${encodeURIComponent(sourceProfileId)}/bootstrap/bundle/export/preview?${query}`,
    { method: "POST", headers: controlHeaders() },
  );
  if (!response.ok) {
    throw new Error(await readApiError(response, "Preview Profile Bundle export failed"));
  }
  return (await response.json()) as ProfileBundleExportPreview;
}

export async function cancelProfileBundleExport(
  apiUrl: string,
  sourceProfileId: string,
  previewToken: string,
): Promise<void> {
  const response = await fetch(
    `${apiUrl}/v1/profiles/${encodeURIComponent(sourceProfileId)}/bootstrap/bundle/export/cancel`,
    {
      method: "POST",
      headers: controlHeaders(true),
      body: JSON.stringify({ preview_token: previewToken }),
    },
  );
  if (!response.ok) {
    throw new Error(await readApiError(response, "Cancel Profile Bundle export failed"));
  }
}

export async function downloadProfileBundleFallback(
  apiUrl: string,
  preview: ProfileBundleExportPreview,
  passphrase: string,
): Promise<{ blob: Blob; fileName: string; sha256: string }> {
  const response = await fetch(
    `${apiUrl}/v1/profiles/${encodeURIComponent(preview.source_profile_id)}/bootstrap/bundle/export`,
    {
      method: "POST",
      headers: {
        ...controlHeaders(true),
        "X-WebFA-Bundle-Passphrase": passphrase,
      },
      body: JSON.stringify({
        preview_token: preview.preview_token,
        expected_source_version: preview.source_profile_version,
      }),
    },
  );
  if (!response.ok) {
    throw new Error(await readApiError(response, "Export Profile Bundle failed"));
  }
  return {
    blob: await response.blob(),
    fileName: preview.suggested_filename,
    sha256: response.headers.get("x-webfa-bundle-sha256") ?? "",
  };
}

export async function previewProfileBundleRestoreFallback(
  apiUrl: string,
  file: File,
  passphrase: string,
): Promise<ProfileBundleRestorePreview> {
  const response = await fetch(`${apiUrl}/v1/profile-bundles/restore/preview`, {
    method: "POST",
    headers: {
      ...controlHeaders(),
      "Content-Type": "application/octet-stream",
      "X-WebFA-Bundle-Passphrase": passphrase,
    },
    body: file,
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Preview Profile Bundle restore failed"));
  }
  return (await response.json()) as ProfileBundleRestorePreview;
}

export async function cancelProfileBundleRestore(
  apiUrl: string,
  previewToken: string,
): Promise<void> {
  const response = await fetch(`${apiUrl}/v1/profile-bundles/restore/cancel`, {
    method: "POST",
    headers: controlHeaders(true),
    body: JSON.stringify({ preview_token: previewToken }),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Cancel Profile Bundle restore failed"));
  }
}

export async function commitProfileBundleRestore(
  apiUrl: string,
  preview: ProfileBundleRestorePreview,
  passphrase: string,
  targetProfile: ProfileCloneTargetPayload,
): Promise<ProfileBundleRestoreResult> {
  const response = await fetch(`${apiUrl}/v1/profile-bundles/restore`, {
    method: "POST",
    headers: {
      ...controlHeaders(true),
      "X-WebFA-Bundle-Passphrase": passphrase,
    },
    body: JSON.stringify({
      preview_token: preview.preview_token,
      target_profile: targetProfile,
    }),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Restore Profile Bundle failed"));
  }
  return (await response.json()) as ProfileBundleRestoreResult;
}

export async function restartHost(apiUrl: string): Promise<VisualizerState> {
  const response = await fetch(`${apiUrl}/v1/visualizer/restart-host`, {
    method: "POST",
    headers: controlHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Restart host failed"));
  }
  return (await response.json()) as VisualizerState;
}

export type CreateLocalResourcePayload = {
  display_name: string;
  content_base64: string;
  owner: "agent" | "user" | "shared";
  purpose: string;
  allowed_origins: string[];
  bound_agent_ids: string[];
  bound_profile_ids: string[];
  expires_in_seconds: number;
  max_uses: number;
};

export async function createLocalResource(
  apiUrl: string,
  payload: CreateLocalResourcePayload,
): Promise<LocalResourceGrantState> {
  const response = await fetch(`${apiUrl}/v1/visualizer/resources`, {
    method: "POST",
    headers: controlHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Create resource grant failed"));
  }
  const body = (await response.json()) as { resource: LocalResourceGrantState };
  return body.resource;
}

export async function revokeLocalResource(
  apiUrl: string,
  resourceRef: string,
): Promise<LocalResourceGrantState> {
  const response = await fetch(
    `${apiUrl}/v1/visualizer/resources/${encodeURIComponent(resourceRef)}`,
    { method: "DELETE", headers: controlHeaders() },
  );
  if (!response.ok) {
    throw new Error(await readApiError(response, "Revoke resource grant failed"));
  }
  const body = (await response.json()) as { resource: LocalResourceGrantState };
  return body.resource;
}

export type ProfilePolicyPayload = {
  profile_id: string;
  owner: AccountOwner;
  bound_agent_ids: string[];
  allowed_origins: string[];
  safety_policy_id: string | null;
  financial_policy_id: string | null;
  trust_mode: TrustMode;
  unknown_external_effect_policy: UnknownEffectPolicy;
};

export async function updateProfilePolicy(
  apiUrl: string,
  payload: ProfilePolicyPayload,
): Promise<ProfilePolicyPayload> {
  const response = await fetch(
    `${apiUrl}/v1/visualizer/profile-policy/${encodeURIComponent(payload.profile_id)}`,
    {
      method: "PUT",
      headers: controlHeaders(true),
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    throw new Error(await readApiError(response, "Update profile policy failed"));
  }
  const body = (await response.json()) as { profile: ProfilePolicyPayload };
  return body.profile;
}

export async function createFinancialPolicy(
  apiUrl: string,
  payload: FinancialPolicy,
): Promise<FinancialPolicy> {
  const response = await fetch(`${apiUrl}/v1/visualizer/financial-policies`, {
    method: "POST",
    headers: controlHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Create financial policy failed"));
  }
  const body = (await response.json()) as { policy: FinancialPolicy };
  return body.policy;
}

export type CreatePaymentInstrumentPayload = PaymentInstrumentState["instrument"];

export async function createPaymentInstrument(
  apiUrl: string,
  payload: CreatePaymentInstrumentPayload,
): Promise<PaymentInstrumentState> {
  const response = await fetch(`${apiUrl}/v1/visualizer/payment-instruments`, {
    method: "POST",
    headers: controlHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Create payment instrument failed"));
  }
  const body = (await response.json()) as { instrument: PaymentInstrumentState };
  return body.instrument;
}

export async function revokePaymentInstrument(
  apiUrl: string,
  instrumentId: string,
): Promise<PaymentInstrumentState> {
  const response = await fetch(
    `${apiUrl}/v1/visualizer/payment-instruments/${encodeURIComponent(instrumentId)}`,
    { method: "DELETE", headers: controlHeaders() },
  );
  if (!response.ok) {
    throw new Error(await readApiError(response, "Revoke payment instrument failed"));
  }
  const body = (await response.json()) as { instrument: PaymentInstrumentState };
  return body.instrument;
}

export async function approveStepUp(
  apiUrl: string,
  stepUpId: string,
  decisionNote = "",
): Promise<StepUpRequestState> {
  const response = await fetch(
    `${apiUrl}/v1/visualizer/step-ups/${encodeURIComponent(stepUpId)}/approve`,
    {
      method: "POST",
      headers: controlHeaders(true),
      body: JSON.stringify({ decided_by: "local_user", decision_note: decisionNote }),
    },
  );
  if (!response.ok) {
    throw new Error(await readApiError(response, "Approve step-up failed"));
  }
  const body = (await response.json()) as { step_up: StepUpRequestState };
  return body.step_up;
}

export async function rejectStepUp(
  apiUrl: string,
  stepUpId: string,
  decisionNote = "",
): Promise<StepUpRequestState> {
  const response = await fetch(
    `${apiUrl}/v1/visualizer/step-ups/${encodeURIComponent(stepUpId)}/reject`,
    {
      method: "POST",
      headers: controlHeaders(true),
      body: JSON.stringify({ decided_by: "local_user", decision_note: decisionNote }),
    },
  );
  if (!response.ok) {
    throw new Error(await readApiError(response, "Reject step-up failed"));
  }
  const body = (await response.json()) as { step_up: StepUpRequestState };
  return body.step_up;
}
