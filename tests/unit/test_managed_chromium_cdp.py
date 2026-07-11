import base64
import json
import threading
import time

from browser.exceptions import BrowserHostClosedError
from browser.managed_chromium_host import ManagedChromiumHost
from browser.managed_chromium_host import _CDPClient
from browser.visual_surface import VisualStreamConfig


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


def test_managed_chromium_screencast_acknowledges_every_frame(monkeypatch):
    clients = []

    class FakeScreencastClient:
        def __init__(self, websocket_url, *, event_handler=None, should_abort=None):
            self.event_handler = event_handler
            self.calls = []
            self.sent = []
            self.emitted = False
            clients.append(self)

        def call(self, method, params=None):
            self.calls.append((method, params or {}))
            return {}

        def send(self, method, params=None):
            self.sent.append((method, params or {}))
            return len(self.sent)

        def pump_events(self, timeout):
            if not self.emitted:
                self.emitted = True
                self.event_handler(
                    "Page.screencastFrame",
                    {
                        "data": base64.b64encode(b"jpeg-frame").decode(),
                        "metadata": {
                            "deviceWidth": 640,
                            "deviceHeight": 360,
                            "pageScaleFactor": 1,
                            "scrollOffsetX": 0,
                            "scrollOffsetY": 12,
                        },
                        "sessionId": 17,
                    },
                )
            time.sleep(min(timeout, 0.01))
            return True

        def close(self):
            return None

    monkeypatch.setattr(
        "browser.managed_chromium_host._CDPClient",
        FakeScreencastClient,
    )
    host = ManagedChromiumHost()
    monkeypatch.setattr(host, "_ensure_page_client", lambda: object())
    monkeypatch.setattr(
        host,
        "_current_page_target",
        lambda: {"id": "page-target-1", "webSocketDebuggerUrl": "ws://page"},
    )
    delivered = []
    ready = threading.Event()

    stream_id = host.start_screencast(
        VisualStreamConfig(),
        lambda frame: (delivered.append(frame), ready.set()),
    )
    assert ready.wait(timeout=2)
    state = host.stop_screencast(stream_id)

    assert delivered[0].data == b"jpeg-frame"
    assert delivered[0].host_target_id == "page-target-1"
    assert delivered[0].scroll_offset_y == 12
    assert ("Page.screencastFrameAck", {"sessionId": 17}) in clients[0].sent
    assert any(method == "Page.startScreencast" for method, _ in clients[0].calls)
    assert any(method == "Page.stopScreencast" for method, _ in clients[0].calls)
    assert state.frames_received == 1


def test_http_json_raises_browser_host_closed_when_not_running():
    host = ManagedChromiumHost()

    try:
        host._http_json("/json/list")
    except BrowserHostClosedError:
        return
    raise AssertionError("expected BrowserHostClosedError")
