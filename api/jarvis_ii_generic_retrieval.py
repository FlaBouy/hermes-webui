"""Generic, evidence-first retrieval for Jarvis II RAG Core.

This module deliberately contains no vendor, manual, or page-number mappings.
For every request it retrieves exact catalog-term candidates from the corpus,
classifies source files, and verifies a wiring result by reading the candidate
PDF.  A workbook or other index may support discovery, but can never become a
wiring-schematic answer.
"""

from __future__ import annotations

import os
import re
from typing import Any, Callable, Iterable
from urllib.parse import quote


_MANUAL_EXTENSIONS = {".pdf", ".doc", ".docx"}
_INDEX_EXTENSIONS = {".csv", ".tsv", ".xls", ".xlsx"}
_CATALOG_TERM = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+(?![A-Za-z0-9])"
)
_WIRING_TERMS = re.compile(r"\b(?:wiring|schematic|connection|terminal|pinout|diagram)\b", re.I)
_DIAGRAM_EVIDENCE = re.compile(
    r"\b(?:wiring\s+diagrams?|simplified\s+schematic|connection\s+diagram|"
    r"terminal\s+assignment|terminal\s+diagram)\b",
    re.I,
)


def catalog_terms(query: object) -> list[str]:
    """Extract model/catalog tokens without embedding a vendor-specific taxonomy."""
    terms: list[str] = []
    for match in _CATALOG_TERM.finditer(str(query or "")):
        term = re.sub(r"\s+", "", match.group(0)).upper()
        if any(character.isdigit() for character in term):
            terms.append(term)
    return list(dict.fromkeys(terms))


def document_kind(source: object) -> str:
    suffix = os.path.splitext(str(source or ""))[1].lower()
    if suffix in _INDEX_EXTENSIONS:
        return "index"
    if suffix in _MANUAL_EXTENSIONS:
        return "manual"
    return "other"


def source_url(source: object) -> str:
    path = str(source or "").replace("\\", "/").lstrip("/")
    if not path:
        return ""
    route = "doc" if os.path.splitext(path)[1].lower() == ".pdf" else "preview"
    return f"/api/extensions/smedley-engineering/sidecar/{route}/{quote(path)}"


def _contains_term(text: object, term: str) -> bool:
    normalized = re.sub(r"[^A-Za-z0-9]", "", str(text or "")).upper()
    expected = re.sub(r"[^A-Za-z0-9]", "", term).upper()
    return bool(expected and expected in normalized)


def _term_occurrences(text: object, term: str) -> int:
    normalized = re.sub(r"[^A-Za-z0-9]", "", str(text or "")).upper()
    expected = re.sub(r"[^A-Za-z0-9]", "", term).upper()
    return normalized.count(expected) if expected else 0


def exact_catalog_candidates(
    query: object,
    *,
    scroll: Callable[[str], Iterable[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Get corpus passages by each exact catalog token, preserving provenance."""
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for term in catalog_terms(query):
        for payload in scroll(term):
            if not isinstance(payload, dict):
                continue
            source = str(payload.get("source") or "")
            text = str(payload.get("text") or payload.get("snippet") or "")
            key = (source, text[:500])
            if not source or key in seen or not _contains_term(text, term):
                continue
            seen.add(key)
            candidate = dict(payload)
            candidate["source"] = source.replace("\\", "/")
            candidate["snippet"] = text
            candidate["matched_catalog_term"] = term
            candidates.append(candidate)
    return candidates


def _pdf_page_texts(path: str) -> list[str]:
    from pypdf import PdfReader

    return [page.extract_text() or "" for page in PdfReader(path).pages]


def verify_wiring_pages(
    source: object,
    catalog_term: str,
    *,
    library_root: str,
    page_reader: Callable[[str], list[str]] = _pdf_page_texts,
    maximum_pages: int = 3,
) -> list[dict[str, Any]]:
    """Read the retrieved PDF and return only pages that prove the request."""
    relative = str(source or "").replace("\\", "/").lstrip("/")
    if document_kind(relative) != "manual" or not relative.lower().endswith(".pdf"):
        return []
    path = os.path.join(library_root, relative)
    if not os.path.isfile(path):
        return []
    pages: list[dict[str, Any]] = []
    for number, text in enumerate(page_reader(path), start=1):
        if not (
            _contains_term(text, catalog_term)
            and _WIRING_TERMS.search(text)
            and _DIAGRAM_EVIDENCE.search(text)
        ):
            continue
        lower = text.lower()
        term_hits = _term_occurrences(text, catalog_term)
        wiring_hits = len(_WIRING_TERMS.findall(text))
        score = term_hits * 100 + wiring_hits * 8
        if re.search(r"\b(?:wiring\s+diagrams?|simplified\s+schematic)\b", lower):
            score += 260
        if re.search(r"\b(?:connection\s+diagram|terminal\s+(?:assignment|diagram))\b", lower):
            score += 140
        if re.search(r"\b(?:input|output|terminal|field)\b", lower):
            score += 12
        if "table of contents" in lower or (lower.count("...") >= 4):
            score -= 180
        if "technical specifications" in lower:
            score -= 250
        pages.append(
            {
                "pdf_page": number,
                "evidence_score": score,
                "excerpt": re.sub(r"\s+", " ", text).strip()[:900],
            }
        )
    pages.sort(key=lambda page: int(page["evidence_score"]), reverse=True)
    return pages[:maximum_pages]


def resolve_wiring_request(
    query: object,
    *,
    scroll: Callable[[str], Iterable[dict[str, Any]]],
    library_root: str,
    page_reader: Callable[[str], list[str]] = _pdf_page_texts,
    maximum_sources: int = 12,
) -> dict[str, Any]:
    """Produce one verified, source-grounded schematic result or fail closed."""
    terms = catalog_terms(query)
    if not _WIRING_TERMS.search(str(query or "")) or not terms:
        return {"ok": False, "status": "UNSUPPORTED_REQUEST", "evidence": []}

    verified: list[dict[str, Any]] = []
    inspected: set[tuple[str, str]] = set()
    for candidate in exact_catalog_candidates(query, scroll=scroll):
        source = str(candidate.get("source") or "")
        if document_kind(source) != "manual":
            continue
        term = str(candidate.get("matched_catalog_term") or "")
        identity = (source, term)
        if identity in inspected:
            continue
        inspected.add(identity)
        if len(inspected) > maximum_sources:
            break
        pages = verify_wiring_pages(
            source, term, library_root=library_root, page_reader=page_reader
        )
        if not pages:
            continue
        verified.append(
            {
                "source": source,
                "term": term,
                "pages": pages,
                "evidence_score": int(pages[0]["evidence_score"]),
            }
        )
    if verified:
        verified.sort(key=lambda item: item["evidence_score"], reverse=True)
        best = verified[0]
        return {
            "ok": True,
            "status": "VERIFIED_EVIDENCE",
            "query": str(query or "").strip(),
            "catalog_term": best["term"],
            "source": best["source"],
            "url": source_url(best["source"]),
            "pages": best["pages"],
            "retrieval": "exact_catalog_corpus_then_pdf_verification",
        }
    return {
        "ok": False,
        "status": "NO_VERIFIED_EVIDENCE",
        "query": str(query or "").strip(),
        "catalog_terms": terms,
        "evidence": [],
    }
