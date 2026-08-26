import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "extensions" / "smedley-engineering" / "voltage-drop-sizing.js"
ENGINEERING = ROOT / "extensions" / "smedley-engineering" / "smedley-engineering.v0.2.5.js"
MANIFEST = ROOT / "extensions" / "smedley-engineering" / "manifest.json"
NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _run_node(scenario: str, *, parallel_sets: int = 2) -> dict:
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const context = {{window: {{}}}};
        vm.createContext(context);
        vm.runInContext(fs.readFileSync({json.dumps(str(HELPER))}, 'utf8'), context);
        const sizing = context.window.SmedleyVoltageDropSizing;
        const calls = [];
        const drops = {{'14': 6, '12': 4, '10': 2.5, '8': 2, '6': 1.5, '4': 1.2, '3': 1}};
        const request = async (path, params) => {{
          calls.push({{path, params: {{...params}}}});
          if (path === '/tools/feeder-size') {{
            return {{
              status: 'ok',
              result: {{
                conductor_size: {json.dumps('3' if scenario == 'ampacity' else '12')},
                combined_cf: 0.88,
                design_amps: 125,
                derated_ampacity_A: 132,
              }},
              assumptions: ['ampacity assumption'],
              warnings: [],
              code_basis: 'NEC NFPA 70, 2014 Ed. -- Table 310.16',
            }};
          }}
          if (path === '/tools/voltage-drop') {{
            const pct = drops[params.conductor_awg] ?? 0.8;
            return {{
              status: 'ok',
              result: {{
                voltage_drop_volts: +(params.voltage * pct / 100).toFixed(3),
                voltage_drop_pct: pct,
                receiving_end_voltage: +(params.voltage * (1 - pct / 100)).toFixed(2),
                pass_fail: pct <= 3 ? 'PASS' : 'FAIL',
                threshold_pct: 3,
              }},
              assumptions: ['voltage assumption'],
              warnings: pct <= 3 ? [] : ['drop warning'],
              code_basis: 'NEC NFPA 70, 2014 Ed. -- Ch.9 Table 9',
            }};
          }}
          throw new Error(`unexpected path ${{path}}`);
        }};
        const input = {{
          voltage: 480, phase: 3, amps: 100, length_ft: 250,
          material: 'copper', temp_rating: 75, circuit_type: 'feeder',
          continuous_load: true, conduit_type: 'steel', power_factor: 0.85,
          parallel_sets: {int(parallel_sets)}, ambient_temp_c: 40, num_conductors: 6,
        }};
        sizing.calculate(input, request).then((result) => {{
          process.stdout.write(JSON.stringify({{result, calls}}));
        }}).catch((error) => {{ console.error(error); process.exit(1); }});
        """
    )
    completed = subprocess.run(
        [NODE, "-e", script], capture_output=True, check=True, text=True
    )
    return json.loads(completed.stdout)


@requires_node
def test_auto_sizing_uses_larger_ampacity_constraint_and_preserves_factors():
    # Single-set path: feeder #3 governs over voltage-drop #10.
    payload = _run_node("ampacity", parallel_sets=1)
    result = payload["result"]

    assert result["status"] == "ok"
    assert result["tool"] == "voltage-drop"
    assert result["result"]["minimum_ampacity_size"] == "3"
    assert result["result"]["minimum_voltage_drop_size"] == "10"
    assert result["result"]["recommended_size"] == "3"
    assert result["result"]["governing_constraint"] == "ampacity"
    assert result["result"]["pass_fail"] == "PASS"
    assert result["result"]["threshold_pct"] == 3
    assert result["result"]["voltage_drop_pct"] == 1
    assert result["result"]["receiving_end_voltage"] == 475.2
    assert result["result"]["parallel_minimum_awg"] is None
    assert "Table 310.16" in result["code_basis"]
    assert "Ch.9 Table 9" in result["code_basis"]
    assert "ampacity assumption" in result["assumptions"]
    assert "voltage assumption" in result["assumptions"]

    feeder_call = payload["calls"][0]
    assert feeder_call["path"] == "/tools/feeder-size"
    assert feeder_call["params"]["parallel_sets"] == 1
    assert feeder_call["params"]["ambient_temp_c"] == 40
    assert feeder_call["params"]["num_conductors"] == 6
    assert feeder_call["params"]["continuous_load"] is True
    assert feeder_call["params"]["temp_rating"] == 75
    voltage_calls = [call for call in payload["calls"] if call["path"] == "/tools/voltage-drop"]
    assert all(call["params"]["parallel_sets"] == 1 for call in voltage_calls)
    assert all("material" not in call["params"] for call in voltage_calls)


@requires_node
def test_auto_sizing_reports_voltage_drop_as_governing_constraint():
    payload = _run_node("voltage", parallel_sets=1)
    result = payload["result"]["result"]

    assert result["minimum_ampacity_size"] == "12"
    assert result["minimum_voltage_drop_size"] == "10"
    assert result["recommended_size"] == "10"
    assert result["governing_constraint"] == "voltage_drop"
    assert "voltage drop" in result["governing_explanation"].lower()
    assert result["pass_fail"] == "PASS"
    assert result["voltage_drop_pct"] == 2.5
    assert result["parallel_minimum_awg"] is None


@requires_node
def test_parallel_sets_enforce_nec_1_0_minimum_on_ampacity_and_voltage_drop_sweep():
    """Live defect: feeder returned #3 for 2 parallel sets; never present as compliant."""
    payload = _run_node("ampacity", parallel_sets=2)
    result = payload["result"]
    body = result["result"]

    assert result["status"] == "ok"
    assert body["feeder_ampacity_size"] == "3"
    assert body["parallel_minimum_awg"] == "1/0"
    assert body["minimum_ampacity_size"] == "1/0"
    assert body["minimum_voltage_drop_size"] == "1/0"
    assert body["recommended_size"] == "1/0"
    assert body["conductor_awg"] == "1/0"
    assert body["pass_fail"] == "PASS"
    assert "310.10(H)" in result["code_basis"]
    assert "1/0" in result["code_basis"]
    assert any("parallel-conductor minimum" in item for item in result["assumptions"])
    assert any("raised to 1/0" in item for item in result["assumptions"])
    assert any("Voltage-drop candidate sweep starts at 1/0" in item for item in result["assumptions"])

    voltage_calls = [call for call in payload["calls"] if call["path"] == "/tools/voltage-drop"]
    requested = [call["params"]["conductor_awg"] for call in voltage_calls]
    allowed = {"1/0", "2/0", "3/0", "4/0", "250", "300", "350", "400", "500", "600", "750", "1000"}
    assert requested
    assert set(requested).issubset(allowed)
    below_floor = {"14", "12", "10", "8", "6", "4", "3", "2", "1"}
    assert not below_floor.intersection(requested)
    assert requested[0] == "1/0"


