import type { HumanTakeoverReason } from "../../types/visualizer";

type AuthSurfaceViewportProps = {
  active: boolean;
  url: string | null;
  reason: HumanTakeoverReason | null;
};

/**
 * Deprecated compatibility placeholder.
 *
 * The former implementation embedded a separate Electron WebContentsView and
 * loaded the target URL again. UI-1B phase 6 replaces that architecture with
 * Session Monitor + HumanControlLease over the existing BrowserHost page.
 */
export function AuthSurfaceViewport({ active, reason }: AuthSurfaceViewportProps) {
  if (!active) return null;
  return (
    <div className="viz-preview-empty">
      旧接管区已停用。请打开会话监控，通过 HumanControlLease 控制同一个 BrowserHost 页面。
      {reason ? ` 当前原因：${reason}` : ""}
    </div>
  );
}
