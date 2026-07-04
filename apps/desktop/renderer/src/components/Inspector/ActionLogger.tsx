"use client";

import { useEffect, useRef } from "react";
import type { VisualizerActionEntry } from "../../types/visualizer";

type ActionLoggerProps = {
  entries: VisualizerActionEntry[];
};

function formatTime(timestamp: string): string {
  try {
    return new Date(timestamp).toLocaleTimeString();
  } catch {
    return timestamp;
  }
}

export function ActionLogger({ entries }: ActionLoggerProps) {
  const consoleRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = consoleRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [entries]);

  return (
    <div className="viz-console" ref={consoleRef}>
      {entries.length === 0 ? (
        <div className="viz-console-line muted">等待 agent 操作…</div>
      ) : (
        entries.map((entry, index) => (
          <div key={`${entry.timestamp}-${entry.tool}-${index}`} className="viz-console-line">
            <span className="viz-line-time">[{formatTime(entry.timestamp)}]</span>
            <span className={`viz-line-tag ${entry.status === "error" ? "warn" : entry.tool.startsWith("webfa.") ? "call" : "info"}`}>
              {entry.status === "error" ? "ERR" : entry.tool.startsWith("webfa.") ? "CALL" : "INFO"}:
            </span>
            <span>
              {entry.tool}
              {entry.message ? ` — ${entry.message}` : ""}
              {entry.code ? ` (${entry.code})` : ""}
              {entry.agent_id ? ` [${entry.agent_id}]` : ""}
            </span>
          </div>
        ))
      )}
    </div>
  );
}