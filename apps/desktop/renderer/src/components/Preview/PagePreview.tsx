import type { VisualizerState } from "../../types/visualizer";
import { AuthTakeoverBanner } from "./AuthTakeoverBanner";
import { TabList } from "./TabList";

type PagePreviewProps = {
  state: VisualizerState | null;
  onOpenMonitor?: () => void;
};

export function PagePreview({ state, onOpenMonitor }: PagePreviewProps) {
  const browserState = state?.browser_state;
  const hostClosed = state?.errors.some((error) => error.code === "browser_host_closed") ?? false;
  const previewUrl = state?.preview.data_url;
  const pageUrl = state?.page.url || "—";
  const pageTitle = state?.page.title || "无标题";
  const elementCount = browserState?.interactive_elements.length ?? 0;
  const hasActivePage = Boolean(state?.page.url);
  const takeoverReason = state?.takeover_surface?.reason ?? state?.web_state?.takeover?.reason ?? null;

  return (
    <div className="viz-preview-panel">
      <div className="viz-preview-header">
        <div>
          <div className="viz-preview-title">{pageTitle}</div>
          <div className="viz-preview-url">{pageUrl}</div>
        </div>
        <div className="viz-preview-meta">
          <span className={`viz-page-status ${state?.page.status ?? "idle"}`}>{state?.page.status ?? "idle"}</span>
          <span className="viz-el-count">{elementCount} 个元素</span>
          {onOpenMonitor && (
            <button type="button" className="viz-complete-auth-btn" onClick={onOpenMonitor}>
              会话监控
            </button>
          )}
        </div>
      </div>

      {browserState && <TabList tabs={browserState.tabs} />}

      <div className="viz-preview-viewport">
        <AuthTakeoverBanner
          auth={state?.page.auth ?? { surface_detected: false, takeover: "none", reason: [], user_action_required: false }}
          hostClosed={hostClosed}
          takeoverReason={takeoverReason}
          onOpenMonitor={onOpenMonitor}
        />
        {previewUrl ? (
          <img src={previewUrl} alt="Page preview" className="viz-preview-image" />
        ) : (
          <div className="viz-preview-empty">
            {hostClosed
              ? "BrowserHost 已关闭，请先重启宿主。"
              : hasActivePage
                ? "预览捕获中…实时交互仅在会话监控窗口中进行。"
                : "尚无页面，等待 Agent 调用 webfa.open_url"}
          </div>
        )}
      </div>
    </div>
  );
}
