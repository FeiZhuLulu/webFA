from pathlib import Path

from browser.managed_chromium_host import _chromium_install_candidates


def test_windows_chromium_candidates_follow_environment_roots() -> None:
    candidates = _chromium_install_candidates(
        platform_name="nt",
        environment={
            "PROGRAMFILES": r"D:\Programs",
            "PROGRAMFILES(X86)": r"D:\Programs32",
            "PROGRAMW6432": r"D:\Programs",
            "LOCALAPPDATA": r"E:\UserApps",
        },
    )

    assert candidates == [
        Path(r"D:\Programs") / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(r"D:\Programs") / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(r"D:\Programs32") / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(r"D:\Programs32") / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(r"E:\UserApps") / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(r"E:\UserApps") / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]


def test_non_windows_chromium_candidates_do_not_assume_windows_paths() -> None:
    assert _chromium_install_candidates(
        platform_name="posix",
        environment={"PROGRAMFILES": r"C:\Program Files"},
    ) == []