@requires_node
def test_parallel_minimum_final_recommendation_never_presents_smaller_than_1_0():
    payload = _run_node("voltage", parallel_sets=2)
    body = payload["result"]["result"]

    assert body["feeder_ampacity_size"] == "12"
    assert body["minimum_ampacity_size"] == "1/0"
    assert body["minimum_voltage_drop_size"] == "1/0"
    assert body["recommended_size"] == "1/0"
    assert body["parallel_minimum_awg"] == "1/0"
    assert "310.10(H)" in payload["result"]["code_basis"]


@requires_node
def test_auto_sizing_fails_closed_for_unsupported_material_without_requests():
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const context = {{window: {{}}}};
        vm.createContext(context);
        vm.runInContext(fs.readFileSync({json.dumps(str(HELPER))}, 'utf8'), context);
        let called = false;
        context.window.SmedleyVoltageDropSizing.calculate({{
          voltage: 480, phase: 3, amps: 100, length_ft: 100,
          material: 'aluminum', temp_rating: 75, circuit_type: 'feeder',
          continuous_load: true, conduit_type: 'steel', power_factor: 0.85,
          parallel_sets: 1, ambient_temp_c: 30, num_conductors: 3,
        }}, async () => {{ called = true; }}).then((result) => {{
          process.stdout.write(JSON.stringify({{result, called}}));
        }});
        """
    )
    completed = subprocess.run(
        [NODE, "-e", script], capture_output=True, check=True, text=True
    )
    payload = json.loads(completed.stdout)

    assert payload["called"] is False
    assert payload["result"]["status"] == "error"
    assert "Copper" in payload["result"]["error"]


@requires_node
def test_auto_sizing_fails_closed_for_missing_design_conditions_without_requests():
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const context = {{window: {{}}}};
        vm.createContext(context);
        vm.runInContext(fs.readFileSync({json.dumps(str(HELPER))}, 'utf8'), context);
        let called = false;
        context.window.SmedleyVoltageDropSizing.calculate({{
          voltage: 480, phase: 3, amps: 100, length_ft: 100,
          material: 'copper', circuit_type: 'feeder',
          continuous_load: true, conduit_type: 'steel',
          parallel_sets: 1, ambient_temp_c: 30, num_conductors: 3,
        }}, async () => {{ called = true; }}).then((result) => {{
          process.stdout.write(JSON.stringify({{result, called}}));
        }});
        """
    )
    completed = subprocess.run(
        [NODE, "-e", script], capture_output=True, check=True, text=True
    )
    payload = json.loads(completed.stdout)

    assert payload["called"] is False
    assert payload["result"]["status"] == "error"
    assert "temp_rating" in payload["result"]["error"]


def test_voltage_drop_primary_form_omits_manual_conductor_size():
    source = ENGINEERING.read_text()
    assert "['voltage-drop'" in source or "'voltage-drop':" in source
    assert "SmedleyVoltageDropSizing" in source
    vd_fields = source.split("'voltage-drop':")[1].split("'feeder-size':")[0]
    assert "'conductor_awg','Conductor size'" not in vd_fields
    assert "'material','Conductor material'" in vd_fields
    assert "'temp_rating'" in vd_fields
    assert "'continuous_load'" in vd_fields
    assert "'ambient_temp_c'" in vd_fields
    assert "'num_conductors'" in vd_fields

    manifest = json.loads(MANIFEST.read_text())
    assert manifest["scripts"][0] == "voltage-drop-sizing.js"
    assert "smedley-engineering.v0.2.5.js" in manifest["scripts"]


def test_voltage_drop_form_is_copper_only_no_aluminum_conductor_option():
    source = ENGINEERING.read_text()
    vd_fields = source.split("'voltage-drop':")[1].split("'feeder-size':")[0]
    assert "'material','Conductor material','select','copper'" in vd_fields
    assert "'material','Conductor material','select','copper|aluminum'" not in vd_fields
    assert "copper|aluminum" not in vd_fields
