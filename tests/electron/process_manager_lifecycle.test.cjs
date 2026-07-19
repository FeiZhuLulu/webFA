const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const { EventEmitter } = require("node:events");
const fs = require("node:fs/promises");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const {
  RuntimeProcessManager,
  buildPackagedRuntimeEnvironment,
  probeRuntimeEndpoint,
} = require("../../apps/desktop/electron/dist/runtimeProcess.js");
const {
  resolveWindowsTaskkillPath,
  terminateProcessTree,
} = require("../../apps/desktop/electron/dist/processTermination.js");
const CONTROL_TOKEN = "test-control-token-0123456789abcdef0123456789";

class FakeChild extends EventEmitter {
  constructor(pid) {
    super();
    this.pid = pid;
    this.exitCode = null;
    this.signalCode = null;
    this.stdout = new EventEmitter();
    this.stderr = new EventEmitter();
    this.stdin = new EventEmitter();
  }
}

function deferredTermination() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function ownedIdentity(instanceId, releaseVersion = "0.2.0") {
  return {
    reachable: true,
    identity: {
      product: "webfa",
      releaseVersion,
      protocolVersion: 1,
      instanceId,
    },
  };
}

function readFirstLine(stream) {
  return new Promise((resolve, reject) => {
    let buffered = "";
    const timer = setTimeout(() => reject(new Error("child pid was not reported")), 5000);
    stream.on("data", (chunk) => {
      buffered += chunk.toString("utf8");
      const newline = buffered.indexOf("\n");
      if (newline < 0) return;
      clearTimeout(timer);
      resolve(buffered.slice(0, newline).trim());
    });
    stream.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
  });
}

function pidIsAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code !== "ESRCH";
  }
}

test("runtime manager probes ownership, blocks duplicate starts, and ignores stale child events", async () => {
  const children = [new FakeChild(101), new FakeChild(202)];
  let spawnCount = 0;
  let activeInstanceId = null;
  const launchTokens = [];
  let tokenGeneration = 0;
  let termination = deferredTermination();
  const manager = new RuntimeProcessManager({
    appRoot: process.cwd(),
    expectedReleaseVersion: "0.2.0",
    controlTokenFactory: () => `${CONTROL_TOKEN}-${++tokenGeneration}`,
    monitorAllowedOrigin: "http://127.0.0.1:8788",
    spawnProcess: (_command, _args, options) => {
      activeInstanceId = options.env.WEBFA_RUNTIME_INSTANCE_ID;
      launchTokens.push(options.env.WEBFA_VISUALIZER_CONTROL_TOKEN);
      return children[spawnCount++];
    },
    probeRuntime: async () =>
      activeInstanceId ? ownedIdentity(activeInstanceId) : { reachable: false },
    terminateProcess: () => termination.promise,
    probeIntervalMs: 1,
  });

  manager.start();
  assert.equal((await manager.waitForStartup()).state, "running");
  assert.equal(manager.getStatus().ownership, "desktop");
  assert.equal(manager.canIssueControlToken(), true);
  assert.equal(manager.getControlToken(), launchTokens[0]);
  children[0].stderr.emit("data", Buffer.from("Error: recoverable request failure"));
  assert.equal(manager.getStatus().state, "running", "request diagnostics must not revoke health");
  manager.start();
  assert.equal(spawnCount, 1, "a live owned child must not be replaced");

  const stopped = manager.stop();
  manager.start();
  assert.equal(spawnCount, 1, "start must not race an in-flight stop");
  termination.resolve();
  assert.equal((await stopped).state, "stopped");
  activeInstanceId = null;

  termination = deferredTermination();
  manager.start();
  assert.equal((await manager.waitForStartup()).pid, 202);
  assert.notEqual(launchTokens[0], launchTokens[1], "a restart must rotate control authority");
  assert.equal(manager.getControlToken(), launchTokens[1]);
  children[0].emit("exit", 1);
  children[0].emit("error", new Error("late old-child error"));
  assert.equal(manager.getStatus().state, "running");
  assert.equal(manager.getStatus().pid, 202);
  termination.resolve();
  await manager.stop();
  assert.equal(manager.getControlToken(), undefined);
});

