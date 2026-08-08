from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
APP_CSS = (ROOT / "app" / "static" / "app.css").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
MAIN_PY = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_ambiguous_status_decorations_are_not_rendered() -> None:
    assert "metric-ring" not in APP_JS
    assert ".metric-ring" not in APP_CSS
    assert "性能下降" not in APP_JS
    assert "可用但受限" not in APP_JS
    assert "代理可以使用" not in APP_JS
    assert "position: absolute;\n  right: -3px;\n  bottom: -3px;" not in APP_CSS


def test_plain_language_explanations_and_location_controls_exist() -> None:
    for phrase in (
        "节点连接不稳定",
        "完整代理链路只有部分测速成功",
        "各网站访问结果在右侧单独显示",
        "存在地区限制",
        "成功取得目标网站响应",
        "每个状态都代表什么",
        "健康评分",
        "24 小时在线率",
        "自动识别出口地区",
        "至少两个公开来源",
    ):
        assert phrase in APP_JS
    assert "人机验证" not in APP_JS
    assert "需要验证" not in APP_JS
    assert "/api/nodes/${nodeId}/locate" in APP_JS


def test_node_rows_show_two_explicit_latency_lines() -> None:
    for phrase in (
        "节点 → 网站",
        "本地 → 节点",
        "网站完整耗时",
        "局域网监测小主机",
        "真实代理链路",
        "完整代理协议链路",
        "固定轻量 204",
        "不会使用 CDN",
        "Google 204",
        "Cloudflare 204",
        "启用本地节点测速",
        "node_probe_enabled",
        "website_latency_ms",
    ):
        assert phrase in (APP_JS + MAIN_PY + (ROOT / "app" / "executor.py").read_text(encoding="utf-8"))
    assert 'class="dual-latency ${extraClass}"' in APP_JS
    assert "经节点 → 网站" not in APP_JS
    assert "latency-line is-website" in APP_JS
    assert "latency-line is-node" in APP_JS
    assert ".dual-latency" in APP_CSS
    assert ".latency-line" in APP_CSS


def test_sort_picker_matches_panel_and_separates_two_latency_metrics() -> None:
    for phrase in (
        "NODE_SORT_OPTIONS",
        'value: "website_latency"',
        'value: "node_latency"',
        "节点 → 网站",
        "本地 → 节点",
        'data-action="toggle-sort-menu"',
        'data-action="set-sort"',
        'data-action="set-sort-direction"',
        'role="listbox"',
        'role="option"',
        "sortDirectionMeta",
        "快到慢",
        "慢到快",
    ):
        assert phrase in APP_JS
    assert '<select data-filter="sort">' not in APP_JS
    for selector in (
        ".sort-picker",
        ".sort-picker-trigger",
        ".sort-menu",
        ".sort-option",
        ".sort-direction-panel",
    ):
        assert selector in APP_CSS


def test_desktop_node_columns_are_resizable_and_persistent() -> None:
    for phrase in (
        "COLUMN_WIDTH_STORAGE_KEY",
        "airport-monitor-node-columns-v1",
        "NODE_COLUMN_LIMITS",
        "columnHeaderMarkup",
        'data-action="reset-columns"',
        "恢复列宽",
        "bindColumnResizing",
        'addEventListener("pointerdown"',
        '"ArrowLeft", "ArrowRight"',
        'role="separator"',
        "aria-valuenow",
        "persistColumnLayouts",
        "localStorage.setItem(COLUMN_WIDTH_STORAGE_KEY",
        "window.innerWidth <= 1400",
    ):
        assert phrase in APP_JS
    for key in (
        "select",
        "node",
        "status",
        "region",
        "latency",
        "health",
        "availability",
        "services",
        "checked",
        "actions",
    ):
        assert f"{key}:" in APP_JS.split("const NODE_COLUMN_LIMITS", 1)[1].split("});", 1)[0]
    for selector in (
        ".column-head",
        ".column-resizer",
        ".node-workbench.has-custom-columns .node-table-head",
        ".node-workbench.has-custom-columns .node-list",
        "body.is-column-resizing",
    ):
        assert selector in APP_CSS
    desktop_css = APP_CSS.split("@media (min-width: 1401px)", 1)[1].split(
        "@media (max-width: 1450px)", 1
    )[0]
    assert "overflow-x: auto" in desktop_css
    mobile_css = APP_CSS.split("@media (max-width: 1400px)", 1)[1]
    assert ".column-reset-button" in mobile_css
    assert ".column-resizer" in mobile_css
    assert "display: none" in mobile_css


