"""Retrieval-only RAG API contract shared by HTTP handlers and tests.

This module deliberately knows nothing about synthesis, ingestion, projects, or
service startup. Callers inject the existing embedding and Qdrant functions.
"""

from __future__ import annotations

import os
import re
import json
import sys
import urllib.parse
from typing import Any, Callable


DEFAULT_TOPK = 5
DEFAULT_SNIPPET_CHARS = 220
MAX_TOPK = 20
MAX_SNIPPET_CHARS = 2000
CORPUS_BASE_URL = os.environ.get("CORPUS_URL", "http://192.168.0.15:8789").rstrip("/")
WEBUI_CORPUS_SIDECAR = "/api/biggy/rag"
PLATO_UNC_ROOT = os.environ.get(
    "PLATO_UNC_ROOT",
    r"\\192.168.0.25\RAG_Pool\Library",
).rstrip("\\")
_DOCNUM_RE = re.compile(r"\b(\d{2})-?(\d{3})\b")
_PUBLICATION_ALIASES_FILE = os.path.expanduser(
    "~/.jarvis_rag_status/publication_aliases.json"
)


class RequestValidationError(ValueError):
    """The retrieval request violates the public HTTP contract."""


def plato_unc_for_source(source: str) -> str:
    """Windows Explorer path on Plato (authoritative corpus host)."""
    rel = str(source or "").replace("/", "\\").lstrip("\\")
    if not rel or rel == "?":
        return ""
    return PLATO_UNC_ROOT + "\\" + rel


def corpus_webui_path(source: str) -> str:
    """Same-origin Hermes WebUI sidecar path (works through Tailscale Serve)."""
    rel = str(source or "").replace("\\", "/").lstrip("/")
    if not rel or rel == "?":
        return ""
    ext = os.path.splitext(rel)[1].lower()
    route = "doc" if ext == ".pdf" else "preview"
    return f"{WEBUI_CORPUS_SIDECAR}/{route}/{urllib.parse.quote(rel)}"


def corpus_url_for_source(source: str) -> str:
    """Prefer WebUI sidecar path so chat links open in-browser."""
    return corpus_webui_path(source)


def markdown_link_for_source(source: str) -> str:
    rel = str(source or "").strip()
    url = corpus_webui_path(rel)
    if not url:
        return rel or "?"
    fname = rel.rsplit("/", 1)[-1] or rel
    return f"📄 [{fname}]({url})"


