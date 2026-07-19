const { spawn, spawnSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const expectedVersion = require(path.join(root, "package.json")).version;
const executable = path.resolve(root, process.argv[2] ?? ".release/sidecar/webfa.exe");
if (!fs.statSync(executable).isFile()) throw new Error(`Sidecar not found: ${executable}`);

function reservePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close((error) => (error ? reject(error) : resolve(port)));
    });
  });
}

async function getJson(url, timeoutMs = 5000) {
  try {
    const response = await fetch(url, {
      cache: "no-store",
      headers: { Connection: "close" },
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!response.ok) throw new Error(`returned HTTP ${response.status}`);
    return await response.json();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const cause = error instanceof Error && error.cause ? ` (${String(error.cause)})` : "";
    throw new Error(`${url} request failed: ${message}${cause}`, { cause: error });
  }
}

async function removeOwnedTree(target) {
  let lastError;
  for (let attempt = 0; attempt <= 40; attempt += 1) {
    try {
      fs.rmSync(target, { recursive: true, force: true });
      return;
    } catch (error) {
      lastError = error;
      const retryable = error && ["EBUSY", "ENOTEMPTY", "EPERM"].includes(error.code);
      if (!retryable || attempt === 40) break;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
  throw lastError;
}

async function main() {
  const port = await reservePort();
  const instanceId = `smoke_${crypto.randomBytes(20).toString("hex")}`;
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "webfa-sidecar-smoke-"));
  const sidecarTemp = path.join(home, "temp");
  fs.mkdirSync(sidecarTemp, { recursive: true });
  const allowed = [
    "APPDATA", "COMSPEC", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "NUMBER_OF_PROCESSORS",
    "PATHEXT", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "SYSTEMDRIVE",
    "SYSTEMROOT", "TEMP", "TMP", "USERDOMAIN", "USERNAME", "USERPROFILE", "WINDIR",
  ];
  const env = Object.fromEntries(allowed.flatMap((key) => process.env[key] ? [[key, process.env[key]]] : []));
  env.PATH = path.join(process.env.SYSTEMROOT ?? "C:\\Windows", "System32");
  // Keep PyInstaller onefile extraction owned by this smoke run so forced
  // process-tree cleanup cannot leak global %TEMP%/_MEI* directories.
  env.TEMP = sidecarTemp;
  env.TMP = sidecarTemp;
  env.WEBFA_HOME = path.join(home, "WebFA");
  env.WEBFA_BROWSER_HEADLESS = "1";
  env.WEBFA_BROWSER_DRIVER = "managed-chromium";
  env.WEBFA_API_HOST = "127.0.0.1";
  env.WEBFA_API_PORT = String(port);
  env.WEBFA_RUNTIME_INSTANCE_ID = instanceId;

  const child = spawn(executable, ["runtime", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: home,
    env,
    shell: false,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let diagnostics = "";
  child.stdout.on("data", (chunk) => { diagnostics = (diagnostics + chunk).slice(-12000); });
  child.stderr.on("data", (chunk) => { diagnostics = (diagnostics + chunk).slice(-12000); });
  try {
    const deadline = Date.now() + 45_000;
    let health;
    while (Date.now() < deadline) {
      if (child.exitCode !== null) throw new Error(`Sidecar exited with ${child.exitCode}: ${diagnostics}`);
      try {
        health = await getJson(`http://127.0.0.1:${port}/health`);
        break;
      } catch {
        await new Promise((resolve) => setTimeout(resolve, 150));
      }
    }
    if (!health) throw new Error(`Sidecar health timed out: ${diagnostics}`);
    if (
      health.product !== "webfa" ||
      health.release_version !== expectedVersion ||
      health.protocol_version !== 1 ||
      health.instance_id !== instanceId
    ) {
      throw new Error(`Unexpected Runtime identity: ${JSON.stringify(health)}`);
    }

    const transactions = await getJson(`http://127.0.0.1:${port}/v1/transactions`);
    const transactionIds = transactions.transactions.map((item) => item.id).sort();
    const expectedTransactions = [
      "github.patch_and_open_pr",
      "hf.compare_and_publish",
      "mock.patch_and_open_pr",
    ];
    if (JSON.stringify(transactionIds) !== JSON.stringify(expectedTransactions)) {
      throw new Error(`Frozen resources are incomplete: ${JSON.stringify(transactionIds)}`);
    }

    const mcp = await getJson(`http://127.0.0.1:${port}/v1/mcp/status`);
    const expectedTools = [
      "webfa.open_url", "webfa.observe", "webfa.act", "webfa.get_tabs", "webfa.switch_tab",
    ];
    if (JSON.stringify(mcp.tools) !== JSON.stringify(expectedTools)) {
      throw new Error(`Frozen MCP contract changed: ${JSON.stringify(mcp.tools)}`);
    }
    const config = await getJson(`http://127.0.0.1:${port}/v1/mcp/config`);
    const entry = config.mcpServers?.webfa;
    if (
      !entry ||
      path.resolve(entry.command) !== executable ||
      JSON.stringify(entry.args) !== '["mcp"]' ||
      entry.env?.WEBFA_RUNTIME_URL !== `http://127.0.0.1:${port}`
    ) {
      throw new Error(`Frozen MCP config does not point to the sidecar: ${JSON.stringify(config)}`);
    }
    const advertisedMcpConfig = path.join(home, "advertised-mcp-config.json");
    fs.writeFileSync(advertisedMcpConfig, `${JSON.stringify(entry)}\n`, "utf8");

    const releasePython = path.join(root, ".release/sidecar-venv/Scripts/python.exe");
    const releasePythonStat = fs.lstatSync(releasePython);
    if (!releasePythonStat.isFile() || releasePythonStat.isSymbolicLink()) {
      throw new Error(`Fresh release-venv Python is required for the MCP probe: ${releasePython}`);
    }
    const mcpProbe = spawnSync(
      releasePython,
      [
        "-I",
        path.join(root, "scripts/smoke-frozen-mcp.py"),
        advertisedMcpConfig,
        home,
      ],
      {
        cwd: home,
        env: { ...env, WEBFA_RUNTIME_URL: `http://127.0.0.1:${port}` },
        encoding: "utf8",
        timeout: 120_000,
        windowsHide: true,
      },
    );
    if (mcpProbe.error || mcpProbe.status !== 0) {
      throw new Error(
        `Frozen MCP JSON-RPC flow failed (${mcpProbe.status}): ${mcpProbe.error ?? mcpProbe.stderr}`,
      );
    }
    let mcpFlow;
    try {
      mcpFlow = JSON.parse(mcpProbe.stdout.trim().split(/\r?\n/).at(-1));
    } catch (error) {
      throw new Error(`Frozen MCP flow did not emit valid evidence: ${mcpProbe.stdout}`, { cause: error });
    }
    if (
      mcpFlow.status !== "pass" ||
      JSON.stringify(mcpFlow.flow) !==
        JSON.stringify(["initialize", "tools/list", "open", "observe", "act", "observe"])
    ) {
      throw new Error(`Frozen MCP flow evidence changed: ${JSON.stringify(mcpFlow)}`);
    }
    const healthAfterMcp = await getJson(`http://127.0.0.1:${port}/health`);
    if (healthAfterMcp.instance_id !== instanceId) {
      throw new Error("MCP client shutdown changed ownership of the external smoke Runtime");
    }
    process.stdout.write(`${JSON.stringify({
      status: "pass",
      executable,
      version: expectedVersion,
      transactionIds,
      tools: mcp.tools,
      mcpFlow: mcpFlow.flow,
    })}\n`);
  } finally {
    let terminationError;
    if (child.exitCode === null) {
      if (process.platform === "win32") {
        const killed = spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
          stdio: "ignore",
          windowsHide: true,
        });
        if (killed.error) terminationError = killed.error;
      } else {
        child.kill("SIGTERM");
      }
    }
    await new Promise((resolve) => {
      if (child.exitCode !== null) return resolve();
      const timer = setTimeout(resolve, 5000);
      child.once("exit", () => { clearTimeout(timer); resolve(); });
    });
    if (child.exitCode === null && !terminationError) {
      terminationError = new Error(`Sidecar process ${child.pid} did not exit after forced tree cleanup`);
    }
    // Windows may retain executable-image or antivirus handles briefly after
    // taskkill returns. Retry explicitly so a root-directory EPERM is retried
    // too, and prove that the owned extraction directory is reclaimed.
    await removeOwnedTree(home);
    if (terminationError) throw terminationError;
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack ?? error}\n`);
  process.exitCode = 1;
});
