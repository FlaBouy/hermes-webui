"""Smedley pre-agent fast routes: glass, greeting, one-shot health."""

from __future__ import annotations

import re
import time

import api.smedley_document_route as docroute
import api.smedley_fast_route as fast
from api.smedley_fast_route import try_smedley_fast_route

PRIMARY_GLASS = "See if you can see what active cards are on primary glass"
GREETING = "Mornin Smedley"
HEALTH = "check service health"
RAG = "What is the fuse rating for a 1756-IF16 analog input module?"
DOC = "Pull the document 02-315"
INGEST = "Please check the ingest state of CR194 Limit Amp Starter.pdf that the RAG has flagged as detected."


def test_primary_glass_zero_tools_truthful_unavailable():
    calls = {"health": 0, "glass": 0, "n8n": 0}

    def health_get(url, timeout):
        calls["health"] += 1
        raise AssertionError("health provider must not run for glass")

    def glass_verifier():
        calls["glass"] += 1
        raise AssertionError("unconfigured glass verifier must not be invoked")

    t0 = time.perf_counter()
    result = try_smedley_fast_route(
        PRIMARY_GLASS,
        health_get=health_get,
        glass_verifier=None,
        environ={},
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert result is not None
    assert result["handled"] is True
    assert result["route"] == "primary_glass"
    assert result["tool_calls"] == 0
    assert result["provider_calls"] == 0
    assert calls == {"health": 0, "glass": 0, "n8n": 0}
    assert "cannot verify the primary physical glass" in result["reply"].lower()
    assert "will not search" in result["reply"].lower()
    assert "n8n" in result["reply"].lower()
    assert elapsed_ms < 250
    result["elapsed_ms"] = elapsed_ms


def test_greeting_zero_tools_and_providers():
    calls = {"health": 0}

    def health_get(url, timeout):
        calls["health"] += 1
        return {"http_status": 200, "body": '{"status":"ok"}'}

    t0 = time.perf_counter()
    result = try_smedley_fast_route(GREETING, health_get=health_get, environ={})
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert result is not None
    assert result["route"] == "greeting_or_status"
    assert result["tool_calls"] == 0
    assert result["provider_calls"] == 0
    assert calls["health"] == 0
    assert "Standing by" in result["reply"]
    assert elapsed_ms < 250
    status = try_smedley_fast_route(
        "Just checking to see if all systems are online",
        health_get=health_get,
        environ={},
    )
    assert status is not None
    assert status["provider_calls"] == 0
    assert status["tool_calls"] == 0
    assert calls["health"] == 0


def test_explicit_health_one_allowlisted_call_no_fallback():
    seen = []

    def health_get(url, timeout):
        seen.append((url, timeout))
        return {"http_status": 200, "body": '{"status":"ok"}'}

    t0 = time.perf_counter()
    result = try_smedley_fast_route(HEALTH, health_get=health_get, environ={})
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert result is not None
    assert result["route"] == "service_health"
    assert result["tool_calls"] == 0
    assert result["provider_calls"] == 1
    assert len(seen) == 1
    assert seen[0][0] == fast.DEFAULT_HEALTH_URL
    assert seen[0][0] in fast.ALLOWED_HEALTH_URLS
    assert "n8n" not in seen[0][0]
    assert "5678" not in seen[0][0]
    assert seen[0][1] == fast.HEALTH_TIMEOUT_S
    assert "health: ok" in result["reply"].lower()
    assert elapsed_ms < 250

    seen.clear()

    def boom(url, timeout):
        seen.append(url)
        raise OSError("connection refused")

    failed = try_smedley_fast_route(HEALTH, health_get=boom, environ={})
    assert failed is not None
    assert failed["provider_calls"] == 1
    assert failed["tool_calls"] == 0
    assert seen == [fast.DEFAULT_HEALTH_URL]
    assert "unavailable" in failed["reply"].lower()
    assert "n8n" in failed["reply"].lower()
    assert "filesystem" in failed["reply"].lower()


def test_normal_rag_and_document_routing_unchanged():
    def health_get(url, timeout):
        raise AssertionError("RAG/doc questions must not hit health")

    assert try_smedley_fast_route(RAG, health_get=health_get, environ={}) is None
    assert try_smedley_fast_route(DOC, health_get=health_get, environ={}) is None
    assert docroute.is_engineering_rag_question(RAG) is True
    assert docroute.is_document_request(DOC) is True
    assert fast.is_primary_glass_request(RAG) is False
    assert fast.is_explicit_service_health_request(RAG) is False


def test_ingest_status_uses_one_authoritative_call_and_stops():
    calls = []

    def ingest_get():
        calls.append("ingest")
        return {
            "ok": True,
            "state": "idle",
            "monitor_online": True,
            "recent": [
                {
                    "file": "CR194 Limit Amp Starter.pdf",
                    "source": "Vendor Data/GE/CR194 Limit Amp Starter.pdf",
                    "state": "ingesting",
                    "phase": "detected",
                    "reason": "",
                },
                {
                    "file": "Limit Amp Starter.pdf",
                    "state": "complete",
                    "phase": "indexed",
                },
            ],
        }

    result = try_smedley_fast_route(INGEST, ingest_status_get=ingest_get, environ={})
    assert result is not None
    assert result["route"] == "ingest_status"
    assert result["tool_calls"] == 0
    assert result["provider_calls"] == 1
    assert calls == ["ingest"]
    assert "CR194 Limit Amp Starter.pdf" in result["reply"]
    assert "detected" in result["reply"].lower()
    assert "ingest radar" in result["reply"].lower()


def test_ingest_status_typo_reports_the_single_attention_item_without_agent_search():
    def ingest_get():
        return {
            "ok": True,
            "state": "idle",
            "monitor_online": True,
            "recent": [
                {
                    "file": "CR194 Limit Amp Starter.pdf",
                    "state": "ingesting",
                    "phase": "detected",
                    "reason": "",
                },
                {"file": "Other.pdf", "state": "complete", "phase": "indexed"},
            ],
        }

    result = try_smedley_fast_route(
        "Check the ingest issue with VR194 Limit Amp Starter.pdf",
        ingest_status_get=ingest_get,
        environ={},
    )
    assert result is not None
    assert result["provider_calls"] == 1
    assert "CR194 Limit Amp Starter.pdf" in result["reply"]
    assert "VR194" not in result["reply"]


def test_ingest_status_provider_failure_terminates_and_argus_rag_is_not_swallowed():
    def boom():
        raise RuntimeError("ledger unavailable")

    result = try_smedley_fast_route(
        "Biggy, what is the RAG ingestion status?",
        ingest_status_get=boom,
        environ={},
    )
    assert result is not None
    assert result["route"] == "ingest_status"
    assert result["tool_calls"] == 0
    assert result["provider_calls"] == 1
    assert "unavailable" in result["reply"].lower()

    assert (
        try_smedley_fast_route(
            "Ask Argus to find the wiring schematic in the ingested manuals",
            ingest_status_get=lambda: (_ for _ in ()).throw(
                AssertionError("ordinary Argus RAG must not hit ingest status")
            ),
            environ={},
        )
        is None
    )


def test_explicit_reingest_command_executes_one_bounded_action_and_stops():
    calls = []

    def ingest_get():
        calls.append("status")
        return {
            "ok": True,
            "monitor_online": True,
            "recent": [
                {
                    "file": "CR194 Limit Amp Starter.pdf",
                    "source": "Vendor Data/GE/CR194 Limit Amp Starter.pdf",
                    "state": "ingesting",
                    "phase": "detected",
                    "reason": "",
                }
            ],
        }

    def retry(source):
        calls.append(("retry", source))
        return {"ok": True, "file": "CR194 Limit Amp Starter.pdf", "state": "queued"}

    result = try_smedley_fast_route(
        "Can you re-ingest the CR194 pdf yourself?",
        ingest_status_get=ingest_get,
        ingest_retry=retry,
        environ={},
    )
    assert result is not None
    assert result["route"] == "ingest_action"
    assert result["tool_calls"] == 0
    assert result["provider_calls"] == 2
    assert calls == ["status", ("retry", "Vendor Data/GE/CR194 Limit Amp Starter.pdf")]
    assert "queued" in result["reply"].lower()


def test_reingest_without_one_resolvable_issue_terminates_without_mutation():
    retried = []
    result = try_smedley_fast_route(
        "Please start the re-ingest.",
        ingest_status_get=lambda: {
            "ok": True,
            "recent": [
                {"file": "a.pdf", "source": "A/a.pdf", "state": "issue", "phase": "failed"},
                {"file": "b.pdf", "source": "B/b.pdf", "state": "issue", "phase": "failed"},
            ],
        },
        ingest_retry=lambda source: retried.append(source),
        environ={},
    )
    assert result is not None
    assert result["route"] == "ingest_action"
    assert result["tool_calls"] == 0
    assert result["provider_calls"] == 1
    assert retried == []
    assert "which file" in result["reply"].lower()


def test_reingest_duplicate_reconciles_without_claiming_it_was_queued():
    result = try_smedley_fast_route(
        "Re-ingest CR194.pdf",
        ingest_status_get=lambda: {
            "ok": True,
            "recent": [
                {
                    "file": "CR194.pdf",
                    "source": "Vendor Data/CR194.pdf",
                    "state": "ingesting",
                    "phase": "detected",
                }
            ],
        },
        ingest_retry=lambda _source: {
            "ok": True,
            "file": "CR194.pdf",
            "state": "duplicate",
            "queued": False,
        },
        environ={},
    )
    assert result is not None
    assert result["route"] == "ingest_action"
    assert "reconciled the duplicate" in result["reply"].lower()
    assert "queued" not in result["reply"].lower()


QUICK_STATUS_EXACT = "Yeah, just doing a quick systems check."
QUICK_STATUS_VARIANTS = (
    "Just doing a systems check.",
    "Yeah just a quick check.",
    "Just checking in.",
)
_HEALTHY_CLAIM_RE = re.compile(
    r"\b(?:green|healthy|all systems (?:are )?(?:go|ok|online)|running hot|no alarms)\b",
    re.IGNORECASE,
)


def test_quick_status_natural_variants_zero_providers():
    calls = {"health": 0, "model": 0}

    def health_get(url, timeout):
        calls["health"] += 1
        raise AssertionError("quick-status must not call health")

    phrases = (QUICK_STATUS_EXACT,) + QUICK_STATUS_VARIANTS
    elapsed = {}
    for phrase in phrases:
        t0 = time.perf_counter()
        result = try_smedley_fast_route(phrase, health_get=health_get, environ={})
        elapsed[phrase] = (time.perf_counter() - t0) * 1000
        assert result is not None, phrase
        assert result["handled"] is True
        assert result["route"] == "greeting_or_status"
        assert result["tool_calls"] == 0
        assert result["provider_calls"] == 0
        assert calls["health"] == 0
        assert calls["model"] == 0
        assert elapsed[phrase] < 250
        reply = result["reply"]
        assert "Standing by" in reply or "did not run a service discovery sweep" in reply
        assert _HEALTHY_CLAIM_RE.search(reply) is None, reply

    wrapped = (
        "[Workspace::v1: /Users/rick/.hermes/profiles/smedley/workspace] "
        "Morning Spadley...."
    )
    t0 = time.perf_counter()
    greet = try_smedley_fast_route(wrapped, health_get=health_get, environ={})
    greet_ms = (time.perf_counter() - t0) * 1000
    assert greet is not None
    assert greet["route"] == "greeting_or_status"
    assert greet["tool_calls"] == 0
    assert greet["provider_calls"] == 0
    assert "Standing by" in greet["reply"]
    assert greet_ms < 250
    assert elapsed[QUICK_STATUS_EXACT] >= 0
    result_meta = {"elapsed_ms": elapsed, "greeting_wrapped_ms": greet_ms}
    assert result_meta["elapsed_ms"][QUICK_STATUS_EXACT] < 250


def test_live_garbled_wake_and_systems_check_fast_route():
    calls = {"health": 0}

    def health_get(url, timeout):
        calls["health"] += 1
        raise AssertionError("live phrases must not call health")

    garbled = "Morning,\ufffd\ufffd\ufffd"
    greet = try_smedley_fast_route(garbled, health_get=health_get, environ={})
    assert greet is not None
    assert greet["route"] == "greeting_or_status"
    assert greet["tool_calls"] == 0
    assert greet["provider_calls"] == 0
    assert greet["spoken_text"]
    assert "Standing by" in greet["reply"]
    assert calls["health"] == 0

    check = try_smedley_fast_route(
        "Just doing a quick systems check.",
        health_get=health_get,
        environ={},
    )
    assert check is not None
    assert check["route"] == "greeting_or_status"
    assert check["tool_calls"] == 0
    assert check["provider_calls"] == 0
    assert "did not run a service discovery sweep" in check["reply"]
    assert check["spoken_text"] == check["reply"]
    assert calls["health"] == 0

    wrapped = (
        "Just doing a quick systems check.\n"
        "[Voice PTT turn: Answer naturally and directly.]"
    )
    wrapped_hit = try_smedley_fast_route(wrapped, health_get=health_get, environ={})
    assert wrapped_hit is not None
    assert wrapped_hit["provider_calls"] == 0
    assert wrapped_hit["tool_calls"] == 0


def test_fast_route_wired_before_agent_in_chat_start():
    src = (__import__("pathlib").Path(__file__).resolve().parents[1] / "api" / "routes.py").read_text(
        encoding="utf-8"
    )
    start = src.find("def _handle_chat_start")
    sync = src.find("def _handle_chat_sync")
    start_body = src[start:sync]
    fast_idx = start_body.find("try_smedley_fast_route")
    rag_idx = start_body.find("try_engineering_rag_answer")
    stream_idx = start_body.find("response = _start_run(")
    assert fast_idx > 0
    assert rag_idx > fast_idx
    assert stream_idx > fast_idx
    assert "try_smedley_fast_route" in src[sync:]
