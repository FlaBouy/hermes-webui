"""Regression: the approved graphical-layer POC replaces only Orb artwork."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRAND = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
BRAND_CSS = (ROOT / "static" / "biggy-brand.css").read_text(encoding="utf-8")
POC = (ROOT / "static" / "argus-orb-graphic-layer.html").read_text(encoding="utf-8")


def _reactor_markup() -> str:
    return BRAND[BRAND.index("function makeReactorDock"):BRAND.index("function installSmedleyButton")]


def test_new_graphical_layer_is_the_live_orb_artwork():
    markup = _reactor_markup()
    assert 'id="j-orb"' in markup
    assert 'id="j-orb-frame"' in markup
    assert 'src="/static/argus-orb-graphic-layer.html"' in markup
    assert 'data-testid="biggy-argus-orb-poc"' in markup
    assert '<svg viewBox="0 0 200 200"' not in markup


def test_masking_is_circular_and_limited_to_orb_and_menu_plates():
    assert 'id="orb-freeze-mask"' not in POC
    assert '<rect width="1200" height="800"' not in POC
    assert "html, body { width: 100%; height: 100%; margin: 0; overflow: hidden; background: transparent; }" in POC
    assert "#j-orb-menu" in BRAND_CSS
    assert ".biggy-orb-menu-tab" in BRAND_CSS


def test_existing_model_and_state_indicator_remain_beneath_graphic():
    markup = _reactor_markup()
    assert markup.index('id="j-orb-frame"') < markup.index('id="j-state-panel"')
    assert markup.index('id="j-argus-name"') < markup.index('id="j-state-panel"')
    assert 'data-testid="biggy-argus-name">A.R.G.U.S.</div>' in markup
    assert 'id="j-brain-chip"' in markup
    assert 'id="j-state-txt"' in markup
    panel = BRAND_CSS[BRAND_CSS.index("#j-state-panel{"):BRAND_CSS.index("#j-state{")]
    assert "bottom:0" in panel
    assert "width:224px" in panel
    orb_css = BRAND_CSS[BRAND_CSS.index("#j-orb{"):BRAND_CSS.index("#j-orb-frame{")]
    assert "top:12px" in orb_css
    assert "left:calc(50% + 6px)" in BRAND_CSS
    assert "transform:translateX(6px)" in BRAND_CSS
    assert "const masterX = axisRect.left + (axisRect.width / 2) - 6;" in BRAND


def test_poc_module_placements_are_present_but_inert():
    for label in ("CHAT", "TASKS", "KANBAN", "SKILLS", "MEMORY", "SPACES", "PROFILES", "TODOS", "INSIGHTS", "LOGS", "SETTINGS", "TOOLS"):
        assert f"['{label}'," in POC
    assert "aria-disabled': 'true'" in POC
    assert "href:" not in POC
    assert "activateModule" not in POC
    module_block = POC[POC.index("modules.forEach"):POC.index("const STATE_CLASS")]
    assert "addEventListener" not in module_block
    assert "#j-orb-frame" in BRAND_CSS
    assert 'id="j-orb-menu"' in _reactor_markup()
    assert "syncArgusOrbMenuFromHermes" in BRAND
    assert "clone.querySelector('.biggy-fleet-state')?.remove()" in BRAND


def test_orb_menu_reuses_hidden_hermes_controls_as_function_owners():
    assert "strip.classList.add('biggy-hermes-orb-source');" in BRAND
    assert ".biggy-hermes-strip.biggy-hermes-orb-source{visibility:hidden;pointer-events:none}" in BRAND_CSS
    assert "pointer-events:auto;cursor:pointer" in BRAND_CSS
    assert "source.click();" in BRAND
    assert "window.setTimeout(syncArgusOrbMenuFromHermes, 0);" in BRAND
    assert "window.setTimeout(syncArgusOrbMenuFromHermes, 160);" in BRAND
    assert "padding:10px 84px 12px" in BRAND_CSS


def test_biggy_active_buttons_share_the_green_active_language():
    assert '#mainChat.biggy-brand-iwo button.active:not(:disabled)' in BRAND_CSS
    assert '#mainChat.biggy-brand-iwo button.is-active:not(:disabled)' in BRAND_CSS
    assert 'button[aria-pressed="true"]:not(:disabled)' in BRAND_CSS
    assert 'button[aria-expanded="true"]:not(:disabled)' in BRAND_CSS
    assert 'color:#75f0b5!important' in BRAND_CSS


def test_active_orb_button_drives_its_white_inference_line():
    assert "'data-module': name" in POC
    assert "biggy-argus-orb-menu-state" in BRAND
    assert "biggy-argus-orb-menu-state" in POC
    assert "stroke: #fff; stroke-width: 3; opacity: 1" in POC
    assert "index === 0 ? ' active'" not in POC


def test_host_retains_state_and_speech_pulse_ownership():
    assert "biggy-argus-orb-state" in BRAND
    assert "biggy-argus-orb-beat" in BRAND
    assert "event.origin !== window.location.origin" in POC
    assert "--speech-beat" in POC
    assert "speech-reactive" in POC


def test_poc_uses_exact_transparent_psd_element_instead_of_a_redraw():
    assert 'id="argus-orb-template"' in POC
    assert 'href="/static/argus-orb-template.png"' in POC
    assert 'x="238.5" y="159" width="723" height="482"' in POC
    assert '<g id="orb-visual">' in POC
    for removed_layer in (
        "hud-arc-frame",
        "hud-data-bars-right",
        "hud-inner-mechanics",
        "hud-aperture",
    ):
        assert removed_layer not in POC
    assert 'id="ring-outer-counterclockwise"' not in POC
    assert 'id="ring-data-counterclockwise"' not in POC
    assert 'id="ring-scan-sweep"' not in POC
    assert 'id="generated"' not in POC
    assert "const ticks" not in POC
    assert "const nodes" not in POC
    assert "const targets" not in POC


def test_orb_has_circular_profile_mask_and_requested_motion_layers():
    assert 'id="argus-profile-mask" cx="596" cy="404" r="252"' in POC
    assert 'id="argus-inner-solid-ring" class="inner-solid-cw"' in POC
    assert ".inner-solid-cw { transform-box:view-box; transform-origin:596px 404px;" in POC
    assert 'r="91" stroke-width="2.5"' in POC
    assert 'id="argus-inner-dashed-ring" class="inner-dashed-ccw"' in POC
    assert ".inner-dashed-ccw { animation:dashCcw 14s linear infinite; }" in POC
    assert "@keyframes dashCcw { to { stroke-dashoffset: 190; } }" in POC
    assert 'r="112" pathLength="703" stroke-width="2.5" stroke-dasharray="11 8"' in POC
    assert POC.index('id="orb-visual"') < POC.index('id="menu-layer"')
    assert "const cx = 596, cy = 404;" in POC
    assert "const edgeRadius = 270;" in POC
    assert "const targetX = cx + (edgeDx / edgeLength) * edgeRadius;" in POC
    assert 'id="argus-lit-ring-pulse" class="synchronized-light ring-speech-reactive"' in POC
    assert 'id="argus-red-core-pulse" class="core-pulse"' in POC
    assert "Math.min(2, Number(event.data.beat)" in POC
    assert 'id="argus-outer-edge-pulse" class="synchronized-light"' in POC
    assert 'mask="url(#outerEdgeLights)"' in POC


def test_orb_center_pulses_red_while_surrounding_lighting_stays_blue():
    assert '<radialGradient id="sensorCore"><stop stop-color="#fff4f1"/>' in POC
    assert '.core-pulse { transform-box:view-box; transform-origin:596px 404px; animation:corePulse 5.6s ease-in-out infinite; }' in POC
    assert 'id="argus-red-core-pulse" class="core-pulse"' in POC
    assert 'r="65" fill="none" stroke="#7f1014"' in POC
    assert 'r="59" fill="none" stroke="#d92f2b"' in POC
    assert 'r="53" fill="#b91f20"' in POC
    assert 'r="41" fill="url(#sensorCore)"' in POC
    assert '.synchronized-light { animation:synchronizedLight 5.6s ease-in-out infinite; }' in POC
    assert 'id="argus-lit-ring-pulse"' in POC
    assert 'stroke="#42dcff"' in POC
    assert 'id="argus-outer-edge-pulse" class="synchronized-light"' in POC


def test_orb_scales_independently_from_rail_sized_menu_plates():
    assert '<g id="orb-visual">' in POC
    assert "const y = 250 + row * 60;" in POC
    assert "const inwardIndex = [40, 20, 0, 0, 20, 40][row];" in POC
    assert "const nodeX = side === 'left' ? 250 + inwardIndex : 950 - inwardIndex;" in POC
    assert "const uniformWidth = Math.max(0, ...sources.map" in BRAND
    assert "clone.style.minWidth = `${uniformWidth}px`;" in BRAND
    assert "clone.classList.add(index < 6 ? 'biggy-orb-menu-left' : 'biggy-orb-menu-right');" in BRAND
    assert "const inwardIndex = [40, 20, 0, 0, 20, 40][row];" in BRAND
    assert "const nodeX = index < 6 ? 250 + inwardIndex : 950 - inwardIndex;" in BRAND
    assert "clone.style.left = `${(nodeX / 1200) * 100}%`;" in BRAND
    assert "translate(calc(-100% - 8px),-50%)" in BRAND_CSS
    assert "translate(8px,-50%)" in BRAND_CSS
    assert "clone.style.top = `${26.5625 + row * 9.375}%`;" in BRAND
    assert "class: 'menu-card'" not in POC
    assert "class: 'menu-label'" not in POC
    assert "cloneNode(true)" in BRAND
