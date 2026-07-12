type ControlPanelProps = {
  busy: boolean;
  hostActionsDisabled: boolean;
  onRefresh: () => void;
  onRestartHost: () => void;
  onOpenMonitor: () => void;
  onCopyJson: () => void;
  onStartRuntime?: () => void;
  onStopRuntime?: () => void;
};

export function ControlPanel({
  busy,
  hostActionsDisabled,
  onRefresh,
  onRestartHost,
  onOpenMonitor,
  onCopyJson,
  onStartRuntime,
  onStopRuntime,
}: ControlPanelProps) {
  return (
    <div className="viz-column-content" style={{ paddingTop: 0 }}>
      <div className="viz-control-stack">
        <button type="button" className="viz-btn" onClick={onRefresh} disabled={busy}>
          {busy ? "刷新中…" : "刷新状态 Refresh State"}
        </button>
        <button type="button" className="viz-btn" onClick={onOpenMonitor} disabled={busy || hostActionsDisabled}>
          打开会话监控 Session Monitor
        </button>
        <button type="button" className="viz-btn viz-btn-warning" onClick={onRestartHost} disabled={busy || hostActionsDisabled}>
          重启宿主 Restart Host
        </button>
        <button type="button" className="viz-btn" onClick={onCopyJson}>
          复制 Agent State JSON
        </button>
        {(onStartRuntime || onStopRuntime) && (
          <div className="viz-runtime-controls">
            {onStartRuntime && (
              <button type="button" className="viz-btn viz-btn-primary" onClick={onStartRuntime}>
                启动 Runtime
              </button>
            )}
            {onStopRuntime && (
              <button type="button" className="viz-btn" onClick={onStopRuntime}>
                停止 Runtime
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}