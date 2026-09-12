"""Library retrieve must not gate on Project Review readiness."""

from __future__ import annotations

from api.smedley_rag_retrieval import (
    _LIBRARY_COVERAGE,
    _LIBRARY_EXCLUDED_QUALITY,
    build_retrieve_response,
    library_hit_allowed,
    library_qdrant_filter,
)


def test_library_qdrant_filter_excludes_failed_not_readiness_generations():
    filt = library_qdrant_filter()
    assert filt["must"] == [{"is_empty": {"key": "project"}}]
    assert "must_not" in filt
    excluded = {v.lower() for v in filt["must_not"][0]["match"]["any"]}
    assert "failed" in excluded
    assert "quarantine" in excluded or "quarantined" in excluded
    # No READY / generation gate in library filter.
    blob = str(filt)
    assert "generation" not in blob
    assert "__no_ready_generation__" not in blob


def test_library_hit_allowed_honest_quality_and_project_isolation():
    from api.smedley_rag_retrieval import library_hit_allowed

    assert library_hit_allowed(
        {
            "source": "Vendor Data/Allen Bradley/1756/1756-in619_-en-p.pdf",
            "text": "ControlLogix installation excerpt",
            "quality_state": "needs_review",
        }
    )
    assert library_hit_allowed(
        {
            "source": "Vendor Data/Honeywell/x.pdf",
            "text": "ok",
            "quality_state": "verified",
        }
    )
    assert not library_hit_allowed(
        {"source": "Vendor Data/x.pdf", "text": "bad", "quality_state": "failed"}
    )
    assert not library_hit_allowed(
        {"source": "Vendor Data/x.pdf", "text": "bad", "quality_state": "FAILED"}
    )
    assert not library_hit_allowed(
        {"source": "Vendor Data/x.pdf", "text": "bad", "quality_state": "Quarantine"}
    )
    assert not library_hit_allowed(
        {
            "source": "Projects/Projects - 2026/ARGUS Production Acceptance/33-18xxx.pdf",
            "text": "fixture",
            "quality_state": "verified",
        }
    )
    assert not library_hit_allowed(
        {
            "source": "projects\\vendor\\odd.pdf",
            "text": "case path",
            "quality_state": "verified",
        }
    )
    # Nonempty project metadata rejects even when path is not under Projects/.
    assert not library_hit_allowed(
        {
            "source": "Vendor Data/shared.pdf",
            "text": "tagged",
            "quality_state": "verified",
            "project": "ARGUS Production Acceptance",
        }
    )
    assert not library_hit_allowed({"source": "Vendor Data/x.pdf", "text": ""})


def test_legacy_chunks_without_chunk_id_dedupe_distinct_docs():
    """Multiple legacy hits with chunk_id=None must not collapse to one."""
    from api.smedley_rag_retrieval import build_retrieve_response, library_hit_identity

    hits = [
        {
            "id": "pt-a",
            "score": 0.95,
            "payload": {
                "source": "Vendor Data/A/doc-a.pdf",
                "text": "alpha excerpt one",
                "pdf_page": 1,
                "quality_state": "needs_review",
            },
        },
        {
            "id": "pt-b",
            "score": 0.94,
            "payload": {
                "source": "Vendor Data/B/doc-b.pdf",
                "text": "bravo excerpt two",
                "pdf_page": 2,
                "quality_state": "verified",
            },
        },
        {
            # No point id and no chunk_id — fallback source+page+text
            "score": 0.93,
            "payload": {
                "source": "Vendor Data/C/doc-c.pdf",
                "text": "charlie excerpt three",
                "pdf_page": 3,
                "quality_state": None,
            },
        },
        {
            # Duplicate of first by point id
            "id": "pt-a",
            "score": 0.92,
            "payload": {
                "source": "Vendor Data/A/doc-a.pdf",
                "text": "alpha excerpt one",
                "pdf_page": 1,
                "quality_state": "needs_review",
            },
        },
    ]
    ids = [library_hit_identity(h) for h in hits]
    assert ids[0] == "id:pt-a"
    assert ids[1] == "id:pt-b"
    assert ids[2].startswith("fb:")
    assert ids[0] == ids[3]
    assert len({ids[0], ids[1], ids[2]}) == 3

    def fake_embed(_texts):
        return [[0.1] * 8]

    def fake_qd(path, body):
        assert "points/search" in path
        return {"result": hits}

    out = build_retrieve_response(
        {"query": "legacy multi doc", "topk": 5, "filter": {"library_only": True}},
        embed_fn=fake_embed,
        qd_fn=fake_qd,
        collection="jarvis_kb",
    )
    sources = [m["source"] for m in out["matches"]]
    assert sources == [
        "Vendor Data/A/doc-a.pdf",
        "Vendor Data/B/doc-b.pdf",
        "Vendor Data/C/doc-c.pdf",
    ]
    assert out["matches"][0]["quality_state"] == "needs_review"
    assert out["matches"][2].get("quality_state") is None


