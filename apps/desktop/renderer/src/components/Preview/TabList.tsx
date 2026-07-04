import type { BrowserState } from "../../types/visualizer";

type TabListProps = {
  tabs: BrowserState["tabs"];
};

export function TabList({ tabs }: TabListProps) {
  if (!tabs.length) {
    return <div className="viz-tab-bar empty">无标签页</div>;
  }

  return (
    <div className="viz-tab-bar">
      {tabs.map((tab) => (
        <div key={tab.id} className={`viz-tab-item${tab.active ? " active" : ""}`} title={tab.url}>
          <span className="viz-tab-title">{tab.title || tab.url || tab.id}</span>
        </div>
      ))}
    </div>
  );
}