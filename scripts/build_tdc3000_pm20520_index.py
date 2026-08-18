#!/usr/bin/env python3
"""Build the source-controlled PM20-520 resolver index from pm20520.pdf.

Reads the live Honeywell TDC library PDF. Does not use semantic RAG.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_PDF = Path(
    "/Users/rick/Mounts/RAG_Pool/Library/Vendor Data/Honeywell/Experian PKS/"
    "TDC3000/Honeywell TDC/pm20520.pdf"
)
DEFAULT_SOURCE_PATH = (
    "Vendor Data/Honeywell/Experian PKS/TDC3000/Honeywell TDC/pm20520.pdf"
)
REPO_API = Path(__file__).resolve().parents[1] / "api"

VALID_PART_RE = re.compile(r"\b((?:MU|MC)-[A-Z]{2,8}\d{2,}[A-Z]?)\b", re.IGNORECASE)
SLASH_PAIR_RE = re.compile(
    r"\b(MU|MC)-([A-Z]{2,8})(\d{2,})/(\d{2,})([A-Z])?\b",
    re.IGNORECASE,
)
FIG_LINE_RE = re.compile(r"^\s*Figure\s+(\d+-\d+)\.?\s*(.*)$", re.IGNORECASE)
COMPAT_RE = re.compile(
    r"The model\s+((?:MU|MC)-[A-Z]{2,8}\d{2,}[A-Z]?)\s+"
    r"(?:Digital Input |Digital Output |Analog Input |Analog Output |)"
    r"IOP is compatible with the model\s+(.+?)\s+FTAs?\b",
    re.IGNORECASE | re.DOTALL,
)
PDFTOTEXT = "/opt/homebrew/bin/pdftotext"


def pdf_page_texts(pdf_path: Path) -> list[str]:
    exe = PDFTOTEXT if os.path.isfile(PDFTOTEXT) else "pdftotext"
    proc = subprocess.run(
        [exe, "-layout", str(pdf_path), "-"],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "pdftotext failed")[:300])
    pages = str(proc.stdout or "").split("\f")
    while pages and not pages[-1].strip():
        pages.pop()
    if not pages:
        raise RuntimeError("pdftotext returned no pages")
    return pages


def printed_page_number(text: str) -> int | None:
    """Footer page number. Ignore the 3/98 issue date sitting on the same line."""
    for ln in reversed(text.splitlines()):
        if "Process Manager I/O Installation" not in ln:
            continue
        cleaned = re.sub(r"\b3/98\b", " ", ln)
        nums = [int(x) for x in re.findall(r"\b(\d{1,3})\b", cleaned) if 1 <= int(x) <= 500]
        return nums[-1] if nums else None
    return None


def expand_models(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(token: str) -> None:
        norm = token.strip().upper()
        if norm and norm not in seen:
            seen.add(norm)
            found.append(norm)

    for m in SLASH_PAIR_RE.finditer(text):
        prefix, family, a, b, suffix = m.groups()
        suffix = suffix or ""
        add(f"{prefix.upper()}-{family.upper()}{a}{suffix}")
        add(f"{prefix.upper()}-{family.upper()}{b}{suffix}")
    for m in VALID_PART_RE.finditer(text):
        add(m.group(1))
    return found


def caption_blocks(page_text: str) -> list[tuple[str, str]]:
    lines = page_text.splitlines()
    out: list[tuple[str, str]] = []
    for i, ln in enumerate(lines):
        m = FIG_LINE_RE.match(ln)
        if not m:
            continue
        fig = m.group(1)
        buf = [m.group(2).strip()]
        for nxt in lines[i + 1 : i + 5]:
            if FIG_LINE_RE.match(nxt):
                break
            s = nxt.strip()
            if s:
                buf.append(s)
        caption = re.sub(r"\s+", " ", " ".join(buf)).strip()
        out.append((fig, caption))
    return out


def is_toc_caption(caption: str) -> bool:
    return bool(re.search(r"\.{4,}|_{4,}", caption))


def is_connection_diagram(caption: str) -> bool:
    low = caption.lower()
    if "assembly layout" in low and "connection diagram" not in low:
        return False
    return "connection diagram" in low


def extract_identity_evidence(pages: list[str]) -> str:
    blob = "\n".join(pages[:40])
    m = re.search(
        r"Conformally coated models of the FTAs and IOPs are identified.{0,280}prefix [“\"]MU[.”\"].",
        blob,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        m = re.search(r"Conformal coating.{0,700}prefix [“\"]MU[.”\"].", blob, re.I | re.S)
    return re.sub(r"\s+", " ", m.group(0)).strip() if m else ""


def extract_compat(pages: list[str]) -> dict[str, dict[str, Any]]:
    blob = "\n".join(pages)
    out: dict[str, dict[str, Any]] = {}
    for m in COMPAT_RE.finditer(blob):
        iop = m.group(1).upper()
        rest = re.sub(r"\s+", " ", m.group(2))
        ftas = expand_models(rest)
        evidence = re.sub(r"\s+", " ", m.group(0))[:500]
        rec = out.setdefault(iop, {"compatible_ftas": [], "evidence": evidence})
        for fta in ftas:
            if fta not in rec["compatible_ftas"]:
                rec["compatible_ftas"].append(fta)
    return out


def classify_kind(part: str, figures: list[dict[str, Any]], compat: dict[str, Any], blob: str) -> str:
    if part in compat:
        return "iop"
    if figures:
        return "fta"
    # Table rows often say "DI IOP" / "FTA" after the model.
    rx = re.compile(rf"{re.escape(part)}\s+([A-Z0-9 /,—-]{{0,80}})", re.I)
    iop_hits = 0
    fta_hits = 0
    for m in rx.finditer(blob):
        tail = m.group(1).lower()
        if "iop" in tail:
            iop_hits += 1
        if "fta" in tail:
            fta_hits += 1
    if iop_hits > fta_hits:
        return "iop"
    if fta_hits > 0:
        return "fta"
    return "unclassified"


def build_index(pdf_path: Path, source_path: str) -> dict[str, Any]:
    pages = pdf_page_texts(pdf_path)
    blob = "\n".join(pages)
    identity_evidence = extract_identity_evidence(pages)
    compat = extract_compat(pages)

    figures_by_model: dict[str, list[dict[str, Any]]] = {}
    all_figures: list[dict[str, Any]] = []
    for pdf_page, text in enumerate(pages, 1):
        printed = printed_page_number(text)
        if printed is None or printed < 20:
            continue
        for fig, caption in caption_blocks(text):
            if is_toc_caption(caption) or not is_connection_diagram(caption):
                continue
            if not re.match(r"Model\s+(?:MU|MC)-", caption, re.IGNORECASE):
                continue
            models = expand_models(caption)
            rec = {
                "figure": fig,
                "printed_page": printed,
                "pdf_page": pdf_page,
                "caption_evidence": caption[:400],
                "models": models,
            }
            all_figures.append(rec)
            for model in models:
                bucket = figures_by_model.setdefault(model, [])
                key = (fig, printed, pdf_page)
                if not any((x["figure"], x["printed_page"], x["pdf_page"]) == key for x in bucket):
                    bucket.append(rec)

    recognized = expand_models(blob)
    identifiers: dict[str, Any] = {}
    for part in recognized:
        figs = [
            {
                "figure": f["figure"],
                "printed_page": f["printed_page"],
                "pdf_page": f["pdf_page"],
                "caption_evidence": f["caption_evidence"],
                "diagram_target": f"{part} FTA",
            }
            for f in figures_by_model.get(part, [])
        ]
        prefix = part[:2]
        body = part[3:]
        counterpart = f"{'MC' if prefix == 'MU' else 'MU'}-{body}"
        counterpart_present = counterpart in set(recognized)
        relation = None
        if counterpart_present and identity_evidence:
            relation = {
                "requested": part,
                "counterpart": counterpart,
                "relation": "mc_conformally_coated_mu_noncoated",
                "evidence": identity_evidence,
            }
        kind = classify_kind(part, figs, compat, blob)
        entry: dict[str, Any] = {
            "part_number": part,
            "kind": kind,
            "connection_figures": figs,
            "document_supported_identity_relation": relation,
        }
        if part in compat:
            entry["compatible_ftas"] = compat[part]["compatible_ftas"]
            entry["compatibility_evidence"] = compat[part]["evidence"]
        identifiers[part] = entry

    for part, rec in identifiers.items():
        if rec.get("compatible_ftas"):
            continue
        rel = rec.get("document_supported_identity_relation") or {}
        other = identifiers.get(rel.get("counterpart") or "")
        if not other or not other.get("compatible_ftas"):
            continue
        rec["compatible_ftas"] = list(other["compatible_ftas"])
        rec["compatibility_inherited_from"] = other["part_number"]
        rec["compatibility_evidence"] = (
            f"{rel.get('evidence') or ''} {other.get('compatibility_evidence') or ''}"
        ).strip()
        if rec.get("kind") == "unclassified":
            rec["kind"] = other.get("kind") or rec["kind"]

    coverage = build_coverage(identifiers)
    return {
        "source_document": "pm20520.pdf",
        "doc_no": "PM20-520",
        "title": "Process Manager I/O Installation",
        "source_path": source_path,
        "pdf_page_count": len(pages),
        "identity_rules": {
            "mu_mc_are_distinct": True,
            "mc_is_conformally_coated": True,
            "manual_generally_references_mu": True,
            "evidence": identity_evidence,
        },
        "connection_diagram_count": len(all_figures),
        "identifiers": identifiers,
        "coverage": coverage,
    }


def build_coverage(identifiers: dict[str, Any]) -> dict[str, Any]:
    verified: list[str] = []
    via_counterpart: list[str] = []
    iop_via_fta: list[str] = []
    recognized_no_figure: list[str] = []

    def fta_has_figures(fta: str) -> bool:
        rec = identifiers.get(fta) or {}
        if rec.get("connection_figures"):
            return True
        rel = rec.get("document_supported_identity_relation") or {}
        other = identifiers.get(rel.get("counterpart") or "") or {}
        return bool(other.get("connection_figures"))

    for part, rec in sorted(identifiers.items()):
        figs = rec.get("connection_figures") or []
        if figs:
            verified.append(part)
            continue
        rel = rec.get("document_supported_identity_relation") or {}
        other = identifiers.get(rel.get("counterpart") or "") or {}
        if part.startswith("MC-") and other.get("connection_figures"):
            via_counterpart.append(part)
            continue
        ftas = rec.get("compatible_ftas") or []
        if rec.get("kind") == "iop" and ftas and any(fta_has_figures(fta) for fta in ftas):
            iop_via_fta.append(part)
            continue
        recognized_no_figure.append(part)
    return {
        "recognized_count": len(identifiers),
        "verified_connection_diagram": verified,
        "verified_via_document_supported_mc_mu_counterpart": via_counterpart,
        "iop_with_verified_compatible_fta_figures": iop_via_fta,
        "recognized_without_verified_connection_diagram": recognized_no_figure,
        "note": (
            "recognized_without_verified_connection_diagram must not be answered "
            "by generic RAG, planning manuals, or compatibility-table-only hits."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--source-path", default=DEFAULT_SOURCE_PATH)
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_API / "tdc3000_pm20520_index.json",
    )
    parser.add_argument(
        "--coverage-out",
        type=Path,
        default=REPO_API / "tdc3000_pm20520_coverage.json",
    )
    args = parser.parse_args()
    index = build_index(args.pdf, args.source_path)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    coverage = {
        "source_document": index["source_document"],
        "source_path": index["source_path"],
        **index["coverage"],
    }
    args.coverage_out.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    print(f"wrote {args.coverage_out}")
    print(
        "recognized={recognized_count} verified={v} iop_via_fta={i} no_figure={n}".format(
            recognized_count=coverage["recognized_count"],
            v=len(coverage["verified_connection_diagram"]),
            i=len(coverage["iop_with_verified_compatible_fta_figures"]),
            n=len(coverage["recognized_without_verified_connection_diagram"]),
        )
    )


if __name__ == "__main__":
    main()
