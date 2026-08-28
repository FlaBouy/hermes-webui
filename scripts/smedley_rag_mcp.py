#!/usr/bin/env python3
"""Local-disk MCP proxy for the Smedley RAG API.

Only the corpus belongs on the mounted RAG volume. Executing Python or its
virtual environment from that volume can raise SIGBUS when macOS briefly
disconnects or remounts it.
"""

import json
import os
import urllib.error
import urllib.request

from mcp.server.fastmcp import FastMCP


RAG_API = os.environ.get("SMEDLEY_RAG_API", "http://127.0.0.1:5004/rag")

mcp = FastMCP(
    "smedley_rag",
    instructions=(
        "ONE tool: rag_search. Call it for engineering, hardware, specs, wiring, "
        "vendor docs, part numbers, or coin collection queries. "
        "After it returns, present the answer immediately and STOP. "
        "Do not call read_resource, list_resources, or any other tool."
    ),
)


@mcp.tool()
def rag_search(query: str) -> str:
    """Search Rick's engineering corpus and return its sourced answer."""
    q = (query or "").strip()
    if not q:
        return "rag_search: empty query."

    try:
        payload = json.dumps({"query": q}).encode()
        request = urllib.request.Request(
            RAG_API,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read())

        if not result.get("rag_needed"):
            return "NOT_CORPUS: Answer directly from your knowledge. Do not call more tools."

        answer = result.get("answer", "")
        if not answer:
            return "No answer returned from RAG API."

        return "[RAG: %d chunks, score %.2f, %.0fs]\n\n%s" % (
            result.get("chunks_found", 0),
            result.get("top_score", 0.0),
            result.get("elapsed_seconds", 0),
            answer,
        )
    except urllib.error.URLError as exc:
        return (
            "RAG API unavailable: %s — answer from general knowledge, "
            "corpus not searched." % exc
        )
    except Exception as exc:
        return "rag_search error: %s" % exc


if __name__ == "__main__":
    mcp.run()