def _bounded_int(value: Any, name: str, default: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise RequestValidationError(f"{name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RequestValidationError(f"{name} must be an integer") from exc
    if parsed < 1 or parsed > maximum:
        raise RequestValidationError(f"{name} must be between 1 and {maximum}")
    return parsed


def _library_only(body: dict[str, Any]) -> bool:
    filter_spec = body.get("filter") or {}
    if not isinstance(filter_spec, dict):
        raise RequestValidationError("filter must be an object")
    value = filter_spec.get("library_only", True)
    if value is not True:
        raise RequestValidationError("only library_only retrieval is supported")
    return True


# Failed / quarantined library chunks are excluded. Other quality_state values
# (verified, needs_review, missing) are returned as stored — never upgraded.
_LIBRARY_EXCLUDED_QUALITY = frozenset({"failed", "quarantined", "quarantine"})

_LIBRARY_COVERAGE = (
    "Library excerpts from non-project indexed chunks. "
    "quality_state is as stored (not upgraded to verified). "
    "Failed/quarantined chunks excluded. "
    "Project Review readiness registry is not applied to general library search."
)


def _normalize_source_path(source: object) -> str:
    raw = str(source or "").strip().replace("\\", "/")
    while "//" in raw:
        raw = raw.replace("//", "/")
    return raw.lstrip("/")


def _normalize_quality_token(value: object) -> str:
    """Lowercase alnum-only token for failed/quarantine variant matching."""
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _quality_excluded(value: object) -> bool:
    token = _normalize_quality_token(value)
    if not token:
        return False
    if token in {_normalize_quality_token(v) for v in _LIBRARY_EXCLUDED_QUALITY}:
        return True
    if token.startswith("quarantine") or token.endswith("quarantine"):
        return True
    if token == "failed" or token.startswith("failed") or token.endswith("failed"):
        return True
    return False


def _excluded_quality_match_values() -> list[str]:
    """Values for Qdrant keyword must_not (case variants of excluded states)."""
    out: set[str] = set()
    for v in _LIBRARY_EXCLUDED_QUALITY:
        out.add(v)
        out.add(v.lower())
        out.add(v.upper())
        out.add(v.capitalize())
    return sorted(out)


def _project_metadata_nonempty(payload: dict[str, Any]) -> bool:
    """True when payload carries a nonempty project field (any type)."""
    if "project" not in payload:
        return False
    proj = payload.get("project")
    if proj is None:
        return False
    if isinstance(proj, bool):
        return True
    if isinstance(proj, (int, float)) and not isinstance(proj, bool):
        return True
    if isinstance(proj, str):
        return bool(proj.strip())
    if isinstance(proj, (list, tuple, set, dict)):
        return len(proj) > 0
    return bool(proj)


def library_qdrant_filter() -> dict[str, Any]:
    """Operational general-library Qdrant filter (not Project Review readiness).

    Pre-readiness contract and August 2026 retrieve backups: library_only means
    ``is_empty(project)`` only. Project Review ``active_filter`` / READY
    generations must not gate the whole vendor library.
    """
    return {
        "must": [{"is_empty": {"key": "project"}}],
        "must_not": [
            {
                "key": "quality_state",
                "match": {"any": _excluded_quality_match_values()},
            }
        ],
    }


def library_hit_allowed(payload: dict[str, Any]) -> bool:
    """Post-filter for library hits — exclude failed and any project-scoped chunk."""
    if not isinstance(payload, dict):
        return False
    if _quality_excluded(payload.get("quality_state")):
        return False
    if _project_metadata_nonempty(payload):
        return False
    source = _normalize_source_path(payload.get("source"))
    if not source or source == "?":
        return False
    if source.lower().startswith("projects/"):
        return False
    return bool(str(payload.get("text") or "").strip())


def library_hit_identity(hit: dict[str, Any]) -> str:
    """Stable dedupe key: point id, else chunk_id, else source+page+text.

    Legacy library points often lack ``chunk_id``; using only that field collapses
    distinct hits under ``None``.
    """
    if not isinstance(hit, dict):
        return "invalid:"
    point_id = hit.get("id")
    if point_id is not None and str(point_id).strip() != "":
        return f"id:{point_id}"
    payload = hit.get("payload") if isinstance(hit.get("payload"), dict) else {}
    chunk_id = payload.get("chunk_id")
    if chunk_id is not None and str(chunk_id).strip() != "":
        return f"chunk:{chunk_id}"
    source = _normalize_source_path(payload.get("source"))
    page = payload.get("pdf_page")
    if isinstance(page, bool) or not isinstance(page, (int, float)):
        page_s = ""
    else:
        page_s = str(int(page))
    text = re.sub(r"\s+", " ", str(payload.get("text") or "")).strip()[:500]
    return f"fb:{source}|{page_s}|{text}"


def _spec_tokens(query: str) -> set[str]:
    tokens: set[str] = set()
    for match in _DOCNUM_RE.finditer(query or ""):
        a, b = match.group(1), match.group(2)
        tokens.add(f"{a}{b}")
        tokens.add(f"{a}-{b}")
        tokens.add(match.group(0))
    return tokens


def _expand_query(query: str) -> str:
    """Ensure hyphenated/compact spec numbers both appear in the embed query."""
    extras: list[str] = []
    for match in _DOCNUM_RE.finditer(query or ""):
        compact = f"{match.group(1)}{match.group(2)}"
        hyphen = f"{match.group(1)}-{match.group(2)}"
        if compact not in query:
            extras.append(compact)
        if hyphen not in query:
            extras.append(hyphen)
    if not extras:
        return query
    return (query + " " + " ".join(dict.fromkeys(extras))).strip()


def _source_bonus(source: str, tokens: set[str]) -> float:
    if not tokens:
        return 0.0
    hay = source.replace("\\", "/").lower()
    for tok in tokens:
        if tok.lower() in hay:
            return 0.12
    return 0.0


def _is_wiring_query(query: str) -> bool:
    q = (query or "").lower()
    return any(w in q for w in ("wiring", "schematic", "connection", "pinout", "fta", "fta connection"))


def _is_planning_manual_fallback(match: dict[str, Any]) -> bool:
    hay = f"{match.get('source') or ''} {match.get('document_identity') or ''}".lower()
    return "hp02500" in hay or "hp02-500" in hay or ("planning" in hay and "installation" not in hay)


def _pm_io_installation_matches(query: str, part: str, topk: int) -> list[dict[str, Any]]:
    """Hard-bind Process Manager I/O Installation (pm20520.pdf) for MU/MC parts."""
    try:
        hw = "/Users/rick/hermes-webui"
        if hw not in sys.path:
            sys.path.insert(0, hw)
        from api.smedley_document_route import retrieve_pm_io_installation_payload  # noqa: WPS433
    except Exception:
        return []
    payload = retrieve_pm_io_installation_payload(part, query=query, public_origin="")
    matches = [
        m
        for m in (payload.get("matches") or [])
        if isinstance(m, dict) and not _is_planning_manual_fallback(m)
    ]
    return matches[: max(1, min(int(topk), 20))]


def _enrich_wiring_figure_packets(query: str, ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For wiring asks, attach verified FTA figure packets or fail closed.

    Planning manuals (HP02-500 / hp02500.pdf) are never returned as a wiring hit.
    """
    if not _is_wiring_query(query):
        return ranked
    try:
        hw = "/Users/rick/hermes-webui"
        if hw not in sys.path:
            sys.path.insert(0, hw)
        from api.smedley_document_route import (  # noqa: WPS433
            collect_fta_connection_diagrams_from_source,
            extract_query_part_numbers,
            _is_installation_manual,
            _is_planning_manual,
        )
    except Exception:
        return [m for m in ranked if not _is_planning_manual_fallback(m)]
    parts = extract_query_part_numbers(query)
    if not parts:
        return []
    packets: list[dict[str, Any]] = []
    for match in ranked:
        source = str(match.get("source") or "")
        title = ""
        ident = match.get("document_identity")
        if isinstance(ident, dict):
            title = str(ident.get("title") or "")
        if _is_planning_manual(source, title):
            continue
        if not _is_installation_manual(source, title):
            continue
        found, _ftas, counterpart_ok = collect_fta_connection_diagrams_from_source(source, parts[0])
        if not found:
            continue
        packet = dict(match)
        packet["score"] = max(float(match.get("score") or 0.0), 0.99)
        packet["figures"] = found
        packet["counterpart_verified"] = counterpart_ok
        packet["pdf_page"] = found[0].get("pdf_page")
        packet["figure"] = found[0].get("figure")
        packet["printed_page"] = found[0].get("printed_page")
        lines = []
        for fig in found:
            target = str(fig.get("matched_model") or parts[0])
            if str(parts[0]).upper() in target.upper().replace(" ", ""):
                lines.append(
                    f"{parts[0]} FTA field-wiring/connection diagram. Source "
                    f"{os.path.basename(source)}, Figure {fig.get('figure')}, "
                    f"PDF page {fig.get('pdf_page')}, printed page {fig.get('printed_page')}. "
                    f"{str(fig.get('excerpt') or '')[:220]}"
                )
            else:
                lines.append(
                    f"{parts[0]} field wiring is on the compatible FTA "
                    f"{fig.get('matched_model')}, not the IOP card. Source "
                    f"{os.path.basename(source)}, Figure {fig.get('figure')}, "
                    f"PDF page {fig.get('pdf_page')}, printed page {fig.get('printed_page')}. "
                    f"{str(fig.get('excerpt') or '')[:220]}"
                )
        packet["snippet"] = " | ".join(lines)[:1800]
        packets.append(packet)
    return packets


def _normalized_publication(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _exact_publication_matches(query: str, topk: int) -> list[dict[str, Any]] | None:
    """Resolve a named 1756 publication before semantic ranking.

    ``None`` means either the question did not name a publication, or it named
    one whose alias is absent/not-indexed/not-resolvable -- in both cases the
    caller must fall through to real semantic retrieval rather than refuse.
    A non-empty list means a present+indexed+resolvable exact alias was found:
    that hard-binds and semantic nearest-neighbour substitution is forbidden
    for this request, exactly as before.
    """
    query_key = _normalized_publication(query)
    if not re.search(r"(?:1756)?(?:td|um|in)0*\d{1,4}", query_key, re.I):
        return None
    try:
        with open(_PUBLICATION_ALIASES_FILE, encoding="utf-8") as handle:
            records = json.load(handle).get("publications", [])
    except Exception:
        return None
    matches: list[dict[str, Any]] = []
    for entry in records if isinstance(records, list) else []:
        if not isinstance(entry, dict):
            continue
        aliases = [entry.get("doc_no"), entry.get("canonical_filename")]
        aliases.extend(entry.get("aliases_exact") or [])
        aliases.extend(entry.get("aliases_normalized") or [])
        alias_keys = [_normalized_publication(alias) for alias in aliases]
        if not any(key and key in query_key for key in alias_keys):
            continue
        # An alias that matched by name but is not actually present/indexed/
        # resolvable is not a hard bind -- it must not silently swallow the
        # request into an empty, retrieval-forbidding result. Skip it here so
        # the caller falls through to real semantic retrieval instead.
        if not (entry.get("present") and entry.get("indexed") and entry.get("resolvable")):
            continue
        source = str(entry.get("source") or "")
        if not source:
            continue
        identity = str(entry.get("doc_no") or entry.get("publication_identifier") or source)
        matches.append({
            "source": source,
            "snippet": str(entry.get("title") or identity),
            "url": corpus_webui_path(source),
            "markdown": markdown_link_for_source(source),
            "plato_unc": plato_unc_for_source(source),
            "lan_url": f"{CORPUS_BASE_URL}/{urllib.parse.quote(source.lstrip('/'), safe='/')}",
            "score": 1.0,
            "document_identity": identity,
            "publication_identifier": entry.get("publication_identifier"),
            "retrieval": "exact_publication_alias",
        })
    if not matches:
        # Named a publication-shaped token, but no entry both matched and was
        # present+indexed+resolvable -- do not forbid semantic retrieval for a
        # document that genuinely cannot be hard-bound; let real retrieval try.
        return None
    return matches[:topk]


def build_retrieve_response(
    body: dict[str, Any],
    *,
    embed_fn: Callable[[list[str]], list[list[float]]],
    qd_fn: Callable[[str, dict[str, Any]], dict[str, Any]],
    collection: str,
) -> dict[str, Any]:
    """Validate a request and return compact library matches only."""
    if not isinstance(body, dict):
        raise RequestValidationError("request body must be an object")

    query = body.get("query")
    if not isinstance(query, str) or not query.strip():
        raise RequestValidationError("query required")
    query = query.strip()
    tokens = _spec_tokens(query)
    expanded = _expand_query(query)

    topk = _bounded_int(body.get("topk"), "topk", DEFAULT_TOPK, MAX_TOPK)
    snippet_chars = _bounded_int(
        body.get("snippet_chars"),
        "snippet_chars",
        DEFAULT_SNIPPET_CHARS,
        MAX_SNIPPET_CHARS,
    )
    _library_only(body)

    if isinstance(body.get("filter"), dict) and "project_folder" in body["filter"]:
        from api.pa_project_retrieval import project_matches
        return project_matches(query, body["filter"]["project_folder"], embed_fn=embed_fn,
                               qd_fn=qd_fn, collection=collection)

    exact_publications = _exact_publication_matches(query, topk)
    if exact_publications is not None:
        return {
            "matches": exact_publications,
            "collection": collection,
            "retrieval": "exact_publication_alias",
        }

    # Deterministic PM20-520 schematic resolver. Wiring / FTA-connection /
    # connection-diagram intents never fall through to vector ranking.
    try:
        hw = "/Users/rick/hermes-webui"
        if hw not in sys.path:
            sys.path.insert(0, hw)
        from api.tdc3000_pm20520_resolver import retrieve_response_for_query
    except Exception:
        retrieve_response_for_query = None  # type: ignore[assignment]
    if retrieve_response_for_query is not None:
        bound = retrieve_response_for_query(query, collection=collection)
        if bound is not None:
            return bound

    # Honeywell MU/MC Process Manager I/O and FTA: PM20-520 first, never
    # semantic RAG or HP02-500 planning ranking.
    try:
        from tdc3000_index_lookup import extract_part_numbers as _hw_parts
        hw_parts = _hw_parts(query)
    except Exception:
        hw_parts = []
    if hw_parts:
        ranked = _pm_io_installation_matches(query, hw_parts[0], topk)
        ranked = _enrich_wiring_figure_packets(query, ranked)
        return {
            "matches": ranked[:topk],
            "collection": collection,
            "retrieval": "pm20520_io_installation",
        }

    # Honeywell TDC3000 custom indexes (csv/json/xlsx/html) are first-class for
    # MU/MC part-number requests. Open URLs come only from those live index links.
    tdc_matches: list[dict[str, Any]] = []
    try:
        from tdc3000_index_lookup import lookup_part_numbers, should_prefer_tdc_index

        if should_prefer_tdc_index(query):
            tdc_matches = lookup_part_numbers(query, topk=topk)
    except Exception:
        tdc_matches = []

    if tdc_matches:
        # Exact index hits win; keep semantic only as filler when under topk.
        ranked = list(tdc_matches)
        if len(ranked) >= topk:
            ranked = _enrich_wiring_figure_packets(query, ranked)
            return {
                "matches": ranked[:topk],
                "collection": collection,
                "retrieval": "tdc3000_custom_index",
            }
        seen_sources = {str(m.get("source") or "") for m in ranked}
    else:
        ranked = []
        seen_sources = set()

    # General library semantic path — do NOT apply Project Review readiness
    # (active_filter / READY generation). That registry gates project grounding
    # only (see project_folder → project_matches). Historical library retrieve
    # used is_empty(project) alone; readiness bolt-on emptied whole-library
    # discovery while 241k+ non-project vectors remained indexed.
    vectors = embed_fn([expanded])
    if not vectors:
        raise RuntimeError("embedding service returned no vector")

    lib_filter = library_qdrant_filter()
    search_body = {
        "vector": vectors[0],
        "limit": max(topk * 3, topk),
        "with_payload": True,
        "filter": lib_filter,
    }
    result = qd_fn(f"/collections/{collection}/points/search", search_body)
    hits = result.get("result", []) if isinstance(result, dict) else []

    # Spec-number filename fallback: vector search often misses "02-315" phrasing
    # unless the query also contains the title words. Scroll by source text match.
    compact_tokens = sorted({t for t in tokens if re.fullmatch(r"\d{5}", t)})
    for tok in compact_tokens[:3]:
        try:
            scrolled = qd_fn(
                f"/collections/{collection}/points/scroll",
                {
                    "filter": {
                        "must": [
                            *lib_filter["must"],
                            {"key": "source", "match": {"text": tok}},
                        ],
                        "must_not": list(lib_filter.get("must_not") or []),
                    },
                    "limit": max(topk, 8),
                    "with_payload": True,
                },
            )
        except Exception:
            continue
        points = (scrolled.get("result") or {}).get("points") if isinstance(scrolled, dict) else None
        if not isinstance(points, list):
            continue
        for point in points:
            # Preserve point id for dedupe; legacy payloads often lack chunk_id.
            hits.append(
                {
                    "id": point.get("id"),
                    "score": 0.82,
                    "payload": point.get("payload") or {},
                }
            )

    seen_chunks: set[str] = set()
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        payload = hit.get("payload") or {}
        if not library_hit_allowed(payload):
            continue
        identity = library_hit_identity(hit)
        if identity in seen_chunks:
            continue
        seen_chunks.add(identity)
        source = _normalize_source_path(payload.get("source")) or "?"
        # When TDC index already answered a part-number query, do not let
        # semantic near-family / wrong-product PDFs outrank or dilute it.
        if tdc_matches:
            continue
        seen_sources.add(source)
        snippet = re.sub(r"\s+", " ", str(payload.get("text") or "")).strip()
        url = corpus_webui_path(source)
        score = hit.get("score")
        base = float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else 0.0
        match: dict[str, Any] = {
            "source": source,
            "snippet": snippet[:snippet_chars],
            "url": url,
            "markdown": markdown_link_for_source(source),
            "plato_unc": plato_unc_for_source(source),
            # Legacy Smedley corpus-serve URL — not for citations.
            "lan_url": f"{CORPUS_BASE_URL}/{urllib.parse.quote(source.lstrip('/'), safe='/')}",
            "score": round(base + _source_bonus(source, tokens), 6),
        }
        for key in (
            "source_hash",
            "source_version",
            "generation",
            "pdf_page",
            "printed_page",
            "chunk_id",
            "quality_state",
            "extraction_method",
            "items",
        ):
            match[key] = payload.get(key)
        match["support_text"] = str(payload.get("text") or "")
        ranked.append(match)

    ranked.sort(key=lambda m: m.get("score", 0.0), reverse=True)
    ranked = _enrich_wiring_figure_packets(query, ranked)
    out: dict[str, Any] = {
        "matches": ranked[:topk],
        "collection": collection,
        "coverage": _LIBRARY_COVERAGE,
        "retrieval": "library_semantic",
    }
    if tdc_matches:
        out["retrieval"] = "tdc3000_custom_index"
    return out
