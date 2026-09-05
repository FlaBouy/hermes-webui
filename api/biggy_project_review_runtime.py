"""Project Review dialog runtime helpers — bounded context, progress, status vs action.

Presentation and turn-binding only. Cancels go through scoped dialog cancel endpoints.
Preserves full saved session history; agent-facing binding overrides obsolete paths.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from api.project_review_awareness import build_review_awareness

# Known TEST-ONLY fixtures. Leave files in place; never treat as production findings.
_SAMPLE_ONLY_MARKERS = (
    "12-1-0104.pdf",
    "sk-26br-102-03 interconnects.dxf",
    "sk-26br-102-03_interconnects.dxf",
    "sk-26br-102-03",
)

# Status = past-result inquiry about prior work (incl. have/did you run variants).
# Clause-scoped: status when every clause is a status inquiry, status-only marker,
# or negated work; any positive execute/directive clause → not status.
_STATUS_INQUIRY_CLAUSE = re.compile(
    r"(?i)^\s*(?:"
    r"have\s+you\s+(?:run|ran|finished|completed|done|already\s+(?:run|ran|finished|done|completed))\b.+"
    r"|"
    r"did\s+you\s+(?:run|ran|finish|complete|already\s+(?:run|finish|complete))\b.+"
    r"|"
    r"did\s+(?:the\s+)?(?:re-?tests?|extract(?:ion)?s?|ocr|review)\b.+"
    r"|"
    r"what\s+(?:is|was|were)\s+(?:the\s+)?(?:status|progress|result|outcome)\b.+"
    r"|"
    r"(?:status|progress)\s+(?:update|check|report|only)\b.*"
    r"|"
    r"status\s+only\b.*"
    r"|"
    r"(?:any|what)\s+(?:progress|results?|updates?)\b.+"
    r")\s*[?]?\s*$"
)

# Split sentences; also split before a comma-introduced positive directive so
# negation does not bleed across ("Do not just report status, rerun …").
_REVIEW_CLAUSE_SPLIT = re.compile(
    r"(?:[.!?;]+\s*)|\n+"
    r"|(?:,\s*)(?=(?:please|re-run|rerun|run\b|extract\b|verify\b|delete\b|"
    r"go\s+ahead|if\s+not)\b)"
)

_NEGATED_CLAUSE_PREFIX = re.compile(
    r"(?i)^\s*(?:please\s+)?(?:do\s+not|don't|dont|never)\b"
)

# Positive execute. Do NOT use re-?run — optional "re-" matches bare "run" and
# falsely forces execute on "Have you run …?".
_STATUS_ACTION_CLAUSE = re.compile(
    r"(?i)\b(?:"
    r"please|delete|verify|extract|re-run|rerun|re\s+run|and\s+then|go\s+ahead|"
    r"run\s+(?:it|them|again|now)|do\s+(?:the\s+)?(?:re-?tests?|extract)"
    r")\b"
)

_FORCE_EXECUTE = re.compile(
    r"(?i)\b(?:"
    r"re-run|rerun|re\s+run|"
    r"run\s+(?:it|them|again|now)|extract\s+again|"
    r"please\s+(?:run|extract|re-run|rerun)|"
    r"go\s+ahead\s+and\s+(?:run|extract|re-run|rerun)|"
    r"do\s+(?:the\s+)?(?:re-?tests?|extract)"
    r")\b"
)

_AND_WORK_CLAUSE = re.compile(
    r"(?i)\band\b.+\b(?:run|extract|verify|delete|re-?test|re-run|rerun)\b"
)

_IF_NOT_EXECUTE = re.compile(
    r"(?i)\bif\s+not\b.+\b(?:run|extract|re-run|rerun|verify|delete)\b"
)

# Soft between-call budgets (do not auto-kill an in-flight OCR tool).
REVIEW_TOOL_COMPLETE_BUDGET = 40
REVIEW_PATH_FAIL_STREAK = 5
REVIEW_STALL_IDLE_SECONDS = 900
REVIEW_MAX_ITERATIONS = 48
# Agent-facing compact context: plain user/assistant only (no tool protocol).
REVIEW_CONTEXT_MAX_CHARS = 48_000
REVIEW_CONTEXT_MAX_MESSAGES = 40
_PROGRESS_EVENTS = frozenset({"tool", "tool_complete", "interim_assistant"})
ELECTRICAL_REVIEW_POLICY = (
    "Owner electrical policy: voltage-drop calculations must target 2.5% or below unless Rick explicitly directs another target; preserve an explicit 2% follow-up. This is owner policy, not a claim that NEC mandates 2.5%. "
    "Verified cable reference: Southwire SPEC45253 is 3C copper XHHW-2/CPE TC-ER + ground, listed by the manufacturer for wet/dry locations, sunlight exposure and direct burial (verify purchased marking). "
    "Source: https://www.southwire.com/wire-cable/power-control/cu-600-1000v-xlpe-insulation-thermoplastic-cpe-tp-jacket-xhhw-2-ct-rated-sunlight-resistant-for-direct-burial-silicone-free/p/SPEC45253 . "
    "The prior claim that TC-ER cannot be used outdoors was false for this selected product. TC-ER alone does not establish every cable's environmental ratings; Allied substitutions need their exact datasheet. "
    "Do not calculate conductor size or voltage drop by guessing, mental arithmetic, or invented tables. Use the deterministic electrical service at http://127.0.0.1:8801/tools with saved owner inputs and explicit assumptions; never reuse an earlier assistant estimate as verified evidence. "
    "The validated electrical calculators support copper conductors only. Aluminum conductors are unsupported; do not estimate them or substitute copper. Aluminum tray or conduit is support material, not conductor material. "
    "A short follow-up modifies the prior circuit, not the whole project review. Preserve voltage, load, length, cable and installation conditions unless the owner changes them."
)
_PROGRESS_CACHE_LOCK = threading.RLock()
_PROGRESS_CACHE_MAX = 32
_PROGRESS_CACHE: OrderedDict[tuple, dict[str, Any]] = OrderedDict()
# One-shot review turn bindings (not persisted on session JSON — worker pops).
_REVIEW_TURN_BINDINGS_LOCK = threading.RLock()
_REVIEW_TURN_BINDINGS: dict[str, dict[str, Any]] = {}
_REASONING_KEYS = frozenset(
    {
        "reasoning",
        "reasoning_content",
        "reasoning_details",
        "reasoning_text",
        "_reasoning",
        "thinking",
        "thought",
        "encrypted_content",
        "encrypted_reasoning",
    }
)


def is_sample_only_source(path: str | None) -> bool:
    """True when basename matches known TEST-ONLY fixtures."""
    name = os.path.basename(str(path or "")).strip().lower().replace("_", " ")
    compact = name.replace(" ", "")
    for marker in _SAMPLE_ONLY_MARKERS:
        m = marker.replace("_", " ")
        if m in name or m.replace(" ", "") in compact:
            return True
    return False


def sample_only_policy_block() -> str:
    return (
        "Sample-only fixtures (NOT production findings; leave originals in place):\n"
        "  - 12-1-0104.pdf\n"
        "  - SK-26BR-102-03 Interconnects.dxf\n"
        "If extracted, label sample_only=true and never fold into Hosford production findings.\n"
    )


def build_dialogue_project_context(
    *,
    project: dict,
    review: dict,
    readiness: dict | None,
    planning: bool = False,
) -> str:
    """Compact conversation context for Project Review fast/dialogue turns.

    Omits MCP path policy, execution budgets, and extract-tool instructions that
    push the light model to invent inventories or claim work is starting.
    """
    readiness = readiness if isinstance(readiness, dict) else {}
    rag = str(review.get("rag_folder") or "").strip() or "not yet assigned"
    scope = str(review.get("scope") or "").strip() or (
        "Perform governance, compliance, and design error review."
    )
    evidence_state = str(readiness.get("state") or "unknown").upper()
    evidence_reason = str(readiness.get("reason") or "No current ingestion decision.")
    lines = [
        "Project-review conversation context (dialogue only):",
        ELECTRICAL_REVIEW_POLICY,
        build_review_awareness(review),
        f"project_id: {project.get('project_id')}",
        f"Project: {project.get('name') or 'Project review'}",
        f"Review type: {review.get('review_type') or 'internal-design'}",
        f"Canonical RAG folder: {rag}",
        f"Review scope: {scope}",
        f"Evidence readiness: {evidence_state} — {evidence_reason}",
        "Evidence warning: OCR-derived and extracted values remain unverified until "
        "the evidence gate says otherwise. Do not approve or sign off.",
        "Verification gates apply to approval, not to discussion or preparing a "
        "provisional worksheet with uncertain values clearly marked. Do not insist "
        "on another extraction or verification before accepting the owner's parameters.",
        "Turn intent: DIALOGUE ONLY — respond and clarify. Do not call tools, do not "
        "inspect or open project files, and do not start OCR/DXF/extraction.",
        "Do not invent missing details, mappings, counts, table inventories, or "
        "verification claims.",
        "When discussing the owner's forthcoming worksheet specification, ask for "
        "the desired columns, included data, grouping/calculation rules and output "
        "format as relevant. Do not substitute old assumptions for that specification.",
    ]
    if planning:
        lines.extend(
            [
                "Planning mode: the owner is asking about capability or offering "
                "parameters later. Acknowledge capability briefly and ask for the "
                "new parameters needed.",
                "Do not enumerate source/table/row inventories from memory or history, "
                "do not invent column mappings, and do not introduce findings.",
            ]
        )
    else:
        lines.append(
            "If the owner asks about prior results already in this conversation, "
            "answer from that context without inventing additional inventory."
        )
    return "\n".join(lines) + "\n\n"


def build_canonical_project_context(
    *,
    project: dict,
    review: dict,
    readiness: dict | None,
    sources: dict | None = None,
    intent: str = "execute",
) -> str:
    """Canonical binding that must outrank obsolete paths in prior transcript turns.

    Dialogue/fast turns must use ``build_dialogue_project_context`` instead — this
    full MCP/path/execution block is for governed (and status preamble) only.
    """
    if intent == "dialogue":
        # Fail closed to compact dialogue context if a caller still passes dialogue.
        return build_dialogue_project_context(
            project=project, review=review, readiness=readiness, planning=False
        )
    sources = sources if isinstance(sources, dict) else {}
    readiness = readiness if isinstance(readiness, dict) else {}
    rag = str(review.get("rag_folder") or "").strip() or "not yet assigned"
    scope = str(review.get("scope") or "").strip() or (
        "Perform governance, compliance, and design error review."
    )
    lines = [
        "Project-review context for this reply (CANONICAL — overrides any older path in history):",
        ELECTRICAL_REVIEW_POLICY,
        build_review_awareness(review),
        f"project_id: {project.get('project_id')}",
        f"Project: {project.get('name') or 'Project review'}",
        f"Review type: {review.get('review_type') or 'internal-design'}",
        f"Canonical RAG folder: {rag}",
        f"Review scope: {scope}",
        "Path forms for project_review_extract path= : (1) basename or path relative to the "
        "Canonical RAG folder; (2) full library-relative path that begins with that Canonical "
        "RAG folder (server strips the folder prefix — do not double-join); (3) absolute path "
        "already inside that folder. Rejected: '..', symlink escape, Library/ prefixed double "
        "joins, and any path outside the canonical folder.",
        "Path precedence: use ONLY the Canonical RAG folder above. Ignore obsolete "
        "'Project Reviews/…' or relocated paths recalled from earlier turns unless they "
        "exactly match this canonical folder.",
        "Extraction policy: use MCP tools project_review_extract_capabilities / "
        "project_review_extract (server smedley_project_review) for document extraction. "
        "Do not bypass MCP with scratch scripts under /tmp, ad-hoc Python OCR drivers, "
        "or unmanaged terminal re-implementations of the extractors.",
        f"Execution budget: at most {REVIEW_TOOL_COMPLETE_BUDGET} tool completions this turn "
        f"(agent max_iterations cap {REVIEW_MAX_ITERATIONS}). After budget or repeated path "
        "failures, stop and report — do not open scratch terminals. Do not kill an in-flight "
        "OCR/extract mid-file; finish or await owner cancel.",
        "Tool output policy: prefer concise evidence refs (evidence_dir, source_sha256, "
        "ocr_verification_state, cells_verified, quality_state). Do not dump raw OCR grids "
        "or full JSON manifests into the owner-visible reply.",
        sample_only_policy_block().rstrip(),
        (
            "Capability facts: Raster PDF tables require table-aware OCR and independent "
            "cell-level verification via the MCP extract tools. DXF is parsed by the local "
            "ezdxf Project Review extractor when provisioned. DWG and RVT are not directly readable "
            "in the current Biggy/Smedley runtime and require a governed conversion "
            "or native export first. Never claim a CAD converter, parser, or OCR engine is "
            "installed unless this turn called project_review_extract_capabilities."
        ),
        (
            "Continue the engineering discussion when evidence needs review, but label "
            "OCR-derived values as unverified and do not approve or sign off until the "
            "evidence gate is verified."
        ),
        f"Evidence readiness: {str(readiness.get('state') or 'unknown').upper()} — "
        f"{readiness.get('reason') or 'No current ingestion decision.'}",
    ]
    if intent == "status_report":
        lines.extend(
            [
                "Turn intent: STATUS REPORT ONLY.",
                "Answer from prior tool results / evidence already in this review session.",
                "Do not call project_review_extract, do not re-run OCR/DXF, and do not start "
                "a new full-project pass unless the owner explicitly orders a re-run.",
                "If prior results are incomplete, say what finished, what failed, and what "
                "remains — without inventing pending work.",
            ]
        )
    else:
        lines.extend(
            [
                "Turn intent: GOVERNED EXECUTION when the owner asks for work.",
                "Discussion and extraction are allowed while evidence needs review; do not "
                "approve or sign off until the evidence gate is verified.",
            ]
        )
    if sources:
        lines.append(
            "Configured sources (reference only):\n"
            f"  plant_specifications: {sources.get('plant_specifications') or 'not provided'}\n"
            f"  code_books: {sources.get('code_books') or 'not provided'}\n"
            f"  design_package: {sources.get('design_package') or 'not provided'}"
        )
    return "\n".join(lines) + "\n\n"


def _split_review_status_clauses(text: str) -> list[str]:
    return [part.strip() for part in _REVIEW_CLAUSE_SPLIT.split(text) if part and part.strip()]


def _clause_has_positive_execute(clause: str) -> bool:
    """True when the clause directs work that is not under a leading negation."""
    value = str(clause or "").strip()
    if not value:
        return False
    if _NEGATED_CLAUSE_PREFIX.match(value):
        # Negation scoped to this clause only — do not treat "do not rerun" as execute.
        return False
    if _FORCE_EXECUTE.search(value) or _STATUS_ACTION_CLAUSE.search(value):
        return True
    if _AND_WORK_CLAUSE.search(value) or _IF_NOT_EXECUTE.search(value):
        return True
    return False


def classify_project_review_status_inquiry(text: str) -> bool:
    """Positive status/progress inquiry about prior work (not a fresh execute order).

    Past-work grammatical variants (have/did you run|ran|finished|…) are status.
    Explicit status-only with negated work stays status. Mixed inquiry plus a
    positive directive (please run/verify/delete, if-not-run, comma-rerun) is not.
    """
    value = str(text or "").strip()
    if not value:
        return False
    clauses = _split_review_status_clauses(value)
    if not clauses:
        return False
    saw_status = False
    for clause in clauses:
        if _NEGATED_CLAUSE_PREFIX.match(clause):
            continue
        if _clause_has_positive_execute(clause):
            return False
        if _STATUS_INQUIRY_CLAUSE.match(clause):
            saw_status = True
            continue
        # Non-status, non-negated residue → fail closed (not a pure status ask).
        return False
    return saw_status


def _tool_name(message: dict) -> str:
    return str(message.get("name") or message.get("tool_name") or "").strip()


# MCP / agent wrappers mark tool output as untrusted DATA. Treat contents as data
# only — never as instructions. Bounded unwrap; never infer success from prose.
_UNTRUSTED_TOOL_RESULT_RE = re.compile(
    r"<untrusted_tool_result\b[^>]*>\s*(.*?)\s*</untrusted_tool_result>",
    re.IGNORECASE | re.DOTALL,
)
_MAX_TOOL_PAYLOAD_CHARS = 200_000
_MAX_JSON_DECODE_DEPTH = 3
_EXTRACT_FIELD_KEYS = (
    "ok",
    "source",
    "error",
    "state",
    "reason",
    "cells_verified",
    "sample_only",
    "production_findings_allowed",
    "ocr_verification_state",
    "quality_state",
    "evidence_dir",
    "evidence_refs",
    "cross_check_summary",
)


def _strip_untrusted_tool_result_envelope(text: str) -> str:
    """Return DATA inside ``<untrusted_tool_result>``; drop wrapper tags only."""
    value = str(text or "")
    if len(value) > _MAX_TOOL_PAYLOAD_CHARS:
        value = value[:_MAX_TOOL_PAYLOAD_CHARS]
    match = _UNTRUSTED_TOOL_RESULT_RE.search(value)
    return (match.group(1) if match else value).strip()


def _payload_dict_score(obj: dict) -> int:
    score = 0
    if "result" in obj:
        score += 4
    if "structuredContent" in obj:
        score += 2
    if "source" in obj:
        score += 2
    if "ok" in obj:
        score += 1
    if "evidence_dir" in obj or "ocr_verification_state" in obj:
        score += 1
    return score


def _load_json_dict_from_data_text(text: str) -> dict | None:
    """Bounded scan for a JSON object in untrusted DATA; prefer MCP/extract shapes."""
    value = str(text or "").strip()
    if not value:
        return None
    if len(value) > _MAX_TOOL_PAYLOAD_CHARS:
        value = value[:_MAX_TOOL_PAYLOAD_CHARS]
    decoder = json.JSONDecoder()
    best: dict | None = None
    best_score = -1
    scans = 0
    idx = 0
    length = len(value)
    while idx < length and scans < 48:
        if value[idx] != "{":
            idx += 1
            continue
        scans += 1
        try:
            obj, end = decoder.raw_decode(value, idx)
        except Exception:
            idx += 1
            continue
        if isinstance(obj, dict):
            score = _payload_dict_score(obj)
            if score >= best_score:
                best = obj
                best_score = score
            idx = end if end > idx else idx + 1
            continue
        idx = end if isinstance(end, int) and end > idx else idx + 1
    return best


def _bounded_json_loads(value: Any, *, depth: int = 0) -> Any:
    """Decode JSON strings up to a small depth; leave non-JSON unchanged."""
    if depth >= _MAX_JSON_DECODE_DEPTH:
        return value
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "{[":
        return value
    if len(text) > _MAX_TOOL_PAYLOAD_CHARS:
        text = text[:_MAX_TOOL_PAYLOAD_CHARS]
    try:
        parsed = json.loads(text)
    except Exception:
        return value
    if isinstance(parsed, str):
        return _bounded_json_loads(parsed, depth=depth + 1)
    return parsed


def _promote_extract_fields(envelope: dict, inner: dict) -> dict:
    """Expose extract fields at top level when MCP wraps them under ``result``."""
    out = dict(envelope)
    out["result"] = inner
    for key in _EXTRACT_FIELD_KEYS:
        if key not in out or out.get(key) in (None, ""):
            if key in inner:
                out[key] = inner[key]
    return out


def _parse_tool_payload(raw: Any) -> dict:
    """Parse tool content as untrusted DATA only (envelope + nested JSON-string result)."""
    if isinstance(raw, dict):
        parsed: Any = raw
    else:
        text = raw if isinstance(raw, str) else json.dumps(raw, default=str)
        text = _strip_untrusted_tool_result_envelope(str(text or ""))
        if not text:
            return {}
        loaded = _load_json_dict_from_data_text(text)
        if loaded is None:
            return {"_unparsed": text[:240]}
        parsed = loaded

    if not isinstance(parsed, dict):
        return {"_unparsed": str(parsed)[:240]}

    result = parsed.get("result")
    decoded = _bounded_json_loads(result, depth=0)
    if isinstance(decoded, dict):
        return _promote_extract_fields(parsed, decoded)

    # Some adapters nest the same payload under structuredContent.result
    structured = parsed.get("structuredContent")
    if isinstance(structured, dict):
        sc_result = _bounded_json_loads(structured.get("result"), depth=0)
        if isinstance(sc_result, dict):
            return _promote_extract_fields(parsed, sc_result)
    return parsed


def format_extract_evidence_line(
    content: Any,
    *,
    tool_name: str = "",
    is_error: bool | None = None,
) -> str:
    """Readable one-line evidence summary preserving safety fields (no raw JSON dump)."""
    parsed = _parse_tool_payload(content)
    nested = parsed.get("result") if isinstance(parsed.get("result"), dict) else {}
    source = str(parsed.get("source") or nested.get("source") or "").strip()
    base = os.path.basename(source) if source else ""
    ok = parsed.get("ok")
    if ok is None:
        ok = nested.get("ok")
    if is_error is True and ok is not True:
        # Preserve tool-level isError without inventing success.
        ok = False
    sample_only = bool(
        parsed.get("sample_only")
        or nested.get("sample_only")
        or is_sample_only_source(source)
        or is_sample_only_source(base)
    )
    prod_ok = parsed.get("production_findings_allowed")
    if prod_ok is None:
        prod_ok = nested.get("production_findings_allowed")
    if sample_only:
        prod_ok = False
    cells = parsed.get("cells_verified")
    if cells is None:
        cells = nested.get("cells_verified")
    if cells is None and isinstance(parsed.get("cross_check_summary"), dict):
        cells = parsed["cross_check_summary"].get("cells_verified")
    if cells is None and isinstance(nested.get("cross_check_summary"), dict):
        cells = nested["cross_check_summary"].get("cells_verified")
    ocr = parsed.get("ocr_verification_state") or nested.get("ocr_verification_state")
    refs = parsed.get("evidence_refs") if isinstance(parsed.get("evidence_refs"), dict) else {}
    if not refs and isinstance(nested.get("evidence_refs"), dict):
        refs = nested["evidence_refs"]
    if not ocr:
        ocr = refs.get("ocr_verification_state")
    quality = parsed.get("quality_state") or nested.get("quality_state") or refs.get("quality_state")
    state = parsed.get("state") or nested.get("state") or ""
    error = str(
        parsed.get("error") or nested.get("error") or nested.get("reason") or parsed.get("reason") or ""
    ).strip()
    if is_error is True and not error and ok is False:
        error = "tool is_error"
    evidence_dir = str(parsed.get("evidence_dir") or nested.get("evidence_dir") or "").strip()
    evidence_base = os.path.basename(evidence_dir.rstrip("/")) if evidence_dir else ""

    label = (tool_name or "tool").split("__")[-1]
    if sample_only:
        disposition = "SAMPLE-ONLY (not production findings)"
    elif ok is True and cells is True:
        disposition = "success (cells_verified=true)"
    elif ok is True and (str(ocr).lower() in {"needs_review", "unverified", "failed", "structure_unverified"} or cells is False):
        disposition = "completed but UNVERIFIED"
    elif ok is True:
        disposition = "completed"
    elif ok is False:
        disposition = f"FAILED ({error or state or 'error'})"
    else:
        disposition = f"unknown ({error or state or 'not treated as success'})"

    bits = [f"{label}: {disposition}"]
    if base:
        bits.append(f"file={base}")
    if state:
        bits.append(f"state={state}")
    if ocr:
        bits.append(f"ocr={ocr}")
    if quality:
        bits.append(f"quality={quality}")
    if cells is not None:
        bits.append(f"cells_verified={cells}")
    if sample_only:
        bits.append("sample_only=true")
    if prod_ok is False:
        bits.append("production_findings_allowed=false")
    if evidence_base:
        bits.append(f"evidence={evidence_base}")
    return " · ".join(bits)


def summarize_prior_review_results(messages: list | None, *, limit: int = 8) -> str:
    """Owner-facing digest of prior extract outcomes (readable, safety fields retained)."""
    rows: list[str] = []
    for message in reversed(list(messages or [])):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "") != "tool":
            continue
        name = _tool_name(message)
        if "project_review_extract" not in name and "capabilities" not in name:
            continue
        line = format_extract_evidence_line(
            message.get("content"),
            tool_name=name,
            is_error=bool(message.get("is_error") or message.get("isError")),
        )
        if not line:
            continue
        rows.append(f"- {line}")
        if len(rows) >= limit:
            break
    rows.reverse()
    if not rows:
        return (
            "No persisted project_review_extract tool results were found in this "
            "review session yet."
        )
    return "Prior extract / capability results in this review session:\n" + "\n".join(rows)


def build_status_report_reply(messages: list | None, *, owner_message: str = "") -> str:
    """Deterministic status reply — no LLM polish (avoids latency / hallucination)."""
    digest = summarize_prior_review_results(messages)
    header = "Status report (prior results only — no new extract/re-run started):"
    note = (
        "Ask explicitly to re-run or extract if you want another full governed pass."
    )
    owner = str(owner_message or "").strip()
    if owner:
        return f"{header}\nOwner asked: {owner}\n\n{digest}\n\n{note}"
    return f"{header}\n\n{digest}\n\n{note}"


def _owner_decision_summaries(messages: list, *, limit: int = 12) -> list[str]:
    rows: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "") != "user":
            continue
        text = _plain_text_content(message.get("content")).strip()
        if not text:
            continue
        if "Owner message:" in text:
            text = text.split("Owner message:", 1)[-1].strip()
        if text.startswith("Project-review context for this reply"):
            continue
        if text.startswith("Retained owner decisions"):
            continue
        if text.startswith("[Prior tool evidence"):
            continue
        rows.append(text[:400] + ("…" if len(text) > 400 else ""))
    if len(rows) > limit:
        rows = rows[:2] + ["…"] + rows[-(limit - 2) :]
    return rows


def _plain_text_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                if part.get("type") == "text" or "text" in part:
                    parts.append(_plain_text_content(part.get("text")))
                elif "content" in part:
                    parts.append(_plain_text_content(part.get("content")))
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        if "text" in content:
            return str(content.get("text") or "")
        if "content" in content:
            return _plain_text_content(content.get("content"))
        return json.dumps(content, default=str)[:500]
    return str(content)


def _serialized_chars(messages: list[dict]) -> int:
    try:
        return len(json.dumps(messages, default=str))
    except Exception:
        return sum(len(str(m)) for m in messages)


def build_review_agent_context_messages(
    messages: list | None,
    *,
    max_messages: int = REVIEW_CONTEXT_MAX_MESSAGES,
    max_chars: int = REVIEW_CONTEXT_MAX_CHARS,
    tool_content_limit: int = 1200,
) -> list[dict]:
    """Agent-facing compact view. Does not mutate the saved session transcript.

    Converts ALL historical tool-call blocks into labeled plain evidence summaries.
    Outbound history is user/assistant text only — never role=tool or tool_calls
    protocol metadata (avoids parallel-tool ID mismatch / invalid truncated JSON).
    Strips reasoning/internal fields and enforces a total serialized char budget.
    """
    del tool_content_limit  # retained for call-site compatibility; evidence lines are bounded
    source = [m for m in list(messages or []) if isinstance(m, dict)]
    decisions = _owner_decision_summaries(source)
    flattened: list[dict] = []
    i = 0
    while i < len(source):
        msg = source[i]
        role = str(msg.get("role") or "")
        if role == "assistant" and msg.get("tool_calls"):
            tool_calls = msg.get("tool_calls") if isinstance(msg.get("tool_calls"), list) else []
            expected_ids = []
            for call in tool_calls:
                if isinstance(call, dict) and call.get("id"):
                    expected_ids.append(str(call.get("id")))
            # Consume following tool results for this block (ID-matched when possible).
            results: list[dict] = []
            j = i + 1
            while j < len(source) and str(source[j].get("role") or "") == "tool":
                results.append(source[j])
                j += 1
            # Prefer ID-matched results; if incomplete, still summarize what we have
            # as plain text (never emit partial tool protocol).
            by_id = {
                str(r.get("tool_call_id") or ""): r
                for r in results
                if str(r.get("tool_call_id") or "")
            }
            ordered = []
            if expected_ids:
                for tid in expected_ids:
                    if tid in by_id:
                        ordered.append(by_id[tid])
                # Include unmatched extras as additional evidence lines.
                for r in results:
                    if r not in ordered:
                        ordered.append(r)
            else:
                ordered = list(results)
            lines = []
            for r in ordered:
                lines.append(
                    format_extract_evidence_line(
                        r.get("content"),
                        tool_name=_tool_name(r),
                    )
                )
            if lines:
                flattened.append(
                    {
                        "role": "user",
                        "content": (
                            "[Prior tool evidence summary — not live tool protocol]\n"
                            + "\n".join(f"- {line}" for line in lines)
                        ),
                    }
                )
            # Keep assistant prose if any (without tool_calls / reasoning).
            prose = _plain_text_content(msg.get("content")).strip()
            if prose:
                flattened.append({"role": "assistant", "content": prose[:4000]})
            i = j
            continue
        if role == "tool":
            flattened.append(
                {
                    "role": "user",
                    "content": (
                        "[Prior tool evidence summary — not live tool protocol]\n- "
                        + format_extract_evidence_line(
                            msg.get("content"),
                            tool_name=_tool_name(msg),
                        )
                    ),
                }
            )
            i += 1
            continue
        if role in {"user", "assistant", "system"}:
            prose = _plain_text_content(msg.get("content")).strip()
            if prose:
                if role == "user" and prose.startswith("Project-review context for this reply"):
                    # Replace stale bindings, NOT the owner's question appended to them.
                    # Dropping the whole row loses the inputs needed by follow-ups.
                    marker = "Owner message: "
                    prose = prose.split(marker, 1)[1].strip() if marker in prose else ""
                    if not prose:
                        i += 1
                        continue
                capped = prose[:4000] + ("…" if len(prose) > 4000 else "")
                flattened.append({"role": role if role != "system" else "user", "content": capped})
            i += 1
            continue
        i += 1

    out: list[dict] = []
    if decisions:
        out.append(
            {
                "role": "user",
                "content": (
                    "Retained owner decisions / requests across this review "
                    "(not only the latest window):\n- "
                    + "\n- ".join(decisions)
                ),
            }
        )
    out.extend(flattened)

    # Enforce message count then total serialized char budget from the tail,
    # always keeping the retained-decisions header when present.
    header = out[0] if out and str(out[0].get("content") or "").startswith("Retained owner") else None
    body = out[1:] if header else list(out)
    if len(body) > max_messages:
        body = body[-max_messages:]
    assembled = ([header] if header else []) + body
    while len(assembled) > (1 if header else 0) and _serialized_chars(assembled) > max_chars:
        # Drop oldest body row.
        if header:
            assembled = [header] + assembled[2:]
        else:
            assembled = assembled[1:]
    # Final safety: never leave tool protocol in outbound.
    clean: list[dict] = []
    for row in assembled:
        if not isinstance(row, dict):
            continue
        if str(row.get("role") or "") == "tool" or row.get("tool_calls"):
            continue
        clean.append(
            {
                "role": str(row.get("role") or "user"),
                "content": _plain_text_content(row.get("content")),
            }
        )
    return clean


def _preview_indicates_failure(payload: dict) -> tuple[bool, str]:
    """Actual journal uses preview JSON + is_error; ok:false may arrive with is_error false."""
    if payload.get("is_error") is True:
        return True, "is_error"
    preview = payload.get("preview")
    text = preview if isinstance(preview, str) else ""
    if not text and isinstance(preview, dict):
        text = json.dumps(preview)
    low = text.lower()
    if '"ok": false' in low or '"ok":false' in low:
        return True, "ok_false"
    for marker in (
        "source file not found",
        "path is outside",
        "does not exist",
        "path required",
        "invalid path",
    ):
        if marker in low:
            return True, marker
    return False, ""


def _redact_progress_payload(payload: dict | None, *, kind: str) -> dict:
    data = payload if isinstance(payload, dict) else {}
    name = str(data.get("name") or data.get("tool") or data.get("tool_name") or "").strip()
    args = data.get("args") if isinstance(data.get("args"), dict) else {}
    if not args and isinstance(data.get("arguments"), dict):
        args = data.get("arguments") or {}
    path = args.get("path") or args.get("file") or ""
    failed, fail_reason = _preview_indicates_failure(data) if kind == "tool_complete" else (False, "")
    short = name.split("__")[-1] if name else ""
    return {
        "tool": short,
        "path": os.path.basename(str(path)) if path else "",
        "sample_only": is_sample_only_source(str(path)),
        "failed": bool(failed),
        "fail_reason": fail_reason,
        "is_error": bool(data.get("is_error")),
        "tid": str(data.get("tid") or ""),
        "in_flight": kind == "tool",
    }


def _empty_progress() -> dict[str, Any]:
    return {
        "items": [],
        "tool_count": 0,
        "tool_complete_count": 0,
        "interim_count": 0,
        "last_progress_at": None,
        "last_seq": 0,
        "stalled": False,
        "stall_reason": "",
        "cancel_recommended": False,
        "budget": {
            "tool_complete_budget": REVIEW_TOOL_COMPLETE_BUDGET,
            "path_fail_streak_limit": REVIEW_PATH_FAIL_STREAK,
            "max_iterations": REVIEW_MAX_ITERATIONS,
        },
        "path_fail_streak": 0,
        "in_flight_extract": False,
        "scan_bytes": 0,
    }


def _apply_progress_event(state: dict[str, Any], event: dict) -> None:
    name = str(event.get("event") or "").strip()
    if name not in _PROGRESS_EVENTS:
        return
    created = event.get("created_at")
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    # Never surface reasoning / metering bodies.
    if name == "interim_assistant":
        state["interim_count"] = int(state.get("interim_count") or 0) + 1
        text = str(payload.get("text") or payload.get("content") or "").strip()
        state.setdefault("items", []).append(
            {
                "kind": "interim",
                "created_at": created,
                "text": text[:240] + ("…" if len(text) > 240 else ""),
            }
        )
        state["last_progress_at"] = created
        # Interim does NOT reset path-fail streak (live runaway had interims between fails).
        return

    meta = _redact_progress_payload(payload, kind=name)
    meta.update({"kind": name, "created_at": created})
    state.setdefault("items", []).append(meta)
    state["last_progress_at"] = created
    tool = str(meta.get("tool") or "")
    if name == "tool":
        # Count logical starts only once per tid.
        tid = str(meta.get("tid") or "") or f"anon-{int(state.get('tool_count') or 0)}"
        seen = state.setdefault("_tids", set())
        if tid not in seen:
            seen.add(tid)
            state["tool_count"] = int(state.get("tool_count") or 0) + 1
        if "project_review_extract" in tool and "capabilities" not in tool:
            state["in_flight_extract"] = True
        return

    # tool_complete
    state["tool_complete_count"] = int(state.get("tool_complete_count") or 0) + 1
    tid = str(meta.get("tid") or "")
    seen = state.setdefault("_tids", set())
    if tid and tid not in seen:
        seen.add(tid)
        state["tool_count"] = int(state.get("tool_count") or 0) + 1
    if "project_review_extract" in tool and "capabilities" not in tool:
        state["in_flight_extract"] = False
    failed = bool(meta.get("failed"))
    pathish = bool(meta.get("path")) or meta.get("fail_reason") in {
        "source file not found",
        "path is outside",
        "ok_false",
    }
    if failed and (
        pathish
        or meta.get("fail_reason")
        in {"source file not found", "path is outside", "ok_false", "is_error"}
    ):
        # Count extract path failures; also count generic ok:false extract errors.
        if "project_review_extract" in tool or "source file not found" in str(
            meta.get("fail_reason")
        ):
            state["path_fail_streak"] = int(state.get("path_fail_streak") or 0) + 1
        elif failed:
            state["path_fail_streak"] = int(state.get("path_fail_streak") or 0) + 1
    else:
        state["path_fail_streak"] = 0


def _finalize_progress(state: dict[str, Any], *, max_items: int) -> dict[str, Any]:
    items = list(state.get("items") or [])[-max_items:]
    tool_complete_count = int(state.get("tool_complete_count") or 0)
    path_fail_streak = int(state.get("path_fail_streak") or 0)
    last_progress_at = state.get("last_progress_at")
    in_flight_extract = bool(state.get("in_flight_extract"))
    stalled = False
    stall_reason = ""
    cancel_recommended = False
    now = time.time()
    if path_fail_streak >= REVIEW_PATH_FAIL_STREAK:
        stalled = True
        stall_reason = (
            f"Repeated path-resolution failures ({path_fail_streak} consecutive) without recovery."
        )
        cancel_recommended = True
    elif tool_complete_count >= REVIEW_TOOL_COMPLETE_BUDGET and not in_flight_extract:
        stalled = True
        stall_reason = (
            f"Review tool-completion budget reached ({tool_complete_count}/"
            f"{REVIEW_TOOL_COMPLETE_BUDGET})."
        )
        cancel_recommended = True
    elif (
        last_progress_at
        and (now - float(last_progress_at)) > REVIEW_STALL_IDLE_SECONDS
        and tool_complete_count >= 8
        and not in_flight_extract
    ):
        stalled = True
        stall_reason = (
            "No new interim/tool progress for >15 minutes after substantial tool activity."
        )
        cancel_recommended = True
    return {
        "items": items,
        "tool_count": int(state.get("tool_count") or 0),
        "tool_complete_count": tool_complete_count,
        "interim_count": int(state.get("interim_count") or 0),
        "last_progress_at": last_progress_at,
        "last_seq": int(state.get("last_seq") or 0),
        "stalled": stalled,
        "stall_reason": stall_reason,
        "cancel_recommended": cancel_recommended,
        "budget": {
            "tool_complete_budget": REVIEW_TOOL_COMPLETE_BUDGET,
            "path_fail_streak_limit": REVIEW_PATH_FAIL_STREAK,
            "max_iterations": REVIEW_MAX_ITERATIONS,
        },
        "path_fail_streak": path_fail_streak,
        "in_flight_extract": in_flight_extract,
        "scan_bytes": int(state.get("byte_offset") or 0),
    }


def collect_review_run_progress(
    session_id: str | None,
    stream_id: str | None,
    *,
    max_items: int = 12,
    session_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Incremental progress from the run journal — no reasoning, no full rescan each poll.

    Uses an append-only byte-offset cache so 1.25s dialog polls only parse new lines.
    Counts logical tool calls (not start+complete doubles). Uses real payload fields:
    ``args``, ``is_error``, ``preview`` (including ``ok:false`` with ``is_error:false``).
    """
    sid = str(session_id or "").strip()
    rid = str(stream_id or "").strip()
    empty = _empty_progress()
    if not sid or not rid:
        return empty
    try:
        from api.run_journal import _run_path

        path = _run_path(sid, rid, session_dir=Path(session_dir) if session_dir else None)
    except Exception:
        return empty
    try:
        st = path.stat()
    except FileNotFoundError:
        return empty
    except OSError:
        return empty

    try:
        resolved = str(path.resolve())
    except OSError:
        resolved = str(path)
    key = (resolved, sid, rid)
    with _PROGRESS_CACHE_LOCK:
        cached = _PROGRESS_CACHE.get(key)
        if (
            cached is None
            or cached.get("inode") != st.st_ino
            or int(cached.get("byte_offset") or 0) > st.st_size
        ):
            # New file / truncated — rebuild.
            cached = {
                "journal_path": resolved,
                "inode": st.st_ino,
                "mtime_ns": st.st_mtime_ns,
                "byte_offset": 0,
                "last_seq": 0,
                "tool_count": 0,
                "tool_complete_count": 0,
                "interim_count": 0,
                "last_progress_at": None,
                "path_fail_streak": 0,
                "in_flight_extract": False,
                "items": [],
                "_tids": set(),
            }
            _PROGRESS_CACHE[key] = cached
            _PROGRESS_CACHE.move_to_end(key)
            while len(_PROGRESS_CACHE) > _PROGRESS_CACHE_MAX:
                _PROGRESS_CACHE.popitem(last=False)
        else:
            _PROGRESS_CACHE.move_to_end(key)
        # Fast path: unchanged file → return finalized view without re-reading.
        if (
            cached.get("inode") == st.st_ino
            and cached.get("size") == st.st_size
            and cached.get("mtime_ns") == st.st_mtime_ns
            and int(cached.get("byte_offset") or 0) >= st.st_size
        ):
            return _finalize_progress(cached, max_items=max_items)

        offset = int(cached.get("byte_offset") or 0)
        if offset > st.st_size:
            offset = 0
            cached["items"] = []
            cached["tool_count"] = 0
            cached["tool_complete_count"] = 0
            cached["interim_count"] = 0
            cached["path_fail_streak"] = 0
            cached["in_flight_extract"] = False
            cached["_tids"] = set()
        try:
            with path.open("rb") as fh:
                fh.seek(offset)
                chunk = fh.read()
                new_offset = fh.tell()
        except OSError:
            return _finalize_progress(cached, max_items=max_items)

        if chunk:
            # Incomplete trailing line stays unconsumed until next append.
            if not chunk.endswith(b"\n"):
                last_nl = chunk.rfind(b"\n")
                if last_nl < 0:
                    cached["size"] = st.st_size
                    cached["mtime_ns"] = st.st_mtime_ns
                    return _finalize_progress(cached, max_items=max_items)
                new_offset = offset + last_nl + 1
                chunk = chunk[: last_nl + 1]
            for raw in chunk.splitlines():
                if not raw.strip():
                    continue
                try:
                    event = json.loads(raw.decode("utf-8"))
                except Exception:
                    continue
                if not isinstance(event, dict):
                    continue
                name = str(event.get("event") or "")
                if name not in _PROGRESS_EVENTS:
                    # Skip reasoning/metering/token without materializing bodies.
                    seq = int(event.get("seq") or 0)
                    if seq > int(cached.get("last_seq") or 0):
                        cached["last_seq"] = seq
                    continue
                _apply_progress_event(cached, event)
                seq = int(event.get("seq") or 0)
                if seq > int(cached.get("last_seq") or 0):
                    cached["last_seq"] = seq
            cached["byte_offset"] = new_offset
        cached["size"] = st.st_size
        cached["mtime_ns"] = st.st_mtime_ns
        cached["inode"] = st.st_ino
        # Bound retained item trail in cache.
        if len(cached.get("items") or []) > 64:
            cached["items"] = list(cached["items"])[-64:]
        return _finalize_progress(cached, max_items=max_items)


