import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RESULTS_JS = ROOT / "extensions" / "smedley-engineering" / "smedley-electrical-results.js"
ENGINEERING_JS = ROOT / "extensions" / "smedley-engineering" / "smedley-engineering.v0.2.5.js"
MANIFEST = ROOT / "extensions" / "smedley-engineering" / "manifest.json"
NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _run_model(tool_id, payload):
    script = f"""
const renderer = require({json.dumps(str(RESULTS_JS))});
const model = renderer.resultModel({json.dumps(tool_id)}, {json.dumps(payload)});
process.stdout.write(JSON.stringify(model));
"""
    completed = subprocess.run(
        [NODE, "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _run_html(tool_id, payload):
    script = f"""
const renderer = require({json.dumps(str(RESULTS_JS))});
process.stdout.write(renderer.renderResultCard({json.dumps(tool_id)}, {json.dumps(payload)}));
"""
    completed = subprocess.run(
        [NODE, "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


@requires_node
def test_manifest_loads_shared_result_renderer_before_workspace_script():
    manifest = json.loads(MANIFEST.read_text())
    scripts = manifest["scripts"]
    assert scripts[0] == "voltage-drop-sizing.js"
    assert "smedley-electrical-results.js" in scripts
    assert "smedley-live-tools.v0.2.5.js" in scripts
    assert "smedley-engineering.v0.2.5.js" in scripts
    assert scripts.index("smedley-electrical-results.js") < scripts.index(
        "smedley-engineering.v0.2.5.js"
    )
    assert scripts.index("smedley-live-tools.v0.2.5.js") < scripts.index(
        "smedley-engineering.v0.2.5.js"
    )
    assert "smedley-electrical-results.css" in manifest["stylesheets"]
    engineering = ENGINEERING_JS.read_text()
    assert "SmedleyElectricalResults" in engineering
    assert "renderResultCard" in engineering
    assert "SmedleyLiveTools" in engineering
    assert "liveApi.wire" in engineering
    assert "RECALCULATE" in engineering


@requires_node
def test_voltage_drop_card_surfaces_pass_values_assumptions_and_code_basis():
    payload = {
        "status": "ok",
        "tool": "voltage-drop",
        "inputs": {"conductor_awg": "4", "voltage": 480},
        "result": {
            "voltage_drop_volts": 11.542,
            "voltage_drop_pct": 2.405,
            "receiving_end_voltage": 468.46,
            "pass_fail": "PASS",
        },
        "assumptions": ["Copper conductors — NEC Ch.9 Table 9, 75C"],
        "warnings": [],
        "code_basis": "NEC NFPA 70, 2014 Ed. — Ch.9 Table 9",
        "sources": [],
    }
    model = _run_model("voltage-drop", payload)
    assert model["state"] == "PASS"
    assert "4 AWG" in model["recommendation"]
    displays = {row["label"]: row["display"] for row in model["values"]}
    assert displays["Voltage drop"] == "11.542 V"
    assert displays["Voltage drop percent"] == "2.405 %"
    assert displays["Receiving end voltage"] == "468.46 V"
    assert model["assumptions"] == payload["assumptions"]
    assert model["codeBasis"] == payload["code_basis"]


@requires_node
def test_voltage_drop_auto_sizing_payload_maps_governing_and_parallel_fields():
    payload = {
        "status": "ok",
        "tool": "voltage-drop",
        "inputs": {"recommended_size": "1/0", "voltage": 480},
        "result": {
            "conductor_awg": "1/0",
            "recommended_size": "1/0",
            "minimum_ampacity_size": "1/0",
            "minimum_voltage_drop_size": "1/0",
            "parallel_minimum_awg": "1/0",
            "governing_constraint": "ampacity",
            "governing_explanation": (
                "Ampacity/code size 1/0 AWG governs over voltage-drop minimum 1/0 AWG."
            ),
            "voltage_drop_volts": 7.2,
            "voltage_drop_pct": 1.5,
            "receiving_end_voltage": 472.8,
            "threshold_pct": 3,
            "design_amps": 125,
            "pass_fail": "PASS",
        },
        "assumptions": ["Automatic conductor sizing applied."],
        "warnings": [],
        "code_basis": "NEC NFPA 70, 2014 Ed. -- Table 310.16 | Ch.9 Table 9",
    }
    model = _run_model("voltage-drop", payload)
    assert model["state"] == "PASS"
    assert "1/0 AWG" in model["recommendation"]
    displays = {row["label"]: row["display"] for row in model["values"]}
    assert displays["Recommended conductor"] == "1/0 AWG"
    assert displays["Minimum ampacity size"] == "1/0 AWG"
    assert displays["Minimum voltage-drop size"] == "1/0 AWG"
    assert displays["Governing constraint"] == "ampacity"
    assert "Ampacity/code size 1/0 AWG governs" in displays["Governing explanation"]
    assert displays["Parallel minimum"] == "1/0 AWG"
    assert displays["Voltage drop"] == "7.2 V"
    assert displays["Voltage drop percent"] == "1.5 %"
    assert displays["Threshold"] == "3 %"


@requires_node
def test_voltage_drop_comparison_card_shows_trial_and_baseline_with_fail_state():
    payload = {
        "status": "ok",
        "tool": "voltage-drop",
        "result": {
            "comparison_size": "8",
            "baseline_recommended_size": "6",
            "recommended_size": "6",
            "minimum_ampacity_size": "6",
            "minimum_voltage_drop_size": "8",
            "ampacity_pass_fail": "FAIL",
            "voltage_drop_pass_fail": "PASS",
            "pass_fail": "FAIL",
            "voltage_drop_pct": 2.1,
        },
        "warnings": ["Trial 8 AWG is below minimum ampacity/code size 6 AWG."],
        "code_basis": "NEC Table 310.16 | Ch.9 Table 9",
    }
    model = _run_model("voltage-drop", payload)
    assert model["state"] == "FAIL"
    assert model["recommendation"] == "8 AWG"
    displays = {row["label"]: row["display"] for row in model["values"]}
    assert displays["Trial conductor"] == "8 AWG"
    assert displays["Baseline recommendation"] == "6 AWG"
    assert displays["Ampacity check"] == "FAIL"
    assert displays["Voltage-drop check"] == "PASS"


@requires_node
def test_each_tool_gets_a_specific_recommendation():
    cases = {
        "feeder-size": ({"conductor_size": "8", "ocpd_size_A": 50}, "8 AWG"),
        "conductor-sets": (
            {"selected_size": "2/0", "solution_found": True, "ocpd_size_A": 200},
            "2/0 AWG",
        ),
        "ocpd-size": ({"ocpd_size_A": 35}, "35 A"),
        "conduit-fill": ({"minimum_trade_size": '1-1/2"', "solution_found": True}, '1-1/2"'),
        "grounding": (
            {"egc": {"size_copper": "8"}, "gec": {"size_copper": "4"}},
            "EGC 8 AWG / GEC 4 AWG",
        ),
        "cable-tray-fill": ({"minimum_standard_width_in": 12, "solution_found": True}, "12 in"),
        "motor-circuit": ({"branch_conductor": "10", "ocpd_size_A": 70}, "10 AWG"),
        "motor-starter": ({"starter_type": "E300 Electronic Overload Relay"}, "E300"),
        "mcc-bucket": ({"total_height_in": 9, "section_spaces_used": 1.5}, "9 in"),
        "vfd-circuit": (
            {
                "input_side": {"input_conductor": "10", "input_ocpd_size_A": 100},
                "output_side": {"output_conductor": "8"},
            },
            "Input 10 AWG / Output 8 AWG",
        ),
    }
    for tool_id, (result, expected) in cases.items():
        model = _run_model(tool_id, {"status": "ok", "result": result})
        assert expected in model["recommendation"], (tool_id, model)


@requires_node
def test_feeder_and_motor_use_vd_pass_fail_not_pass_fail():
    """Live feeder-size / motor-circuit return result.vd_pass_fail (not pass_fail)."""
    feeder_fail = _run_model(
        "feeder-size",
        {
            "status": "ok",
            "result": {
                "conductor_size": "6",
                "voltage_drop_pct": 16.03,
                "vd_pass_fail": "FAIL",
                "vd_threshold_pct": 3.0,
            },
            "warnings": [
                "Voltage drop 16.03% exceeds feeder threshold of 3.0% -- consider /tools/conductor-sets."
            ],
            "code_basis": "NEC NFPA 70, 2014 Ed. -- Table 310.16: ampacity",
        },
    )
    assert feeder_fail["state"] == "FAIL"
    assert "6 AWG" in feeder_fail["recommendation"]

    feeder_pass = _run_model(
        "feeder-size",
        {
            "status": "ok",
            "result": {
                "conductor_size": "6",
                "voltage_drop_pct": 1.603,
                "vd_pass_fail": "PASS",
                "vd_threshold_pct": 3.0,
            },
            "warnings": [],
            "code_basis": "NEC NFPA 70, 2014 Ed. -- Table 310.16: ampacity; Table 250.122: EGC.",
        },
    )
    assert feeder_pass["state"] == "PASS"

    motor_fail = _run_model(
        "motor-circuit",
        {
            "status": "ok",
            "result": {
                "branch_conductor": "8",
                "vd_pass_fail": "FAIL",
                "voltage_drop_pct": 5.2,
            },
            "warnings": ["Voltage drop exceeds motor branch threshold."],
            "code_basis": "NEC 430.22; Ch.9 Table 9",
        },
    )
    assert motor_fail["state"] == "FAIL"


@requires_node
def test_vfd_circuit_uses_nested_output_side_vd_pass_fail():
    """Live vfd-circuit returns result.output_side.vd_pass_fail."""
    fail = _run_model(
        "vfd-circuit",
        {
            "status": "ok",
            "result": {
                "input_side": {"input_conductor": "8", "input_ocpd_size_A": 100},
                "output_side": {
                    "output_conductor": "8",
                    "voltage_drop_pct": 4.5,
                    "vd_pass_fail": "FAIL",
                    "vd_threshold_pct": 2.0,
                },
            },
            "warnings": ["Output voltage drop exceeds threshold."],
            "code_basis": "NEC 430.122(A); Ch.9 Table 9",
        },
    )
    assert fail["state"] == "FAIL"
    assert "Input 8 AWG" in fail["recommendation"]
    assert "Output 8 AWG" in fail["recommendation"]

    # Nested VD PASS proves compliance, but live warnings still force WARN.
    warn = _run_model(
        "vfd-circuit",
        {
            "status": "ok",
            "result": {
                "input_side": {"input_conductor": "8", "input_ocpd_size_A": 100, "egc_size": "8"},
                "output_side": {
                    "output_conductor": "8",
                    "voltage_drop_pct": 1.853,
                    "vd_pass_fail": "PASS",
                    "vd_threshold_pct": 2.0,
                },
            },
            "warnings": [
                "drive_input_fla not provided -- estimated at motor FLA x 1.10 = 37.4A."
            ],
            "code_basis": "NEC NFPA 70, 2014 Ed. -- NEC 430.122(A): VFD conductors at 125%.",
        },
    )
    assert warn["state"] == "WARN"
    assert "Input 8 AWG / Output 8 AWG" == warn["recommendation"]


@requires_node
def test_conduit_fill_check_existing_trade_size_names_checked_size():
    """Check-existing mode returns trade_size + pass_fail (no minimum_trade_size)."""
    model = _run_model(
        "conduit-fill",
        {
            "status": "ok",
            "inputs": {
                "conduit_type": "emt",
                "conductor_size": "12",
                "num_current_carrying": 3,
                "trade_size": "1",
            },
            "result": {
                "trade_size": "1",
                "fill_pct": 6.2,
                "fill_limit_pct": 40,
                "pass_fail": "PASS",
                "egc_size": "12",
            },
            "warnings": [],
            "code_basis": "NEC NFPA 70, 2014 Ed. -- Ch.9 Table 1: fill %",
        },
    )
    assert model["state"] == "PASS"
    assert model["recommendation"] == "1"
    displays = {row["label"]: row["display"] for row in model["values"]}
    assert displays["Checked trade size"] == "1"
    assert displays["Pass / fail"] == "PASS"


@requires_node
def test_grounding_recommendation_covers_egc_gec_and_both_modes():
    egc_only = _run_model(
        "grounding",
        {
            "status": "ok",
            "inputs": {"mode": "egc", "ocpd_amps": 100},
            "result": {
                "egc": {"size_copper": "8", "ocpd_amps": 100.0, "nec_reference": "NEC Table 250.122"}
            },
            "warnings": [],
            "code_basis": "NEC Table 250.122: EGC; Table 250.66: GEC",
        },
    )
    assert "EGC 8 AWG" in egc_only["recommendation"]
    assert "GEC" not in egc_only["recommendation"]

    gec_only = _run_model(
        "grounding",
        {
            "status": "ok",
            "inputs": {"mode": "gec", "service_conductor_size": "3/0"},
            "result": {
                "gec": {
                    "size_copper": "2",
                    "service_conductor": "3/0",
                    "nec_reference": "NEC Table 250.66",
                }
            },
            "warnings": [
                "Verify GEC connection per NEC 250.68 -- must be accessible, not subject to corrosion."
            ],
            "code_basis": "NEC Table 250.122: EGC; Table 250.66: GEC",
        },
    )
    assert "GEC 2 AWG" in gec_only["recommendation"]
    assert "EGC" not in gec_only["recommendation"]

    both = _run_model(
        "grounding",
        {
            "status": "ok",
            "inputs": {"mode": "both", "ocpd_amps": 100, "service_conductor_size": "3/0"},
            "result": {
                "egc": {"size_copper": "8", "ocpd_amps": 100.0},
                "gec": {"size_copper": "2", "service_conductor": "3/0"},
            },
            "warnings": [],
            "code_basis": "NEC Table 250.122: EGC; Table 250.66: GEC",
        },
    )
    assert both["recommendation"] == "EGC 8 AWG / GEC 2 AWG"


@requires_node
def test_warning_and_failure_states_fail_closed():
    warning = _run_model(
        "ocpd-size",
        {"status": "ok", "result": {"ocpd_size_A": 35}, "warnings": ["Verify terminal rating"]},
    )
    assert warning["state"] == "WARN"
    assert warning["warnings"] == ["Verify terminal rating"]

    failed = _run_model(
        "conduit-fill",
        {"status": "ok", "result": {"solution_found": False}, "warnings": []},
    )
    assert failed["state"] == "FAIL"

    no_compliance_proof = _run_model(
        "ocpd-size",
        {"status": "ok", "result": {"ocpd_size_A": 35}, "warnings": []},
    )
    assert no_compliance_proof["state"] == "WARN"
    assert any("does not establish compliance" in item for item in no_compliance_proof["warnings"])

    pass_with_warnings = _run_model(
        "motor-circuit",
        {
            "status": "ok",
            "result": {"branch_conductor": "8", "pass_fail": "PASS"},
            "warnings": ["Provide nameplate FLA"],
        },
    )
    assert pass_with_warnings["state"] == "WARN"


@requires_node
def test_card_escapes_content_and_keeps_raw_json_in_closed_technical_details():
    payload = {
        "status": "ok",
        "result": {"ocpd_size_A": 35},
        "warnings": ["<img src=x onerror=alert(1)>"],
        "assumptions": ["Field conditions verified"],
        "code_basis": "NEC <script>alert(1)</script>",
    }
    html = _run_html("ocpd-size", payload)
    assert "smedley-result-card" in html
    assert "Technical Details" in html
    assert '<details class="smedley-result-technical">' in html
    assert '<details class="smedley-result-technical" open' not in html
    assert "<img src=x" not in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


@requires_node
def test_error_card_is_actionable_and_never_reports_pass():
    model = _run_model(
        "feeder-size",
        {"status": "error", "error": "amps is required", "field": "amps"},
    )
    assert model["state"] == "FAIL"
    assert model["recommendation"] == "Correct Load amps and recalculate."
    assert model["warnings"] == ["amps is required"]
