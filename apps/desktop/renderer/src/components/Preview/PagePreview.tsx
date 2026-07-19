import type { VisualizerState } from "../../types/visualizer";
import { AuthTakeoverBanner } from "./AuthTakeoverBanner";
import { TabList } from "./TabList";

type PagePreviewProps = {
  state: VisualizerState | null;
  runtimeNotice?: RuntimeSurfaceNotice | null;
  onOpenMonitor?: () => void;
  monitorDisabled?: boolean;
};

export type RuntimeSurfaceNotice = {
  tone: "neutral" | "progress" | "warning" | "error";
  eyebrow: string;
  title: string;
  detail: string;
  statusLabel: string;
  meta: string;
  actionLabel?: string;
  actionDisabled?: boolean;
  onAction?: () => void;
};

export function PagePreview({
  state,
  runtimeNotice = null,
  onOpenMonitor,
  monitorDisabled = false,
}: PagePreviewProps) {
  const browserState = state?.browser_state;
  const hostClosed = state?.errors.some((error) => error.code === "browser_host_closed") ?? false;
  const previewUrl = state?.preview.data_url;
  const pageUrl = state?.page.url || runtimeNotice?.meta || "—";
  const pageTitle = state?.page.title || (runtimeNotice ? "运行环境" : "无标题");
  const elementCount = browserState?.interactive_elements.length ?? 0;
  const hasActivePage = Boolean(state?.page.url);
  const takeoverReason = state?.takeover_surface?.reason ?? state?.web_state?.takeover?.reason ?? null;

  return (
    <div className="viz-preview-panel">
      <div className="viz-preview-header">
        <div className="viz-preview-heading">
          <div className="viz-preview-title">{pageTitle}</div>
          <div className="viz-preview-url">{pageUrl}</div>
        </div>
        <div className="viz-preview-meta">
          <span className={`viz-page-status ${runtimeNotice?.tone ?? state?.page.status ?? "idle"}`}>
            {runtimeNotice?.statusLabel ?? state?.page.status ?? "idle"}
          </span>
          <span className="viz-el-count">{elementCount} 个元素</span>
          {onOpenMonitor && (
            <button
              type="button"
              className="viz-complete-auth-btn"
              disabled={monitorDisabled}
              onClick={onOpenMonitor}
              title={monitorDisabled ? "Runtime 就绪后可打开会话监控" : undefined}
            >
              会话监控
            </button>
          )}
        </div>
      </div>

      {browserState && <TabList tabs={browserState.tabs} />}

      <div className="viz-preview-viewport">
        {!runtimeNotice && (
          <AuthTakeoverBanner
            auth={state?.page.auth ?? { surface_detected: false, takeover: "none", reason: [], user_action_required: false }}
            hostClosed={hostClosed}
            takeoverReason={takeoverReason}
            onOpenMonitor={onOpenMonitor}
          />
        )}
        {runtimeNotice ? (
          <div
            className={`viz-runtime-notice ${runtimeNotice.tone}`}
            role={runtimeNotice.tone === "error" || runtimeNotice.tone === "warning" ? "alert" : "status"}
          >
            <div className="viz-runtime-notice-head">
              <span className="viz-runtime-notice-signal" aria-hidden="true">
                <span />
                <span />
                <span />
              </span>
              <span className="viz-runtime-notice-eyebrow">{runtimeNotice.eyebrow}</span>
            </div>
            <div className="viz-runtime-notice-title">{runtimeNotice.title}</div>
            <div className="viz-runtime-notice-copy">{runtimeNotice.detail}</div>
            {runtimeNotice.actionLabel && runtimeNotice.onAction && (
              <button
                type="button"
                className="viz-btn viz-runtime-notice-action"
                disabled={runtimeNotice.actionDisabled}
                onClick={runtimeNotice.onAction}
              >
                {runtimeNotice.actionLabel}
              </button>
            )}
          </div>
        ) : previewUrl ? (
          <img src={previewUrl} alt={`${pageTitle} 页面预览`} className="viz-preview-image" />
        ) : (
          <div className="viz-preview-empty">
            <div className="viz-preview-empty-mark" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            <div className="viz-preview-empty-title">
              {hostClosed ? "BrowserHost 已关闭" : hasActivePage ? "正在建立视觉流" : "等待外部 Agent 打开网页"}
            </div>
            <div className="viz-preview-empty-copy">
              {hostClosed
                ? "请在控制面板中重启宿主，然后重新检查会话状态。"
                : hasActivePage
                  ? "预览捕获中。需要实时操作时，请进入会话监控。"
                  : "外部 Agent 调用 webfa.open_url 后，页面预览、对象与操作轨迹会显示在这里。"}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
