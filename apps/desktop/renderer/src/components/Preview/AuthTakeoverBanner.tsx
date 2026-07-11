import type { BrowserAuthState, HumanTakeoverReason } from "../../types/visualizer";

type AuthTakeoverBannerProps = {
  auth: BrowserAuthState;
  hostClosed: boolean;
  takeoverSurfaceActive: boolean;
  takeoverReason: HumanTakeoverReason | null;
};

export function AuthTakeoverBanner({
  auth,
  hostClosed,
  takeoverSurfaceActive,
  takeoverReason,
}: AuthTakeoverBannerProps) {
  if (!auth.user_action_required && !auth.surface_detected && !hostClosed && !takeoverSurfaceActive) {
    return null;
  }

  const title = hostClosed
    ? "浏览器宿主已关闭"
    : takeoverSurfaceActive
      ? "WebFA 接管区已打开"
      : auth.user_action_required
        ? "需要人工接管"
        : "检测到认证页面";

  const detail = hostClosed
    ? "请使用「重启宿主」或「打开接管区」恢复当前 URL，然后在 WebFA 窗口内完成认证。"
    : takeoverSurfaceActive
      ? takeoverReason === "authentication"
        ? "请在 WebFA 接管区完成登录、扫码、验证码或 2FA。完成后点击「完成接管」，再让 agent 继续 observe。"
        : "当前区域无法由 WebFA 可靠结构化。请在接管区完成必要步骤，完成后点击「完成接管」，再让 agent 继续 observe。"
      : "请点击「打开接管区」，在 WebFA 窗口内完成人工步骤。Agent 不会读取密码、cookie 或 token。";

  return (
    <div className="viz-auth-banner">
      <div className="viz-auth-banner-inner">
        <div className="viz-auth-title">{title}</div>
        <div className="viz-auth-detail">{detail}</div>
        {(takeoverReason || auth.reason.length > 0) && (
          <div className="viz-auth-reasons">
            原因: {takeoverReason ?? auth.reason.join(", ")}
          </div>
        )}
      </div>
    </div>
  );
}