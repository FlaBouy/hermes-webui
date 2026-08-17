from __future__ import annotations

import api.smedley_document_route as docroute
from api.jarvis_rag_ingest_events import canonical_pub_id, PROCESSING


def test_canonical_pub_id_td005_and_in619():
    assert canonical_pub_id("1756-td005_-en-e.pdf") == "1756-TD005"
    assert canonical_pub_id("1756-in619_-en-p.pdf") == "1756-IN619"


def test_smb_path_is_not_document_extract():
    smb = "smb://192.168.0.25/RAG_Pool/Library/Vendor Data/Allen Bradley/1756"
    assert docroute.is_library_path_operation(smb)
    result = docroute.try_document_route(smb, public_origin="https://smedley.example:9111")
    assert result and result["handled"] is True
    assert result["retrieval"] == "library_path_rejected"
    assert "SMB" in result["reply"] or "sidebar" in result["reply"].lower()
    assert "could not extract that selected document" not in result["reply"].lower()


def test_processing_phases_are_the_red_contract():
    assert {"detected", "queued", "extracting", "indexing"} <= PROCESSING
