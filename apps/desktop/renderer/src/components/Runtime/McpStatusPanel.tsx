"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchMcpClientConfig, fetchMcpRuntimeStatus } from "../../lib/visualizer-api";
import type { McpClientConfig, McpRuntimeStatus } from "../../types/mcp";
import type { RuntimeState } from "../../types/webfa-desktop";

type McpStatusPanelProps = {
  apiUrl: string;
  runtimeState: RuntimeState;
  activeAgentId: string | null;
  leaseExpiresAt: string | null;
};

const MCP_REFRESH_MS = 5000;

function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

function commandLabel(config: McpClientConfig | null): string {
  if (!config) return "等待 Runtime 配置";
  const { command, args } = config.mcpServers.webfa;
  return [command, ...args].join(" ");
}

function leasePresentation(activeAgentId: string | null, leaseExpiresAt: string | null) {
  if (!activeAgentId) {
    return { label: "未连接", detail: "当前没有外部 Agent 持有 Session", active: false };
  }
  if (!leaseExpiresAt) {
    return { label: "未生效", detail: `${activeAgentId} · Runtime 未报告有效期`, active: false };
  }

  const expiresAt = Date.parse(leaseExpiresAt);
  if (!Number.isFinite(expiresAt)) {
    return { label: "状态未知", detail: `${activeAgentId} · 无法解析租约有效期`, active: false };
  }
  if (expiresAt <= Date.now()) {
    return {
      label: "已过期",
      detail: `${activeAgentId} · ${new Date(expiresAt).toLocaleString()}`,
      active: false,
    };
  }
  return {
    label: "有效",
    detail: `${activeAgentId} · 至 ${new Date(expiresAt).toLocaleString()}`,
    active: true,
  };
}

export function McpStatusPanel({
  apiUrl,
  runtimeState,
  activeAgentId,
  leaseExpiresAt,
}: McpStatusPanelProps) {
  const [status, setStatus] = useState<McpRuntimeStatus | null>(null);
  const [config, setConfig] = useState<McpClientConfig | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [copyMessage, setCopyMessage] = useState<string | null>(null);
  const lease = useMemo(
    () => leasePresentation(activeAgentId, leaseExpiresAt),
    [activeAgentId, leaseExpiresAt],
  );

  useEffect(() => {
    if (runtimeState !== "running") {
      setStatus(null);
      setConfig(null);
      setLoadError(null);
      return;
    }

    const controller = new AbortController();
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function refresh() {
      const [statusResult, configResult] = await Promise.allSettled([
        fetchMcpRuntimeStatus(apiUrl, controller.signal),
        fetchMcpClientConfig(apiUrl, controller.signal),
      ]);
      if (disposed) return;

      if (statusResult.status === "fulfilled") {
        setStatus(statusResult.value);
      } else if (statusResult.reason?.name !== "AbortError") {
        setStatus(null);
      }

      if (configResult.status === "fulfilled") {
        setConfig(configResult.value);
      } else if (configResult.reason?.name !== "AbortError") {
        setConfig(null);
      }

      const failures = [statusResult, configResult]
        .filter((result): result is PromiseRejectedResult => result.status === "rejected")
        .filter((result) => result.reason?.name !== "AbortError")
        .map((result) => errorMessage(result.reason));
      setLoadError(failures.length > 0 ? failures.join(" · ") : null);
      timer = setTimeout(() => void refresh(), MCP_REFRESH_MS);
    }

    void refresh();
    return () => {
      disposed = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [apiUrl, runtimeState]);

  useEffect(() => {
    if (!copyMessage) return;
    const timer = setTimeout(() => setCopyMessage(null), 2400);
    return () => clearTimeout(timer);
  }, [copyMessage]);

  async function copyConfig() {
    if (!config) {
      setCopyMessage("MCP 配置尚不可用");
      return;
    }
    try {
      await navigator.clipboard.writeText(JSON.stringify(config, null, 2));
      setCopyMessage("MCP 客户端配置已复制");
    } catch {
      setCopyMessage("复制 MCP 配置失败");
    }
  }

  const capabilityAvailable = runtimeState === "running" && status?.status === "available";

  return (
    <div className="viz-column-content viz-column-content-tight-top">
      <div className="viz-status-group">
        <div className="viz-status-card">
          <div className="viz-status-label">MCP capability</div>
          <div className="viz-status-value">
            <span className={`viz-indicator-dot${capabilityAvailable ? " pulse" : ""}`} aria-hidden="true" />
            {runtimeState !== "running" ? "Runtime 离线" : capabilityAvailable ? "可连接" : "检查中"}
          </div>
          <div className="viz-status-subtext">
            {status ? `${status.transport} · 由外部 Agent 客户端持有` : "未建立 Desktop MCP 进程"}
          </div>
          {status && (
            <div className="viz-mcp-tools" aria-label={`${status.tools.length} 个 MCP tools`}>
              {status.tools.map((tool) => <code key={tool}>{tool}</code>)}
            </div>
          )}
        </div>

        <div className="viz-status-card">
          <div className="viz-status-label">External Agent lease</div>
          <div className="viz-status-value">
            <span className={`viz-indicator-dot${lease.active ? " pulse" : ""}`} aria-hidden="true" />
            {lease.label}
          </div>
          <div className="viz-status-subtext">{lease.detail}</div>
        </div>

        <div className="viz-status-card">
          <div className="viz-status-label">MCP client config</div>
          <div className="viz-mcp-command" title={commandLabel(config)}>{commandLabel(config)}</div>
          <button
            type="button"
            className="viz-btn viz-mcp-copy-btn"
            onClick={() => void copyConfig()}
            disabled={!config}
          >
            复制 MCP 客户端配置
          </button>
          <div className="viz-mcp-note">
            由外部 Agent 的 MCP 客户端启动 stdio bridge；WebFA Desktop 不运行或替代 Agent。
            复制后请为每个客户端设置不同的 WEBFA_AGENT_ID。
          </div>
        </div>

        {loadError && runtimeState === "running" && (
          <div className="viz-status-card viz-status-card-warn">
            <div className="viz-status-label">MCP status unavailable</div>
            <div className="viz-status-subtext">{loadError}</div>
          </div>
        )}
      </div>
      <div className="viz-mcp-copy-status" role="status" aria-live="polite">
        {copyMessage}
      </div>
    </div>
  );
}
