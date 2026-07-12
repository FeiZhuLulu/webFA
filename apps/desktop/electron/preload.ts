import { contextBridge, ipcRenderer } from "electron";
import type { AuthSurfaceBounds, AuthSurfaceStatus } from "./authSurface";
import type { McpStatus } from "./mcpProcess";
import type { RuntimeStatus } from "./runtimeProcess";

contextBridge.exposeInMainWorld("webfaDesktop", {
  getRuntimeStatus: (): Promise<RuntimeStatus> => ipcRenderer.invoke("runtime:getStatus"),
  startRuntime: (): Promise<RuntimeStatus> => ipcRenderer.invoke("runtime:start"),
  stopRuntime: (): Promise<RuntimeStatus> => ipcRenderer.invoke("runtime:stop"),
  getMcpStatus: (): Promise<McpStatus> => ipcRenderer.invoke("mcp:getStatus"),
  startMcp: (): Promise<McpStatus> => ipcRenderer.invoke("mcp:start"),
  stopMcp: (): Promise<McpStatus> => ipcRenderer.invoke("mcp:stop"),
  restartMcp: (): Promise<McpStatus> => ipcRenderer.invoke("mcp:restart"),
  getDesktopConfig: (): Promise<{
    apiUrl: string;
    consoleUrl: string;
    authSurfaceProfilePath: string;
    visualizerControlToken: string;
  }> =>
    ipcRenderer.invoke("desktop:getConfig"),
  openMonitor: (): Promise<{ opened: boolean }> => ipcRenderer.invoke("monitor:open"),
  getAuthSurfaceStatus: (): Promise<AuthSurfaceStatus> => ipcRenderer.invoke("auth-surface:getStatus"),
  showAuthSurface: (payload: { url: string; bounds: AuthSurfaceBounds }): Promise<AuthSurfaceStatus> =>
    ipcRenderer.invoke("auth-surface:show", payload),
  hideAuthSurface: (): Promise<AuthSurfaceStatus> => ipcRenderer.invoke("auth-surface:hide"),
  destroyAuthSurface: (): Promise<AuthSurfaceStatus> => ipcRenderer.invoke("auth-surface:destroy"),
  onAuthSurfaceRequestBounds: (callback: () => void) => {
    const listener = () => callback();
    ipcRenderer.on("auth-surface:request-bounds", listener);
    return () => ipcRenderer.removeListener("auth-surface:request-bounds", listener);
  },
  onRuntimeStatus: (callback: (status: RuntimeStatus) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, status: RuntimeStatus) => callback(status);
    ipcRenderer.on("runtime-status", listener);
    return () => ipcRenderer.removeListener("runtime-status", listener);
  },
  onMcpStatus: (callback: (status: McpStatus) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, status: McpStatus) => callback(status);
    ipcRenderer.on("mcp-status", listener);
    return () => ipcRenderer.removeListener("mcp-status", listener);
  }
});
