from browser.runtime_errors import (
    BrowserRuntimeError,
    auth_surface_active,
    browser_host_closed,
    dialog_required,
    from_value_error,
    navigation_blocked,
    private_url_blocked,
    stale_element,
)


def test_runtime_error_detail_shape():
    exc = stale_element()
    assert exc.to_detail() == {
        "code": "stale_element",
        "message": "Element id is stale; call observe again",
        "recover_hint": "Call webfa.observe to refresh element ids before acting",
    }


def test_from_value_error_maps_stale_element():
    mapped = from_value_error(ValueError("element id is stale; call observe again"))
    assert mapped is not None
    assert mapped.code == "stale_element"


def test_from_value_error_maps_auth_surface():
    mapped = from_value_error(ValueError("auth surface is active; complete WebFA auth takeover before agent actions"))
    assert mapped is not None
    assert mapped.code == "auth_surface_active"


def test_error_codes_have_recover_hint():
    for factory in (private_url_blocked, navigation_blocked, browser_host_closed, dialog_required, auth_surface_active):
        if factory is private_url_blocked:
            exc = factory("http://127.0.0.1/", policy="block")
        elif factory is navigation_blocked:
            exc = factory("http://169.254.169.254/")
        else:
            exc = factory()
        assert isinstance(exc, BrowserRuntimeError)
        assert exc.recover_hint