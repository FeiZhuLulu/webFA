from browser.action_log import ActionLog, redact_action_message


def test_action_log_keeps_recent_entries_in_order():
    log = ActionLog(max_entries=3)
    log.record(tool="webfa.open_url", message="https://example.com")
    log.record(tool="webfa.observe")
    log.record(tool="webfa.act", status="error", code="stale_element", message="stale")

    recent = log.recent()
    assert len(recent) == 3
    assert recent[0]["tool"] == "webfa.open_url"
    assert recent[-1]["code"] == "stale_element"


def test_action_log_ring_buffer_drops_oldest():
    log = ActionLog(max_entries=2)
    log.record(tool="first")
    log.record(tool="second")
    log.record(tool="third")

    recent = log.recent()
    assert [entry["tool"] for entry in recent] == ["second", "third"]


def test_action_log_redacts_sensitive_url_query_values():
    message = redact_action_message("https://example.com/callback?code=abc123&state=ok&access_token=secret")

    assert "abc123" not in message
    assert "secret" not in message
    assert "code=[REDACTED]" in message
    assert "access_token=[REDACTED]" in message
    assert "state=ok" in message


def test_action_log_redacts_sensitive_plain_message_values():
    log = ActionLog()
    log.record(tool="webfa.open_url", message="token=abc password:secret")

    recent = log.recent()
    assert recent[0]["message"] == "token=[REDACTED] password:[REDACTED]"
