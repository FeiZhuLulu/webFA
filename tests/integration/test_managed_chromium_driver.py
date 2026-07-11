from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from browser.host_driver import HostBrowserDriver
from browser.managed_chromium_host import ManagedChromiumHost, _find_chromium_executable
from browser.object_registry import ObjectRegistry
from browser.runtime import BrowserRuntime
from browser.web_object_compiler import WebObjectCompiler
from browser.web_observe import WebObserveService
from schemas.browser import BrowserActionRequest
from schemas.web import WebObserveQuery, WebObserveRequest, WebOperationRequest
from storage.db import reset_engine_for_tests


FIXTURE_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "agent_validation_page.html"
STRUCTURED_READING_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "structured_reading_page.html"


def _require_managed_chromium() -> None:
    pytest.importorskip("websockets.sync.client")
    try:
        _find_chromium_executable()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def test_managed_chromium_collects_p10_raw_web_snapshot(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))

    host = ManagedChromiumHost(headless=True)
    driver = HostBrowserDriver(host)
    try:
        driver.open(FIXTURE_PAGE.as_uri())
        snapshot = driver.observe_web_raw()

        assert snapshot.url == FIXTURE_PAGE.as_uri()
        assert snapshot.accessibility_nodes
        assert snapshot.dom_documents
        assert snapshot.engine_frames
        assert snapshot.evidence_errors == []
        assert any(node.backend_dom_node_id is not None for node in snapshot.accessibility_nodes)
        assert any(document.nodes for document in snapshot.dom_documents)

        legacy = snapshot.to_page_snapshot()
        assert legacy.title == "WebFA Agent Validation"
        assert legacy.interactive_elements
    finally:
        driver.close()


def test_managed_chromium_compiles_real_web_objects(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))

    host = ManagedChromiumHost(headless=True)
    driver = HostBrowserDriver(host)
    try:
        driver.open(FIXTURE_PAGE.as_uri())
        snapshot = driver.observe_web_raw()
        compilation = WebObjectCompiler().compile(snapshot)
        roles = {item.role for item in compilation.state.objects}

        assert {"document", "frame", "heading", "form", "textbox", "button"}.issubset(roles)
        assert compilation.state.outline
        assert compilation.state.object_count == len(compilation.state.objects)
        assert compilation.provenance
        assert all(
            not set(item.capabilities).intersection({"click", "double_click", "type", "press", "focus"})
            for item in compilation.state.objects
        )
    finally:
        driver.close()


def test_managed_chromium_compiles_structured_reading_objects(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))

    host = ManagedChromiumHost(headless=True)
    driver = HostBrowserDriver(host)
    try:
        driver.open(STRUCTURED_READING_PAGE.as_uri())
        snapshot = driver.observe_web_raw()
        compilation = WebObjectCompiler().compile(snapshot)
        objects = [item for item in compilation.state.objects if hasattr(item, "role")]
        list_object = next(item for item in objects if item.role == "list")
        table = next(item for item in objects if item.role == "table")
        form = next(item for item in objects if item.role == "form")
        status = next(item for item in objects if item.role == "status")

        assert list_object.observable.range_readable is True
        assert list_object.observable.item_count == 2
        assert len(list_object.relations.items) == 2
        assert table.observable.range_readable is True
        assert table.observable.item_count == 3
        assert len(table.relations.rows) == 3
        assert len(table.relations.headers) >= 2
        assert len(form.relations.fields) == 2
        assert form.relations.submit_control is not None
        assert status.text == "Report ready"
    finally:
        driver.close()


