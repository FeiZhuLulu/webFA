import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("webfaMonitor", {
  getConfig: (): Promise<{
    websocketUrl: string;
    token: string;
    sessionId: string;
    expiresAt: string;
  }> => ipcRenderer.invoke("monitor:getConfig"),
  openControlCenter: (): Promise<{ opened: boolean }> =>
    ipcRenderer.invoke("monitor:openControlCenter")
});
