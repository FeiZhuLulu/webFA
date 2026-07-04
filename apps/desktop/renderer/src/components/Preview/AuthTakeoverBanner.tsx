import type { BrowserAuthState } from "../../types/visualizer";

type AuthTakeoverBannerProps = {
  auth: BrowserAuthState;
  hostClosed: boolean;
};

export function AuthTakeoverBanner({ auth, hostClosed }: AuthTakeoverBannerProps) {
  if (!auth.user_action_required && !auth.surface_detected && !hostClosed) {
    return null;
  }

  const title = hostClosed
    ? "浏览器宿主已关闭"
    : auth.user_action_required
      ? "需要人工接管"
      : "检测到认证页面";

  const detail = hostClosed
    ? "可见 Chromium 窗口已关闭。请使用「重启宿主」或让 agent 再次调用 open_url 恢复。"
    : "请在可见 Chromium 窗口中完成登录、扫码、验证码或 2FA。Agent 不会读取密码、cookie 或 token。";

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