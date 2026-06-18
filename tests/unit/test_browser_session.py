from browser.session import BrowserSession


class FakeDriver:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_browser_session_defaults_and_close():
    created: list[FakeDriver] = []

    def factory() -> FakeDriver:
        driver = FakeDriver()
        created.append(driver)
        return driver

    session = BrowserSession(driver_factory=factory)

    assert session.session_id == "default"
    assert session.profile_id == "default"
    assert session.ensure_driver() is session.ensure_driver()

    session.registry.update(type("Raw", (), {"url": "https://example.com", "interactive_elements": [{"id": "el_1"}]})())
    session.close()

    assert created[0].closed is True
    assert session.driver is None
