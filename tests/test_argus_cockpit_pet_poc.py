from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POC_JS = (ROOT / "static" / "argus-cockpit-pet-poc.js").read_text(encoding="utf-8")
POC_HTML = (ROOT / "static" / "argus-cockpit-pet-poc.html").read_text(encoding="utf-8")
PRODUCTION = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")


def test_cockpit_pet_poc_is_not_loaded_by_production():
    assert "argus-cockpit-pet-poc" not in PRODUCTION
    assert '<argus-cockpit-pet' in POC_HTML
    assert "no production wiring" in POC_HTML.lower()


def test_cockpit_pet_exposes_future_rewire_contract():
    assert "customElements.define('argus-cockpit-pet'" in POC_JS
    assert "argus-cockpit-action" in POC_JS
    assert "setActiveActions(actions = [])" in POC_JS
    assert "['model', 'status', 'tracking']" in POC_JS
    assert 'data-state="idle"' in POC_JS
    assert "['THINKING', 'SPEAKING', 'WORKING', 'SUCCESS', 'WARNING', 'ERROR']" in POC_JS


def test_eye_tracking_is_bounded_and_centerable():
    assert "* 11 * strength" in POC_JS
    assert "* 8 * strength" in POC_JS
    assert "centerEye()" in POC_JS
    assert "this._eyeNode.style.translate" in POC_JS
    assert "document.addEventListener('pointermove'" in POC_JS
    assert 'clipPath id="eyeAperture"' in POC_JS
    assert '<ellipse cx="596" cy="404" rx="13" ry="24"' in POC_JS


def test_existing_orb_artwork_and_complete_menu_are_reused():
    assert "/static/argus-orb-template.png" in POC_JS
    for label in ("CHAT", "TASKS", "KANBAN", "SKILLS", "MEMORY", "SPACES", "PROFILES", "TODOS", "INSIGHTS", "LOGS", "SETTINGS", "TOOLS"):
        assert f"'{label}'" in POC_JS


def test_state_motion_and_menu_feedback_are_bounded():
    assert '@keyframes cw' in POC_JS
    assert '@keyframes ccw' in POC_JS
    assert '@keyframes speechEye' in POC_JS
    assert '@keyframes tieFlow' in POC_JS
    assert '@keyframes confirmSweep' in POC_JS
    assert '@keyframes successPath' in POC_JS
    assert 'animation:stepCw 4.8s steps(12,end) infinite' in POC_JS
    assert '.tie.active' in POC_JS
    assert '.node.active' in POC_JS
    assert 'paintActionClass(actionId' in POC_JS
    assert 'prefers-reduced-motion:reduce' in POC_JS
    assert 'data-state="thinking"' in POC_HTML
    assert 'data-state="speaking"' in POC_HTML
    for state in ('working', 'success', 'warning', 'error'):
        assert f'data-state="{state}"' in POC_HTML
