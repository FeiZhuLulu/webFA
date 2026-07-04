import pytest
from pydantic import ValidationError

from schemas.browser import BrowserActionRequest, BrowserDialog, BrowserState


def test_browser_dialog_schema():
    dialog = BrowserDialog(
        id="dialog_1",
        type="confirm",
        message="Proceed?",
        default_value="",
        user_action_required=True,
    )
    assert dialog.type == "confirm"


def test_accept_dialog_requires_target():
    with pytest.raises(ValidationError):
        BrowserActionRequest(action="accept_dialog")


def test_browser_state_includes_dialogs_and_frames():
    state = BrowserState(
        dialogs=[BrowserDialog(id="dialog_1", type="alert", message="hi")],
        frames=[],
    )
    assert state.dialogs[0].id == "dialog_1"