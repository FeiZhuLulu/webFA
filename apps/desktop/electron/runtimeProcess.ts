import { ChildProcessWithoutNullStreams, spawn } from "child_process";
import path from "path";

export type RuntimeState = "stopped" | "starting" | "running" | "error";

export interface RuntimeStatus {
  state: RuntimeState;
  pid?: number;
  apiUrl: string;
  dbPath?: string;
  lastError?: string;
  exitCode?: number | null;
}

export interface RuntimeProcessManagerOptions {
  appRoot: string;
  host?: string;
  port?: number;
  pythonExecutable?: string;
  onStatus?: (status: RuntimeStatus) => void;
}

export class RuntimeProcessManager {
  private child: ChildProcessWithoutNullStreams | null = null;
  private status: RuntimeStatus;
  private readonly appRoot: string;
  private readonly host: string;
  private readonly port: number;
  private readonly pythonExecutable: string;
  private readonly onStatus?: (status: RuntimeStatus) => void;

  constructor(options: RuntimeProcessManagerOptions) {
    this.appRoot = options.appRoot;
    this.host = options.host ?? "127.0.0.1";
    this.port = options.port ?? 8787;
    this.pythonExecutable = options.pythonExecutable ?? process.env.WEBFA_PYTHON ?? "python";
    this.onStatus = options.onStatus;
    this.status = {
      state: "stopped",
      apiUrl: `http://${this.host}:${this.port}`
    };
  }

  getStatus(): RuntimeStatus {
    return { ...this.status };
  }

  start(): RuntimeStatus {
    if (this.child && this.status.state !== "stopped" && this.status.state !== "error") {
      return this.getStatus();
    }

    this.updateStatus({ state: "starting", lastError: undefined, exitCode: undefined });

    const pythonPathParts = [
      this.appRoot,
      path.join(this.appRoot, "packages"),
      path.join(this.appRoot, "packages", "webfa-core"),
      process.env.PYTHONPATH ?? ""
    ].filter(Boolean);

    const env = {
      ...process.env,
      PYTHONPATH: pythonPathParts.join(path.delimiter),
      WEBFA_API_HOST: this.host,
      WEBFA_API_PORT: String(this.port)
    };

    const args = [
      "-m",
      "uvicorn",
      "apps.runtime.main:app",
      "--host",
      this.host,
      "--port",
      String(this.port)
    ];

    this.child = spawn(this.pythonExecutable, args, {
      cwd: this.appRoot,
      env,
      shell: false
    });

    this.child.stdout.on("data", (chunk: Buffer) => {
      const text = chunk.toString("utf8");
      if (text.includes("Application startup complete") || text.includes("Uvicorn running")) {
        this.updateStatus({ state: "running", pid: this.child?.pid });
      }
      process.stdout.write(`[webfa-runtime] ${text}`);
    });

    this.child.stderr.on("data", (chunk: Buffer) => {
      const text = chunk.toString("utf8");
      process.stderr.write(`[webfa-runtime] ${text}`);
      if (/Traceback|Error|Exception|Address already in use/i.test(text)) {
        this.updateStatus({ state: "error", pid: this.child?.pid, lastError: text.trim() });
      }
    });

    this.child.on("error", (error: Error) => {
      this.updateStatus({ state: "error", lastError: error.message });
      this.child = null;
    });

    this.child.on("exit", (code: number | null) => {
      const nextState: RuntimeState = code === 0 || code === null ? "stopped" : "error";
      this.updateStatus({
        state: nextState,
        pid: undefined,
        exitCode: code,
        lastError: nextState === "error" ? `Runtime exited with code ${code}` : undefined
      });
      this.child = null;
    });

    return this.getStatus();
  }

  stop(): RuntimeStatus {
    if (!this.child) {
      this.updateStatus({ state: "stopped", pid: undefined, exitCode: undefined, lastError: undefined });
      return this.getStatus();
    }

    const child = this.child;
    this.child = null;

    if (process.platform === "win32") {
      spawn("taskkill", ["/pid", String(child.pid), "/f", "/t"]);
    } else {
      child.kill("SIGTERM");
    }

    this.updateStatus({ state: "stopped", pid: undefined, exitCode: undefined, lastError: undefined });
    return this.getStatus();
  }

  private updateStatus(partial: Partial<RuntimeStatus>): void {
    this.status = {
      ...this.status,
      ...partial,
      apiUrl: `http://${this.host}:${this.port}`
    };
    this.onStatus?.(this.getStatus());
  }
}
