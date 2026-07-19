"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  KeyboardEvent as ReactKeyboardEvent,
  MouseEvent as ReactMouseEvent,
  ReactNode,
} from "react";

const COMPACT_LAYOUT_QUERY = "(max-width: 920px)";
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

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
  const [compactLayout, setCompactLayout] = useState(false);
  const [compactPanel, setCompactPanel] = useState<"left" | "right" | null>(null);
  const compactPanelRef = useRef<"left" | "right" | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const leftRef = useRef<HTMLElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  const rightRef = useRef<HTMLElement>(null);
  const leftToggleRef = useRef<HTMLButtonElement>(null);
  const rightToggleRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const media = window.matchMedia(COMPACT_LAYOUT_QUERY);
    const syncLayout = () => setCompactLayout(media.matches);
    syncLayout();
    media.addEventListener("change", syncLayout);
    return () => media.removeEventListener("change", syncLayout);
  }, []);

  compactPanelRef.current = compactPanel;

  const closeCompactPanel = useCallback((restoreFocus = true) => {
    const current = compactPanelRef.current;
    compactPanelRef.current = null;
    setCompactPanel(null);
    if (restoreFocus && current) {
      const target = current === "left" ? leftToggleRef.current : rightToggleRef.current;
      window.setTimeout(() => target?.focus(), 0);
    }
  }, []);

  useEffect(() => {
    if (!compactLayout && compactPanel) {
      closeCompactPanel(false);
    } else if (
      (compactPanel === "left" && leftCollapsed) ||
      (compactPanel === "right" && rightCollapsed)
    ) {
      closeCompactPanel();
    }
  }, [closeCompactPanel, compactLayout, compactPanel, leftCollapsed, rightCollapsed]);

  useEffect(() => {
    const backgroundIsInert = compactLayout && compactPanel !== null;
    mainRef.current?.toggleAttribute("inert", backgroundIsInert);
    const header = rootRef.current?.querySelector<HTMLElement>(".viz-app-header");
    header?.toggleAttribute("inert", backgroundIsInert);
    return () => {
      mainRef.current?.removeAttribute("inert");
      header?.removeAttribute("inert");
    };
  }, [compactLayout, compactPanel]);

  useEffect(() => {
    if (!compactLayout || !compactPanel) return;
    const panel = compactPanel === "left" ? leftRef.current : rightRef.current;
    window.setTimeout(() => panel?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)?.focus(), 0);
  }, [compactLayout, compactPanel]);

  const openCompactPanel = (panel: "left" | "right") => {
    if (panel === "left" && leftCollapsed) onToggleLeft();
    if (panel === "right" && rightCollapsed) onToggleRight();
    setCompactPanel(panel);
  };

  const handleDrawerKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (!compactPanel) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeCompactPanel();
      return;
    }
    if (event.key !== "Tab") return;

    const focusable = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
      (element) => element.getClientRects().length > 0,
    );
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const handlePanelClickCapture = (
    panel: "left" | "right",
    event: ReactMouseEvent<HTMLElement>,
  ) => {
    if (!compactLayout) return;
    const target = event.target instanceof Element ? event.target : null;
    if (!target?.closest(`[data-webfa-panel-collapse="${panel}"]`)) return;
    event.preventDefault();
    event.stopPropagation();
    closeCompactPanel();
  };

  const leftHidden = leftCollapsed || (compactLayout && compactPanel !== "left");
  const rightHidden = rightCollapsed || (compactLayout && compactPanel !== "right");
  const showToolbar = compactLayout || leftCollapsed || rightCollapsed;

  return (
    <div className={`viz-app${compactLayout ? " compact-layout" : ""}`} ref={rootRef}>
      <a className="viz-skip-link" href="#webfa-main-content">跳至主要内容</a>
      {header}
      <div className="viz-dashboard">
        <aside
          id="webfa-control-panel"
          ref={leftRef}
          className={`viz-column viz-column-left${leftCollapsed ? " collapsed" : ""}`}
          aria-label="WebFA 控制面板"
          aria-hidden={leftHidden}
          aria-modal={compactLayout && !leftHidden ? true : undefined}
          role={compactLayout ? "dialog" : undefined}
          hidden={leftHidden}
          onClickCapture={(event) => handlePanelClickCapture("left", event)}
          onKeyDown={handleDrawerKeyDown}
        >
          {left}
        </aside>
        {compactLayout && compactPanel && (
          <div
            className="viz-drawer-backdrop"
            data-panel={compactPanel}
            aria-hidden="true"
            onPointerDown={() => closeCompactPanel()}
          />
        )}
        <main id="webfa-main-content" className="viz-column-main" ref={mainRef} tabIndex={-1}>
          {showToolbar && (
            <div className="viz-main-toolbar">
              <div className="viz-main-toolbar-group">
                {(compactLayout || leftCollapsed) && (
                  <button
                    ref={leftToggleRef}
                    type="button"
                    className="viz-toggle-btn"
                    onClick={() => (compactLayout ? openCompactPanel("left") : onToggleLeft())}
                    aria-label="展开控制面板"
                    aria-controls="webfa-control-panel"
                    aria-expanded={!leftHidden}
                  >
                    <svg className="viz-icon" viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
                      <polyline points="9 18 15 12 9 6" />
                    </svg>
                    <span>控制面板</span>
                  </button>
                )}
              </div>
              <div className="viz-main-toolbar-group">
                {(compactLayout || rightCollapsed) && (
                  <button
                    ref={rightToggleRef}
                    type="button"
                    className="viz-toggle-btn"
                    onClick={() => (compactLayout ? openCompactPanel("right") : onToggleRight())}
                    aria-label="展开 Runtime 投影"
                    aria-controls="webfa-agent-view"
                    aria-expanded={!rightHidden}
                  >
                    <span>Runtime 投影</span>
                    <svg className="viz-icon" viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
                      <polyline points="15 18 9 12 15 6" />
                    </svg>
                  </button>
                )}
              </div>
            </div>
          )}
          {main}
        </main>
        <aside
          id="webfa-agent-view"
          ref={rightRef}
          className={`viz-column viz-column-right${rightCollapsed ? " collapsed" : ""}`}
          aria-label="Runtime 投影"
          aria-hidden={rightHidden}
          aria-modal={compactLayout && !rightHidden ? true : undefined}
          role={compactLayout ? "dialog" : undefined}
          hidden={rightHidden}
          onClickCapture={(event) => handlePanelClickCapture("right", event)}
          onKeyDown={handleDrawerKeyDown}
        >
          {right}
        </aside>
      </div>
    </div>
  );
}
