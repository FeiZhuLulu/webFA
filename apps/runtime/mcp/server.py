"""WebFA MCP stdio server.

Run: python -m apps.runtime.mcp.server
Env: WEBFA_RUNTIME_URL=http://127.0.0.1:8787
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path
APP_ROOT = Path(__file__).resolve().parents[3]
for candidate in [APP_ROOT, APP_ROOT / "packages", APP_ROOT / "packages" / "webfa-core"]:
    value = str(candidate)
    if value not in sys.path:
        sys.path.insert(0, value)

from mcp.server.fastmcp import FastMCP

from apps.runtime.mcp.tools import (
    tool_discover,
    tool_execute,
    tool_get_execution,
    tool_get_proof,
    tool_plan,
    tool_preview,
)

mcp = FastMCP(
    "WebFA",
    instructions=(
        "WebFA is a local Agent Action Transaction Gateway. "
        "Use webfa.discover to find available transactions, "
        "webfa.plan to create a plan, "
        "webfa.preview to generate a diff and approval, "
        "then ask the user to approve in the WebFA Console, "
        "and webfa.execute with the approval token to run the transaction."
    ),
)


@mcp.tool()
def webfa_discover(intent: str | None = None, provider: str | None = None) -> str:
    """Discover available providers and transactions.

    Args:
        intent: Optional description of what you want to do (e.g. "fix github issue and open pr").
        provider: Optional provider filter (e.g. "mock", "github").
    """
    result = tool_discover(intent=intent, provider=provider)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def webfa_plan(transaction_id: str, input: dict[str, Any]) -> str:
    """Create a transaction plan.

    Args:
        transaction_id: The transaction to plan (e.g. "mock.patch_and_open_pr").
        input: Transaction input parameters (e.g. owner, repo, issue_number, task_description).
    """
    result = tool_plan(transaction_id=transaction_id, input=input)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def webfa_preview(plan_id: str) -> str:
    """Preview a plan: generate diff, run policy check, create approval.

    After preview, the user must approve in the WebFA Console at the returned approval_url.

    Args:
        plan_id: The plan to preview.
    """
    result = tool_preview(plan_id=plan_id)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def webfa_execute(plan_id: str, approval_token: str, idempotency_key: str | None = None) -> str:
    """Execute an approved plan.

    Requires a valid approval_token from a user-approved approval.
    The user must approve in the WebFA Console first.

    Args:
        plan_id: The plan to execute.
        approval_token: The approval token from the user's approval.
        idempotency_key: Optional key to prevent duplicate execution.
    """
    result = tool_execute(plan_id=plan_id, approval_token=approval_token, idempotency_key=idempotency_key)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def webfa_get_execution(execution_id: str) -> str:
    """Get execution status and details.

    Args:
        execution_id: The execution to query.
    """
    result = tool_get_execution(execution_id=execution_id)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def webfa_get_proof(proof_id: str) -> str:
    """Get proof bundle for a completed execution.

    Args:
        proof_id: The proof to query.
    """
    result = tool_get_proof(proof_id=proof_id)
    return json.dumps(result, ensure_ascii=False)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
