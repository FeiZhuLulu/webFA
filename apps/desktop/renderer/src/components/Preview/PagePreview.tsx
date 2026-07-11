import type { HumanTakeoverReason, VisualizerState } from "../../types/visualizer";
import { AuthSurfaceViewport } from "./AuthSurfaceViewport";
import { AuthTakeoverBanner } from "./AuthTakeoverBanner";
import { TabList } from "./TabList";

type PagePreviewProps = {
  state: VisualizerState | null;
  takeoverSurfaceActive: boolean;
  takeoverSurfaceUrl: string | null;
  takeoverReason: HumanTakeoverReason | null;
  onCompleteTakeover?: () => void;
};

export function PagePreview({
  state,
  takeoverSurfaceActive,
  takeoverSurfaceUrl,
  takeoverReason,
  onCompleteTakeover,
}: PagePreviewProps) {
  const browserState = state?.browser_state;
  const hostClosed = state?.errors.some((error) => error.code === "browser_host_closed") ?? false;
  const previewUrl = state?.preview.data_url;
  const pageUrl = state?.page.url || "—";
  const pageTitle = state?.page.title || "无标题";
  const elementCount = browserState?.interactive_elements.length ?? 0;
  const hasActivePage = Boolean(state?.page.url);

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
          {takeoverSurfaceActive && onCompleteTakeover && (
            <button type="button" className="viz-complete-auth-btn" onClick={onCompleteTakeover}>
              完成接管
            </button>
          )}
        </div>
      </div>

      {browserState && <TabList tabs={browserState.tabs} />}

      <div className="viz-preview-viewport">
        <AuthTakeoverBanner
          auth={state?.page.auth ?? { surface_detected: false, takeover: "none", reason: [], user_action_required: false }}
          hostClosed={hostClosed}
          takeoverSurfaceActive={takeoverSurfaceActive}
          takeoverReason={takeoverReason}
        />
        {takeoverSurfaceActive ? (
          <AuthSurfaceViewport active url={takeoverSurfaceUrl || state?.page.url || null} reason={takeoverReason} />
        ) : previewUrl ? (
          <img src={previewUrl} alt="Page preview" className="viz-preview-image" />
        ) : (
          <div className="viz-preview-empty">
            {hostClosed
              ? "宿主已关闭，请使用「重启宿主」或「打开接管区」恢复"
              : hasActivePage
                ? "预览捕获中…"
                : "尚无页面，等待 agent 调用 webfa.open_url"}
          </div>
        )}
      </div>
    </div>
  );
}