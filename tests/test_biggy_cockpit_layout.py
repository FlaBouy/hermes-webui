"""Static contracts for the A.R.G.U.S. Cockpit and Fleet rail layout."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRAND = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
BRAND_CSS = (ROOT / "static" / "biggy-brand.css").read_text(encoding="utf-8")


def test_cockpit_owns_home_sync_filter_ptt_and_room_in_order():
    cockpit = BRAND[BRAND.index("function installCockpitStrip"):BRAND.index("function forceChromeLabels")]
    assert cockpit.index("makeHomeControl()") < cockpit.index("makeSpeechSyncControl()")
    assert cockpit.index("<span>FILTER</span>") < cockpit.index("controls.querySelector('#biggyPtt')")
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
    assert ".biggy-jarvis-transplant{" in BRAND_CSS
    assert "bottom:calc(100% - 8px)" in BRAND_CSS
    assert ".biggy-cockpit-strip{" in BRAND_CSS
    assert "left:50%;top:20px" in BRAND_CSS
    assert "reactorDock.appendChild(modelStatus)" in BRAND
    assert "composer.appendChild(reactorDock)" in BRAND