def format_review_progress_status(progress: dict | None) -> str:
    progress = progress if isinstance(progress, dict) else {}
    items = list(progress.get("items") or [])
    if progress.get("in_flight_extract"):
        base = "Smedley extract/OCR in progress — leave it running until this tool finishes."
        if progress.get("stalled"):
            return (
                f"{base} Budget/stall noted ({progress.get('stall_reason') or 'limit'}); "
                "Cancel is available but will interrupt the worker — spinner stays while live."
            )
        return base
    if progress.get("stalled"):
        return (
            "Smedley review appears stalled: "
            f"{progress.get('stall_reason') or 'no meaningful progress'}. "
            "Use Cancel Turn when ready, then retry — recoverable; worker still live until cancelled."
        )
    if not items:
        return "Smedley is working…"
    last = items[-1]
    kind = str(last.get("kind") or "")
    if kind == "interim" and last.get("text"):
        return f"Smedley update: {last.get('text')}"
    tool = str(last.get("tool") or "tool")
    path = str(last.get("path") or "")
    suffix = f" on {path}" if path else ""
    if kind == "tool_complete":
        if last.get("failed"):
            return f"Smedley tool failed: {tool}{suffix}…"
        return "Smedley is working…"
    if kind == "tool":
        return "Smedley is working…"
    tools = int(progress.get("tool_count") or 0)
    interims = int(progress.get("interim_count") or 0)
    return f"Smedley working… ({tools} tools, {interims} updates)"


