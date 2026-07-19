import type { VisualizerState } from "../../types/visualizer";
import type { RuntimeState, RuntimeStatus } from "../../types/webfa-desktop";
import { presentRuntimeIssue } from "../../lib/runtime-presentation";

type StatusPanelProps = {
  state: VisualizerState | null;
  runtimeState: RuntimeState;
  desktopStatus: RuntimeStatus | null;
  apiUrl: string;
};

function hostLabel(status: string | undefined): string {
  if (status === "running") return "运行中";
  if (status === "exited") return "已关闭";
  if (status === "error") return "异常";
  return "未启动";
}

function ownershipLabel(status: RuntimeStatus | null): string {
  if (status?.ownership === "desktop") return "Desktop 持有";
  if (status?.ownership === "external") return "外部 Runtime";
  if (status?.ownership === "collision") return "端口冲突";
  return "未持有";
}

export function StatusPanel({ state, runtimeState, desktopStatus, apiUrl }: StatusPanelProps) {
  const online = runtimeState === "running" && state?.runtime.online;
  const lease = state?.agent.lease_expires_at;
  const browserMissing = state?.runtime.executable_found === false;
  const issue = presentRuntimeIssue(desktopStatus);
  const runtimeLabel = online
    ? "在线"
    : runtimeState === "starting"
      ? "启动中"
      : runtimeState === "error"
        ? "错误"
        : "离线";

  return (
    <div className="viz-column-content">
      <div className="viz-status-group">
        <div className="viz-status-card">
          <div className="viz-status-label">Runtime</div>
          <div className="viz-status-value">
            <span className={`viz-indicator-dot ${online ? "pulse" : runtimeState}`} />
            {runtimeLabel}
          </div>
          <div className="viz-status-subtext">{apiUrl}</div>
          {desktopStatus && (
            <div className="viz-status-subtext">
              {ownershipLabel(desktopStatus)}
              {desktopStatus.releaseVersion ? ` · v${desktopStatus.releaseVersion}` : ""}
            </div>
          )}
        </div>

        <div className="viz-status-card">
          <div className="viz-status-label">Driver / Host</div>
          <div className="viz-status-value">{state?.runtime.driver ?? "—"}</div>
          <div className="viz-status-subtext">
            {hostLabel(state?.runtime.host_status)} · {state?.runtime.visible_window ? "可见窗口" : state?.runtime.headless ? "无头" : "不可见"}
          </div>
          <div className="viz-status-subtext">
            {browserMissing
              ? "未发现 Chrome / Edge"
              : state?.runtime.executable_name
                ? `浏览器：${state.runtime.executable_name}`
                : "浏览器：等待检测"}
          </div>
        </div>

        {browserMissing && (
          <div className="viz-status-card viz-status-card-warn" role="alert">
            <div className="viz-status-label">Browser prerequisite</div>
            <div className="viz-status-value">需要安装 Chrome 或 Edge</div>
            <div className="viz-status-subtext">
              Runtime 保持在线，但外部 Agent 在浏览器可用前不能打开网页。安装 Chrome 或 Edge 后重新检测。
            </div>
          </div>
        )}

        {state?.runtime.last_error && (
          <div className="viz-status-card viz-status-card-warn" role="alert">
            <div className="viz-status-label">Browser host</div>
            <div className="viz-status-subtext">{state.runtime.last_error}</div>
          </div>
        )}

        <div className="viz-status-card">
          <div className="viz-status-label">External Agent</div>
          <div className="viz-status-value">{state?.agent.active_agent_id ?? "无"}</div>
          <div className="viz-status-subtext">
            Profile: {state?.profile.profile_id ?? "default"} · {state?.profile.owner ?? "shared"}
            {state?.profile.shared ? " (共享)" : ""}
          </div>
          <div className="viz-status-subtext">
            Trust: {state?.profile.trust_mode ?? "trusted_agent"} · Unknown: {state?.profile.unknown_external_effect_policy ?? "require_step_up"}
          </div>
        </div>

        {lease && (
          <div className="viz-status-card">
            <div className="viz-status-label">External Agent Lease</div>
            <div className="viz-status-value">{new Date(lease).toLocaleTimeString()}</div>
          </div>
        )}

        {(state?.errors.length ?? 0) > 0 && (
          <div className="viz-status-card viz-status-card-warn" role="alert">
            <div className="viz-status-label">Alerts</div>
            {state?.errors.map((error) => (
              <div key={error.code} className="viz-status-subtext">
                {error.code}: {error.message}
              </div>
            ))}
          </div>
        )}

        {issue && (
          <div className="viz-status-card viz-status-card-warn" role="alert">
            <div className="viz-status-label">Runtime boundary</div>
            <div className="viz-status-value">{issue.title}</div>
            <div className="viz-status-subtext">{issue.detail}</div>
          </div>
        )}
      </div>
    </div>
  );
}
