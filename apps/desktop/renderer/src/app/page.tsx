"use client";

import { useEffect, useMemo, useState } from "react";
import type { RuntimeStatus } from "../types/webfa-desktop";

type HealthResponse = {
  status: "ok";
  runtime: "running";
  api: { host: string; port: number; url: string };
  storage: { data_dir: string; db_path: string; logs_dir: string };
  mcp: { status: string; transport: string };
};

type ProviderResponse = {
  providers: Array<{ id: string; name: string; status: string; auth_mode: string | null }>;
};

type TransactionResponse = {
  transactions: Array<{ id: string; provider: string; name: string; risk: string; approval_level: string }>;
};

const API_FALLBACK = "http://127.0.0.1:8787";

export default function DashboardPage() {
  const [runtime, setRuntime] = useState<RuntimeStatus>({ state: "stopped", apiUrl: API_FALLBACK });
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [providers, setProviders] = useState<ProviderResponse["providers"]>([]);
  const [transactions, setTransactions] = useState<TransactionResponse["transactions"]>([]);
  const [lastError, setLastError] = useState<string | null>(null);

  const apiUrl = useMemo(() => runtime.apiUrl || health?.api.url || API_FALLBACK, [runtime.apiUrl, health?.api.url]);

  async function refreshRuntime() {
    try {
      if (window.webfaDesktop) {
        const status = await window.webfaDesktop.getRuntimeStatus();
        setRuntime(status);
      }
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error));
    }
  }

  async function refreshApi() {
    try {
      const healthResponse = await fetch(`${apiUrl}/health`, { cache: "no-store" });
      if (!healthResponse.ok) throw new Error(`Health failed: ${healthResponse.status}`);
      const nextHealth = (await healthResponse.json()) as HealthResponse;
      setHealth(nextHealth);
      setRuntime((current) => ({ ...current, state: "running", apiUrl: nextHealth.api.url, dbPath: nextHealth.storage.db_path }));

      const [providerResponse, transactionResponse] = await Promise.all([
        fetch(`${apiUrl}/v1/providers`, { cache: "no-store" }),
        fetch(`${apiUrl}/v1/transactions`, { cache: "no-store" })
      ]);
      setProviders(((await providerResponse.json()) as ProviderResponse).providers);
      setTransactions(((await transactionResponse.json()) as TransactionResponse).transactions);
      setLastError(null);
    } catch (error) {
      setHealth(null);
      setRuntime((current) => ({ ...current, state: current.state === "error" ? "error" : "stopped" }));
      setLastError(error instanceof Error ? error.message : String(error));
    }
  }

  useEffect(() => {
    refreshRuntime();
    refreshApi();

    const unsubscribe = window.webfaDesktop?.onRuntimeStatus((status) => {
      setRuntime(status);
      if (status.state === "error" && status.lastError) setLastError(status.lastError);
      if (status.state === "stopped") setHealth(null);
    });

    const id = window.setInterval(refreshApi, 2500);
    return () => {
      unsubscribe?.();
      window.clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiUrl]);

  async function startRuntime() {
    const status = await window.webfaDesktop?.startRuntime();
    if (status) setRuntime(status);
    await refreshApi();
  }

  async function stopRuntime() {
    const status = await window.webfaDesktop?.stopRuntime();
    if (status) setRuntime(status);
    setHealth(null);
  }

  return (
    <main className="min-h-screen p-8">
      <section className="mx-auto max-w-6xl space-y-6">
        <header className="flex flex-col gap-3 border-b border-slate-800 pb-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.28em] text-slate-500">WebFA Desktop v0.1</p>
            <h1 className="mt-2 text-3xl font-semibold text-white">Agent Action Transaction Gateway</h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-400">
              Local console for runtime status, storage paths, provider connection placeholders, and transaction registry discovery.
            </p>
          </div>
          <div className="flex gap-2">
            <button className="rounded-md bg-white px-4 py-2 text-sm font-medium text-slate-950" onClick={startRuntime}>
              Start Runtime
            </button>
            <button className="rounded-md border border-slate-700 px-4 py-2 text-sm font-medium text-slate-200" onClick={stopRuntime}>
              Stop Runtime
            </button>
          </div>
        </header>

        {lastError ? (
          <div className="rounded-lg border border-red-900 bg-red-950/30 p-4 text-sm text-red-200">
            Runtime/UI error: {lastError}
          </div>
        ) : null}

        <div className="grid gap-4 md:grid-cols-3">
          <StatusCard label="Runtime" value={runtime.state} detail={runtime.pid ? `pid ${runtime.pid}` : "process managed by Electron"} />
          <StatusCard label="REST API" value={apiUrl} detail={health ? "health ok" : "waiting for runtime"} />
          <StatusCard label="MCP" value="placeholder" detail={health?.mcp.status ?? "not implemented in v0.1"} />
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <Panel title="Local Storage">
            <dl className="space-y-3 text-sm">
              <KeyValue label="Data directory" value={health?.storage.data_dir ?? "Unavailable while runtime is stopped"} />
              <KeyValue label="SQLite DB" value={health?.storage.db_path ?? runtime.dbPath ?? "Unavailable while runtime is stopped"} />
              <KeyValue label="Logs" value={health?.storage.logs_dir ?? "Unavailable while runtime is stopped"} />
            </dl>
          </Panel>

          <Panel title="Provider Connections">
            <div className="space-y-3">
              {(providers.length ? providers : [
                { id: "github", name: "GitHub", status: "disconnected", auth_mode: null },
                { id: "huggingface", name: "Hugging Face", status: "disconnected", auth_mode: null }
              ]).map((provider) => (
                <div key={provider.id} className="flex items-center justify-between rounded-md border border-slate-800 p-3">
                  <div>
                    <div className="font-medium text-slate-100">{provider.name}</div>
                    <div className="text-xs text-slate-500">{provider.id}</div>
                  </div>
                  <span className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-300">{provider.status}</span>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <Panel title="Transaction Registry">
          <div className="grid gap-3 md:grid-cols-2">
            {transactions.map((transaction) => (
              <div key={transaction.id} className="rounded-lg border border-slate-800 p-4">
                <div className="font-medium text-slate-100">{transaction.id}</div>
                <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-400">
                  <KeyValue label="Provider" value={transaction.provider} />
                  <KeyValue label="Risk" value={transaction.risk} />
                  <KeyValue label="Approval" value={transaction.approval_level} />
                </div>
              </div>
            ))}
            {!transactions.length ? <p className="text-sm text-slate-500">No transactions loaded while runtime is stopped.</p> : null}
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

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-[0.14em] text-slate-600">{label}</dt>
      <dd className="mt-1 break-all text-slate-300">{value}</dd>
    </div>
  );
}