def annotate_sample_only_extract_result(path: str, result: dict) -> dict:
    """Mark TEST-ONLY fixtures; leave originals untouched; block production findings."""
    out = dict(result or {})
    if not is_sample_only_source(path) and not is_sample_only_source(out.get("source")):
        return out
    out["sample_only"] = True
    out["production_findings_allowed"] = False
    note = (
        "TEST-ONLY sample fixture — leave original in place; do not treat extract "
        "as Hosford production findings."
    )
    warnings = list(out.get("warnings") or [])
    if note not in warnings:
        warnings.append(note)
    out["warnings"] = warnings
    nested = out.get("result")
    if isinstance(nested, dict):
        nested = dict(nested)
        nested["sample_only"] = True
        nested["production_findings_allowed"] = False
        out["result"] = nested
    return out


def set_project_review_turn_binding(
    session_id: str,
    *,
    context_messages: list | None = None,
    max_iterations: int | None = None,
) -> None:
    """Store one-shot agent binding for the next review turn (process-local)."""
    sid = str(session_id or "").strip()
    if not sid:
        return
    with _REVIEW_TURN_BINDINGS_LOCK:
        _REVIEW_TURN_BINDINGS[sid] = {
            "context_messages": list(context_messages or []),
            "max_iterations": max_iterations,
            "created_at": time.time(),
        }


