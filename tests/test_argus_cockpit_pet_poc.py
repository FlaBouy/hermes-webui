from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
POC_JS = (ROOT / "static" / "argus-cockpit-pet-poc.js").read_text(encoding="utf-8")
POC_HTML = (ROOT / "static" / "argus-cockpit-pet-poc.html").read_text(encoding="utf-8")
PRODUCTION = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")


def test_cockpit_pet_poc_is_not_loaded_by_production():
    assert "argus-cockpit-pet-poc" not in PRODUCTION
    assert '<argus-cockpit-pet' in POC_HTML
    assert "no production wiring" in POC_HTML.lower()
    assert '<title>A.R.G.U.S. Cockpit Orb POC</title>' in POC_HTML
    assert 'Isolated cockpit-orb proof of concept' in POC_HTML


def test_cockpit_pet_exposes_future_rewire_contract():
    assert "customElements.define('argus-cockpit-pet'" in POC_JS
    assert "argus-cockpit-action" in POC_JS
    assert "setActiveActions(actions = [])" in POC_JS
    assert "['label', 'model', 'size', 'status', 'tracking']" in POC_JS
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
    assert "new URL('argus-orb-template.png'" in POC_JS
    assert '/static/argus-orb-template.png' not in POC_JS
    for label in ("CHAT", "TASKS", "KANBAN", "SKILLS", "MEMORY", "SPACES", "PROFILES", "TODOS", "INSIGHTS", "LOGS", "SETTINGS", "TOOLS"):
        assert f"'{label}'" in POC_JS


def test_orb_label_is_editable_and_persistent():
    assert "this.getAttribute('label')" in POC_JS
    assert ".slice(0, 20)" in POC_JS
    assert 'id="orb-name"' in POC_HTML
    assert "label.trim() ? localStorage.setItem(nameKey, label)" in POC_HTML
    assert "pet.setAttribute('label', label)" in POC_HTML
    assert 'src="./argus-cockpit-pet-poc.js?v=' in POC_HTML


def test_whole_entity_resizes_with_proportional_menu_graphics():
    assert "this.getAttribute('size')" in POC_JS
    assert "Math.min(140, Math.max(60" in POC_JS
    assert "this.style.setProperty('--pet-width'" in POC_JS
    assert 'container-type:inline-size' in POC_JS
    assert 'width:11.667cqw' in POC_JS
    assert 'height:3.75cqw' in POC_JS
    assert 'font:800 1.389cqw/1' in POC_JS
    assert 'box-shadow:0 0 1.389cqw' in POC_JS
    assert '.name{position:absolute;left:calc(50% + .94cqw)' in POC_JS
    assert 'id="orb-scale"' in POC_HTML
    assert 'id="move-orb"' in POC_HTML
    assert "localStorage.setItem(layoutKey, JSON.stringify(layout))" in POC_HTML
    assert "moveOrb.setPointerCapture(event.pointerId)" in POC_HTML


def test_menu_state_choreography_is_bounded_and_accessible():
    assert '@keyframes energyToButton' in POC_JS
    assert 'animation:energyToButton 1.15s ease-in-out infinite' in POC_JS
    assert '@keyframes selectedPathPulse' in POC_JS
    assert '@keyframes selectedNodePulse' in POC_JS
    assert '.tie.active{stroke:#fff;stroke-width:2.7;stroke-dasharray:none' in POC_JS
    assert '@keyframes activeButton' in POC_JS
    assert '@keyframes workingButton' in POC_JS
    assert '@keyframes successButton' in POC_JS
    assert '@keyframes warningButton' in POC_JS
    assert '@keyframes errorButton' in POC_JS
    assert '@keyframes pathRetract' in POC_JS
    assert "signalTrail.setAttribute('pathLength', 100)" in POC_JS
    assert "signalHead.setAttribute('pathLength', 100)" in POC_JS
    assert "path.setAttribute('class', 'tie'); path.dataset.action = actionId;\n" in POC_JS
    assert "const connectorX = x + (side === 'left' ? 78 : -78)" in POC_JS
    assert 'const leftX = 100 + inward' in POC_JS
    assert "const x = side === 'left' ? leftX : 1192 - leftX" in POC_JS
    assert 'const outerRadius = 250' in POC_JS
    assert 'const bendX = edgeX + (connectorX - edgeX) * 0.5' in POC_JS
    assert 'ties.append(path, signalTrail, signalHead, node)' in POC_JS
    assert "this.paintActionClass(action, 'selecting', true)" in POC_JS
    assert "this.paintActionClass(action, 'deactivating', true)" in POC_JS
    assert 'this._deactivateTimers.clear()' in POC_JS
    assert '.entity[data-state="warning"] button.active' in POC_JS
    assert '.entity[data-state="error"] button.active' in POC_JS
    assert '@media(prefers-reduced-motion:reduce)' in POC_JS


def test_shareable_package_contains_only_portable_review_files(tmp_path):
    output = tmp_path / "cockpit-pet.zip"
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "package_argus_cockpit_pet_poc.py"), "--output", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    with ZipFile(output) as archive:
        assert set(archive.namelist()) == {
            "argus-cockpit-pet-poc/argus-cockpit-pet-poc.html",
            "argus-cockpit-pet-poc/argus-cockpit-pet-poc.js",
            "argus-cockpit-pet-poc/argus-orb-template.png",
            "argus-cockpit-pet-poc/README.md",
            "argus-cockpit-pet-poc/FEEDBACK.md",
        }


def test_state_motion_and_menu_feedback_are_bounded():
    assert '@keyframes cw' in POC_JS
    assert '@keyframes ccw' in POC_JS
    assert '@keyframes speechEye' in POC_JS
    assert '@keyframes energyToButton' in POC_JS
    assert '@keyframes confirmSweep' in POC_JS
    assert '@keyframes selectedPathPulse' in POC_JS
    assert '@keyframes warningRing' in POC_JS
    assert '@keyframes errorRing' in POC_JS
    assert 'animation:warningRing 1.8s ease-in-out infinite' in POC_JS
    assert 'animation:errorRing .72s ease-in-out infinite' in POC_JS
    assert 'animation:stepCw 4.8s steps(12,end) infinite' in POC_JS
    assert '.tie.active' in POC_JS
    assert '.node.active' in POC_JS
    assert 'paintActionClass(actionId' in POC_JS
    assert 'prefers-reduced-motion:reduce' in POC_JS
    assert 'data-state="thinking"' in POC_HTML
    assert 'data-state="speaking"' in POC_HTML
    for state in ('working', 'success', 'warning', 'error'):
        assert f'data-state="{state}"' in POC_HTML
