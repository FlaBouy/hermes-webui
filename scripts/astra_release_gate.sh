#!/bin/bash
# Local release gate for the deployed feature branch; no production-state writes.
set -euo pipefail
cd "$(dirname "$0")/.."
export HERMES_HOME="$(mktemp -d /tmp/astra-gate-home.XXXXXX)"
export HERMES_WEBUI_STATE_DIR="$(mktemp -d /tmp/astra-gate-state.XXXXXX)"
./scripts/test.sh tests/test_astra_closeout.py tests/test_biggy_fleet.py tests/test_argus_cockpit_pet_poc.py tests/test_biggy_voice_route.py tests/test_project_review_durable_turns.py tests/test_project_store_integrity.py tests/test_electrical_material_contract.py tests/test_smedley_voltage_drop_sizing.py tests/test_smedley_cable_tray.py tests/test_review_dictation_and_circuit_context.py tests/test_biggy_project_review_lifecycle.py tests/test_project_review_speech.py tests/test_review_tool_handoff_regressions.py tests/test_review_request_browser_contract.py tests/test_argus_world.py -q
node --check static/biggy-brand.js
./scripts/test.sh tests/test_biggy_pa_sources.py -q
node --check static/argus-cockpit-pet-poc.js
node --check extensions/smedley-engineering/smedley-engineering.v0.2.5.js
node --check extensions/smedley-engineering/voltage-drop-sizing.js
git diff --check
./.venv/bin/python scripts/ruff_lint.py --diff c6d1f524db86590fbaa5c992768f09ba7142722f
# Follow with documented live health, hashes and physical-glass smoke.
