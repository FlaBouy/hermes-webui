"""Deterministic PM20-520 schematic resolver — caption/page evidence cases."""

from __future__ import annotations

import json
from pathlib import Path

from api.tdc3000_pm20520_resolver import (
    RETRIEVAL_MODE,
    UNAVAILABLE,
    classify_artifact,
    parse_requested_part,
    resolve_pm20520_schematic,
    retrieve_response_for_query,
)
from api.smedley_rag_retrieval import build_retrieve_response

INDEX = json.loads(
    (Path(__file__).resolve().parents[1] / "api" / "tdc3000_pm20520_index.json").read_text()
)
COVERAGE = json.loads(
    (Path(__file__).resolve().parents[1] / "api" / "tdc3000_pm20520_coverage.json").read_text()
)


def _assert_caption(packet: dict, figure: str, model: str) -> None:
    cap = packet["caption_evidence"]
    assert f"Figure {figure}" in cap or packet["figure"] == figure
    assert model in cap
    assert "Connection Diagram" in cap


def test_coverage_lists_recognized_without_generic_rag_substitution():
    assert COVERAGE["recognized_count"] == len(INDEX["identifiers"])
    assert COVERAGE["verified_connection_diagram"]
    assert COVERAGE["recognized_without_verified_connection_diagram"]
    assert "generic RAG" in COVERAGE["note"]


def test_mu_tdod53_fta_connection_wiring_schematic():
    got = resolve_pm20520_schematic("MU-TDOD53", "wiring_schematic")
    assert got["status"] == "verified"
    assert got["requested_part"] == "MU-TDOD53"
    assert got["source_document"] == "pm20520.pdf"
    assert got["figure"] == "5-13"
    assert got["printed_page"] == 196
    assert got["pdf_page"] == 216
    assert got["retrieval_mode"] == RETRIEVAL_MODE
    assert got["document_supported_identity_relation"] is None
    _assert_caption(got, "5-13", "MU-TDOD53")
    query = retrieve_response_for_query(
        "MU-TDOD53 FTA connection wiring schematic", collection="jarvis_kb"
    )
    assert query is not None
    assert query["retrieval"] == RETRIEVAL_MODE
    assert query["pm20520_resolver"]["figure"] == "5-13"


def test_mu_taih02_fta_connection():
    got = resolve_pm20520_schematic("MU-TAIH02", "fta_connection")
    assert got["status"] == "verified"
    assert got["figure"] == "2-41"
    assert got["printed_page"] == 72
    assert got["pdf_page"] == 92
    _assert_caption(got, "2-41", "MU-TAIH02")


def test_mc_pdix02_uses_document_supported_fta_figures():
    got = resolve_pm20520_schematic("MC-PDIX02", "wiring_schematic")
    assert got["status"] == "verified"
    assert got["requested_part"] == "MC-PDIX02"
    rel = got["document_supported_identity_relation"]
    assert rel["counterpart"] == "MU-PDIX02"
    assert "MC" in rel["evidence"] and "MU" in rel["evidence"]
    figs = {(f["figure"], f["printed_page"], f["pdf_page"]) for f in got["figures"]}
    assert ("4-6", 145, 165) in figs
    assert ("4-7", 146, 166) in figs
    assert ("4-8", 147, 167) in figs
    assert got["figure"] == "4-6"
    assert got["printed_page"] == 145
    assert got["pdf_page"] == 165
    for f in got["figures"]:
        assert "Connection Diagram" in f["caption_evidence"]
        assert "FTA" in f["caption_evidence"]


def test_mcp_tix02_is_not_rewritten():
    part, kind = parse_requested_part("MCP-TIX02 wiring schematic")
    assert part == "MCP-TIX02"
    assert kind == "unvalidated_lookalike"
    got = resolve_pm20520_schematic("MCP-TIX02", "wiring_schematic")
    assert got["status"] == "evidence_unavailable"
    assert got["requested_part"] == "MCP-TIX02"
    assert got["reason"] == UNAVAILABLE
    assert "rewritten" in got["detail"]
    bound = retrieve_response_for_query("MCP-TIX02 wiring schematic", collection="jarvis_kb")
    assert bound is not None
    assert bound["matches"] == []
    assert bound["retrieval"] == RETRIEVAL_MODE


def test_recognized_part_without_verified_figure():
    part = "MC-GLFD02"
    assert part in COVERAGE["recognized_without_verified_connection_diagram"]
    got = resolve_pm20520_schematic(part, "connection_diagram")
    assert got["status"] == "evidence_unavailable"
    assert got["requested_part"] == part
    assert got["reason"] == UNAVAILABLE


def test_unknown_honeywell_looking_identifier():
    got = resolve_pm20520_schematic("MU-ZZZZ99", "wiring_schematic")
    assert got["status"] == "evidence_unavailable"
    assert got["requested_part"] == "MU-ZZZZ99"
    assert got["reason"] == UNAVAILABLE


def test_allen_bradley_1756_is_not_captured_by_resolver():
    assert classify_artifact("1756-TD0005") == ""
    assert retrieve_response_for_query("1756-TD0005", collection="jarvis_kb") is None
    assert retrieve_response_for_query(
        "Allen-Bradley 1756-TD0005 retrieval", collection="jarvis_kb"
    ) is None


def test_retrieve_path_does_not_call_embed_for_pm20520_schematic():
    def boom_embed(_texts):
        raise AssertionError("generic vector ranking must not run")

    def boom_qd(_path, _body):
        raise AssertionError("generic vector ranking must not run")

    out = build_retrieve_response(
        {"query": "MU-TDOD53 FTA connection wiring schematic", "topk": 5},
        embed_fn=boom_embed,
        qd_fn=boom_qd,
        collection="jarvis_kb",
    )
    assert out["retrieval"] == RETRIEVAL_MODE
    assert out["pm20520_resolver"]["figure"] == "5-13"
    assert out["pm20520_resolver"]["printed_page"] == 196

    blocked = build_retrieve_response(
        {"query": "MCP-TIX02 wiring schematic", "topk": 5},
        embed_fn=boom_embed,
        qd_fn=boom_qd,
        collection="jarvis_kb",
    )
    assert blocked["matches"] == []
    assert blocked["pm20520_resolver"]["reason"] == UNAVAILABLE


def test_mu_and_mc_remain_distinct_identities():
    mu = resolve_pm20520_schematic("MU-TDOD53", "wiring_schematic")
    mc = resolve_pm20520_schematic("MC-TDOD53", "wiring_schematic")
    assert mu["requested_part"] == "MU-TDOD53"
    assert mc["requested_part"] == "MC-TDOD53"
    if mc["status"] == "verified":
        assert mc["document_supported_identity_relation"]["counterpart"] == "MU-TDOD53"
