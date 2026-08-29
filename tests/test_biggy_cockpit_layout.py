"""Static contracts for the A.R.G.U.S. Cockpit and Fleet rail layout."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRAND = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
BRAND_CSS = (ROOT / "static" / "biggy-brand.css").read_text(encoding="utf-8")
ARGUS_WORLD = (ROOT / "api" / "argus_world.py").read_text(encoding="utf-8")
BIGGY_ELECTRICAL = (ROOT / "static" / "biggy-electrical-tools.js").read_text(encoding="utf-8")


def test_cockpit_owns_home_sync_filter_rag_ptt_and_room_in_order():
    cockpit = BRAND[BRAND.index("function installCockpitStrip"):BRAND.index("function forceChromeLabels")]
    assert cockpit.index("makeHomeControl()") < cockpit.index("makeSpeechSyncControl()")
    assert cockpit.index("<span>FILTER</span>") < cockpit.index("rag.textContent = 'RAG'")
    assert cockpit.index("rag.textContent = 'RAG'") < cockpit.index("controls.querySelector('#biggyPtt')")
    assert cockpit.index("controls.querySelector('#biggyPtt')") < cockpit.index("controls.querySelector('#biggyAudioRoute')")


def test_fleet_strip_only_owns_machine_launchers():
    fleet = BRAND[BRAND.index("function renderFleetStrip"):BRAND.index("async function refreshFleetStrip")]
    assert "makeHomeControl" not in fleet
    assert "makeSpeechSyncControl" not in fleet
    assert "launchFleetMachine(machine)" in fleet


def test_filter_stays_functional_but_is_removed_from_right_rail():
    cockpit = BRAND[BRAND.index("function installCockpitStrip"):BRAND.index("function forceChromeLabels")]
    mount = BRAND[BRAND.index("function mountTravelRailInWorkspace"):BRAND.index("function hideTravelMap")]
    assert "biggyCatRail-filter" in cockpit
    assert 'filter.hidden = true' in mount
    assert 'data-category="filter"' in BRAND_CSS


def test_orb_is_bottom_docked_and_cockpit_and_fleet_share_top_center():
    assert ".biggy-argus-reactor{" in BRAND_CSS
    assert "bottom:calc(100% - 72px)" in BRAND_CSS
    assert ".biggy-top-rail-group{" in BRAND_CSS
    assert "position:absolute;left:50%;top:20px" in BRAND_CSS
    assert "group.prepend(strip)" in BRAND
    assert "group.appendChild(strip)" in BRAND
    assert "reactorDock.appendChild(modelStatus)" in BRAND
    assert "composer.appendChild(reactorDock)" in BRAND


def test_reactor_model_badge_remains_single_line_after_bottom_dock_move():
    chip_rule = BRAND_CSS[BRAND_CSS.index("#j-brain-chip{"):BRAND_CSS.index("#j-orb svg")]
    assert "white-space:nowrap" in chip_rule
    assert "text-overflow:ellipsis" in chip_rule
    status_rule = BRAND_CSS[BRAND_CSS.index(".biggy-brand-status{"):BRAND_CSS.index(".biggy-brand-meta{")]
    assert "width:max-content" in status_rule


def test_rag_button_toggles_panel_without_reinstalling_conversation_stack():
    cockpit = BRAND[BRAND.index("function installCockpitStrip"):BRAND.index("function forceChromeLabels")]
    assert "biggyCockpitRag" in cockpit
    assert "setArgusRagPanelVisible" in cockpit
    assert "aria-pressed" in BRAND
    assert "ARGUS_RAG_PANEL_STORAGE_KEY" in BRAND
    assert ".biggy-argus-rag-overview[hidden]{display:none}" in BRAND_CSS
    assert "setArgusRagPanelVisible(false, rag, false)" in cockpit
    assert "biggy-rag-visibility" in BRAND
    shell = BRAND[BRAND.index("function applyShell()"):BRAND.index("async function tryStart()")]
    assert "installArgusConversationLane(mainChat)" not in shell
    assert ".biggy-argus-conversation-lane" not in BRAND_CSS


def test_hidden_rag_galaxy_stops_the_dormant_webgl_render_loop():
    visibility = ARGUS_WORLD[
        ARGUS_WORLD.index("function setRagGalaxyVisible"):
        ARGUS_WORLD.index("function restoreBaseGalaxyVisibility")
    ]
    assert "g.resumeAnimation()" in visibility
    assert "controls.autoRotate = true" in visibility
    assert "controls.autoRotate = false" in visibility
    assert "g.pauseAnimation()" in visibility


def test_prompt_and_pa_deck_match_bottom_rail_without_overlap():
    assert "--biggy-bottom-deck-width:min(856px,calc(100% - 48px))" in BRAND_CSS
    assert "padding:10px 84px 66px" in BRAND_CSS
    assert "width:var(--biggy-bottom-deck-width);margin:0 auto" in BRAND_CSS
    assert "width:var(--biggy-bottom-deck-width);max-width:calc(100% - 48px)" in BRAND_CSS
    assert "function syncBiggySharedCenterline()" in BRAND
    assert "const masterX = axisRect.left + (axisRect.width / 2)" in BRAND
    assert "placeOnMaster(document.getElementById('biggyTopRailGroup'))" in BRAND
    assert "placeOnMaster(document.getElementById('biggyArgusReactor'))" in BRAND
    assert "biggy-home-centerline-sync" in BRAND


def test_prompt_and_pa_deck_use_the_rendered_main_chat_width_on_every_monitor():
    sync = BRAND[BRAND.index("function syncBiggySharedCenterline"):BRAND.index("function scheduleBiggySharedCenterline")]
    assert "const mainRect = mainChat.getBoundingClientRect()" in sync
    assert "const horizontalInset = window.matchMedia('(max-width: 900px)').matches ? 24 : 168" in sync
    assert "const deckWidth = Math.max(0, Math.min(856, mainRect.width - horizontalInset))" in sync
    assert "deck.style.width = `${deckWidth}px`" in sync
    assert "hermesStrip.style.width = `${deckWidth}px`" in sync
    assert "new MutationObserver(scheduleBiggySharedCenterline)" in BRAND


def test_prompt_actions_return_to_half_height_prompt_in_requested_order():
    assert "function installPromptInlineControls()" in BRAND
    assert "controls.appendChild(attach)" in BRAND
    assert "controls.appendChild(savedPrompts)" in BRAND
    assert "controls.appendChild(dictate)" in BRAND
    assert "controls.appendChild(voice)" in BRAND
    assert "controls.appendChild(send)" in BRAND
    prompt_controls = BRAND[BRAND.index("function installPromptInlineControls"):BRAND.index("const FLEET_STATUS_PATH")]
    assert prompt_controls.index("controls.appendChild(attach)") < prompt_controls.index("controls.appendChild(savedPrompts)")
    assert prompt_controls.index("controls.appendChild(savedPrompts)") < prompt_controls.index("controls.appendChild(dictate)")
    assert prompt_controls.index("controls.appendChild(dictate)") < prompt_controls.index("controls.appendChild(voice)")
    assert prompt_controls.index("controls.appendChild(voice)") < prompt_controls.index("controls.appendChild(send)")
    assert "box.appendChild(savedPromptsPopup)" in prompt_controls
    assert "installPromptInlineControls();" in BRAND
    assert ".biggy-prompt-inline-controls{" in BRAND_CSS
    assert "flex-direction:row;flex-wrap:nowrap" in BRAND_CSS
    assert "min-height:34px;height:36px;max-height:92px" in BRAND_CSS
    assert "width:28px;height:28px" in BRAND_CSS


def test_expanded_biggy_voice_keeps_inline_actions_in_the_prompt_row():
    controls = BRAND_CSS[BRAND_CSS.index(".biggy-prompt-inline-controls{"):BRAND_CSS.index(".biggy-prompt-inline-controls #btnGptVoice")]
    assert "top:auto;bottom:4px" in controls
    assert "transform:none" in controls
    assert "top:50%" not in controls


def test_remaining_native_prompt_controls_join_the_hermes_rail():
    hermes = BRAND[BRAND.index("function installHermesStrip"):BRAND.index("function installPaRailToggle")]
    assert "const footer = document.querySelector('.composer-footer')" in hermes
    assert "strip.appendChild(footer)" in hermes
    assert ".biggy-hermes-strip>.composer-footer{" in BRAND_CSS


def test_pa_button_owns_closed_by_default_right_rail():
    assert "function installPaRailToggle(mainChat)" in BRAND
    assert "setOpen(false)" in BRAND
    assert "installPaRailToggle(mainChat)" in BRAND
    assert "window.closeWorkspacePanel()" in BRAND
    assert "deck.insertBefore(button, box)" in BRAND
    assert ".biggy-pa-toggle{" in BRAND_CSS
    assert ".biggy-pa-rail-open > .biggy-category-rail" in BRAND_CSS
    assert "body.biggy-brand #btnWorkspacePanelEdgeToggle{display:none!important}" in BRAND_CSS


def test_rag_overview_clears_top_rails_on_desktop_and_tablet():
    assert "left:24px;top:76px" in BRAND_CSS
    assert ".biggy-argus-rag-overview{left:12px;top:64px" in BRAND_CSS


def test_rag_overview_preserves_radar_and_adds_four_level_ingest_controls():
    tools = BRAND[BRAND.index("function ensureArgusRagIngestTools"):BRAND.index("function renderArgusRagOverview")]
    assert 'id="biggyArgusRagSummary"' in BRAND
    assert "panel.id = 'biggyArgusIngestTools'" in tools
    assert 'id="biggyArgusLibraryFolder"' in tools
    assert 'id="biggyArgusLibrarySubfolder"' in tools
    assert 'id="biggyArgusLibraryLevel3"' in tools
    assert 'id="biggyArgusLibraryLevel4"' in tools
    assert "selectedArgusLibraryFolder" in tools
    assert "refreshArgusLibrarySubfolders" in tools
    assert "refreshArgusLibraryLevel3" in tools
    assert "refreshArgusLibraryLevel4" in tools
    assert "ARGUS_RAG_INGEST_PROXY" in tools
    assert "const ARGUS_RAG_INGEST_PROXY = '/api/biggy/rag'" in BRAND
    assert "/ingest-upload?folder=" in tools
    assert "NEW LIBRARY FOLDER" in tools
    assert "CORPUS STATUS" in tools
    assert "EMBED → QDRANT → ARGUS" in tools
    assert ".biggy-argus-ingest-tools{" in BRAND_CSS
    assert ".biggy-argus-ingest-drop{" in BRAND_CSS


def test_rag_ingest_polling_follows_rag_panel_visibility():
    visibility = BRAND[BRAND.index("function setArgusRagPanelVisible"):BRAND.index("function installArgusConversationLane")]
    assert "startArgusRagIngestPolling" in visibility
    assert "stopArgusRagIngestPolling" in visibility


def test_legacy_conversation_stack_is_removed_from_the_active_shell():
    shell = BRAND[BRAND.index("function applyShell()"):BRAND.index("async function tryStart()")]
    assert "installArgusConversationLane(mainChat)" not in shell
    assert "clearInterval(conversationLaneTimer)" in shell
    assert ".biggy-argus-conversation-lane" not in BRAND_CSS


def test_hermes_controls_replace_left_navigation_beneath_prompt():
    assert "body.biggy-brand .layout > .rail" in BRAND_CSS
    assert "body.biggy-brand .layout > .sidebar" in BRAND_CSS
    assert "function installHermesStrip(mainChat)" in BRAND
    assert "layout.appendChild(strip)" in BRAND
    assert ".biggy-hermes-strip{" in BRAND_CSS
    assert "bottom:8px" in BRAND_CSS
    for panel in ("chat", "tasks", "kanban", "skills", "memory", "workspaces", "profiles", "todos", "insights", "logs", "settings"):
        assert f"['{panel}'," in BRAND


def test_hermes_secondary_panels_share_one_centered_starfield_overlay():
    assert "const HERMES_SECONDARY_PANELS = Object.freeze({" in BRAND
    for panel, main_id in (
        ("tasks", "mainTasks"),
        ("kanban", "mainKanban"),
        ("skills", "mainSkills"),
        ("memory", "mainMemory"),
        ("workspaces", "mainWorkspaces"),
        ("profiles", "mainProfiles"),
        ("insights", "mainInsights"),
        ("logs", "mainLogs"),
        ("settings", "mainSettings"),
    ):
        assert f"{panel}: '{main_id}'" in BRAND
    assert "todos: null" in BRAND
    assert "function ensureHermesSecondaryHost(mainChat)" in BRAND
    assert "function openHermesSecondaryPanel(mainChat, panel, label)" in BRAND
    assert "function closeHermesSecondaryPanel" in BRAND
    assert "host.id = 'biggyHermesSecondaryHost'" in BRAND
    assert "page.dataset.hermesPanel = panel" in BRAND
    assert "await window.switchPanel(panel)" in BRAND
    strip = BRAND[BRAND.index("function installHermesStrip"):BRAND.index("function installPaRailToggle")]
    assert "panel === 'settings'" not in strip
    assert ".biggy-hermes-secondary-host{" in BRAND_CSS
    assert "width:var(--biggy-bottom-deck-width)" in BRAND_CSS
    assert ".biggy-hermes-secondary-scroll{" in BRAND_CSS
    assert "overflow-y:auto" in BRAND_CSS
    assert "flex-direction:column" in BRAND_CSS


def test_settings_overlay_keeps_native_hermes_items_and_hosts_session_controls():
    assert "function installHermesSettingsControls(page)" in BRAND
    settings = BRAND[BRAND.index("function installHermesSettingsControls"):BRAND.index("function ensureHermesSecondaryHost")]
    for node_id in (
        "profileChipWrap",
        "composerWorkspaceGroup",
        "composerModelChip",
        "composerReasoningWrap",
        "composerWsDropdown",
        "composerModelDropdown",
        "composerReasoningDropdown",
    ):
        assert node_id in settings
    assert "page.insertBefore(controls, page.firstChild)" in settings
    assert "installHermesSettingsControls(page)" in BRAND[BRAND.index("function ensureHermesSecondaryHost"):BRAND.index("async function openHermesSecondaryPanel")]
    assert ".biggy-hermes-settings-controls{" in BRAND_CSS
    assert '.biggy-hermes-secondary-page[data-hermes-panel="settings"]' in BRAND_CSS


def test_hermes_secondary_overlay_tracks_the_rendered_lower_rail_width():
    sync = BRAND[BRAND.index("function syncBiggySharedCenterline"):BRAND.index("function scheduleBiggySharedCenterline")]
    assert "const hermesSecondaryHost = document.getElementById('biggyHermesSecondaryHost')" in sync
    assert "hermesSecondaryHost.style.width = `${deckWidth}px`" in sync
    assert "const reactorRect = reactor.getBoundingClientRect()" in sync
    assert "hermesSecondaryHost.style.bottom = `${overlayBottom}px`" in sync


def test_tools_launcher_is_last_on_hermes_rail_and_toggles_hidden_top_rail():
    strip = BRAND[BRAND.index("function installHermesStrip"):BRAND.index("function installPaRailToggle")]
    assert "button.dataset.panel = 'tools'" in strip
    assert "<span>TOOLS</span>" in strip
    assert strip.index("if (footer) strip.appendChild(footer)") < strip.index("button.dataset.panel = 'tools'")
    assert "function ensureBiggyToolsRail(mainChat)" in BRAND
    assert "rail.id = 'biggyToolsRail'" in BRAND
    assert "rail.hidden = true" in BRAND
    assert "toggleBiggyToolsRail(mainChat, button)" in strip
    assert ".biggy-tools-rail{" in BRAND_CSS
    assert ".biggy-tools-rail[hidden]{display:none!important}" in BRAND_CSS


def test_tools_rail_carries_every_smedley_electrical_tool_in_two_groups():
    rail = BRAND[BRAND.index("const BIGGY_ELECTRICAL_TOOLS"):BRAND.index("function loadBiggyElectricalAsset")]
    for tool_id in (
        "voltage-drop", "feeder-size", "conductor-sets", "ocpd-size",
        "conduit-fill", "grounding", "cable-tray-fill", "motor-circuit",
        "motor-starter", "mcc-bucket", "vfd-circuit",
    ):
        assert f"['{tool_id}'," in rail
    assert "GENERIC CIRCUIT TOOLS" in BRAND
    assert "MOTOR & STARTER TOOLS" in BRAND


def test_biggy_tools_use_shared_smedley_calculation_assets_and_center_overlay():
    assert "'/extensions/smedley-engineering/voltage-drop-sizing.js'" in BRAND
    assert "'/extensions/smedley-engineering/smedley-electrical-results.js'" in BRAND
    assert "'/extensions/smedley-engineering/smedley-live-tools.v0.2.5.js'" in BRAND
    assert "'/static/biggy-electrical-tools.js'" in BRAND
    assert "window.BiggyElectricalTools.open" in BRAND
    assert "page.dataset.hermesPanel = 'tools'" in BRAND
    assert "host.dataset.activePanel = 'tools'" in BRAND
    assert "main.classList.add('biggy-hermes-overlay-open')" in BRAND
    assert "main.classList.add('biggy-tools-open')" in BRAND
    assert '.biggy-hermes-secondary-page[data-hermes-panel="tools"]' in BRAND_CSS


def test_electrical_runtime_disposes_the_previous_tool_before_opening_another():
    assert "let activeClose = null" in BIGGY_ELECTRICAL
    assert "if(activeClose)activeClose()" in BIGGY_ELECTRICAL
    assert "if(activeClose===close)activeClose=null" in BIGGY_ELECTRICAL
    assert "SmedleyVoltageDropSizing" in BIGGY_ELECTRICAL
    assert "SmedleyElectricalResults" in BIGGY_ELECTRICAL
    assert "SmedleyLiveTools" in BIGGY_ELECTRICAL


def test_server_owned_speech_cannot_start_a_second_browser_reader():
    policy = BRAND[BRAND.index("function installSmedleyAudioPolicy"):BRAND.index("function isBiggyInstance")]
    assert "newestAssistant.ptt_owned_tts" in policy
    assert "String(newestAssistant.tts_owner || '').trim()" in policy
    ownership_guard = policy.index("newestAssistant.ptt_owned_tts")
    browser_speech = policy.index("speakOnSmedley(raw")
    assert ownership_guard < browser_speech


def test_galaxy_canvas_remains_full_screen_while_home_camera_controls_framing():
    assert "const syncGalaxyViewportProfile = () =>" not in BRAND
    assert "iframe.style.top = `${profileTop}px`" not in BRAND
    assert ".biggy-v6-world{\n  position:absolute;inset:0;width:100%;height:100%" in BRAND_CSS
    assert "window.addEventListener('resize', scheduleGalaxyCanvasSize)" in BRAND
    assert "starField.scale.set(1.55, 1.35, 1.2)" in ARGUS_WORLD


def test_home_uses_lightweight_starfield_and_lazy_loads_webgl_on_rag_reveal():
    install = BRAND[
        BRAND.index("function installBiggyV6World"):
        BRAND.index("function makeHeader")
    ]
    toggle = BRAND[
        BRAND.index("function setArgusRagPanelVisible"):
        BRAND.index("function ensureArgusConversationLane")
    ]
    assert "iframe.dataset.src = `${V6_WORLD_PATH}" in install
    assert "iframe.dataset.loaded = '0'" in install
    assert "iframe.hidden = true" in install
    assert "frame.src = frame.dataset.src" in toggle
    assert "frame.hidden = false" in toggle
    assert "frame.hidden = true" in toggle
    assert ".biggy-dormant-starfield{" in BRAND_CSS


def test_rag_reveal_restores_home_camera_and_boot_does_not_restore_stale_cards():
    assert "{ type: 'biggy-rag-home' }" in BRAND
    assert "data.type === 'biggy-rag-home'" in ARGUS_WORLD
    assert "primeOnly = false" in BRAND
    assert "if (primeOnly) return false" in BRAND
    assert "force: true, primeOnly: true" in BRAND


def test_argus_response_label_observer_is_idempotent():
    """Response branding must not trigger its own MutationObserver forever."""
    labels = BRAND[BRAND.index("function labelArgusResponses"):BRAND.index("function removeCaduceus")]
    assert "name && name.textContent !== 'A.R.G.U.S.'" in labels
    assert "icon && icon.textContent !== 'A'" in labels
    assert "turn.dataset.responseAgent !== 'argus'" in labels
    assert "if (name) name.textContent = 'A.R.G.U.S.'" not in labels
