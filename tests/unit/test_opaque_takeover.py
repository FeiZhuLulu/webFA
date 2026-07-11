from __future__ import annotations

from browser.raw_snapshot import RawDOMDocument, RawDOMNode, RawFrameEvidence, RawWebSnapshot
from browser.runtime import BrowserRuntime
from schemas.browser import BrowserTab, BrowserViewport
from schemas.web import WebObject, WebObserveRequest, WebOperationRequest


class OpaqueFixtureDriver:
    def __init__(self) -> None:
        self.url = "https://example.com/editor"
        self.closed = False

    def open(self, url: str) -> None:
        self.url = url

    def observe_web_raw(self) -> RawWebSnapshot:
        return _snapshot(self.url)

    def observe_raw(self):
        return self.observe_web_raw().to_page_snapshot()

    def act(self, request) -> None:
        raise AssertionError(f"opaque takeover must not execute a primitive action: {request}")

    def tabs(self):
        return [BrowserTab(id="tab_1", url=self.url, title="Editor", active=True)]

    def switch_tab(self, tab_id: str) -> None:
        raise ValueError(tab_id)

    def close(self) -> None:
        self.closed = True

    def status(self) -> dict:
        return {"host_status": "running", "visible_window": False}


def _snapshot(url: str = "https://example.com/editor") -> RawWebSnapshot:
    return RawWebSnapshot(
        url=url,
        title="Diagram editor",
        loading=False,
        focused_element_id=None,
        viewport=BrowserViewport(width=1280, height=720),
        tabs=[BrowserTab(id="tab_1", url=url, title="Editor", active=True)],
        visible_text="Diagram editor",
        frames=[
            {
                "id": "frame_1",
                "parent_id": None,
                "url": url,
                "title": "Diagram editor",
                "same_origin": True,
                "visible": True,
            }
        ],
        dom_documents=[
            RawDOMDocument(
                document_index=0,
                frame_id="cdp-main",
                url=url,
                title="Diagram editor",
                base_url="https://example.com/",
                content_language="en",
                encoding_name="UTF-8",
                nodes=(
                    RawDOMNode(
                        document_index=0,
                        node_index=0,
                        backend_node_id=500,
                        parent_index=None,
                        node_type=1,
                        node_name="CANVAS",
                        node_value="",
                        attributes={"aria-label": "Diagram workspace"},
                        bounds=(20.0, 40.0, 900.0, 560.0),
                    ),
                ),
            )
        ],
        engine_frames=[
            RawFrameEvidence(
                frame_id="cdp-main",
                parent_id=None,
                url=url,
                loader_id="loader-editor",
                security_origin="https://example.com",
                mime_type="text/html",
            )
        ],
    )


def test_compiler_exposes_visible_canvas_as_explicit_opaque_surface():
    runtime = BrowserRuntime(driver_factory=OpaqueFixtureDriver)
    try:
        runtime.open("https://example.com/editor", agent_id="opaque-test")
        observed = runtime.observe_web(WebObserveRequest(mode="page", detail="full"))
        opaque = next(
            item
            for item in observed.state.objects
            if isinstance(item, WebObject) and item.role == "opaque_surface"
        )

        assert opaque.name == "Diagram workspace"
        assert opaque.opaque_reason == "canvas_without_semantic_objects"
        assert opaque.capabilities == ["request_human_takeover"]
        assert opaque.origin == "https://example.com"
    finally:
        runtime.close()


def test_opaque_takeover_preserves_reason_target_origin_across_observe():
    runtime = BrowserRuntime(driver_factory=OpaqueFixtureDriver)
    try:
        runtime.open("https://example.com/editor", agent_id="opaque-test")
        observed = runtime.observe_web(WebObserveRequest(mode="page", detail="full"))
        opaque = next(
            item
            for item in observed.state.objects
            if isinstance(item, WebObject) and item.role == "opaque_surface"
        )

        result = runtime.act_web(
            WebOperationRequest(
                target=opaque.id,
                operation="request_human_takeover",
                expected_object_version=opaque.version,
            ),
            agent_id="opaque-test",
        )

        assert result.state.takeover.required is True
        assert result.state.takeover.reason == "opaque_surface"
        assert result.state.takeover.target == opaque.id
        assert result.state.takeover.origin == "https://example.com"
        assert result.state.auth.surface_detected is False

        takeover_view = runtime.observe_web(WebObserveRequest(mode="page"))
        assert takeover_view.state.document_id == "human_takeover"
        assert takeover_view.state.title == "WebFA Human Takeover"
        assert takeover_view.state.takeover.reason == "opaque_surface"
        assert takeover_view.state.takeover.target == opaque.id
        assert takeover_view.state.takeover.origin == "https://example.com"

        status = runtime.status()
        assert status["takeover_active"] is True
        assert status["takeover_reason"] == "opaque_surface"
        assert status["takeover_target"] == opaque.id
    finally:
        runtime.close()
