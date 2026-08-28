import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / "workflows" / "jarvis-ii-pa-core-poc.json"


def workflow():
    payload = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    return payload[0] if isinstance(payload, list) else payload


def connected_nodes(source_name):
    graph = workflow()["connections"]
    return [
        edge["node"]
        for branch in graph[source_name]["main"]
        for edge in branch
    ]


def test_argus_pa_workflow_identity_is_pinned():
    data = workflow()
    assert data["id"] == "cD6uUqpzXQl3n3iU"
    assert data["name"] == "Jarvis II — PA Core POC"


def test_clear_tool_requests_are_classified_before_the_model_planner():
    assert connected_nodes("Build 120B Plan Request") == ["Classify Deterministic Plan"]
    assert connected_nodes("Classify Deterministic Plan") == ["Deterministic Plan?"]
    assert connected_nodes("Deterministic Plan?") == [
        "Governed PA Response",
        "Local 120B Plan",
    ]


def test_successful_executions_are_saved_for_correlation_autopsy():
    settings = workflow()["settings"]
    assert settings["saveDataSuccessExecution"] == "all"
    assert settings["saveExecutionProgress"] is True