def test_managed_chromium_registry_keeps_identity_and_tracks_changes(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))

    host = ManagedChromiumHost(headless=True)
    driver = HostBrowserDriver(host)
    compiler = WebObjectCompiler()
    registry = ObjectRegistry()
    try:
        driver.open(FIXTURE_PAGE.as_uri())
        first = registry.update(compiler.compile(driver.observe_web_raw()))
        field = next(item for item in first.state.objects if getattr(item, "role", None) == "textbox")
        legacy_field = registry.legacy_target_for(field.id)
        assert legacy_field

        driver.act(BrowserActionRequest(action="type", target=legacy_field, text="Fei"))
        second = registry.update(compiler.compile(driver.observe_web_raw()))
        updated_field = next(item for item in second.state.objects if getattr(item, "role", None) == "textbox")

        assert updated_field.id == field.id
        assert updated_field.version == field.version + 1
        assert second.state.document_id == first.state.document_id
        assert second.state.document_revision == first.state.document_revision + 1
        assert next(item for item in second.changes.updated if item.id == field.id)

        observe_service = WebObserveService(registry)
        page_view = observe_service.observe(
            WebObserveRequest(mode="page", detail="summary", limit=10)
        )
        query_view = observe_service.observe(
            WebObserveRequest(
                mode="query",
                query=WebObserveQuery(capability="set_value", visible=True),
                detail="summary",
            )
        )
        changes_view = observe_service.observe(
            WebObserveRequest(
                mode="changes",
                since_revision=first.state.document_revision,
                detail="summary",
            )
        )

        assert page_view.state.objects
        assert any(item.role in {"textbox", "searchbox"} for item in query_view.state.objects)
        assert any(item.id == field.id for item in changes_view.state.objects)

        host.evaluate("history.pushState({}, '', '?view=updated')")
        third = registry.update(compiler.compile(driver.observe_web_raw()))
        pushed_field = next(item for item in third.state.objects if getattr(item, "role", None) == "textbox")

        assert third.state.document_id == second.state.document_id
        assert pushed_field.id == updated_field.id
        assert third.state.document_revision == second.state.document_revision + 1
        assert third.changes.document_changed_fields == ["url"]
    finally:
        driver.close()


def test_browser_runtime_internal_queryable_observe_coexists_with_legacy_state(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))

    runtime = BrowserRuntime(
        headless=True,
        driver_factory=lambda: HostBrowserDriver(ManagedChromiumHost(headless=True)),
    )
    try:
        runtime.open(FIXTURE_PAGE.as_uri(), agent_id="p10-test")
        initial = runtime.observe_web(
            WebObserveRequest(mode="page", detail="debug", limit=20),
            allow_debug=True,
        )
        field = next(
            item
            for item in initial.state.objects
            if getattr(item, "role", None) in {"textbox", "searchbox"}
        )
        legacy_target = initial.debug_provenance[field.id].legacy_id
        assert legacy_target
        assert initial.state.agent.active_agent_id == "p10-test"

        operation = runtime.act_web(
            WebOperationRequest(
                target=field.id,
                operation="set_value",
                arguments={"value": "Fei"},
                expected_object_version=field.version,
            ),
            agent_id="p10-test",
        )
        changes = runtime.observe_web(
            WebObserveRequest(
                mode="changes",
                since_revision=initial.state.document_revision,
                detail="summary",
            )
        )
        legacy_state = runtime.observe()

        assert operation.previous_object_version == field.version
        assert operation.current_object_version == field.version + 1
        assert operation.state.agent.active_agent_id == "p10-test"
        assert any(item.id == field.id for item in changes.state.objects)
        assert changes.state.changes.updated
        assert legacy_state.interactive_elements
        assert changes.state.agent.active_agent_id == "p10-test"
    finally:
        runtime.close()


