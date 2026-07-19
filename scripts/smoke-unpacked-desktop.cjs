const { spawn, spawnSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");

const root = fs.realpathSync(path.resolve(__dirname, ".."));
const packageJson = require(path.join(root, "package.json"));
const smokeRequest = parseArguments(process.argv.slice(2));
const unpackedRoot = path.resolve(root, smokeRequest.unpackedRoot ?? ".release/electron/win-unpacked");
const executable = path.join(unpackedRoot, "WebFA.exe");
const sidecarExecutable = path.join(unpackedRoot, "resources", "sidecar", "webfa.exe");
const smokeRoot = path.join(root, ".release", "desktop-smoke");
const upgradeSmokeRoot = path.join(root, ".release", "upgrade-smoke");

if (process.platform !== "win32") {
  throw new Error("The unpacked WebFA Desktop lifecycle smoke currently requires Windows");
}
for (const candidate of [executable, sidecarExecutable]) {
  if (!fs.statSync(candidate).isFile()) throw new Error(`Packaged executable not found: ${candidate}`);
}

function parseArguments(argv) {
  const request = { expectedVersion: packageJson.version };
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (!value.startsWith("--")) {
      if (request.unpackedRoot) throw new Error(`Unexpected Desktop smoke argument: ${value}`);
      request.unpackedRoot = value;
      continue;
    }
    if (!new Set(["--expected-version", "--reuse-upgrade-user-data"]).has(value)) {
      throw new Error(`Unknown Desktop smoke option: ${value}`);
    }
    const optionValue = argv[index + 1];
    if (!optionValue || optionValue.startsWith("--")) throw new Error(`${value} requires a value`);
    index += 1;
    if (value === "--expected-version") request.expectedVersion = optionValue;
    else request.reuseUpgradeUserData = optionValue;
  }
  if (!/^\d+\.\d+\.\d+$/.test(request.expectedVersion)) {
    throw new Error(`Desktop smoke expected version must be exact: ${request.expectedVersion}`);
  }
  return request;
}

function resolveUpgradeUserData(value) {
  if (!value) return undefined;
  const target = path.resolve(root, value);
  const relation = path.relative(upgradeSmokeRoot, target);
  if (!relation || relation.startsWith("..") || path.isAbsolute(relation)) {
    throw new Error(`Reusable Desktop smoke user data is outside the upgrade-smoke root: ${target}`);
  }
  if (fs.existsSync(target) && fs.lstatSync(target).isSymbolicLink()) {
    throw new Error(`Reusable Desktop smoke user data must not be a link: ${target}`);
  }
  return target;
}

function sameWindowsPath(left, right) {
  return typeof left === "string" && typeof right === "string" &&
    path.win32.normalize(left).toLowerCase() === path.win32.normalize(right).toLowerCase();
}

function reservePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        server.close(() => reject(new Error("Could not reserve a loopback port")));
        return;
      }
      server.close((error) => (error ? reject(error) : resolve(address.port)));
    });
  });
}

function waitForExit(child, timeoutMs) {
  return new Promise((resolve, reject) => {
    if (child.exitCode !== null) {
      resolve({ code: child.exitCode, signal: child.signalCode });
      return;
    }
    const timer = setTimeout(() => {
      reject(new Error(`Packaged Desktop did not exit within ${timeoutMs} ms`));
    }, timeoutMs);
    child.once("exit", (code, signal) => {
      clearTimeout(timer);
      resolve({ code, signal });
    });
    child.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
  });
}

function canConnect(port, timeoutMs = 1000) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: "127.0.0.1", port });
    let settled = false;
    const finish = (reachable) => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolve(reachable);
    };
    socket.setTimeout(timeoutMs, () => finish(false));
    socket.once("connect", () => finish(true));
    socket.once("error", () => finish(false));
  });
}

function countProcessesByExecutable(target) {
  const command = [
    "$ErrorActionPreference = 'Stop'",
    "$target = [IO.Path]::GetFullPath($env:WEBFA_SMOKE_EXECUTABLE)",
    "$matches = @(Get-CimInstance Win32_Process | Where-Object {",
    "  $_.ExecutablePath -and [IO.Path]::GetFullPath($_.ExecutablePath) -eq $target",
    "})",
    "[Console]::Out.Write($matches.Count)",
  ].join("\n");
  const result = spawnSync(
    "powershell.exe",
    ["-NoProfile", "-NonInteractive", "-Command", command],
    {
      env: { ...process.env, WEBFA_SMOKE_EXECUTABLE: target },
      encoding: "utf8",
      timeout: 15_000,
      windowsHide: true,
    },
  );
  if (result.error || result.status !== 0 || !/^\d+$/.test(result.stdout.trim())) {
    throw new Error(
      `Could not verify process cleanup for ${target}: ${result.error ?? result.stderr ?? result.stdout}`,
    );
  }
  return Number(result.stdout.trim());
}

