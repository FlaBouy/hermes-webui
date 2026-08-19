"""Deterministic TDC3000 PM20-520 schematic resolver.

Exact MU/MC wiring / FTA-connection / connection-diagram requests resolve
against the source-controlled PM20-520 index. Generic vector ranking is not
a fallback for these intents.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

INDEX_PATH = Path(__file__).resolve().parent / "tdc3000_pm20520_index.json"

VALID_PART_RE = re.compile(r"\b((?:MU|MC)-[A-Z]{2,8}\d{2,}[A-Z]?)\b", re.IGNORECASE)
# Honeywell-looking tokens that must never be silently rewritten into MU/MC.
LOOKALIKE_RE = re.compile(r"\b(M[CU][A-Z0-9]*-?[A-Z]{1,8}\d{2,}[A-Z]?)\b", re.IGNORECASE)
AB_PART_RE = re.compile(r"\b1756-[A-Z]{1,6}\d{0,4}[A-Z]?\b", re.IGNORECASE)

SCHEMATIC_ARTIFACTS = frozenset(
    {"wiring_schematic", "fta_connection", "connection_diagram"}
)
UNAVAILABLE = "NO_VERIFIED_PM20520_CONNECTION_DIAGRAM"
RETRIEVAL_MODE = "tdc3000_pm20520_resolver"


def _unavailable(part: str, *, detail: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {
        "status": "evidence_unavailable",
        "requested_part": part,
        "reason": UNAVAILABLE,
        "retrieval_mode": RETRIEVAL_MODE,
    }
    if detail:
        out["detail"] = detail
    return out


@lru_cache(maxsize=1)
def load_index() -> dict[str, Any]:
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def classify_artifact(query: object, artifact: object = "") -> str:
    explicit = str(artifact or "").strip().lower()
    if explicit in SCHEMATIC_ARTIFACTS:
        return explicit
    q = str(query or "").lower()
    if re.search(r"\bfta\s+connection\b|\bfta\s+diagram\b", q):
        return "fta_connection"
    if re.search(r"\bconnection\s+diagram\b", q):
        return "connection_diagram"
    if re.search(r"\bwiring\s+schematic\b|\bwiring\s+diagram\b|\bschematic\b|\bwiring\b", q):
        return "wiring_schematic"
    return ""


def parse_requested_part(text: object) -> tuple[str, str]:
    """Return (token, status) where status is validated|unvalidated_lookalike|none.

    Validated tokens keep exact MU vs MC identity. Lookalikes are never rewritten.
    """
    msg = str(text or "")
    found = [m.group(1).upper() for m in VALID_PART_RE.finditer(msg)]
    if found:
        return found[0], "validated"
    for m in LOOKALIKE_RE.finditer(msg):
        token = m.group(1).upper()
        if not VALID_PART_RE.search(token):
            return token, "unvalidated_lookalike"
    return "", "none"


def _fta_figures(index: dict[str, Any], fta: str) -> list[dict[str, Any]]:
    rec = (index.get("identifiers") or {}).get(fta) or {}
    return list(rec.get("connection_figures") or [])


def _verified_packet(
    *,
    part: str,
    index: dict[str, Any],
    figures: list[dict[str, Any]],
    diagram_target: str,
    relation: object,
) -> dict[str, Any]:
    primary = figures[0]
    return {
        "status": "verified",
        "requested_part": part,
        "source_document": index.get("source_document") or "pm20520.pdf",
        "source_path": index.get("source_path") or "",
        "diagram_target": diagram_target,
        "figure": primary.get("figure"),
        "printed_page": primary.get("printed_page"),
        "pdf_page": primary.get("pdf_page"),
        "caption_evidence": primary.get("caption_evidence"),
        "document_supported_identity_relation": relation,
        "retrieval_mode": RETRIEVAL_MODE,
        "figures": [
            {
                "figure": f.get("figure"),
                "printed_page": f.get("printed_page"),
                "pdf_page": f.get("pdf_page"),
                "caption_evidence": f.get("caption_evidence"),
                "diagram_target": f.get("diagram_target") or diagram_target,
            }
            for f in figures
        ],
    }


def resolve_pm20520_schematic(
    part_number: object,
    artifact: object = "wiring_schematic",
) -> dict[str, Any]:
    """Resolve a structured {part_number, artifact} request against PM20-520."""
    artifact_s = str(artifact or "wiring_schematic").strip().lower()
    if artifact_s not in SCHEMATIC_ARTIFACTS:
        artifact_s = "wiring_schematic"
    raw = str(part_number or "").strip().upper()
    part, kind = parse_requested_part(raw or str(part_number or ""))
    if kind == "unvalidated_lookalike":
        return _unavailable(part or raw, detail="unvalidated_identifier_not_rewritten")
    if kind != "validated" or not part:
        return _unavailable(raw, detail="unknown_or_unvalidated_identifier")

    index = load_index()
    rec = (index.get("identifiers") or {}).get(part)
    if not rec:
        return _unavailable(part, detail="identifier_not_in_pm20520")

    relation = None
    if part.startswith("MC-"):
        relation = rec.get("document_supported_identity_relation")

    figures = list(rec.get("connection_figures") or [])
    if not figures:
        counterpart = (relation or rec.get("document_supported_identity_relation") or {}).get(
            "counterpart"
        )
        other = (index.get("identifiers") or {}).get(counterpart or "") or {}
        if part.startswith("MC-") and other.get("connection_figures"):
            figures = list(other["connection_figures"])
            relation = rec.get("document_supported_identity_relation")
    if figures:
        return _verified_packet(
            part=part,
            index=index,
            figures=figures,
            diagram_target=f"{part} FTA",
            relation=relation if part.startswith("MC-") else None,
        )

    # IOP / other identities: wiring is on compatible FTA figures only.
    fta_models = list(rec.get("compatible_ftas") or [])
    gathered: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any]] = set()
    for fta in fta_models:
        for fig in _fta_figures(index, fta):
            key = (fig.get("figure"), fig.get("printed_page"), fig.get("pdf_page"))
            if key in seen:
                continue
            seen.add(key)
            item = dict(fig)
            item["diagram_target"] = f"{fta} FTA"
            gathered.append(item)
    if gathered:
        return _verified_packet(
            part=part,
            index=index,
            figures=gathered,
            diagram_target="compatible FTA connection diagrams",
            relation=relation,
        )

    return _unavailable(part, detail="recognized_without_verified_connection_diagram")


def retrieve_response_for_query(query: object, *, collection: str) -> dict[str, Any] | None:
    """Return a retrieve payload for PM20-520 schematic intents, else None.

    None means the generic retrieve path (including Allen-Bradley) should run.
    A dict, including evidence_unavailable, forbids vector/manual ranking.
    """
    q = str(query or "")
    if AB_PART_RE.search(q) and not VALID_PART_RE.search(q):
        return None
    artifact = classify_artifact(q)
    if artifact not in SCHEMATIC_ARTIFACTS:
        return None
    part, kind = parse_requested_part(q)
    if kind == "none":
        return None
    if kind == "unvalidated_lookalike":
        resolved = _unavailable(part, detail="unvalidated_identifier_not_rewritten")
    else:
        resolved = resolve_pm20520_schematic(part, artifact)
    matches: list[dict[str, Any]] = []
    if resolved.get("status") == "verified":
        for fig in resolved.get("figures") or [resolved]:
            matches.append(
                {
                    "source": resolved.get("source_path"),
                    "score": 1.0,
                    "match_kind": "verified_connection_diagram",
                    "part_number": resolved.get("requested_part"),
                    "retrieval": RETRIEVAL_MODE,
                    "revision": "PM20-520",
                    "figure": fig.get("figure"),
                    "printed_page": fig.get("printed_page"),
                    "pdf_page": fig.get("pdf_page"),
                    # PDF viewer page anchor and the explicit MC↔MU coating
                    # relationship are presentation evidence, not model
                    # inference.  Keep them on every figure packet so the
                    # document route can both explain the counterpart and
                    # open the verified diagram page.
                    "page_hint": fig.get("pdf_page"),
                    "document_supported_identity_relation": resolved.get(
                        "document_supported_identity_relation"
                    ),
                    "caption_evidence": fig.get("caption_evidence"),
                    "diagram_target": fig.get("diagram_target"),
                    "snippet": fig.get("caption_evidence") or "",
                    "document_identity": {
                        "title": "Process Manager I/O Installation",
                        "doc_no": "PM20-520",
                        "filename": "pm20520.pdf",
                    },
                }
            )
    return {
        "matches": matches,
        "collection": collection,
        "retrieval": RETRIEVAL_MODE,
        "pm20520_resolver": resolved,
    }
