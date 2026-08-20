import json
from pathlib import Path


def test_active_pa_planner_receives_bounded_short_term_context():
    root = Path(__file__).resolve().parents[1]
    workflow = json.loads((root / "workflows" / "jarvis-ii-pa-core-poc.json").read_text())
    workflow = workflow[0] if isinstance(workflow, list) else workflow
    planner = next(node for node in workflow["nodes"] if node["name"] == "Build 120B Plan Request")
    code = planner["parameters"]["jsCode"]

    assert "conversationContext" in code
    assert "request.conversationContext" in code
    assert "slice(-10)" in code
    assert "never evidence" in code
    assert "fresh verification" in code

    governed = next(node for node in workflow["nodes"] if node["name"] == "Governed PA Response")
    governed_code = governed["parameters"]["jsCode"]
    assert "effectiveRagObjective" in governed_code
    assert "target_recovered" in governed_code
