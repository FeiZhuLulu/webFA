import type { BrowserAuthState } from "../../types/visualizer";

type AuthTakeoverBannerProps = {
  auth: BrowserAuthState;
  hostClosed: boolean;
  authSurfaceActive: boolean;
};

export function AuthTakeoverBanner({ auth, hostClosed, authSurfaceActive }: AuthTakeoverBannerProps) {
  if (!auth.user_action_required && !auth.surface_detected && !hostClosed) {
    return null;
  }

  const title = hostClosed
    ? "浏览器宿主已关闭"
    : authSurfaceActive
      ? "WebFA 接管区已打开"
      : auth.user_action_required
        ? "需要人工接管"
        : "检测到认证页面";

  const detail = hostClosed
    ? "请使用「重启宿主」或「打开接管区」恢复当前 URL，然后在 WebFA 窗口内完成认证。"
    : authSurfaceActive
      ? "请在 WebFA 接管区完成登录、扫码、验证码或 2FA。完成后点击「完成接管」，再让 agent 继续 observe。"
      : "请点击「打开接管区」，在 WebFA 窗口内完成登录、扫码、验证码或 2FA。Agent 不会读取密码、cookie 或 token。";

  return (
    <div className="viz-auth-banner">
      <div className="viz-auth-banner-inner">
        <div className="viz-auth-title">{title}</div>
        <div className="viz-auth-detail">{detail}</div>
        {auth.reason.length > 0 && (
          <div className="viz-auth-reasons">原因: {auth.reason.join(", ")}</div>
        )}
      </div>
    </div>
  );
}