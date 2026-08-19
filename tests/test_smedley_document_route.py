"""t_e2207f21: Smedley document-route module — intent, LAN neutralize, absolute URLs."""

from __future__ import annotations

import json
from pathlib import Path

import api.smedley_document_route as docroute


ORIGIN = "https://smedley.example:9111"
LAN = "http://192.168.0.15:8789/Library/NEC/02-315.pdf"
SOURCE = "Library/NEC/02-315.pdf"


def test_is_document_request_detects_pull_find_link_intents():
    assert docroute.is_document_request("Pull the document for 02-315")
    assert docroute.is_document_request("Can you find the NEC manual?")
    assert docroute.is_document_request("Provide a link to the datasheet")
    assert docroute.is_document_request("link to 02315")
    assert not docroute.is_document_request("What is voltage drop on a 480V feeder?")
    assert not docroute.is_document_request("/help")
    assert not docroute.is_document_request(
        "q\n\n<retrieved_library_context>\nexcerpts\n</retrieved_library_context>"
    )


def test_hc900_edge_schematic_request_routes_to_the_hc900_manual(monkeypatch):
    query = "Hey Smedley, ask Jarvis to get me a schematic on a Honeywell Edge 900A16-0103 analog input module."
    assert docroute.is_document_request(query, allow_ask_jarvis=True)
    assert docroute.extract_query_part_numbers(query) == ["900A16-0103"]

    monkeypatch.setattr(
        docroute,
        "retrieve_documents",
        lambda *_args, **_kwargs: {
            "matches": [
                {
                    "source": "Vendor Data/Honeywell/Honeywell Edge UIO/ControlEdge HC900 IO Modules Specifications.pdf",
                    "url": "/api/extensions/smedley-engineering/sidecar/doc/Vendor%20Data/Honeywell/Honeywell%20Edge%20UIO/ControlEdge%20HC900%20IO%20Modules%20Specifications.pdf",
                    "snippet": "ControlEdge HC900 Universal Analog Input module specifications.",
                    "score": 0.79,
                }
            ]
        },
    )
    result = docroute.try_document_route(query, allow_ask_jarvis=True, public_origin=ORIGIN)
    assert result and result["handled"] is True
    assert result["active_document"]["source"].endswith("ControlEdge HC900 IO Modules Specifications.pdf")
    assert result["active_document"]["part_number"] == "900A16-0103"


def test_hc900_900a16_verified_wiring_page_includes_printed_page():
    active = {
        "source": "Vendor Data/Honeywell/Honeywell Edge UIO/ControlEdge HC900 IO Modules Specifications.pdf",
        "title": "ControlEdge HC900 IO Modules Specifications.pdf",
        "part_number": "900A16-0103",
    }
    result = docroute.try_active_document_review(
        "extract the wiring schematic", active, public_origin=ORIGIN
    )
    assert result and result["handled"] is True
    assert result["active_document"]["page_hint"] == 12
    assert "printed page **12**" in result["reply"]


def test_vendor_neutral_schematic_request_is_a_document_request():
    # No Honeywell, Allen-Bradley, or other vendor-specific catalog rule may
    # be required for a request to retrieve engineering library evidence.
    assert docroute.is_document_request(
        "Get me a wiring schematic for the Acme Controls ZX-47 module."
    )


def test_normalize_corpus_url_never_emits_lan_and_absolutizes():
    abs_url = docroute.normalize_corpus_url(LAN, source=SOURCE, public_origin=ORIGIN)
    assert abs_url == (
        f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/doc/"
        "Library/NEC/02-315.pdf"
    )
    assert "192.168.0.15:8789" not in abs_url
    assert "localhost" not in abs_url.lower()
    assert "lan_url" not in abs_url.lower()

    # Relative sidecar promoted to absolute when origin known.
    rel = "/api/extensions/smedley-engineering/sidecar/preview/Library/x.docx"
    assert docroute.normalize_corpus_url(rel, public_origin=ORIGIN) == ORIGIN + rel

    # Corpus-serve / loopback origins must not be treated as WebUI public origin.
    assert docroute.normalize_public_origin("http://192.168.0.15:8789") == ""
    assert docroute.normalize_public_origin("http://127.0.0.1:8787") == ""
    assert docroute.normalize_public_origin("http://localhost:9111") == ""


