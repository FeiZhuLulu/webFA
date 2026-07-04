import { BrowserWindow, WebContentsView, session } from "electron";
import fs from "fs";
import os from "os";
import path from "path";

export type AuthSurfaceBounds = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type AuthSurfaceStatus = {
  active: boolean;
  url: string | null;
  profilePath: string;
};

export class AuthSurfaceManager {
  private view: WebContentsView | null = null;
  private ownerWindow: BrowserWindow | null = null;
  private active = false;
  private currentUrl: string | null = null;

  getProfilePath(): string {
    const webfaHome = process.env.WEBFA_HOME?.trim();
    if (webfaHome) {
      return path.join(webfaHome, "browser", "managed-chromium-profile-default");
    }
    const appData = process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming");
    return path.join(appData, "WebFA", "browser", "managed-chromium-profile-default");
  }

  getStatus(): AuthSurfaceStatus {
    this.updateCurrentUrlFromView();
    return {
      active: this.active,
      url: this.currentUrl,
      profilePath: this.getProfilePath()
    };
  }

  private ensureView(window: BrowserWindow): WebContentsView {
    if (this.view) {
      return this.view;
    }

    const profilePath = this.getProfilePath();
    fs.mkdirSync(profilePath, { recursive: true });
    const authSession = session.fromPath(profilePath, { cache: true });
    const view = new WebContentsView({
      webPreferences: {
        session: authSession,
        sandbox: true,
        nodeIntegration: false,
        contextIsolation: true,
        devTools: false
      }
    });

    view.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    view.webContents.on("will-attach-webview", (event) => {
      event.preventDefault();
    });
    view.webContents.on("context-menu", (event) => {
      event.preventDefault();
    });
    view.webContents.on("did-navigate", (_event, url) => {
      this.currentUrl = url;
    });
    view.webContents.on("did-navigate-in-page", (_event, url) => {
      this.currentUrl = url;
    });
    view.webContents.on("did-finish-load", () => {
      this.updateCurrentUrlFromView();
    });

    window.contentView.addChildView(view);
    view.setVisible(false);
    this.view = view;
    this.ownerWindow = window;
    return view;
  }

  show(window: BrowserWindow, bounds: AuthSurfaceBounds, url: string): AuthSurfaceStatus {
    if (!url.startsWith("http://") && !url.startsWith("https://") && !url.startsWith("file://") && url !== "about:blank") {
      throw new Error("auth surface url must start with http://, https://, file://, or be about:blank");
    }

    const hadView = Boolean(this.view);
    const view = this.ensureView(window);
    view.setBounds({
      x: Math.round(bounds.x),
      y: Math.round(bounds.y),
      width: Math.max(0, Math.round(bounds.width)),
      height: Math.max(0, Math.round(bounds.height))
    });
    view.setVisible(true);
    if (!hadView || this.currentUrl !== url) {
      void view.webContents.loadURL(url);
    }
    this.currentUrl = url;
    this.active = true;
    return this.getStatus();
  }

  hide(): AuthSurfaceStatus {
    this.updateCurrentUrlFromView();
    if (this.view) {
      this.view.setVisible(false);
    }
    this.active = false;
    return this.getStatus();
  }

  destroy(): AuthSurfaceStatus {
    this.updateCurrentUrlFromView();
    const finalUrl = this.currentUrl;
    if (this.view) {
      try {
        this.ownerWindow?.contentView.removeChildView(this.view);
      } catch {
        // Best-effort cleanup; closing webContents below still releases the page.
      }
      const contents = this.view.webContents;
      if (!contents.isDestroyed()) {
        contents.close();
      }
      this.view = null;
      this.ownerWindow = null;
    }
    this.active = false;
    this.currentUrl = finalUrl;
    return this.getStatus();
  }

  private updateCurrentUrlFromView(): void {
    if (!this.view) {
      return;
    }
    const contents = this.view.webContents;
    if (contents.isDestroyed()) {
      return;
    }
    const url = contents.getURL();
    if (url) {
      this.currentUrl = url;
    }
  }
}

export function resolveWebfaProfilePath(): string {
  const manager = new AuthSurfaceManager();
  return manager.getProfilePath();
}
