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
_WIRING_TERMS = re.compile(r"(?:wiring|schematic|connection|terminal|pinout|diagram)", re.I)
_MANUAL_REQUEST_TERMS = re.compile(
    r"(?:manual|installation\s+(?:manual|guide)|user\s+guide|hardware\s+guide|"
    r"specification(?:s)?|documentation)",
    re.I,
)
_DIAGRAM_EVIDENCE = re.compile(
    r"(?:wiring\s*diagrams?|schematic|connection\s*diagram|"
    r"terminal\s*assignment|terminal\s*diagram|diagram)",
    re.I,
)
_QUERY_WORD = re.compile(r"[A-Za-z]{4,}")
_VENDOR_QUERY_WORD = re.compile(r"[A-Za-z]{2,}")
_MANUAL_QUERY_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]{2,}")
_MANUAL_QUERY_STOP_WORDS = {
    "ask", "have", "jarvis", "find", "need", "with", "that", "this", "the", "for", "and",
    "manual", "guide", "system", "vendor", "data", "folder", "under",
    "from", "documentation",
}


def _source_vendor_tokens(source: object) -> set[str]:
    """Return the first vendor-folder words below ``Vendor Data``.

    This is corpus metadata, not a vendor map: the resolver learns the available
    vendor labels from the candidates returned for the current request.
    """
    parts = [part.strip() for part in str(source or "").replace("\\", "/").split("/")]
    for index, part in enumerate(parts[:-1]):
        if part.lower() == "vendor data":
            words = [word.lower() for word in _VENDOR_QUERY_WORD.findall(parts[index + 1])]
            # Vendor aliases are derived from the current corpus folder label.
            # For example, a folder named "Allen Bradley" contributes its
            # generic initialism "ab"; no vendor-name mapping is maintained.
            tokens = {word for word in words if len(word) >= 4}
            if len(words) >= 2:
                tokens.add("".join(word[0] for word in words))
            return tokens
    return set()


def _query_vendor_tokens(query: object, candidates: Iterable[dict[str, Any]]) -> set[str]:
    """Find request words that match a vendor label in this candidate set."""
    request_words = {word.lower() for word in _VENDOR_QUERY_WORD.findall(str(query or ""))}
    candidate_vendor_words: set[str] = set()
    for candidate in candidates:
        candidate_vendor_words.update(_source_vendor_tokens(candidate.get("source")))
    return request_words & candidate_vendor_words


def catalog_terms(query: object) -> list[str]:
    """Extract model/catalog tokens without embedding a vendor-specific taxonomy."""
    terms: list[str] = []
    for match in _CATALOG_TERM.finditer(str(query or "")):
        term = re.sub(r"\s+", "", match.group(0)).upper()
        if any(character.isdigit() for character in term):
            terms.append(term)
            # A trailing numeric configuration/suffix is commonly absent from
            # a manual's family heading (for example, MODEL-0103 vs MODEL).
            # Keep the exact token first and add the derived family only as a
            # second retrieval term; PDF evidence still decides the answer.
            if re.search(r"-\d{3,}$", term):
                terms.append(term.rsplit("-", 1)[0])
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
    # This endpoint is served by the GUI that produced the answer. It is
    # intentionally separate from Smedley's production sidecar so a Biggy
    # citation remains in Biggy's authenticated browser session.
    return f"/api/jarvis-ii/rag-document/{quote(path)}"


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


def manual_query_terms(query: object) -> list[str]:
    """Return generic corpus terms for a named-manual request.

    This derives terms from the current request; it intentionally has no
    vendor, document-number, or folder mapping.
    """
    words = [
        word
        for word in _MANUAL_QUERY_WORD.findall(str(query or "").lower())
        if word not in _MANUAL_QUERY_STOP_WORDS
    ]
    # Keep exact hyphenated catalog identifiers intact.  Splitting 1756-IB32
    # into unrelated words made a strong corpus hit look weak and triggered an
    # unbounded shared-filesystem fallback.
    exact = [term.lower() for term in catalog_terms(query)]
    return list(dict.fromkeys([*exact, *words]))[:8]


