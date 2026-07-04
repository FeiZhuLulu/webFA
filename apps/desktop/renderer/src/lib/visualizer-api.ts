import type { VisualizerState } from "../types/visualizer";

const API_FALLBACK = "http://127.0.0.1:8787";

export function resolveApiUrl(preferred?: string | null): string {
  return preferred || API_FALLBACK;
}

async function readApiError(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string | { code?: string; message?: string } };
    const detail = body.detail;
    if (typeof detail === "string" && detail) return detail;
    if (detail && typeof detail === "object") {
      const code = detail.code ? `[${detail.code}] ` : "";
      return `${code}${detail.message || fallback}`;
    }
  } catch {
    // ignore parse errors
  }
  if (response.status === 404) {
    return "Visualizer API 不存在，请重启 Runtime 到最新版本";
  }
  return `${fallback} (${response.status})`;
}

export async function fetchVisualizerState(apiUrl: string): Promise<VisualizerState> {
  const response = await fetch(`${apiUrl}/v1/visualizer/state`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Visualizer state failed"));
  }
  return (await response.json()) as VisualizerState;
}

export async function restartHost(apiUrl: string): Promise<VisualizerState> {
  const response = await fetch(`${apiUrl}/v1/visualizer/restart-host`, { method: "POST" });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Restart host failed"));
  }
  return (await response.json()) as VisualizerState;
}

export async function openVisibleHost(apiUrl: string): Promise<VisualizerState> {
  const response = await fetch(`${apiUrl}/v1/visualizer/open-host`, { method: "POST" });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Open host failed"));
  }
  return (await response.json()) as VisualizerState;
}