def test_responsive_service_icons_wrap_instead_of_being_clipped() -> None:
    responsive_css = APP_CSS.split("@media (max-width: 1400px)", 1)[1].split(
        "@media (max-width: 900px)", 1
    )[0]
    service_css = responsive_css.split(".service-strip {", 1)[1].split("}", 1)[0]
    assert "flex-wrap: wrap" in service_css
    assert "overflow: visible" in service_css
    mark_css = responsive_css.split(".service-mark {", 1)[1].split("}", 1)[0]
    assert "width: 32px" in mark_css


def test_node_status_reason_is_not_truncated_case() -> None:
    assert 'class="node-status-cell"' in APP_JS
    status_css = APP_CSS.split(".uptime-note {", 1)[1].split("}", 1)[0]
    assert "white-space: normal" in status_css
    assert "text-overflow: ellipsis" not in status_css
    compact_css = APP_CSS.split("@media (max-width: 1450px)", 1)[1]
    assert ".protocol-mark" in compact_css
    assert "display: none" in compact_css.split(".protocol-mark", 1)[1].split("}", 1)[0]


def test_service_result_has_logo_icon_and_accessible_description() -> None:
    assert 'class="service-mark level-${meta[1]}"' in APP_JS
    assert 'role="img"' in APP_JS
    assert 'aria-label="${escapeHtml(description)}"' in APP_JS
    assert 'class="service-state-icon"' in APP_JS


def test_action_tooltips_do_not_expand_node_rows() -> None:
    assert ".row-actions .icon-button[data-tooltip]::after" not in APP_CSS
    assert "content: attr(data-tooltip)" not in APP_CSS
    assert 'data-tooltip="查看详情" title="查看详情"' in APP_JS


def test_node_detail_is_centered_compact_and_keyboard_safe() -> None:
    assert 'class="modal node-detail-modal"' in APP_JS
    assert 'class="drawer"' not in APP_JS
    assert "data.runs.slice(0, 5)" in APP_JS
    assert "最近 5 次检测" in APP_JS
    assert ".node-detail-modal" in APP_CSS
    assert "justify-self: end" not in APP_CSS
    assert 'event.key !== "Tab"' in APP_JS


def test_secret_forms_do_not_invite_password_autofill() -> None:
    assert 'id="subscription-form" class="modal-body" autocomplete="off"' in APP_JS
    assert 'name="url" type="password"' in APP_JS
    assert 'autocomplete="new-password" data-1p-ignore' in APP_JS
    assert 'id="notification-form" class="notification-form" autocomplete="off"' in APP_JS


def test_mobile_login_does_not_keep_navigation_padding() -> None:
    assert "body:has(#login-view:not([hidden]))" in APP_CSS
    login_body_css = APP_CSS.split(
        "body:has(#login-view:not([hidden])) {", 1
    )[1].split("}", 1)[0]
    assert "padding-bottom: 0" in login_body_css


def test_metric_labels_use_full_chinese_and_can_wrap() -> None:
    assert '"24 小时在线率", "availability", true' in APP_JS
    assert '"24h 在线率"' not in APP_JS
    metric_label_css = APP_CSS.split(".metric-copy small {", 1)[1].split("}", 1)[0]
    assert "white-space: normal" in metric_label_css
    assert "text-overflow: ellipsis" not in metric_label_css


def test_node_identity_text_can_display_in_full() -> None:
    for selector in (".node-identity strong {", ".node-identity small {"):
        block = APP_CSS.split(selector, 1)[1].split("}", 1)[0]
        assert "white-space: normal" in block
        assert "text-overflow: ellipsis" not in block


def test_detail_history_has_room_for_specific_status_text() -> None:
    detail_run_css = APP_CSS.split(
        ".node-detail-modal .run-row {", 1
    )[1].split("}", 1)[0]
    assert "minmax(170px, 1.25fr)" in detail_run_css
    mobile_css = APP_CSS.split("@media (max-width: 680px)", 1)[1]
    assert ".node-detail-modal .run-row" in mobile_css


