export type RuntimeState = "stopped" | "starting" | "running" | "error";

export interface RuntimeStatus {
  state: RuntimeState;
  pid?: number;
  apiUrl: string;
  dbPath?: string;
  lastError?: string;
  exitCode?: number | null;
}

declare global {
  interface Window {
    webfaDesktop?: {
      getRuntimeStatus: () => Promise<RuntimeStatus>;
      startRuntime: () => Promise<RuntimeStatus>;
      stopRuntime: () => Promise<RuntimeStatus>;
      getDesktopConfig: () => Promise<{ apiUrl: string; consoleUrl: string }>;
      onRuntimeStatus: (callback: (status: RuntimeStatus) => void) => () => void;
    };
  }
}
