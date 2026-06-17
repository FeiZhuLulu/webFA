"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import type { McpStatus, RuntimeStatus } from "../types/webfa-desktop";

const API_FALLBACK = "http://127.0.0.1:8787";

type HealthResponse = {
  status: "ok";
  runtime: "running";
  api: { host: string; port: number; url: string };
  storage: { data_dir: string; db_path: string; logs_dir: string };
  mcp: { status: string; transport: string };
};

export default function DashboardPage() {
  const [runtime, setRuntime] = useState<RuntimeStatus>({ state: "stopped", apiUrl: API_FALLBACK });
  const [mcpStatus, setMcpStatus] = useState<McpStatus>({ state: "stopped", transport: "stdio", runtimeUrl: API_FALLBACK });
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [providers, setProviders] = useState<Array<{ id: string; name: string; status: string }>>([]);
  const [transactions, setTransactions] = useState<Array<{ id: string; provider: string; name: string; risk: string }>>([]);
  const [lastError, setLastError] = useState<string | null>(null);
  const [approvals, setApprovals] = useState<Array<{ id: string; plan_id: string; status: string; expires_at: string | null }>>([]);
  const [executions, setExecutions] = useState<Array<{ id: string; plan_id: string; status: string; proof_id: string | null }>>([]);
  const [proofs, setProofs] = useState<Array<{ id: string; provider: string; hash: string | null }>>([]);
  const [creating, setCreating] = useState(false);
  const [mcpConfig, setMcpConfig] = useState<string>("");
  const [copied, setCopied] = useState(false);
  const [githubStatus, setGithubStatus] = useState<{ status: string; auth_mode: string | null; last_verified_at: string | null }>({ status: "disconnected", auth_mode: null, last_verified_at: null });
  const [githubToken, setGithubToken] = useState("");
  const [githubConnecting, setGithubConnecting] = useState(false);

  const apiUrl = useMemo(() => runtime.apiUrl || health?.api.url || API_FALLBACK, [runtime.apiUrl, health?.api.url]);

  const refreshApi = useCallback(async () => {
    try {
      const healthResponse = await fetch(`${apiUrl}/health`, { cache: "no-store" });
      if (!healthResponse.ok) throw new Error(`Health failed: ${healthResponse.status}`);
      const nextHealth = (await healthResponse.json()) as HealthResponse;
      setHealth(nextHealth);
      setRuntime((c) => ({ ...c, state: "running", apiUrl: nextHealth.api.url, dbPath: nextHealth.storage.db_path }));

      const [provResp, txnResp, approvalResp] = await Promise.all([
        fetch(`${apiUrl}/v1/providers`, { cache: "no-store" }),
        fetch(`${apiUrl}/v1/transactions`, { cache: "no-store" }),
        fetch(`${apiUrl}/v1/approvals`, { cache: "no-store" }),
      ]);
      setProviders(((await provResp.json()) as { providers: typeof providers }).providers);
      setTransactions(((await txnResp.json()) as { transactions: typeof transactions }).transactions);
      setApprovals(((await approvalResp.json()) as { items: typeof approvals }).items);
      setLastError(null);
    } catch (error) {
      setHealth(null);
      setRuntime((c) => ({ ...c, state: c.state === "error" ? "error" : "stopped" }));
      setLastError(error instanceof Error ? error.message : String(error));
    }
  }, [apiUrl]);

  useEffect(() => {
    refreshApi();
    const id = window.setInterval(refreshApi, 3000);

    // Poll MCP status from Electron
    const pollMcp = async () => {
      try {
        const status = await window.webfaDesktop?.getMcpStatus();
        if (status) setMcpStatus(status);
      } catch {}
    };
    pollMcp();
    const mcpId = window.setInterval(pollMcp, 3000);

    // Fetch MCP config
    fetch(`${apiUrl}/v1/mcp/config`).then(r => r.json()).then(c => setMcpConfig(JSON.stringify(c, null, 2))).catch(() => {});

    // Fetch GitHub status
    fetch(`${apiUrl}/v1/providers/github`).then(r => r.json()).then(s => setGithubStatus(s)).catch(() => {});

    return () => { window.clearInterval(id); window.clearInterval(mcpId); };
  }, [refreshApi, apiUrl]);

  async function createMockPlan() {
    setCreating(true);
    try {
      const resp = await fetch(`${apiUrl}/v1/plans`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transaction_id: "mock.patch_and_open_pr",
          input: { owner: "mock-owner", repo: "mock-repo", issue_number: 1, task_description: "Fix mock issue." },
        }),
      });
      if (!resp.ok) throw new Error(`Create plan failed: ${resp.status}`);
      const plan = await resp.json();

      // Auto-preview
      const previewResp = await fetch(`${apiUrl}/v1/plans/${plan.id}/preview`, { method: "POST" });
      if (!previewResp.ok) throw new Error(`Preview failed: ${previewResp.status}`);

      await refreshApi();
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error));
    } finally {
      setCreating(false);
    }
  }

  async function approveApproval(approvalId: string) {
    try {
      const resp = await fetch(`${apiUrl}/v1/approvals/${approvalId}/approve`, { method: "POST" });
      if (!resp.ok) throw new Error(`Approve failed: ${resp.status}`);
      const result = await resp.json();

      // Auto-execute
      const execResp = await fetch(`${apiUrl}/v1/executions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_id: result.plan_id, approval_token: result.approval_token }),
      });
      if (!execResp.ok) throw new Error(`Execute failed: ${execResp.status}`);
      const execution = await execResp.json();

      setExecutions((prev) => [execution, ...prev]);
      if (execution.proof_id) {
        setProofs((prev) => [{ id: execution.proof_id, provider: "mock", hash: null }, ...prev]);
      }
      await refreshApi();
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error));
    }
  }

  async function rejectApproval(approvalId: string) {
    try {
      await fetch(`${apiUrl}/v1/approvals/${approvalId}/reject`, { method: "POST" });
      await refreshApi();
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error));
    }
  }

  async function connectGithub() {
    if (!githubToken) return;
    setGithubConnecting(true);
    try {
      const resp = await fetch(`${apiUrl}/v1/providers/github/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: githubToken }),
      });
      const result = await resp.json();
      setGithubStatus(result);
      setGithubToken("");
      await refreshApi();
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error));
    } finally {
      setGithubConnecting(false);
    }
  }

  async function disconnectGithub() {
    try {
      await fetch(`${apiUrl}/v1/providers/github/disconnect`, { method: "DELETE" });
      setGithubStatus({ status: "disconnected", auth_mode: null, last_verified_at: null });
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error));
    }
  }

  const pendingApprovals = approvals.filter((a) => a.status === "pending");

  return (
    <main className="min-h-screen p-8">
      <section className="mx-auto max-w-6xl space-y-6">
        <header className="flex flex-col gap-3 border-b border-slate-800 pb-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.28em] text-slate-500">WebFA Desktop v0.1</p>
            <h1 className="mt-2 text-3xl font-semibold text-white">Agent Action Transaction Gateway</h1>
          </div>
          <div className="flex gap-2">
            <button
              className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
              onClick={createMockPlan}
              disabled={creating || runtime.state !== "running"}
            >
              {creating ? "Creating..." : "Create Mock Transaction"}
            </button>
            <button className="rounded-md border border-slate-700 px-4 py-2 text-sm font-medium text-slate-200" onClick={() => window.webfaDesktop?.stopRuntime()}>
              Stop Runtime
            </button>
          </div>
        </header>

        {lastError && (
          <div className="rounded-lg border border-red-900 bg-red-950/30 p-4 text-sm text-red-200">{lastError}</div>
        )}

        <div className="grid gap-4 md:grid-cols-4">
          <StatusCard label="Runtime" value={runtime.state} detail={runtime.pid ? `pid ${runtime.pid}` : "managed by Electron"} />
          <StatusCard label="MCP Server" value={mcpStatus.state} detail={mcpStatus.transport} />
          <StatusCard label="REST API" value={apiUrl} detail={health ? "health ok" : "waiting"} />
          <StatusCard label="GitHub" value={githubStatus.status} detail={githubStatus.auth_mode ?? "not configured"} />
        </div>

        <Panel title="GitHub Connection">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className={`rounded-full px-3 py-1 text-xs ${githubStatus.status === "connected" ? "bg-emerald-900 text-emerald-300" : githubStatus.status === "error" || githubStatus.status === "invalid" ? "bg-red-900 text-red-300" : "bg-slate-800 text-slate-400"}`}>
                  {githubStatus.status}
                </span>
                {githubStatus.last_verified_at && <span className="text-xs text-slate-500">Verified: {new Date(githubStatus.last_verified_at).toLocaleString()}</span>}
              </div>
              {githubStatus.status === "connected" && (
                <button className="rounded border border-red-800 px-3 py-1 text-xs text-red-300 hover:bg-red-950" onClick={disconnectGithub}>Disconnect</button>
              )}
            </div>
            {githubStatus.status !== "connected" && (
              <div className="flex gap-2">
                <input
                  type="password"
                  className="flex-1 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 placeholder-slate-500"
                  placeholder="GitHub fine-grained PAT (github_pat_...)"
                  value={githubToken}
                  onChange={(e) => setGithubToken(e.target.value)}
                />
                <button
                  className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                  onClick={connectGithub}
                  disabled={githubConnecting || !githubToken}
                >
                  {githubConnecting ? "Connecting..." : "Connect"}
                </button>
              </div>
            )}
            <p className="text-xs text-slate-500">P3: Read-only access. Write operations (PR creation) are reserved for Phase 4.</p>
          </div>
        </Panel>

        {pendingApprovals.length > 0 && (
          <Panel title={`Pending Approvals (${pendingApprovals.length})`}>
            <div className="space-y-3">
              {pendingApprovals.map((a) => (
                <div key={a.id} className="flex items-center justify-between rounded-md border border-amber-800 bg-amber-950/20 p-3">
                  <div>
                    <div className="font-medium text-amber-200">{a.id}</div>
                    <div className="text-xs text-amber-400">Plan: {a.plan_id}</div>
                  </div>
                  <div className="flex gap-2">
                    <button className="rounded bg-emerald-600 px-3 py-1 text-xs text-white hover:bg-emerald-500" onClick={() => approveApproval(a.id)}>
                      Approve
                    </button>
                    <button className="rounded border border-slate-600 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800" onClick={() => rejectApproval(a.id)}>
                      Reject
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        )}

        <div className="grid gap-4 md:grid-cols-2">
          <Panel title="Provider Connections">
            <div className="space-y-3">
              {providers.map((p) => (
                <div key={p.id} className="flex items-center justify-between rounded-md border border-slate-800 p-3">
                  <div className="font-medium text-slate-100">{p.name}</div>
                  <span className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-300">{p.status}</span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Transaction Registry">
            <div className="space-y-3">
              {transactions.map((t) => (
                <div key={t.id} className="rounded-md border border-slate-800 p-3">
                  <div className="font-medium text-slate-100">{t.id}</div>
                  <div className="text-xs text-slate-400">{t.provider} · {t.risk}</div>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        {executions.length > 0 && (
          <Panel title="Recent Executions">
            <div className="space-y-3">
              {executions.map((e) => (
                <div key={e.id} className="rounded-md border border-slate-800 p-3">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-slate-100">{e.id}</span>
                    <span className={`rounded-full px-2 py-0.5 text-xs ${e.status === "verified" ? "bg-emerald-900 text-emerald-300" : "bg-slate-800 text-slate-400"}`}>{e.status}</span>
                  </div>
                  {e.proof_id && <div className="mt-1 text-xs text-slate-500">Proof: {e.proof_id}</div>}
                </div>
              ))}
            </div>
          </Panel>
        )}

        <Panel title="MCP Configuration">
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <span className={`rounded-full px-3 py-1 text-xs ${mcpStatus.state === "running" ? "bg-emerald-900 text-emerald-300" : mcpStatus.state === "error" ? "bg-red-900 text-red-300" : "bg-slate-800 text-slate-400"}`}>
                {mcpStatus.state}
              </span>
              <span className="text-xs text-slate-500">Transport: {mcpStatus.transport}</span>
              <div className="flex gap-2 ml-auto">
                <button className="rounded border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800" onClick={() => window.webfaDesktop?.startMcp()}>Start</button>
                <button className="rounded border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800" onClick={() => window.webfaDesktop?.stopMcp()}>Stop</button>
                <button className="rounded border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800" onClick={() => window.webfaDesktop?.restartMcp()}>Restart</button>
              </div>
            </div>
            {mcpConfig && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs uppercase tracking-widest text-slate-500">Client Config</span>
                  <button
                    className="rounded border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800"
                    onClick={() => { navigator.clipboard.writeText(mcpConfig); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
                  >
                    {copied ? "Copied!" : "Copy"}
                  </button>
                </div>
                <pre className="overflow-auto rounded-md border border-slate-800 bg-slate-950 p-4 text-xs text-slate-300">{mcpConfig}</pre>
              </div>
            )}
            {mcpStatus.lastError && (
              <div className="rounded border border-red-900 bg-red-950/30 p-3 text-xs text-red-300">{mcpStatus.lastError}</div>
            )}
          </div>
        </Panel>
      </section>
    </main>
  );
}

function StatusCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
      <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</div>
      <div className="mt-2 break-all text-lg font-semibold text-white">{value}</div>
      <div className="mt-1 text-sm text-slate-500">{detail}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-950/70 p-5">
      <h2 className="mb-4 text-lg font-semibold text-white">{title}</h2>
      {children}
    </section>
  );
}
