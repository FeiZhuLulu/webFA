from __future__ import annotations

from browser.object_registry import ObjectRegistry
from browser.raw_snapshot import RawAccessibilityNode, RawFrameEvidence, RawWebSnapshot
from browser.web_object_compiler import WebObjectCompiler
from browser.web_observe import WebObserveService
from schemas.browser import BrowserTab, BrowserViewport
from schemas.web import WebObject, WebObserveRequest


def _snapshot() -> RawWebSnapshot:
    url = "https://example.com/report"
    nodes = [
        RawAccessibilityNode(
            node_id="ax_main",
            role="main",
            name="Report",
            child_ids=("ax_heading", "ax_list", "ax_table"),
        ),
        RawAccessibilityNode(
            node_id="ax_heading",
            role="heading",
            name="Quarterly report",
            parent_id="ax_main",
            properties={"level": 1},
        ),
        RawAccessibilityNode(
            node_id="ax_list",
            role="list",
            name="Highlights",
            parent_id="ax_main",
            child_ids=("ax_item_1", "ax_item_2"),
        ),
        RawAccessibilityNode(
            node_id="ax_item_1",
            role="listitem",
            name="Revenue increased",
            parent_id="ax_list",
        ),
        RawAccessibilityNode(
            node_id="ax_item_2",
            role="listitem",
            name="Costs decreased",
            parent_id="ax_list",
        ),
        RawAccessibilityNode(
            node_id="ax_table",
            role="table",
            name="Metrics",
            parent_id="ax_main",
            child_ids=("ax_row_head", "ax_row_data"),
        ),
        RawAccessibilityNode(
            node_id="ax_row_head",
            role="row",
            name="Headers",
            parent_id="ax_table",
            child_ids=("ax_header_metric", "ax_header_value"),
        ),
        RawAccessibilityNode(
            node_id="ax_header_metric",
            role="columnheader",
            name="Metric",
            parent_id="ax_row_head",
        ),
        RawAccessibilityNode(
            node_id="ax_header_value",
            role="columnheader",
            name="Value",
            parent_id="ax_row_head",
        ),
        RawAccessibilityNode(
            node_id="ax_row_data",
            role="row",
            name="Revenue row",
            parent_id="ax_table",
            child_ids=("ax_cell_metric", "ax_cell_value"),
        ),
        RawAccessibilityNode(
            node_id="ax_cell_metric",
            role="cell",
            name="Revenue",
            parent_id="ax_row_data",
        ),
        RawAccessibilityNode(
            node_id="ax_cell_value",
            role="cell",
            name="$120",
            parent_id="ax_row_data",
        ),
    ]
    return RawWebSnapshot(
        url=url,
        title="Quarterly report",
        loading=False,
        focused_element_id=None,
        viewport=BrowserViewport(width=1280, height=720),
        tabs=[BrowserTab(id="tab_1", url=url, title="Quarterly report", active=True)],
        visible_text="Quarterly report Revenue increased Costs decreased Metric Value Revenue $120",
        content_blocks=[],
        forms=[],
        interactive_elements=[],
        dialogs=[],
        frames=[
            {
                "id": "frame_1",
                "parent_id": None,
                "url": url,
                "title": "Quarterly report",
                "same_origin": True,
                "visible": True,
            }
        ],
        accessibility_nodes=nodes,
        engine_frames=[
            RawFrameEvidence(
                frame_id="frame-main",
                parent_id=None,
                url=url,
                loader_id="loader-report",
                security_origin="https://example.com",
                mime_type="text/html",
            )
        ],
    )


def _by_role(state, role: str) -> list[WebObject]:
    return [item for item in state.objects if isinstance(item, WebObject) and item.role == role]


def test_compiler_builds_explicit_list_and_table_relationships():
    compilation = WebObjectCompiler().compile(_snapshot())
    state = compilation.state

    list_object = _by_role(state, "list")[0]
    list_items = _by_role(state, "list_item")
    table = _by_role(state, "table")[0]
    rows = _by_role(state, "row")
    column_headers = _by_role(state, "column_header")
    cells = _by_role(state, "cell")

    assert list_object.relations.items == [item.id for item in list_items]
    assert list_object.observable.range_readable is True
    assert list_object.observable.item_count == 2
    assert list_object.observable.visible_range.start == 0
    assert list_object.observable.visible_range.end == 1
    assert all(item.relations.belongs_to == list_object.id for item in list_items)
    assert [item.text for item in list_items] == ["Revenue increased", "Costs decreased"]

    assert table.relations.rows == [item.id for item in rows]
    assert table.relations.items == table.relations.rows
    assert table.relations.headers == [item.id for item in column_headers]
    assert table.observable.item_count == 2
    assert rows[0].relations.cells == [item.id for item in column_headers]
    assert rows[1].relations.cells == [item.id for item in cells]
    assert rows[1].observable.item_count == 2
    assert [item.text for item in cells] == ["Revenue", "$120"]


def test_object_range_reads_semantic_table_rows_not_arbitrary_children():
    registry = ObjectRegistry()
    registered = registry.update(WebObjectCompiler().compile(_snapshot()))
    table = _by_role(registered.state, "table")[0]
    second_row = _by_role(registered.state, "row")[1]

    result = WebObserveService(registry).observe(
        WebObserveRequest(
            mode="object",
            target=table.id,
            range={"start": 1, "limit": 1},
            detail="full",
        )
    )
    returned = [item for item in result.state.objects if isinstance(item, WebObject)]
    projected_table = returned[0]

    assert len(returned) == 2
    assert returned[1].id == second_row.id
    assert projected_table.relations.rows == [second_row.id]
    assert projected_table.relations.items == [second_row.id]
    assert projected_table.observable.item_count == 2
    assert projected_table.observable.visible_range.start == 1
    assert projected_table.observable.visible_range.end == 1