test("packaged runtime manager launches a source-free sidecar with a hostile parent environment sanitized", async () => {
  const child = new FakeChild(303);
  let launch;
  let expectedInstanceId = null;
  const previousUnsafe = process.env.WEBFA_ENABLE_UNSAFE_LEGACY_BROWSER_API;
  const previousResources = process.env.WEBFA_RESOURCES_ROOT;
  const previousRuntimeUrl = process.env.WEBFA_RUNTIME_URL;
  const previousHome = process.env.WEBFA_HOME;
  const previousNodeOptions = process.env.NODE_OPTIONS;
  process.env.WEBFA_ENABLE_UNSAFE_LEGACY_BROWSER_API = "1";
  process.env.WEBFA_RESOURCES_ROOT = "C:/attacker/resources";
  process.env.WEBFA_RUNTIME_URL = "http://attacker.invalid:9999";
  process.env.WEBFA_HOME = "C:/attacker/home";
  process.env.NODE_OPTIONS = "--inspect=0.0.0.0:9229";
  try {
    const manager = new RuntimeProcessManager({
      appRoot: "C:/source/webfa",
      expectedReleaseVersion: "0.2.0",
      workingDirectory: "C:/Users/Test/AppData/Roaming/WebFA",
      sidecarExecutable: "C:/Program Files/WebFA/resources/sidecar/webfa.exe",
      controlTokenFactory: () => CONTROL_TOKEN,
      monitorAllowedOrigin: "http://127.0.0.1:49152",
      spawnProcess: (command, args, options) => {
        launch = { command, args, options };
        expectedInstanceId = options.env.WEBFA_RUNTIME_INSTANCE_ID;
        return child;
      },
      probeRuntime: async () =>
        expectedInstanceId ? ownedIdentity(expectedInstanceId) : { reachable: false },
      terminateProcess: async () => undefined,
      probeIntervalMs: 1,
    });

    manager.start();
    assert.equal((await manager.waitForStartup()).state, "running");
    assert.equal(launch.command, "C:/Program Files/WebFA/resources/sidecar/webfa.exe");
    assert.deepEqual(launch.args, ["runtime", "--host", "127.0.0.1", "--port", "8787"]);
    assert.equal(launch.options.cwd, "C:/Users/Test/AppData/Roaming/WebFA");
    assert.equal("PYTHONPATH" in launch.options.env, false);
    assert.equal("NODE_OPTIONS" in launch.options.env, false);
    assert.equal("WEBFA_ENABLE_UNSAFE_LEGACY_BROWSER_API" in launch.options.env, false);
    assert.equal("WEBFA_RESOURCES_ROOT" in launch.options.env, false);
    assert.equal(launch.options.env.WEBFA_RUNTIME_URL, "http://127.0.0.1:8787");
    assert.equal(launch.options.env.WEBFA_HOME, "C:\\Users\\Test\\AppData\\Roaming\\WebFA");
    assert.equal(launch.options.env.WEBFA_MCP_COMMAND, launch.command);
    assert.equal(launch.options.env.WEBFA_MCP_ARGS_JSON, '["mcp"]');
    assert.equal(launch.options.env.WEBFA_STRICT_CONSOLE_ORIGINS, "1");
    assert.equal(launch.options.env.WEBFA_CONSOLE_ALLOWED_ORIGINS, "http://127.0.0.1:49152");
    await manager.stop();
  } finally {
    for (const [name, value] of [
      ["WEBFA_ENABLE_UNSAFE_LEGACY_BROWSER_API", previousUnsafe],
      ["WEBFA_RESOURCES_ROOT", previousResources],
      ["WEBFA_RUNTIME_URL", previousRuntimeUrl],
      ["WEBFA_HOME", previousHome],
      ["NODE_OPTIONS", previousNodeOptions],
    ]) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
});

test("packaged environment allowlist rejects WebFA, Node, and loader overrides", () => {
  const sanitized = buildPackagedRuntimeEnvironment({
    PATH: "C:/Windows/System32",
    APPDATA: "C:/Users/Test/AppData/Roaming",
    WEBFA_ENABLE_LEGACY_TRANSACTION: "1",
    WEBFA_PRIVATE_URL_POLICY: "allow",
    WEBFA_VISUALIZER_CONTROL_TOKEN: "attacker-token",
    PYTHONPATH: "C:/attacker/python",
    NODE_OPTIONS: "--require C:/attacker.js",
    ELECTRON_RUN_AS_NODE: "1",
  });
  assert.deepEqual(sanitized, {
    PATH: "C:/Windows/System32",
    APPDATA: "C:/Users/Test/AppData/Roaming",
  });
});

test("Windows process-tree cleanup uses a qualified system executable", () => {
  assert.equal(
    resolveWindowsTaskkillPath({ SystemRoot: "C:\\Windows", PATH: "C:\\attacker" }),
    "C:\\Windows\\System32\\taskkill.exe",
  );
  assert.throws(
    () => resolveWindowsTaskkillPath({ PATH: "C:\\attacker" }),
    /SystemRoot is unavailable/,
  );
  assert.throws(
    () => resolveWindowsTaskkillPath({ SystemRoot: "relative-windows" }),
    /unqualified process-tree cleanup command/,
  );
});

test("runtime manager refuses a non-loopback bind target", () => {
  assert.throws(
    () => new RuntimeProcessManager({
      appRoot: process.cwd(),
      expectedReleaseVersion: "0.2.0",
      host: "0.0.0.0",
      controlTokenFactory: () => CONTROL_TOKEN,
      monitorAllowedOrigin: "http://127.0.0.1:8788",
    }),
    /must be 127\.0\.0\.1 or localhost/,
  );
});

test("runtime manager refuses compatible external and foreign endpoint occupants without spawning", async () => {
  for (const scenario of [
    {
      probe: ownedIdentity("external_12345678"),
      ownership: "external",
      issueCode: "external_runtime",
      message: /external WebFA Runtime/,
      releaseVersion: "0.2.0",
    },
    {
      probe: ownedIdentity("external_12345678", "0.1.9"),
      ownership: "collision",
      issueCode: "endpoint_collision",
      message: /incompatible service/,
      releaseVersion: "0.1.9",
    },
    {
      probe: { reachable: true, detail: "health returned HTTP 404" },
      ownership: "collision",
      issueCode: "endpoint_collision",
      message: /occupied by another or incompatible service/,
      releaseVersion: undefined,
    },
  ]) {
    let spawnCount = 0;
    let terminateCount = 0;
    const manager = new RuntimeProcessManager({
      appRoot: process.cwd(),
      expectedReleaseVersion: "0.2.0",
      controlTokenFactory: () => CONTROL_TOKEN,
      monitorAllowedOrigin: "http://127.0.0.1:8788",
      probeRuntime: async () => scenario.probe,
      spawnProcess: () => {
        spawnCount += 1;
        return new FakeChild(404);
      },
      terminateProcess: async () => {
        terminateCount += 1;
      },
    });
    manager.start();
    const status = await manager.waitForStartup();
    assert.equal(status.state, "error");
    assert.equal(status.ownership, scenario.ownership);
    assert.equal(status.issue.code, scenario.issueCode);
    assert.equal(status.issue.recovery, "resolve_endpoint");
    assert.match(status.lastError, scenario.message);
    assert.equal(status.releaseVersion, scenario.releaseVersion);
    assert.equal(manager.canIssueControlToken(), false);
    assert.equal(spawnCount, 0);
    await manager.stop();
    assert.equal(terminateCount, 0, "Desktop must never terminate an external endpoint occupant");
  }
});

test("runtime manager detects a startup ownership race and reaps only its own child", async () => {
  const child = new FakeChild(505);
  let probeCount = 0;
  let terminated = 0;
  const manager = new RuntimeProcessManager({
    appRoot: process.cwd(),
    expectedReleaseVersion: "0.2.0",
    controlTokenFactory: () => CONTROL_TOKEN,
    monitorAllowedOrigin: "http://127.0.0.1:8788",
    spawnProcess: () => child,
    probeRuntime: async () => {
      probeCount += 1;
      if (probeCount === 1) return { reachable: false };
      return ownedIdentity("different_12345678");
    },
    terminateProcess: async (target) => {
      assert.equal(target, child);
      terminated += 1;
    },
    probeIntervalMs: 1,
  });
  manager.start();
  const status = await manager.waitForStartup();
  assert.equal(status.state, "error");
  assert.equal(status.ownership, "collision");
  assert.equal(status.issue.code, "ownership_changed");
  assert.equal(terminated, 1);
  assert.equal(manager.canIssueControlToken(), false);
});

test("runtime stop rejects a process-tree cleanup failure and preserves owned error state", async () => {
  const child = new FakeChild(606);
  let expectedInstanceId = null;
  const manager = new RuntimeProcessManager({
    appRoot: process.cwd(),
    expectedReleaseVersion: "0.2.0",
    controlTokenFactory: () => CONTROL_TOKEN,
    monitorAllowedOrigin: "http://127.0.0.1:8788",
    spawnProcess: (_command, _args, options) => {
      expectedInstanceId = options.env.WEBFA_RUNTIME_INSTANCE_ID;
      return child;
    },
    probeRuntime: async () =>
      expectedInstanceId ? ownedIdentity(expectedInstanceId) : { reachable: false },
    terminateProcess: async () => {
      throw new Error("tree still alive");
    },
    probeIntervalMs: 1,
  });
  manager.start();
  await manager.waitForStartup();
  await assert.rejects(manager.stop(), /tree still alive/);
  assert.equal(manager.getStatus().issue.code, "cleanup_failed");
  assert.equal(manager.getStatus().issue.recovery, "retry_stop");
  assert.doesNotMatch(manager.getStatus().lastError, /tree still alive/);
  assert.deepEqual(
    {
      state: manager.getStatus().state,
      ownership: manager.getStatus().ownership,
      pid: manager.getStatus().pid,
    },
    { state: "error", ownership: "desktop", pid: 606 },
  );
});

test("runtime manager keeps raw startup diagnostics out of renderer status", async () => {
  const child = new FakeChild(707);
  const manager = new RuntimeProcessManager({
    appRoot: process.cwd(),
    expectedReleaseVersion: "0.2.0",
    controlTokenFactory: () => CONTROL_TOKEN,
    monitorAllowedOrigin: "http://127.0.0.1:8788",
    spawnProcess: () => child,
    probeRuntime: async () => ({ reachable: false }),
    terminateProcess: async () => undefined,
    startupTimeoutMs: 100,
    probeIntervalMs: 1,
  });

  manager.start();
  await new Promise((resolve) => setImmediate(resolve));
  child.stderr.emit("data", Buffer.from("Traceback: C:\\Users\\Private\\secret.py token=do-not-render\n"));
  child.emit("exit", 1);
  const status = await manager.waitForStartup();

  assert.equal(status.state, "error");
  assert.equal(status.issue.code, "startup_failed");
  assert.equal(status.issue.recovery, "inspect_logs");
  assert.doesNotMatch(JSON.stringify(status), /Private|secret\.py|do-not-render/);
  assert.equal(manager.canIssueControlToken(), false);
});

test("runtime startup timeout reaps only its child and clears renderer authority", async () => {
  const child = new FakeChild(808);
  let terminated = 0;
  const manager = new RuntimeProcessManager({
    appRoot: process.cwd(),
    expectedReleaseVersion: "0.2.0",
    controlTokenFactory: () => CONTROL_TOKEN,
    monitorAllowedOrigin: "http://127.0.0.1:8788",
    spawnProcess: () => child,
    probeRuntime: async () => ({ reachable: false }),
    terminateProcess: async (target) => {
      assert.equal(target, child);
      terminated += 1;
    },
    startupTimeoutMs: 10,
    probeIntervalMs: 1,
  });

  manager.start();
  const status = await manager.waitForStartup();

  assert.equal(terminated, 1);
  assert.equal(status.state, "error");
  assert.equal(status.ownership, "none");
  assert.equal(status.pid, undefined);
  assert.equal(status.issue.code, "startup_timeout");
  assert.equal(status.issue.recovery, "retry_start");
  assert.equal(manager.canIssueControlToken(), false);
  assert.equal(manager.getControlToken(), undefined);
});

test("runtime endpoint probe requires the WebFA identity contract", async () => {
  const server = http.createServer((request, response) => {
    response.setHeader("Content-Type", "application/json");
    if (request.url === "/health") {
      response.end(JSON.stringify({
        product: "webfa",
        release_version: "0.2.0",
        protocol_version: 1,
        instance_id: "runtime_12345678",
      }));
      return;
    }
    response.statusCode = 404;
    response.end("{}");
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const address = server.address();
    const result = await probeRuntimeEndpoint(`http://127.0.0.1:${address.port}`);
    assert.deepEqual(result, ownedIdentity("runtime_12345678"));
  } finally {
    await new Promise((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
  }
});

test("runtime manager verifies and reaps a real source Runtime", { timeout: 60_000 }, async () => {
  const portServer = http.createServer();
  await new Promise((resolve) => portServer.listen(0, "127.0.0.1", resolve));
  const port = portServer.address().port;
  await new Promise((resolve, reject) =>
    portServer.close((error) => (error ? reject(error) : resolve())),
  );

  const appRoot = path.resolve(__dirname, "../..");
  const temporaryRoot = await fs.mkdtemp(path.join(os.tmpdir(), "webfa-runtime-manager-"));
  const previousHome = process.env.WEBFA_HOME;
  process.env.WEBFA_HOME = path.join(temporaryRoot, "WebFA");
  const manager = new RuntimeProcessManager({
    appRoot,
    expectedReleaseVersion: "0.2.0",
    workingDirectory: appRoot,
    port,
    pythonExecutable: process.env.WEBFA_PYTHON || "python",
    controlTokenFactory: () => CONTROL_TOKEN,
    monitorAllowedOrigin: "http://127.0.0.1:49152",
    startupTimeoutMs: 30_000,
  });
  try {
    manager.start();
    const status = await manager.waitForStartup();
    assert.equal(status.state, "running", status.lastError);
    assert.equal(status.ownership, "desktop");
    assert.match(status.instanceId, /^desktop_[a-f0-9]{36}$/);
    assert.equal(status.releaseVersion, "0.2.0");
    assert.equal(manager.canIssueControlToken(), true);
    const health = await probeRuntimeEndpoint(`http://127.0.0.1:${port}`);
    assert.equal(health.identity.instanceId, status.instanceId);
    assert.equal((await manager.stop()).state, "stopped");
    assert.equal(manager.canIssueControlToken(), false);
  } finally {
    if (manager.getStatus().pid) await manager.stop().catch(() => undefined);
    if (previousHome === undefined) delete process.env.WEBFA_HOME;
    else process.env.WEBFA_HOME = previousHome;
    await fs.rm(temporaryRoot, { recursive: true, force: true });
  }
});

test("process-tree termination removes a real parent and descendant", async () => {
  const parentScript = [
    'const { spawn } = require("node:child_process")',
    'const child = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], { stdio: "ignore" })',
    'process.stdout.write(String(child.pid) + "\\n")',
    'setInterval(() => {}, 1000)',
  ].join(";");
  const parent = spawn(process.execPath, ["-e", parentScript], {
    detached: process.platform !== "win32",
    stdio: ["pipe", "pipe", "pipe"],
    windowsHide: true,
  });
  const descendantPid = Number(await readFirstLine(parent.stdout));
  assert.equal(Number.isInteger(descendantPid) && descendantPid > 0, true);
  assert.equal(pidIsAlive(parent.pid), true);
  assert.equal(pidIsAlive(descendantPid), true);

  await terminateProcessTree(parent);

  assert.equal(pidIsAlive(parent.pid), false);
  assert.equal(pidIsAlive(descendantPid), false);
});
