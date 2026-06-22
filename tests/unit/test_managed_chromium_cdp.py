import json

from browser.managed_chromium_host import _CDPClient


class FakeWebSocket:
    def __init__(self, fail_recv: bool) -> None:
        self.fail_recv = fail_recv
        self.last_id = None
        self.closed = False

    def send(self, raw: str) -> None:
        self.last_id = json.loads(raw)["id"]

    def recv(self, timeout: float):
        if self.fail_recv:
            raise RuntimeError("keepalive ping timeout")
        return json.dumps({"id": self.last_id, "result": {"ok": True}})

    def close(self) -> None:
        self.closed = True


def test_cdp_client_reconnects_once_after_receive_failure(monkeypatch):
    sockets = [FakeWebSocket(fail_recv=True), FakeWebSocket(fail_recv=False)]

    def fake_connect(url: str, open_timeout: int, ping_interval):
        assert url == "ws://example/devtools/page/1"
        return sockets.pop(0)

    monkeypatch.setattr("websockets.sync.client.connect", fake_connect)

    client = _CDPClient("ws://example/devtools/page/1")
    result = client.call("Runtime.evaluate", {"expression": "1 + 1"})

    assert result == {"ok": True}