def test_external_check_all_button_is_bound() -> None:
    assert 'const externalCheckAll = $(\'[data-action="check-all"]\', root);' in APP_JS
    assert "externalCheckAll.addEventListener" in APP_JS
    assert "runCheckAll(externalCheckAll)" in APP_JS


def test_dashboard_only_requests_enabled_nodes() -> None:
    assert 'nodeQuery.set("enabled_only", "true")' in APP_JS
    assert 'nodeQuery.get("status") === "paused"' in APP_JS
    assert 'mode === "dashboard"' in APP_JS


def test_homepage_performance_metrics_are_explicit() -> None:
    for phrase in (
        "小主机性能",
        "每 60 秒轻量采样",
        "整机 CPU",
        "全部核心综合",
        "内存占用",
        "硬盘占用",
        "CPU 温度",
        "CPU Package",
        "硬盘温度",
        "SMART 实测",
        "传感器不可用",
        "占用偏高",
        "温度偏高",
    ):
        assert phrase in APP_JS
    assert ".performance-ribbon" in APP_CSS
    assert ".performance-track" in APP_CSS
    assert ".hardware-profile" in APP_CSS
    assert "function hardwareProfile(hardware = {})" in APP_JS
    assert "小主机硬件配置" in APP_JS
    assert "state.dashboard.hardware || {}" in APP_JS
    assert 'performanceMetric("硬盘温度", system.disk_temperature_c, "diskTemperature", "thermometer", "SMART 实测")' in APP_JS


def test_homepage_key_numbers_have_a_readable_visual_scale() -> None:
    summary_value_css = APP_CSS.split(".summary-ribbon strong {", 1)[1].split(
        "}", 1
    )[0]
    performance_value_css = APP_CSS.split(
        ".performance-copy > strong {", 1
    )[1].split("}", 1)[0]
    assert "clamp(1.68rem" in summary_value_css
    assert "font-weight: 830" in summary_value_css
    assert "clamp(1.36rem" in performance_value_css
    assert "font-weight: 830" in performance_value_css
    assert "@media (max-width: 1180px)" in APP_CSS


def test_node_management_has_direct_selection_and_enable_controls() -> None:
    for phrase in (
        'class="node-management-bar"',
        'data-action="select-visible"',
        "全选本页",
        'data-action="enable-selected"',
        "启用所选",
        'data-action="disable-selected"',
        "停用所选",
        'data-action="set-node-enabled"',
        'class="button button-small node-state-button',
        "retainVisibleSelection",
    ):
        assert phrase in APP_JS
    for selector in (
        ".node-management-bar",
        ".node-management-actions",
        ".button-enable",
        ".button-disable",
        ".node-state-button",
    ):
        assert selector in APP_CSS
    assert '@app.put("/api/nodes/enabled-batch")' in MAIN_PY
    assert "class NodeBatchEnableRequest" in MAIN_PY
    assert "max_length=500" in MAIN_PY


def test_admin_session_defaults_to_fixed_thirty_days() -> None:
    assert "SESSION_DAYS = 30" in MAIN_PY
    assert "SESSION_MAX_AGE_SECONDS = SESSION_DAYS * 24 * 60 * 60" in MAIN_PY
    assert "timedelta(days=SESSION_DAYS)" in MAIN_PY
    assert "remaining_seconds = max(1" in MAIN_PY
    assert "30 天后自动失效" in INDEX_HTML


def test_every_native_select_is_enhanced_by_the_shared_control() -> None:
    assert APP_JS.count("<select") == 10
    assert APP_JS.count("data-select-kind=") == 10
    for kind in (
        "status",
        "country",
        "service",
        "page_size",
        "trend_range",
        "region",
        "refresh_interval",
    ):
        assert f'data-select-kind="{kind}"' in APP_JS
    for phrase in (
        "function enhanceSelects",
        "function setSmartSelectOpen",
        "function syncSmartSelect",
        'role", "combobox"',
        'role="listbox"',
        'role="option"',
        '"ArrowDown", "ArrowUp", "Home", "End"',
        "event.stopPropagation()",
    ):
        assert phrase in APP_JS
    for selector in (
        ".smart-select-trigger",
        ".smart-select-menu",
        ".smart-select-option",
        ".smart-select-native",
        ".smart-select-menu-head",
    ):
        assert selector in APP_CSS


