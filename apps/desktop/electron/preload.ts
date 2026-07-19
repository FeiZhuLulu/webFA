import { contextBridge, ipcRenderer } from "electron";
import type { RuntimeStatus } from "./runtimeProcess";

contextBridge.exposeInMainWorld("webfaDesktop", {
  getRuntimeStatus: (): Promise<RuntimeStatus> => ipcRenderer.invoke("runtime:getStatus"),
  startRuntime: (): Promise<RuntimeStatus> => ipcRenderer.invoke("runtime:start"),
  stopRuntime: (): Promise<RuntimeStatus> => ipcRenderer.invoke("runtime:stop"),
  getDesktopConfig: (): Promise<{
    apiUrl: string;
    consoleUrl: string;
    visualizerControlToken?: string;
  }> =>
    ipcRenderer.invoke("desktop:getConfig"),
  openMonitor: (): Promise<{ opened: boolean }> => ipcRenderer.invoke("monitor:open"),
  saveProfileBundle: (args: {
    profileId: string;
    sourceVersion: number;
    previewToken: string;
    passphrase: string;
    suggestedFilename: string;
  }): Promise<
    | { status: "cancelled" }
    | { status: "saved"; fileName: string; byteCount: number; sha256: string }
  > => ipcRenderer.invoke("profileBundle:save", args),
  previewProfileBundleRestore: (args: { passphrase: string }): Promise<
    | { status: "cancelled" }
    | { status: "previewed"; fileName: string; preview: Record<string, unknown> }
  > => ipcRenderer.invoke("profileBundle:previewRestore", args),
  onRuntimeStatus: (callback: (status: RuntimeStatus) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, status: RuntimeStatus) => callback(status);
    ipcRenderer.on("runtime-status", listener);
    return () => ipcRenderer.removeListener("runtime-status", listener);
  }
});
