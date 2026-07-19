import { ChildProcessWithoutNullStreams, spawn } from "child_process";
import { randomBytes } from "crypto";
import path from "path";
import { terminateProcessTree } from "./processTermination";

export const WEBFA_RUNTIME_PROTOCOL_VERSION = 1;
const RUNTIME_INSTANCE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{15,127}$/;

export type RuntimeState = "stopped" | "starting" | "running" | "error";
export type RuntimeOwnership = "none" | "desktop" | "external" | "collision";
export type RuntimeIssueCode =
  | "external_runtime"
  | "endpoint_collision"
  | "ownership_changed"
  | "spawn_failed"
  | "startup_timeout"
  | "startup_failed"
  | "runtime_exited"
  | "cleanup_failed";
export type RuntimeRecovery =
  | "resolve_endpoint"
  | "retry_start"
  | "inspect_logs"
  | "retry_stop";

export interface RuntimeIssue {
  code: RuntimeIssueCode;
  message: string;
  recovery: RuntimeRecovery;
}

export interface RuntimeIdentity {
  product: "webfa";
  releaseVersion: string;
  protocolVersion: number;
  instanceId: string;
}

export interface RuntimeProbeResult {
  reachable: boolean;
  identity?: RuntimeIdentity;
  detail?: string;
}

