import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("webfaMonitor", {
  getConfig: (): Promise<
    | {
        status: "ready";
        websocketUrl: string;
        token: string;
        sessionId: string;
        expiresAt: string;
      }
    | {
        status: "waiting";
        reason: "no_active_session";
        sessionId: string;
        retryAfterMs: number;
      }
    | {
        status: "unavailable";
        reason: "runtime_unavailable" | "monitor_config_failed";
        retryAfterMs: number;
      }
  > => ipcRenderer.invoke("monitor:getConfig"),
  openControlCenter: (): Promise<{ opened: boolean }> =>
    ipcRenderer.invoke("monitor:openControlCenter")
});
