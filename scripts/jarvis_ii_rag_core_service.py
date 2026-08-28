#!/usr/bin/env python3
"""Standalone HTTP adapter for the generic Jarvis II RAG Core.

It is intentionally separate from Smedley's existing RAG process.  The only
supported operation is a read-only, evidence-verified wiring lookup.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAG_BUILD = os.environ.get(
    "JARVIS_RAG_BUILD_PATH",
    os.path.join(ROOT, "runtime", "argus-rag"),
)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if RAG_BUILD not in sys.path:
    sys.path.insert(0, RAG_BUILD)

from api.jarvis_ii_generic_retrieval import (  # noqa: E402
    resolve_manual_request,
    resolve_wiring_request,
)
from api.argus_observability import record_event, terminal_event  # noqa: E402
from rag_config import COLLECTION  # noqa: E402

LIB_ROOT = os.environ.get("ARGUS_RAG_LIBRARY_ROOT", "/Users/rick/Mounts/RAG_Pool/Library")

PORT = int(os.environ.get("JARVIS_II_RAG_CORE_PORT", "5014"))
MAX_QUERY_LENGTH = 1000
SMEDLEY_RETRIEVE_URL = os.environ.get(
    "ARGUS_CANONICAL_RAG_RETRIEVE_URL",
    "http://127.0.0.1:5004/rag/retrieve",
)


def corpus_scroll(term: str) -> list[dict[str, Any]]:
    """Use the same bounded retrieval plane as Smedley.

    Raw Qdrant full-text scrolls were unindexed scans that survived client
    timeouts and saturated this service.  The canonical Smedley endpoint uses
    the configured embedding/search contract and returns in bounded time.
    """
    request = urllib.request.Request(
        SMEDLEY_RETRIEVE_URL,
        data=json.dumps({
            "query": str(term),
            "topk": 20,
            "snippet_chars": 1200,
            "filter": {"library_only": True},
        }).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
        return []
    matches = payload.get("matches") if isinstance(payload, dict) else []
    return [dict(match) for match in matches if isinstance(match, dict)]


def resolve(payload: object) -> tuple[int, dict[str, Any]]:
    body = payload if isinstance(payload, dict) else {}
    query = str(body.get("query") or "").strip()
    correlation_id = str(body.get("correlation_id") or "").strip() or "argus-core-uncorrelated"
    started = time.monotonic()
    record_event(
        correlation_id,
        component="argus-rag-core",
        stage="retrieve",
        status="started",
        query_length=len(query),
    )
    if not query or len(query) > MAX_QUERY_LENGTH:
        terminal_event(correlation_id, component="argus-rag-core", ok=False, error="INVALID_REQUEST")
        return HTTPStatus.BAD_REQUEST, {
            "ok": False,
            "status": "INVALID_REQUEST",
            "error": f"query must be 1 to {MAX_QUERY_LENGTH} characters",
        }
    result = resolve_wiring_request(
        query,
        scroll=corpus_scroll,
        library_root=LIB_ROOT,
        maximum_sources=6,
    )
    if result.get("status") == "UNSUPPORTED_REQUEST":
        result = resolve_manual_request(
            query,
            scroll=corpus_scroll,
            library_root=LIB_ROOT,
            maximum_sources=6,
        )
    result["schema"] = "jarvis.ii.rag_core.vnext.v1"
    result["collection"] = COLLECTION
    result["correlation_id"] = correlation_id
    terminal_event(
        correlation_id,
        component="argus-rag-core",
        ok=result.get("status") in {"VERIFIED_MANUAL", "VERIFIED_EVIDENCE", "NO_VERIFIED_EVIDENCE"},
        duration_ms=int((time.monotonic() - started) * 1000),
        evidence_status=result.get("status"),
        has_source=bool(result.get("source")),
    )
    return HTTPStatus.OK, result


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(HTTPStatus.OK, {"ok": True, "service": "jarvis-ii-rag-core-vnext"})
            return
        self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/resolve":
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(max(0, min(length, 100_000))).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "status": "INVALID_REQUEST"})
            return
        status, response = resolve(body)
        self._json(status, response)

    def log_message(self, _format: str, *_args: object) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
