"""Security and routing contract for Biggy's narrow RAG ingest bridge."""

from types import SimpleNamespace

import pytest

from api.routes import _biggy_rag_proxy_target


def parsed(path: str, query: str = ""):
    return SimpleNamespace(path=path, query=query)


@pytest.mark.parametrize(
    ("path", "method", "query", "expected"),
    [
        ("/api/biggy/rag/health", "GET", "", "http://127.0.0.1:5004/health"),
        (
            "/api/biggy/rag/library-folders",
            "GET",
            "parent=AI%20Workshop%2FRoot",
            "http://127.0.0.1:5004/library-folders?parent=AI+Workshop%2FRoot",
        ),
        (
            "/api/biggy/rag/ingest-upload",
            "POST",
            "folder=Vendor%20Data",
            "http://127.0.0.1:5004/ingest-upload?folder=Vendor+Data",
        ),
        (
            "/api/biggy/rag/library-folders",
            "POST",
            "",
            "http://127.0.0.1:5004/library-folders",
        ),
        (
            "/api/biggy/rag/ingest-retry",
            "POST",
            "",
            "http://127.0.0.1:5004/ingest-retry",
        ),
    ],
)
def test_biggy_rag_proxy_only_resolves_allowlisted_operations(path, method, query, expected):
    assert _biggy_rag_proxy_target(parsed(path, query), method) == expected


def test_biggy_rag_proxy_does_not_claim_unrelated_routes():
    assert _biggy_rag_proxy_target(parsed("/api/biggy/v6/world/status"), "GET") is None


@pytest.mark.parametrize(
    ("path", "method", "query", "error"),
    [
        ("/api/biggy/rag/rag", "POST", "", ValueError),
        ("/api/biggy/rag/health", "POST", "", PermissionError),
        ("/api/biggy/rag/library-folders", "GET", "url=http://example.com", ValueError),
        ("/api/biggy/rag/library-folders", "GET", "parent=../Secrets", ValueError),
        ("/api/biggy/rag/ingest-upload", "POST", "folder=/tmp", ValueError),
    ],
)
def test_biggy_rag_proxy_rejects_open_proxy_and_folder_escape(path, method, query, error):
    with pytest.raises(error):
        _biggy_rag_proxy_target(parsed(path, query), method)
