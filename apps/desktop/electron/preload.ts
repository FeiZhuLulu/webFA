import { contextBridge, ipcRenderer } from "electron";
import type { RuntimeStatus } from "./runtimeProcess";

contextBridge.exposeInMainWorld("webfaDesktop", {
  getRuntimeStatus: (): Promise<RuntimeStatus> => ipcRenderer.invoke("runtime:getStatus"),
  startRuntime: (): Promise<RuntimeStatus> => ipcRenderer.invoke("runtime:start"),
  stopRuntime: (): Promise<RuntimeStatus> => ipcRenderer.invoke("runtime:stop"),
  getDesktopConfig: (): Promise<{ apiUrl: string; consoleUrl: string }> => ipcRenderer.invoke("desktop:getConfig"),
  onRuntimeStatus: (callback: (status: RuntimeStatus) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, status: RuntimeStatus) => callback(status);
    ipcRenderer.on("runtime-status", listener);
    return () => ipcRenderer.removeListener("runtime-status", listener);
  }
});
