from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import api.biggy_fleet as fleet


ROOT = Path(__file__).resolve().parents[1]
BIGGY_JS = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
BIGGY_CSS = (ROOT / "static" / "biggy-brand.css").read_text(encoding="utf-8")
ROUTES = (ROOT / "api" / "routes.py").read_text(encoding="utf-8")


def _write_status(root: Path, machine: str, state: str, when: float) -> None:
    stamp = datetime.fromtimestamp(when, timezone.utc).isoformat()
    (root / f"{machine}-worker-status.json").write_text(
        json.dumps({"state": state, "updated_at": stamp}),
        encoding="utf-8",
    )


def test_fleet_contract_includes_desktops_smedley_and_plato(monkeypatch, tmp_path):
    now = 1_787_496_000.0
    for machine in ("THUNDERDOME", "HAL9000", "PROMETHEUS"):
        _write_status(tmp_path, machine, "idle", now - 20)
    monkeypatch.setattr(fleet, "_REGISTRY_ROOT", tmp_path)
    monkeypatch.setattr(fleet.time, "time", lambda: now)
    monkeypatch.setattr(fleet, "_tcp_online", lambda host, ports: True)

    payload = fleet.fleet_status()
    by_id = {item["id"]: item for item in payload["machines"]}
    assert set(by_id) == {"SMEDLEY", "THUNDERDOME", "HAL9000", "PROMETHEUS", "PLATO"}
    assert by_id["SMEDLEY"]["kind"] == "hermes"
    assert by_id["SMEDLEY"]["launch_url"] == "http://192.168.0.15:8787/"
    assert by_id["THUNDERDOME"]["launch_url"].startswith("rdp://")
    assert by_id["PLATO"]["kind"] == "web"
    assert by_id["PLATO"]["launch_url"] == "https://192.168.0.25/"
    assert all(by_id[machine]["state"] == "online" for machine in by_id)


def test_fleet_status_distinguishes_busy_error_and_stale(monkeypatch, tmp_path):
    now = 1_787_496_000.0
    _write_status(tmp_path, "THUNDERDOME", "running", now - 10)
    _write_status(tmp_path, "HAL9000", "failed", now - 10)
    _write_status(tmp_path, "PROMETHEUS", "idle", now - 500)
    monkeypatch.setattr(fleet, "_REGISTRY_ROOT", tmp_path)
    monkeypatch.setattr(fleet.time, "time", lambda: now)
    monkeypatch.setattr(fleet, "_tcp_online", lambda host, ports: host == "192.168.0.25")

    by_id = {item["id"]: item for item in fleet.fleet_status()["machines"]}
    assert by_id["THUNDERDOME"]["state"] == "busy"
    assert by_id["HAL9000"]["state"] == "error"
    assert by_id["PROMETHEUS"]["state"] == "offline"
    assert by_id["PLATO"]["state"] == "online"


def test_fleet_strip_is_top_rail_anchored_and_routes_are_same_origin():
    assert "const FLEET_STATUS_PATH = '/api/biggy/fleet/status'" in BIGGY_JS
    assert "function ensureTopRailGroup()" in BIGGY_JS
    assert "group.appendChild(strip)" in BIGGY_JS
    assert ".biggy-top-rail-group{" in BIGGY_CSS
    assert "position:absolute;left:50%;top:20px" in BIGGY_CSS
    assert "launchFleetMachine(machine)" in BIGGY_JS
    assert "openSmedleyGui();" in BIGGY_JS
    assert "resetBiggyWorkspace();" in BIGGY_JS
    assert "<span>HOME</span>" in BIGGY_JS
    assert "Reset galaxy and clear PA cards" in BIGGY_JS
    assert 'parsed.path == "/api/biggy/fleet/status"' in ROUTES
