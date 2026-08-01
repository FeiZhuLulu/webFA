from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_renderer_desktop_types_do_not_expose_retired_mcp_ipc():
    declarations = (ROOT / "apps/desktop/renderer/src/types/webfa-desktop.d.ts").read_text(encoding="utf-8")

    assert "getRuntimeStatus:" in declarations
    assert "onRuntimeStatus:" in declarations
    for retired in (
        "export type McpState",
        "interface McpStatus",
        "getMcpStatus:",
        "startMcp:",
        "stopMcp:",
        "restartMcp:",
        "onMcpStatus:",
    ):
        assert retired not in declarations


def test_control_center_mcp_panel_is_runtime_read_only_and_client_owned():
    api = (ROOT / "apps/desktop/renderer/src/lib/visualizer-api.ts").read_text(encoding="utf-8")
    panel = (ROOT / "apps/desktop/renderer/src/components/Runtime/McpStatusPanel.tsx").read_text(encoding="utf-8")
    page = (ROOT / "apps/desktop/renderer/src/app/page.tsx").read_text(encoding="utf-8")

    status_reader = api.split("export async function fetchMcpRuntimeStatus", 1)[1].split(
        "export async function fetchMcpClientConfig", 1
    )[0]
    config_reader = api.split("export async function fetchMcpClientConfig", 1)[1].split(
        "async function readApiError", 1
    )[0]

    assert "/v1/mcp/status" in status_reader
    assert "/v1/mcp/config" in config_reader
    assert "controlHeaders" not in status_reader
    assert "controlHeaders" not in config_reader
    assert "method:" not in status_reader
    assert "method:" not in config_reader

    assert "fetchMcpRuntimeStatus" in panel
    assert "fetchMcpClientConfig" in panel
    assert "navigator.clipboard.writeText(JSON.stringify(config, null, 2))" in panel
    assert "由外部 Agent 的 MCP 客户端启动 stdio bridge；WebFA Desktop 不运行或替代 Agent。" in panel
    assert "window.webfaDesktop" not in panel
    for forbidden in ("startMcp", "stopMcp", "restartMcp", "getMcpStatus"):
        assert forbidden not in panel

    assert "<McpStatusPanel" in page
    assert "activeAgentId={visualizerState?.agent.active_agent_id ?? null}" in page
    assert "leaseExpiresAt={visualizerState?.agent.lease_expires_at ?? null}" in page


def test_desktop_copy_presents_external_agents_as_runtime_clients():
    page = (ROOT / "apps/desktop/renderer/src/app/page.tsx").read_text(encoding="utf-8")
    shell = (ROOT / "apps/desktop/renderer/src/components/Layout/VisualizerShell.tsx").read_text(encoding="utf-8")
    monitor = (ROOT / "apps/desktop/renderer/src/app/monitor/page.tsx").read_text(encoding="utf-8")
    status = (ROOT / "apps/desktop/renderer/src/components/Runtime/StatusPanel.tsx").read_text(encoding="utf-8")

    assert "Runtime manager" in page
    assert "外部 Agent 接入" in page
    assert "Runtime 投影" in page
    assert "Runtime 投影" in shell
    assert "外部 Agent 控制" in monitor
    assert "External Agent" in status

    combined = "\n".join((page, shell, monitor, status))
    for ambiguous in ("Agent View", "Agent 视图", '"Agent 控制"', "Active Agent"):
        assert ambiguous not in combined


