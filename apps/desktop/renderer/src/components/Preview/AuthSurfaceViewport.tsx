"use client";

import { useCallback, useEffect, useRef } from "react";
import type { HumanTakeoverReason } from "../../types/visualizer";

type AuthSurfaceViewportProps = {
  active: boolean;
  url: string | null;
  reason: HumanTakeoverReason | null;
};

export function AuthSurfaceViewport({ active, url, reason }: AuthSurfaceViewportProps) {
  const hostRef = useRef<HTMLDivElement>(null);

  const syncBounds = useCallback(async () => {
    if (!active || !url || !hostRef.current || !window.webfaDesktop?.showAuthSurface) {
      return;
    }
    const rect = hostRef.current.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      return;
    }
    await window.webfaDesktop.showAuthSurface({
      url,
      bounds: {
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height
      }
    });
  }, [active, url]);

  useEffect(() => {
    if (!active || !url) {
      void window.webfaDesktop?.destroyAuthSurface();
      return;
    }

    void syncBounds();
    const node = hostRef.current;
    if (!node) {
      return;
    }

    const observer = new ResizeObserver(() => {
      void syncBounds();
    });
    observer.observe(node);
    window.addEventListener("resize", syncBounds);
    const unsubscribe = window.webfaDesktop?.onAuthSurfaceRequestBounds?.(() => {
      void syncBounds();
    });

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", syncBounds);
      unsubscribe?.();
      void window.webfaDesktop?.destroyAuthSurface();
    };
  }, [active, url, syncBounds]);

  return (
    <div ref={hostRef} className={`viz-auth-surface-host${active ? " active" : ""}`}>
      {active ? (
        <div className="viz-auth-surface-label">
          WebFA 接管区 · {reason === "authentication" ? "登录/扫码/验证码请在此完成" : "请在此完成需要人工处理的页面步骤"}
        </div>
      ) : (
        <div className="viz-auth-surface-placeholder" />
      )}
    </div>
  );
}
