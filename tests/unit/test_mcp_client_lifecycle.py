from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from apps.runtime.mcp import server as mcp_server
from apps.runtime.mcp import tools as mcp_tools


class RecordingClient:
    def __init__(self, close_calls: list[str] | None = None) -> None:
        self.close_calls = close_calls

    def close(self) -> None:
        if self.close_calls is not None:
            self.close_calls.append("close")


def test_concurrent_first_tools_share_one_runtime_client(monkeypatch) -> None:
    constructor_calls = 0
    calls_lock = threading.Lock()
    start = threading.Barrier(12)

    class SlowClient(RecordingClient):
        def __init__(self) -> None:
            nonlocal constructor_calls
            with calls_lock:
                constructor_calls += 1
            time.sleep(0.03)

    monkeypatch.setattr(mcp_tools, "_client", None)
    monkeypatch.setattr(mcp_tools, "WebFARuntimeClient", SlowClient)

    def resolve_client(_index: int):
        start.wait()
        return mcp_tools.get_client()

    with ThreadPoolExecutor(max_workers=12) as executor:
        clients = list(executor.map(resolve_client, range(12)))

    assert constructor_calls == 1
    assert len({id(client) for client in clients}) == 1


@pytest.mark.parametrize("server_failure", [None, RuntimeError("stdio failed")])
def test_mcp_main_always_closes_runtime_client(monkeypatch, server_failure) -> None:
    close_calls: list[str] = []
    client = RecordingClient(close_calls)
    monkeypatch.setattr(mcp_tools, "_client", client)

    def run(*, transport: str) -> None:
        assert transport == "stdio"
        if server_failure is not None:
            raise server_failure

    monkeypatch.setattr(mcp_server.mcp, "run", run)

    if server_failure is None:
        mcp_server.main()
    else:
        with pytest.raises(RuntimeError, match="stdio failed"):
            mcp_server.main()

    assert close_calls == ["close"]
    assert mcp_tools._client is None
