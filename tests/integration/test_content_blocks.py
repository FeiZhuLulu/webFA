"""Integration test for P5.5 Content Blocks MVP.

Verifies that `observe` returns structured content_blocks for a search
results page, that each result's title and description do not bleed into
another block, that each block's element_ids point at the interactive
elements inside it, and that the legacy visible_text still works.

Requires Playwright; skipped when Playwright is not installed (mirrors
test_browser_api.py).
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from storage.db import reset_engine_for_tests

FIXTURE_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "search_results_page.html"

EXPECTED_RESULTS = [
    ("alpha/webfa-one", "First repository description"),
    ("beta/webfa-two", "Second repository description"),
    ("gamma/webfa-three", "Third repository description"),
]


def test_content_blocks_structured_for_search_results(monkeypatch, tmp_path: Path):
    pytest.importorskip("playwright.sync_api")
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        opened = client.post("/v1/browser/open", json={"url": FIXTURE_PAGE.as_uri()})
        assert opened.status_code == 200, opened.text
        state = opened.json()["state"]

        blocks = state["content_blocks"]
        # observe returns at least one block per result (title + description).
        # We ask for at least 3 blocks total since results drive most of them.
        assert len(blocks) >= 3, f"expected >= 3 content blocks, got {len(blocks)}"

        # Every block conforms to the typed schema.
        for block in blocks:
            assert set(block.keys()) == {"id", "type", "text", "element_ids"}
            assert block["id"].startswith("block_")
            assert block["type"] in {"heading", "paragraph", "list_item", "form", "nav", "generic"}
            assert isinstance(block["element_ids"], list)

        block_texts = [block["text"] for block in blocks]

        # Each result's title and description appear and do not bleed together.
        for title, description in EXPECTED_RESULTS:
            assert any(title in text for text in block_texts), f"title {title!r} missing from blocks"
            assert any(description in text for text in block_texts), (
                f"description {description!r} missing from blocks"
            )

        # No single block should contain text from two different results' descriptions
        # joined together (would mean result boundaries collapsed).
        for block in blocks:
            hits = sum(1 for _, description in EXPECTED_RESULTS if description in block["text"])
            assert hits <= 1, f"block {block['id']} merged multiple result descriptions: {block['text']!r}"

        # Each result's title link is referenced by the element_ids of the block
        # that contains that title text.
        interactive_by_text = {el["text"]: el["id"] for el in state["interactive_elements"]}
        for title, _ in EXPECTED_RESULTS:
            link_id = interactive_by_text[title]
            owning = [b for b in blocks if title in b["text"]]
            assert owning, f"no block owns title {title!r}"
            assert any(link_id in b["element_ids"] for b in owning), (
                f"title {title!r} link id {link_id} not bound to its block"
            )

        # Legacy visible_text is untouched for older agents.
        assert state["visible_text"]
        for title, _ in EXPECTED_RESULTS:
            assert title in state["visible_text"]


def test_content_blocks_never_carry_html_or_storage(monkeypatch, tmp_path: Path):
    pytest.importorskip("playwright.sync_api")
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_BROWSER_HEADLESS", "1")
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        opened = client.post("/v1/browser/open", json={"url": FIXTURE_PAGE.as_uri()})
        assert opened.status_code == 200, opened.text
        state = opened.json()["state"]

    serialized = str(state["content_blocks"]).lower()
    for forbidden in ("html", "outerhtml", "innerhtml", "cookies", "localstorage", "sessionstorage"):
        assert forbidden not in serialized, f"content_blocks leaked {forbidden!r}"
