from api.jarvis_ii_generic_retrieval import resolve_wiring_request


def test_catalog_terms_are_generic_and_normalized():
    from api.jarvis_ii_generic_retrieval import catalog_terms

    assert catalog_terms("Need a schematic for a 1756-IA16 and MU-TDID12") == [
        "1756-IA16",
        "MU-TDID12",
    ]


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
