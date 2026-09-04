"""Regression contracts for the accepted, production-mounted A.R.G.U.S. Object."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRAND = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
BRAND_CSS = (ROOT / "static" / "biggy-brand.css").read_text(encoding="utf-8")
OBJECT = (ROOT / "static" / "argus-cockpit-pet-poc.js").read_text(encoding="utf-8")
MANAGER = (ROOT / "static" / "biggy-pets.js").read_text(encoding="utf-8")


def _reactor_markup() -> str:
    return BRAND[BRAND.index("function makeReactorDock"):BRAND.index("function installSmedleyButton")]


def test_accepted_object_is_live_without_legacy_iframe_or_cloned_menu():
    markup = _reactor_markup()
    assert '<argus-cockpit-pet id="j-orb"' in markup
    assert 'data-testid="biggy-argus-orb-object"' in markup
    assert 'id="j-orb-frame"' not in markup
    assert 'id="j-orb-menu"' not in markup
    assert "cloneNode(true)" not in markup
    assert "argus-orb-graphic-layer.html" not in markup


def test_object_masks_the_world_behind_orb_but_not_its_controls():
    assert '.profile{fill:#01060b;opacity:.99}' in OBJECT
    assert '<circle class="profile" cx="596" cy="404" r="252" fill="url(#mask)"/>' in OBJECT
    assert '.menu-button{position:absolute' in OBJECT
    assert '#j-orb-menu' not in BRAND_CSS
    assert '.biggy-orb-menu-tab' not in BRAND_CSS


def test_label_model_and_online_indicator_are_inside_object():
    assert '<div class="name">A.R.G.U.S.</div>' in OBJECT
    assert '<div class="readout"><span class="model"></span><span class="state"></span></div>' in OBJECT
    assert "this.shadowRoot.querySelector('.name').textContent = label" in OBJECT
    assert "this.shadowRoot.querySelector('.model').textContent = `◆ ${model}`" in OBJECT
    assert "this.shadowRoot.querySelector('.state').textContent = status" in OBJECT
    assert "orb.setAttribute('model', short || '—')" in BRAND
    assert "orb.setAttribute('status', next === 'tool-running' ? 'TOOL RUNNING' : next)" in BRAND


def test_complete_menu_is_interactive_and_hidden_controls_remain_owners():
    for label in ("CHAT", "TASKS", "KANBAN", "SKILLS", "MEMORY", "SPACES", "PROFILES", "TODOS", "INSIGHTS", "LOGS", "SETTINGS", "TOOLS"):
        assert f"'{label}'" in OBJECT
    assert "argus-cockpit-action" in OBJECT
    assert "orb.addEventListener('argus-cockpit-action'" in BRAND
    assert "owner.click()" in BRAND
    assert "orb.setActiveActions(active)" in BRAND
    assert "strip.classList.add('biggy-hermes-orb-source');" in BRAND
    assert ".biggy-hermes-strip.biggy-hermes-orb-source{visibility:hidden;pointer-events:none}" in BRAND_CSS


def test_selected_button_uses_solid_white_live_connection():
    assert '.tie.active{stroke:#fff;stroke-width:2.7;stroke-dasharray:none' in OBJECT
    assert '@keyframes selectedPathPulse' in OBJECT
    assert '@keyframes energyToButton' in OBJECT
    assert 'animation:energyToButton 1.15s ease-in-out infinite' in OBJECT
    assert "this.paintActionClass(action, 'selecting', true)" in OBJECT


def test_host_owns_state_model_and_speech_pulse_without_cross_frame_messages():
    assert "orb.setAttribute('status', next === 'tool-running' ? 'TOOL RUNNING' : next)" in BRAND
    assert "orb.setAttribute('model', short || '—')" in BRAND
    assert "orb.setAttribute('beat', String(level))" in BRAND
    assert "orb.setAttribute('beat', '0')" in BRAND
    assert "postMessage" not in _reactor_markup()
    assert "this.getAttribute('beat')" in OBJECT
    assert "--speech-scale" in OBJECT
    assert "--speech-brightness" in OBJECT


def test_orb_is_protected_always_mounted_object_in_ani():
    assert "const ORB_OBJECT_ID='__argus_orb__'" in MANAGER
    assert "'A.R.G.U.S. Orb — always on'" in MANAGER
    assert "toggle.textContent='Always on'" in MANAGER
    assert "toggle.disabled=true" in MANAGER
    assert "removeButton.disabled=true" in MANAGER
    assert "resetPosition.textContent='Center Orb'" in MANAGER
    assert "state.instances.forEach(item=>{item.enabled=false;})" in MANAGER


def test_whole_object_scales_as_one_entity_and_prompt_stays_independent():
    assert "--argus-object-width" in MANAGER
    assert "clampOrbSize" in MANAGER
    assert "width:min(var(--argus-object-width,560px),calc(100vw - 136px))" in BRAND_CSS
    assert "aspect-ratio:1200/720" in BRAND_CSS
    assert "this.style.setProperty('--pet-width'" in OBJECT
    assert "composer.appendChild(reactorDock)" in BRAND
    assert "padding:10px 84px 12px" in BRAND_CSS


def test_eye_and_lighting_keep_red_center_and_blue_outer_language():
    assert '<radialGradient id="iris" cx="38%" cy="34%"><stop stop-color="#ffb1a3"/>' in OBJECT
    assert '.eye{transform-box:view-box' in OBJECT
    assert 'clipPath id="eyeAperture"' in OBJECT
    assert 'stroke="#42dcff" stroke-width="8"' in OBJECT
    assert '@keyframes warningRing' in OBJECT
    assert '@keyframes errorRing' in OBJECT
