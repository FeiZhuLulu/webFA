import type { BrowserState } from "../../types/visualizer";

type AgentStateInspectorProps = {
  browserState: BrowserState | null;
  expanded: boolean;
  onToggle: () => void;
};

export function AgentStateInspector({ browserState, expanded, onToggle }: AgentStateInspectorProps) {
  return (
    <div className="viz-agent-json">
      <button type="button" className="viz-section-toggle" onClick={onToggle}>
        BrowserState JSON {expanded ? "▾" : "▸"}
      </button>
      {expanded && (
        <pre className="viz-json-pre">{browserState ? JSON.stringify(browserState, null, 2) : "null"}</pre>
      )}
    </div>
  );
}