def test_managed_chromium_open_observe_act_loop(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_DRIVER", "managed-chromium")
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        opened = client.post("/v1/browser/open", json={"url": FIXTURE_PAGE.as_uri()})
        assert opened.status_code == 200, opened.text
        state = opened.json()["state"]
        assert state["title"] == "WebFA Agent Validation"
        assert state["url_parts"]["scheme"] == "file"
        assert "WebFA Agent Validation" in state["visible_text"]
        assert state["content_blocks"]

        tabs = client.get("/v1/browser/tabs")
        assert tabs.status_code == 200, tabs.text
        assert tabs.json()["tabs"]

        name_el = next(el for el in state["interactive_elements"] if el["placeholder"] == "Your name")
        button_el = next(el for el in state["interactive_elements"] if el["role"] == "button")

        typed = client.post("/v1/browser/act", json={"action": "type", "target": name_el["id"], "text": "Fei"})
        assert typed.status_code == 200, typed.text
        typed_el = next(el for el in typed.json()["state"]["interactive_elements"] if el["placeholder"] == "Your name")
        assert typed_el["value"] == "Fei"

        clicked = client.post("/v1/browser/act", json={"action": "click", "target": button_el["id"]})
        assert clicked.status_code == 200, clicked.text
        assert "Hello Fei" in clicked.json()["state"]["visible_text"]


def test_managed_chromium_rejects_unsupported_actions(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_DRIVER", "managed-chromium")
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        state = client.post("/v1/browser/open", json={"url": FIXTURE_PAGE.as_uri()}).json()["state"]
        name_el = next(el for el in state["interactive_elements"] if el["placeholder"] == "Your name")
        unsupported = client.post("/v1/browser/act", json={"action": "select", "target": name_el["id"], "value": "x"})

    assert unsupported.status_code == 400
    detail = unsupported.json()["detail"]
    assert "element is not a select" in str(detail.get("message", detail))


def test_managed_chromium_object_form_actions(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_DRIVER", "managed-chromium")
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        state = client.post("/v1/browser/open", json={"url": FIXTURE_PAGE.as_uri()}).json()["state"]
        assert state["forms"][0]["field_details"][0]["key"] == "name"

        filled = client.post("/v1/browser/act", json={"action": "fill_form", "target": "form_1", "fields": {"name": "Fei"}})
        assert filled.status_code == 200, filled.text
        field = filled.json()["state"]["forms"][0]["field_details"][0]
        assert field["value"] == "Fei"

        submitted = client.post("/v1/browser/act", json={"action": "submit_form", "target": "form_1"})
        assert submitted.status_code == 200, submitted.text
        assert "Hello Fei" in submitted.json()["state"]["visible_text"]


def test_managed_chromium_double_click_and_row_elements(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_DRIVER", "managed-chromium")
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    reset_engine_for_tests()

    page = tmp_path / "rows.html"
    page.write_text(
        """
        <!doctype html>
        <title>Rows</title>
        <div role="row" ondblclick="result.textContent='Opened first mail'">First mail subject</div>
        <div role="row" ondblclick="result.textContent='Opened second mail'">Second mail subject</div>
        <div id="result"></div>
        """,
        encoding="utf-8",
    )

    with TestClient(create_app()) as client:
        state = client.post("/v1/browser/open", json={"url": page.as_uri()}).json()["state"]
        row = next(el for el in state["interactive_elements"] if "First mail subject" in el["text"])
        owning = [block for block in state["content_blocks"] if "First mail subject" in block["text"]]
        assert owning
        assert row["id"] in owning[0]["element_ids"]

        opened = client.post("/v1/browser/act", json={"action": "double_click", "target": row["id"]})
        assert opened.status_code == 200, opened.text
        assert "Opened first mail" in opened.json()["state"]["visible_text"]


def test_managed_chromium_type_updates_react_like_controlled_input(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_DRIVER", "managed-chromium")
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    reset_engine_for_tests()

    page = tmp_path / "controlled.html"
    page.write_text(
        """
        <!doctype html>
        <title>Controlled</title>
        <input id="phone" placeholder="Phone">
        <button onclick="phone.value = phone.dataset.state || ''">Send code</button>
        <script>
          phone.addEventListener('input', () => phone.dataset.state = phone.value);
        </script>
        """,
        encoding="utf-8",
    )

    with TestClient(create_app()) as client:
        state = client.post("/v1/browser/open", json={"url": page.as_uri()}).json()["state"]
        phone = next(el for el in state["interactive_elements"] if el["placeholder"] == "Phone")
        button = next(el for el in state["interactive_elements"] if el["role"] == "button")
        typed = client.post("/v1/browser/act", json={"action": "type", "target": phone["id"], "text": "13800138000"})
        assert typed.status_code == 200, typed.text
        clicked = client.post("/v1/browser/act", json={"action": "click", "target": button["id"]})
        assert clicked.status_code == 200, clicked.text
        field = next(el for el in clicked.json()["state"]["interactive_elements"] if el["placeholder"] == "Phone")
        assert field["value"] == "13800138000"


def test_managed_chromium_restarts_after_process_exit(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))

    host = ManagedChromiumHost(headless=True)
    try:
        host.navigate(FIXTURE_PAGE.as_uri())
        first = host.status()
        assert first["host_status"] == "running"

        assert host._process is not None
        host._process.kill()
        host._process.wait(timeout=5)
        assert host.status()["host_status"] == "exited"

        host.navigate(FIXTURE_PAGE.as_uri())
        restarted = host.status()
        assert restarted["host_status"] == "running"
        assert restarted["last_error"] is None
    finally:
        host.close()
