from __future__ import annotations

from browser.driver import RawPageSnapshot
from browser.runtime import BrowserRuntime
from schemas.browser import BrowserActionRequest, BrowserTab, BrowserViewport


class FakeAuthDriver:
    def __init__(self) -> None:
        self.url = ""
        self.visible = False
        self.relaunches: list[str] = []

    def open(self, url: str) -> None:
        self.url = url

    def observe_raw(self) -> RawPageSnapshot:
        return RawPageSnapshot(
            url=self.url,
            title="Sign in",
            loading=False,
            focused_element_id=None,
            viewport=BrowserViewport(width=1280, height=720),
            tabs=[BrowserTab(id="tab_1", url=self.url, title="Sign in", active=True)],
            visible_text="Sign in Password Verification code",
            forms=[
                {
                    "id": "form_1",
                    "fields": ["el_1"],
                    "field_details": [{"id": "el_1", "key": "password", "type": "password", "value": "secret"}],
                    "submit": None,
                }
            ],
            interactive_elements=[
                {
                    "id": "el_1",
                    "role": "textbox",
                    "tag": "input",
                    "name": "Password",
                    "value": "secret",
                    "input_type": "password",
                    "visible": True,
                    "enabled": True,
                    "actions": ["type"],
                }
            ],
        )

    def act(self, request: BrowserActionRequest) -> None:
        pass

    def tabs(self) -> list[BrowserTab]:
        return []

    def switch_tab(self, tab_id: str) -> None:
        pass

    def close(self) -> None:
        pass

    def status(self) -> dict:
        return {"host_status": "running", "visible_window": self.visible, "headless": not self.visible}

    def relaunch_visible(self, url: str) -> None:
        self.visible = True
        self.url = url
        self.relaunches.append(url)


class FakeDelayedAuthDriver(FakeAuthDriver):
    def __init__(self) -> None:
        super().__init__()
        self.auth_visible = False

    def observe_raw(self) -> RawPageSnapshot:
        if self.auth_visible:
            return super().observe_raw()
        return RawPageSnapshot(
            url=self.url,
            title="Home",
            loading=False,
            focused_element_id=None,
            viewport=BrowserViewport(width=1280, height=720),
            tabs=[BrowserTab(id="tab_1", url=self.url, title="Home", active=True)],
            visible_text="Welcome",
            interactive_elements=[
                {
                    "id": "el_1",
                    "role": "button",
                    "tag": "button",
                    "name": "Sign in",
                    "visible": True,
                    "enabled": True,
                    "actions": ["click"],
                }
            ],
        )

    def act(self, request: BrowserActionRequest) -> None:
        self.auth_visible = True


def test_auth_takeover_relaunches_visible_window(monkeypatch):
    monkeypatch.setenv("WEBFA_AUTH_TAKEOVER", "auto")
    driver = FakeAuthDriver()
    runtime = BrowserRuntime(headless=True, driver_factory=lambda: driver)

    result = runtime.open("https://example.com/login")

    assert driver.relaunches == ["https://example.com/login"]
    assert result.state.auth.surface_detected is True
    assert result.state.auth.takeover == "visible_window"
    assert result.state.auth.user_action_required is True
    assert result.state.interactive_elements[0].value == ""


def test_auth_takeover_after_action_relaunches_visible_window(monkeypatch):
    monkeypatch.setenv("WEBFA_AUTH_TAKEOVER", "auto")
    driver = FakeDelayedAuthDriver()
    runtime = BrowserRuntime(headless=True, driver_factory=lambda: driver)

    opened = runtime.open("https://example.com")
    assert opened.state.auth.surface_detected is False

    result = runtime.act(BrowserActionRequest(action="click", target="el_1"))

    assert driver.relaunches == ["https://example.com"]
    assert result.state.auth.takeover == "visible_window"


def test_auth_takeover_off_does_not_relaunch(monkeypatch):
    monkeypatch.setenv("WEBFA_AUTH_TAKEOVER", "off")
    driver = FakeAuthDriver()
    runtime = BrowserRuntime(headless=True, driver_factory=lambda: driver)

    result = runtime.open("https://example.com/login")

    assert driver.relaunches == []
    assert result.state.auth.surface_detected is True
    assert result.state.auth.takeover == "none"


def test_auth_takeover_does_not_relaunch_in_visible_mode(monkeypatch):
    monkeypatch.setenv("WEBFA_AUTH_TAKEOVER", "auto")
    driver = FakeAuthDriver()
    driver.visible = True
    runtime = BrowserRuntime(headless=False, driver_factory=lambda: driver)

    result = runtime.open("https://example.com/login")

    assert driver.relaunches == []
    assert result.state.auth.surface_detected is True
    assert result.state.auth.user_action_required is True
    assert result.state.auth.takeover == "none"


def test_runtime_rejects_agent_typing_password_field(monkeypatch):
    monkeypatch.setenv("WEBFA_AUTH_TAKEOVER", "off")
    driver = FakeAuthDriver()
    runtime = BrowserRuntime(headless=True, driver_factory=lambda: driver)
    runtime.open("https://example.com/login")

    try:
        runtime.act(BrowserActionRequest(action="type", target="el_1", text="secret"))
    except ValueError as exc:
        assert "password fields require user auth takeover" in str(exc)
    else:
        raise AssertionError("agent typing password field must be rejected")


def test_runtime_rejects_fill_form_password_field(monkeypatch):
    monkeypatch.setenv("WEBFA_AUTH_TAKEOVER", "off")
    driver = FakeAuthDriver()
    runtime = BrowserRuntime(headless=True, driver_factory=lambda: driver)
    runtime.open("https://example.com/login")

    try:
        runtime.act(BrowserActionRequest(action="fill_form", target="form_1", fields={"password": "secret"}))
    except ValueError as exc:
        assert "password fields require user auth takeover" in str(exc)
    else:
        raise AssertionError("fill_form password field must be rejected")