def manual_candidates(
    query: object,
    *,
    scroll: Callable[[str], Iterable[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Collect manual candidates from the corpus using request-derived terms."""
    grouped: dict[str, dict[str, Any]] = {}
    for term in manual_query_terms(query):
        for payload in scroll(term):
            if not isinstance(payload, dict):
                continue
            source = str(payload.get("source") or "").replace("\\", "/")
            text = str(payload.get("text") or payload.get("snippet") or "")
            if not source or document_kind(source) != "manual":
                continue
            candidate = grouped.setdefault(
                source,
                {"source": source, "snippets": [], "matched_terms": set()},
            )
            candidate["matched_terms"].add(term)
            if text:
                candidate["snippets"].append(text)
    return list(grouped.values())


def _manual_search_roots(library_root: str, query_terms: Iterable[str]) -> list[str]:
    """Narrow an on-disk fallback using the library's current vendor folders."""
    vendor_root = os.path.join(library_root, "Vendor Data")
    terms = {term.lower() for term in query_terms}
    if not os.path.isdir(vendor_root):
        return [library_root]
    roots = [
        os.path.join(vendor_root, entry)
        for entry in os.listdir(vendor_root)
        if os.path.isdir(os.path.join(vendor_root, entry))
        and terms.intersection(word.lower() for word in _QUERY_WORD.findall(entry))
    ]
    return roots or [library_root]


def filesystem_manual_candidates(
    query: object,
    *,
    library_root: str,
    page_reader: Callable[[str], list[str]] | None = None,
    maximum_candidates: int = 48,
) -> list[dict[str, Any]]:
    """Verify likely manual PDFs by current folder metadata and title pages.

    This is a generic recovery path for an incompletely indexed corpus. It
    narrows from vendor folders derived from the request, then requires both
    request/path and request/title evidence before returning a document.
    """
    terms = manual_query_terms(query)
    reader = page_reader or _pdf_page_texts
    candidates: list[dict[str, Any]] = []
    for root in _manual_search_roots(library_root, terms):
        for directory, _folders, files in os.walk(root):
            for name in files:
                if not name.lower().endswith(".pdf"):
                    continue
                path = os.path.join(directory, name)
                relative = os.path.relpath(path, library_root).replace("\\", "/")
                path_matches = [term for term in terms if term in relative.lower()]
                if len(path_matches) < 2:
                    continue
                candidates.append({"path": path, "source": relative, "path_matches": path_matches})
                if len(candidates) >= maximum_candidates:
                    break
            if len(candidates) >= maximum_candidates:
                break
        if len(candidates) >= maximum_candidates:
            break

    verified: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            path = candidate["path"]
            sidecars = [path + ".ocr.txt", os.path.splitext(path)[0] + ".ocr.txt"]
            title_text = ""
            for sidecar in dict.fromkeys(sidecars):
                if os.path.isfile(sidecar):
                    with open(sidecar, "r", encoding="utf-8", errors="ignore") as handle:
                        title_text = handle.read(24_000)
                    if title_text.strip():
                        break
            if not title_text.strip():
                title_text = " ".join(reader(path)[:3])
        except Exception:
            continue
        title_matches = [term for term in terms if term in title_text.lower()]
        if len(title_matches) < 2:
            continue
        verified.append(
            {
                "source": candidate["source"],
                "matched_terms": sorted(set(candidate["path_matches"] + title_matches)),
                "evidence_score": len(candidate["path_matches"]) * 100 + len(title_matches) * 100,
                "excerpt": re.sub(r"\s+", " ", title_text).strip()[:900],
            }
        )
    return verified


def _pdf_page_texts(path: str) -> list[str]:
    from pypdf import PdfReader

    return [page.extract_text() or "" for page in PdfReader(path).pages]


def verify_wiring_pages(
    source: object,
    catalog_term: str,
    *,
    catalog_aliases: Iterable[str] = (),
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
    accepted_terms = list(dict.fromkeys([catalog_term, *catalog_aliases]))
    for number, text in enumerate(page_reader(path), start=1):
        matched_term = next(
            (term for term in accepted_terms if _contains_term(text, term)), ""
        )
        if not (
            matched_term
            and _WIRING_TERMS.search(text)
            and _DIAGRAM_EVIDENCE.search(text)
        ):
            continue
        lower = text.lower()
        term_hits = _term_occurrences(text, matched_term)
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
                "matched_catalog_term": matched_term,
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
    maximum_sources: int = 6,
) -> dict[str, Any]:
    """Produce one verified, source-grounded schematic result or fail closed."""
    terms = catalog_terms(query)
    if not _WIRING_TERMS.search(str(query or "")) or not terms:
        return {"ok": False, "status": "UNSUPPORTED_REQUEST", "evidence": []}

    candidates = exact_catalog_candidates(query, scroll=scroll)
    requested_vendor = _query_vendor_tokens(query, candidates)
    verified: list[dict[str, Any]] = []
    inspected: set[str] = set()
    for candidate in candidates:
        source = str(candidate.get("source") or "")
        if document_kind(source) != "manual":
            continue
        # When the request explicitly names a vendor that appears in the
        # current corpus candidates, never let an exact part-number mention in
        # another vendor's manual win the page-ranking race.
        if requested_vendor and not (requested_vendor & _source_vendor_tokens(source)):
            continue
        term = str(candidate.get("matched_catalog_term") or "")
        if source in inspected:
            continue
        inspected.add(source)
        if len(inspected) > maximum_sources:
            break
        pages = verify_wiring_pages(
            source,
            term,
            catalog_aliases=terms,
            library_root=library_root,
            page_reader=page_reader,
        )
        if not pages:
            continue
        verified.append(
            {
                "source": source,
                "term": str(pages[0].get("matched_catalog_term") or term),
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
            "catalog_term": terms[0],
            "matched_catalog_term": best["term"],
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


def resolve_manual_request(
    query: object,
    *,
    scroll: Callable[[str], Iterable[dict[str, Any]]],
    library_root: str,
    page_reader: Callable[[str], list[str]] = _pdf_page_texts,
    maximum_sources: int = 6,
) -> dict[str, Any]:
    """Verify a requested manual exists in the current corpus and library.

    A manual lookup verifies the document, not a page-level technical claim.
    Page, wiring, and schematic answers continue to use ``resolve_wiring_request``.
    """
    if not _MANUAL_REQUEST_TERMS.search(str(query or "")):
        return {"ok": False, "status": "UNSUPPORTED_REQUEST", "evidence": []}
    terms = manual_query_terms(query)
    if not terms:
        return {"ok": False, "status": "NO_VERIFIED_EVIDENCE", "evidence": []}

    candidates = manual_candidates(query, scroll=scroll)
    requested_vendor = _query_vendor_tokens(query, candidates)
    verified: list[dict[str, Any]] = []
    for candidate in candidates:
        source = str(candidate["source"])
        if requested_vendor and not (requested_vendor & _source_vendor_tokens(source)):
            continue
        path = os.path.join(library_root, source.lstrip("/"))
        if not os.path.isfile(path):
            continue
        matched_terms = sorted(candidate["matched_terms"])
        snippet = " ".join(str(value) for value in candidate["snippets"])
        # Corpus retrieval plus an on-disk manual is the evidence threshold for
        # document discovery. It never represents an index workbook as a manual.
        exact_terms = {term.lower() for term in catalog_terms(query)}
        has_exact_catalog_match = bool(exact_terms.intersection(term.lower() for term in matched_terms))
        if len(matched_terms) < 2 and not has_exact_catalog_match:
            continue
        score = len(matched_terms) * 100 + sum(
            10 for term in matched_terms if term.lower() in source.lower()
        )
        verified.append(
            {
                "source": source,
                "matched_terms": matched_terms,
                "evidence_score": score,
                "excerpt": re.sub(r"\s+", " ", snippet).strip()[:900],
            }
        )
        if len(verified) >= maximum_sources:
            break
    # Only walk the shared filesystem when bounded corpus retrieval found no
    # on-disk manual.  Walking the whole SMB library after an already-verified
    # candidate made successful lookups exceed the UI timeout and left orphaned
    # server threads consuming CPU.  The fast path already requires both a
    # corpus match and ``os.path.isfile`` evidence.
    if not verified and os.environ.get("ARGUS_RAG_ALLOW_FILESYSTEM_WALK") == "1":
        verified.extend(
            filesystem_manual_candidates(
                query,
                library_root=library_root,
                page_reader=page_reader,
                maximum_candidates=maximum_sources * 8,
            )
        )
    if not verified:
        return {
            "ok": False,
            "status": "NO_VERIFIED_EVIDENCE",
            "query": str(query or "").strip(),
            "query_terms": terms,
            "evidence": [],
        }
    verified.sort(key=lambda item: int(item["evidence_score"]), reverse=True)
    best = verified[0]
    return {
        "ok": True,
        "status": "VERIFIED_MANUAL",
        "query": str(query or "").strip(),
        "source": best["source"],
        "url": source_url(best["source"]),
        "document_kind": "manual",
        "matched_terms": best["matched_terms"],
        "excerpt": best["excerpt"],
        "retrieval": "request_terms_corpus_then_on_disk_manual_verification",
    }
