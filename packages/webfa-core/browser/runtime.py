from __future__ import annotations

import queue
import threading
from typing import Any, Callable

from browser.agent_lease import AgentLease, AgentLeaseSnapshot
from browser.agent_view import AgentViewBuilder
from browser.config import resolve_browser_runtime_config
from browser.driver import BrowserDriver, RawPageSnapshot
from browser.driver_factory import create_default_driver_factory
from browser.exceptions import BrowserHostClosedError
from browser.runtime_errors import BrowserRuntimeError
from browser.runtime_errors import auth_surface_active as auth_surface_active_error
from browser.runtime_errors import dialog_not_found
from browser.runtime_errors import dialog_required as dialog_required_error
from browser.runtime_errors import stale_element as stale_element_error
from browser.url_policy import enforce_navigation_allowed
from browser.session import BrowserSession
from schemas.browser import (
    BrowserActionRequest,
    BrowserActionResult,
    BrowserAgentState,
    BrowserAuthState,
    BrowserElement,
    BrowserForm,
    BrowserState,
    BrowserTab,
)


DriverFactory = Callable[[], BrowserDriver]


class BrowserRuntime:
    """Single-session agent browser runtime backed by one driver thread."""

    def __init__(self, headless: bool | None = None, driver_factory: DriverFactory | None = None) -> None:
        config = resolve_browser_runtime_config(headless=headless)
        self._driver_name = config.driver_name
        self._headless = config.headless
        self._auth_takeover = config.auth_takeover
        self._auth_surface_mode = config.auth_surface_mode
        self._private_url_policy = config.private_url_policy
        self._driver_factory = driver_factory or create_default_driver_factory(self._driver_name, self._headless)
        self._jobs: queue.Queue[tuple[str, tuple, queue.Queue] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._closed = False
        self._agent_lease = AgentLease()

    def open(self, url: str, agent_id: str | None = None) -> BrowserActionResult:
        self._agent_lease.acquire(agent_id)
        return self._with_agent_result(self._call("open", url))

    def observe(self) -> BrowserState:
        return self._with_agent_state(self._call("observe"))

    def act(self, request: BrowserActionRequest, agent_id: str | None = None) -> BrowserActionResult:
        self._agent_lease.acquire(agent_id)
        return self._with_agent_result(self._call("act", request))

    def tabs(self) -> list[BrowserTab]:
        return self._call("tabs")

    def switch_tab(self, tab_id: str, agent_id: str | None = None) -> BrowserState:
        self._agent_lease.acquire(agent_id)
        return self._with_agent_state(self._call("switch_tab", tab_id))

    def capture_preview(self) -> str | None:
        if self._closed:
            return None
        if self._thread is None:
            return None
        try:
            return self._call("capture_preview")
        except Exception:
            return None

    def restart_host(self) -> BrowserState:
        return self._with_agent_state(self._call("restart_host"))

    def relaunch_visible_host(self) -> BrowserState:
        return self._with_agent_state(self._call("relaunch_visible_host"))

    def open_auth_surface(self, url: str | None = None) -> BrowserState:
        return self._with_agent_state(self._call("open_auth_surface", url))

    def close_auth_surface(self, url: str | None = None) -> BrowserState:
        return self._with_agent_state(self._call("close_auth_surface", url))

    def status(self) -> dict[str, Any]:
        lease = self._agent_lease.snapshot().as_dict()
        base = {
            "selected_driver": self._driver_name,
            "headless": self._headless,
            "auth_takeover": self._auth_takeover,
            "auth_surface_mode": self._auth_surface_mode,
            "visible_window": False,
            "session_id": "default",
            "profile_id": "default",
            "profile_shared": True,
            **lease,
            "host_status": "not_started",
            "last_error": None,
        }
        if self._closed:
            return {**base, "host_status": "closed"}
        if self._thread is None:
            return base
        try:
            worker_status = self._call("status")
            return {**base, **worker_status}
        except Exception as exc:
            return {**base, "host_status": "error", "last_error": str(exc)}

    def close(self) -> None:
        if self._thread is None or self._closed:
            return
        result: queue.Queue = queue.Queue(maxsize=1)
        self._jobs.put(("close", (), result))
        ok, value = result.get(timeout=30)
        self._closed = True
        self._thread.join(timeout=30)
        if not ok:
            raise value

    def _call(self, name: str, *args: Any) -> Any:
        if self._closed:
            raise RuntimeError("browser runtime is closed")
        self._ensure_thread()
        result: queue.Queue = queue.Queue(maxsize=1)
        self._jobs.put((name, args, result))
        ok, value = result.get(timeout=60)
        if ok:
            return value
        raise value

    def _ensure_thread(self) -> None:
        if self._thread is not None:
            return
        worker = _BrowserWorker(
            self._driver_factory,
            headless=self._headless,
            auth_takeover=self._auth_takeover,
            auth_surface_mode=self._auth_surface_mode,
            private_url_policy=self._private_url_policy,
        )
        self._thread = threading.Thread(target=worker.run, args=(self._jobs,), name="webfa-browser", daemon=True)
        self._thread.start()

    def _with_agent_result(self, result: BrowserActionResult) -> BrowserActionResult:
        result.state = self._with_agent_state(result.state)
        return result

    def _with_agent_state(self, state: BrowserState) -> BrowserState:
        state.agent = _agent_state_from_snapshot(self._agent_lease.snapshot())
        return state


def _agent_state_from_snapshot(snapshot: AgentLeaseSnapshot) -> BrowserAgentState:
    return BrowserAgentState(
        active_agent_id=snapshot.active_agent_id,
        agent_lease_expires_at=snapshot.expires_at.isoformat() if snapshot.expires_at else None,
        profile_shared=snapshot.profile_shared,
        profile_id=snapshot.profile_id,
    )


class _BrowserWorker:
    def __init__(
        self,
        driver_factory: DriverFactory,
        headless: bool,
        auth_takeover: str,
        auth_surface_mode: str,
        private_url_policy: str,
    ) -> None:
        self._session = BrowserSession(driver_factory=driver_factory)
        self._view_builder = AgentViewBuilder()
        self._headless = headless
        self._auth_takeover = auth_takeover
        self._auth_surface_mode = auth_surface_mode
        self._private_url_policy = private_url_policy
        self._auth_surface_active = False
        self._auth_surface_url: str | None = None

    def run(self, jobs: queue.Queue) -> None:
        handlers: dict[str, Callable[..., Any]] = {
            "open": self.open,
            "observe": self.observe,
            "act": self.act,
            "tabs": self.tabs,
            "switch_tab": self.switch_tab,
            "close": self.close,
            "status": self.status,
            "capture_preview": self.capture_preview,
            "restart_host": self.restart_host,
            "relaunch_visible_host": self.relaunch_visible_host,
            "open_auth_surface": self.open_auth_surface,
            "close_auth_surface": self.close_auth_surface,
        }
        while True:
            job = jobs.get()
            if job is None:
                return
            name, args, result = job
            try:
                value = handlers[name](*args)
                result.put((True, value))
                if name == "close":
                    return
            except Exception as exc:
                result.put((False, exc))

    def open(self, url: str) -> BrowserActionResult:
        self._auth_surface_active = False
        self._auth_surface_url = None
        enforce_navigation_allowed(url, policy=self._private_url_policy)  # type: ignore[arg-type]
        if self._host_is_exited():
            self._session.reset()
        driver = self._ensure_driver()
        driver.open(url)
        return BrowserActionResult(ok=True, action="open_url", state=self._state_after_navigation(driver))

    def observe(self) -> BrowserState:
        if self._auth_surface_active:
            return self._auth_surface_state()
        if self._session.driver is None:
            return BrowserState()
        self._raise_if_host_exited()
        return self._state_from_raw(self._session.driver.observe_raw())

    def act(self, request: BrowserActionRequest) -> BrowserActionResult:
        if self._auth_surface_active:
            raise auth_surface_active_error()
        self._raise_if_host_exited()
        driver = self._session.ensure_driver()
        if request.action in {"accept_dialog", "dismiss_dialog"}:
            return self._dialog_action(driver, request)
        if self._driver_has_pending_dialog(driver):
            raise dialog_required_error()
        if request.action in {"fill_form", "submit_form", "follow_link", "activate_control", "choose_option", "read_list", "inspect_block"}:
            return self._object_action(driver, request)
        if request.target:
            if request.action == "type":
                state = self._state_from_raw(driver.observe_raw())
                element = _find_element(state, request.target)
                if (element.input_type or "").lower() == "password":
                    raise auth_surface_active_error()
            self._session.registry.require(request.target)
        driver.act(request)
        if self._driver_has_pending_dialog(driver):
            raise dialog_required_error()
        return BrowserActionResult(ok=True, action=request.action, state=self._state_after_navigation(driver))

    def tabs(self) -> list[BrowserTab]:
        if self._auth_surface_active:
            return []
        if self._session.driver is None:
            return []
        self._raise_if_host_exited()
        return self._session.driver.tabs()

    def switch_tab(self, tab_id: str) -> BrowserState:
        if self._auth_surface_active:
            raise auth_surface_active_error()
        self._raise_if_host_exited()
        driver = self._ensure_driver()
        driver.switch_tab(tab_id)
        return self._state_from_raw(driver.observe_raw())

    def close(self) -> None:
        self._session.close()

    def status(self) -> dict[str, Any]:
        if self._session.driver is None:
            return {"host_status": "not_started"}
        driver = self._session.driver
        if hasattr(driver, "status"):
            status = driver.status()
            if isinstance(status, dict):
                return status
        return {"host_status": "running"}

    def capture_preview(self) -> str | None:
        if self._session.driver is None:
            return None
        self._raise_if_host_exited()
        capture = getattr(self._session.driver, "capture_screenshot", None)
        if not callable(capture):
            return None
        return capture()

    def restart_host(self) -> BrowserState:
        self._auth_surface_active = False
        self._auth_surface_url = None
        url = self._current_url_or_blank()
        self._session.reset()
        driver = self._ensure_driver()
        driver.open(url)
        return self._state_after_navigation(driver)

    def relaunch_visible_host(self) -> BrowserState:
        return self.open_auth_surface()

    def open_auth_surface(self, url: str | None = None) -> BrowserState:
        target_url = (url or "").strip() or self._current_url_or_blank()
        self._session.reset()
        self._auth_surface_active = True
        self._auth_surface_url = target_url
        return self._auth_surface_state(target_url)

    def close_auth_surface(self, url: str | None = None) -> BrowserState:
        target_url = (url or "").strip() or self._auth_surface_url or "about:blank"
        self._auth_surface_active = False
        self._auth_surface_url = None
        self._session.reset()
        if not target_url or target_url == "about:blank":
            return BrowserState()
        driver = self._ensure_driver()
        driver.open(target_url)
        return self._state_after_navigation(driver)

    def _auth_surface_state(self, url: str | None = None) -> BrowserState:
        return BrowserState(
            session_id=self._session.session_id,
            url=url or self._auth_surface_url or "about:blank",
            title="WebFA Auth Surface",
            auth=BrowserAuthState(
                surface_detected=True,
                takeover="auth_surface",
                reason=["auth_surface_requested"],
                user_action_required=True,
            ),
        )

    def _current_url_or_blank(self) -> str:
        if self._session.driver is None:
            return "about:blank"
        if self._host_is_exited():
            return "about:blank"
        try:
            raw = self._session.driver.observe_raw()
            return raw.url or "about:blank"
        except Exception:
            return "about:blank"

    def _ensure_driver(self) -> BrowserDriver:
        return self._session.ensure_driver()

    def _host_is_exited(self) -> bool:
        driver = self._session.driver
        if driver is None or not hasattr(driver, "status"):
            return False
        status = driver.status()
        return isinstance(status, dict) and status.get("host_status") == "exited"

    def _raise_if_host_exited(self) -> None:
        if self._host_is_exited():
            raise BrowserHostClosedError()

    def _state_from_raw(self, raw: RawPageSnapshot) -> BrowserState:
        self._session.registry.update(raw)
        return self._view_builder.build(raw, session_id=self._session.session_id)

    def _state_after_navigation(self, driver: BrowserDriver) -> BrowserState:
        raw = driver.observe_raw()
        try:
            enforce_navigation_allowed(raw.url, policy=self._private_url_policy)  # type: ignore[arg-type]
        except BrowserRuntimeError:
            self._session.reset()
            raise
        state = self._state_from_raw(raw)
        if self._auth_surface_mode == "electron":
            return state
        if not self._should_takeover_auth(driver, state):
            return state
        relaunch = getattr(driver, "relaunch_visible", None)
        if not callable(relaunch):
            return state
        relaunch(state.url)
        self._session.registry.clear()
        visible_state = self._state_from_raw(driver.observe_raw())
        visible_state.auth.surface_detected = True
        visible_state.auth.takeover = "visible_window"
        visible_state.auth.user_action_required = True
        if not visible_state.auth.reason:
            visible_state.auth.reason = state.auth.reason
        return visible_state

    def _should_takeover_auth(self, driver: BrowserDriver, state: BrowserState) -> bool:
        if self._auth_surface_mode == "electron":
            return False
        if self._auth_takeover != "auto":
            return False
        if not self._headless:
            return False
        if not state.auth.surface_detected:
            return False
        if not state.url.startswith(("http://", "https://")):
            return False
        status = driver.status() if hasattr(driver, "status") else {}
        if isinstance(status, dict) and status.get("visible_window"):
            return False
        return True

    def _driver_has_pending_dialog(self, driver: BrowserDriver) -> bool:
        has_pending = getattr(driver, "has_pending_dialog", None)
        if callable(has_pending):
            return bool(has_pending())
        return False

    def _dialog_action(self, driver: BrowserDriver, request: BrowserActionRequest) -> BrowserActionResult:
        if not request.target:
            raise dialog_not_found(None)
        driver.act(request)
        return BrowserActionResult(ok=True, action=request.action, state=self._state_after_navigation(driver))

    def _object_action(self, driver: BrowserDriver, request: BrowserActionRequest) -> BrowserActionResult:
        if self._driver_has_pending_dialog(driver):
            raise dialog_required_error()
        state = self._state_from_raw(driver.observe_raw())
        if request.action == "fill_form":
            form = _find_form(state, request.target)
            for key, value in (request.fields or {}).items():
                field = _find_field(form, key)
                if (field.type or "").lower() == "password":
                    raise auth_surface_active_error()
                self._session.registry.require(field.id)
                driver.act(BrowserActionRequest(action="clear", target=field.id))
                driver.act(BrowserActionRequest(action="type", target=field.id, text=value))
            return BrowserActionResult(ok=True, action=request.action, state=self._state_after_navigation(driver))
        if request.action == "submit_form":
            form = _find_form(state, request.target)
            if form.submit:
                self._session.registry.require(form.submit)
                driver.act(BrowserActionRequest(action="click", target=form.submit))
            elif form.fields:
                self._session.registry.require(form.fields[0])
                driver.act(BrowserActionRequest(action="press", target=form.fields[0], key="Enter"))
            else:
                raise ValueError("form has no submit control or fields")
            return BrowserActionResult(ok=True, action=request.action, state=self._state_after_navigation(driver))
        if request.action in {"follow_link", "activate_control"}:
            element = _find_element(state, request.target)
            expected = "link" if request.action == "follow_link" else None
            if expected and element.role != expected:
                raise ValueError("follow_link requires a link element")
            self._session.registry.require(element.id)
            driver.act(BrowserActionRequest(action="click", target=element.id))
            return BrowserActionResult(ok=True, action=request.action, state=self._state_after_navigation(driver))
        if request.action == "choose_option":
            element = _find_element(state, request.target)
            self._session.registry.require(element.id)
            driver.act(BrowserActionRequest(action="select", target=element.id, value=request.value, text=request.text))
            return BrowserActionResult(ok=True, action=request.action, state=self._state_after_navigation(driver))
        if request.action == "inspect_block":
            data = _inspect_block(state, request.target)
            return BrowserActionResult(ok=True, action=request.action, state=state, data=data)
        if request.action == "read_list":
            data = _read_list(state, request.target)
            return BrowserActionResult(ok=True, action=request.action, state=state, data=data)
        raise ValueError(f"unsupported object action: {request.action}")


def _find_form(state: BrowserState, form_id: str | None) -> BrowserForm:
    for form in state.forms:
        if form.id == form_id:
            return form
    raise stale_element_error()


def _find_field(form: BrowserForm, key: str):
    normalized = _norm(key)
    for field in form.field_details:
        candidates = {field.key, field.name, field.label, field.placeholder, field.id}
        if normalized in {_norm(candidate) for candidate in candidates if candidate}:
            return field
    raise ValueError(f"form field not found: {key}")


def _find_element(state: BrowserState, element_id: str | None) -> BrowserElement:
    for element in state.interactive_elements:
        if element.id == element_id:
            return element
    raise stale_element_error()


def _inspect_block(state: BrowserState, block_id: str | None) -> dict:
    for block in state.content_blocks:
        if block.id == block_id:
            elements = [element.model_dump() for element in state.interactive_elements if element.id in set(block.element_ids)]
            return {
                "id": block.id,
                "type": block.type,
                "text": block.text,
                "element_ids": block.element_ids,
                "elements": elements,
            }
    raise stale_element_error()


def _read_list(state: BrowserState, block_id: str | None) -> dict:
    inspected = _inspect_block(state, block_id)
    text = inspected["text"]
    lines = [part.strip() for part in text.replace(" • ", "\n").splitlines() if part.strip()]
    if len(lines) <= 1:
        lines = [part.strip() for part in text.split("  ") if part.strip()]
    return {
        **inspected,
        "items": [{"text": line} for line in lines] or [{"text": text}],
    }


def _norm(value: str) -> str:
    return " ".join(value.strip().lower().split())
