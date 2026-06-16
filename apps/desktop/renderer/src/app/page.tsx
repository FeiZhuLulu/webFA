"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import type { RuntimeStatus } from "../types/webfa-desktop";

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
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [providers, setProviders] = useState<Array<{ id: string; name: string; status: string }>>([]);
  const [transactions, setTransactions] = useState<Array<{ id: string; provider: string; name: string; risk: string }>>([]);
  const [lastError, setLastError] = useState<string | null>(null);
  const [approvals, setApprovals] = useState<Array<{ id: string; plan_id: string; status: string; expires_at: string | null }>>([]);
  const [executions, setExecutions] = useState<Array<{ id: string; plan_id: string; status: string; proof_id: string | null }>>([]);
  const [proofs, setProofs] = useState<Array<{ id: string; provider: string; hash: string | null }>>([]);
  const [creating, setCreating] = useState(false);

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
    return () => window.clearInterval(id);
  }, [refreshApi]);

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

        <div className="grid gap-4 md:grid-cols-3">
          <StatusCard label="Runtime" value={runtime.state} detail={runtime.pid ? `pid ${runtime.pid}` : "managed by Electron"} />
          <StatusCard label="REST API" value={apiUrl} detail={health ? "health ok" : "waiting"} />
          <StatusCard label="SQLite DB" value={health?.storage.db_path ?? "—"} detail="local storage" />
        </div>

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