async function removeOwnedTree(target) {
  const relation = path.relative(smokeRoot, target);
  if (!relation || relation.startsWith("..") || path.isAbsolute(relation)) {
    throw new Error(`Refusing to remove a directory outside the owned smoke root: ${target}`);
  }
  let lastError;
  for (let attempt = 0; attempt <= 40; attempt += 1) {
    try {
      fs.rmSync(target, { recursive: true, force: true });
      return;
    } catch (error) {
      lastError = error;
      if (!error || !["EBUSY", "ENOTEMPTY", "EPERM"].includes(error.code) || attempt === 40) break;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
  throw lastError;
}

async function main() {
  const port = await reservePort();
  fs.mkdirSync(smokeRoot, { recursive: true });
  const home = path.join(smokeRoot, `run-${process.pid}-${crypto.randomBytes(8).toString("hex")}`);
  const userData = resolveUpgradeUserData(smokeRequest.reuseUpgradeUserData) ?? path.join(home, "user-data");
  const temporaryDirectory = path.join(home, "temp");
  const hostileInheritedHome = path.join(home, "hostile-inherited-webfa-home");
  const resultPath = path.join(userData, "release-smoke-result.json");
  fs.mkdirSync(userData, { recursive: true });
  fs.mkdirSync(temporaryDirectory, { recursive: true });

  const allowedEnvironmentKeys = [
    "APPDATA", "COMSPEC", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "NUMBER_OF_PROCESSORS",
    "PATHEXT", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "SYSTEMDRIVE",
    "SYSTEMROOT", "USERDOMAIN", "USERNAME", "USERPROFILE", "WINDIR",
  ];
  const environment = Object.fromEntries(
    allowedEnvironmentKeys.flatMap((key) => process.env[key] ? [[key, process.env[key]]] : []),
  );
  environment.PATH = path.join(process.env.SYSTEMROOT ?? "C:\\Windows", "System32");
  environment.TEMP = temporaryDirectory;
  environment.TMP = temporaryDirectory;
  environment.WEBFA_API_HOST = "127.0.0.1";
  environment.WEBFA_API_PORT = String(port);
  environment.WEBFA_HOME = hostileInheritedHome;

  const child = spawn(
    executable,
    ["--webfa-release-smoke", `--user-data-dir=${userData}`, "--no-first-run"],
    {
      cwd: home,
      env: environment,
      shell: false,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let diagnostics = "";
  child.stdout.on("data", (chunk) => {
    diagnostics = `${diagnostics}${chunk.toString("utf8")}`.slice(-20_000);
  });
  child.stderr.on("data", (chunk) => {
    diagnostics = `${diagnostics}${chunk.toString("utf8")}`.slice(-20_000);
  });

  let caughtError;
  try {
    const exit = await waitForExit(child, 90_000);
    if (exit.code !== 0) {
      throw new Error(`Packaged Desktop exited with ${exit.code ?? exit.signal}: ${diagnostics}`);
    }
    if (!fs.existsSync(resultPath)) {
      throw new Error(`Packaged Desktop did not write lifecycle evidence: ${diagnostics}`);
    }
    const result = JSON.parse(fs.readFileSync(resultPath, "utf8"));
    if (
      result.status !== "pass" ||
      result.product !== "webfa" ||
      result.releaseVersion !== smokeRequest.expectedVersion ||
      result.protocolVersion !== 1 ||
      !sameWindowsPath(result.userDataPath, userData) ||
      result.apiUrl !== `http://127.0.0.1:${port}` ||
      result.runtimeOwnership !== "desktop" ||
      result.applicationIconLoaded !== true ||
      !/^desktop_[a-f0-9]{36}$/.test(result.runtimeInstanceId ?? "") ||
      !Number.isInteger(result.runtimePid) ||
      result.renderer?.readyState !== "complete" ||
      result.renderer?.title !== "WebFA Control Center" ||
      result.renderer?.hasMain !== true ||
      result.renderer?.hasWebfaBrand !== true ||
      result.cleanup?.runtimeState !== "stopped" ||
      result.cleanup?.rendererServerStopped !== true
    ) {
      throw new Error(`Unexpected packaged Desktop lifecycle evidence: ${JSON.stringify(result)}`);
    }
    if (fs.existsSync(hostileInheritedHome)) {
      throw new Error(`Packaged Desktop wrote through inherited WEBFA_HOME: ${hostileInheritedHome}`);
    }
    const consoleUrl = new URL(result.consoleUrl);
    if (consoleUrl.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(consoleUrl.hostname)) {
      throw new Error(`Packaged renderer did not use a loopback origin: ${result.consoleUrl}`);
    }
    if (await canConnect(port)) {
      throw new Error(`Owned Runtime endpoint remained reachable after Desktop exit: 127.0.0.1:${port}`);
    }
    const remainingDesktopProcesses = countProcessesByExecutable(executable);
    const remainingSidecarProcesses = countProcessesByExecutable(sidecarExecutable);
    if (remainingDesktopProcesses !== 0 || remainingSidecarProcesses !== 0) {
      throw new Error(
        `Packaged process cleanup failed (desktop=${remainingDesktopProcesses}, sidecar=${remainingSidecarProcesses})`,
      );
    }
    process.stdout.write(`${JSON.stringify({
      status: "pass",
      executable,
      version: result.releaseVersion,
      userDataPath: result.userDataPath,
      reusedUpgradeUserData: Boolean(smokeRequest.reuseUpgradeUserData),
      protocolVersion: result.protocolVersion,
      runtimeOwnership: result.runtimeOwnership,
      apiUrl: result.apiUrl,
      inheritedWebfaHomeIgnored: true,
      applicationIconLoaded: result.applicationIconLoaded,
      renderer: result.renderer,
      cleanup: result.cleanup,
    })}\n`);
  } catch (error) {
    caughtError = error;
    throw error;
  } finally {
    if (child.exitCode === null) {
      spawnSync("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], {
        stdio: "ignore",
        windowsHide: true,
      });
      await waitForExit(child, 10_000).catch(() => undefined);
    }
    try {
      await removeOwnedTree(home);
    } catch (cleanupError) {
      if (!caughtError) throw cleanupError;
      process.stderr.write(`Smoke cleanup also failed: ${cleanupError.stack ?? cleanupError}\n`);
    }
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack ?? error}\n`);
  process.exitCode = 1;
});
