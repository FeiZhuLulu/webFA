import pytest

from browser.runtime_errors import BrowserRuntimeError
from browser.url_policy import classify_url, enforce_navigation_allowed, evaluate_url_security


def test_classify_public_url():
    result = classify_url("https://example.com/path")
    assert result.url_class == "public"
    assert result.hard_block is False


def test_about_blank_is_allowed():
    security = evaluate_url_security("about:blank")
    assert security.url_class == "public"
    assert security.policy == "allow"


def test_classify_localhost():
    result = classify_url("http://127.0.0.1:8787/health")
    assert result.url_class == "local"


def test_classify_private_ip():
    result = classify_url("http://192.168.1.10/dashboard")
    assert result.url_class == "private"


def test_classify_file_url():
    result = classify_url("file:///tmp/fixture.html")
    assert result.url_class == "file"


def test_metadata_ip_is_hard_block():
    result = classify_url("http://169.254.169.254/latest/meta-data/")
    assert result.url_class == "blocked"
    assert result.hard_block is True


def test_sensitive_query_adds_risk_flag():
    security = evaluate_url_security("https://example.com/callback?access_token=secret")
    assert security.policy == "warn"
    assert any(flag.startswith("sensitive_query:") for flag in security.risk_flags)


def test_default_warn_allows_localhost():
    security = evaluate_url_security("http://localhost:8787/")
    assert security.policy == "warn"
    assert security.url_class == "local"


def test_block_policy_blocks_private_ip():
    security = evaluate_url_security("http://10.0.0.5/", policy="block")
    assert security.policy == "block"


def test_enforce_navigation_blocks_metadata_even_when_allow():
    with pytest.raises(BrowserRuntimeError) as excinfo:
        enforce_navigation_allowed("http://169.254.169.254/latest/meta-data/", policy="allow")
    assert excinfo.value.code == "navigation_blocked"


def test_enforce_navigation_blocks_localhost_when_block_policy():
    with pytest.raises(BrowserRuntimeError) as excinfo:
        enforce_navigation_allowed("http://127.0.0.1:8787/", policy="block")
    assert excinfo.value.code == "private_url_blocked"