"use client";

import { useEffect, useMemo, useState } from "react";
import {
  createLocalResource,
  revokeLocalResource,
} from "../../lib/visualizer-api";
import type { LocalResourceGrantState } from "../../types/visualizer";

const MAX_RESOURCE_BYTES = 20 * 1024 * 1024;

type ResourceGrantPanelProps = {
  apiUrl: string;
  resources: LocalResourceGrantState[];
  pageUrl: string;
  activeAgentId: string | null;
  profileId: string;
  disabled?: boolean;
  onChanged: () => Promise<void> | void;
  onMessage: (message: string) => void;
  onError: (message: string) => void;
};

export function ResourceGrantPanel({
  apiUrl,
  resources,
  pageUrl,
  activeAgentId,
  profileId,
  disabled = false,
  onChanged,
  onMessage,
  onError,
}: ResourceGrantPanelProps) {
  const [file, setFile] = useState<File | null>(null);
  const [purpose, setPurpose] = useState("agent_upload");
  const [origin, setOrigin] = useState(() => originFromUrl(pageUrl));
  const [owner, setOwner] = useState<"agent" | "user" | "shared">("user");
  const [maxUses, setMaxUses] = useState(1);
  const [expiresInSeconds, setExpiresInSeconds] = useState(3600);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const next = originFromUrl(pageUrl);
    if (next) setOrigin(next);
  }, [pageUrl]);

  const activeResources = useMemo(
    () => resources.filter((item) => item.status !== "revoked"),
    [resources],
  );

  async function submitGrant() {
    if (!file) {
      onError("请选择需要授权的文件");
      return;
    }
    if (file.size > MAX_RESOURCE_BYTES) {
      onError("文件超过 20 MiB 的 P11.6 上限");
      return;
    }
    if (!purpose.trim() || !origin.trim()) {
      onError("用途和目标 Origin 均为必填项");
      return;
    }

    setBusy(true);
    try {
      const contentBase64 = await fileToBase64(file);
      const created = await createLocalResource(apiUrl, {
        display_name: file.name,
        content_base64: contentBase64,
        owner,
        purpose: purpose.trim(),
        allowed_origins: [origin.trim()],
        bound_agent_ids: activeAgentId ? [activeAgentId] : [],
        bound_profile_ids: profileId ? [profileId] : [],
        expires_in_seconds: expiresInSeconds,
        max_uses: maxUses,
      });
      setFile(null);
      const input = document.getElementById("webfa-resource-file") as HTMLInputElement | null;
      if (input) input.value = "";
      onMessage(`资源授权已创建：${created.grant.resource_ref}`);
      await onChanged();
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function revoke(resourceRef: string) {
    setBusy(true);
    try {
      await revokeLocalResource(apiUrl, resourceRef);
      onMessage("资源授权已撤销");
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
        <input
          id="webfa-resource-file"
          type="file"
          disabled={disabled || busy}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          style={{ width: "100%", fontSize: 12 }}
        />
        <input
          className="viz-input"
          value={purpose}
          onChange={(event) => setPurpose(event.target.value)}
          placeholder="用途，例如 submit_application"
          disabled={disabled || busy}
        />
        <input
          className="viz-input"
          value={origin}
          onChange={(event) => setOrigin(event.target.value)}
          placeholder="允许的 Origin，例如 https://example.com"
          disabled={disabled || busy}
        />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <select
            className="viz-input"
            value={owner}
            onChange={(event) => setOwner(event.target.value as "agent" | "user" | "shared")}
            disabled={disabled || busy}
          >
            <option value="user">用户资源</option>
            <option value="agent">Agent 资源</option>
            <option value="shared">共享资源</option>
          </select>
          <input
            className="viz-input"
            type="number"
            min={1}
            max={100}
            value={maxUses}
            onChange={(event) => setMaxUses(Math.max(1, Number(event.target.value) || 1))}
            title="最大使用次数"
            disabled={disabled || busy}
          />
        </div>
        <select
          className="viz-input"
          value={expiresInSeconds}
          onChange={(event) => setExpiresInSeconds(Number(event.target.value))}
          disabled={disabled || busy}
        >
          <option value={900}>15 分钟有效</option>
          <option value={3600}>1 小时有效</option>
          <option value={21600}>6 小时有效</option>
          <option value={86400}>24 小时有效</option>
        </select>
        <div style={{ fontSize: 11, opacity: 0.72, lineHeight: 1.45 }}>
          文件会复制到 WebFA 管理目录。Agent 只能获得 resource_ref，不能读取本地绝对路径。
          {activeAgentId ? ` 绑定 Agent：${activeAgentId}。` : " 当前未绑定具体 Agent。"}
        </div>
        <button
          type="button"
          className="viz-btn viz-btn-primary"
          disabled={disabled || busy || !file}
          onClick={() => void submitGrant()}
        >
          {busy ? "处理中…" : "创建资源授权"}
        </button>
      </div>

      {activeResources.length > 0 && (
        <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
          {activeResources.map((item) => (
            <div
              key={item.grant.resource_ref}
              style={{
                border: "1px solid rgba(127,127,127,.25)",
                borderRadius: 8,
                padding: 8,
                fontSize: 11,
                lineHeight: 1.45,
              }}
            >
              <div style={{ fontWeight: 600 }}>{item.grant.display_name}</div>
              <div>{item.status} · 剩余 {item.remaining_uses}/{item.grant.max_uses}</div>
              <div style={{ overflowWrap: "anywhere", opacity: 0.75 }}>{item.grant.resource_ref}</div>
              <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                <button
                  type="button"
                  className="viz-btn"
                  onClick={() => void navigator.clipboard.writeText(item.grant.resource_ref)}
                >
                  复制引用
                </button>
                <button
                  type="button"
                  className="viz-btn viz-btn-warning"
                  disabled={busy}
                  onClick={() => void revoke(item.grant.resource_ref)}
                >
                  撤销
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
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

async function fileToBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const chunks: string[] = [];
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    const chunk = bytes.subarray(offset, Math.min(offset + chunkSize, bytes.length));
    chunks.push(String.fromCharCode(...chunk));
  }
  return btoa(chunks.join(""));
}
