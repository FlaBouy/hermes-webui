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
        "Jarvis II Decision Agent",
    ]


def test_agentic_fallback_graph_is_complete_and_not_dangling():
    data = workflow()
    names = {node["name"] for node in data["nodes"]}
    targets = {
        edge["node"]
        for value in data["connections"].values()
        for branches in value.values()
        for branch in branches
        for edge in branch
    }
    assert targets <= names
    assert connected_nodes("Jarvis II Decision Agent") == ["Normalize Agent Decision"]
    assert connected_nodes("Normalize Agent Decision") == ["Governed PA Response"]


def test_named_destination_success_requires_semantic_fidelity():
    assert connected_nodes("Resolve Named Destination") == ["Validate Named Destination"]
    assert connected_nodes("Validate Named Destination") == ["Named Destination Resolved?"]
    nodes = {node["name"]: node for node in workflow()["nodes"]}
    gate = nodes["Validate Named Destination"]["parameters"]["jsCode"]
    branch = json.dumps(nodes["Named Destination Resolved?"]["parameters"])
    assert "SEMANTIC_DESTINATION_MISMATCH" in gate
    assert "ratio>=0.67" in gate
    assert "destinationMatch" in branch


def test_calendar_window_handles_relative_owner_language():
    nodes = {node["name"]: node for node in workflow()["nodes"]}
    code = nodes["Prepare Calendar Window"]["parameters"]["jsCode"]
    assert "next\\s+weekend" in code
    assert "next\\s+week" in code
    assert "tomorrow" in code
    assert "calendarWindow" in code


def test_agent_plan_separates_destination_from_time_and_requested_actions():
    nodes = {node["name"]: node for node in workflow()["nodes"]}
    prompt = nodes["Jarvis II Decision Agent"]["parameters"]["text"]
    assert "destination is only the physical place" in prompt
    assert "exclude dates, relative times" in prompt
    assert "calendar_window" in prompt


def test_n8n_terminal_travel_result_owns_the_verified_route_contract():
    nodes = {node["name"]: node for node in workflow()["nodes"]}
    code = nodes["Render Travel Evidence"]["parameters"]["jsCode"]
    assert "argus.route_acceptance.v2" in code
    assert "authority:'n8n_pa_core'" in code
    assert "calendar_window:base.calendarWindow" in code


def test_successful_executions_are_saved_for_correlation_autopsy():
    settings = workflow()["settings"]
    assert settings["saveDataSuccessExecution"] == "all"
    assert settings["saveExecutionProgress"] is True
