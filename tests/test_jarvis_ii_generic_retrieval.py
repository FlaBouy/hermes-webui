from api.jarvis_ii_generic_retrieval import (
    resolve_manual_request,
    resolve_wiring_request,
)


def test_catalog_terms_are_generic_and_normalized():
    from api.jarvis_ii_generic_retrieval import catalog_terms

    assert catalog_terms("Need a schematic for a 1756-IA16 and MU-TDID12") == [
        "1756-IA16",
        "MU-TDID12",
    ]
    assert catalog_terms("schematic for 900A16-0103") == ["900A16-0103", "900A16"]


def test_wiring_resolution_uses_exact_corpus_evidence_and_pdf_pages(tmp_path):
    manual = "Vendor Data/Example/Example Manual.pdf"
    index = "Vendor Data/Example/Lookup.xlsx"
    manual_path = tmp_path / manual
    manual_path.parent.mkdir(parents=True)
    manual_path.write_bytes(b"test")

    def scroll(term):
        assert term == "1756-IA16"
        return [
            {"source": index, "text": "1756-IA16 lookup result"},
            {"source": manual, "text": "1756-IA16 installation and field wiring"},
        ]

    def pages(_path):
        return [
            "Cover page",
            "1756-IA16 terminal wiring schematic and connection diagram",
            "General notes",
        ]

    result = resolve_wiring_request(
        "Ask Jarvis for a wiring schematic for a 1756-IA16",
        scroll=scroll,
        library_root=str(tmp_path),
        page_reader=pages,
    )

    assert result["ok"] is True
    assert result["source"] == manual
    assert result["pages"][0]["pdf_page"] == 2
    assert result["pages"][0]["evidence_score"] > 0
    assert result["retrieval"] == "exact_catalog_corpus_then_pdf_verification"


def test_wiring_resolution_fails_closed_when_only_an_index_is_retrieved(tmp_path):
    result = resolve_wiring_request(
        "wiring schematic for 1756-IA16",
        scroll=lambda _term: [
            {
                "source": "Vendor Data/Example/Lookup.xlsx",
                "text": "1756-IA16 lookup result",
            }
        ],
        library_root=str(tmp_path),
        page_reader=lambda _path: [],
    )

    assert result["ok"] is False
    assert result["status"] == "NO_VERIFIED_EVIDENCE"


def test_wiring_resolution_rejects_a_specification_page_that_only_mentions_wiring(tmp_path):
    manual = "Vendor Data/Example/Specifications.pdf"
    manual_path = tmp_path / manual
    manual_path.parent.mkdir(parents=True)
    manual_path.write_bytes(b"test")

    result = resolve_wiring_request(
        "wiring schematic for 1756-IB32",
        scroll=lambda _term: [{"source": manual, "text": "1756-IB32 wiring"}],
        library_root=str(tmp_path),
        page_reader=lambda _path: [
            "1756-IB32 Technical Specifications wiring requirements and terminal values"
        ],
    )

    assert result["ok"] is False
    assert result["status"] == "NO_VERIFIED_EVIDENCE"


def test_wiring_resolution_accepts_compacted_ocr_when_the_page_names_a_diagram(tmp_path):
    manual = "Vendor Data/Example/Installation.pdf"
    manual_path = tmp_path / manual
    manual_path.parent.mkdir(parents=True)
    manual_path.write_bytes(b"test")

    result = resolve_wiring_request(
        "schematic for 900A16-0103",
        scroll=lambda term: [
            {"source": manual, "text": f"{term} module wiring"}
        ],
        library_root=str(tmp_path),
        page_reader=lambda _path: [
            "HighLevelAnalogInputModule(16Channels)WiringSeeTheFollowingDiagram900A16-XXXX"
        ],
    )

    assert result["ok"] is True
    assert result["catalog_term"] == "900A16-0103"
    assert result["matched_catalog_term"] == "900A16"


