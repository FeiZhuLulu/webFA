import type { VisualizerState } from "../../types/visualizer";

type StatusPanelProps = {
  state: VisualizerState | null;
  runtimeState: "running" | "stopped" | "error";
  apiUrl: string;
};

function hostLabel(status: string | undefined): string {
  if (status === "running") return "运行中";
  if (status === "exited") return "已关闭";
  if (status === "error") return "异常";
  return "未启动";
}

export function StatusPanel({ state, runtimeState, apiUrl }: StatusPanelProps) {
  const online = runtimeState === "running" && state?.runtime.online;
  const lease = state?.agent.lease_expires_at;

  return (
    <div className="viz-column-content">
      <div className="viz-status-group">
        <div className="viz-status-card">
          <div className="viz-status-label">Runtime</div>
          <div className="viz-status-value">
            <span className={`viz-indicator-dot${online ? " pulse" : ""}`} />
            {online ? "在线" : runtimeState === "error" ? "错误" : "离线"}
          </div>
          <div className="viz-status-subtext">{apiUrl}</div>
        </div>

        <div className="viz-status-card">
          <div className="viz-status-label">Driver / Host</div>
          <div className="viz-status-value">{state?.runtime.driver ?? "—"}</div>
          <div className="viz-status-subtext">
            {hostLabel(state?.runtime.host_status)} · {state?.runtime.visible_window ? "可见窗口" : state?.runtime.headless ? "无头" : "不可见"}
          </div>
        </div>

        <div className="viz-status-card">
          <div className="viz-status-label">Active Agent</div>
          <div className="viz-status-value">{state?.agent.active_agent_id ?? "无"}</div>
          <div className="viz-status-subtext">
            Profile: {state?.profile.profile_id ?? "default"}
            {state?.profile.shared ? " (共享)" : ""}
          </div>
        </div>

        {lease && (
          <div className="viz-status-card">
            <div className="viz-status-label">Lease Expires</div>
            <div className="viz-status-value">{new Date(lease).toLocaleTimeString()}</div>
          </div>
        )}

        {(state?.errors.length ?? 0) > 0 && (
          <div className="viz-status-card viz-status-card-warn">
            <div className="viz-status-label">Alerts</div>
            {state?.errors.map((error) => (
              <div key={error.code} className="viz-status-subtext">
                {error.code}: {error.message}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}