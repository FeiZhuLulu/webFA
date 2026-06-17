import { ChildProcessWithoutNullStreams, spawn } from "child_process";
import path from "path";

export type McpState = "stopped" | "starting" | "running" | "error";

export interface McpStatus {
  state: McpState;
  pid?: number;
  transport: string;
  runtimeUrl: string;
  lastError?: string;
  exitCode?: number | null;
}

export interface McpProcessManagerOptions {
  appRoot: string;
  runtimeUrl: string;
  pythonExecutable?: string;
  onStatus?: (status: McpStatus) => void;
}

export class McpProcessManager {
  private child: ChildProcessWithoutNullStreams | null = null;
  private status: McpStatus;
  private readonly appRoot: string;
  private readonly runtimeUrl: string;
  private readonly pythonExecutable: string;
  private readonly onStatus?: (status: McpStatus) => void;

  constructor(options: McpProcessManagerOptions) {
    this.appRoot = options.appRoot;
    this.runtimeUrl = options.runtimeUrl;
    this.pythonExecutable = options.pythonExecutable ?? process.env.WEBFA_PYTHON ?? "python";
    this.onStatus = options.onStatus;
    this.status = {
      state: "stopped",
      transport: "stdio",
      runtimeUrl: this.runtimeUrl,
    };
  }

  getStatus(): McpStatus {
    return { ...this.status };
  }

  start(): McpStatus {
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
      WEBFA_RUNTIME_URL: this.runtimeUrl,
      WEBFA_MCP_CALLER: "local-mcp",
      WEBFA_MCP_MODE: "stdio",
    };

    const args = ["-m", "apps.runtime.mcp.server"];

    this.child = spawn(this.pythonExecutable, args, {
      cwd: this.appRoot,
      env,
      shell: false,
      stdio: ["pipe", "pipe", "pipe"],
    });

    this.child.stdout.on("data", (chunk: Buffer) => {
      const text = chunk.toString("utf8");
      // MCP stdio server communicates via JSON-RPC on stdin/stdout
      // We don't log stdout as it's protocol traffic
      process.stdout.write(`[webfa-mcp] ${text}`);
    });

    this.child.stderr.on("data", (chunk: Buffer) => {
      const text = chunk.toString("utf8");
      process.stderr.write(`[webfa-mcp] ${text}`);
      if (/Traceback|Error|Exception/i.test(text)) {
        this.updateStatus({ state: "error", pid: this.child?.pid, lastError: text.trim() });
      }
    });

    this.child.on("error", (error: Error) => {
      this.updateStatus({ state: "error", lastError: error.message });
      this.child = null;
    });

    this.child.on("exit", (code: number | null) => {
      const nextState: McpState = code === 0 || code === null ? "stopped" : "error";
      this.updateStatus({
        state: nextState,
        pid: undefined,
        exitCode: code,
        lastError: nextState === "error" ? `MCP server exited with code ${code}` : undefined,
      });
      this.child = null;
    });

    // MCP stdio server is ready immediately (it reads from stdin)
    this.updateStatus({ state: "running", pid: this.child?.pid });

    return this.getStatus();
  }

  stop(): McpStatus {
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

  restart(): McpStatus {
    this.stop();
    return this.start();
  }

  private updateStatus(partial: Partial<McpStatus>): void {
    this.status = {
      ...this.status,
      ...partial,
      transport: "stdio",
      runtimeUrl: this.runtimeUrl,
    };
    this.onStatus?.(this.getStatus());
  }
}