def get_project_review_turn_binding(session_id: str) -> dict[str, Any] | None:
    """Read one-shot review binding without consuming it."""
    sid = str(session_id or "").strip()
    if not sid:
        return None
    with _REVIEW_TURN_BINDINGS_LOCK:
        row = _REVIEW_TURN_BINDINGS.get(sid)
        return dict(row) if isinstance(row, dict) else None


def pop_project_review_turn_binding(session_id: str) -> dict[str, Any] | None:
    """Consume one-shot review binding for ``session_id``, if present."""
    sid = str(session_id or "").strip()
    if not sid:
        return None
    with _REVIEW_TURN_BINDINGS_LOCK:
        return _REVIEW_TURN_BINDINGS.pop(sid, None)


def clear_review_progress_cache(session_id: str | None = None, stream_id: str | None = None) -> None:
    """Test/helper: drop incremental progress cache entries."""
    with _PROGRESS_CACHE_LOCK:
        if not session_id and not stream_id:
            _PROGRESS_CACHE.clear()
            return
        drop = [
            key
            for key in _PROGRESS_CACHE
            if (not session_id or (len(key) > 1 and key[1] == session_id))
            and (not stream_id or (len(key) > 2 and key[2] == stream_id))
        ]
        for key in drop:
            _PROGRESS_CACHE.pop(key, None)
