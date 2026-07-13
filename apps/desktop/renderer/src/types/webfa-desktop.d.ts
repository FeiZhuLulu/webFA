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
      getDesktopConfig: () => Promise<{
        apiUrl: string;
        consoleUrl: string;
        visualizerControlToken: string;
      }>;
      openMonitor: () => Promise<{ opened: boolean }>;
      saveProfileBundle: (args: {
        profileId: string;
        sourceVersion: number;
        previewToken: string;
        passphrase: string;
        suggestedFilename: string;
      }) => Promise<
        | { status: "cancelled" }
        | { status: "saved"; fileName: string; byteCount: number; sha256: string }
      >;
      previewProfileBundleRestore: (args: { passphrase: string }) => Promise<
        | { status: "cancelled" }
        | { status: "previewed"; fileName: string; preview: Record<string, unknown> }
      >;
      onRuntimeStatus: (callback: (status: RuntimeStatus) => void) => () => void;
      onMcpStatus: (callback: (status: McpStatus) => void) => () => void;
    };
    webfaMonitor?: {
      getConfig: () => Promise<{
        websocketUrl: string;
        token: string;
        sessionId: string;
        expiresAt: string;
      }>;
      openControlCenter: () => Promise<{ opened: boolean }>;
    };
  }
}
