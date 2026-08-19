#!/usr/bin/env python3
"""Standalone HTTP adapter for the generic Jarvis II RAG Core.

It is intentionally separate from Smedley's existing RAG process.  The only
supported operation is a read-only, evidence-verified wiring lookup.
"""

from __future__ import annotations

import json
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAG_BUILD = os.environ.get(
    "JARVIS_RAG_BUILD_PATH", "/Users/rick/Mounts/Z/DATA/n8n_share/Staging/RAG-build"
)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if RAG_BUILD not in sys.path:
    sys.path.insert(0, RAG_BUILD)

from api.jarvis_ii_generic_retrieval import resolve_wiring_request  # noqa: E402
from jarvis_rag_poc import COLLECTION, LIB_ROOT, qd  # noqa: E402

PORT = int(os.environ.get("JARVIS_II_RAG_CORE_PORT", "5014"))
MAX_QUERY_LENGTH = 1000


def corpus_scroll(term: str) -> list[dict[str, Any]]:
    result = qd(
        f"/collections/{COLLECTION}/points/scroll",
        {
            "filter": {
                "must": [
                    {"is_empty": {"key": "project"}},
                    {"key": "text", "match": {"text": term}},
                ]
            },
            "limit": 24,
            "with_payload": True,
        },
    )
    points = (result.get("result") or {}).get("points") or []
    return [point.get("payload") or {} for point in points if isinstance(point, dict)]


def resolve(payload: object) -> tuple[int, dict[str, Any]]:
    body = payload if isinstance(payload, dict) else {}
    query = str(body.get("query") or "").strip()
    if not query or len(query) > MAX_QUERY_LENGTH:
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
    result["schema"] = "jarvis.ii.rag_core.vnext.v1"
    result["collection"] = COLLECTION
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
