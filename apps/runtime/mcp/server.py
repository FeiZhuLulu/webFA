"""WebFA MCP stdio server.

Run: python -m apps.runtime.mcp.server
Env: WEBFA_RUNTIME_URL=http://127.0.0.1:8787
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[3]
for candidate in [APP_ROOT, APP_ROOT / "packages", APP_ROOT / "packages" / "webfa-core"]:
    value = str(candidate)
    if value not in sys.path:
        sys.path.insert(0, value)

from mcp.server.fastmcp import FastMCP

from schemas.safety import SafetyOperationEnvelope
from schemas.web import ObserveDetail, ObserveMode, SemanticOperationName

from apps.runtime.mcp.tools import (
    tool_act,
    tool_discover,
    tool_execute,
    tool_get_execution,
    tool_get_proof,
    tool_get_tabs,
    tool_observe,
    tool_open_url,
    tool_plan,
    tool_preview,
    tool_switch_tab,
)

mcp = FastMCP(
    "WebFA",
    instructions=(
        "WebFA is an agent-native browser runtime. "
        "Use webfa.open_url, webfa.observe, and webfa.act to operate real websites "
        "through WebState, stable WebObjects, declared capabilities, and semantic operations. "
        "Do not use browser primitives, selectors, coordinates, raw DOM, Playwright, or CDP. "
        "Read AGENT_MANUAL.md before validation; prefer URL-first navigation when page state is encoded in URLs."
    ),
)


@mcp.tool(name="webfa.open_url")
def webfa_open_url(url: str, safety: SafetyOperationEnvelope | None = None) -> str:
    """Open a URL, prefer constructed URLs for known state, and optionally establish a task-scoped SafetyContext."""
    return json.dumps(
        tool_open_url(
            url=url,
            safety=safety.model_dump(mode="json") if safety is not None else None,
        ),
        ensure_ascii=False,
    )


@mcp.tool(name="webfa.observe")
def webfa_observe(
    mode: ObserveMode = "page",
    target: str | None = None,
    query: dict[str, Any] | None = None,
    range: dict[str, int] | None = None,
    since_revision: int | None = None,
    detail: ObserveDetail = "standard",
    limit: int = 50,
) -> str:
    """Read WebState in page, object, query, or changes mode."""
    return json.dumps(
        tool_observe(
            mode=mode,
            target=target,
            query=query,
            range=range,
            since_revision=since_revision,
            detail=detail,
            limit=limit,
        ),
        ensure_ascii=False,
    )


@mcp.tool(name="webfa.act")
def webfa_act(
    operation: SemanticOperationName,
    target: str,
    arguments: dict[str, Any] | None = None,
    expected_object_version: int | None = None,
    expected_document_revision: int | None = None,
    safety: SafetyOperationEnvelope | None = None,
) -> str:
    """Execute a semantic operation, optionally using a task-scoped SafetyContext."""
    return json.dumps(
        tool_act(
            operation=operation,
            target=target,
            arguments=arguments,
            expected_object_version=expected_object_version,
            expected_document_revision=expected_document_revision,
            safety=safety.model_dump(mode="json") if safety is not None else None,
        ),
        ensure_ascii=False,
    )


@mcp.tool(name="webfa.get_tabs")
def webfa_get_tabs() -> str:
    """List current browser tabs."""
    return json.dumps(tool_get_tabs(), ensure_ascii=False)


@mcp.tool(name="webfa.switch_tab")
def webfa_switch_tab(tab_id: str) -> str:
    """Switch active browser tab by tab id."""
    return json.dumps(tool_switch_tab(tab_id=tab_id), ensure_ascii=False)


if os.getenv("WEBFA_ENABLE_LEGACY_TRANSACTION") == "1":

    @mcp.tool(name="webfa.discover")
    def webfa_discover(intent: str | None = None, provider: str | None = None) -> str:
        """Legacy: discover providers and transactions."""
        return json.dumps(tool_discover(intent=intent, provider=provider), ensure_ascii=False)

    @mcp.tool(name="webfa.plan")
    def webfa_plan(transaction_id: str, input: dict[str, Any]) -> str:
        """Legacy: create a transaction plan."""
        return json.dumps(tool_plan(transaction_id=transaction_id, input=input), ensure_ascii=False)

    @mcp.tool(name="webfa.preview")
    def webfa_preview(plan_id: str) -> str:
        """Legacy: preview a transaction plan."""
        return json.dumps(tool_preview(plan_id=plan_id), ensure_ascii=False)

    @mcp.tool(name="webfa.execute")
    def webfa_execute(plan_id: str, approval_token: str, idempotency_key: str | None = None) -> str:
        """Legacy: execute an approved transaction plan."""
        return json.dumps(
            tool_execute(plan_id=plan_id, approval_token=approval_token, idempotency_key=idempotency_key),
            ensure_ascii=False,
        )

    @mcp.tool(name="webfa.get_execution")
    def webfa_get_execution(execution_id: str) -> str:
        """Legacy: get transaction execution status."""
        return json.dumps(tool_get_execution(execution_id=execution_id), ensure_ascii=False)

    @mcp.tool(name="webfa.get_proof")
    def webfa_get_proof(proof_id: str) -> str:
        """Legacy: get transaction proof."""
        return json.dumps(tool_get_proof(proof_id=proof_id), ensure_ascii=False)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
