"use client";

import type { ReactNode } from "react";

type VisualizerShellProps = {
  header: ReactNode;
  left: ReactNode;
  main: ReactNode;
  right: ReactNode;
  leftCollapsed: boolean;
  rightCollapsed: boolean;
  onToggleLeft: () => void;
  onToggleRight: () => void;
};

export function VisualizerShell({
  header,
  left,
  main,
  right,
  leftCollapsed,
  rightCollapsed,
  onToggleLeft,
  onToggleRight,
}: VisualizerShellProps) {
  return (
    <div className="viz-app">
      {header}
      <div className="viz-dashboard">
        <aside className={`viz-column viz-column-left${leftCollapsed ? " collapsed" : ""}`}>{left}</aside>
        <main className="viz-column-main">
          {(leftCollapsed || rightCollapsed) && (
            <div className="viz-main-toolbar" style={{ display: "flex", justifyContent: "space-between", padding: "6px 12px", minHeight: "36px", alignItems: "center" }}>
              <div>
                {leftCollapsed && (
                  <button type="button" className="viz-toggle-btn" onClick={onToggleLeft} title="展开左侧" style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                    <svg className="viz-icon" viewBox="0 0 24 24" width="12" height="12">
                      <polyline points="9 18 15 12 9 6" />
                    </svg>
                    <span>展开左侧</span>
                  </button>
                )}
              </div>
              <div>
                {rightCollapsed && (
                  <button type="button" className="viz-toggle-btn" onClick={onToggleRight} title="展开右侧" style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                    <span>展开右侧</span>
                    <svg className="viz-icon" viewBox="0 0 24 24" width="12" height="12">
                      <polyline points="15 18 9 12 15 6" />
                    </svg>
                  </button>
                )}
              </div>
            </div>
          )}
          {main}
        </main>
        <aside className={`viz-column viz-column-right${rightCollapsed ? " collapsed" : ""}`}>{right}</aside>
      </div>
    </div>
  );
}