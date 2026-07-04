import type { BrowserElement } from "../../types/visualizer";

type ElementTableProps = {
  elements: BrowserElement[];
  focusedId: string | null;
};

export function ElementTable({ elements, focusedId }: ElementTableProps) {
  return (
    <div className="viz-elements-wrap">
      <table className="viz-elements-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Role</th>
            <th>Name</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {elements.length === 0 ? (
            <tr>
              <td colSpan={4} className="viz-empty-cell">
                暂无交互元素
              </td>
            </tr>
          ) : (
            elements.map((element) => (
              <tr key={element.id} className={element.id === focusedId ? "focused" : ""}>
                <td>
                  <span className="viz-el-id">{element.id}</span>
                </td>
                <td>
                  <span className="viz-el-role">{element.role}</span>
                </td>
                <td>{element.name || element.placeholder || element.text || "—"}</td>
                <td className="viz-el-actions">{element.actions.join(", ")}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}