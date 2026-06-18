"""MCP → Runtime HTTP client. All MCP tools go through this client."""

from __future__ import annotations

import os
from typing import Any

import httpx


class RuntimeUnavailableError(Exception):
    """Runtime is not reachable."""
    pass


class WebFARuntimeClient:
    """HTTP client for WebFA Runtime REST API."""

    def __init__(self, base_url: str | None = None, caller: str = "mcp") -> None:
        self.base_url = base_url or os.getenv("WEBFA_RUNTIME_URL", "http://127.0.0.1:8787")
        self.caller = caller
        self._client = httpx.Client(timeout=10.0)

    def _headers(self, tool: str | None = None) -> dict[str, str]:
        h = {"X-WebFA-Caller": self.caller}
        if tool:
            h["X-WebFA-MCP-Tool"] = tool
        return h

    def _get(self, path: str, tool: str | None = None, params: dict | None = None) -> dict[str, Any]:
        try:
            resp = self._client.get(
                f"{self.base_url}{path}",
                headers=self._headers(tool),
                params=params,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError:
            raise RuntimeUnavailableError(f"Runtime unreachable at {self.base_url}")
        except httpx.HTTPStatusError as e:
            raise RuntimeErrorResponse(e.response.status_code, e.response.json())

    def _post(self, path: str, tool: str | None = None, json: dict | None = None) -> dict[str, Any]:
        try:
            resp = self._client.post(
                f"{self.base_url}{path}",
                headers=self._headers(tool),
                json=json,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError:
            raise RuntimeUnavailableError(f"Runtime unreachable at {self.base_url}")
        except httpx.HTTPStatusError as e:
            raise RuntimeErrorResponse(e.response.status_code, e.response.json())

    def health(self) -> dict[str, Any]:
        return self._get("/health", tool="health")

    def open_url(self, url: str) -> dict[str, Any]:
        return self._post("/v1/browser/open", tool="webfa.open_url", json={"url": url})

    def observe(self) -> dict[str, Any]:
        return self._get("/v1/browser/observe", tool="webfa.observe")

    def browser_act(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/v1/browser/act", tool="webfa.act", json=payload)

    def get_tabs(self) -> dict[str, Any]:
        return self._get("/v1/browser/tabs", tool="webfa.get_tabs")

    def switch_tab(self, tab_id: str) -> dict[str, Any]:
        return self._post("/v1/browser/tabs/switch", tool="webfa.switch_tab", json={"tab_id": tab_id})

    def list_providers(self) -> dict[str, Any]:
        return self._get("/v1/providers", tool="webfa.discover")

    def list_transactions(self) -> dict[str, Any]:
        return self._get("/v1/transactions", tool="webfa.discover")

    def create_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/v1/plans", tool="webfa.plan", json=payload)

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        return self._get(f"/v1/plans/{plan_id}", tool="webfa.plan")

    def preview_plan(self, plan_id: str) -> dict[str, Any]:
        return self._post(f"/v1/plans/{plan_id}/preview", tool="webfa.preview")

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/v1/executions", tool="webfa.execute", json=payload)

    def get_execution(self, execution_id: str) -> dict[str, Any]:
        return self._get(f"/v1/executions/{execution_id}", tool="webfa.get_execution")

    def get_proof(self, proof_id: str) -> dict[str, Any]:
        return self._get(f"/v1/proofs/{proof_id}", tool="webfa.get_proof")

    def list_approvals(self, status: str | None = None) -> dict[str, Any]:
        params = {"status": status} if status else None
        return self._get("/v1/approvals", tool="webfa.get_approval", params=params)

    def get_approval(self, approval_id: str) -> dict[str, Any]:
        return self._get(f"/v1/approvals/{approval_id}", tool="webfa.get_approval")


class RuntimeErrorResponse(Exception):
    """Runtime returned an error HTTP response."""

    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Runtime error {status_code}: {body}")