def test_library_semantic_does_not_require_readiness_registry(monkeypatch):
    """Empty/unavailable Project Review registry must not empty library search."""

    def boom_registry(*_a, **_k):
        raise AssertionError("library path must not call Project Review readiness")

    monkeypatch.setattr(
        "api.argus_review_contract.active_filter", boom_registry, raising=False
    )
    monkeypatch.setattr(
        "review_readiness.active_filter", boom_registry, raising=False
    )

    captured: list[dict] = []

    def fake_embed(texts):
        assert texts and isinstance(texts[0], str)
        return [[0.1] * 8]

    def fake_qd(path, body):
        captured.append({"path": path, "body": body})
        assert "points/search" in path
        assert body["filter"]["must"] == [{"is_empty": {"key": "project"}}]
        assert "generation" not in str(body["filter"]["must"])
        return {
            "result": [
                {
                    "score": 0.91,
                    "payload": {
                        "source": "Vendor Data/Allen Bradley/1756/1756-td002_-en-e.pdf",
                        "text": "1756 ControlLogix selection guide excerpt for TD002.",
                        "quality_state": "needs_review",
                        "pdf_page": 12,
                        "chunk_id": "chunk-td002",
                        "source_hash": "hash-td002",
                    },
                },
                {
                    "score": 0.90,
                    "payload": {
                        "source": "Vendor Data/Allen Bradley/1756/1756-in619_-en-p.pdf",
                        "text": "1756-IN619 installation instructions excerpt.",
                        "quality_state": "verified",
                        "pdf_page": 3,
                        "chunk_id": "chunk-in619",
                        "source_hash": "hash-in619",
                    },
                },
                {
                    "score": 0.89,
                    "payload": {
                        "source": "Vendor Data/junk.pdf",
                        "text": "should be dropped",
                        "quality_state": "failed",
                        "chunk_id": "chunk-fail",
                    },
                },
                {
                    "score": 0.88,
                    "payload": {
                        "source": "Projects/Other/secret.pdf",
                        "text": "project isolation",
                        "quality_state": "verified",
                        "chunk_id": "chunk-proj",
                    },
                },
            ]
        }

    out = build_retrieve_response(
        {"query": "1756 ControlLogix installation", "topk": 5, "filter": {"library_only": True}},
        embed_fn=fake_embed,
        qd_fn=fake_qd,
        collection="jarvis_kb",
    )
    assert out["retrieval"] == "library_semantic"
    assert out["coverage"] == _LIBRARY_COVERAGE
    sources = [m["source"] for m in out["matches"]]
    assert "Vendor Data/Allen Bradley/1756/1756-td002_-en-e.pdf" in sources
    assert "Vendor Data/Allen Bradley/1756/1756-in619_-en-p.pdf" in sources
    assert all("junk.pdf" not in s for s in sources)
    assert all(not s.startswith("Projects/") for s in sources)
    qualities = {m["source"]: m.get("quality_state") for m in out["matches"]}
    assert qualities["Vendor Data/Allen Bradley/1756/1756-td002_-en-e.pdf"] == "needs_review"
    assert qualities["Vendor Data/Allen Bradley/1756/1756-in619_-en-p.pdf"] == "verified"
    assert captured, "expected qdrant search"


def test_project_folder_path_still_uses_project_matches(monkeypatch):
    """Project Review scoping must remain readiness-gated via project_matches."""

    called = {"project": False}

    def fake_project_matches(query, folder, **kwargs):
        called["project"] = True
        assert folder == "Projects/Demo"
        return {
            "matches": [
                {
                    "source": "Projects/Demo/a.pdf",
                    "snippet": "scoped",
                    "quality_state": "verified",
                }
            ],
            "scope": "Projects/Demo/",
            "coverage": "project",
        }

    monkeypatch.setattr(
        "api.pa_project_retrieval.project_matches", fake_project_matches
    )

    def boom_embed(_t):
        raise AssertionError("library embed must not run for project_folder")

    def boom_qd(_p, _b):
        raise AssertionError("library qd must not run for project_folder")

    out = build_retrieve_response(
        {
            "query": "what is in scope",
            "topk": 3,
            "filter": {"library_only": True, "project_folder": "Projects/Demo"},
        },
        embed_fn=boom_embed,
        qd_fn=boom_qd,
        collection="jarvis_kb",
    )
    assert called["project"] is True
    assert out["scope"] == "Projects/Demo/"
    assert out["matches"][0]["source"] == "Projects/Demo/a.pdf"
