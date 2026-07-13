"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  cancelCookieImport,
  closeProfileSession,
  commitCookieImport,
  fetchProfiles,
  previewCookieImport,
} from "../../lib/visualizer-api";
import type {
  BrowserProfileCatalogItem,
  CookieImportPreview,
} from "../../types/profile-bootstrap";

const MAX_COOKIE_FILE_BYTES = 5 * 1024 * 1024;

type ProfileBootstrapPanelProps = {
  apiUrl: string;
  currentProfileId: string;
  disabled?: boolean;
  onChanged: () => Promise<void> | void;
  onMessage: (message: string) => void;
  onError: (message: string) => void;
};

export function ProfileBootstrapPanel({
  apiUrl,
  currentProfileId,
  disabled = false,
  onChanged,
  onMessage,
  onError,
}: ProfileBootstrapPanelProps) {
  const [profiles, setProfiles] = useState<BrowserProfileCatalogItem[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState(currentProfileId || "default");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<CookieImportPreview | null>(null);
  const [busy, setBusy] = useState(false);

  const availableProfiles = useMemo(
    () => profiles.filter((profile) => profile.catalog_state === "ready" && profile.persistence === "persistent"),
    [profiles],
  );
  const selectedProfile = useMemo(
    () => availableProfiles.find((profile) => profile.profile_id === selectedProfileId) ?? null,
    [availableProfiles, selectedProfileId],
  );

  const loadProfiles = useCallback(async () => {
    if (disabled) return;
    try {
      const next = await fetchProfiles(apiUrl);
      setProfiles(next);
      const readyIds = new Set(
        next
          .filter((profile) => profile.catalog_state === "ready" && profile.persistence === "persistent")
          .map((profile) => profile.profile_id),
      );
      setSelectedProfileId((current) => {
        if (readyIds.has(current)) return current;
        if (readyIds.has(currentProfileId)) return currentProfileId;
        return next.find((profile) => readyIds.has(profile.profile_id))?.profile_id ?? "";
      });
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    }
  }, [apiUrl, currentProfileId, disabled, onError]);

  useEffect(() => {
    void loadProfiles();
  }, [loadProfiles]);

  async function clearPreview({ notify = false }: { notify?: boolean } = {}) {
    const current = preview;
    setPreview(null);
    if (!current) return;
    try {
      await cancelCookieImport(apiUrl, current.profile_id, current.preview_token);
      if (notify) onMessage("Cookie 导入预览已取消，原始数据已从 Runtime 内存清除");
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    }
  }

  async function selectFile(nextFile: File | null) {
    if (preview) await clearPreview();
    setFile(nextFile);
  }

  async function selectProfile(profileId: string) {
    if (preview) await clearPreview();
    setSelectedProfileId(profileId);
  }

  async function createPreview() {
    if (!selectedProfile) {
      onError("请选择一个可维护的持久 Profile");
      return;
    }
    if (!file) {
      onError("请选择 Cookie JSON 或 Netscape cookies.txt 文件");
      return;
    }
    if (file.size > MAX_COOKIE_FILE_BYTES) {
      onError("Cookie 文件超过 5 MiB 上限");
      return;
    }

    setBusy(true);
    try {
      const next = await previewCookieImport(
        apiUrl,
        selectedProfile.profile_id,
        selectedProfile.version,
        file,
      );
      setPreview(next);
      onMessage(`预览完成：可导入 ${next.accepted_count} 条，拒绝 ${next.rejected_count} 条`);
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function closeSession() {
    if (!selectedProfile) return;
    setBusy(true);
    try {
      const result = await closeProfileSession(apiUrl, selectedProfile.profile_id);
      onMessage(result.status === "session_closed" ? "目标 Profile 会话已关闭" : "目标 Profile 当前未运行");
      await onChanged();
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function commit() {
    if (!preview) return;
    const confirmed = window.confirm(
      `将 ${preview.accepted_count} 条 Cookie 写入 Profile。此操作只表示 cookies_imported，不保证网站登录已恢复。继续吗？`,
    );
    if (!confirmed) return;

    setBusy(true);
    try {
      const result = await commitCookieImport(apiUrl, preview);
      setPreview(null);
      setFile(null);
      const input = document.getElementById("webfa-cookie-import-file") as HTMLInputElement | null;
      if (input) input.value = "";
      onMessage(`Cookie 已写入并验证：${result.verified_count}/${result.imported_count}`);
      await loadProfiles();
      await onChanged();
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="viz-column-content" style={{ paddingTop: 0 }}>
      <div className="viz-control-stack">
        <select
          className="viz-input"
          value={selectedProfileId}
          disabled={disabled || busy || availableProfiles.length === 0}
          onChange={(event) => void selectProfile(event.target.value)}
        >
          {availableProfiles.map((profile) => (
            <option key={profile.profile_id} value={profile.profile_id}>
              {profile.display_name} · {profile.agent_alias} · {profile.bootstrap_source} · v{profile.version}
            </option>
          ))}
        </select>

        <input
          id="webfa-cookie-import-file"
          type="file"
          accept=".json,.txt,.cookies"
          disabled={disabled || busy || !selectedProfile}
          onChange={(event) => void selectFile(event.target.files?.[0] ?? null)}
          style={{ width: "100%", fontSize: 12 }}
        />

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <button
            type="button"
            className="viz-btn"
            disabled={disabled || busy || !selectedProfile}
            onClick={() => void closeSession()}
          >
            关闭目标会话
          </button>
          <button
            type="button"
            className="viz-btn viz-btn-primary"
            disabled={disabled || busy || !file || !selectedProfile || preview !== null}
            onClick={() => void createPreview()}
          >
            {busy ? "处理中…" : "生成脱敏预览"}
          </button>
        </div>

        <div style={{ fontSize: 11, opacity: 0.72, lineHeight: 1.45 }}>
          支持常见 Cookie JSON 与 Netscape cookies.txt。文件内容不会进入 Agent State、Monitor、SafetyReceipt 或日志返回。
          导入前目标 Profile 必须没有活动 Session。
        </div>
      </div>

      {preview && (
        <div
          style={{
            border: "1px solid rgba(127,127,127,.28)",
            borderRadius: 8,
            padding: 9,
            marginTop: 10,
            fontSize: 11,
            lineHeight: 1.5,
          }}
        >
          <div style={{ fontWeight: 650, marginBottom: 4 }}>Cookie 导入预览</div>
          <div>
            {preview.source_format} · 接受 {preview.accepted_count}/{preview.total_entries} · 拒绝 {preview.rejected_count}
          </div>
          <div>
            域 {preview.domain_count} · Secure {preview.secure_count} · HttpOnly {preview.http_only_count} · 分区 {preview.partitioned_count}
          </div>
          <div>
            会话 Cookie {preview.session_count} · 持久 Cookie {preview.persistent_count}
          </div>
          {preview.domains.length > 0 && (
            <div style={{ marginTop: 5, opacity: 0.78, overflowWrap: "anywhere" }}>
              {preview.domains.slice(0, 12).join(" · ")}
              {preview.domains.length > 12 ? ` · +${preview.domains.length - 12}` : ""}
            </div>
          )}
          {preview.warnings.length > 0 && (
            <div style={{ marginTop: 5, opacity: 0.78 }}>
              {preview.warnings.map((warning) => `${warningLabel(warning.code)} ×${warning.count}`).join("；")}
            </div>
          )}
          <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
            <button
              type="button"
              className="viz-btn viz-btn-primary"
              disabled={busy}
              onClick={() => void commit()}
            >
              确认导入
            </button>
            <button
              type="button"
              className="viz-btn"
              disabled={busy}
              onClick={() => void clearPreview({ notify: true })}
            >
              取消并清除
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function warningLabel(code: string): string {
  const labels: Record<string, string> = {
    cookie_expired: "已过期",
    duplicate_cookie_replaced: "重复项已覆盖",
    entry_not_object: "无效 JSON 项",
    netscape_line_invalid: "无效 Netscape 行",
    same_site_none_requires_secure: "SameSite=None 但非 Secure",
    domain_normalized: "域名已规范化",
    domain_list_truncated: "域名列表已截断",
  };
  return labels[code] ?? code;
}
