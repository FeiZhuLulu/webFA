import type { BrowserAuthState, HumanTakeoverReason } from "../../types/visualizer";

type AuthTakeoverBannerProps = {
  auth: BrowserAuthState;
  hostClosed: boolean;
  takeoverReason: HumanTakeoverReason | null;
  onOpenMonitor?: () => void;
};

export function AuthTakeoverBanner({
  auth,
  hostClosed,
  takeoverReason,
  onOpenMonitor,
}: AuthTakeoverBannerProps) {
  const takeoverRequired = auth.user_action_required || Boolean(takeoverReason);
  if (!auth.surface_detected && !takeoverRequired && !hostClosed) return null;

  const title = hostClosed
    ? "BrowserHost 已关闭"
    : takeoverRequired
      ? "需要人工接管"
      : "检测到认证页面";

  const detail = hostClosed
    ? "请先重启 BrowserHost。网页不会在控制中心内重新加载。"
    : takeoverReason === "payment_verification"
      ? "请在会话监控窗口中完成支付密码、3-D Secure、银行 App 确认或其他支付验证。支付秘密不会返回给 Agent。"
      : takeoverReason === "biometric_verification"
        ? "请在会话监控窗口中完成指纹、面容或安全密钥验证。生物识别数据不会进入 Agent State。"
        : takeoverReason === "opaque_surface"
          ? "当前区域无法可靠结构化。请在会话监控窗口临时控制同一个 BrowserHost 页面。"
          : "请在会话监控窗口完成登录、验证码、2FA、扫码或其他人工步骤。控制中心不会创建第二份网页。";

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
        {!hostClosed && onOpenMonitor && (
          <button type="button" className="viz-complete-auth-btn" onClick={onOpenMonitor}>
            打开会话监控
          </button>
        )}
      </div>
    </div>
  );
}
