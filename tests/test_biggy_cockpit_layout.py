"""Static contracts for the A.R.G.U.S. Cockpit and Fleet rail layout."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRAND = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
BRAND_CSS = (ROOT / "static" / "biggy-brand.css").read_text(encoding="utf-8")


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


def test_orb_is_bottom_docked_and_cockpit_is_top_centered():
    assert ".biggy-argus-reactor{" in BRAND_CSS
    assert "bottom:calc(100% - 8px)" in BRAND_CSS
    assert ".biggy-cockpit-strip{" in BRAND_CSS
    assert "left:50%;top:20px" in BRAND_CSS
    assert "reactorDock.appendChild(modelStatus)" in BRAND
    assert "composer.appendChild(reactorDock)" in BRAND


def test_reactor_model_badge_remains_single_line_after_bottom_dock_move():
    chip_rule = BRAND_CSS[BRAND_CSS.index("#j-brain-chip{"):BRAND_CSS.index("#j-orb svg")]
    assert "white-space:nowrap" in chip_rule
    assert "text-overflow:ellipsis" in chip_rule
    status_rule = BRAND_CSS[BRAND_CSS.index(".biggy-brand-status{"):BRAND_CSS.index(".biggy-brand-meta{")]
    assert "width:max-content" in status_rule


def test_rag_button_toggles_panel_and_conversation_origin():
    cockpit = BRAND[BRAND.index("function installCockpitStrip"):BRAND.index("function forceChromeLabels")]
    assert "biggyCockpitRag" in cockpit
    assert "setArgusRagPanelVisible" in cockpit
    assert "aria-pressed" in BRAND
    assert "ARGUS_RAG_PANEL_STORAGE_KEY" in BRAND
    assert ".biggy-argus-rag-overview[hidden]{display:none}" in BRAND_CSS
    assert ".biggy-rag-panel-off .biggy-argus-conversation-lane{top:28px}" in BRAND_CSS


def test_half_width_prompt_is_centered_on_the_shared_cockpit_axis():
    assert "padding-left:84px;padding-right:84px" in BRAND_CSS
    assert "#mainChat.biggy-brand-iwo #composerBox{width:50%;max-width:900px;margin-left:auto;margin-right:auto}" in BRAND_CSS
    assert "function syncBiggySharedCenterline()" in BRAND
    assert "const masterX = promptRect.left + (promptRect.width / 2)" in BRAND
    assert "placeOnMaster(document.getElementById('biggyCockpitStrip'))" in BRAND
    assert "placeOnMaster(document.getElementById('biggyFleetStrip'))" in BRAND
    assert "placeOnMaster(document.getElementById('biggyArgusReactor'))" in BRAND
    assert "biggy-home-centerline-sync" in BRAND


def test_conversation_lane_clears_full_width_composer_overlay():
    """Dialog stack must stop above the full-width bottom overlay, not the half-width prompt."""
    boundary = BRAND[BRAND.index("function syncArgusConversationLaneBoundary"):BRAND.index("function argusConversationText")]
    assert "document.getElementById('composerWrap')" in boundary
    assert "document.getElementById('composerBox')" not in boundary
    assert "overlapsLane" not in boundary
    assert "hostRect.bottom - overlayRect.top" in boundary
    assert "Math.max(132," in boundary
    assert "scheduleArgusConversationLaneBoundary" in BRAND
    assert "scheduleArgusConversationLaneBoundary()" in BRAND
    # Usable bottom follows overlay across viewport sizes; top positions stay RAG-gated.
    assert ".biggy-rag-panel-off .biggy-argus-conversation-lane{top:28px}" in BRAND_CSS
    assert "bottom:var(--biggy-conversation-bottom,176px)" in BRAND_CSS
    assert "overflow:auto" in BRAND_CSS[BRAND_CSS.index(".biggy-argus-conversation-turns{"):BRAND_CSS.index(".biggy-argus-dialog{")]


def test_conversation_lane_keeps_complete_assistant_text():
    renderer = BRAND[BRAND.index("function renderArgusConversationLane"):BRAND.index("function installArgusConversationLane")]
    assert "text: text.slice(0, 1400)" not in renderer
    assert "result.push({ identity, pending, text, index })" in renderer


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


def test_argus_response_label_observer_is_idempotent():
    """Response branding must not trigger its own MutationObserver forever."""
    labels = BRAND[BRAND.index("function labelArgusResponses"):BRAND.index("function removeCaduceus")]
    assert "name && name.textContent !== 'A.R.G.U.S.'" in labels
    assert "icon && icon.textContent !== 'A'" in labels
    assert "turn.dataset.responseAgent !== 'argus'" in labels
    assert "if (name) name.textContent = 'A.R.G.U.S.'" not in labels