def test_normalize_corpus_url_idempotent_across_href_shapes():
    lib = "Vendor Data/Allen Bradley/1756-um001_-en-p.pdf"
    want_suffix = "/api/extensions/smedley-engineering/sidecar/doc/" + lib.replace(" ", "%20")
    shapes = [
        ("", lib),
        ("", "api/extensions/smedley-engineering/sidecar/doc/" + lib),
        ("", "/api/extensions/smedley-engineering/sidecar/doc/" + lib),
        ("/api/extensions/smedley-engineering/sidecar/doc/" + lib, ""),
        ("http://localhost:8787/api/extensions/smedley-engineering/sidecar/doc/" + lib, ""),
        (
            "http://localhost:8787/api/extensions/smedley-engineering/sidecar/doc/"
            "api/extensions/smedley-engineering/sidecar/doc/" + lib,
            "",
        ),
        (f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/doc/" + lib.replace(" ", "%20"), lib),
        (lib, lib),
    ]
    for url, src in shapes:
        out = docroute.normalize_corpus_url(url, source=src, public_origin=ORIGIN)
        assert out.count("/api/extensions/smedley-engineering/sidecar/doc/") == 1, (url, src, out)
        assert out.endswith(want_suffix) or want_suffix in out
        # Second pass must not grow.
        again = docroute.normalize_corpus_url(out, source=src, public_origin=ORIGIN)
        assert again == out


def test_public_origin_env_prefers_canonical_over_request_host(monkeypatch):
    """Persisted links must stay on Smedley's origin when Host is loopback/TD."""
    monkeypatch.setenv(docroute.PUBLIC_ORIGIN_ENV, ORIGIN)
    # Loopback request Host must not win over the configured canonical origin.
    assert (
        docroute.normalize_public_origin("http://127.0.0.1:8787") == ORIGIN
    )
    abs_url = docroute.normalize_corpus_url(LAN, source=SOURCE, public_origin="http://127.0.0.1:8787")
    assert abs_url.startswith(ORIGIN + "/api/extensions/smedley-engineering/sidecar/")
    assert "127.0.0.1" not in abs_url
    assert "192.168.0.15:8789" not in abs_url


def test_neutralize_match_drops_lan_url_field():
    raw = {
        "source": SOURCE,
        "snippet": "Article 310",
        "url": LAN,
        "markdown": f"📄 [02-315.pdf]({LAN})",
        "lan_url": LAN,
        "score": 0.91,
    }
    cleaned = docroute.neutralize_match(raw, public_origin=ORIGIN)
    assert "lan_url" not in cleaned
    assert "192.168.0.15:8789" not in cleaned["url"]
    assert "192.168.0.15:8789" not in cleaned["markdown"]
    assert cleaned["url"].startswith(ORIGIN + "/api/extensions/smedley-engineering/sidecar/")
    assert cleaned["markdown"].startswith("📄 [")


def test_maybe_rewrite_sidecar_rag_json_strips_lan_and_absolutizes():
    payload = {
        "matches": [
            {
                "source": SOURCE,
                "snippet": "x",
                "url": "/api/extensions/smedley-engineering/sidecar/doc/Library/NEC/02-315.pdf",
                "markdown": f"📄 [02-315.pdf]({LAN})",
                "lan_url": LAN,
            }
        ],
        "collection": "jarvis_kb",
    }
    body = json.dumps(payload).encode("utf-8")
    out = docroute.maybe_rewrite_sidecar_rag_json(
        "smedley-engineering",
        "rag/retrieve",
        body,
        "application/json",
        public_origin=ORIGIN,
    )
    rewritten = json.loads(out.decode("utf-8"))
    match = rewritten["matches"][0]
    assert "lan_url" not in match
    assert "192.168.0.15:8789" not in json.dumps(rewritten)
    assert match["url"].startswith(ORIGIN)
    # Non-smedley extension bodies pass through unchanged.
    other = docroute.maybe_rewrite_sidecar_rag_json("other-ext", "rag/retrieve", body)
    assert other == body


def test_try_document_route_deterministic_reply(monkeypatch):
    monkeypatch.setattr(
        docroute,
        "retrieve_documents",
        lambda query, topk=8, public_origin="": {
            "matches": [
                {
                    "source": SOURCE,
                    "snippet": "Conductor ampacity table.",
                    "url": f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/doc/{SOURCE}",
                    "markdown": (
                        f"📄 [02-315.pdf]({ORIGIN}/api/extensions/"
                        f"smedley-engineering/sidecar/doc/{SOURCE})"
                    ),
                    "score": 0.88,
                }
            ],
            "collection": "jarvis_kb",
        },
    )
    result = docroute.try_document_route(
        "Pull the document 02-315", public_origin=ORIGIN
    )
    assert result is not None
    assert result["handled"] is True
    assert result["error"] is None
    assert "192.168.0.15:8789" not in result["reply"]
    assert "127.0.0.1:8789" not in result["reply"]
    assert "localhost:8789" not in result["reply"]
    assert "lan_url" not in result["reply"].lower()
    assert ORIGIN in result["reply"]
    assert "/api/extensions/smedley-engineering/sidecar/doc/" in result["reply"]
    assert docroute.try_document_route("explain Kirchhoff's laws") is None


def test_try_document_route_uses_env_origin_not_loopback_host(monkeypatch):
    monkeypatch.setenv(docroute.PUBLIC_ORIGIN_ENV, ORIGIN)
    monkeypatch.setattr(
        docroute,
        "retrieve_documents",
        lambda query, topk=8, public_origin="": {
            "matches": [
                {
                    "source": SOURCE,
                    "snippet": "x",
                    "url": LAN,
                    "markdown": f"📄 [02-315.pdf]({LAN})",
                    "lan_url": LAN,
                    "score": 0.5,
                }
            ],
            "collection": "jarvis_kb",
        },
    )
    result = docroute.try_document_route(
        "Open document 02-315", public_origin="http://127.0.0.1:8787"
    )
    assert result is not None and result["handled"] is True
    assert ORIGIN in result["reply"]
    assert "127.0.0.1" not in result["reply"]
    assert "192.168.0.15:8789" not in result["reply"]
    assert "localhost" not in result["reply"].lower()


def test_active_document_review_extracts_only_requested_section(monkeypatch):
    active = {
        "source": "Electrical Resources/GP Brewton/02315 - Excavation and Fill Rev A.doc",
        "url": f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/preview/x.doc",
        "title": "02315 - Excavation and Fill Rev A.doc",
    }
    preview = """1. INTENT\nGeneral intent text.\n7. TESTS\nTesting shall be performed by an independent laboratory.\nCompaction results shall be reported to the Engineer.\n8. FILLING\nUnrelated filling text."""
    monkeypatch.setattr(docroute, "fetch_active_document_text", lambda source: preview)

    result = docroute.try_active_document_review("Please read section 7", active, public_origin=ORIGIN)

    assert result is not None and result["handled"] is True
    assert "Testing shall be performed" in result["reply"]
    assert "Unrelated filling text" not in result["reply"]
    assert "02315 - Excavation" in result["reply"]


def test_active_document_review_reports_no_match_without_guessing(monkeypatch):
    active = {"source": "Library/earthwork.pdf", "title": "earthwork.pdf"}
    monkeypatch.setattr(docroute, "fetch_active_document_text", lambda source: "1. SCOPE\nScope text.")

    result = docroute.try_active_document_review("Read section 9-7", active, public_origin=ORIGIN)

    assert result is not None and result["handled"] is True
    assert "could not find the requested section" in result["reply"]


def test_active_document_review_accepts_word_and_pdf_sources():
    assert docroute.is_active_document_review_request(
        "Quote paragraph 7", {"source": "Library/spec.doc"}
    )
    assert docroute.is_active_document_review_request(
        "Read section 2.1", {"source": "Library/spec.docx"}
    )
    assert docroute.is_active_document_review_request(
        "What does it say?", {"source": "Library/spec.pdf"}
    )


def test_document_selector_recognizes_spoken_doc_as_dock_and_picks_revision():
    matches = [
        {"source": "GP Brewton/02315 - Excavation and Fill.doc"},
        {"source": "GP Brewton/02315 - Excavation and Fill Rev A.doc"},
    ]
    selected = docroute.active_document_from_matches(
        matches, query="Let's open the Rev A dock"
    )
    assert selected["title"] == "02315 - Excavation and Fill Rev A.doc"
    assert docroute.is_document_request("Let's open the Rev A dock")


def test_specification_number_request_prefers_gp_brewton_wire_and_cable_spec(monkeypatch):
    nec = {"source": "Electrical Resources/NFPA - Data/2014 NEC Handbook.pdf", "snippet": "Feeder guidance."}
    wire = {
        "source": "Electrical Resources/GP Brewton/Brewton Specs/16120 - Wire and Cable Rev 1.doc",
        "snippet": "This specification covers 600-volt power cable.",
    }
    # NEC ranked first from retrieval; Brewton must win after prioritization.
    monkeypatch.setattr(
        docroute,
        "retrieve_documents",
        lambda *args, **kwargs: {"matches": [nec, wire], "collection": "jarvis_kb"},
    )

    query = "What is the GP Brewton general wire and cable specification for 600 volt feeders?"
    ranked = docroute.prioritize_gp_brewton_spec_matches([nec, wire], query)
    assert ranked[0]["source"] == wire["source"]

    result = docroute.try_document_route(query, public_origin=ORIGIN)

    assert result is not None and result["handled"] is True
    assert "16120 - Wire and Cable" in result["reply"]
    assert "2014 NEC Handbook" not in result["reply"]
    assert "/api/extensions/smedley-engineering/sidecar/" in result["reply"]
    assert "16120" in result["reply"]
    assert result["active_document"]["source"] == wire["source"]
    assert "16120" in str(result["active_document"].get("title") or result["active_document"].get("source") or "")
    assert docroute.project_spec_lookup_query(
        "What is the general wire and cable specification for 600 volt feeders?"
    ) == "GP Brewton general wire and cable specification 600 volt feeders"
    assert docroute.is_specification_number_request(query)


def test_prioritize_gp_brewton_matches_bare_project_prefix():
    nec = {"source": "Electrical Resources/NFPA - Data/2014 NEC Handbook.pdf"}
    wire = {"source": "GP Brewton/16120 - Wire and Cable Rev 1.doc"}
    ranked = docroute.prioritize_gp_brewton_spec_matches(
        [nec, wire],
        "What is the wire and cable specification number?",
    )
    assert ranked[0]["source"] == wire["source"]


def test_engineering_question_retrieves_and_quotes_verified_source(monkeypatch):
    source = "GP Brewton/11510 - Centrifugal Process Pumps - Rev A.doc"
    monkeypatch.setattr(docroute, "retrieve_documents", lambda *args, **kwargs: {"matches": [{"source": source}]})
    monkeypatch.setattr(docroute, "fetch_active_document_text", lambda source: "4.2 SHAFT. The pump shaft shall have a minimum surface hardness of 55 HRC. Material verification is required.")

    result = docroute.try_engineering_rag_answer("What hardness does the pump shaft need?", public_origin=ORIGIN)

    assert result is not None and result["handled"] is True
    assert "55 HRC" in result["reply"]
    assert "Centrifugal Process Pumps" in result["reply"]
    assert result["active_document"]["source"] == source


def test_engineering_question_never_guesses_when_source_has_no_passage(monkeypatch):
    source = "GP Brewton/11510 - Centrifugal Process Pumps - Rev A.doc"
    monkeypatch.setattr(docroute, "retrieve_documents", lambda *args, **kwargs: {"matches": [{"source": source}]})
    monkeypatch.setattr(docroute, "fetch_active_document_text", lambda source: "1. Scope. This specification covers centrifugal pumps.")

    result = docroute.try_engineering_rag_answer("What hardness does the pump shaft need?", public_origin=ORIGIN)

    assert result is not None and (
        "will not guess" in result["reply"]
        or "will not substitute" in result["reply"]
        or "cannot yet verify" in result["reply"]
    )
    assert docroute.try_engineering_rag_answer("Morning, Rick") is None


def test_engineering_excerpt_finds_requirement_inside_one_long_word_preview():
    preview = "Scope text. Pump shafts shall be filleted. Shaft sleeves shall be 400-500 Brinell hardness. End text."

    assert docroute._best_engineering_excerpt(preview, "What hardness does the pump shaft need?") == "Shaft sleeves shall be 400-500 Brinell hardness."


def test_active_document_recommendation_followup_quotes_preferred_vendor(monkeypatch):
    active = {"source": "GP Brewton/11510 - Centrifugal Process Pumps - Rev A.doc"}
    monkeypatch.setattr(docroute, "fetch_active_document_text", lambda source: "The recommended motor shall be supplied. Mechanical seals shall be quoted for all pumps. Durametallic or Safematic seals are preferred.")

    result = docroute.try_active_document_review("Who do they recommend?", active, public_origin=ORIGIN)

    assert result is not None and "Durametallic or Safematic seals are preferred" in result["reply"]


def test_engineering_excerpt_prefers_exact_shaft_guard_clearance():
    preview = "Rotating Equipment Guard Standard. Design for 1/4 inch gap on shaft and ends. Fixed guards require hinged access covers."

    assert docroute._best_engineering_excerpt(preview, "What is the standard guidance for a guard on this rotating shaft?") == "Design for 1/4 inch gap on shaft and ends."


def test_wiring_extract_followup_intent_binds_to_active_document():
    active = {
        "source": "Vendor Data/Honeywell/Experian PKS/TDC3000/Honeywell TDC/pm20520.pdf",
        "title": "Process Manager I/O Installation",
        "doc_no": "PM20-520",
        "part_number": "MC-PDIX02",
        "url": f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/doc/x.pdf",
    }
    assert docroute.is_wiring_extract_followup("Extract the wiring diagram.")
    assert docroute.is_wiring_extract_followup("show me the schematic")
    assert docroute.is_wiring_extract_followup("extract it")
    assert docroute.is_active_document_review_request("Extract the wiring diagram.", active)
    assert not docroute.is_active_document_review_request("Extract the wiring diagram.", {})
    # New document lookups must not be treated as extract-on-bound-doc.
    long_lookup = (
        "I need the user manual that shows the wiring schematics for a Honeywell IOM MC-PDIX02"
    )
    assert not docroute.is_wiring_extract_followup(long_lookup)
    assert not docroute.is_active_document_review_request(long_lookup, active)
    ab_lookup = "Find the wiring schematic for Allen Bradley 1756-OW16I"
    assert not docroute.is_wiring_extract_followup(ab_lookup)
    assert not docroute.is_active_document_review_request(ab_lookup, active)


def test_wiring_extract_uses_bound_pdf_pages_not_vision(monkeypatch):
    active = {
        "source": "Vendor Data/Honeywell/x/pm20520.pdf",
        "title": "Process Manager I/O Installation",
        "doc_no": "PM20-520",
        "part_number": "MC-PDIX02",
        "url": f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/doc/Vendor%20Data/x/pm20520.pdf",
    }
    monkeypatch.setattr(
        docroute,
        "resolve_active_document_filesystem_path",
        lambda _ad: "/tmp/fake-pm20520.pdf",
    )
    monkeypatch.setattr(
        docroute,
        "extract_wiring_pages_from_pdf",
        lambda *_a, **_k: [
            {
                "pdf_page": 159,
                "score": 80,
                "reasons": ["part_hit", "wiring"],
                "excerpt": "MU-PDIX02 Digital Input IOP is compatible. Figure 4-1 wiring connections.",
            }
        ],
    )

    result = docroute.try_active_document_review(
        "Extract the wiring diagram.", active, public_origin=ORIGIN
    )

    assert result is not None and result["handled"] is True
    assert "Verified PDF page **159**" in result["reply"]
    assert "Open wiring page" in result["reply"]
    assert "snapshot" not in result["reply"].lower()
    assert "No page loaded" not in result["reply"]
    assert result["spoken_reply"]
    assert "159" in result["spoken_reply"]
    assert result["active_document"]["page_hint"] == 159
    assert result["extraction"]["pages"][0]["pdf_page"] == 159


def test_wiring_extract_honest_failure_retains_context(monkeypatch):
    active = {
        "source": "Vendor Data/Honeywell/x/pm20520.pdf",
        "title": "Process Manager I/O Installation",
        "doc_no": "PM20-520",
        "part_number": "MC-PDIX02",
        "url": f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/doc/x.pdf",
    }
    monkeypatch.setattr(docroute, "resolve_active_document_filesystem_path", lambda _ad: "")
    result = docroute.try_active_document_review(
        "Extract the wiring diagram.", active, public_origin=ORIGIN
    )
    assert result is not None and result["handled"] is True
    assert "still have" in result["reply"].lower() or "retained" in result["reply"].lower() or "bound" in result["reply"].lower()
    assert "Open manual" in result["reply"]
    assert result.get("active_document", {}).get("source")


def test_webui_chat_start_and_messages_wire_document_route():
    """Chat/start short-circuits document intents; messages.js consumes the flag."""
    routes = (Path(__file__).resolve().parents[1] / "api" / "routes.py").read_text(
        encoding="utf-8"
    )
    messages = (Path(__file__).resolve().parents[1] / "static" / "messages.js").read_text(
        encoding="utf-8"
    )
    assert "try_document_route" in routes
    assert 'document_route": True' in routes or "document_route\": True" in routes
    assert "maybe_rewrite_sidecar_rag_json" in routes
    assert "try_active_document_review" in routes
    assert "startData.document_route" in messages
    assert "active_document_review" in messages
    assert "engineering_rag_answer" in messages
    assert "externalRefreshReason:'document-route'" in messages or 'document-route' in messages
    # Session binding must clear on index-only / no-manual document turns.
    assert "s.active_document = None" in routes


def test_electrical_fuse_question_is_source_gated_not_free_chat():
    q = "What is the internal fusing on a 1756-OB16I card for a 120V circuit"
    assert docroute.is_electrical_equipment_fact_question(q)
    assert docroute.is_engineering_rag_question(q)
    assert not docroute.is_document_request(q)


def test_ob16i_fuse_answer_quotes_um058_not_family_memory(monkeypatch):
    source = "Vendor Data/Allen Bradley/1756/1756-um058_-en-p.pdf"
    text = """
1756-OB16I                                          10…30V DC 16-point isolated output module
Table 11 - Recommended Fuses
1756-OB16I(6) (8)             None—Fused IFM can be used to protect outputs                          4 A Quick acting                         MQ2-4A
"""
    monkeypatch.setattr(
        docroute,
        "retrieve_documents",
        lambda *a, **k: {
            "matches": [
                {
                    "source": source,
                    "score": 0.9,
                    "url": f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/doc/{source}",
                    "document_identity": {"title": "ControlLogix Digital I/O Modules", "doc_no": "1756-UM058"},
                }
            ]
        },
    )
    monkeypatch.setattr(docroute, "fetch_active_document_text", lambda *_a, **_k: text)
    monkeypatch.setattr(docroute, "resolve_active_document_filesystem_path", lambda *_a, **_k: "")

    q = "What is the internal fusing on a 1756-OB16I card for a 120V circuit"
    result = docroute.try_engineering_rag_answer(q, public_origin=ORIGIN)
    assert result and result["handled"]
    assert result.get("verification") == "source_grounded"
    assert "1756-OB16I" in result["reply"]
    assert "None" in result["reply"] and "Fused IFM" in result["reply"]
    assert "0.5A" not in result["reply"]
    assert "120VAC" not in result["reply"]
    assert "Based on my experience" not in result["reply"]
    assert "Let me search" not in result["reply"]
    assert result["active_document"]["part_number"] == "1756-OB16I"
    assert "um058" in result["source"]


def test_ifm_followup_reuses_active_part_context(monkeypatch):
    source = "Vendor Data/Allen Bradley/1756/1756-um058_-en-p.pdf"
    text = """
1756-OB16I,      1492-IFM40DS24-4     Status-indicating Isolated with 24/48V AC/DC status indicators
                 1492-IFM40F-FS-2                        Isolated with extra terminals for 120V AC/DC outputs
1756-OB16I       1492-IFM40F-FS24-2                      Fusible Isolated with extra terminals
                 1492-CABLExY (x=cable length)
"""
    monkeypatch.setattr(
        docroute,
        "retrieve_documents",
        lambda *a, **k: {
            "matches": [
                {
                    "source": source,
                    "score": 0.9,
                    "url": f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/doc/{source}",
                    "part_number": "1756-OB16I",
                    "document_identity": {"title": "ControlLogix Digital I/O Modules", "doc_no": "1756-UM058"},
                }
            ]
        },
    )
    monkeypatch.setattr(docroute, "fetch_active_document_text", lambda *_a, **_k: text)
    monkeypatch.setattr(docroute, "resolve_active_document_filesystem_path", lambda *_a, **_k: "")

    active = {
        "source": source,
        "part_number": "1756-OB16I",
        "title": "ControlLogix Digital I/O Modules",
        "url": f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/doc/{source}",
    }
    q = "What is the fusible IFM module and cable to match the 1756-OB16I"
    # Follow-up without repeating part should still work via active context:
    q2 = "What is the fusible IFM module and cable to match"
    assert docroute.is_active_part_compatibility_followup(q2, active)
    result = docroute.try_engineering_rag_answer(
        q2, public_origin=ORIGIN, active_document=active
    )
    assert result and result["handled"]
    assert "1492-IFM40F-FS" in result["reply"] or "1492-IFM40" in result["reply"]
    assert "1492-CABLE" in result["reply"]
    assert result["active_document"]["part_number"] == "1756-OB16I"
    assert "cannot verify" not in result["reply"].lower() or "1492" in result["reply"]


def test_electrical_no_source_refuses_fabrication(monkeypatch):
    monkeypatch.setattr(
        docroute,
        "retrieve_documents",
        lambda *a, **k: {"matches": []},
    )
    q = "What is the internal fusing on a 1756-ZZ99X card for a 120V circuit"
    result = docroute.try_engineering_rag_answer(q, public_origin=ORIGIN)
    assert result and result["handled"]
    assert result.get("verification") == "not_found"
    assert "cannot yet verify" in result["reply"].lower() or "cannot verify" in result["reply"].lower()
    assert "will not" in result["reply"].lower() or "not substitute" in result["reply"].lower()
    assert "0.5" not in result["reply"]
    assert "Based on my experience" not in result["reply"]
    assert "Closest library hit" not in result["reply"]
    assert "um009" not in result["reply"].lower()
    assert "Want me to run that retrieval now" in result["reply"]
    assert "Wiring Diagram Knowledgebase" not in result["reply"]
    assert (result.get("active_document") or {}).get("part_number") == "1756-ZZ99X"


def test_ifm_unknown_pairing_returns_ab_lookup_index(monkeypatch):
    monkeypatch.setattr(
        docroute,
        "retrieve_documents",
        lambda *a, **k: {"matches": []},
    )
    monkeypatch.setattr(docroute, "_seed_authoritative_manuals_for_part", lambda *a, **k: [])
    q = "I need a IFM part number to match a 1756-ZZ99X IO card"
    result = docroute.try_engineering_rag_answer(q, public_origin=ORIGIN)
    assert result and result["handled"]
    assert result.get("verification") == "lookup_index"
    assert result.get("document_kind") == "index"
    assert "Wiring Diagram Knowledgebase Technote IDs by Part Number — lookup index" in result["reply"]
    assert "lookup index" in result["reply"].lower()
    assert "not an i/o module manual" in result["reply"].lower()
    assert "does **not** prove compatibility" in result["reply"]
    assert "will not extract" in result["reply"].lower()
    assert "Closest library hit" not in result["reply"]
    assert "um009" not in result["reply"].lower()
    assert "1492-IFM20F-3" not in result["reply"]  # no guessed pairing
    assert "sidecar/preview/" in result["reply"]
    assert "Wiring" in result["reply"] and "Knowledgebase" in result["reply"]
    assert (result.get("active_document") or {}).get("part_number") == "1756-ZZ99X"
    assert (result.get("active_document") or {}).get("pending_action", {}).get(
        "action"
    ) == docroute._PENDING_USE_AB_INDEX_ACTION
    assert not result["active_document"].get("source")
    # Affirmative uses the index; still not a manual / not diagram extract.
    follow = docroute.try_engineering_rag_answer(
        "Yes",
        public_origin=ORIGIN,
        active_document=result["active_document"],
    )
    assert follow and follow.get("verification") == "lookup_index"
    assert "lookup index" in follow["reply"].lower()
    assert (
        "prove compatibility" in follow["reply"].lower()
        or "proof of compatibility" in follow["reply"].lower()
    )
    assert follow["active_document"]["part_number"] == "1756-ZZ99X"
    assert "extract the wiring" not in follow["reply"].lower()


def test_ia16_ifm_uses_um058_not_analog_um009(monkeypatch):
    source = "Vendor Data/Allen Bradley/1756/1756-um058_-en-p.pdf"
    text = """
1756-IA16, 1756-IA16K                               74…132V AC 16-point input module                                                              97
1756-IA16,       1492-IFM20F-3                             3-wire sensor type input devices                                                        1492-CABLExX
1756-IA16K       1492-IFM20D120                              Standard with 120V AC/DC status indicators(1)                                         (x=cable length)
                 1492-IFM20F-F120A-2     Fusible             Extra terminals with 120V AC/DC blown fuse status indicators.
"""
    analog = {
        "source": "Vendor Data/Allen Bradley/1756/1756-um009_-en-p.pdf",
        "score": 0.95,
        "url": f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/doc/um009.pdf",
        "document_identity": {"title": "ControlLogix Analog I/O Modules", "doc_no": "1756-UM009"},
    }
    digital = {
        "source": source,
        "score": 0.40,
        "url": f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/doc/um058.pdf",
        "document_identity": {
            "title": "ControlLogix Digital I/O Modules User Manual",
            "doc_no": "1756-UM058",
        },
    }
    monkeypatch.setattr(
        docroute,
        "retrieve_documents",
        lambda *a, **k: {"matches": [analog, digital], "collection": "jarvis_kb"},
    )
    monkeypatch.setattr(docroute, "_seed_authoritative_manuals_for_part", lambda *a, **k: [digital])
    monkeypatch.setattr(docroute, "_load_manual_text_for_evidence", lambda selected: text if "um058" in str(selected.get("source") or "") else "analog only 1756-IF16 calibration")
    q = "I need a IFM part number to match a 1756-IA16 IO card"
    result = docroute.try_engineering_rag_answer(q, public_origin=ORIGIN)
    assert result and result["verification"] == "source_grounded"
    assert "um058" in result["source"]
    assert "um009" not in result["reply"]
    assert "Closest library hit" not in result["reply"]
    assert "1492-IFM20" in result["reply"]
    assert "ask for" not in result["reply"].lower()
    assert result["active_document"]["part_number"] == "1756-IA16"


def test_analog_manual_rejected_for_digital_part():
    assert not docroute.source_family_compatible_with_part(
        "Vendor Data/Allen Bradley/1756/1756-um009_-en-p.pdf",
        "ControlLogix Analog I/O",
        "1756-IA16",
    )
    assert docroute.source_family_compatible_with_part(
        "Vendor Data/Allen Bradley/1756/1756-um058_-en-p.pdf",
        "ControlLogix Digital I/O",
        "1756-IA16",
    )


def test_chassis_rejects_analog_um009_as_primary(monkeypatch):
    """Wrong-family RAG primary (UM009 analog) must never ground chassis answers."""
    um009 = "Vendor Data/Allen Bradley/1756/1756-um009_-en-p.pdf"
    um001 = "Vendor Data/Allen Bradley/1756/1756-um001_-en-p.pdf"
    analog_noise = """
1756-IF6I Module Current Wiring Example with a Two-Wire Transmitter
1756-IF16 Module Current Input Circuit
"""
    weak_um001 = """
Before You Begin To install a ControlLogix chassis and power supply
ControlLogix Power Supply Installation Instructions, publication 1756-IN619
"""
    monkeypatch.setattr(
        docroute,
        "retrieve_documents",
        lambda *a, **k: {
            "matches": [
                {
                    "source": um009,
                    "score": 0.95,
                    "document_identity": {"title": "ControlLogix Analog I/O Modules", "doc_no": "1756-UM009"},
                },
                {
                    "source": um001,
                    "score": 0.4,
                    "document_identity": {"title": "ControlLogix System User Manual", "doc_no": "1756-UM001"},
                },
            ]
        },
    )
    monkeypatch.setattr(docroute, "_seed_authoritative_manuals_for_part", lambda *a, **k: [])
    monkeypatch.setattr(
        docroute,
        "_load_manual_text_for_evidence",
        lambda selected: analog_noise if "um009" in str(selected.get("source") or "").lower() else weak_um001,
    )
    q = "What power supply do I need for a ControlLogix chassis?"
    result = docroute.try_engineering_rag_answer(q, public_origin=ORIGIN)
    assert result and result["handled"]
    assert result.get("verification") == "not_found"
    assert "um009" not in (result.get("source") or "").lower()
    assert "um009" not in result["reply"].lower()
    assert "module current wiring" not in result["reply"].lower()
    assert "serious juice" not in result["reply"].lower()
    assert (result.get("active_document") or {}).get("topic") == "controllogix_chassis_power"
    follow = docroute.try_engineering_rag_answer(
        "13 slot", public_origin=ORIGIN, active_document=result["active_document"]
    )
    assert follow and follow["handled"]
    assert follow.get("verification") != "source_grounded" or "um009" not in (follow.get("source") or "").lower()
    assert "um009" not in follow["reply"].lower()
    assert "serious juice" not in follow["reply"].lower()
    assert (follow.get("active_document") or {}).get("chassis_slots") == "13" or (
        follow.get("active_document") or {}
    ).get("topic") == "controllogix_chassis_power"


def test_controllogix_chassis_power_is_electrical_fail_closed(monkeypatch):
    source = "Vendor Data/Allen Bradley/1756-um001_-en-p.pdf"
    weak_toc = """
Before You Begin To install a ControlLogix chassis and power supply before you install your
Updated references to ControlLogix chassis and power supply installation instructions 13, 17, 31
ControlLogix Power Supply Installation Instructions, publication 1756-IN619
"""
    strong = """
1756-PA75 85 W 120/240V AC power supply for ControlLogix chassis
1756-PB75 85 W 24V DC power supply
Use the power-supply sizing worksheet; sum module backplane current for a 13-slot chassis.
Standard and redundant power-supply configurations are listed in this chapter.
"""
    monkeypatch.setattr(
        docroute,
        "retrieve_documents",
        lambda *a, **k: {"matches": [{"source": source, "score": 0.5}]},
    )
    monkeypatch.setattr(
        docroute,
        "_seed_authoritative_manuals_for_part",
        lambda *a, **k: [
            {
                "source": source,
                "score": 0.99,
                "document_identity": {"title": "ControlLogix System User Manual", "doc_no": "1756-UM001"},
            }
        ],
    )
    # Weak TOC-only library text must fail closed (no opinion, no fake sizing).
    monkeypatch.setattr(docroute, "_load_manual_text_for_evidence", lambda selected: weak_toc)
    q = "What power supply do I need for a ControlLogix chassis?"
    assert docroute.is_electrical_equipment_fact_question(q)
    weak = docroute.try_engineering_rag_answer(q, public_origin=ORIGIN)
    assert weak and weak["handled"] and weak.get("verification") == "not_found"
    assert "serious juice" not in weak["reply"].lower()
    assert "bite the bullet" not in weak["reply"].lower()
    assert "1756-PA75" not in weak["reply"]  # no guessed pairing
    assert (weak.get("active_document") or {}).get("topic") == "controllogix_chassis_power"
    assert "UM001" in weak["reply"] or "IN619" in weak["reply"]

    # Strong sizing excerpt is allowed when present.
    monkeypatch.setattr(docroute, "_load_manual_text_for_evidence", lambda selected: strong)
    result = docroute.try_engineering_rag_answer(q, public_origin=ORIGIN)
    assert result and result.get("verification") == "source_grounded"
    assert "1756-PA75" in result["reply"] or "sizing worksheet" in result["reply"].lower()
    assert result["reply"].count("/api/extensions/smedley-engineering/sidecar/doc/") == 1
    assert "sidecar/doc/api/extensions" not in result["reply"]
    assert (result.get("active_document") or {}).get("topic") == "controllogix_chassis_power"
    follow = docroute.try_engineering_rag_answer(
        "13 slot", public_origin=ORIGIN, active_document=result["active_document"]
    )
    assert follow and follow["handled"]
    assert "serious juice" not in (follow.get("reply") or "").lower()
    assert (follow.get("active_document") or {}).get("chassis_slots") == "13" or (
        follow.get("active_document") or {}
    ).get("topic") == "controllogix_chassis_power"
    if follow.get("verification") == "source_grounded":
        assert follow["reply"].count("/api/extensions/smedley-engineering/sidecar/doc/") == 1
        assert "sidecar/doc/api/extensions" not in follow["reply"]
    else:
        assert "cannot yet verify" in follow["reply"].lower() or "will not" in follow["reply"].lower()


def test_never_calls_xlsx_knowledgebase_a_manual_and_blocks_cross_vendor():
    ab_index = {
        "source": (
            "Vendor Data/Allen Bradley/Wiring Diagram Knowledgebase "
            "Technote IDs by Part Number 1-11-2021.xlsx"
        ),
        "score": 0.99,
        "url": f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/preview/x.xlsx",
        "document_identity": {
            "title": "Wiring Diagram Knowledgebase Technote IDs by Part Number 1-11-2021.xlsx"
        },
    }
    hw_manual = {
        "source": "Vendor Data/Honeywell/Experian PKS/TDC3000/Honeywell TDC/pm20520.pdf",
        "score": 0.40,
        "match_kind": "exact",
        "part_number": "MC-PDIX02",
        "retrieval": "tdc3000_custom_index",
        "revision": "PM20-520",
        "url": f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/doc/pm20520.pdf",
        "document_identity": {
            "title": "Process Manager I/O Installation",
            "doc_no": "PM20-520",
        },
    }
    query = "Find the wiring schematic for Honeywell IOM MC-PDIX02"
    reply, pending = docroute.build_operator_document_reply(
        [ab_index, hw_manual], query=query, public_origin=ORIGIN
    )
    assert "lookup index" not in reply.lower() or "PM20-520" in reply
    assert "engineering-library manual" in reply.lower() or "Process Manager" in reply
    assert "Knowledgebase" not in reply
    assert "Allen Bradley" not in reply
    assert "PM20-520" in reply
    assert pending is not None
    assert pending["action"] == "extract_wiring_schematic"
    assert pending["source"].endswith("pm20520.pdf")
    active = docroute.active_document_from_matches(
        [ab_index, hw_manual], query=query, public_origin=ORIGIN
    )
    assert active["source"].endswith("pm20520.pdf")
    assert active["document_kind"] == "manual"
    assert active.get("source_vendor") == "honeywell"


def test_index_only_never_offers_diagram_extraction():
    ab_index = {
        "source": (
            "Vendor Data/Allen Bradley/Wiring Diagram Knowledgebase "
            "Technote IDs by Part Number 1-11-2021.xlsx"
        ),
        "score": 0.99,
        "url": f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/preview/x.xlsx",
        "document_identity": {
            "title": "Wiring Diagram Knowledgebase Technote IDs by Part Number 1-11-2021.xlsx"
        },
    }
    query = "Find the wiring schematic for Allen Bradley 1756-OW16I"
    reply, pending = docroute.build_operator_document_reply(
        [ab_index], query=query, public_origin=ORIGIN
    )
    assert "lookup index" in reply.lower()
    assert "manual" not in reply.lower() or "not an engineering installation manual" in reply.lower()
    assert "Want me to extract" not in reply
    assert pending is None
    active = docroute.active_document_from_matches(
        [ab_index], query=query, public_origin=ORIGIN
    )
    assert active == {}
    spoken = docroute.build_compact_spoken_document_reply([ab_index], query=query)
    assert "lookup index" in spoken.lower()
    assert "cannot extract" in spoken.lower()


def test_affirmative_yes_binds_to_pending_extract_action(monkeypatch):
    active = {
        "source": "Vendor Data/Honeywell/x/pm20520.pdf",
        "title": "Process Manager I/O Installation",
        "doc_no": "PM20-520",
        "part_number": "MC-PDIX02",
        "url": f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/doc/x.pdf",
        "pending_action": {
            "action": "extract_wiring_schematic",
            "source": "Vendor Data/Honeywell/x/pm20520.pdf",
            "title": "Process Manager I/O Installation",
            "part_number": "MC-PDIX02",
            "doc_no": "PM20-520",
        },
    }
    assert docroute.is_affirmative_followup("Yes")
    assert docroute.is_affirmative_followup("yeah")
    assert docroute.is_affirmative_followup("please")
    assert docroute.is_affirmative_followup("do it")
    assert docroute.is_active_document_review_request("Yes", active)
    assert not docroute.is_active_document_review_request("Yes", {**active, "pending_action": None})
    assert not docroute.is_active_document_review_request("Yes", {})

    monkeypatch.setattr(
        docroute,
        "resolve_active_document_filesystem_path",
        lambda _ad: "/tmp/fake-pm20520.pdf",
    )
    monkeypatch.setattr(
        docroute,
        "extract_wiring_pages_from_pdf",
        lambda *_a, **_k: [
            {
                "pdf_page": 159,
                "score": 80,
                "reasons": ["part_hit", "wiring"],
                "excerpt": "MU-PDIX02 wiring connections.",
            }
        ],
    )
    result = docroute.try_active_document_review("Yes", active, public_origin=ORIGIN)
    assert result is not None and result["handled"] is True
    assert "159" in result["reply"]
    assert "pending_action" not in (result.get("active_document") or {})
    assert result["extraction"]["pages"][0]["pdf_page"] == 159


def test_document_route_two_turn_extract_and_yes_gate(monkeypatch):
    """E2E-style gate: request → extract phrasing AND request → Yes."""
    hw_manual = {
        "source": "Vendor Data/Honeywell/Experian PKS/TDC3000/Honeywell TDC/pm20520.pdf",
        "score": 0.95,
        "match_kind": "exact",
        "part_number": "MC-PDIX02",
        "retrieval": "tdc3000_custom_index",
        "revision": "PM20-520",
        "url": f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/doc/pm20520.pdf",
        "document_identity": {
            "title": "Process Manager I/O Installation",
            "doc_no": "PM20-520",
        },
    }
    ab_index = {
        "source": (
            "Vendor Data/Allen Bradley/Wiring Diagram Knowledgebase "
            "Technote IDs by Part Number 1-11-2021.xlsx"
        ),
        "score": 0.99,
        "url": f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/preview/x.xlsx",
        "document_identity": {
            "title": "Wiring Diagram Knowledgebase Technote IDs by Part Number 1-11-2021.xlsx"
        },
    }
    monkeypatch.setattr(
        docroute,
        "retrieve_documents",
        lambda *a, **k: {"matches": [ab_index, hw_manual], "collection": "jarvis_kb"},
    )
    query = "Find the wiring schematic for Honeywell IOM MC-PDIX02"
    turn1 = docroute.try_document_route(query, public_origin=ORIGIN)
    assert turn1 and turn1["handled"]
    assert "PM20-520" in turn1["reply"]
    assert "Knowledgebase" not in turn1["reply"]
    assert turn1["active_document"]["source"].endswith("pm20520.pdf")
    assert turn1["active_document"]["pending_action"]["action"] == "extract_wiring_schematic"
    assert turn1["retrieval_receipt"]["query_vendor"] == "honeywell"
    assert turn1["retrieval_receipt"]["document_kind"] == "manual"

    active = turn1["active_document"]
    monkeypatch.setattr(
        docroute,
        "resolve_active_document_filesystem_path",
        lambda _ad: "/tmp/fake-pm20520.pdf",
    )
    monkeypatch.setattr(
        docroute,
        "extract_wiring_pages_from_pdf",
        lambda *_a, **_k: [
            {"pdf_page": 159, "score": 80, "reasons": ["part_hit"], "excerpt": "wiring"}
        ],
    )
    extract_turn = docroute.try_active_document_review(
        "Extract the wiring diagram.", active, public_origin=ORIGIN
    )
    assert extract_turn and extract_turn["handled"]
    assert extract_turn["active_document"]["page_hint"] == 159

    # Re-bind pending for Yes path (fresh turn1 state).
    active2 = dict(turn1["active_document"])
    yes_turn = docroute.try_active_document_review("Yes", active2, public_origin=ORIGIN)
    assert yes_turn and yes_turn["handled"]
    assert yes_turn["active_document"]["page_hint"] == 159
    assert "Ready when you are" not in (yes_turn.get("reply") or "")


def test_index_only_document_route_clears_manual_binding(monkeypatch):
    ab_index = {
        "source": (
            "Vendor Data/Allen Bradley/Wiring Diagram Knowledgebase "
            "Technote IDs by Part Number 1-11-2021.xlsx"
        ),
        "score": 0.99,
        "url": f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/preview/x.xlsx",
        "document_identity": {
            "title": "Wiring Diagram Knowledgebase Technote IDs by Part Number 1-11-2021.xlsx"
        },
    }
    unrelated_manual = {
        "source": "Vendor Data/Allen Bradley/1771/1771-td182_-en-p.pdf",
        "score": 0.98,
        "url": f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/doc/1771.pdf",
    }
    monkeypatch.setattr(
        docroute,
        "retrieve_documents",
        lambda *a, **k: {
            "matches": [ab_index, unrelated_manual],
            "collection": "jarvis_kb",
        },
    )
    result = docroute.try_document_route(
        "Find the wiring schematic for Allen Bradley 1756-OW16I",
        public_origin=ORIGIN,
    )
    assert result and result["handled"]
    assert "lookup index" in result["reply"].lower()
    assert "1771-td182" not in result["reply"]
    assert "Want me to extract" not in result["reply"]
    assert result.get("active_document") in (None, {})
    assert result.get("pending_action") is None