def test_latency_statistics_has_six_windows_and_clear_metric_language() -> None:
    for phrase in (
        'data-view="latency"',
        'id="page-latency"',
        'id="latency-content"',
    ):
        assert phrase in INDEX_HTML
    for phrase in (
        "function loadLatency",
        "function renderLatency",
        "function latencyPeriodCell",
        "function periodCoverage",
        "function openLatencyScoreGuide",
        "720 小时",
        "${windowItem.hours} 小时",
        "${escapeHtml(windowItem.label)}",
        "本地 → 节点",
        "节点 → 网站",
        "30 天时间在线率",
        "30 天总评分",
        "在线率按可观测时间加权",
        "覆盖率与置信度",
        "未知数据不再重新分配权重抬高总分",
        "离线直到恢复都持续扣分",
        "恢复后立即全量复测",
    ):
        assert phrase in APP_JS
    for selector in (
        ".latency-summary-ribbon",
        ".latency-table-scroll",
        ".latency-node-row",
        ".latency-period-cell",
        ".latency-overall-score",
        ".score-formula",
    ):
        assert selector in APP_CSS
    assert '@app.get("/api/latency-summary")' in MAIN_PY
    assert "grid-template-columns: repeat(6, 1fr);" in APP_CSS


def test_dynamic_visual_styles_are_allowed_without_relaxing_scripts() -> None:
    assert "script-src 'self'" in MAIN_PY
    assert "script-src 'self' 'unsafe-inline'" not in MAIN_PY
    assert "style-src-elem 'self'" in MAIN_PY
    assert "style-src-attr 'unsafe-inline'" in MAIN_PY


def test_every_supported_country_has_a_local_flag_asset() -> None:
    country_block = APP_JS.split("const COUNTRY_NAMES = {", 1)[1].split("};", 1)[0]
    country_codes = set(re.findall(r"\b([A-Z]{2}):", country_block))
    flag_codes = {
        item.stem.upper()
        for item in (ROOT / "app" / "static" / "flags").glob("*.svg")
    }
    assert country_codes
    assert country_codes <= flag_codes
    assert (ROOT / "app" / "static" / "flags" / "LICENSE-flag-icons.txt").exists()


def test_account_and_region_disclosures_use_the_same_accessible_language() -> None:
    assert 'id="user-menu" class="user-menu" role="menu"' in INDEX_HTML
    assert 'id="logout-button" role="menuitem"' in INDEX_HTML
    assert "<details><summary><i data-lucide=\"chevron-right\"></i>" in APP_JS
    assert ".location-setting summary::-webkit-details-marker" in APP_CSS


def test_global_theme_picker_has_three_light_palettes_and_deep_gray_dark_mode() -> None:
    for theme, label in (
        ("sky", "天际蓝"),
        ("jade", "青岚绿"),
        ("sunset", "霞光橙"),
        ("dark", "深灰夜色"),
    ):
        assert f'data-theme-option="{theme}"' in INDEX_HTML
        assert label in INDEX_HTML
    assert INDEX_HTML.count('data-theme-trigger') == 2
    assert 'role="menuitemradio"' in INDEX_HTML
    assert 'const themes = ["sky", "jade", "sunset", "dark"]' in APP_JS
    assert 'localStorage.setItem("airport-monitor-theme", next)' in APP_JS
    assert ':root[data-theme="jade"]' in APP_CSS
    assert ':root[data-theme="sunset"]' in APP_CSS
    dark_tokens = APP_CSS.split(':root[data-theme="dark"]', 1)[1].split("}", 1)[0]
    assert "--bg: #17191d" in dark_tokens
    assert "#000" not in dark_tokens


def test_browser_icons_include_svg_and_ico_routes() -> None:
    assert (ROOT / "app" / "static" / "favicon.svg").exists()
    favicon_ico = ROOT / "app" / "static" / "favicon.ico"
    assert favicon_ico.exists()
    assert favicon_ico.stat().st_size > 1024
    assert 'href="/favicon.svg"' in INDEX_HTML
    assert 'href="/favicon.ico"' in INDEX_HTML
    assert '@app.get("/favicon.ico"' in MAIN_PY
    assert 'media_type="image/x-icon"' in MAIN_PY
