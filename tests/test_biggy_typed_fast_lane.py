"""Static integration contract for Biggy's typed V6 conversation lane."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTES = (ROOT / "api" / "routes.py").read_text(encoding="utf-8")
MESSAGES = (ROOT / "static" / "messages.js").read_text(encoding="utf-8")
BRAND = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")


def test_typed_fast_lane_runs_before_document_and_agent_routes():
    start = ROUTES.index("def _handle_chat_start")
    fast = ROUTES.index("should_use_fast_conversation_route", start)
    documents = ROUTES.index("_ask_jarvis_document_fast_path", fast)
    assert start < fast < documents


def test_client_reconciles_completed_fast_turn_without_sse_or_refetch():
    marker = "if(startData.biggy_fast_voice_route)"
    start = MESSAGES.index(marker)
    end = MESSAGES.index("// Ask Jarvis hard-bind", start)
    block = MESSAGES[start:end]
    assert "returnedSession.messages" in block
    assert "S.activeStreamId=null" in block
    assert "removeThinking()" in block
    assert "setBusy(false)" in block
    assert "loadSession(" not in block


def test_project_review_paints_owner_followup_before_network_wait():
    start = BRAND.index("dialog.querySelector('#biggyProjectDialogSend').addEventListener")
    end = BRAND.index("pane.querySelectorAll('[data-biggy-location-target]'", start)
    block = BRAND[start:end]
    optimistic = block.index("is-owner is-optimistic")
    request = block.index("/api/biggy/projects/reviews/dialog")
    assert optimistic < request
    assert "Smedley is working" in block
    assert "biggy-project-dialog-tool-details" in BRAND
    assert "<summary>Tool activity</summary>" in BRAND
    assert 'aria-label="Live review tool activity"' in BRAND
    assert "toolDetailsOpen" in BRAND
    assert "priorDetails && priorDetails.open" in BRAND
    assert "Heavy extraction was not started" in ROUTES
    assert '"retryable": True' in ROUTES
    assert 'intent = "dialogue"' in ROUTES
    runtime = (ROOT / "api" / "biggy_project_review_runtime.py").read_text(encoding="utf-8")
    assert "build_dialogue_project_context" in runtime
    assert "Turn intent: DIALOGUE ONLY" in runtime
    assert "Planning mode:" in runtime
    assert "Do not enumerate source/table/row inventories" in runtime
    voice = (ROOT / "api" / "biggy_voice_route.py").read_text(encoding="utf-8")
    assert "message_has_current_execute_directive" in voice
    assert "dialogue_default_clarify" in voice
    assert "dialogue_capability_or_deferred" in voice
    assert "explicit_continuation" in voice
    assert "is_capability_or_deferred_planning" in voice


def test_project_review_fast_lane_pins_honest_cad_capability_context():
    from api.biggy_project_review_runtime import (
        build_canonical_project_context,
        build_dialogue_project_context,
    )

    runtime = (ROOT / "api" / "biggy_project_review_runtime.py").read_text(encoding="utf-8")
    text = build_canonical_project_context(
        project={"project_id": "p1", "name": "Demo"},
        review={"review_type": "internal-design", "rag_folder": "Projects/Demo"},
        readiness={"state": "needs_review", "reason": "OCR needs review"},
    )
    assert "DWG and RVT are not" in text
    assert "directly readable" in text
    assert "DXF is parsed by the local ezdxf Project Review extractor" in text
    dialogue = build_dialogue_project_context(
        project={"project_id": "p1", "name": "Demo"},
        review={"review_type": "internal-design", "rag_folder": "Projects/Demo", "scope": "scope"},
        readiness={"state": "needs_review", "reason": "OCR needs review"},
        planning=True,
    )
    assert "DIALOGUE ONLY" in dialogue
    assert "Planning mode:" in dialogue
    assert "project_review_extract path=" not in dialogue
    assert "Execution budget" not in dialogue
    assert "/api/smedley/project-review/extract" in ROUTES
    assert "smedley_project_review_extract" in ROUTES
    assert "smedley_project_review" in ROUTES
    assert "build_canonical_project_context" in ROUTES
    assert "build_dialogue_project_context" in ROUTES
    assert "history_cap = 4 if planning else 24" in ROUTES
    assert "is_capability_or_deferred_planning" in ROUTES
    assert "governed_message = project_context + onboarding + \"Owner message: \" + message" in ROUTES
    assert "Continue the engineering discussion when evidence needs review" in text
    assert "Smedley review turn already in progress" in ROUTES
    assert "plan_project_review_turn" in ROUTES
    assert "_get_session_agent_lock(session_id)" in ROUTES
    assert "project_review_status_route" in ROUTES
    assert "build_review_agent_context_messages" in ROUTES
    assert "set_project_review_turn_binding" in ROUTES
    assert "project_review_turn_context" not in ROUTES or "set_project_review_turn_binding" in ROUTES
    assert "build_canonical_project_context" in runtime
    assert "build_dialogue_project_context" in runtime


def test_project_review_dialog_remains_available_when_evidence_needs_review():
    assert "dispatch.disabled = !selected || !ready" in BRAND
    assert "openDialog.disabled = !selected;" in BRAND
    assert "openDialog.disabled = !selected || !ready" not in BRAND
