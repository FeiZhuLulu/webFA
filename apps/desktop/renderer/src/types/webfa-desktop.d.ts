export type RuntimeState = "stopped" | "starting" | "running" | "error";
export type RuntimeIssueCode =
  | "external_runtime"
  | "endpoint_collision"
  | "ownership_changed"
  | "spawn_failed"
  | "startup_timeout"
  | "startup_failed"
  | "runtime_exited"
  | "cleanup_failed";

export interface RuntimeIssue {
  code: RuntimeIssueCode;
  message: string;
  recovery: "resolve_endpoint" | "retry_start" | "inspect_logs" | "retry_stop";
}

export interface RuntimeStatus {
  state: RuntimeState;
  ownership: "none" | "desktop" | "external" | "collision";
  pid?: number;
  apiUrl: string;
  dbPath?: string;
  lastError?: string;
  issue?: RuntimeIssue;
  exitCode?: number | null;
  releaseVersion?: string;
  protocolVersion?: number;
  instanceId?: string;
}

declare global {
  interface Window {
    webfaDesktop?: {
      getRuntimeStatus: () => Promise<RuntimeStatus>;
      startRuntime: () => Promise<RuntimeStatus>;
      stopRuntime: () => Promise<RuntimeStatus>;
      getDesktopConfig: () => Promise<{
        apiUrl: string;
        consoleUrl: string;
        visualizerControlToken?: string;
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
    };
    webfaMonitor?: {
      getConfig: () => Promise<
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
      >;
      openControlCenter: () => Promise<{ opened: boolean }>;
    };
  }
}
