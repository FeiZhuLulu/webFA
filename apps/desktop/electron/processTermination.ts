import { ChildProcessWithoutNullStreams, spawn } from "child_process";
import path from "path";

const GRACEFUL_TIMEOUT_MS = 5000;
const FORCE_TIMEOUT_MS = 5000;

function hasExited(child: ChildProcessWithoutNullStreams): boolean {
  return child.exitCode !== null || child.signalCode !== null;
}

function waitForExit(
  child: ChildProcessWithoutNullStreams,
  timeoutMs: number,
): Promise<boolean> {
  if (hasExited(child)) return Promise.resolve(true);
  return new Promise((resolve) => {
    let settled = false;
    const finish = (exited: boolean) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      child.removeListener("exit", onExit);
      resolve(exited);
    };
    const onExit = () => finish(true);
    const timer = setTimeout(() => finish(hasExited(child)), timeoutMs);
    child.once("exit", onExit);
  });
}

export function resolveWindowsTaskkillPath(environment: NodeJS.ProcessEnv = process.env): string {
  const windowsRoot = environment.SystemRoot ?? environment.SYSTEMROOT ?? environment.WINDIR;
  if (!windowsRoot || !path.win32.isAbsolute(windowsRoot)) {
    throw new Error("Windows SystemRoot is unavailable; refusing an unqualified process-tree cleanup command");
  }
  return path.win32.join(windowsRoot, "System32", "taskkill.exe");
}

async function taskkillTree(child: ChildProcessWithoutNullStreams): Promise<void> {
  if (!child.pid || hasExited(child)) return;
  await new Promise<void>((resolve, reject) => {
    const killer = spawn(resolveWindowsTaskkillPath(), ["/pid", String(child.pid), "/f", "/t"], {
      stdio: "ignore",
      windowsHide: true,
    });
    killer.once("error", reject);
    killer.once("exit", (code) => {
      if (code === 0 || hasExited(child)) resolve();
      else reject(new Error(`taskkill exited with code ${code}`));
    });
  });
  if (!(await waitForExit(child, FORCE_TIMEOUT_MS))) {
    throw new Error(`process tree ${child.pid} did not exit after taskkill`);
  }
}

function signalProcessGroup(child: ChildProcessWithoutNullStreams, signal: NodeJS.Signals): void {
  if (!child.pid) throw new Error("child process has no pid");
  try {
    process.kill(-child.pid, signal);
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code === "ESRCH") return;
    throw error;
  }
}

export async function terminateProcessTree(
  child: ChildProcessWithoutNullStreams,
): Promise<void> {
  if (hasExited(child)) return;
  if (process.platform === "win32") {
    await taskkillTree(child);
    return;
  }

  signalProcessGroup(child, "SIGTERM");
  if (await waitForExit(child, GRACEFUL_TIMEOUT_MS)) return;
  signalProcessGroup(child, "SIGKILL");
  if (!(await waitForExit(child, FORCE_TIMEOUT_MS))) {
    throw new Error(`process tree ${child.pid ?? "unknown"} did not exit after SIGKILL`);
  }
}