def test_wiring_resolution_honors_a_vendor_cue_from_current_corpus_candidates(tmp_path):
    right_manual = "Vendor Data/Allen Bradley/1756/ControlLogix.pdf"
    wrong_manual = "Vendor Data/Honeywell/Legacy/FTA wiring.pdf"
    for manual in (right_manual, wrong_manual):
        path = tmp_path / manual
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test")

    def pages(path):
        if path.endswith("ControlLogix.pdf"):
            return ["1756-OW16I wiring diagram and terminal assignment"]
        return ["1756-OW16I wiring diagram and terminal assignment"]

    result = resolve_wiring_request(
        "wiring schematic for an Allen-Bradley 1756-OW16I",
        scroll=lambda _term: [
            {"source": wrong_manual, "text": "1756-OW16I wiring diagram"},
            {"source": right_manual, "text": "1756-OW16I wiring diagram"},
        ],
        library_root=str(tmp_path),
        page_reader=pages,
    )

    assert result["ok"] is True
    assert result["source"] == right_manual


def test_wiring_resolution_derives_vendor_initialism_from_current_corpus_candidates(tmp_path):
    right_manual = "Vendor Data/Allen Bradley/1756/ControlLogix.pdf"
    wrong_manual = "Vendor Data/Honeywell/Legacy/FTA wiring.pdf"
    for manual in (right_manual, wrong_manual):
        path = tmp_path / manual
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test")

    result = resolve_wiring_request(
        "schematic for an AB 1756-OW16I card",
        scroll=lambda _term: [
            {"source": wrong_manual, "text": "1756-OW16I wiring diagram"},
            {"source": right_manual, "text": "1756-OW16I wiring diagram"},
        ],
        library_root=str(tmp_path),
        page_reader=lambda path: ["1756-OW16I wiring diagram"] if "ControlLogix" in path else ["1756-OW16I wiring diagram"],
    )

    assert result["ok"] is True
    assert result["source"] == right_manual


def test_manual_resolution_verifies_a_document_without_vendor_mapping(tmp_path):
    manual = "Vendor Data/Honeywell/Experian PKS/TDC3000/pm20520.pdf"
    path = tmp_path / manual
    path.parent.mkdir(parents=True)
    path.write_bytes(b"test")

    def scroll(term):
        if term in {"honeywell", "process", "tdc3000"}:
            return [
                {
                    "source": manual,
                    "text": "Honeywell Process Manager I/O Installation for TDC3000",
                }
            ]
        return []

    result = resolve_manual_request(
        "Find the Honeywell Process Manager I/O Installation manual for the TDC3000 system",
        scroll=scroll,
        library_root=str(tmp_path),
    )

    assert result["ok"] is True
    assert result["status"] == "VERIFIED_MANUAL"
    assert result["source"] == manual
    assert result["document_kind"] == "manual"


def test_manual_resolution_never_answers_with_an_index(tmp_path):
    index = "Vendor Data/Honeywell/TDC3000/manual-index.xlsx"
    path = tmp_path / index
    path.parent.mkdir(parents=True)
    path.write_bytes(b"test")

    result = resolve_manual_request(
        "Find the Honeywell TDC3000 installation manual",
        scroll=lambda _term: [{"source": index, "text": "TDC3000 manual index"}],
        library_root=str(tmp_path),
    )

    assert result["ok"] is False
    assert result["status"] == "NO_VERIFIED_EVIDENCE"


def test_manual_resolution_recovers_from_incomplete_corpus_with_pdf_title_evidence(tmp_path):
    manual = "Vendor Data/Honeywell/Experian PKS/TDC3000/pm20520.pdf"
    path = tmp_path / manual
    path.parent.mkdir(parents=True)
    path.write_bytes(b"test")

    result = resolve_manual_request(
        "Find the Honeywell Process Manager I/O Installation manual for the TDC3000 system",
        scroll=lambda _term: [
            {
                "source": "Vendor Data/Honeywell/Honeywell C300/other.pdf",
                "text": "Honeywell documentation",
            }
        ],
        library_root=str(tmp_path),
        page_reader=lambda _path: [
            "Honeywell Process Manager I/O Installation Manual for TDC3000"
        ],
    )

    assert result["ok"] is True
    assert result["source"] == manual
    assert "tdc3000" in result["matched_terms"]
