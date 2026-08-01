"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  cancelCookieImport,
  cancelProfileBundleExport,
  cancelProfileBundleRestore,
  cancelProfileClone,
  closeProfileSession,
  commitCookieImport,
  commitProfileBundleRestore,
  commitProfileClone,
  downloadProfileBundleFallback,
  fetchProfiles,
  previewCookieImport,
  previewProfileBundleExport,
  previewProfileBundleRestoreFallback,
  previewProfileClone,
} from "../../lib/visualizer-api";
import type {
  BrowserProfileCatalogItem,
  CookieImportPreview,
  ProfileBundleExportPreview,
  ProfileBundleRestorePreview,
  ProfileClonePreview,
} from "../../types/profile-bootstrap";

const MAX_COOKIE_FILE_BYTES = 5 * 1024 * 1024;
const MAX_BROWSER_BUNDLE_BYTES = 256 * 1024 * 1024;

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
  const [clonePreview, setClonePreview] = useState<ProfileClonePreview | null>(null);
  const [cloneAlias, setCloneAlias] = useState("");
  const [cloneDisplayName, setCloneDisplayName] = useState("");
  const [bundleExportPreview, setBundleExportPreview] = useState<ProfileBundleExportPreview | null>(null);
  const [bundleExportPassphrase, setBundleExportPassphrase] = useState("");
  const [bundleExportConfirm, setBundleExportConfirm] = useState("");
  const [bundleRestorePreview, setBundleRestorePreview] = useState<ProfileBundleRestorePreview | null>(null);
  const [bundleRestoreFile, setBundleRestoreFile] = useState<File | null>(null);
  const [bundleRestoreFileName, setBundleRestoreFileName] = useState("");
  const [bundleRestorePassphrase, setBundleRestorePassphrase] = useState("");
  const [bundleRestoreCommitPassphrase, setBundleRestoreCommitPassphrase] = useState("");
  const [bundleRestoreAlias, setBundleRestoreAlias] = useState("");
  const [bundleRestoreDisplayName, setBundleRestoreDisplayName] = useState("");
  const [desktopBundleAvailable, setDesktopBundleAvailable] = useState(false);
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
    setDesktopBundleAvailable(Boolean(window.webfaDesktop?.previewProfileBundleRestore));
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

  async function clearClonePreview({ notify = false }: { notify?: boolean } = {}) {
    const current = clonePreview;
    setClonePreview(null);
    if (!current) return;
    try {
      await cancelProfileClone(apiUrl, current.source_profile_id, current.preview_token);
      if (notify) onMessage("Profile clone 预览已取消");
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    }
  }

  async function clearBundleExportPreview({ notify = false }: { notify?: boolean } = {}) {
    const current = bundleExportPreview;
    setBundleExportPreview(null);
    setBundleExportPassphrase("");
    setBundleExportConfirm("");
    if (!current) return;
    try {
      await cancelProfileBundleExport(apiUrl, current.source_profile_id, current.preview_token);
      if (notify) onMessage("Profile Bundle 导出预览已取消");
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    }
  }

  async function clearBundleRestorePreview({ notify = false }: { notify?: boolean } = {}) {
    const current = bundleRestorePreview;
    setBundleRestorePreview(null);
    setBundleRestoreFile(null);
    setBundleRestoreFileName("");
    setBundleRestoreCommitPassphrase("");
    setBundleRestoreAlias("");
    setBundleRestoreDisplayName("");
    if (!current) return;
    try {
      await cancelProfileBundleRestore(apiUrl, current.preview_token);
      if (notify) onMessage("Profile Bundle 恢复预览已取消并清除临时文件");
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
    if (clonePreview) await clearClonePreview();
    if (bundleExportPreview) await clearBundleExportPreview();
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

  async function createClonePreview() {
    if (!selectedProfile) {
      onError("请选择需要克隆的持久 Profile");
      return;
    }
    setBusy(true);
    try {
      const next = await previewProfileClone(
        apiUrl,
        selectedProfile.profile_id,
        selectedProfile.version,
      );
      setClonePreview(next);
      if (!cloneAlias) setCloneAlias(`${selectedProfile.agent_alias}-copy`);
      if (!cloneDisplayName) setCloneDisplayName(`${selectedProfile.display_name} Copy`);
      onMessage(`Clone 预览完成：${next.file_count} 个文件，${formatBytes(next.total_bytes)}`);
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function commitClone() {
    if (!clonePreview) return;
    if (!cloneAlias.trim() || !cloneDisplayName.trim()) {
      onError("新 Profile 的别名和显示名称均为必填项");
      return;
    }
    const confirmed = window.confirm(
      `将源 Profile 的浏览器存储复制为新 Profile“${cloneDisplayName.trim()}”。Agent 授权与 Safety/Financial policy 不会继承。继续吗？`,
    );
    if (!confirmed) return;

    setBusy(true);
    try {
      const result = await commitProfileClone(apiUrl, clonePreview, {
        agent_alias: cloneAlias.trim(),
        display_name: cloneDisplayName.trim(),
        owner: "user_owned",
        trust_mode: "guarded",
      });
      setClonePreview(null);
      setCloneAlias("");
      setCloneDisplayName("");
      onMessage(`Profile 已克隆：${result.target_agent_alias} · ${formatBytes(result.total_bytes)}`);
      await loadProfiles();
      await onChanged();
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function createBundleExportPreview() {
    if (!selectedProfile) {
      onError("请选择需要导出的持久 Profile");
      return;
    }
    setBusy(true);
    try {
      const next = await previewProfileBundleExport(
        apiUrl,
        selectedProfile.profile_id,
        selectedProfile.version,
      );
      setBundleExportPreview(next);
      onMessage(`Bundle 导出预览完成：${next.file_count} 个文件，${formatBytes(next.total_bytes)}`);
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function saveBundleExport() {
    if (!bundleExportPreview) return;
    if (bundleExportPassphrase.length < 12) {
      onError("Bundle 口令至少需要 12 个字符");
      return;
    }
    if (bundleExportPassphrase !== bundleExportConfirm) {
      onError("两次输入的 Bundle 口令不一致");
      return;
    }
    setBusy(true);
    try {
      if (window.webfaDesktop?.saveProfileBundle) {
        const result = await window.webfaDesktop.saveProfileBundle({
          profileId: bundleExportPreview.source_profile_id,
          sourceVersion: bundleExportPreview.source_profile_version,
          previewToken: bundleExportPreview.preview_token,
          passphrase: bundleExportPassphrase,
          suggestedFilename: bundleExportPreview.suggested_filename,
        });
        if (result.status === "cancelled") {
          onMessage("已取消保存，导出预览仍可继续使用");
          return;
        }
        setBundleExportPreview(null);
        setBundleExportPassphrase("");
        setBundleExportConfirm("");
        onMessage(`加密 Bundle 已保存：${result.fileName} · ${formatBytes(result.byteCount)}`);
      } else {
        if (bundleExportPreview.total_bytes > MAX_BROWSER_BUNDLE_BYTES) {
          throw new Error("浏览器回退模式仅支持 256 MiB 以内的 Bundle，请使用 WebFA Desktop 流式导出");
        }
        const result = await downloadProfileBundleFallback(
          apiUrl,
          bundleExportPreview,
          bundleExportPassphrase,
        );
        const url = URL.createObjectURL(result.blob);
        try {
          const anchor = document.createElement("a");
          anchor.href = url;
          anchor.download = result.fileName;
          anchor.click();
        } finally {
          URL.revokeObjectURL(url);
        }
        setBundleExportPreview(null);
        setBundleExportPassphrase("");
        setBundleExportConfirm("");
        onMessage(`加密 Bundle 已生成：${result.fileName}`);
      }
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function createBundleRestorePreview() {
    if (bundleRestorePassphrase.length < 12) {
      onError("Bundle 口令至少需要 12 个字符");
      return;
    }
    setBusy(true);
    try {
      let next: ProfileBundleRestorePreview;
      let fileName: string;
      if (window.webfaDesktop?.previewProfileBundleRestore) {
        const result = await window.webfaDesktop.previewProfileBundleRestore({
          passphrase: bundleRestorePassphrase,
        });
        if (result.status === "cancelled") {
          onMessage("已取消选择 Bundle 文件");
          return;
        }
        next = result.preview as unknown as ProfileBundleRestorePreview;
        fileName = result.fileName;
      } else {
        if (!bundleRestoreFile) {
          onError("请选择 .webfa-profile 文件");
          return;
        }
        if (bundleRestoreFile.size > MAX_BROWSER_BUNDLE_BYTES) {
          onError("浏览器回退模式仅支持 256 MiB 以内的 Bundle，请使用 WebFA Desktop 流式恢复");
          return;
        }
        next = await previewProfileBundleRestoreFallback(
          apiUrl,
          bundleRestoreFile,
          bundleRestorePassphrase,
        );
        fileName = bundleRestoreFile.name;
      }
      setBundleRestorePreview(next);
      setBundleRestoreFileName(fileName);
      setBundleRestoreAlias(`${next.source_agent_alias}-restored`);
      setBundleRestoreDisplayName(`${next.source_display_name} Restored`);
      setBundleRestorePassphrase("");
      onMessage(`Bundle 已认证：${next.file_count} 个文件，${formatBytes(next.total_bytes)}`);
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function commitBundleRestore() {
    if (!bundleRestorePreview) return;
    if (!bundleRestoreAlias.trim() || !bundleRestoreDisplayName.trim()) {
      onError("恢复后的 Profile 别名和显示名称均为必填项");
      return;
    }
    if (bundleRestoreCommitPassphrase.length < 12) {
      onError("请重新输入 Bundle 口令以确认恢复");
      return;
    }
    const confirmed = window.confirm(
      `将已认证 Bundle 恢复为新 Profile“${bundleRestoreDisplayName.trim()}”。不会覆盖已有 Profile，也不会恢复 Agent 或安全策略绑定。继续吗？`,
    );
    if (!confirmed) return;
    setBusy(true);
    try {
      const result = await commitProfileBundleRestore(
        apiUrl,
        bundleRestorePreview,
        bundleRestoreCommitPassphrase,
        {
          agent_alias: bundleRestoreAlias.trim(),
          display_name: bundleRestoreDisplayName.trim(),
          owner: "user_owned",
          trust_mode: "guarded",
        },
      );
      setBundleRestorePreview(null);
      setBundleRestoreFile(null);
      setBundleRestoreFileName("");
      setBundleRestoreCommitPassphrase("");
      setBundleRestoreAlias("");
      setBundleRestoreDisplayName("");
      const input = document.getElementById("webfa-profile-bundle-file") as HTMLInputElement | null;
      if (input) input.value = "";
      onMessage(`Profile Bundle 已恢复：${result.target_agent_alias} · ${formatBytes(result.total_bytes)}`);
      await loadProfiles();
      await onChanged();
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="viz-column-content viz-column-content-tight-top" data-ui="profile-bootstrap-panel">
      <div className="viz-control-stack">
        <label className="viz-management-field">
          <span>维护 Profile</span>
          <select
            className="viz-input"
            aria-label="选择 Profile"
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
        </label>

        <label className="viz-management-field">
          <span>Cookie 文件</span>
          <input
            id="webfa-cookie-import-file"
            type="file"
            aria-label="选择 Cookie 导入文件"
            accept=".json,.txt,.cookies"
            disabled={disabled || busy || !selectedProfile}
            onChange={(event) => void selectFile(event.target.files?.[0] ?? null)}
            className="viz-file-input"
          />
        </label>

        <div className="viz-grid-2col">
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

        <div className="viz-field-note">
          支持常见 Cookie JSON 与 Netscape cookies.txt。文件内容不会进入 Agent State、Monitor、SafetyReceipt 或日志返回。
          导入前目标 Profile 必须没有活动 Session。
        </div>
      </div>

      {preview && (
        <div className="viz-preview-card">
          <div className="viz-preview-card-title">Cookie 导入预览</div>
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
            <div className="viz-preview-card-meta">
              {preview.domains.slice(0, 12).join(" · ")}
              {preview.domains.length > 12 ? ` · +${preview.domains.length - 12}` : ""}
            </div>
          )}
          {preview.warnings.length > 0 && (
            <div className="viz-preview-card-meta">
              {preview.warnings.map((warning) => `${warningLabel(warning.code)} ×${warning.count}`).join("；")}
            </div>
          )}
          <div className="viz-preview-card-actions">
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

      <div className="viz-subsection">
        <div className="viz-subsection-title">Clone Profile</div>
        <div className="viz-control-stack">
          <label className="viz-management-field">
            <span>新 Profile 别名</span>
            <input
              className="viz-input"
              aria-label="新 Profile 别名"
              value={cloneAlias}
              onChange={(event) => setCloneAlias(event.target.value)}
              placeholder="例如 work-copy"
              disabled={disabled || busy || clonePreview === null}
            />
          </label>
          <label className="viz-management-field">
            <span>显示名称</span>
            <input
              className="viz-input"
              aria-label="新 Profile 显示名称"
              value={cloneDisplayName}
              onChange={(event) => setCloneDisplayName(event.target.value)}
              placeholder="用于本地识别，不暴露给 Agent"
              disabled={disabled || busy || clonePreview === null}
            />
          </label>
          <div className="viz-grid-2col">
            <button
              type="button"
              className="viz-btn viz-btn-primary"
              disabled={disabled || busy || !selectedProfile || clonePreview !== null || preview !== null}
              onClick={() => void createClonePreview()}
            >
              生成 Clone 预览
            </button>
            <button
              type="button"
              className="viz-btn"
              disabled={disabled || busy || !selectedProfile}
              onClick={() => void closeSession()}
            >
              关闭源会话
            </button>
          </div>
          <div className="viz-field-note">
            Clone 会复制源 Profile 的浏览器身份与网站存储，但不会继承 Agent bindings、允许 Origin、Safety policy 或 Financial policy。
          </div>
        </div>
      </div>

      {clonePreview && (
        <div className="viz-preview-card">
          <div className="viz-preview-card-title">Profile Clone 预览</div>
          <div>源：{clonePreview.source_agent_alias} · v{clonePreview.source_profile_version}</div>
          <div>
            文件 {clonePreview.file_count} · {formatBytes(clonePreview.total_bytes)} · 排除运行时项 {clonePreview.excluded_count}
          </div>
          <div className="viz-preview-card-actions">
            <button
              type="button"
              className="viz-btn viz-btn-primary"
              disabled={busy || !cloneAlias.trim() || !cloneDisplayName.trim()}
              onClick={() => void commitClone()}
            >
              确认克隆
            </button>
            <button
              type="button"
              className="viz-btn"
              disabled={busy}
              onClick={() => void clearClonePreview({ notify: true })}
            >
              取消
            </button>
          </div>
        </div>
      )}

      <div className="viz-subsection">
        <div className="viz-subsection-title">Encrypted Profile Bundle</div>
        <div className="viz-field-note viz-field-note-spaced">
          `.webfa-profile` 使用 Scrypt + AES-256-GCM 加密经筛选的网站身份状态。它不包含密码、自动填充、历史、书签、标签页或扩展；恢复只创建新 Profile，也不恢复 Agent 或 Safety/Financial policy 绑定。
        </div>

        <div className="viz-control-stack">
          <div className="viz-subsection-compact-title">Export selected Profile</div>
          <div className="viz-grid-2col">
            <button
              type="button"
              className="viz-btn viz-btn-primary"
              disabled={
                disabled ||
                busy ||
                !selectedProfile ||
                bundleExportPreview !== null ||
                preview !== null ||
                clonePreview !== null
              }
              onClick={() => void createBundleExportPreview()}
            >
              生成导出预览
            </button>
            <button
              type="button"
              className="viz-btn"
              disabled={disabled || busy || !selectedProfile}
              onClick={() => void closeSession()}
            >
              关闭源会话
            </button>
          </div>
        </div>

        {bundleExportPreview && (
          <div className="viz-preview-card">
            <div className="viz-preview-card-title">Bundle 导出预览</div>
            <div>
              {bundleExportPreview.source_display_name} · {bundleExportPreview.file_count} 个文件 · {formatBytes(bundleExportPreview.total_bytes)}
            </div>
            <div>排除运行时项 {bundleExportPreview.excluded_count} · {bundleExportPreview.suggested_filename}</div>
            <label className="viz-management-field viz-field-mt">
              <span>Bundle 加密口令</span>
              <input
                className="viz-input"
                type="password"
                aria-label="Profile Bundle 加密口令"
                autoComplete="new-password"
                value={bundleExportPassphrase}
                onChange={(event) => setBundleExportPassphrase(event.target.value)}
                placeholder="至少 12 个字符"
                disabled={busy}
              />
            </label>
            <label className="viz-management-field viz-field-mt-sm">
              <span>确认加密口令</span>
              <input
                className="viz-input"
                type="password"
                aria-label="确认 Profile Bundle 加密口令"
                autoComplete="new-password"
                value={bundleExportConfirm}
                onChange={(event) => setBundleExportConfirm(event.target.value)}
                placeholder="再次输入"
                disabled={busy}
              />
            </label>
            <div className="viz-preview-card-actions">
              <button
                type="button"
                className="viz-btn viz-btn-primary"
                disabled={
                  busy ||
                  bundleExportPassphrase.length < 12 ||
                  bundleExportPassphrase !== bundleExportConfirm
                }
                onClick={() => void saveBundleExport()}
              >
                加密并保存
              </button>
              <button
                type="button"
                className="viz-btn"
                disabled={busy}
                onClick={() => void clearBundleExportPreview({ notify: true })}
              >
                取消
              </button>
            </div>
          </div>
        )}

        <div className="viz-subsection-compact">
          <div className="viz-subsection-compact-title">Restore encrypted Bundle</div>
          {!desktopBundleAvailable && (
            <label className="viz-management-field viz-field-mb">
              <span>加密 Bundle 文件</span>
              <input
                id="webfa-profile-bundle-file"
                type="file"
                aria-label="选择加密的 Profile Bundle"
                accept=".webfa-profile"
                disabled={disabled || busy || bundleRestorePreview !== null}
                onChange={(event) => {
                  const selected = event.target.files?.[0] ?? null;
                  setBundleRestoreFile(selected);
                  setBundleRestoreFileName(selected?.name ?? "");
                }}
                className="viz-file-input"
              />
            </label>
          )}
          <label className="viz-management-field">
            <span>Bundle 解密口令</span>
            <input
              className="viz-input"
              type="password"
              aria-label="Profile Bundle 解密口令"
              autoComplete="current-password"
              value={bundleRestorePassphrase}
              onChange={(event) => setBundleRestorePassphrase(event.target.value)}
              placeholder="输入口令以认证文件"
              disabled={disabled || busy || bundleRestorePreview !== null}
            />
          </label>
          <button
            type="button"
            className="viz-btn viz-btn-primary viz-field-mt-sm"
            disabled={
              disabled ||
              busy ||
              bundleRestorePreview !== null ||
              bundleRestorePassphrase.length < 12 ||
              (!desktopBundleAvailable && !bundleRestoreFile)
            }
            onClick={() => void createBundleRestorePreview()}
          >
            {desktopBundleAvailable ? "选择并认证 Bundle" : "认证 Bundle"}
          </button>
        </div>

        {bundleRestorePreview && (
          <div className="viz-preview-card">
            <div className="viz-preview-card-title">Bundle 恢复预览</div>
            <div>{bundleRestoreFileName || "Encrypted Bundle"}</div>
            <div>
              来源：{bundleRestorePreview.source_display_name} · {bundleRestorePreview.source_agent_alias} · {bundleRestorePreview.source_bootstrap_source}
            </div>
            <div>
              格式 v{bundleRestorePreview.bundle_format_version} · {bundleRestorePreview.file_count} 个文件 · {formatBytes(bundleRestorePreview.total_bytes)}
            </div>
            <div className="viz-preview-card-meta">
              {bundleRestorePreview.source_platform} → {bundleRestorePreview.current_platform}
            </div>
            <div className="viz-preview-card-meta">
              {bundleRestorePreview.compatibility_warning}
            </div>
            <label className="viz-management-field viz-field-mt">
              <span>新 Profile 别名</span>
              <input
                className="viz-input"
                aria-label="恢复后的 Profile 别名"
                value={bundleRestoreAlias}
                onChange={(event) => setBundleRestoreAlias(event.target.value)}
                placeholder="恢复后的新别名"
                disabled={busy}
              />
            </label>
            <label className="viz-management-field viz-field-mt-sm">
              <span>显示名称</span>
              <input
                className="viz-input"
                aria-label="恢复后的 Profile 显示名称"
                value={bundleRestoreDisplayName}
                onChange={(event) => setBundleRestoreDisplayName(event.target.value)}
                placeholder="用于本地识别"
                disabled={busy}
              />
            </label>
            <label className="viz-management-field viz-field-mt-sm">
              <span>再次确认 Bundle 口令</span>
              <input
                className="viz-input"
                type="password"
                aria-label="确认恢复的 Profile Bundle 口令"
                autoComplete="current-password"
                value={bundleRestoreCommitPassphrase}
                onChange={(event) => setBundleRestoreCommitPassphrase(event.target.value)}
                placeholder="重新输入以确认恢复"
                disabled={busy}
              />
            </label>
            <div className="viz-preview-card-actions">
              <button
                type="button"
                className="viz-btn viz-btn-primary"
                disabled={
                  busy ||
                  !bundleRestoreAlias.trim() ||
                  !bundleRestoreDisplayName.trim() ||
                  bundleRestoreCommitPassphrase.length < 12
                }
                onClick={() => void commitBundleRestore()}
              >
                恢复为新 Profile
              </button>
              <button
                type="button"
                className="viz-btn"
                disabled={busy}
                onClick={() => void clearBundleRestorePreview({ notify: true })}
              >
                取消并清除
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  const units = ["KiB", "MiB", "GiB", "TiB"];
  let size = value / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && size >= 1024; index += 1) {
    size /= 1024;
    unit = units[index];
  }
  return `${size >= 10 ? size.toFixed(1) : size.toFixed(2)} ${unit}`;
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
