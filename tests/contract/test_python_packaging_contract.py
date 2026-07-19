from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[2]


def test_python_distribution_declares_versioned_runtime_resources():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"webfa_resources"' in pyproject
    assert '"webfa_resources" = "resources"' in pyproject
    assert '[tool.setuptools.package-data]' in pyproject
    assert '"webfa_resources.transactions" = ["*.yaml"]' in pyproject
    assert (ROOT / "resources" / "__init__.py").is_file()
    assert (ROOT / "resources" / "transactions" / "__init__.py").is_file()


def test_runtime_uses_the_shared_resource_resolver():
    runtime_main = (ROOT / "apps" / "runtime" / "main.py").read_text(encoding="utf-8")

    assert "default_resources_root()" in runtime_main
    assert 'Path(__file__).resolve().parents[2] / "resources"' not in runtime_main


def test_distribution_metadata_positions_webfa_as_external_agent_runtime():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]

    assert "internet Runtime for external Agents" in project["description"]
    assert project["urls"]["Repository"] == "https://github.com/FeiZhuLulu/webFA.git"
    assert project["scripts"] == {
        "webfa": "apps.runtime.cli:main_webfa",
        "webfa-runtime": "apps.runtime.cli:main_runtime",
        "webfa-mcp": "apps.runtime.cli:main_mcp",
    }


def test_external_agent_configs_do_not_take_over_runtime_host_policy():
    expected_ids = {
        "codex.md": "codex",
        "claude-code.md": "claude-code",
        "kimi-code.md": "kimi-code",
        "opencode.md": "opencode",
    }
    for filename, agent_id in expected_ids.items():
        guide = (ROOT / "docs" / "agent-integrations" / filename).read_text(encoding="utf-8")
        assert f'"WEBFA_AGENT_ID": "{agent_id}"' in guide
        assert "profile_ref" in guide
        assert "session_busy" in guide
        assert "WEBFA_BROWSER_DRIVER" not in guide
        assert "WEBFA_AUTH_TAKEOVER" not in guide


def test_source_install_does_not_require_optional_desktop_dependencies():
    for filename, desktop_marker in (
        ("README.md", "如需开发可选的人类控制面"),
        ("README.en.md", "To develop the optional human control surface"),
    ):
        readme = (ROOT / filename).read_text(encoding="utf-8")
        source_install = readme.split(desktop_marker, 1)[0]
        assert 'pip install -e ".[dev]"' in source_install
        assert "npm install" not in source_install


def test_doctor_uses_the_public_web_object_surface():
    cli = (ROOT / "apps" / "runtime" / "cli.py").read_text(encoding="utf-8")

    assert 'client.open_url(page.as_uri())' in cli
    assert '"operation": "set_value"' in cli
    assert '"operation": "submit"' in cli
    assert 'f"{runtime_url}/v1/browser/open"' not in cli
