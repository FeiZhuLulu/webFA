import type { BrowserContentBlock } from "../../types/visualizer";

type ContentBlocksListProps = {
  blocks: BrowserContentBlock[];
};

export function ContentBlocksList({ blocks }: ContentBlocksListProps) {
  if (!blocks.length) {
    return <div className="viz-empty-note">暂无内容块</div>;
  }

  return (
    <div className="viz-blocks-list">
      {blocks.map((block) => (
        <div key={block.id} className="viz-block-card">
          <div className="viz-block-header">
            <span className="viz-block-badge">{block.type}</span>
            {block.element_ids.length > 0 && (
              <div className="viz-block-pills">
                {block.element_ids.map((id) => (
                  <span key={id} className="viz-el-pill">
                    {id}
                  </span>
                ))}
              </div>
            )}
          </div>
          <div className="viz-block-text">{block.text}</div>
        </div>
      ))}
    </div>
  );
}