export interface RuntimeStatus {
  state: RuntimeState;
  ownership: RuntimeOwnership;
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

export interface RuntimeProcessManagerOptions {
  appRoot: string;
  expectedReleaseVersion: string;
  workingDirectory?: string;
  dataDirectory?: string;
  host?: string;
  port?: number;
  pythonExecutable?: string;
  sidecarExecutable?: string;
  controlTokenFactory: () => string;
  monitorAllowedOrigin: string;
  onStatus?: (status: RuntimeStatus) => void;
  spawnProcess?: typeof spawn;
  terminateProcess?: (child: ChildProcessWithoutNullStreams) => Promise<void>;
  probeRuntime?: (apiUrl: string, timeoutMs?: number) => Promise<RuntimeProbeResult>;
  startupTimeoutMs?: number;
  probeIntervalMs?: number;
}

const PACKAGED_ENVIRONMENT_KEYS = new Set([
  "APPDATA",
  "COMSPEC",
  "DISPLAY",
  "HOMEDRIVE",
  "HOMEPATH",
  "HOME",
  "LANG",
  "LC_ALL",
  "LOCALAPPDATA",
  "NUMBER_OF_PROCESSORS",
  "PATH",
  "PATHEXT",
  "PROGRAMDATA",
  "PROGRAMFILES",
  "PROGRAMFILES(X86)",
  "PROGRAMW6432",
  "SYSTEMDRIVE",
  "SYSTEMROOT",
  "TEMP",
  "TMP",
  "TZ",
  "USERDOMAIN",
  "USERNAME",
  "USERPROFILE",
  "WINDIR",
  "WAYLAND_DISPLAY",
  "XDG_CONFIG_HOME",
  "XDG_RUNTIME_DIR",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseRuntimeIdentity(value: unknown): RuntimeIdentity | undefined {
  if (!isRecord(value)) return undefined;
  const product = value.product;
  const releaseVersion = value.release_version;
  const protocolVersion = value.protocol_version;
  const instanceId = value.instance_id;
  if (
    product !== "webfa" ||
    typeof releaseVersion !== "string" ||
    releaseVersion.length === 0 ||
    typeof protocolVersion !== "number" ||
    !Number.isInteger(protocolVersion) ||
    typeof instanceId !== "string" ||
    !RUNTIME_INSTANCE_ID_PATTERN.test(instanceId)
  ) {
    return undefined;
  }
  return {
    product,
    releaseVersion,
    protocolVersion,
    instanceId,
  };
}

export async function probeRuntimeEndpoint(
  apiUrl: string,
  timeoutMs = 800,
): Promise<RuntimeProbeResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${apiUrl}/health`, {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) {
      return { reachable: true, detail: `health returned HTTP ${response.status}` };
    }
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      return { reachable: true, detail: "health returned non-JSON content" };
    }
    const identity = parseRuntimeIdentity(payload);
    if (!identity) {
      return { reachable: true, detail: "health did not provide a valid WebFA identity" };
    }
    return { reachable: true, identity };
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return { reachable: false, detail };
  } finally {
    clearTimeout(timer);
  }
}

export function buildPackagedRuntimeEnvironment(
  parentEnvironment: NodeJS.ProcessEnv = process.env,
): NodeJS.ProcessEnv {
  const environment: NodeJS.ProcessEnv = {};
  for (const [key, value] of Object.entries(parentEnvironment)) {
    if (value !== undefined && PACKAGED_ENVIRONMENT_KEYS.has(key.toUpperCase())) {
      environment[key] = value;
    }
  }
  return environment;
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function runtimeIssue(
  code: RuntimeIssueCode,
  message: string,
  recovery: RuntimeRecovery,
): RuntimeIssue {
  return { code, message, recovery };
}

export class RuntimeProcessManager {
  private child: ChildProcessWithoutNullStreams | null = null;
  private status: RuntimeStatus;
  private readonly appRoot: string;
  private readonly workingDirectory: string;
  private readonly dataDirectory?: string;
  private readonly host: string;
  private readonly port: number;
  private readonly pythonExecutable: string;
  private readonly sidecarExecutable?: string;
  private readonly expectedReleaseVersion: string;
  private readonly controlTokenFactory: () => string;
  private visualizerControlToken: string | undefined;
  private readonly monitorAllowedOrigin: string;
  private readonly onStatus?: (status: RuntimeStatus) => void;
  private readonly spawnProcess: typeof spawn;
  private readonly terminateProcess: (child: ChildProcessWithoutNullStreams) => Promise<void>;
  private readonly probeRuntime: (apiUrl: string, timeoutMs?: number) => Promise<RuntimeProbeResult>;
  private readonly startupTimeoutMs: number;
  private readonly probeIntervalMs: number;
  private stoppingChild: ChildProcessWithoutNullStreams | null = null;
  private stopPromise: Promise<RuntimeStatus> | null = null;
  private startPromise: Promise<void> | null = null;
  private lifecycleGeneration = 0;

  constructor(options: RuntimeProcessManagerOptions) {
    this.appRoot = options.appRoot;
    this.expectedReleaseVersion = options.expectedReleaseVersion.trim();
    if (!this.expectedReleaseVersion) {
      throw new Error("Desktop Runtime expected release version must not be empty");
    }
    this.workingDirectory = options.workingDirectory ?? options.appRoot;
    this.dataDirectory = options.dataDirectory
      ? path.resolve(options.dataDirectory)
      : options.sidecarExecutable
        ? path.resolve(this.workingDirectory)
        : undefined;
    this.host = options.host ?? "127.0.0.1";
    this.port = options.port ?? 8787;
    if (!new Set(["127.0.0.1", "localhost"]).has(this.host.toLowerCase())) {
      throw new Error("Desktop Runtime host must be 127.0.0.1 or localhost");
    }
    if (!Number.isInteger(this.port) || this.port < 1 || this.port > 65535) {
      throw new Error("Desktop Runtime port must be an integer between 1 and 65535");
    }
    this.pythonExecutable = options.pythonExecutable ?? process.env.WEBFA_PYTHON ?? "python";
    this.sidecarExecutable = options.sidecarExecutable;
    this.controlTokenFactory = options.controlTokenFactory;
    this.monitorAllowedOrigin = options.monitorAllowedOrigin;
    this.onStatus = options.onStatus;
    this.spawnProcess = options.spawnProcess ?? spawn;
    this.terminateProcess = options.terminateProcess ?? terminateProcessTree;
    this.probeRuntime = options.probeRuntime ?? probeRuntimeEndpoint;
    this.startupTimeoutMs = options.startupTimeoutMs ?? 20_000;
    this.probeIntervalMs = options.probeIntervalMs ?? 100;
    this.status = {
      state: "stopped",
      ownership: "none",
      apiUrl: this.apiUrl,
    };
  }

  private get apiUrl(): string {
    return `http://${this.host}:${this.port}`;
  }

  getStatus(): RuntimeStatus {
    return { ...this.status };
  }

  canIssueControlToken(): boolean {
    return (
      this.status.state === "running" &&
      this.status.ownership === "desktop" &&
      Boolean(this.status.instanceId) &&
      Boolean(this.visualizerControlToken)
    );
  }

  getControlToken(): string | undefined {
    return this.canIssueControlToken() ? this.visualizerControlToken : undefined;
  }

  start(): RuntimeStatus {
    if (this.child || this.startPromise || this.stopPromise) {
      return this.getStatus();
    }

    const generation = ++this.lifecycleGeneration;
    this.visualizerControlToken = undefined;
    this.updateStatus({
      state: "starting",
      ownership: "none",
      pid: undefined,
      lastError: undefined,
      issue: undefined,
      exitCode: undefined,
      releaseVersion: undefined,
      protocolVersion: undefined,
      instanceId: undefined,
    });
    const promise = this.startLifecycle(generation)
      .catch((error) => {
        if (generation !== this.lifecycleGeneration) return;
        console.error("[webfa-runtime] Runtime startup failed", error);
        const issue = runtimeIssue(
          "startup_failed",
          "Runtime could not start. Review the local application log, then retry.",
          "inspect_logs",
        );
        this.updateStatus({
          state: "error",
          ownership: "none",
          pid: this.child?.pid,
          lastError: issue.message,
          issue,
        });
      })
      .finally(() => {
        if (this.startPromise === promise) this.startPromise = null;
      });
    this.startPromise = promise;
    return this.getStatus();
  }

  async waitForStartup(): Promise<RuntimeStatus> {
    await this.startPromise;
    return this.getStatus();
  }

  private async startLifecycle(generation: number): Promise<void> {
    const existing = await this.probeRuntime(this.apiUrl);
    if (generation !== this.lifecycleGeneration) return;
    if (existing.reachable) {
      const compatible =
        existing.identity?.protocolVersion === WEBFA_RUNTIME_PROTOCOL_VERSION &&
        existing.identity.releaseVersion === this.expectedReleaseVersion;
      const issue = compatible
        ? runtimeIssue(
            "external_runtime",
            "A compatible external WebFA Runtime already occupies this endpoint. Desktop did not attach or take control.",
            "resolve_endpoint",
          )
        : runtimeIssue(
            "endpoint_collision",
            "The Runtime endpoint is occupied by another or incompatible service. Desktop did not start or attach.",
            "resolve_endpoint",
          );
      this.updateStatus({
        state: "error",
        ownership: compatible ? "external" : "collision",
        lastError: issue.message,
        issue,
        releaseVersion: existing.identity?.releaseVersion,
        protocolVersion: existing.identity?.protocolVersion,
        instanceId: existing.identity?.instanceId,
      });
      return;
    }

    const expectedInstanceId = `desktop_${randomBytes(18).toString("hex")}`;
    const controlToken = this.controlTokenFactory().trim();
    if (controlToken.length < 32) {
      throw new Error("Desktop Runtime control token must contain at least 32 characters");
    }
    this.visualizerControlToken = controlToken;
    const child = this.spawnRuntime(expectedInstanceId);
    if (!child || generation !== this.lifecycleGeneration) {
      if (child && this.child === child) await this.stopChildAfterFailedStart(child);
      if (!this.child) this.visualizerControlToken = undefined;
      return;
    }

    const deadline = Date.now() + this.startupTimeoutMs;
    while (Date.now() < deadline) {
      if (generation !== this.lifecycleGeneration || this.child !== child) return;
      const probe = await this.probeRuntime(this.apiUrl);
      if (generation !== this.lifecycleGeneration || this.child !== child) return;
      if (probe.reachable) {
        if (
          probe.identity?.protocolVersion === WEBFA_RUNTIME_PROTOCOL_VERSION &&
          probe.identity.releaseVersion === this.expectedReleaseVersion &&
          probe.identity.instanceId === expectedInstanceId
        ) {
          this.updateStatus({
            state: "running",
            ownership: "desktop",
            pid: child.pid,
            lastError: undefined,
            issue: undefined,
            releaseVersion: probe.identity.releaseVersion,
            protocolVersion: probe.identity.protocolVersion,
            instanceId: probe.identity.instanceId,
          });
          return;
        }
        await this.failStartedChild(child, runtimeIssue(
          "ownership_changed",
          "Runtime endpoint ownership changed during startup. Desktop refused to attach or disclose control authority.",
          "resolve_endpoint",
        ), "collision");
        return;
      }
      await delay(this.probeIntervalMs);
    }

    if (generation === this.lifecycleGeneration && this.child === child) {
      await this.failStartedChild(child, runtimeIssue(
        "startup_timeout",
        `Runtime did not provide a verified health identity within ${this.startupTimeoutMs} ms.`,
        "retry_start",
      ), "none");
    }
  }

  private spawnRuntime(expectedInstanceId: string): ChildProcessWithoutNullStreams | null {
    const pythonPathParts = this.sidecarExecutable
      ? []
      : [
          this.appRoot,
          path.join(this.appRoot, "packages"),
          path.join(this.appRoot, "packages", "webfa-core"),
          process.env.PYTHONPATH ?? "",
        ].filter(Boolean);
    const inheritedEnv = this.sidecarExecutable
      ? buildPackagedRuntimeEnvironment()
      : { ...process.env };
    if (this.sidecarExecutable) delete inheritedEnv.PYTHONPATH;

    const env: NodeJS.ProcessEnv = {
      ...inheritedEnv,
      WEBFA_API_HOST: this.host,
      WEBFA_API_PORT: String(this.port),
      WEBFA_RUNTIME_URL: this.apiUrl,
      WEBFA_RUNTIME_INSTANCE_ID: expectedInstanceId,
      WEBFA_BROWSER_DRIVER: "managed-chromium",
      WEBFA_BROWSER_HEADLESS: this.sidecarExecutable
        ? "1"
        : process.env.WEBFA_BROWSER_HEADLESS ?? "1",
      WEBFA_AUTH_SURFACE_MODE: this.sidecarExecutable
        ? "electron"
        : process.env.WEBFA_AUTH_SURFACE_MODE ?? "electron",
      WEBFA_VISUALIZER_CONTROL_TOKEN: this.visualizerControlToken,
      WEBFA_MONITOR_ALLOWED_ORIGINS: this.sidecarExecutable
        ? this.monitorAllowedOrigin
        : process.env.WEBFA_MONITOR_ALLOWED_ORIGINS ?? this.monitorAllowedOrigin,
      WEBFA_CONSOLE_ALLOWED_ORIGINS: this.sidecarExecutable
        ? this.monitorAllowedOrigin
        : process.env.WEBFA_CONSOLE_ALLOWED_ORIGINS ?? this.monitorAllowedOrigin,
      ...(this.sidecarExecutable ? { WEBFA_STRICT_CONSOLE_ORIGINS: "1" } : {}),
      ...(this.sidecarExecutable && this.dataDirectory
        ? { WEBFA_HOME: this.dataDirectory }
        : {}),
      ...(pythonPathParts.length > 0 ? { PYTHONPATH: pythonPathParts.join(path.delimiter) } : {}),
      ...(this.sidecarExecutable
        ? {
            WEBFA_MCP_COMMAND: this.sidecarExecutable,
            WEBFA_MCP_ARGS_JSON: JSON.stringify(["mcp"]),
          }
        : {}),
    };

    const command = this.sidecarExecutable ?? this.pythonExecutable;
    const args = this.sidecarExecutable
      ? ["runtime", "--host", this.host, "--port", String(this.port)]
      : [
          "-m",
          "uvicorn",
          "apps.runtime.main:app",
          "--host",
          this.host,
          "--port",
          String(this.port),
        ];

    let child: ChildProcessWithoutNullStreams;
    try {
      child = this.spawnProcess(command, args, {
        cwd: this.workingDirectory,
        env,
        shell: false,
        detached: process.platform !== "win32",
        windowsHide: true,
      });
    } catch (error) {
      console.error("[webfa-runtime] Runtime process could not be spawned", error);
      const issue = runtimeIssue(
        "spawn_failed",
        "The Runtime process could not be launched. Review the local application log, then retry.",
        "inspect_logs",
      );
      this.updateStatus({
        state: "error",
        ownership: "none",
        pid: undefined,
        lastError: issue.message,
        issue,
      });
      return null;
    }
    this.child = child;
    this.attachChild(child);
    this.updateStatus({ state: "starting", ownership: "desktop", pid: child.pid });
    return child;
  }

  private attachChild(child: ChildProcessWithoutNullStreams): void {
    child.stdout.on("data", (chunk: Buffer) => {
      if (!this.isCurrent(child)) return;
      process.stdout.write(`[webfa-runtime] ${chunk.toString("utf8")}`);
    });

    child.stderr.on("data", (chunk: Buffer) => {
      if (!this.isCurrent(child)) return;
      const text = chunk.toString("utf8");
      process.stderr.write(`[webfa-runtime] ${text}`);
      if (
        this.status.state === "starting" &&
        /Traceback|Address already in use|Application startup failed/i.test(text)
      ) {
        const issue = runtimeIssue(
          "startup_failed",
          "Runtime reported a startup failure. Review the local application log, then retry.",
          "inspect_logs",
        );
        this.updateStatus({ lastError: issue.message, issue });
      }
    });

    child.on("error", (error: Error) => {
      if (!this.isCurrent(child)) return;
      console.error("[webfa-runtime] Runtime process emitted an error", error);
      const issue = runtimeIssue(
        "spawn_failed",
        "The Runtime process could not be launched. Review the local application log, then retry.",
        "inspect_logs",
      );
      this.updateStatus({
        state: "error",
        ownership: "none",
        pid: undefined,
        lastError: issue.message,
        issue,
      });
      this.child = null;
      this.visualizerControlToken = undefined;
    });

    child.on("exit", (code: number | null) => {
      if (!this.isCurrent(child)) return;
      const nextState: RuntimeState = code === 0 || code === null ? "stopped" : "error";
      const issue = nextState === "error"
        ? this.status.issue?.code === "startup_failed"
          ? this.status.issue
          : runtimeIssue(
              "runtime_exited",
              `Runtime exited unexpectedly with code ${code}.`,
              "retry_start",
            )
        : undefined;
      this.updateStatus({
        state: nextState,
        ownership: "none",
        pid: undefined,
        exitCode: code,
        lastError: issue?.message,
        issue,
        instanceId: undefined,
      });
      this.child = null;
      this.visualizerControlToken = undefined;
    });
  }

  private async failStartedChild(
    child: ChildProcessWithoutNullStreams,
    issue: RuntimeIssue,
    ownership: RuntimeOwnership,
  ): Promise<void> {
    try {
      await this.stopChildAfterFailedStart(child);
      this.visualizerControlToken = undefined;
      this.updateStatus({
        state: "error",
        ownership,
        pid: undefined,
        lastError: issue.message,
        issue,
        instanceId: undefined,
      });
    } catch (error) {
      console.error("[webfa-runtime] Failed-start cleanup did not complete", error);
      const cleanupIssue = runtimeIssue(
        "cleanup_failed",
        `${issue.message} Desktop could not confirm process cleanup and will not discard ownership.`,
        "retry_stop",
      );
      this.updateStatus({
        state: "error",
        ownership: "desktop",
        pid: child.pid,
        lastError: cleanupIssue.message,
        issue: cleanupIssue,
      });
    }
  }

  private async stopChildAfterFailedStart(child: ChildProcessWithoutNullStreams): Promise<void> {
    this.stoppingChild = child;
    try {
      await this.terminateProcess(child);
      if (this.child === child) this.child = null;
    } finally {
      if (this.stoppingChild === child) this.stoppingChild = null;
    }
  }

  stop(): Promise<RuntimeStatus> {
    if (this.stopPromise) return this.stopPromise;
    ++this.lifecycleGeneration;
    if (!this.child) {
      this.visualizerControlToken = undefined;
      this.updateStatus({
        state: "stopped",
        ownership: "none",
        pid: undefined,
        exitCode: undefined,
        lastError: undefined,
        issue: undefined,
        instanceId: undefined,
      });
      return Promise.resolve(this.getStatus());
    }

    const child = this.child;
    this.stoppingChild = child;
    this.stopPromise = (async () => {
      try {
        await this.terminateProcess(child);
        if (this.child === child) this.child = null;
        this.visualizerControlToken = undefined;
        this.updateStatus({
          state: "stopped",
          ownership: "none",
          pid: undefined,
          exitCode: undefined,
          lastError: undefined,
          issue: undefined,
          instanceId: undefined,
        });
      } catch (error) {
        console.error("[webfa-runtime] Runtime process-tree cleanup failed", error);
        const issue = runtimeIssue(
          "cleanup_failed",
          "Desktop could not confirm that its Runtime process tree stopped. Ownership is retained for a safe retry.",
          "retry_stop",
        );
        this.updateStatus({
          state: "error",
          ownership: "desktop",
          pid: child.pid,
          lastError: issue.message,
          issue,
        });
        throw error;
      } finally {
        if (this.stoppingChild === child) this.stoppingChild = null;
        this.stopPromise = null;
      }
      return this.getStatus();
    })();
    return this.stopPromise;
  }

  private isCurrent(child: ChildProcessWithoutNullStreams): boolean {
    return this.child === child && this.stoppingChild !== child;
  }

  private updateStatus(partial: Partial<RuntimeStatus>): void {
    this.status = {
      ...this.status,
      ...partial,
      apiUrl: this.apiUrl,
    };
    this.onStatus?.(this.getStatus());
  }
}
