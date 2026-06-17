export type RuntimeState = "stopped" | "starting" | "running" | "error";

export interface RuntimeStatus {
  state: RuntimeState;
  pid?: number;
  apiUrl: string;
  dbPath?: string;
  lastError?: string;
  exitCode?: number | null;
}

export type McpState = "stopped" | "starting" | "running" | "error";

export interface McpStatus {
  state: McpState;
  pid?: number;
  transport: string;
  runtimeUrl: string;
  lastError?: string;
  exitCode?: number | null;
}

declare global {
  interface Window {
    webfaDesktop?: {
      getRuntimeStatus: () => Promise<RuntimeStatus>;
      startRuntime: () => Promise<RuntimeStatus>;
      stopRuntime: () => Promise<RuntimeStatus>;
      getMcpStatus: () => Promise<McpStatus>;
      startMcp: () => Promise<McpStatus>;
      stopMcp: () => Promise<McpStatus>;
      restartMcp: () => Promise<McpStatus>;
      getDesktopConfig: () => Promise<{ apiUrl: string; consoleUrl: string }>;
      onRuntimeStatus: (callback: (status: RuntimeStatus) => void) => () => void;
      onMcpStatus: (callback: (status: McpStatus) => void) => () => void;
    };
  }
}
