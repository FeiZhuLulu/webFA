"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { McpStatus, RuntimeStatus } from "../types/webfa-desktop";

const API_FALLBACK = "http://127.0.0.1:8787";

type BrowserElement = {
  id: string;
  role: string;
  tag: string;
  name: string;
  value: string;
  placeholder: string;
  visible: boolean;
  enabled: boolean;
  actions: string[];
};

type BrowserState = {
  session_id: string;
  url: string;
  title: string;
  page_status: "idle" | "loading";
  focused_element_id: string | null;
  tabs: Array<{ id: string; url: string; title: string; active: boolean }>;
  visible_text: string;
  interactive_elements: BrowserElement[];
  error: Record<string, unknown> | null;
};

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
  const [mcpTools, setMcpTools] = useState<string[]>([]);
  const [url, setUrl] = useState("https://example.com");
  const [actionJson, setActionJson] = useState('{"action":"click","target":"el_1"}');
  const [state, setState] = useState<BrowserState | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const apiUrl = useMemo(() => runtime.apiUrl || health?.api.url || API_FALLBACK, [runtime.apiUrl, health?.api.url]);

  const refreshStatus = useCallback(async () => {
    try {
      const healthResponse = await fetch(`${apiUrl}/health`, { cache: "no-store" });
      if (!healthResponse.ok) throw new Error(`Health failed: ${healthResponse.status}`);
      const nextHealth = (await healthResponse.json()) as HealthResponse;
      setHealth(nextHealth);
      setRuntime((current) => ({ ...current, state: "running", apiUrl: nextHealth.api.url, dbPath: nextHealth.storage.db_path }));

      const mcpResponse = await fetch(`${apiUrl}/v1/mcp/status`, { cache: "no-store" });
      if (mcpResponse.ok) setMcpTools(((await mcpResponse.json()) as { tools: string[] }).tools);
      setLastError(null);
    } catch (error) {
      setHealth(null);
      setRuntime((current) => ({ ...current, state: current.state === "error" ? "error" : "stopped" }));
      setLastError(error instanceof Error ? error.message : String(error));
    }
  }, [apiUrl]);

  async function observe() {
    const response = await fetch(`${apiUrl}/v1/browser/observe`, { cache: "no-store" });
    if (!response.ok) throw new Error(`Observe failed: ${response.status}`);
    setState((await response.json()) as BrowserState);
  }

  async function openUrl() {
    setBusy(true);
    try {
      const response = await fetch(`${apiUrl}/v1/browser/open`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      if (!response.ok) throw new Error(`Open failed: ${response.status}`);
      setState(((await response.json()) as { state: BrowserState }).state);
      setLastError(null);
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function runAction() {
    setBusy(true);
    try {
      const payload = JSON.parse(actionJson) as Record<string, unknown>;
      const response = await fetch(`${apiUrl}/v1/browser/act`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(`Act failed: ${response.status} ${await response.text()}`);
      setState(((await response.json()) as { state: BrowserState }).state);
      setLastError(null);
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    refreshStatus();
    const statusId = window.setInterval(refreshStatus, 3000);
    const pollMcp = async () => {
      try {
        const status = await window.webfaDesktop?.getMcpStatus();
        if (status) setMcpStatus(status);
      } catch {}
    };
    pollMcp();
    const mcpId = window.setInterval(pollMcp, 3000);
    return () => {
      window.clearInterval(statusId);
      window.clearInterval(mcpId);
    };
  }, [refreshStatus]);

  return (
    <main className="min-h-screen bg-slate-950 p-6 text-slate-100">
      <section className="mx-auto max-w-7xl space-y-5">
        <header className="flex flex-col gap-3 border-b border-slate-800 pb-5 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.22em] text-slate-500">WebFA P4</p>
            <h1 className="mt-2 text-3xl font-semibold">Agent Browser Runtime</h1>
          </div>
          <div className="flex gap-2">
            <button className="rounded-md border border-slate-700 px-3 py-2 text-sm" onClick={() => window.webfaDesktop?.startRuntime()}>
              Start Runtime
            </button>
            <button className="rounded-md border border-slate-700 px-3 py-2 text-sm" onClick={() => window.webfaDesktop?.stopRuntime()}>
              Stop Runtime
            </button>
          </div>
        </header>

        {lastError && <div className="rounded-md border border-red-900 bg-red-950/40 p-3 text-sm text-red-200">{lastError}</div>}

        <div className="grid gap-3 md:grid-cols-4">
          <StatusCard label="Runtime" value={runtime.state} detail={runtime.pid ? `pid ${runtime.pid}` : apiUrl} />
          <StatusCard label="MCP" value={mcpStatus.state} detail={mcpStatus.transport} />
          <StatusCard label="Page" value={state?.page_status ?? "idle"} detail={state?.title || "no page"} />
          <StatusCard label="Elements" value={String(state?.interactive_elements.length ?? 0)} detail={state?.focused_element_id ?? "none focused"} />
        </div>

        <Panel title="Open">
          <div className="flex gap-2">
            <input
              className="min-w-0 flex-1 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
            />
            <button className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium disabled:opacity-50" onClick={openUrl} disabled={busy || runtime.state !== "running"}>
              Open
            </button>
            <button className="rounded-md border border-slate-700 px-4 py-2 text-sm disabled:opacity-50" onClick={() => observe().catch((error) => setLastError(String(error)))} disabled={busy}>
              Observe
            </button>
          </div>
        </Panel>

        <div className="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
          <Panel title="Interactive Elements">
            <div className="max-h-[520px] overflow-auto">
              <table className="w-full text-left text-xs">
                <thead className="sticky top-0 bg-slate-950 text-slate-500">
                  <tr>
                    <th className="py-2 pr-3">ID</th>
                    <th className="py-2 pr-3">Role</th>
                    <th className="py-2 pr-3">Name</th>
                    <th className="py-2 pr-3">Value</th>
                    <th className="py-2 pr-3">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {(state?.interactive_elements ?? []).map((element) => (
                    <tr key={element.id} className="border-t border-slate-800">
                      <td className="py-2 pr-3 font-mono text-emerald-300">{element.id}</td>
                      <td className="py-2 pr-3">{element.role}</td>
                      <td className="py-2 pr-3">{element.name || element.placeholder}</td>
                      <td className="py-2 pr-3">{element.value}</td>
                      <td className="py-2 pr-3 text-slate-400">{element.actions.join(", ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title="Action">
            <div className="space-y-3">
              <textarea
                className="h-40 w-full rounded-md border border-slate-700 bg-slate-900 p-3 font-mono text-xs"
                value={actionJson}
                onChange={(event) => setActionJson(event.target.value)}
              />
              <button className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium disabled:opacity-50" onClick={runAction} disabled={busy || !state}>
                Run Action
              </button>
              <div className="text-xs text-slate-500">MCP tools: {mcpTools.join(", ")}</div>
            </div>
          </Panel>
        </div>

        <Panel title="BrowserState">
          <pre className="max-h-[520px] overflow-auto rounded-md border border-slate-800 bg-slate-950 p-4 text-xs text-slate-300">
            {JSON.stringify(state, null, 2)}
          </pre>
        </Panel>
      </section>
    </main>
  );
}

function StatusCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
      <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</div>
      <div className="mt-2 break-all text-lg font-semibold">{value}</div>
      <div className="mt-1 break-all text-sm text-slate-500">{detail}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-5">
      <h2 className="mb-4 text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}
