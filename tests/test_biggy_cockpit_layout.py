"""Static contracts for the A.R.G.U.S. Cockpit and Fleet rail layout."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRAND = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
BRAND_CSS = (ROOT / "static" / "biggy-brand.css").read_text(encoding="utf-8")
ARGUS_WORLD = (ROOT / "api" / "argus_world.py").read_text(encoding="utf-8")


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
    assert "width:204px;height:280px" in BRAND_CSS
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
    visibility = BRAND[BRAND.index("function setArgusRagPanelVisible"):BRAND.index("function installArgusConversationLane")]
    assert "if (next && host && !document.getElementById('biggyV6World'))" in visibility
    assert "installBiggyV6World(host)" in visibility
    shell = BRAND[BRAND.index("function applyShell()"):BRAND.index("async function tryStart()")]
    assert "clearBiggyV6World(mainChat)" in shell
    assert "installBiggyV6World(mainChat)" not in shell
    assert "installArgusConversationLane(mainChat)" not in shell
    assert ".biggy-argus-conversation-lane" not in BRAND_CSS


def test_starfield_is_shell_owned_when_rag_graph_is_not_loaded():
    starfield = BRAND[BRAND.index("function installStaticStarfield"):BRAND.index("function installBiggyV6World")]
    assert "data-testid', 'biggy-static-starfield'" in starfield
    assert "repeating CSS tile" in starfield
    assert "without loading the RAG graph" in starfield
    assert "Array.from({ length: 1800 }" in starfield
    assert "const yaw = -now" in starfield
    assert "requestAnimationFrame(paint)" in starfield
    assert ".biggy-static-starfield{" in BRAND_CSS
    assert "animation:biggy-static-starfield-drift 84s linear infinite" not in BRAND_CSS
    shell = BRAND[BRAND.index("function applyShell()"):BRAND.index("async function tryStart()")]
    assert "clearBiggyV6World(mainChat);\n    installStaticStarfield(mainChat);" in shell


def test_prompt_and_pa_deck_match_bottom_rail_without_overlap():
    assert "padding:10px 84px 54px" in BRAND_CSS
    assert "width:auto!important;max-width:calc(100% - 48px)" in BRAND_CSS


def test_tools_rail_reuses_the_smedley_engineering_runtime():
    strip = BRAND[BRAND.index("function installHermesStrip"):BRAND.index("function installSettingsSessionControls")]
    assert "biggy-hermes-tools" in strip
    assert "ensureSharedSmedleyTools" in strip
    assert "SmedleyEngineeringTools" in strip
    assert "smedley-engineering.v0.2.5.js" in BRAND
    assert "biggy-tools-rail" in BRAND_CSS
    assert "#mainChat.biggy-brand-iwo > .smedley-engineering-modal-backdrop" in BRAND_CSS
    assert "inset:72px 0 400px;align-items:flex-start;padding:16px" in BRAND_CSS


def test_session_controls_move_to_settings_without_reparenting_native_nodes():
    settings = BRAND[BRAND.index("function installSettingsSessionControls"):BRAND.index("function installPaRailToggle")]
    for source in ("composerWorkspaceChip", "composerModelChip", "composerReasoningChip"):
        assert source in settings
    assert "window.toggleComposerWsDropdown" in settings
    assert "nativeControl.disabled = false" in settings
    assert "document.getElementById('composerModelChip')?.click()" in settings
    assert "window.toggleReasoningDropdown" in settings
    assert "proxy.disabled = false" in settings
    assert "event.stopPropagation()" in settings
    assert "placeNativeMenuInSettings" in settings
    assert "--biggy-settings-menu-top" in settings
    assert "composerModelDropdown" in settings
    assert "biggySettingsMenu" in settings
    assert "#mainChat.biggy-brand-iwo .composer-ws-wrap" in BRAND_CSS
    assert ".biggy-settings-session-controls" in BRAND_CSS
    assert "--biggy-settings-menu-left" in BRAND_CSS
    assert "function syncBiggySharedCenterline()" in BRAND
    assert "const masterX = axisRect.left + (axisRect.width / 2)" in BRAND
    assert "placeOnMaster(document.getElementById('biggyTopRailGroup'))" in BRAND
    assert "reactor.style.top = `${Math.round(axisRect.top - parentRect.top - reactor.offsetHeight - 8)}px`" in BRAND
    assert "biggy-home-centerline-sync" in BRAND


def test_prompt_and_pa_deck_use_the_intrinsic_hermes_rail_width_on_every_monitor():
    sync = BRAND[BRAND.index("function syncBiggySharedCenterline"):BRAND.index("function scheduleBiggySharedCenterline")]
    assert "hermesStrip.style.removeProperty('width')" in sync
    assert "const railWidth = hermesStrip ? Math.round(hermesStrip.getBoundingClientRect().width) : 0" in sync
    assert "deck.style.setProperty('width', `${railWidth}px`)" in sync
    assert "new MutationObserver(scheduleBiggySharedCenterline)" in BRAND


def test_send_and_biggy_voice_return_to_half_height_prompt():
    assert "function installPromptInlineControls()" in BRAND
    assert "makeProxy('btnGptVoice', 'biggyPromptVoiceProxy'" in BRAND
    assert "makeProxy('btnSend', 'biggyPromptSendProxy'" in BRAND
    assert "controls.appendChild(voice)" not in BRAND
    assert "controls.appendChild(send)" not in BRAND
    assert "installPromptInlineControls();" in BRAND
    assert ".biggy-prompt-inline-controls{" in BRAND_CSS
    assert "flex-direction:row;flex-wrap:nowrap" in BRAND_CSS
    assert "min-height:34px;height:36px;max-height:92px" in BRAND_CSS
    assert "width:28px;height:28px" in BRAND_CSS


def test_prompt_actions_share_the_right_hand_control_group_and_leave_text_left_aligned():
    prompt = BRAND[BRAND.index("function installPromptInlineControls()"):BRAND.index("const FLEET_STATUS_PATH")]
    for source in ("btnAttach", "btnSavedPrompts", "btnMic", "btnGptVoice", "btnSend"):
        assert f"makeProxy('{source}'" in prompt
    assert "'biggyPromptAttachProxy', right" in prompt
    assert "'biggyPromptSavedPromptsProxy', right" in prompt
    assert "'biggyPromptDictateProxy', right" in prompt
    assert "padding:7px 166px 7px 12px" in BRAND_CSS
    assert "#mainChat.biggy-brand-iwo #composerBox .composer-footer{display:none!important}" in BRAND_CSS
    assert ".biggy-prompt-inline-left{\n  position:absolute" in BRAND_CSS
    assert "display:none!important" in BRAND_CSS[BRAND_CSS.index(".biggy-prompt-inline-left{"):BRAND_CSS.index(".biggy-prompt-inline-controls button,")]


def test_prompt_controls_are_native_click_proxies_not_reparented_nodes():
    prompt = BRAND[BRAND.index("function installPromptInlineControls()"):BRAND.index("const FLEET_STATUS_PATH")]
    assert "nativeControl.click()" in prompt
    assert "source.cloneNode(true)" in prompt
    assert "controls.appendChild(voice)" not in prompt
    assert "#mainChat.biggy-brand-iwo .composer-footer #btnGptVoice" in BRAND_CSS


def test_session_dropdowns_stage_above_the_settings_overlay_and_restore_after_close():
    settings = BRAND[BRAND.index("function installSettingsSessionControls"):BRAND.index("function installPaRailToggle")]
    assert "biggySettingsMenuPortal" in settings
    assert "menu._biggySettingsMenuHome" in settings
    assert "home.parent.insertBefore(menu" in settings
    assert "biggy-settings-staged-menu" in settings
    assert "menu.style.setProperty('position', 'fixed', 'important')" in settings
    assert ".biggy-settings-menu-portal>.biggy-settings-staged-menu" in BRAND_CSS
    assert "z-index:141!important" in BRAND_CSS


def test_expanded_biggy_voice_keeps_inline_actions_in_the_prompt_row():
    controls = BRAND_CSS[BRAND_CSS.index(".biggy-prompt-inline-controls{"):BRAND_CSS.index(".biggy-prompt-inline-left{")]
    assert "top:auto;bottom:4px" in controls
    assert "transform:none" in controls
    assert "top:50%" not in controls


def test_hermes_rail_never_reparents_native_composer_controls():
    hermes = BRAND[BRAND.index("function installHermesStrip"):BRAND.index("function installPaRailToggle")]
    assert "strip.appendChild(footer)" not in hermes
    assert "box.appendChild(footer)" not in hermes
    assert ".biggy-hermes-strip>.composer-footer{" not in BRAND_CSS


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
    assert "left:24px;top:66px" in BRAND_CSS
    assert ".biggy-argus-rag-overview{left:12px;top:56px" in BRAND_CSS


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


def test_profiles_overlay_includes_the_read_only_hermes_worker_roster():
    strip = BRAND[BRAND.index("function installHermesStrip"):BRAND.index("function installSettingsSessionControls")]
    assert "if (next === 'profiles') await renderBiggyWorkerRoster()" in strip
    roster = BRAND[BRAND.index("async function renderBiggyWorkerRoster"):BRAND.index("function ensureBiggyToolsRail")]
    assert "'/api/biggy/worker-profiles'" in roster
    assert "HERMES WORKERS" in roster
    assert "native Biggy profile remains available" in roster
    assert ".biggy-worker-roster{" in BRAND_CSS


def test_cockpit_rail_keeps_native_hermes_panels_and_composer_interactive():
    """Cockpit launchers must not take ownership of Hermes-rendered nodes."""
    rail = BRAND[BRAND.index("function installHermesStrip(mainChat)"):BRAND.index("function ensureArgusConversationLane")]
    assert "window.switchPanel(next)" in rail
    assert "main.dataset.biggyHermesPanel" in rail
    assert "appendChild(todos)" not in rail
    assert "appendChild(footer)" not in rail
    composer_rule = BRAND_CSS[BRAND_CSS.index("#mainChat.biggy-brand-iwo .composer-wrap{"):BRAND_CSS.index("#mainChat.biggy-brand-iwo .composer-wrap::before")]
    assert "pointer-events:auto" in composer_rule


def test_native_hermes_main_views_present_as_centered_cockpit_overlays():
    assert "main.main>.main-view:not(#mainChat)" in BRAND_CSS
    assert "position:absolute;z-index:80" in BRAND_CSS
    assert "body.biggy-brand main.main>#mainChat.biggy-brand-iwo" in BRAND_CSS


def test_requested_hermes_utility_panes_keep_native_list_and_detail_surfaces():
    """Cockpit utility overlays must expose the full stock interaction model."""
    for panel in ("tasks", "skills", "memory", "workspaces", "profiles", "todos"):
        assert f'[data-biggy-hermes-panel="{panel}"]' in BRAND_CSS
    assert ".layout > .sidebar > .panel-view.active" in BRAND_CSS
    assert "node relocation" in BRAND_CSS
    # ToDos has a native sidebar surface only; it must use the complete overlay.
    assert '[data-biggy-hermes-panel="todos"]) .layout > .sidebar > .panel-view.active' in BRAND_CSS


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


def test_rag_reveal_restores_home_camera_and_boot_does_not_restore_stale_cards():
    assert "{ type: 'biggy-rag-home' }" in BRAND
    assert "data.type === 'biggy-rag-home'" in ARGUS_WORLD
    assert "biggy-rag-home-applied" in BRAND
    assert "parent.postMessage({ type: 'biggy-rag-home-applied'" in ARGUS_WORLD
    assert "iframe.dataset.ragStage = '1'" in BRAND
    assert '.biggy-v6-world[data-rag-stage="1"]{opacity:0!important}' in BRAND_CSS
    assert "frame.removeAttribute('data-rag-stage')" in BRAND
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