def test_safety_center_has_visible_grouped_form_labels_and_semantic_sections():
    panel = (ROOT / "apps/desktop/renderer/src/components/Runtime/SafetyCenterPanel.tsx").read_text(
        encoding="utf-8"
    )
    styles = (ROOT / "apps/desktop/renderer/src/app/globals.css").read_text(encoding="utf-8")

    assert '<section className="viz-management-section" aria-labelledby={id}>' in panel
    assert '<h3 id={id} className="viz-management-heading">' in panel
    assert '<label className={`viz-management-field' in panel
    for label in (
        "Profile 所有者",
        "信任模式",
        "未知外部效果",
        "允许的 Origins",
        "策略 ID",
        "最低保证级别",
        "引用 ID",
        "安全显示名称",
    ):
        assert f'<Field label="{label}">' in panel
    assert "style={{" not in panel
    assert "等待外部 Agent 重试" in panel
    assert ".viz-management-section" in styles
    assert ".viz-management-field > span" in styles
    assert ".viz-limit-grid" in styles
    assert 'data-ui="profile-policy-effect"' in panel
    assert "保存后立即作用于当前 Profile" in panel
    assert "身份存储维护仍要求先关闭 Session" in panel
    assert "bound_agent_ids: profile.bound_agent_ids" in panel
    assert "safety_policy_id: profile.safety_policy_id" in panel
    assert "bound_agent_ids: activeAgentId ? [activeAgentId] : []" not in panel.split(
        "async function addPolicy", 1
    )[0]


def test_empty_runtime_surfaces_are_centered_and_semantically_named():
    action_log = (
        ROOT / "apps/desktop/renderer/src/components/Inspector/ActionLogger.tsx"
    ).read_text(encoding="utf-8")
    monitor = (ROOT / "apps/desktop/renderer/src/app/monitor/page.tsx").read_text(
        encoding="utf-8"
    )
    monitor_styles = (
        ROOT / "apps/desktop/renderer/src/app/monitor/monitor.module.css"
    ).read_text(encoding="utf-8")
    audit = (ROOT / "scripts/audit-source-ui.cjs").read_text(encoding="utf-8")

    assert 'role="log"' in action_log
    assert 'aria-label="Agent Action Log"' in action_log
    assert 'data-ui="action-log-empty"' in action_log
    assert "等待 Agent 活动" in action_log
    assert 'data-ui="monitor-surface"' in monitor
    assert 'data-ui="monitor-empty-surface"' in monitor
    assert monitor_styles.count("grid-area: 1 / 1;") >= 2
    assert "monitorEmptyCenterOffset" in audit
    assert "actionLogEmptyCenterOffset" in audit
    assert "Math.abs(item.monitorEmptyCenterOffset.y) > 2" in audit
    assert "Math.abs(item.actionLogEmptyCenterOffset.y) > 2" in audit


def test_profile_bootstrap_fields_keep_visible_labels_and_visual_audit_coverage():
    panel = (
        ROOT / "apps/desktop/renderer/src/components/Runtime/ProfileBootstrapPanel.tsx"
    ).read_text(encoding="utf-8")
    audit = (ROOT / "scripts/audit-source-ui.cjs").read_text(encoding="utf-8")

    assert 'data-ui="profile-bootstrap-panel"' in panel
    # 字段必须保留可见 label 容器类；允许并列工具类（如 viz-field-mt），按子串统计。
    assert panel.count("viz-management-field") >= 10
    for label in (
        "维护 Profile",
        "Cookie 文件",
        "新 Profile 别名",
        "Bundle 加密口令",
        "Bundle 解密口令",
        "再次确认 Bundle 口令",
    ):
        assert f"<span>{label}</span>" in panel
    assert "controlIdentityDesktop" in audit
    assert "controlIdentityMobile" in audit
    assert "controlSafetyDesktop" in audit
    assert "controlSafetyMobile" in audit


def test_source_ui_audit_waits_for_runtime_state_before_control_capture():
    audit = (ROOT / "scripts/audit-source-ui.cjs").read_text(encoding="utf-8")

    assert 'document.querySelector(".viz-header-pill")' in audit
    assert 'runtimeState !== "starting"' in audit
    assert "Runtime state did not settle before source UI capture" in audit


def test_brand_mark_geometry_is_consistent_across_public_assets():
    sources = (
        (ROOT / "packaging/webfa-mark.svg").read_text(encoding="utf-8"),
        (ROOT / "apps/desktop/renderer/src/components/Layout/BrandMark.tsx").read_text(
            encoding="utf-8"
        ),
        (ROOT / "scripts/generate-brand-assets.cjs").read_text(encoding="utf-8"),
    )
    for fragment in ("19.05", "9.43", "15.17", "5.20", "19.34", "5.25", "2.6"):
        assert all(fragment in source for source in sources), fragment
