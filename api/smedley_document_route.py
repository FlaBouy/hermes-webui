"""Force natural-language document requests through the Smedley RAG path.

Detects pull/find/link document intents, retrieves via the Smedley RAG
retrieve endpoint (not ordinary chat), and deterministically emits canonical
absolute WebUI sidecar preview/doc links. LAN corpus-serve URLs
(192.168.0.15:8789) are never emitted to clients.

Absolute sidecar URLs keep document links usable when a session is later
viewed through TD (or any workstation) against Smedley's WebUI origin.

Gated: callers decide when to invoke. This module does not mutate kanban cards.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Optional

logger = logging.getLogger(__name__)

WEBUI_CORPUS_SIDECAR = "/api/extensions/smedley-engineering/sidecar"
LAN_HOST_RE = re.compile(
    r"https?://(?:192\.168\.0\.15|127\.0\.0\.1|localhost)(?::8789)(/[^\s\)\"']*)?",
    re.IGNORECASE,
)
LAN_MARKDOWN_HREF_RE = re.compile(
    r"\]\((https?://(?:192\.168\.0\.15|127\.0\.0\.1|localhost):8789/[^)]+)\)",
    re.IGNORECASE,
)
SIDECAR_HREF_RE = re.compile(
    r"^/api/extensions/smedley-engineering/sidecar/(?:preview|doc|printed-page)/",
    re.IGNORECASE,
)
# Match sidecar route anywhere (including duplicated /doc/.../doc/... prefixes).
_SIDECAR_ROUTE_PREFIX_RE = re.compile(
    r"(?i)(?:https?://[^/\s]+)?(/api/extensions/smedley-engineering/sidecar/(?:preview|doc|printed-page)/)+",
)
_SIDECAR_REL_PREFIX_RE = re.compile(
    r"(?i)^(?:/)?(?:api/extensions/smedley-engineering/sidecar/(?:preview|doc|printed-page)/)+",
)
# Unsupported LLM-invented "search UI" citations — never a real sidecar route.
SIDECAR_SEARCH_PATH_RE = re.compile(
    r"(?i)/api/extensions/smedley-engineering/sidecar/search(?:\?[^)\s<>\"']*)?"
)
SIDECAR_SEARCH_MD_RE = re.compile(
    r"(!?\[[^\]]*\])\(((?:https?://[^)\s]+)?/api/extensions/smedley-engineering/"
    r"sidecar/search\?[^)]*)\)",
    re.IGNORECASE,
)

# Intent: pull/find/open a document OR ask for a document link.
_DOC_NOUN = (
    r"(?:document|doc(?:ument)?s?|spec(?:ification)?s?|manuals?|datasheets?|"
    r"pdfs?|drawings?|prints?|procedures?|standards?|dock)"
)
_DOC_VERB = (
    r"(?:pull|get|fetch|find|locate|open|show|send|give|provide|bring|grab|"
    r"retrieve|look\s*up|lookup|search\s+for|need|want)"
)
_LINK_ASK = (
    r"(?:(?:give|send|provide|get|need|want|show)\s+(?:me\s+)?(?:a\s+|the\s+)?"
    r"(?:link|url|href|preview)|(?:link|url)\s+to)"
)
# Honeywell FTA / IOP model tokens (MC-TDID52, MU-TDID52, MU/MC-…).
# Require the hyphen so STT tokens like MCP-TIX02 are not treated as MC-TIX02.
_HW_PART = re.compile(
    r"\b(?:MU\s*/\s*MC|MC\s*/\s*MU|MU|MC)-[A-Z]{2,6}\d{2,}[A-Z]?\b",
    re.IGNORECASE,
)
_AB_PART = re.compile(
    # Real Allen-Bradley 1756/1769/1794/5094 catalog suffixes always start
    # with a letter (IA16, PA75, L61, EN2T, ...) -- never a bare number.
    # Requiring a leading letter prevents natural phrasing like "1756 13
    # slot chassis" from being mis-normalized into a fake part "1756-13".
    r"\b(?:1756|1769|1794|5094)[- ]?[A-Z][A-Z0-9]{1,}\b",
    re.IGNORECASE,
)
_DOCNUM = re.compile(r"\b\d{2}-\d{3}\b")  # require hyphen (02-315); never bare ZIP 32444
_FILE_EXT = re.compile(
    r"\b[\w./\\ -]+\.(?:pdf|docx?|xlsx?|pptx?|txt|md)\b",
    re.IGNORECASE,
)
_AFFIRMATIVE_FOLLOWUP_RE = re.compile(
    r"^\s*(?:yes|yep|yeah|yup|sure|ok|okay|please|do\s+it|go\s+ahead|"
    r"proceed|affirmative|sounds\s+good|that\s+works|do\s+that|"
    r"yes\s+please|please\s+do)\s*[.!]?\s*$",
    re.IGNORECASE,
)
_NEGATIVE_FOLLOWUP_RE = re.compile(
    r"^\s*(?:no|nope|nah|negative|not\s+now|no\s+thanks?|"
    r"don'?t\s+bother|skip\s+it|never\s*mind)\s*[.!]?\s*$",
    re.IGNORECASE,
)
# Narrow governing-source guidance: the user is telling Smedley which already-
# bound document to treat as the authoritative reference for a stated
# engineering topic (e.g. "That is the manual to use when asked about 1756
# power supplies."). This must never be parsed as a brand-new document
# lookup -- it has no document number of its own to look up.
_GOVERNING_SOURCE_GUIDANCE_RE = re.compile(
    r"^\s*(?:"
    r"(?:that|this)(?:\s+is|'s)\s+the\s+(?:manual|document|doc|reference|source)\s+to\s+use\b"
    r"|use\s+(?:that|this)\s+(?:manual|document|doc|reference|source)\b"
    r")\s*(?:whenever|when\s+(?:asked|talking)\s+about|for\s+questions?\s+about|"
    r"for|to\s+answer(?:\s+questions?)?(?:\s+about)?)?\s*"
    r"(?P<topic>.+?)\s*[.!]?\s*$",
    re.IGNORECASE,
)
_PENDING_EXTRACT_ACTION = "extract_wiring_schematic"
_MANUAL_EXTS = {".pdf", ".doc", ".docx"}
_INDEX_EXTS = {".xlsx", ".xls", ".csv"}
_INDEX_TITLE_RE = re.compile(
    r"\b(?:knowledgebase|technote\s+ids?|lookup\s+index|part\s+number\s+index|"
    r"index\s+by\s+part|cross[- ]?reference)\b",
    re.IGNORECASE,
)

_DOCUMENT_REQUEST_RES = (
    re.compile(
        rf"\b{_DOC_VERB}\b.{{0,80}}\b{_DOC_NOUN}\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        rf"\b{_DOC_NOUN}\b.{{0,40}}\b{_DOC_VERB}\b",
        re.IGNORECASE | re.DOTALL,
    ),
    # “I need the user manual …” / “need … wiring schematics”
    re.compile(
        rf"\b(?:need|want)\b.{{0,100}}\b(?:{_DOC_NOUN}|wiring|schematics?|pinouts?)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(rf"\b{_LINK_ASK}\b.{{0,80}}\b{_DOC_NOUN}\b", re.IGNORECASE | re.DOTALL),
    re.compile(rf"\b{_LINK_ASK}\b.{{0,80}}{_DOCNUM.pattern}", re.IGNORECASE),
    re.compile(
        rf"\b{_DOC_VERB}\b.{{0,80}}{_DOCNUM.pattern}",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        rf"\b{_DOC_VERB}\b.{{0,80}}{_FILE_EXT.pattern}",
        re.IGNORECASE | re.DOTALL,
    ),
    # Part-number / Honeywell FTA asks are first-class document requests.
    re.compile(
        rf"(?:{_HW_PART.pattern}).{{0,80}}\b(?:{_DOC_NOUN}|wiring|schematics?)\b|"
        rf"\b(?:{_DOC_NOUN}|wiring|schematics?)\b.{{0,80}}(?:{_HW_PART.pattern})",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(rf"(?:{_HW_PART.pattern})", re.IGNORECASE),
    # Allen-Bradley / Rockwell catalog numbers with wiring/manual cues.
    re.compile(
        rf"(?:{_AB_PART.pattern}).{{0,80}}\b(?:{_DOC_NOUN}|wiring|schematics?)\b|"
        rf"\b(?:{_DOC_NOUN}|wiring|schematics?)\b.{{0,80}}(?:{_AB_PART.pattern})",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        rf"(?:can\s+you|please|pls)?\s*(?:{_LINK_ASK})",
        re.IGNORECASE,
    ),
)

DEFAULT_RAG_RETRIEVE_URL = "http://127.0.0.1:5004/rag/retrieve"
RAG_RETRIEVE_URL_ENV = "HERMES_WEBUI_SMEDLEY_RAG_RETRIEVE_URL"
DEFAULT_JARVIS_N8N_BRIEFING_URL = (
    "http://192.168.0.15:5680/webhook/jarvis-pa-biggy-briefing"
)
JARVIS_N8N_BRIEFING_URL_ENV = "SMEDLEY_JARVIS_N8N_BRIEFING_URL"
JARVIS_N8N_HANDOFF_ENABLE_ENV = "SMEDLEY_JARVIS_N8N_HANDOFF"
JARVIS_N8N_TOKEN_ENV = "GPT_BIGGY_PROPOSE_TOKEN"
JARVIS_N8N_TOKEN_FILE_ENV = "GPT_BIGGY_PROPOSE_TOKEN_FILE"
DOC_ROUTE_ENABLED_ENV = "HERMES_WEBUI_SMEDLEY_DOC_ROUTE"
PUBLIC_ORIGIN_ENV = "HERMES_WEBUI_SMEDLEY_PUBLIC_ORIGIN"
MAX_ACTIVE_DOCUMENT_PREVIEW_BYTES = 2 * 1024 * 1024
_ACTIVE_DOCUMENT_SECTION_RE = re.compile(
    r"\b(?:paragraph|para|section|sec\.?|article|clause)\s*(?:no\.?\s*)?"
    r"([0-9]+(?:[.\-][0-9]+)*)\b",
    re.IGNORECASE,
)
_ACTIVE_DOCUMENT_FOLLOWUP_RE = re.compile(
    r"\b(?:paragraph|para|section|sec\.?|article|clause|what\s+does\s+it\s+say|"
    r"read\s+(?:that|it)|quote|exact\s+(?:wording|text))\b",
    re.IGNORECASE,
)
_ACTIVE_DOCUMENT_WIRING_EXTRACT_RE = re.compile(
    r"\b(?:extract|pull|show|open|find|get|locate|display|bring\s+up|hand|send|give)\b.{0,40}\b"
    r"(?:wiring|schematic|connection\s+diagram|terminal\s+diagram|diagram)\b"
    r"|\b(?:wiring|schematic|connection)\s+(?:diagram|page|schematic|drawing)s?\b"
    r"|\bextract\s+(?:it|that|the\s+(?:page|diagram|schematic|wiring))\b"
    # Natural continuations naming the page number rather than the verb
    # "extract" — order-flexible so "page number for the schematic" and
    # "schematic page number" both match. Scoped by requiring both a
    # page-number phrase AND a wiring/schematic/diagram/connection noun
    # within a short span, so ordinary questions are not swept in.
    r"|\bpage\s*(?:number|no\.?|#)\b.{0,60}\b(?:wiring|schematic|diagram|connection)\b"
    r"|\b(?:wiring|schematic|diagram|connection)\b.{0,60}\bpage\s*(?:number|no\.?|#)\b",
    re.IGNORECASE,
)
_ACTIVE_DOCUMENT_RECOMMENDATION_RE = re.compile(
    r"\b(?:who\s+(?:do|does|would)\s+(?:they|it)\s+recommend|recommend(?:ed|ation)?|preferred|manufacturer|vendor)\b",
    re.IGNORECASE,
)
_LIBRARY_ROOT_ENV = "SMEDLEY_LIBRARY_ROOT"
_DEFAULT_LIBRARY_ROOTS = (
    "/Users/rick/Mounts/RAG_Pool/Library",
    "/Volumes/RAG_Pool/Library",
)
_GROUNDED_CONTEXT_RE = re.compile(r"<retrieved_library_context>(.*?)</retrieved_library_context>", re.I | re.S)
_GROUNDED_SIDECAR_RE = re.compile(r"\]\((?:https?://[^)]+)?/api/extensions/smedley-engineering/sidecar/(?:preview|doc)/([^)\s]+)\)", re.I)
_ENGINEERING_TERMS = frozenset({
    "allowable", "bearing", "cable", "card", "catalog", "channel", "circuit",
    "compatible", "compatibility", "concrete", "criteria", "current", "design",
    "electrical", "excavation", "failure", "foundation", "footing", "fuse",
    "fused", "fusing", "hardness", "ifm", "input", "load", "material",
    "mechanical", "module", "motor", "output", "pipe", "pump", "rating",
    "rated", "ratio", "shaft", "spec", "stability", "structural", "terminal",
    "voltage", "volt", "welding", "wiring",
})
_ENGINEERING_PRIORITY_TERMS = frozenset({
    "hardness", "ratio", "minimum", "maximum", "allowable", "shall", "shaft",
    "fuse", "fusing", "ifm", "rating", "voltage",
})
_ENGINEERING_QUESTION_RE = re.compile(r"\b(?:what|which|where|when|how|does|is|are|shall|should|need)\b|\?", re.I)
_ELECTRICAL_FACT_RE = re.compile(
    r"\b(?:fuse|fusing|fused|amp(?:ere)?s?|rating|rated|voltage|volts?|"
    r"current|channel|compatible|compatibility|match(?:es|ing)?|"
    r"ifm|interface\s+modules?|pre-?wired|cables?|terminals?|"
    r"catalog|cat\.?\s*nos?|datasheets?|internal\s+fus|"
    r"power\s+suppl(?:y|ies)|psu|chassis|watt(?:age)?s?|redundan(?:t|cy)|"
    r"backplane|slot(?:s)?|sizing|thermal)\w*\b",
    re.IGNORECASE,
)
_CHASSIS_POWER_TOPIC_RE = re.compile(
    r"(?i)(?:\b(?:controllogix|allen[- ]?bradley|rockwell|1756)\b.{0,100}"
    r"\b(?:power\s+suppl(?:y|ies)|psu|chassis|watt(?:age)?s?|redundan(?:t|cy)|"
    r"backplane|slots?)\b|"
    r"\b(?:power\s+suppl(?:y|ies)|psu|chassis|watt(?:age)?s?|redundan(?:t|cy)|"
    r"backplane|slots?)\b.{0,100}\b(?:controllogix|allen[- ]?bradley|rockwell|1756)\b|"
    r"\b(?:1756-P[AB]\w*|which\s+power\s+suppl(?:y|ies)|"
    r"chassis\s+(?:power|sizing|selection)|"
    r"power\s+suppl(?:y|ies)\s+for\s+(?:a\s+)?(?:controllogix|1756))\b)",
)
_SLOT_FOLLOWUP_RE = re.compile(
    r"^\s*(\d{1,2})\s*-?\s*slots?\s*[.?]?\s*$",
    re.IGNORECASE,
)
_SLOT_IN_TEXT_RE = re.compile(
    r"\b(\d{1,2})\s*-?\s*slots?\b",
    re.IGNORECASE,
)
_COMPATIBILITY_FOLLOWUP_RE = re.compile(
    r"\b(?:fusible\s+ifm|ifm|interface\s+module|pre-?wired\s+cable|cable|"
    r"match|compatible|compatibility|wiring\s+system|1492|"
    r"power\s+suppl(?:y|ies)|psu|chassis|redundan(?:t|cy)|watt(?:age)?s?|slots?)\b",
    re.IGNORECASE,
)
_CHAIN_OF_THOUGHT_RE = re.compile(
    r"(?i)(?:let me (?:search|check|try|pull|look)|based on my experience|"
    r"the rag search|i(?:'| a)m going to search|hidden search|"
    r"thinking out loud|as an ai)"
)
_PENDING_IFM_LOOKUP_ACTION = "retrieve_ifm_cable_for_part"
_PENDING_USE_AB_INDEX_ACTION = "use_ab_wiring_index_for_part"
_PENDING_CHASSIS_SIZING_ACTION = "retrieve_controllogix_chassis_power"
_AB_WIRING_INDEX_SOURCE = (
    "Vendor Data/Allen Bradley/"
    "Wiring Diagram Knowledgebase Technote IDs by Part Number 1-11-2021.xlsx"
)
_AB_WIRING_INDEX_TITLE = (
    "Wiring Diagram Knowledgebase Technote IDs by Part Number — lookup index"
)
_AB_WIRING_INDEX_SMB = (
    "smb://192.168.0.25/RAG_Pool/Library/Vendor Data/Allen Bradley/"
    "Wiring Diagram Knowledgebase Technote IDs by Part Number 1-11-2021.xlsx"
)
_AB_DIGITAL_IO_MANUAL_SOURCES = (
    "Vendor Data/Allen Bradley/1756/1756-um058_-en-p.pdf",
)
_AB_CHASSIS_POWER_MANUAL_SOURCES = (
    "Vendor Data/Allen Bradley/1756-um001_-en-p.pdf",
    "Vendor Data/Allen Bradley/1756/1756-um001_-en-p.pdf",
)
_AB_ANALOG_IO_MANUAL_RE = re.compile(
    r"(?:1756-um009|um009_|analog\s+i/?o|analog\s+input)",
    re.IGNORECASE,
)
# Digital discrete catalog bodies vs analog IF/OF families.
_AB_DIGITAL_BODY_RE = re.compile(
    r"^1756-(?:IA|IB|IC|IH|IV|OA|OB|OC|OG|OH|OV|OW|OX)\d",
    re.IGNORECASE,
)
_AB_ANALOG_BODY_RE = re.compile(
    r"^1756-(?:IF|IR|IT|OF|OY)\d",
    re.IGNORECASE,
)
_SPECIFICATION_NUMBER_RE = re.compile(
    r"\b(?:spec(?:ification)?\s*(?:number|no\.?|#)|(?:general\s+)?(?:wire|cable|piping|hvac)\s+(?:spec|specification))\b",
    re.IGNORECASE,
)
# Allen-Bradley 1756 publication tokens: TD0005, TD-0005, 1756-TD005, 1756-UM001, IN619.
_AB_1756_PUB_TOKEN_RE = re.compile(
    r"\b(?:1756[-_ ]+)?(TD|UM|IN)[-_ ]*0*(\d{1,4})(?:[A-Z])?(?:[-_]?EN[-_]?[A-Z])?\b",
    re.IGNORECASE,
)
_AB_1756_PUB_FILENAME_RE = re.compile(
    r"\b1756[-_](td|um|in)0*(\d{1,4})[-_][^\s,]+\.(?:pdf|docx?)\b",
    re.IGNORECASE,
)
_AB_1756_MANIFEST_REL = "ab_1756_publication_manifest.json"
_AB_1756_LIBRARY_REL = "Vendor Data/Allen Bradley/1756"


class _PreviewTextExtractor(HTMLParser):
    """Convert the trusted loopback preview HTML into bounded plain text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data and data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        return "\n".join(self.parts)


def document_route_enabled() -> bool:
    """Opt-out via HERMES_WEBUI_SMEDLEY_DOC_ROUTE=0/false/off."""
    raw = (os.environ.get(DOC_ROUTE_ENABLED_ENV) or "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def _is_ask_jarvis_traffic(text: object) -> bool:
    """Ask Jarvis turns must not auto-open the Smedley engineering document sidecar."""
    try:
        from api.ask_jarvis_route import is_ask_jarvis_command

        return bool(is_ask_jarvis_command(str(text or "")))
    except Exception:
        return bool(
            re.search(
                r"(?i)\bask\s+jarvis\b",
                str(text or ""),
            )
        )


def is_library_path_operation(text: object) -> bool:
    msg = str(text or "").strip()
    if not msg:
        return False
    return bool(
        re.search(r"(?i)\bsmb://", msg)
        or re.search(r"(?i)\\\\192\.168\.0\.25\\RAG_Pool", msg)
        or re.search(r"(?i)/Users/rick/Mounts/RAG_Pool/Library", msg)
    )


def is_document_request(text: object) -> bool:
    """True when the user is asking to pull/find a document or get a doc link."""
    msg = str(text or "").strip()
    if not msg or len(msg) > 4000:
        return False
    if is_library_path_operation(msg):
        return True
    # Biggy → Ask Jarvis: never treat as automatic Smedley document sidecar request.
    if _is_ask_jarvis_traffic(msg):
        return False
    # Slash commands and obvious non-doc tooling stay on ordinary chat.
    if msg.startswith("/"):
        return False
    # Already-grounded RAG turns (extension retrieveFromComposer) stay on chat.
    if "<retrieved_library_context>" in msg:
        return False
    # Governing-source guidance ("That is the manual to use when asked about
    # X") names no document of its own to look up -- it must never be routed
    # as a document request, with or without an active_document bound. Real
    # explicit document requests (doc numbers, publication tokens, spec
    # numbers, "find/open/pull <manual>") are unaffected by this exclusion.
    if is_governing_source_guidance(msg):
        return False
    # A request for a governing project specification is a document lookup even
    # when it does not include a verb such as "find" or "open".
    if _SPECIFICATION_NUMBER_RE.search(msg):
        return True
    if extract_ab_1756_publication_tokens(msg):
        return True
    for pattern in _DOCUMENT_REQUEST_RES:
        if pattern.search(msg):
            return True
    # Bare "link to 02315" / "document 02-315 please"
    if _DOCNUM.search(msg) and re.search(
        r"\b(?:document|doc|spec|pdf|link|url|preview|pull|find|open)\b",
        msg,
        re.IGNORECASE,
    ):
        return True
    return False


def is_specification_number_request(text: object) -> bool:
    return bool(_SPECIFICATION_NUMBER_RE.search(str(text or "")))


def extract_ab_1756_publication_tokens(query: object) -> list[tuple[str, int, str]]:
    """Return (kind, number, raw_token) for 1756 TD/UM/IN publication mentions."""
    msg = str(query or "")
    found: list[tuple[str, int, str]] = []
    seen: set[tuple[str, int]] = set()
    for rx in (_AB_1756_PUB_TOKEN_RE, _AB_1756_PUB_FILENAME_RE):
        for match in rx.finditer(msg):
            kind = str(match.group(1) or "").upper()
            try:
                number = int(match.group(2))
            except (TypeError, ValueError):
                continue
            key = (kind, number)
            if key in seen:
                continue
            seen.add(key)
            found.append((kind, number, match.group(0)))
    return found


def _load_ab_1756_publication_manifest() -> dict[str, Any]:
    """Live ingest-reconciled aliases first; committed snapshot is fallback only."""
    try:
        from api.ab_1756_publication_reconcile import load_or_reconcile_manifest

        payload = load_or_reconcile_manifest(library_root=library_root(), persist=True)
        if isinstance(payload, dict) and payload.get("publications"):
            return payload
    except Exception:
        logger.warning("1756 publication reconcile failed; using committed snapshot if present")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), _AB_1756_MANIFEST_REL)
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _ab_1756_manifest_index() -> dict[tuple[str, int], dict[str, Any]]:
    payload = _load_ab_1756_publication_manifest()
    index: dict[tuple[str, int], dict[str, Any]] = {}
    for entry in payload.get("publications") or []:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind") or "").upper()
        try:
            number = int(entry.get("number"))
        except (TypeError, ValueError):
            continue
        if kind and number >= 0:
            index[(kind, number)] = entry
    return index


def _ab_1756_pub_present(entry: dict[str, Any]) -> bool:
    rel = str(entry.get("source") or "").replace("\\", "/")
    root = library_root()
    if not rel or not root:
        return False
    return os.path.isfile(os.path.join(root, rel))


def _format_ab_1756_pub_label(kind: str, number: int, raw: object = "") -> str:
    token = str(raw or "").strip()
    if token:
        return token
    return f"1756-{kind}{number:03d}"


def resolve_ab_1756_publication_alias(query: object) -> dict[str, Any] | None:
    """Deterministic 1756 publication alias — runs before semantic retrieval.

    Zero/punctuation/case insensitive: TD0005, TD-0005, 1756-TD0005 → on-disk
    1756-td005. Never substitute a different TD/UM document.
    """
    tokens = extract_ab_1756_publication_tokens(query)
    if not tokens:
        return None
    index = _ab_1756_manifest_index()
    kind, number, raw = tokens[0]
    entry = index.get((kind, number))
    label = _format_ab_1756_pub_label(kind, number, raw)
    payload = _load_ab_1756_publication_manifest()
    smb = str(payload.get("smb") or "smb://192.168.0.25/RAG_Pool/Library/Vendor Data/Allen Bradley/1756")
    if not entry:
        return {
            "status": "absent",
            "kind": kind,
            "number": number,
            "requested": label,
            "source": None,
            "smb": smb,
            "reason": (
                f"{label} is not in the 1756 library at {smb}. "
                f"No 1756-{kind}{number:03d} file is present; I will not substitute another TD/UM document."
            ),
        }
    present = _ab_1756_pub_present(entry)
    result = dict(entry)
    result["status"] = "present" if present else "absent"
    result["present"] = present
    result["indexed"] = bool(entry.get("indexed"))
    result["resolvable"] = bool(entry.get("resolvable", present))
    result["ingest_phase"] = entry.get("ingest_phase")
    result["requested"] = label
    result["smb"] = smb
    if not present:
        filename = str(entry.get("canonical_filename") or entry.get("source") or "")
        result["reason"] = (
            f"{label} maps to {filename or 'its canonical 1756 publication'}, "
            f"but that file is not present in {smb}. I will not substitute another TD/UM document."
        )
    return result


def _match_from_ab_1756_alias(
    alias: dict[str, Any], *, public_origin: object = ""
) -> dict[str, Any]:
    origin = normalize_public_origin(public_origin)
    source = str(alias.get("source") or "").replace("\\", "/")
    title = str(alias.get("title") or "")
    doc_no = str(alias.get("doc_no") or "")
    ident = {
        "title": title,
        "doc_no": doc_no,
        "filename": str(alias.get("canonical_filename") or ""),
        "publication_identifier": str(alias.get("publication_identifier") or doc_no),
        "vendor": "Allen-Bradley / Rockwell Automation",
        "family": "1756 ControlLogix",
        "revision": alias.get("revision"),
        "date": alias.get("date"),
    }
    url = normalize_corpus_url("", source=source, public_origin=origin)
    return {
        "source": source,
        "score": 1.0,
        "match_kind": "publication_alias",
        "retrieval": "ab_1756_publication_alias",
        "url": url,
        "revision": alias.get("publication_identifier") or doc_no,
        "document_identity": ident,
        "document_kind": "manual",
    }


def _ab_1756_absent_reply(alias: dict[str, Any]) -> str:
    return str(alias.get("reason") or "That 1756 publication is not in the library.")


def project_spec_lookup_query(query: object) -> str:
    """Remove conversational filler that otherwise biases vector search to NEC."""
    words = re.findall(r"[A-Za-z0-9]+", str(query or ""))
    ignored = {"what", "which", "is", "are", "the", "a", "an", "for", "of", "on", "that", "i", "need", "looking"}
    concise = " ".join(word for word in words if word.lower() not in ignored)
    return f"GP Brewton {concise}".strip()


def prioritize_gp_brewton_spec_matches(matches: object, query: object) -> list[dict[str, Any]]:
    """Put matching Brewton project specs ahead of generic reference material."""
    if not isinstance(matches, list):
        return []
    query_tokens = set(re.findall(r"[a-z0-9]+", str(query or "").lower()))
    query_tokens -= {"what", "which", "the", "for", "and", "general", "spec", "specification", "number", "volt", "volts", "feeder", "feeders"}

    def key(item: object) -> tuple[int, int]:
        source = str(item.get("source") or "") if isinstance(item, dict) else ""
        source_l = source.lower()
        # Match "GP Brewton/..." at path start and ".../GP Brewton/..." mid-path.
        is_gp = int(
            "gp brewton" in source_l
            or "brewton specs" in source_l
        )
        title_tokens = set(re.findall(r"[a-z0-9]+", source.rsplit("/", 1)[-1].lower()))
        return (is_gp, len(query_tokens & title_tokens))

    cleaned = [item for item in matches if isinstance(item, dict)]
    return sorted(cleaned, key=key, reverse=True)


def _coerce_public_origin_candidate(raw: object) -> str:
    """Normalize one origin candidate, or '' when unset/invalid/forbidden."""
    value = str(raw or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    try:
        parts = urllib.parse.urlsplit(value)
    except Exception:
        return ""
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    host = (parts.hostname or "").lower()
    port = parts.port
    # Never emit loopback / localhost absolute links (break when opened via TD).
    if host in {"127.0.0.1", "localhost", "::1"}:
        return ""
    # Never treat corpus-serve 192.168.0.15:8789 as the WebUI origin.
    if host == "192.168.0.15" and (port == 8789 or port is None):
        return ""
    return f"{parts.scheme}://{parts.netloc}".rstrip("/")


def normalize_public_origin(origin: object = "") -> str:
    """Return a scheme://host[:port] origin, or '' when unset/invalid.

    Prefer HERMES_WEBUI_SMEDLEY_PUBLIC_ORIGIN when set so persisted sidecar
    links stay absolute to Smedley's WebUI even if the request Host is
    loopback or a different workstation (TD) origin.
    """
    env_raw = (os.environ.get(PUBLIC_ORIGIN_ENV) or "").strip()
    for candidate in (env_raw, str(origin or "").strip()):
        normalized = _coerce_public_origin_candidate(candidate)
        if normalized:
            return normalized
    return ""


def library_relpath_from_source(source: object = "") -> str:
    """Return a clean library-relative path; strip duplicated sidecar route prefixes."""
    rel = str(source or "").replace("\\", "/").strip()
    if not rel or rel == "?":
        return ""
    try:
        parsed = urllib.parse.urlsplit(rel)
        if parsed.scheme in ("http", "https") and parsed.path:
            rel = parsed.path + (("?" + parsed.query) if parsed.query else "")
    except Exception:
        pass
    rel = rel.split("?")[0].split("#")[0]
    # Peel every leading sidecar route prefix (handles doubled /doc/.../doc/...).
    while True:
        nxt = _SIDECAR_REL_PREFIX_RE.sub("", rel, count=1)
        if nxt == rel:
            break
        rel = nxt
    # If a sidecar marker remains mid-string, keep only the path after the last route.
    low = rel.lower()
    last_doc = low.rfind("/api/extensions/smedley-engineering/sidecar/doc/")
    last_prev = low.rfind("/api/extensions/smedley-engineering/sidecar/preview/")
    last_print = low.rfind("/api/extensions/smedley-engineering/sidecar/printed-page/")
    last = max(last_doc, last_prev, last_print)
    if last >= 0:
        if last_print >= last_doc and last_print >= last_prev:
            route = "printed-page"
        elif last_doc >= last_prev:
            route = "doc"
        else:
            route = "preview"
        prefix = f"/api/extensions/smedley-engineering/sidecar/{route}/"
        rel = rel[last + len(prefix) :]
    try:
        rel = urllib.parse.unquote(rel)
    except Exception:
        pass
    return rel.strip().lstrip("/").replace("\\", "/")


def sidecar_preview_path(source: object) -> str:
    """Deterministic relative WebUI sidecar path for a corpus source."""
    rel = library_relpath_from_source(source)
    if not rel or rel == "?":
        return ""
    ext = os.path.splitext(rel)[1].lower()
    route = "doc" if ext == ".pdf" else "preview"
    return f"{WEBUI_CORPUS_SIDECAR}/{route}/{urllib.parse.quote(rel, safe='/')}"


def sidecar_printed_page_path(source: object, printed_page: object) -> str:
    """User-facing schematic link: printed page, never PDF ordinal."""
    rel = library_relpath_from_source(source)
    printed = str(printed_page or "").strip()
    if not rel or rel == "?" or not printed.isdigit():
        return ""
    return (
        f"{WEBUI_CORPUS_SIDECAR}/printed-page/{urllib.parse.quote(rel, safe='/')}"
        f"?printed={printed}"
    )


def resolve_printed_page_to_pdf_page(source: object, printed_page: object) -> int | None:
    """Map a verified printed/footer page to the 1-based PDF ordinal.

    Uses each PDF page's own header/footer printed number. Never infers a
    page from a search snippet or a constant offset. Ambiguous matches fail
    closed.
    """
    printed = str(printed_page or "").strip()
    if not printed.isdigit():
        return None
    rel = library_relpath_from_source(source)
    root = library_root()
    if not rel or not root:
        return None
    full = os.path.join(root, rel)
    if not os.path.isfile(full):
        return None
    try:
        texts = _pdf_page_texts(full)
    except Exception:
        return None
    hits = [
        idx + 1
        for idx, text in enumerate(texts)
        if _printed_page_number(text) == printed
    ]
    if len(hits) != 1:
        return None
    return hits[0]


def handle_printed_page_sidecar_get(
    handler,
    proxy_path: object,
    query: object = "",
    *,
    public_origin: object = "",
    accept: object = "",
) -> bool:
    """Serve the printed-page resolver. True if this request was a printed-page route."""
    rest = str(proxy_path or "").lstrip("/")
    if not rest.startswith("printed-page/"):
        return False
    rel = urllib.parse.unquote(rest[len("printed-page/") :])
    rel = library_relpath_from_source(rel)
    qs = urllib.parse.parse_qs(str(query or ""))
    printed = str((qs.get("printed") or [""])[0]).strip()
    pdf_page = resolve_printed_page_to_pdf_page(rel, printed)
    if not pdf_page:
        handler.send_response(404)
        body = b'{"error":"printed page not verified in source document"}'
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body)
        return True
    doc_path = sidecar_preview_path(rel)
    doc_href = doc_path
    viewer_href = f"{doc_path}#page={pdf_page}"
    want_json = "application/json" in str(accept or "").lower()
    if want_json:
        payload = json.dumps(
            {
                "source": rel,
                "printed_page": printed,
                "pdf_page": pdf_page,
                "doc_url": doc_href,
                "viewer_url": viewer_href,
            }
        ).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(payload)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(payload)
        return True
    from html import escape as _html_escape

    safe_view = _html_escape(viewer_href, quote=True)
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>Printed p.{_html_escape(printed)}</title>"
        "<style>html,body{margin:0;height:100%;background:#111}</style>"
        f"<script>location.replace({json.dumps(viewer_href)});</script>"
        "</head><body>"
        f"<embed src='{safe_view}' type='application/pdf' style='width:100%;height:100vh'>"
        "</body></html>"
    ).encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(html)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(html)
    return True


def _collapse_duplicated_sidecar_path(path: object) -> str:
    """Idempotently collapse .../sidecar/doc/.../sidecar/doc/... into one route."""
    raw = str(path or "").strip()
    if not raw:
        return ""
    try:
        parsed = urllib.parse.urlsplit(raw)
        if parsed.scheme in ("http", "https"):
            path_only = parsed.path
            query = ("?" + parsed.query) if parsed.query else ""
        else:
            path_only = parsed.path or raw.split("?")[0].split("#")[0]
            query = ("?" + parsed.query) if parsed.query else (
                ("?" + raw.split("?", 1)[1].split("#")[0]) if "?" in raw else ""
            )
    except Exception:
        path_only = raw.split("?")[0].split("#")[0]
        query = ""
    rel = library_relpath_from_source(path_only)
    if not rel:
        return ""
    if "/sidecar/printed-page/" in path_only.lower():
        printed = ""
        if query.startswith("?"):
            vals = urllib.parse.parse_qs(query[1:]).get("printed") or [""]
            printed = str(vals[0] if vals else "").strip()
        rebuilt = sidecar_printed_page_path(rel, printed)
        return rebuilt or ""
    rebuilt = sidecar_preview_path(rel)
    if not rebuilt:
        return ""
    return rebuilt + query


def _is_sidecar_preview_or_doc_path(path: object) -> bool:
    raw = str(path or "").split("?")[0].split("#")[0]
    if SIDECAR_HREF_RE.match(raw):
        return True
    # Doubled route still counts as a sidecar path for collapse.
    return bool(
        re.search(
            r"(?i)/api/extensions/smedley-engineering/sidecar/(?:preview|doc|printed-page)/",
            raw,
        )
    )


def absolutize_sidecar_href(path_or_url: object, *, public_origin: object = "") -> str:
    """Canonical absolute sidecar URL when origin is known; else relative path.

    Only preview|doc|printed-page routes are accepted. Unsupported paths such as
    ``/sidecar/search?q=`` are rejected (empty string) so callers fall back to
    a source-derived preview/doc link. Already-prefixed and doubled routes are
    collapsed before absolutizing (idempotent).
    """
    raw = str(path_or_url or "").strip()
    if not raw:
        return ""
    origin = normalize_public_origin(public_origin)
    # Already absolute sidecar — collapse duplicates, keep preview|doc only.
    try:
        parsed = urllib.parse.urlsplit(raw)
        if parsed.scheme in ("http", "https") and _is_sidecar_preview_or_doc_path(
            parsed.path
        ):
            collapsed = _collapse_duplicated_sidecar_path(raw)
            if not collapsed:
                return ""
            if origin:
                # collapsed may already be absolute if origin was baked in — keep path only
                cparse = urllib.parse.urlsplit(collapsed)
                path = cparse.path if cparse.scheme else collapsed
                if not path.startswith("/"):
                    path = "/" + path
                q = ("?" + cparse.query) if cparse.query else ""
                return path + q
            cparse = urllib.parse.urlsplit(collapsed)
            if cparse.scheme:
                return cparse.path + (("?" + cparse.query) if cparse.query else "")
            return collapsed
    except Exception:
        pass
    collapsed = _collapse_duplicated_sidecar_path(raw) if _is_sidecar_preview_or_doc_path(raw) else ""
    if not collapsed:
        if not _is_sidecar_preview_or_doc_path(raw):
            return ""
        collapsed = _collapse_duplicated_sidecar_path(raw)
    if not collapsed:
        return ""
    path = collapsed.split("#")[0]
    cparse = urllib.parse.urlsplit(path)
    if cparse.scheme in ("http", "https"):
        path = cparse.path + (("?" + cparse.query) if cparse.query else "")
    if not path.startswith("/"):
        path = "/" + path
    # Operator chat links must be same-origin relative so the current WebUI
    # session cookie is sent. Never bake localhost, Tailscale, or any host.
    return path


def normalize_corpus_url(
    path_or_url: object, *, source: object = "", public_origin: object = ""
) -> str:
    """Rewrite LAN/corpus-serve/search URLs to sidecar preview|doc; never lan_url.

    Idempotent: already-canonical sidecar hrefs (relative, same-origin, Tailscale,
    or accidentally double-prefixed) collapse to one preview|doc route.
    """
    raw = str(path_or_url or "").strip()
    origin = normalize_public_origin(public_origin)
    src_rel = library_relpath_from_source(source)
    if not raw:
        return absolutize_sidecar_href(sidecar_preview_path(src_rel), public_origin=origin)
    # Unsupported search UI citations → source-derived preview/doc when possible.
    if SIDECAR_SEARCH_PATH_RE.search(raw):
        if src_rel:
            return absolutize_sidecar_href(
                sidecar_preview_path(src_rel), public_origin=origin
            )
        return ""
    lan = LAN_HOST_RE.match(raw) or LAN_HOST_RE.search(raw)
    if lan:
        rel = (lan.group(1) or "").split("?")[0].split("#")[0]
        try:
            rel = urllib.parse.unquote(rel)
        except Exception:
            pass
        rel = library_relpath_from_source(rel.lstrip("/").replace("\\", "/"))
        return absolutize_sidecar_href(
            sidecar_preview_path(rel or src_rel), public_origin=origin
        )
    # Any sidecar-shaped path/URL (including doubled) → collapse once.
    if _is_sidecar_preview_or_doc_path(raw) or _SIDECAR_ROUTE_PREFIX_RE.search(raw):
        return absolutize_sidecar_href(raw.split("#")[0], public_origin=origin)
    # Absolute non-sidecar URL with sidecar path segment.
    try:
        parsed = urllib.parse.urlsplit(raw)
        if parsed.path.startswith(WEBUI_CORPUS_SIDECAR + "/"):
            if source or src_rel:
                return absolutize_sidecar_href(
                    sidecar_preview_path(src_rel), public_origin=origin
                )
            return ""
    except Exception:
        pass
    # Bare library-relative path in the URL field.
    if re.search(r"\.(?:pdf|docx?|xlsx?|pptx?|txt|md)$", raw, re.I) and "://" not in raw:
        return absolutize_sidecar_href(
            sidecar_preview_path(library_relpath_from_source(raw) or src_rel),
            public_origin=origin,
        )
    if src_rel:
        return absolutize_sidecar_href(sidecar_preview_path(src_rel), public_origin=origin)
    return ""


def markdown_link_for_source(
    source: object, url: object = "", *, public_origin: object = ""
) -> str:
    rel = library_relpath_from_source(source) or str(source or "").strip()
    href = normalize_corpus_url(url, source=rel, public_origin=public_origin) or absolutize_sidecar_href(
        sidecar_preview_path(rel), public_origin=public_origin
    )
    if not href:
        return rel or "?"
    fname = rel.rsplit("/", 1)[-1] or rel
    return f"📄 [{fname}]({href})"


def neutralize_lan_url_text(text: object, *, public_origin: object = "") -> str:
    """Strip/rewrite any 192.168.0.15:8789 (and loopback :8789) citations."""
    value = str(text or "")
    if not value:
        return ""
    origin = normalize_public_origin(public_origin)

    def _md_sub(match: re.Match[str]) -> str:
        next_href = normalize_corpus_url(match.group(1), public_origin=origin)
        return f"]({next_href})" if next_href else "]()"

    value = LAN_MARKDOWN_HREF_RE.sub(_md_sub, value)
    value = LAN_HOST_RE.sub(
        lambda m: normalize_corpus_url(m.group(0), public_origin=origin) or "", value
    )
    value = re.sub(r"lan_url\s*[:=]\s*\S+", "", value, flags=re.IGNORECASE)
    # Promote relative sidecar markdown hrefs to absolute when origin known.
    if origin:
        value = re.sub(
            r"\]\((/api/extensions/smedley-engineering/sidecar/(?:preview|doc|printed-page)/[^)]+)\)",
            lambda m: f"]({absolutize_sidecar_href(m.group(1), public_origin=origin)})",
            value,
        )
    return value.strip()


def neutralize_match(match: object, *, public_origin: object = "") -> dict[str, Any]:
    """Return a match dict with sidecar url/markdown and lan_url removed."""
    if not isinstance(match, dict):
        return {}
    origin = normalize_public_origin(public_origin)
    source = str(match.get("source") or "").strip()
    url = normalize_corpus_url(
        match.get("url") or "", source=source, public_origin=origin
    ) or absolutize_sidecar_href(sidecar_preview_path(source), public_origin=origin)
    md = neutralize_lan_url_text(match.get("markdown") or "", public_origin=origin)
    if not md or "192.168.0.15:8789" in md or "lan_url" in md.lower():
        md = markdown_link_for_source(source, url, public_origin=origin)
    else:
        # Ensure href is sidecar even when markdown lacked an explicit LAN URL.
        md = re.sub(
            r"\]\((https?://[^)]+/api/extensions/smedley-engineering/sidecar/(?:preview|doc|printed-page)/[^)]+)\)",
            lambda m: f"]({normalize_corpus_url(m.group(1), source=source, public_origin=origin) or m.group(1)})",
            md,
        )
        md = re.sub(
            r"\]\((/api/extensions/smedley-engineering/sidecar/(?:preview|doc|printed-page)/[^)]+)\)",
            lambda m: f"]({normalize_corpus_url(m.group(1), source=source, public_origin=origin) or m.group(1)})",
            md,
        )
        if "](" not in md:
            md = markdown_link_for_source(source, url, public_origin=origin)
    out = {
        "source": source,
        "snippet": str(match.get("snippet") or ""),
        "url": url,
        "markdown": md,
    }
    if isinstance(match.get("score"), (int, float)) and not isinstance(match.get("score"), bool):
        out["score"] = float(match["score"])
    if match.get("plato_unc"):
        out["plato_unc"] = str(match.get("plato_unc"))
    # Preserve TDC3000 custom-index identity metadata through Smedley → Jarvis.
    for key in (
        "match_kind",
        "part_number",
        "observed_part",
        "document_identity",
        "revision",
        "page_hint",
        "chunk_hint",
        "index_href",
        "index_formats",
        "retrieval",
    ):
        if key in match and match.get(key) is not None:
            out[key] = match.get(key)
    # Explicitly drop lan_url — never forward corpus-serve fallbacks.
    return out


def neutralize_retrieve_payload(
    payload: object, *, public_origin: object = ""
) -> dict[str, Any]:
    """Rewrite a /rag/retrieve JSON body so clients never see LAN URLs."""
    if not isinstance(payload, dict):
        return {"matches": [], "collection": ""}
    origin = normalize_public_origin(public_origin)
    matches = payload.get("matches") if isinstance(payload.get("matches"), list) else []
    out = {
        "matches": [
            neutralize_match(m, public_origin=origin) for m in matches if isinstance(m, dict)
        ],
        "collection": str(payload.get("collection") or ""),
    }
    if payload.get("retrieval"):
        out["retrieval"] = str(payload.get("retrieval"))
    return out


def classify_document_kind(source: object = "", title: object = "") -> str:
    """Return manual | index | other for operator presentation gates."""
    src = str(source or "").replace("\\", "/").strip()
    ttl = str(title or "").strip() or src.rsplit("/", 1)[-1]
    ext = os.path.splitext(src)[1].lower() or os.path.splitext(ttl)[1].lower()
    blob = f"{src} {ttl}".lower()
    if ext in _INDEX_EXTS or _INDEX_TITLE_RE.search(ttl) or "knowledgebase" in blob:
        return "index"
    if ext in _MANUAL_EXTS:
        return "manual"
    return "other"


def infer_query_vendor(query: object) -> str:
    """Best-effort vendor family from the operator query."""
    msg = str(query or "")
    low = msg.lower()
    if "honeywell" in low or "tdc3000" in low or "tdc 3000" in low or "experion" in low or _HW_PART.search(msg):
        return "honeywell"
    if "allen" in low or "bradley" in low or "rockwell" in low or _AB_PART.search(msg):
        return "allen_bradley"
    return ""


def infer_source_vendor(source: object = "", title: object = "") -> str:
    blob = f"{source or ''} {title or ''}".lower().replace("\\", "/")
    if "honeywell" in blob or "tdc3000" in blob or "/tdc/" in blob or "experion" in blob or "experian pks" in blob:
        return "honeywell"
    if "allen bradley" in blob or "allen-bradley" in blob or "rockwell" in blob or "/1756/" in blob:
        return "allen_bradley"
    return ""


def vendor_compatible(query_vendor: str, source_vendor: str) -> bool:
    if not query_vendor or not source_vendor:
        return True
    return query_vendor == source_vendor


def extract_query_part_numbers(query: object) -> list[str]:
    """Catalog/part numbers explicitly present in the operator query."""
    msg = str(query or "")
    found: list[str] = []
    for rx in (_HW_PART, _AB_PART):
        for m in rx.finditer(msg):
            found.append(re.sub(r"\s+", "-", m.group(0).upper()))
    return list(dict.fromkeys(found))


def classify_retrieval_intent(query: object) -> str:
    """Operator retrieval class. Wiring/FTA connection is never a generic-manual class."""
    q = str(query or "").lower()
    if re.search(r"\bfta\s+connection\b|\bconnection\s+diagram\b|\bfta\s+diagram\b", q):
        return "fta_connection"
    if re.search(r"\bwiring\s+schematic\b|\bwiring\s+diagram\b|\bschematic\b|\bwiring\b", q):
        return "wiring_schematic"
    if extract_query_part_numbers(q):
        return "part_lookup"
    return "document"


def is_wiring_grade_intent(query: object) -> bool:
    return classify_retrieval_intent(query) in {"wiring_schematic", "fta_connection"}


def is_wiring_narrowing_followup(query: object) -> bool:
    """True when this turn asks for the schematic/diagram without naming a new part.

    Extract/pull/show against an already-bound document stay on review.
    Declining a generic manual in favor of the schematic is a narrowing turn.
    """
    msg = str(query or "").strip()
    if not msg or extract_query_part_numbers(msg):
        return False
    if re.search(
        r"\b(?:extract|pull|show|open|find|get|locate|display|bring\s+up)\b",
        msg,
        re.I,
    ) and not re.search(r"\b(?:do not|don't|dont)\s+need\b.{0,80}\bmanual", msg, re.I):
        return False
    return bool(
        is_wiring_grade_intent(msg)
        or re.search(
            r"\b(?:the\s+)?(?:wiring\s+schematic|fta\s+(?:connection\s+)?diagram|connection\s+diagram)\b",
            msg,
            re.I,
        )
    )


def resolve_validated_part(
    query: object,
    *,
    prior_validated_part: object = None,
    active_document: object = None,
) -> tuple[str, str]:
    """Return (part, source) where source is current_turn|prior_turn_validated|none.

    Malformed/unvalidated tokens are never carried forward.
    """
    current = extract_query_part_numbers(query)
    if current:
        return str(current[0]).strip().upper(), "current_turn"
    prior = str(prior_validated_part or "").strip().upper()
    if not prior and isinstance(active_document, dict):
        prior = str(active_document.get("part_number") or "").strip().upper()
    if prior and extract_query_part_numbers(prior) and is_wiring_narrowing_followup(query):
        return prior, "prior_turn_validated"
    return "", "none"


def _parts_compatible(query_part: object, candidate_part: object) -> bool:
    q = str(query_part or "").strip().upper()
    c = str(candidate_part or "").strip().upper()
    if not q or not c:
        return False
    q_needles = set(_part_match_needles(q))
    c_needles = set(_part_match_needles(c))
    return bool(q_needles & c_needles) or c.lower() in q.lower() or q.lower() in c.lower()


def manual_relevant_to_query_parts(match: dict[str, Any], query_parts: list[str]) -> bool:
    """Reject cross-family manuals (e.g. 1771 PDF for a 1756-OW16I ask)."""
    if not query_parts:
        return True
    pn = str(match.get("part_number") or "").strip()
    observed = str(match.get("observed_part") or "").strip()
    if pn and any(_parts_compatible(q, pn) for q in query_parts):
        return True
    if observed and any(_parts_compatible(q, observed) for q in query_parts):
        return True
    kind = str(match.get("match_kind") or "")
    if kind == "exact" and str(match.get("retrieval") or "") == "tdc3000_custom_index":
        # TDC custom-index exact hits are already part-resolved upstream.
        return True
    blob = " ".join(
        [
            str(match.get("source") or ""),
            str(match.get("snippet") or ""),
            _match_title(match),
            pn,
            observed,
        ]
    )
    return any(_text_mentions_part(blob, q) for q in query_parts)


def _match_title(match: dict[str, Any]) -> str:
    ident = match.get("document_identity") if isinstance(match.get("document_identity"), dict) else {}
    return str((ident or {}).get("title") or match.get("source") or "").rsplit("/", 1)[-1]


def _is_planning_manual(source: object = "", title: object = "") -> bool:
    hay = f"{source} {title}".replace("\\", "/").lower()
    return "hp02500" in hay or "hp02-500" in hay or (
        "planning" in hay and "installation" not in hay
    )


def _is_installation_manual(source: object = "", title: object = "") -> bool:
    hay = f"{source} {title}".replace("\\", "/").lower()
    return "pm20520" in hay or "i/o installation" in hay or "io installation" in hay


_PM_IO_INSTALLATION_REL = (
    "Vendor Data/Honeywell/Experian PKS/TDC3000/Honeywell TDC/pm20520.pdf"
)


def pm_io_installation_source() -> str:
    """Filesystem-relative path of the TDC3000 Process Manager I/O Installation manual."""
    root = library_root()
    if not root:
        return ""
    rel = _PM_IO_INSTALLATION_REL.replace("\\", "/")
    full = os.path.join(root, rel)
    if os.path.isfile(full):
        return rel
    return ""


def retrieve_pm_io_installation_payload(
    part: object, *, query: object = "", public_origin: object = ""
) -> dict[str, Any]:
    """Authoritative first resolver for Honeywell MU/MC Process Manager I/O and FTA.

    Scans PM20-520 (pm20520.pdf) model tables, compatibility statements, and
    Connection Diagram figures. Never returns HP02-500 / planning-manual hits.
    """
    part_s = str(part or "").strip().upper()
    empty: dict[str, Any] = {
        "matches": [],
        "collection": "pm20520_io_installation",
        "retrieval": "pm20520_io_installation",
    }
    source = pm_io_installation_source()
    if not part_s or not source:
        return empty
    found, ftas, counterpart_ok = collect_fta_connection_diagrams_from_source(source, part_s)
    root = library_root()
    texts: list[str] = []
    try:
        texts = _pdf_page_texts(os.path.join(root, source))
    except Exception:
        texts = []
    mentioned = any(_text_mentions_part(page, part_s) for page in texts)
    wiring = is_wiring_grade_intent(query)
    if wiring and not found:
        return empty
    if not wiring and not (mentioned or found):
        return empty
    origin = normalize_public_origin(public_origin)
    href = normalize_corpus_url("", source=source, public_origin=origin) or absolutize_sidecar_href(
        sidecar_preview_path(source), public_origin=origin
    )
    match: dict[str, Any] = {
        "source": source,
        "score": 1.0,
        "match_kind": "exact",
        "part_number": part_s,
        "retrieval": "pm20520_io_installation",
        "revision": "PM20-520",
        "url": href,
        "document_identity": {
            "title": "Process Manager I/O Installation",
            "doc_no": "PM20-520",
            "filename": "pm20520.pdf",
        },
        "figures": found,
        "compatible_ftas": ftas,
        "counterpart_verified": counterpart_ok,
    }
    if found:
        match["pdf_page"] = found[0].get("pdf_page")
        match["figure"] = found[0].get("figure")
        match["printed_page"] = found[0].get("printed_page")
        match["page_hint"] = found[0].get("pdf_page")
        match["snippet"] = str(found[0].get("excerpt") or "")[:900]
    return {
        "matches": [match],
        "collection": "pm20520_io_installation",
        "retrieval": "pm20520_io_installation",
    }


def select_operator_document_match(
    matches: object, *, query: object = ""
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Pick operator-facing manual vs optional index; enforce vendor/part gates."""
    items = [m for m in (matches if isinstance(matches, list) else []) if isinstance(m, dict)]
    q_vendor = infer_query_vendor(query)
    query_parts = extract_query_part_numbers(query)
    query_tokens = set(re.findall(r"[a-z0-9]+", str(query or "").lower()))
    query_tokens -= {
        "open", "the", "a", "an", "doc", "dock", "document", "please", "lets",
        "need", "user", "manual", "wiring", "schematics", "schematic", "for",
        "honeywell", "iota", "find", "pull", "link", "show", "want", "can",
        "you", "me", "next", "page", "extract",
    }
    wants_wiring = any(
        w in str(query or "").lower()
        for w in ("wiring", "schematic", "connection", "pinout", "fta")
    )
    manuals: list[dict[str, Any]] = []
    indexes: list[dict[str, Any]] = []
    for match in items:
        source = str(match.get("source") or "").replace("\\", "/")
        title = _match_title(match)
        kind = classify_document_kind(source, title)
        src_vendor = infer_source_vendor(source, title)
        if not vendor_compatible(q_vendor, src_vendor):
            continue
        if kind == "manual":
            if not manual_relevant_to_query_parts(match, query_parts):
                continue
            if (wants_wiring or query_parts) and _is_planning_manual(source, title):
                continue
            manuals.append(match)
        elif kind == "index":
            indexes.append(match)

    def _rank_key(match: dict[str, Any]) -> tuple[int, int, int, int, int, float]:
        exact = 1 if str(match.get("match_kind") or "") == "exact" else 0
        tdc = 1 if str(match.get("retrieval") or "") == "tdc3000_custom_index" else 0
        title = _match_title(match)
        source = str(match.get("source") or "")
        blob_tokens = set(re.findall(r"[a-z0-9]+", f"{title} {source}".lower()))
        overlap = len(query_tokens & blob_tokens) if query_tokens else 0
        try:
            score = float(match.get("score") or 0.0)
        except Exception:
            score = 0.0
        install = 1 if (wants_wiring or query_parts) and _is_installation_manual(source, title) else 0
        planning = 1 if (wants_wiring or query_parts) and _is_planning_manual(source, title) else 0
        return (exact, tdc, install, 0 if planning else 1, overlap, score)

    manuals.sort(key=_rank_key, reverse=True)
    indexes.sort(key=_rank_key, reverse=True)
    return (manuals[0] if manuals else None, indexes[0] if indexes else None)


def _top_document_match(matches: object) -> dict[str, Any] | None:
    """Backward-compatible top match — manuals only (never xlsx/index)."""
    manual, _index = select_operator_document_match(matches, query="")
    if manual:
        return manual
    # Legacy fallback: first PDF/DOC with URL, still never an index/xlsx.
    items = matches if isinstance(matches, list) else []
    for match in items:
        if not isinstance(match, dict) or not match.get("url"):
            continue
        source = str(match.get("source") or "")
        if classify_document_kind(source, _match_title(match)) != "manual":
            continue
        return match
    return None


def build_operator_document_reply(
    matches: object, *, query: object = "", public_origin: object = ""
) -> tuple[str, dict[str, Any] | None]:
    """Clean operator-facing PA answer + optional pending_action payload.

    Returns (reply, pending_action_dict_or_None).
    """
    origin = normalize_public_origin(public_origin)
    manual, index = select_operator_document_match(matches, query=query)
    q = str(query or "").lower()
    wants_wiring = is_wiring_grade_intent(query) or any(
        w in q for w in ("wiring", "schematic", "connection", "pinout")
    )
    query_parts = extract_query_part_numbers(query)

    def _wiring_unavailable(part_s: str) -> tuple[str, None]:
        who = f" for **{part_s}**" if part_s else ""
        unavailable = (
            f"I cannot yet verify an authoritative wiring or FTA connection diagram"
            f"{who}. I will not substitute a generic planning manual, a compatibility "
            "table, or an unverified page/figure. Provide the exact part number if this "
            "token is a transcription, or bind a verified installation manual."
        )
        return unavailable, None

    if not isinstance(manual, dict) and isinstance(index, dict):
        if wants_wiring and _HW_PART.search(str(query or "")):
            return _wiring_unavailable((query_parts[0] if query_parts else ""))
        item = neutralize_match(index, public_origin=origin)
        title = _match_title(item) or "lookup index"
        href = str(item.get("url") or "").strip()
        lines = [
            f"I found a **lookup index**, not an engineering installation manual:",
            "",
            f"**{title}**",
            "",
            "This file is a part-number knowledgebase/index. I will not treat it as a manual "
            "and I cannot extract a wiring schematic page from it.",
        ]
        if href:
            lines.extend(["", f"[Open index]({href})"])
        lines.extend(
            [
                "",
                "Provide a document number or a more specific part/vendor cue so I can resolve the actual manual.",
            ]
        )
        return "\n".join(lines), None

    if not isinstance(manual, dict):
        if wants_wiring or (query_parts and _HW_PART.search(str(query_parts[0]))):
            return _wiring_unavailable((query_parts[0] if query_parts else ""))
        return (
            "I could not find a matching engineering-library manual for that request. "
            "Try a document number (for example 02-315) or a Honeywell part number.",
            None,
        )

    item = neutralize_match(manual, public_origin=origin)
    ident = item.get("document_identity") if isinstance(item.get("document_identity"), dict) else {}
    title = str((ident or {}).get("title") or "").strip() or str(item.get("source") or "manual").rsplit("/", 1)[-1]
    doc_no = str((ident or {}).get("doc_no") or item.get("revision") or "").strip()
    part = str(item.get("part_number") or "").strip()
    if query_parts:
        part = query_parts[0]
    kind = str(item.get("match_kind") or "").strip()
    href = str(item.get("url") or "").strip()
    page = item.get("page_hint")
    identity = f"**{title}**" + (f" (**{doc_no}**)" if doc_no else "")
    pending = None

    if kind == "near_family":
        observed = str(item.get("observed_part") or "").strip()
        lines = [
            f"I found a **near-family** manual, not an exact substitute for **{part or 'the requested part'}**"
            + (f" (related: {observed})." if observed else "."),
            "",
            identity,
            "",
            f"[Open manual]({href})" if href else "",
            "",
            "Want me to keep searching for an exact part match?",
        ]
        return "\n".join(line for line in lines if line is not None).strip(), None

    who = f" for **{part}**" if part else ""
    if kind == "publication_alias":
        pub_id = str((ident or {}).get("publication_identifier") or doc_no).strip()
        filename = str((ident or {}).get("filename") or "").strip()
        lines = [
            f"I found **{doc_no or title}** in the 1756 library:",
            "",
            identity,
        ]
        if pub_id and pub_id != doc_no:
            lines.extend(["", f"Publication **{pub_id}**."])
        if filename:
            lines.extend(["", f"File: `{filename}`"])
        if href:
            lines.extend(["", f"[Open {doc_no or 'manual'}]({href})"])
        return "\n".join(line for line in lines if line is not None).strip(), None
    if wants_wiring:
        schematic = try_first_reply_fta_schematic(
            item, part=part, public_origin=origin
        )
        if schematic:
            return schematic, None
        return _wiring_unavailable(part)
    lines = [
        f"I found the engineering-library manual{who}:",
        "",
        identity,
    ]
    if href:
        lines.extend(["", f"[Open manual]({href})"])
    return "\n".join(lines), pending


def build_retrieval_receipt(matches: object, *, query: object = "") -> dict[str, Any]:
    """Internal provenance only — never dump into operator chat prose."""
    manual, index = select_operator_document_match(matches, query=query)
    top = manual or index or {}
    ident = top.get("document_identity") if isinstance(top.get("document_identity"), dict) else {}
    return {
        "schema": "smedley.document_route_receipt.v1",
        "query": str(query or "").strip(),
        "match_kind": top.get("match_kind"),
        "part_number": top.get("part_number"),
        "observed_part": top.get("observed_part"),
        "document_identity": ident or None,
        "revision": top.get("revision"),
        "page_hint": top.get("page_hint"),
        "index_href": top.get("index_href"),
        "index_formats": top.get("index_formats"),
        "source": top.get("source"),
        "url": top.get("url"),
        "retrieval": top.get("retrieval"),
        "score": top.get("score"),
        "document_kind": classify_document_kind(top.get("source"), _match_title(top)) if top else None,
        "query_vendor": infer_query_vendor(query) or None,
        "source_vendor": infer_source_vendor(top.get("source"), _match_title(top)) if top else None,
        "index_source": (index or {}).get("source") if index and manual else None,
    }


def build_deterministic_document_reply(
    matches: object, *, query: object = "", public_origin: object = ""
) -> str:
    """Operator-visible document-route reply (clean PA answer)."""
    reply, _pending = build_operator_document_reply(
        matches, query=query, public_origin=public_origin
    )
    return reply


def build_compact_spoken_document_reply(
    matches: object, *, query: object = ""
) -> str:
    """Natural TTS only — no markdown, URLs, scores, or retrieval tokens."""
    manual, index = select_operator_document_match(matches, query=query)
    if not isinstance(manual, dict) and isinstance(index, dict):
        title = _match_title(index) or "a lookup index"
        return (
            f"I found a lookup index, {title}, not an installation manual. "
            "I cannot extract a wiring schematic from an index."
        )
    top = manual
    if not isinstance(top, dict):
        return "I could not find that manual in the engineering library."
    ident = top.get("document_identity") if isinstance(top.get("document_identity"), dict) else {}
    title = str((ident or {}).get("title") or "").strip() or "the engineering manual"
    doc_no = str((ident or {}).get("doc_no") or top.get("revision") or "").strip()
    part = str(top.get("part_number") or "").strip()
    kind = str(top.get("match_kind") or "").strip()
    # Speak document numbers naturally: PM20-520 -> PM 20-520
    doc_spoken = re.sub(r"([A-Z]{1,4})(\d{2})-(\d{3})", r"\1 \2-\3", doc_no) if doc_no else ""
    if kind == "near_family":
        return (
            f"I found a near-family manual, {title}"
            + (f", document {doc_spoken}" if doc_spoken else "")
            + f", not an exact substitute for {part or 'the requested part'}. "
            "The manual is on screen."
        )
    who = f" for {part}" if part else ""
    bits = [f"I found {title}{who}."]
    if kind == "publication_alias" and doc_no:
        bits = [f"I found {doc_no}, {title}."]
    elif doc_spoken:
        bits = [f"I found {title}, document {doc_spoken}{who}."]
    q = str(query or "").lower()
    if any(w in q for w in ("wiring", "schematic", "connection", "pinout")):
        page = top.get("page_hint")
        if page not in (None, ""):
            bits.append(f"Wiring schematic is on page {page}.")
        else:
            bits.append("The wiring schematic page still needs extraction.")
    bits.append("The manual is on screen.")
    return " ".join(bits)


# Spoken-output sanitizer: keep visible markdown/HTML links intact in chat;
# strip TTS-hostile URLs, link markup (including filenames/titles), scores,
# document-route chrome, UI metadata, and raw retrieval payloads.
_DOC_ROUTE_HEADER_RE = re.compile(
    r"(?im)^[ \t]*Document links(?:\s+for\s+[“\"][^”\"]*[”\"])?"
    r"(?:\s*\(sidecar preview\))?\s*:?[ \t]*\n?"
)
_DOC_ROUTE_HEADER_INLINE_RE = re.compile(
    r"(?i)\bDocument links(?:\s+for\s+[“\"][^”\"]*[”\"])?"
    r"(?:\s*\(sidecar preview\))?\s*:?"
)
_SCORE_META_RE = re.compile(r"\(\s*score\s*=\s*[-+]?\d*\.?\d+\s*\)", re.IGNORECASE)
_MD_LINK_DROP_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)|\[[^\]]*\]\([^)]+\)")
_RAW_URL_RE = re.compile(r"https?://[^\s<>\]\)\"']+", re.IGNORECASE)
_SIDECAR_PATH_RE = re.compile(
    r"(?i)/api/extensions/smedley-engineering/sidecar/(?:preview|doc)/[^\s<>\]\)\"']*"
)
_BARE_FILENAME_RE = re.compile(
    r"\b[\w./\\-]+\.(?:pdf|docx?|xlsx?|pptx?|txt|md)\b",
    re.IGNORECASE,
)
_JSON_OBJECT_RE = re.compile(r"\{[^{}]*\}")
_RETRIEVAL_KEY_RE = re.compile(
    r'(?i)"(?:matches|collection|lan_url|snippet|source|score|url|markdown)"\s*:'
)
_RETRIEVAL_FIELD_RE = re.compile(
    r"(?i)\b(?:matches|collection|snippet|source|topk|library_only|"
    r"snippet_chars)\b\s*[:=]\s*",
)
_UI_META_RES = (
    re.compile(r"(?i)\b(?:sidecar preview|lan_url)\b\s*:?"),
    re.compile(r"(?i)\b(?:card title|source pill|owner\s*ack)\b\s*:?"),
)


def _strip_retrieval_payload(value: str) -> str:
    """Drop raw RAG/retrieve JSON blobs and leftover retrieval field chrome."""
    text = value
    for _ in range(8):
        changed = False

        def _drop_retrieval_object(match: re.Match[str]) -> str:
            nonlocal changed
            body = match.group(0)
            if _RETRIEVAL_KEY_RE.search(body):
                changed = True
                return " "
            return body

        nxt = _JSON_OBJECT_RE.sub(_drop_retrieval_object, text)
        if nxt == text and not changed:
            break
        text = nxt
    text = _RETRIEVAL_FIELD_RE.sub(" ", text)
    # Fail closed: any residue still shaped like a retrieve payload is not prose.
    if _RETRIEVAL_KEY_RE.search(text) or re.search(
        r'(?i)\b(?:matches|collection)\b\s*[:=]', text
    ):
        return ""
    return text


def sanitize_for_spoken_output(text: object) -> str:
    """Return voice-safe answer prose only — no URLs, filenames, or UI chrome.

    Visible chat replies keep clickable markdown links. This sanitizer is the
    spoken-output twin used before TTS (document-route replies and ordinary
    assistant text that cites corpus links). Filenames and link titles are
    dropped so PTT speaks the answer body, not retrieval chrome.
    """
    value = str(text or "")
    if not value.strip():
        return ""

    # Drop document-route / card-title boilerplate before link rewriting.
    value = _DOC_ROUTE_HEADER_RE.sub(" ", value)
    value = _DOC_ROUTE_HEADER_INLINE_RE.sub(" ", value)
    value = _SCORE_META_RE.sub(" ", value)
    for pattern in _UI_META_RES:
        value = pattern.sub(" ", value)

    # Raw retrieval JSON / field dumps must never be spoken.
    value = _strip_retrieval_payload(value)
    if not value.strip():
        return ""

    # Markdown links and images → drop entirely (no filename / title spoken).
    value = _MD_LINK_DROP_RE.sub(" ", value)

    # Any remaining raw WebUI / absolute URLs must not be spoken.
    value = _RAW_URL_RE.sub(" ", value)
    value = _SIDECAR_PATH_RE.sub(" ", value)

    # Bare corpus filenames left after link stripping (list rows, etc.).
    value = _BARE_FILENAME_RE.sub(" ", value)

    # Light markdown / chrome cleanup (parity with client _stripForTTS).
    value = re.sub(r"(?m)^[ \t]*#{1,6}\s+", "", value)
    value = re.sub(r"`[^`]+`", " ", value)
    value = re.sub(r"\*\*(.+?)\*\*", r"\1", value)
    value = re.sub(r"\*(.+?)\*", r"\1", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(
        r"[\U0001F300-\U0001F9FF\U0001FA00-\U0001FAFF\u2600-\u27BF\uFE0F\u200D📄]",
        "",
        value,
    )
    # List markers → spaces; newlines → sentence breaks.
    value = re.sub(r"(?m)^[ \t]*[-*•]\s+", "", value)
    value = re.sub(r"\n+", ". ", value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    value = re.sub(r"([.!?])\1+", r"\1", value)
    value = re.sub(r"\.\s*\.", ".", value)
    return value.strip(" \t.-")


def rag_retrieve_url() -> str:
    return (os.environ.get(RAG_RETRIEVE_URL_ENV) or DEFAULT_RAG_RETRIEVE_URL).strip()


def retrieve_documents(
    query: str,
    *,
    topk: int = 8,
    timeout: float = 45.0,
    public_origin: object = "",
) -> dict[str, Any]:
    """POST to Smedley RAG retrieve; return neutralized matches payload."""
    origin = normalize_public_origin(public_origin)
    body = {
        "query": str(query or "").strip(),
        "topk": max(1, min(int(topk), 20)),
        "snippet_chars": 900,
        "filter": {"library_only": True},
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        rag_retrieve_url(),
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            payload = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        raise RuntimeError(f"RAG retrieve HTTP {exc.code}: {detail}") from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"RAG retrieve failed: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("RAG retrieve returned non-object JSON")
    return neutralize_retrieve_payload(payload, public_origin=origin)


def active_document_from_matches(
    matches: object, *, query: object = "", public_origin: object = ""
) -> dict[str, str]:
    """Return the one canonical manual selected for session-scoped review.

    Must match the same manual shown in the operator reply. Indexes/xlsx are never bound.
    """
    origin = normalize_public_origin(public_origin)
    manual, _index = select_operator_document_match(matches, query=query)
    if not isinstance(manual, dict):
        return {}
    item = neutralize_match(manual, public_origin=origin)
    source = str(item.get("source") or "").strip().replace("\\", "/")
    ext = os.path.splitext(source)[1].lower()
    if not (source and ext in _MANUAL_EXTS):
        return {}
    if classify_document_kind(source, _match_title(item)) != "manual":
        return {}
    ident = item.get("document_identity") if isinstance(item.get("document_identity"), dict) else {}
    title = str((ident or {}).get("title") or source.rsplit("/", 1)[-1])
    record = {
        "source": source,
        "url": str(item.get("url") or ""),
        "title": title,
        "document_kind": "manual",
        "query_vendor": infer_query_vendor(query) or "",
        "source_vendor": infer_source_vendor(source, title) or "",
    }
    if ident:
        for key in ("doc_no", "filename", "category", "pages", "status"):
            if ident.get(key) is not None:
                record[key] = ident.get(key)
    if item.get("part_number"):
        record["part_number"] = str(item.get("part_number"))
    if item.get("match_kind"):
        record["match_kind"] = str(item.get("match_kind"))
    if item.get("index_href"):
        record["index_href"] = str(item.get("index_href"))
    if item.get("revision"):
        record["revision"] = str(item.get("revision"))
    return record


def _active_document_source(active_document: object) -> str:
    if not isinstance(active_document, dict):
        return ""
    source = str(active_document.get("source") or "").strip().replace("\\", "/")
    if not source or source.startswith("/") or ".." in source.split("/"):
        return ""
    if os.path.splitext(source)[1].lower() not in _MANUAL_EXTS:
        return ""
    return source


def is_affirmative_followup(query: object) -> bool:
    """True for short explicit affirmatives that accept the offered next action."""
    return bool(_AFFIRMATIVE_FOLLOWUP_RE.match(str(query or "").strip()))


def is_negative_followup(query: object) -> bool:
    """True for short explicit declines that reject the offered next action."""
    return bool(_NEGATIVE_FOLLOWUP_RE.match(str(query or "").strip()))


def governing_source_guidance_topic(query: object) -> str:
    """Return the stated engineering topic when the query is governing-source
    guidance ("That is the manual to use when asked about X"), else ''.

    This never returns a truthy value for an ordinary new document request --
    the phrasing has no document number/name of its own to look up.
    """
    msg = str(query or "").strip()
    if not msg:
        return ""
    m = _GOVERNING_SOURCE_GUIDANCE_RE.match(msg)
    if not m:
        return ""
    topic = re.sub(r"\s+", " ", m.group("topic") or "").strip()
    return topic


def is_governing_source_guidance(query: object) -> bool:
    return bool(governing_source_guidance_topic(query))


def _governing_topic_key(topic: str) -> str:
    """Loosely normalize a stated topic to a stable key for later matching."""
    low = str(topic or "").lower()
    if _CHASSIS_POWER_TOPIC_RE.search(low) or re.search(
        r"\b(?:power\s+suppl(?:y|ies)|psu)\b.*\b(?:chassis|1756)\b|"
        r"\b(?:1756)\b.*\bpower\s+suppl(?:y|ies)\b",
        low,
    ):
        return "controllogix_chassis_power"
    slug = re.sub(r"[^a-z0-9]+", "_", low).strip("_")
    return slug or "general"


def _slot_count_from_text(text: object) -> str:
    """Return chassis slot count from a free-text ask or follow-up."""
    msg = str(text or "").strip()
    if not msg:
        return ""
    m = _SLOT_FOLLOWUP_RE.match(msg) or _SLOT_IN_TEXT_RE.search(msg)
    return str(m.group(1)) if m else ""


def _pending_retrieval_action(pending: object) -> str:
    """Return pending retrieval action name, or '' if not a retrieval pending."""
    if not isinstance(pending, dict):
        return ""
    action = str(pending.get("action") or "").strip()
    if action in {
        _PENDING_CHASSIS_SIZING_ACTION,
        _PENDING_IFM_LOOKUP_ACTION,
        "retrieve_part_manual",
    }:
        return action
    return ""


def is_wiring_extract_followup(query: object) -> bool:
    """True for offered follow-ups like 'extract the wiring diagram'.

    Must not swallow a new document lookup that merely mentions wiring/schematics
    (e.g. 'user manual ... wiring schematics for MC-PDIX02') while an older
    active_document is still bound.
    """
    msg = str(query or "").strip()
    if not msg or not _ACTIVE_DOCUMENT_WIRING_EXTRACT_RE.search(msg):
        return False
    # Fresh part/doc lookups belong to document_route, not extract-on-bound-doc.
    if _HW_PART.search(msg) or _AB_PART.search(msg) or _DOCNUM.search(msg):
        return False
    mentions_manual = bool(
        re.search(
            r"\b(?:user\s+)?manuals?\b|\bdatasheets?\b|\bknowledgebase\b|\biota\b|\biom\b",
            msg,
            re.IGNORECASE,
        )
    )
    if mentions_manual and not re.search(r"\bextract\b", msg, re.IGNORECASE):
        # Declining a generic manual in favor of the schematic is a wiring
        # follow-up, not a new manual lookup.
        if re.search(r"\b(?:do not|don't|dont)\s+need\b.{0,80}\bmanual", msg, re.I):
            return True
        return False
    return True


def _pending_extract_bound(active_document: object) -> bool:
    if not isinstance(active_document, dict):
        return False
    pending = active_document.get("pending_action")
    if isinstance(pending, dict):
        return str(pending.get("action") or "") == _PENDING_EXTRACT_ACTION
    return str(pending or "") == _PENDING_EXTRACT_ACTION


def is_active_document_review_request(query: object, active_document: object) -> bool:
    """True for section/text/wiring follow-ups after a document was selected."""
    if not _active_document_source(active_document):
        return False
    msg = str(query or "").strip()
    if not msg:
        return False
    if is_library_path_operation(msg):
        return False
    if is_wiring_extract_followup(msg):
        if _pending_extract_bound(active_document):
            return True
        # Artifact-narrowing ("I need the wiring schematic") after a validated
        # part must re-enter document retrieve for a figure packet, not extract
        # from a possibly-wrong bound planning manual.
        if is_wiring_narrowing_followup(msg):
            return False
        return True
    if is_affirmative_followup(msg) and _pending_extract_bound(active_document):
        return True
    # A bare decline only means something when there is an actual pending
    # offer to decline -- otherwise leave it to fall through as ordinary chat.
    if is_negative_followup(msg) and _pending_extract_bound(active_document):
        return True
    # Narrow governing-source guidance ("That is the manual to use when asked
    # about X") names no new document of its own -- it must bind the already
    # active document to the stated topic, never fall through to a generic
    # document-route lookup (which has nothing to find and would otherwise
    # drop the binding entirely). Checked before the "do not steal" guard
    # below since is_document_request() can false-positive on this phrasing.
    if is_governing_source_guidance(msg):
        return True
    # Do not steal a new document-route lookup into review of a prior binding.
    if is_document_request(msg) and not is_affirmative_followup(msg):
        return False
    return bool(
        _ACTIVE_DOCUMENT_SECTION_RE.search(msg)
        or _ACTIVE_DOCUMENT_FOLLOWUP_RE.search(msg)
        or _ACTIVE_DOCUMENT_RECOMMENDATION_RE.search(msg)
    )


def library_root() -> str:
    env = str(os.environ.get(_LIBRARY_ROOT_ENV) or "").strip()
    if env and os.path.isdir(env):
        return os.path.realpath(env)
    for candidate in _DEFAULT_LIBRARY_ROOTS:
        if os.path.isdir(candidate):
            return os.path.realpath(candidate)
    return ""


def resolve_active_document_filesystem_path(active_document: object) -> str:
    """Resolve session active_document.source under the library root (no path escape)."""
    source = _active_document_source(active_document)
    root = library_root()
    if not source or not root:
        return ""
    full = os.path.realpath(os.path.join(root, source))
    root_real = os.path.realpath(root)
    if full != root_real and not full.startswith(root_real + os.sep):
        return ""
    if not os.path.isfile(full):
        return ""
    return full


def _preview_url_for_source(source: str) -> str:
    base = rag_retrieve_url()
    parts = urllib.parse.urlsplit(base)
    if parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("active document preview requires the local Smedley RAG service")
    origin = f"{parts.scheme}://{parts.netloc}"
    return origin + "/preview/" + urllib.parse.quote(source, safe="/")


def fetch_active_document_text(source: object, *, timeout: float = 15.0) -> str:
    """Read text from the existing, safe Word/PDF sidecar preview service."""
    normalized = _active_document_source({"source": source})
    if not normalized:
        raise RuntimeError("invalid active document source")
    request = urllib.request.Request(
        _preview_url_for_source(normalized), headers={"Accept": "text/html"}, method="GET"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(MAX_ACTIVE_DOCUMENT_PREVIEW_BYTES + 1)
    if len(body) > MAX_ACTIVE_DOCUMENT_PREVIEW_BYTES:
        raise RuntimeError("document preview exceeds review limit")
    parser = _PreviewTextExtractor()
    parser.feed(body.decode("utf-8", errors="replace"))
    text = re.sub(r"\n{2,}", "\n", parser.text())
    if not text.strip():
        raise RuntimeError("document preview contained no extractable text")
    return text.strip()


def _section_candidates(query: str) -> list[str]:
    raw = [m.group(1) for m in _ACTIVE_DOCUMENT_SECTION_RE.finditer(query)]
    candidates: list[str] = []
    for value in raw:
        candidates.extend([value, value.replace("-", "."), value.replace(".", "-")])
    return list(dict.fromkeys(candidates))


def extract_active_document_passage(text: object, query: object) -> str:
    """Return the requested section plus nearby prose, never a whole document."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in str(text or "").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    def _excerpt_at(index: int) -> str:
        selected = [lines[index]]
        for nearby in lines[index + 1:index + 7]:
            # Stop at the next numbered heading; do not bleed a later section
            # into the requested passage.
            if re.match(r"^(?:SECTION\s+)?\d+(?:[.\-]\d+)*[.\s:—-]", nearby, re.I):
                break
            selected.append(nearby)
        return " ".join(selected)[:2400].strip()

    candidates = _section_candidates(str(query or ""))
    for candidate in candidates:
        heading = re.compile(rf"^(?:SECTION\s+)?{re.escape(candidate)}[.\s:—-]", re.I)
        for index, line in enumerate(lines):
            if heading.search(line):
                nearby = lines[index + 1:index + 5]
                if any("PAGEREF" in item.upper() for item in nearby):
                    # Converted legacy Word tables of contents split a section
                    # number and title into separate HTML nodes.  Resolve that
                    # title to the later body heading instead of reading TOC.
                    title = next((item for item in nearby if item.isalpha()), "")
                    if title:
                        for body_index in range(index + len(nearby) + 1, len(lines)):
                            if lines[body_index].casefold() == title.casefold():
                                return _excerpt_at(body_index)
                    continue
                return _excerpt_at(index)
    # A Word preview may lose heading punctuation. Match the requested label in
    # prose as a bounded fallback, then return only local context.
    for candidate in candidates:
        needle = re.compile(rf"\b{re.escape(candidate)}\b", re.I)
        for index, line in enumerate(lines):
            if needle.search(line):
                return " ".join(lines[index:index + 6])[:2400].strip()
    return ""


def _part_match_needles(part: object) -> list[str]:
    """Honeywell MU-/MC- prefixes are conformal-coat variants of the same family."""
    raw = str(part or "").strip().upper()
    if not raw:
        return []
    needles = [raw.lower()]
    m = re.match(r"^(M[UC])-([A-Z0-9]+)$", raw)
    if m:
        body = m.group(2)
        needles.extend([f"mu-{body.lower()}", f"mc-{body.lower()}", body.lower()])
    return list(dict.fromkeys(needles))


def _text_mentions_part(text: object, part: object) -> bool:
    low = str(text or "").lower()
    for needle in _part_match_needles(part):
        if not needle:
            continue
        # Boundary-aware: 1756-OB16I must not match 1756-OB16IEF.
        if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", low):
            return True
    return False


def _part_mention_span(text: object, part: object) -> tuple[int, int] | None:
    """First boundary-aware span of any part-family needle in text, or None."""
    low = str(text or "").lower()
    for needle in _part_match_needles(part):
        if not needle:
            continue
        m = re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", low)
        if m:
            return m.span()
    return None


def _part_centered_excerpt(text: object, part: object, *, width: int = 900) -> str:
    """Excerpt centered on the verified part mention, not a naive page-start slice.

    A multi-part comparison table can put unrelated family text before the
    exact part's own sentence; slicing from character 0 can foreground that
    unrelated text and cut the part confirmation off entirely. Center the
    window on the actual match so the part-number sentence is visible.
    """
    raw = str(text or "")
    collapsed = re.sub(r"\s+", " ", raw).strip()
    if not collapsed:
        return ""
    span = _part_mention_span(collapsed, part)
    if not span:
        return collapsed[:width]
    start, end = span
    mid = (start + end) // 2
    half = width // 2
    win_start = max(0, mid - half)
    win_end = win_start + width
    if win_end > len(collapsed):
        win_end = len(collapsed)
        win_start = max(0, win_end - width)
    excerpt = collapsed[win_start:win_end]
    if win_start > 0:
        excerpt = "…" + excerpt
    if win_end < len(collapsed):
        excerpt = excerpt + "…"
    return excerpt


def _score_wiring_page(text: str, *, part: str) -> tuple[int, list[str]]:
    low = str(text or "").lower()
    reasons: list[str] = []
    score = 0
    if _text_mentions_part(low, part):
        score += 50
        reasons.append("part_hit")
    if re.search(r"\bfigure\s+\d+", low):
        score += 12
        reasons.append("figure")
    if "connection diagram" in low:
        score += 25
        reasons.append("connection_diagram")
    if "wiring" in low:
        score += 10
        reasons.append("wiring")
    if "schematic" in low:
        score += 10
        reasons.append("schematic")
    if "terminal" in low:
        score += 4
        reasons.append("terminal")
    if "iop compatibility" in low or "compatible with the model" in low:
        score += 8
        reasons.append("iop_compat")
    return score, reasons


def _figure_refs(text: str) -> list[str]:
    refs = re.findall(r"\bFigure\s+(\d+[-\u2013]\d+)\b", str(text or ""), flags=re.I)
    # Normalize en-dash
    return list(dict.fromkeys(r.replace("\u2013", "-") for r in refs))


_SCHEMATIC_CAPTION_RE = re.compile(
    r"\b(?:wiring|schematic|cabling|cable|connection|pinning|pin[- ]?out)\b",
    re.IGNORECASE,
)


def _verified_figure_for_part(text: object, part: object) -> str:
    """Figure number of a wiring/schematic/cabling/pinning figure captioned FOR
    this exact part/model, or '' if none.

    A page that merely mentions the part in a compatibility table -- while an
    unrelated figure for a different assembly happens to sit on the same page
    -- must not qualify. The figure's OWN caption must name this part's model
    family, not just co-occur with it.
    """
    raw = str(text or "")
    if not str(part or "").strip():
        return ""
    low = raw.lower()
    # A "List of Figures" / table-of-contents page repeats many captions with
    # trailing page-number leaders -- it is not the actual figure page and
    # must never be claimed as a verified diagram location.
    if "table of contents" in low or low.count("figure ") > 5:
        return ""
    for m in re.finditer(r"\bFigure\s+(\d+[-\u2013]\d+)[ \t]*", raw, re.IGNORECASE):
        fig_no = m.group(1)
        window = raw[m.end():m.end() + 300]
        # A genuine figure CAPTION is a heading -- "Figure 4-8          Model
        # MU-TDID52/72 ...". A narrative body sentence that merely REFERS to
        # a figure elsewhere on the page reads as a lowercase continuation --
        # "Figure 4-8 is a connection diagram for the screw terminal-type
        # model MU-TDID52...". Requiring the immediate next token to start
        # uppercase (a heading) rejects the narrative-sentence case, which
        # would otherwise let an unrelated compatible-FTA name mentioned
        # later in that same sentence falsely verify this page.
        first_char = window.lstrip(" \t")[:1]
        if first_char.isalpha() and first_char.islower():
            continue
        # A real figure caption often wraps across 2-4 lines in extracted PDF
        # text (e.g. "...24 Vdc Digital Input FTA\nConnection Diagram") --
        # capturing only the first line silently drops the very word
        # ("Connection"/"Diagram"/"Wiring") that proves it is a schematic.
        # Join the caption block: everything up to the next blank line or the
        # next "Figure N-N" token, capped to a few lines so an unrelated body
        # paragraph further down the page can never be pulled in.
        caption_lines: list[str] = []
        for line in window.split("\n"):
            stripped = line.strip()
            if not stripped:
                break
            if re.match(r"^Figure\s+\d+[-\u2013]\d+\b", stripped, re.IGNORECASE):
                break
            caption_lines.append(stripped)
            if len(caption_lines) >= 4:
                break
        caption = " ".join(caption_lines)
        if not _SCHEMATIC_CAPTION_RE.search(caption):
            continue
        if _text_mentions_part(caption, part):
            return fig_no.replace("\u2013", "-")
    return ""


def _caption_model_label(text: object, fig_no: object, fallback: object) -> str:
    """The figure's own caption model token (e.g. 'MU-TDID52/72'), verbatim,
    or ``fallback`` if the caption text can't be isolated. Used only for
    display -- never changes which figure/page was actually verified."""
    raw = str(text or "")
    fig = str(fig_no or "").strip()
    if fig:
        m = re.search(
            rf"\bFigure\s+{re.escape(fig)}\b[ \t]*Model\s+((?:MU|MC)-[A-Z0-9]+(?:\s*/\s*\d+)?)",
            raw,
            re.IGNORECASE,
        )
        if m:
            return re.sub(r"\s*/\s*", "/", m.group(1).upper())
    return str(fallback or "").strip()


def compact_fta_connection_spoken(part: object, figure: object, printed_page: object) -> str:
    """Jarvis TTS for a verified FTA connection diagram — no audit/PDF/URL prose."""
    part_s = str(part or "").strip()
    fig_s = str(figure or "").strip()
    printed_s = str(printed_page or "").strip()
    if not (part_s and fig_s and printed_s):
        return ""
    return f"{part_s}. I found Figure {fig_s}, printed page {printed_s}. The diagram is open."


def _printed_page_number(text: object) -> str:
    """Derive the document's own printed/footer page number from its own
    header/footer line, e.g. '152 Process Manager I/O Installation 3/98' ->
    '152', or '3/98 Process Manager I/O Installation 151' -> '151'.

    This is derived per-page from the document's own rendered header/footer,
    never assumed from a universal PDF-index-to-printed-page offset --
    different manuals (and even different sections of the same manual, e.g.
    front matter vs. body) can shift that offset. Extraction backend also
    varies (pypdf renders this line first; the pdftotext -layout fallback can
    place the same physical footer line last), so both ends are checked.
    """
    raw = str(text or "")
    lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
    if not lines:
        return ""

    def _page_num_in_line(line: str) -> str:
        tokens = line.split()
        if not tokens:
            return ""
        # Only trust this as a page-number line when a revision-code token
        # (e.g. '3/98') is also present -- otherwise a bare leading/trailing
        # number could be an unrelated figure/table digit.
        if not any(re.fullmatch(r"\d{1,2}/\d{2,4}", tok) for tok in tokens):
            return ""
        if re.fullmatch(r"\d{1,4}", tokens[0]):
            return tokens[0]
        if re.fullmatch(r"\d{1,4}", tokens[-1]):
            return tokens[-1]
        return ""

    for candidate in (lines[0], lines[-1]):
        found = _page_num_in_line(candidate)
        if found:
            return found
    return ""


_PDF_TEXT_CACHE: dict[tuple[str, float], list[str]] = {}


def _pdf_page_texts(pdf_path: str) -> list[str]:
    """Return 1:1 page texts via pypdf or pdftotext (WebUI runtime may lack pypdf)."""
    try:
        mtime = os.path.getmtime(pdf_path)
    except OSError:
        mtime = 0.0
    cache_key = (os.path.realpath(pdf_path), mtime)
    cached = _PDF_TEXT_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        out: list[str] = []
        for page in reader.pages:
            try:
                out.append(page.extract_text() or "")
            except Exception:
                out.append("")
        if out:
            _PDF_TEXT_CACHE[cache_key] = out
            return out
    except Exception:
        pass

    pdftotext = "/opt/homebrew/bin/pdftotext"
    if not os.path.isfile(pdftotext):
        pdftotext = "pdftotext"
    try:
        proc = subprocess.run(
            [pdftotext, "-layout", pdf_path, "-"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"pdftotext failed: {type(exc).__name__}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:200]
        raise RuntimeError(f"pdftotext rc={proc.returncode}: {detail or 'failed'}")
    # Form-feed separates pages.
    pages = str(proc.stdout or "").split("\f")
    # Trailing empty page from final form-feed.
    while pages and not pages[-1].strip():
        pages.pop()
    if not pages:
        raise RuntimeError("pdftotext returned no pages")
    _PDF_TEXT_CACHE[cache_key] = pages
    return pages


_COMPATIBLE_FTA_SENTENCE_RE = re.compile(
    r"[^.]*\bcompatible\s+with\s+the\s+model\b[^.]*\.",
    re.IGNORECASE,
)
_FTA_MODEL_TOKEN_RE = re.compile(r"\b(?:MU|MC)-[A-Z]{2,8}\d{1,4}\b", re.IGNORECASE)


def _document_supports_mc_mu_pair(page_texts: list[str], part: object) -> bool:
    """True only when the bound document itself states the MC/MU relationship."""
    part_norm = str(part or "").strip().upper()
    counterpart = _conformal_coat_counterpart(part_norm)
    if not part_norm or not counterpart:
        return False
    blob = "\n".join(str(t or "") for t in page_texts)
    if not _text_mentions_part(blob, part_norm) or not _text_mentions_part(blob, counterpart):
        return False
    if re.search(
        r"conformally coated models of the FTAs and IOPs are identified\s+by the prefix [\"“]?MC",
        blob,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        rf"{re.escape(part_norm)}\s+DI IOP[^\n]{{0,40}}Conformally Coated",
        blob,
        re.IGNORECASE,
    ):
        return True
    return bool(re.search(rf"{re.escape(part_norm)}[^\n]{{0,80}}conformally coated", blob, re.I))


def _explicitly_compatible_fta_models(page_texts: list[str], part: object) -> list[str]:
    """FTA/module models the BOUND document's own text names as compatible
    with this exact part -- extracted from its compatibility sentence, never
    guessed or substituted from a family/near-model heuristic."""
    part_norm = str(part or "").strip()
    if not part_norm:
        return []
    needles = [part_norm]
    counterpart = _conformal_coat_counterpart(part_norm)
    if counterpart and _document_supports_mc_mu_pair(page_texts, part_norm):
        needles.append(counterpart)
    out: list[str] = []
    skip = {n.upper() for n in needles}
    for text in page_texts:
        for sent_m in _COMPATIBLE_FTA_SENTENCE_RE.finditer(str(text or "")):
            sentence = sent_m.group(0)
            if not any(_text_mentions_part(sentence, n) for n in needles):
                continue
            for tok in _FTA_MODEL_TOKEN_RE.findall(sentence):
                norm = tok.upper()
                if norm in out or any(_text_mentions_part(norm, n) for n in skip):
                    continue
                out.append(norm)
    return out


def collect_fta_connection_diagrams_from_source(
    source: object, part: object
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Scan one bound PDF for verified FTA connection diagrams.

    Returns (found_list, compatible_ftas, counterpart_verified).
    """
    src = str(source or "").replace("\\", "/").lstrip("/")
    root = library_root()
    if not src or not root:
        return [], [], False
    full = os.path.join(root, src)
    if not os.path.isfile(full):
        return [], [], False
    try:
        texts = _pdf_page_texts(full)
    except Exception:
        return [], [], False
    counterpart_ok = _document_supports_mc_mu_pair(texts, part)
    ftas = _explicitly_compatible_fta_models(texts, part)
    ident = {
        "source": src,
        "title": "",
        "doc_no": "",
        "filename": os.path.basename(src),
    }
    targets: list[str] = []
    part_s = str(part or "").strip()
    if part_s:
        targets.append(part_s)
    counterpart = _conformal_coat_counterpart(part_s) if counterpart_ok else ""
    if counterpart and counterpart.upper() not in {t.upper() for t in targets}:
        targets.append(counterpart)
    for fta in ftas:
        if fta and fta.upper() not in {t.upper() for t in targets}:
            targets.append(fta)
    found: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for target in targets:
        for idx, text in enumerate(texts):
            fig = _verified_figure_for_part(text, target)
            if not fig:
                continue
            excerpt = _part_centered_excerpt(text, target)
            if not _is_wiring_grade_figure_text(text, excerpt):
                continue
            key = (idx + 1, fig)
            if key in seen:
                continue
            seen.add(key)
            found.append(
                {
                    "source": src,
                    "title": "Process Manager I/O Installation" if "pm20520" in src.lower() else ident["filename"],
                    "doc_no": "PM20-520" if "pm20520" in src.lower() else "",
                    "filename": ident["filename"],
                    "pdf_page": idx + 1,
                    "printed_page": _printed_page_number(text),
                    "figure": fig,
                    "matched_model": _caption_model_label(text, fig, target),
                    "requested_part": part_s,
                    "excerpt": excerpt,
                }
            )
    return found, ftas, counterpart_ok


def _is_wiring_grade_figure_text(text: object, excerpt: object = "") -> bool:
    """True only for connection/field-wiring diagrams, never assembly layouts."""
    hay = f"{excerpt or ''}\n{text or ''}".lower()
    if "assembly layout" in hay and "connection diagram" not in hay:
        return False
    return any(
        token in hay
        for token in ("connection diagram", "fta connection", "field wiring", "customer wiring")
    )


def try_first_reply_fta_schematic(
    item: dict[str, Any], *, part: str, public_origin: object = ""
) -> str | None:
    """Operator first-reply packet for a verified FTA connection diagram, or None."""
    if not part:
        return None
    source = str(item.get("source") or "")
    found, ftas, counterpart_ok = collect_fta_connection_diagrams_from_source(source, part)
    if not found:
        return None
    ident = item.get("document_identity") if isinstance(item.get("document_identity"), dict) else {}
    active = {
        "source": source,
        "title": str((ident or {}).get("title") or item.get("title") or ""),
        "doc_no": str((ident or {}).get("doc_no") or item.get("revision") or ""),
        "part_number": part,
        "url": str(item.get("url") or ""),
        "counterpart_verified": counterpart_ok,
    }
    reply, _spoken, _receipt = build_authoritative_schematic_reply(
        active,
        found,
        [{"source": source, "filename": os.path.basename(source), "doc_no": active["doc_no"], "target": part}],
        ftas,
        public_origin=public_origin,
        counterpart_verified=counterpart_ok,
    )
    return reply


def authoritative_tdc3000_schematic_search(
    part: object, extra_models: object = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Search the TDC3000 authoritative custom index (all 4 formats: csv,
    json, xlsx, html) plus their index-linked PDFs for genuine wiring/FTA
    connection figures captioned for ``part`` or one of ``extra_models``
    (explicitly-verified compatible FTAs -- never a guessed family manual).

    Returns (found_list, checked_entries). ``found_list`` holds every
    distinct verified figure found for ``part`` or any of ``extra_models`` --
    a part can have several applicable FTA connection-diagram variants (e.g.
    one per terminal type), and the caller must let the operator pick the
    one matching their actual hardware rather than silently returning only
    the first hit. ``checked_entries`` lists every index-linked document
    actually inspected, for a disclosed "nothing found" outcome that never
    claims more than was really checked.
    """
    try:
        _bin_dir = "/Users/rick/bin"
        if _bin_dir not in sys.path:
            sys.path.insert(0, _bin_dir)
        import tdc3000_index_lookup as tdc  # noqa: WPS433 (deliberate lazy import)
    except Exception:
        return [], []
    try:
        by_filename = tdc.get_index_by_filename()
    except Exception:
        return [], []
    if not by_filename:
        return [], []

    targets: list[str] = []
    for candidate in [str(part or "").strip()] + [str(x).strip() for x in (extra_models or [])]:
        norm = candidate.upper()
        if norm and norm not in targets:
            targets.append(norm)

    root = library_root()
    checked: list[dict[str, Any]] = []
    found: list[dict[str, Any]] = []
    # Dedup keys are scoped per-target, not per-document: the same PDF (e.g.
    # the already-bound manual) can legitimately carry a genuine figure for
    # one target (an FTA model) while having none for another (the IOP part
    # itself) -- marking a document "seen" globally after its first target
    # pass would wrongly skip re-scanning its pages for a later target.
    seen_checked: set[tuple[str, str]] = set()
    seen_found: set[tuple[str, int, str]] = set()
    for target in targets:
        try:
            hits = tdc._scan_exact_identifier(target, by_filename)  # noqa: SLF001
        except Exception:
            continue
        for hit in hits:
            source = str(hit.get("library_source") or "")
            if not source:
                continue
            checked_key = (source, target)
            if checked_key not in seen_checked:
                seen_checked.add(checked_key)
                checked.append(
                    {
                        "target": target,
                        "filename": hit.get("filename"),
                        "title": hit.get("title"),
                        "doc_no": hit.get("doc_no"),
                        "source": source,
                        "index_formats": hit.get("index_formats"),
                    }
                )
            if not root:
                continue
            full = os.path.join(root, source)
            if not os.path.isfile(full):
                continue
            try:
                texts = _pdf_page_texts(full)
            except Exception:
                continue
            for idx, text in enumerate(texts):
                fig = _verified_figure_for_part(text, target)
                if not fig:
                    continue
                if not _is_wiring_grade_figure_text(text):
                    continue
                found_key = (source, idx + 1, fig)
                if found_key in seen_found:
                    continue
                seen_found.add(found_key)
                found.append(
                    {
                        "source": source,
                        "title": hit.get("title") or "",
                        "doc_no": hit.get("doc_no") or "",
                        "filename": hit.get("filename") or "",
                        "pdf_page": idx + 1,
                        "figure": fig,
                        # Display label from the figure's own caption verbatim
                        # (e.g. "MU-TDID52/72") when isolable, falling back to
                        # the matched search target -- presentation only, does
                        # not change which figure/page was actually verified.
                        "matched_model": _caption_model_label(text, fig, target),
                        "requested_part": str(part or "").strip(),
                        "index_href": hit.get("index_href"),
                        "index_formats": hit.get("index_formats"),
                    }
                )
    return found, checked


def extract_wiring_pages_from_pdf(
    pdf_path: object,
    *,
    part_number: object = "",
    max_pages: int = 3,
) -> list[dict[str, Any]]:
    """Locate verified wiring/schematic-relevant PDF pages for the active part."""
    path = str(pdf_path or "")
    if not path or not os.path.isfile(path):
        return []
    page_texts = _pdf_page_texts(path)
    part = str(part_number or "").strip()

    # A page may only be claimed as a verified wiring/schematic answer when it
    # carries its own figure/caption directly applicable to this part (or the
    # part's explicitly named model) -- not merely a page where the part is
    # mentioned in a compatibility table while an unrelated figure for a
    # different assembly happens to share the page.
    part_pages: list[tuple[int, int, list[str], str]] = []
    for index, text in enumerate(page_texts):
        if part and not _text_mentions_part(text, part):
            continue
        if part and not _verified_figure_for_part(text, part):
            continue
        score, reasons = _score_wiring_page(text, part=part)
        if score < 50:
            continue
        part_pages.append((score, index + 1, reasons, text))
    if not part_pages and part:
        for index, text in enumerate(page_texts):
            if _text_mentions_part(text, part) and _verified_figure_for_part(text, part):
                score, reasons = _score_wiring_page(text, part=part)
                part_pages.append((score, index + 1, reasons, text))
    if not part_pages:
        return []

    def _prefer_key(item: tuple[int, int, list[str], str]) -> tuple[int, int]:
        score, _page_no, reasons, _text = item
        rich = 1 if any(
            r in reasons for r in ("wiring", "schematic", "connection_diagram", "figure", "iop_compat")
        ) else 0
        return (rich, score)

    part_pages.sort(key=lambda item: (_prefer_key(item)[0], _prefer_key(item)[1], -item[1]), reverse=True)
    best_score, best_page, best_reasons, best_text = part_pages[0]
    selected: list[dict[str, Any]] = [
        {
            "pdf_page": best_page,
            "printed_page": _printed_page_number(best_text),
            "score": best_score,
            "reasons": best_reasons,
            "excerpt": _part_centered_excerpt(best_text, part),
        }
    ]
    seen = {best_page}

    for fig in _figure_refs(best_text):
        needle = re.compile(rf"\bFigure\s+{re.escape(fig)}\b", re.I)
        for index, text in enumerate(page_texts):
            page_no = index + 1
            if page_no in seen:
                continue
            if not needle.search(text):
                continue
            if "table of contents" in text.lower() or text.lower().count("figure ") > 8:
                continue
            score, reasons = _score_wiring_page(text, part=part)
            selected.append(
                {
                    "pdf_page": page_no,
                    "printed_page": _printed_page_number(text),
                    "score": score + 30,
                    "reasons": reasons + [f"figure_ref:{fig}"],
                    "excerpt": _part_centered_excerpt(text, part),
                }
            )
            seen.add(page_no)
            if len(selected) >= max_pages:
                return selected[:max_pages]

    for page_no in range(max(1, best_page - 2), min(len(page_texts), best_page + 12) + 1):
        if page_no in seen:
            continue
        text = page_texts[page_no - 1]
        score, reasons = _score_wiring_page(text, part=part)
        if "connection_diagram" not in reasons and "schematic" not in reasons:
            continue
        # Proximity to the verified page is not enough -- a nearby figure for a
        # DIFFERENT assembly (e.g. a shared power-distribution module) must not
        # be retained as if it were relevant to this part.
        if part and not _verified_figure_for_part(text, part):
            continue
        selected.append(
            {
                "pdf_page": page_no,
                "printed_page": _printed_page_number(text),
                "score": score,
                "reasons": reasons + ["near_part_context"],
                "excerpt": _part_centered_excerpt(text, part),
            }
        )
        seen.add(page_no)
        if len(selected) >= max_pages:
            break
    return selected[:max_pages]


def build_wiring_extract_reply(
    active_document: object,
    pages: list[dict[str, Any]],
    *,
    public_origin: object = "",
    error: object = "",
) -> tuple[str, str, dict[str, Any]]:
    """Operator-facing wiring extraction answer + compact spoken + receipt patch."""
    origin = normalize_public_origin(public_origin)
    source = _active_document_source(active_document)
    title = ""
    part = ""
    doc_no = ""
    url = ""
    if isinstance(active_document, dict):
        title = str(active_document.get("title") or "").strip()
        part = str(active_document.get("part_number") or "").strip()
        doc_no = str(active_document.get("doc_no") or active_document.get("revision") or "").strip()
        url = str(active_document.get("url") or "").strip()
    identity = title or (source.rsplit("/", 1)[-1] if source else "the active manual")
    if doc_no:
        identity = f"{identity} ({doc_no})"
    open_href = normalize_corpus_url(url, source=source, public_origin=origin) or absolutize_sidecar_href(
        sidecar_preview_path(source) if source else "", public_origin=origin
    )
    receipt = {
        "schema": "smedley.active_document_wiring_extract.v1",
        "source": source,
        "title": title or None,
        "doc_no": doc_no or None,
        "part_number": part or None,
        "url": open_href or url or None,
        "pages": pages,
        "error": str(error or "") or None,
    }
    if error and not pages:
        reply = (
            f"I still have **{identity}** bound for **{part or 'this part'}**, but wiring-diagram "
            f"extraction failed ({error}). The manual context is retained — try again, or open the manual."
        )
        if open_href:
            reply += f"\n\n[Open manual]({open_href})"
        spoken = (
            f"Wiring extraction failed for {title or 'the active manual'}"
            + (f", document {doc_no}" if doc_no else "")
            + ". The manual context is still bound."
        )
        return reply, spoken, receipt
    if not pages:
        reply = (
            f"I searched **{identity}** for a wiring/schematic figure captioned for "
            f"**{part or 'the requested part'}** itself. None is verified in this manual — "
            f"{part or 'the part'} appears only in compatibility/reference text here, not in a "
            "figure or caption of its own. I will not substitute a nearby module's diagram or "
            "claim a page as the strongest context without a verified figure. "
            "The document context stays bound."
        )
        if open_href:
            reply += f"\n\n[Open manual]({open_href})"
        spoken = (
            f"No verified wiring diagram for this part in {title or 'the active manual'}. "
            "I will not substitute a different module's figure. The manual is still bound."
        )
        return reply, spoken, receipt

    top = pages[0]
    page_no = top.get("pdf_page")
    printed_no = str(top.get("printed_page") or "").strip()
    page_href = ""
    has_printed_link = False
    if printed_no.isdigit():
        page_href = absolutize_sidecar_href(
            sidecar_printed_page_path(source, printed_no), public_origin=origin
        )
        has_printed_link = bool(page_href)
    page_stmt = f"printed manual page **{printed_no}**" if printed_no else "printed page not verified"
    if page_no:
        page_stmt += f" (PDF ordinal page {page_no}, audit only)"
    lines = [
        f"Using the bound manual **{identity}**"
        + (f" for **{part}**" if part else "")
        + ":",
        "",
        f"Verified figure found — {page_stmt} contains the strongest wiring/schematic context for this part.",
    ]
    if top.get("excerpt"):
        # Excerpt is already a bounded, part-centered window — do not re-slice
        # from the front, or the part-number confirmation can be cut again.
        lines.extend(["", str(top["excerpt"])])
    if len(pages) > 1:
        extras = ", ".join(
            f"printed p.{p.get('printed_page') or '?'}" for p in pages[1:]
        )
        lines.extend(["", f"Related pages also retained: {extras}."])
    if has_printed_link:
        fig = str(top.get("figure") or "").strip()
        link_label = (
            f"Open Figure {fig} — printed p.{printed_no}"
            if fig
            else f"Open wiring page — printed p.{printed_no}"
        )
        lines.extend(["", f"[{link_label}]({page_href})"])
    elif open_href:
        lines.extend(["", f"[Open manual]({open_href})"])
    lines.extend(["", "Want me to pull another figure or FTA connection diagram from this manual?"])
    reply = "\n".join(lines)
    doc_spoken = re.sub(r"([A-Z]+)(\d{2})-(\d{3})", r"\1 \2-\3", doc_no) if doc_no else ""
    printed_spoken = f", printed page {printed_no}" if printed_no else ""
    spoken = (
        f"I extracted wiring context from {title or 'the bound manual'}"
        + (f", document {doc_spoken}" if doc_spoken else "")
        + (f" for {part}" if part else "")
        + f"{printed_spoken}. The printed-page link is on screen."
    )
    return reply, spoken, receipt


def _conformal_coat_counterpart(part: object) -> str:
    """The other MC-/MU- coating variant of ``part``, or '' if not that style."""
    raw = str(part or "").strip().upper()
    m = re.match(r"^(MC|MU)-([A-Z0-9]+)$", raw)
    if not m:
        return ""
    prefix, body = m.group(1), m.group(2)
    return f"{'MU' if prefix == 'MC' else 'MC'}-{body}"


def build_authoritative_schematic_reply(
    active_document: object,
    found_list: list[dict[str, Any]],
    checked: list[dict[str, Any]],
    compatible_ftas: list[str],
    *,
    public_origin: object = "",
    counterpart_verified: bool = False,
) -> tuple[str, str, dict[str, Any]]:
    """Outcome A/B reply when the bound manual has no verified figure itself.

    Outcome A: one or more index-proven authoritative documents have a
    genuine wiring/FTA connection figure for the part or an explicitly
    compatible FTA model. A part can have several applicable FTA variants
    (e.g. one connection diagram per terminal type) -- every one actually
    verified is listed with its own page/link so the operator can pick the
    one matching their real hardware; none is ever presented as a direct
    diagram of the IOP/part itself when it is really an FTA diagram.
    Outcome B: a structured, disclosed "nothing found" result naming every
    authoritative index entry actually checked. The originally bound
    document's identity/compatibility text is never treated as a schematic.
    """
    origin = normalize_public_origin(public_origin)
    bound_source = _active_document_source(active_document)
    bound_title = ""
    part = ""
    bound_doc_no = ""
    bound_url = ""
    if isinstance(active_document, dict):
        bound_title = str(active_document.get("title") or "").strip()
        part = str(active_document.get("part_number") or "").strip()
        bound_doc_no = str(active_document.get("doc_no") or active_document.get("revision") or "").strip()
        bound_url = str(active_document.get("url") or "").strip()
    bound_identity = bound_title or (bound_source.rsplit("/", 1)[-1] if bound_source else "the active manual")
    if bound_doc_no:
        bound_identity = f"{bound_identity} ({bound_doc_no})"
    bound_open_href = normalize_corpus_url(
        bound_url, source=bound_source, public_origin=origin
    ) or absolutize_sidecar_href(
        sidecar_preview_path(bound_source) if bound_source else "", public_origin=origin
    )
    counterpart = _conformal_coat_counterpart(part)
    if counterpart and not counterpart_verified:
        counterpart = ""

    checked_receipt = [
        {"target": c.get("target"), "filename": c.get("filename"), "doc_no": c.get("doc_no"), "source": c.get("source")}
        for c in checked
    ]

    def _figure_is_requested_part(found: dict[str, Any]) -> bool:
        requested = str(part or "").strip().upper()
        matched = str(found.get("matched_model") or "").upper().replace(" ", "")
        return bool(requested) and requested in matched.replace("/", "")

    direct_fta = any(_figure_is_requested_part(f) for f in found_list)

    if found_list:
        entries: list[dict[str, Any]] = []
        if direct_fta:
            identity_line = (
                f"**{part}** is the requested FTA. **{bound_identity}** is the source document. "
                "The verified figure below is the field-wiring/connection diagram for this FTA, "
                "not a planning-manual mention and not an IOP-card diagram."
            )
            search_line = (
                f"Verified {len(found_list)} FTA connection diagram"
                f"{'s' if len(found_list) != 1 else ''} captioned for **{part}**:"
            )
        else:
            identity_line = (
                (
                    f"**{part}** is the conformally coated counterpart of **{counterpart}**; "
                    f"**{bound_identity}** documents both under the same IOP entry. "
                    if counterpart else f"**{bound_identity}** is the bound manual for **{part}**. "
                )
                + (
                    f"{part} has no wiring/schematic figure of its own — that lives on its FTA (field termination "
                    "assembly), not the IOP card. Its own compatibility text is supporting identity evidence only, "
                    "not a schematic."
                )
            )
            search_line = (
                f"Searching the authoritative TDC3000 index (all 4 formats) found "
                f"{len(found_list)} verified FTA connection diagram"
                f"{'s' if len(found_list) != 1 else ''} for {part}'s explicitly compatible FTA model"
                f"{'s' if len(found_list) != 1 else ''} — select the one matching the FTA actually wired to your "
                f"{part}:"
            )
        lines: list[str] = [
            identity_line,
            "",
            search_line,
            "",
        ]
        for found in found_list:
            page_no = found.get("pdf_page")
            printed_no = str(found.get("printed_page") or "").strip()
            if not printed_no and page_no:
                found_root = library_root()
                found_full = os.path.join(found_root, found.get("source") or "") if found_root else ""
                if found_full and os.path.isfile(found_full):
                    try:
                        found_texts = _pdf_page_texts(found_full)
                        if 0 < int(page_no) <= len(found_texts):
                            printed_no = _printed_page_number(found_texts[int(page_no) - 1])
                    except Exception:
                        printed_no = ""
            found_href = ""
            if printed_no.isdigit():
                found_href = absolutize_sidecar_href(
                    sidecar_printed_page_path(found.get("source") or "", printed_no),
                    public_origin=origin,
                )
            found_identity = str(found.get("title") or found.get("filename") or "the indexed manual")
            if found.get("doc_no"):
                found_identity = f"{found_identity} ({found['doc_no']})"
            matched_model = str(found.get("matched_model") or part).strip()
            page_stmt = (
                f"printed manual page **{printed_no}**"
                if printed_no
                else "printed page not verified"
            )
            if page_no:
                page_stmt += f" (PDF ordinal page {page_no}, audit only)"
            link_label = (
                f"Open Figure {found['figure']} — printed p.{printed_no}"
                if printed_no
                else f"Open Figure {found['figure']} ({matched_model} FTA diagram)"
            )
            if found_href:
                lines.append(
                    f"- Figure **{found['figure']}** — **{matched_model}** FTA connection diagram, in "
                    f"**{found_identity}**, {page_stmt}. [{link_label}]({found_href})"
                )
            else:
                lines.append(
                    f"- Figure **{found['figure']}** — **{matched_model}** FTA connection diagram, in "
                    f"**{found_identity}**, {page_stmt}."
                )
            entries.append({
                **found,
                "printed_page": printed_no or None,
                "pdf_page": page_no,
                "printed_page_href": found_href or None,
            })
        if not direct_fta:
            lines.extend([
                "",
                f"None of these is a direct {part} diagram — each is the connection diagram for the named FTA "
                f"terminal assembly that {part} plugs into.",
            ])
        else:
            lines.extend([
                "",
                f"Requested part: **{part}**. Actual diagram target: the named FTA on each figure. "
                "Do not treat a compatibility table or planning manual as this packet.",
            ])
        reply = "\n".join(lines)
        receipt = {
            "schema": "smedley.authoritative_tdc3000_schematic.v1",
            "outcome": "found",
            "requested_part": part,
            "conformal_coat_counterpart": counterpart or None,
            "matched_models": [str(f.get("matched_model") or "") for f in found_list],
            "bound_document": {"source": bound_source, "title": bound_title, "doc_no": bound_doc_no},
            "found_documents": entries,
            "checked": checked_receipt,
        }
        spoken = (
            compact_fta_connection_spoken(
                part,
                found_list[0].get("figure"),
                found_list[0].get("printed_page"),
            )
            if direct_fta
            else (
                f"{bound_title or 'The bound manual'} has no schematic of its own for {part}. "
                f"The TDC3000 index found {len(found_list)} FTA connection diagram"
                f"{'s' if len(found_list) != 1 else ''} for its compatible FTA models — pick the one matching your "
                "hardware. Links are on screen."
            )
        )
        if direct_fta and not spoken:
            spoken = (
                f"Verified FTA connection diagram for {part} is on screen, "
                f"Figure {found_list[0].get('figure')}."
            )
        return reply, spoken, receipt

    checked_lines = "; ".join(
        f"{c.get('filename')} ({c.get('doc_no') or c.get('title') or 'untitled'})" for c in checked
    ) or "no index-linked documents matched this part or its compatible FTA models"
    fta_note = (
        f" or its explicitly compatible FTA models ({', '.join(compatible_ftas)})"
        if compatible_ftas
        else ""
    )
    reply = (
        f"No authoritative schematic found in the indexed TDC3000 library for **{part}**{fta_note}. "
        f"**{bound_identity}** contains only supporting identity/compatibility text for {part} — never treated "
        f"as a schematic. Authoritative index entries checked (all 4 formats: csv/json/xlsx/html): {checked_lines}. "
        "I will not invent a substitute manual."
    )
    if bound_open_href:
        reply += f"\n\n[Open manual]({bound_open_href})"
    spoken = (
        f"No authoritative wiring schematic was found in the TDC3000 index for {part}"
        + (f" or its compatible FTAs" if compatible_ftas else "")
        + f". {len(checked)} indexed documents were checked. The bound manual is still {bound_title or 'retained'}."
    )
    receipt = {
        "schema": "smedley.authoritative_tdc3000_schematic.v1",
        "outcome": "not_found",
        "requested_part": part,
        "compatible_ftas": compatible_ftas,
        "bound_document": {"source": bound_source, "title": bound_title, "doc_no": bound_doc_no},
        "found_document": None,
        "checked": checked_receipt,
    }
    return reply, spoken, receipt


def try_active_document_review(
    query: object, active_document: object, *, public_origin: object = ""
) -> Optional[dict[str, Any]]:
    """Resolve a paragraph/section/wiring ask against the session's selected document."""
    if not is_active_document_review_request(query, active_document):
        return None
    source = _active_document_source(active_document)
    origin = normalize_public_origin(public_origin)

    # Explicit decline of a pending extract offer: clear the pending action
    # without executing it or dropping the bound document/active identity.
    if is_negative_followup(query) and _pending_extract_bound(active_document):
        active_out = dict(active_document) if isinstance(active_document, dict) else {}
        active_out.pop("pending_action", None)
        title = str(active_out.get("title") or "").strip() or "the active manual"
        part = str(active_out.get("part_number") or "").strip()
        reply = (
            f"Understood — skipping the wiring-schematic extraction. "
            f"**{title}**" + (f" for **{part}**" if part else "") + " stays bound if you need it later."
        )
        return {
            "handled": True,
            "reply": reply,
            "spoken_reply": f"Skipping the wiring extraction. {title} is still bound.",
            "source": source,
            "active_document": active_out,
            "error": None,
        }

    # Governing-source guidance binds the already-active document to a stated
    # engineering topic. It must never be treated as a new document lookup --
    # keep the current binding, do not re-search, do not clear it.
    governing_topic = governing_source_guidance_topic(query)
    if governing_topic:
        active_out = dict(active_document) if isinstance(active_document, dict) else {}
        topic_key = _governing_topic_key(governing_topic)
        active_out["governing_topic"] = governing_topic
        active_out["governing_topic_key"] = topic_key
        title = str(active_out.get("title") or active_out.get("doc_no") or "").strip() or "this document"
        reply = (
            f"Understood — **{title}** stays bound as the governing reference "
            f"for {governing_topic}. I'll use it first for that topic going forward."
        )
        return {
            "handled": True,
            "reply": reply,
            "spoken_reply": sanitize_for_spoken_output(reply),
            "source": source,
            "active_document": active_out,
            "error": None,
        }

    # Offered follow-up: explicit extract phrasing OR affirmative on pending extract.
    wants_extract = is_wiring_extract_followup(query) or (
        is_affirmative_followup(query) and _pending_extract_bound(active_document)
    )
    if wants_extract:
        pdf_path = resolve_active_document_filesystem_path(active_document)
        part = ""
        if isinstance(active_document, dict):
            part = str(active_document.get("part_number") or "").strip()
        pages: list[dict[str, Any]] = []
        err = ""
        if not pdf_path:
            err = "bound PDF path unavailable"
        elif os.path.splitext(pdf_path)[1].lower() != ".pdf":
            err = "bound document is not a PDF"
        else:
            source = _active_document_source(active_document)
            found_list, compatible_ftas, counterpart_ok = collect_fta_connection_diagrams_from_source(
                source, part
            )
            if found_list:
                reply, spoken, receipt = build_authoritative_schematic_reply(
                    active_document,
                    found_list,
                    [
                        {
                            "source": source,
                            "filename": os.path.basename(str(source or "")),
                            "doc_no": str(
                                (active_document or {}).get("doc_no")
                                or (active_document or {}).get("revision")
                                or ""
                            )
                            if isinstance(active_document, dict)
                            else "",
                            "target": part,
                        }
                    ],
                    compatible_ftas,
                    public_origin=origin,
                    counterpart_verified=counterpart_ok,
                )
                active_out = dict(active_document) if isinstance(active_document, dict) else {}
                active_out.pop("pending_action", None)
                active_out["verified_schematics"] = [
                    {
                        "source": f.get("source"),
                        "pdf_page": f.get("pdf_page"),
                        "printed_page": f.get("printed_page"),
                        "matched_model": f.get("matched_model"),
                        "figure": f.get("figure"),
                    }
                    for f in found_list
                ]
                return {
                    "handled": True,
                    "reply": reply,
                    "spoken_reply": spoken,
                    "source": source,
                    "active_document": active_out,
                    "extraction": receipt,
                    "error": None,
                }
            try:
                pages = extract_wiring_pages_from_pdf(pdf_path, part_number=part)
            except Exception as exc:  # noqa: BLE001
                err = type(exc).__name__
                logger.warning("wiring extract failed: %s", err)

        # The bound manual itself has no verified figure: never fall back to
        # merely re-showing the generic manual. Search the authoritative
        # TDC3000 index (all 4 formats, plus the part's own explicitly
        # compatible FTA models) and return outcome A (found, cited) or
        # outcome B (disclosed, naming what was checked) -- never both silent
        # and never a guessed substitute.
        if not err and not pages and part and pdf_path.lower().endswith(".pdf"):
            compatible_ftas: list[str] = []
            try:
                bound_texts = _pdf_page_texts(pdf_path)
                compatible_ftas = _explicitly_compatible_fta_models(bound_texts, part)
            except Exception:
                compatible_ftas = []
            found_list, checked = authoritative_tdc3000_schematic_search(part, compatible_ftas)
            counterpart_ok = False
            try:
                counterpart_ok = _document_supports_mc_mu_pair(bound_texts, part)
            except Exception:
                counterpart_ok = False
            reply, spoken, receipt = build_authoritative_schematic_reply(
                active_document,
                found_list,
                checked,
                compatible_ftas,
                public_origin=origin,
                counterpart_verified=counterpart_ok,
            )
            active_out = dict(active_document) if isinstance(active_document, dict) else {}
            active_out.pop("pending_action", None)
            if found_list:
                active_out["verified_schematics"] = [
                    {
                        "source": f.get("source"),
                        "pdf_page": f.get("pdf_page"),
                        "matched_model": f.get("matched_model"),
                        "figure": f.get("figure"),
                    }
                    for f in found_list
                ]
            return {
                "handled": True,
                "reply": reply,
                "spoken_reply": spoken,
                "source": source,
                "active_document": active_out,
                "extraction": receipt,
                "error": None,
            }

        reply, spoken, receipt = build_wiring_extract_reply(
            active_document, pages, public_origin=origin, error=err
        )
        # Keep page_hint on active document when verified; clear spent pending action.
        active_out = dict(active_document) if isinstance(active_document, dict) else {}
        active_out.pop("pending_action", None)
        if pages:
            active_out["page_hint"] = pages[0].get("pdf_page")
            active_out["wiring_pages"] = [p.get("pdf_page") for p in pages]
        return {
            "handled": True,
            "reply": reply,
            "spoken_reply": spoken,
            "source": source,
            "active_document": active_out,
            "extraction": receipt,
            "error": err or None,
        }

    try:
        text = fetch_active_document_text(source)
        passage = extract_active_document_passage(text, str(query or ""))
        if not passage and _ACTIVE_DOCUMENT_RECOMMENDATION_RE.search(str(query or "")):
            passage = _best_engineering_excerpt(text, str(query or ""))
    except Exception as exc:  # noqa: BLE001
        logger.warning("active document review failed: %s", type(exc).__name__)
        return {
            "handled": True,
            "reply": "I could not extract that selected document for review. The document context is still bound.",
            "spoken_reply": "I could not extract that selected document for review. The document context is still bound.",
            "active_document": active_document if isinstance(active_document, dict) else None,
            "error": type(exc).__name__,
        }
    link = markdown_link_for_source(source, public_origin=public_origin)
    if not passage:
        reply = f"I reviewed {link}, but could not find the requested section. Try the exact section number or a distinctive phrase."
    else:
        reply = f"From {link}:\n\n{passage}"
    return {
        "handled": True,
        "reply": reply,
        "spoken_reply": sanitize_for_spoken_output(reply),
        "source": source,
        "active_document": active_document if isinstance(active_document, dict) else None,
        "error": None,
    }


def try_grounded_document_excerpt(message: object, *, public_origin: object = "") -> Optional[dict[str, Any]]:
    """Answer a RAG-grounded engineering ask from its first cited source, not an LLM guess."""
    raw = str(message or "")
    block = _GROUNDED_CONTEXT_RE.search(raw)
    if not block:
        return None
    source_match = _GROUNDED_SIDECAR_RE.search(block.group(1))
    if not source_match:
        return None
    source = urllib.parse.unquote(source_match.group(1)).replace("\\", "/")
    source = _active_document_source({"source": source})
    if not source:
        return None
    question = raw[:block.start()].strip()
    tokens = [t for t in re.findall(r"[a-z]{4,}", question.lower()) if t not in {"what", "with", "from", "that", "this", "according", "foundation", "foundations"}]
    try:
        lines = [re.sub(r"\s+", " ", line).strip() for line in fetch_active_document_text(source).splitlines()]
    except Exception as exc:  # noqa: BLE001
        logger.warning("grounded document excerpt failed: %s", type(exc).__name__)
        return None
    best_index, best_score = -1, 0
    for index, line in enumerate(lines):
        folded = line.lower()
        hits = {token for token in tokens if token in folded}
        score = len(hits) + 3 * len(hits & _ENGINEERING_PRIORITY_TERMS)
        if score > best_score:
            best_index, best_score = index, score
    if best_index < 0 or best_score <= 0:
        return None
    passage = " ".join(line for line in lines[best_index:best_index + 3] if line)[:1800]
    reply = f"{passage}\n\nSource: {markdown_link_for_source(source, public_origin=public_origin)}"
    return {"handled": True, "reply": reply, "spoken_reply": sanitize_for_spoken_output(reply), "source": source, "error": None}


def is_electrical_equipment_fact_question(query: object) -> bool:
    """True for fuse/rating/IFM/chassis-power asks that must be source-gated."""
    msg = str(query or "").strip()
    if not msg or len(msg) > 1200 or msg.startswith("/"):
        return False
    if _is_ask_jarvis_traffic(msg) or "<retrieved_library_context>" in msg:
        return False
    if _CHASSIS_POWER_TOPIC_RE.search(msg):
        return True
    has_part = bool(_HW_PART.search(msg) or _AB_PART.search(msg))
    return bool(has_part and _ELECTRICAL_FACT_RE.search(msg))


def is_active_chassis_power_followup(query: object, active_document: object) -> bool:
    """True for short slot/redundancy follow-ups that reuse chassis-power context."""
    if not isinstance(active_document, dict):
        return False
    topic = str(active_document.get("topic") or "").strip()
    if topic != "controllogix_chassis_power" and not active_document.get("chassis_power"):
        return False
    msg = str(query or "").strip()
    if not msg or is_document_request(msg):
        return False
    if _HW_PART.search(msg) or _AB_PART.search(msg):
        return False
    if _SLOT_FOLLOWUP_RE.match(msg):
        return True
    return bool(
        re.search(r"\b(?:redundan(?:t|cy)|dual\s+supply|single\s+supply|watt(?:age)?s?)\b", msg, re.I)
        and len(msg) < 80
    )


def is_active_part_compatibility_followup(query: object, active_document: object) -> bool:
    """True for IFM/cable/match follow-ups that should reuse the bound part."""
    if not isinstance(active_document, dict):
        return False
    if is_active_chassis_power_followup(query, active_document):
        return True
    part = str(active_document.get("part_number") or "").strip()
    if not part:
        return False
    msg = str(query or "").strip()
    if not msg or is_document_request(msg):
        return False
    if _HW_PART.search(msg) or _AB_PART.search(msg):
        # Explicit new part — treat as a fresh engineering ask, not follow-up reuse.
        return False
    return bool(_COMPATIBILITY_FOLLOWUP_RE.search(msg) and _ENGINEERING_QUESTION_RE.search(msg))


def is_engineering_rag_question(query: object) -> bool:
    """Gate automatic RAG to substantive engineering questions, not ordinary chat."""
    msg = str(query or "").strip()
    if not msg or len(msg) > 1200 or msg.startswith("/") or is_document_request(msg):
        return False
    if _is_ask_jarvis_traffic(msg):
        return False
    if "<retrieved_library_context>" in msg:
        return False
    if is_electrical_equipment_fact_question(msg):
        return True
    if not _ENGINEERING_QUESTION_RE.search(msg):
        return False
    # Catalog/part asks are first-class engineering lookups even without a
    # generic civil/mech keyword (e.g. fuse/IFM questions).
    if extract_query_part_numbers(msg) and _ELECTRICAL_FACT_RE.search(msg):
        return True
    tokens = set(re.findall(r"[a-z]{3,}", msg.lower()))
    return bool(tokens & _ENGINEERING_TERMS)


def select_engineering_evidence_match(
    matches: object, *, query: object = ""
) -> dict[str, Any] | None:
    """Pick a manual for engineering-fact answers.

    Series-folder proximity alone is not enough: analog manuals are rejected for
    digital catalog numbers, and part-mention in snippet/title ranks above bare
    1756/ path coincidence.
    """
    items = [m for m in (matches if isinstance(matches, list) else []) if isinstance(m, dict)]
    q_vendor = infer_query_vendor(query)
    query_parts = extract_query_part_numbers(query)
    ranked: list[tuple[int, dict[str, Any]]] = []
    for match in items:
        source = str(match.get("source") or "").replace("\\", "/")
        title = _match_title(match)
        if classify_document_kind(source, title) != "manual":
            continue
        src_vendor = infer_source_vendor(source, title)
        if not vendor_compatible(q_vendor, src_vendor):
            continue
        if query_parts and any(
            not source_family_compatible_with_part(source, title, p) for p in query_parts
        ):
            continue
        blob = f"{source} {title} {match.get('snippet') or ''} {match.get('part_number') or ''}"
        score = 0
        if query_parts and any(_text_mentions_part(blob, p) for p in query_parts):
            score += 100
        elif query_parts:
            series_ok = False
            for p in query_parts:
                series = re.match(r"^(\d{4})", p)
                if series and f"/{series.group(1).lower()}/" in source.lower():
                    series_ok = True
                    break
            if not series_ok and not manual_relevant_to_query_parts(match, query_parts):
                continue
            # Bare series folder is weak — digital I/O pubs get a boost for digital parts.
            score += 25 if series_ok else 10
            if any(_AB_DIGITAL_BODY_RE.match(p) for p in query_parts) and re.search(
                r"um058|digital\s+i/?o", f"{source} {title}", re.I
            ):
                score += 50
            if any(_AB_ANALOG_BODY_RE.match(p) for p in query_parts) and re.search(
                r"um009|analog", f"{source} {title}", re.I
            ):
                score += 50
        if str(match.get("match_kind") or "") == "exact":
            score += 20
        try:
            score += min(int(float(match.get("score") or 0) * 10), 15)
        except Exception:
            pass
        ranked.append((score, match))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def source_family_compatible_with_part(
    source: object = "", title: object = "", part: object = ""
) -> bool:
    """Reject cross-function manuals (e.g. analog UM009 for digital 1756-IA16)."""
    part_s = str(part or "").strip().upper().replace(" ", "-")
    blob = f"{source or ''} {title or ''}"
    if not part_s:
        return True
    if _AB_DIGITAL_BODY_RE.match(part_s) and _AB_ANALOG_IO_MANUAL_RE.search(blob):
        return False
    if _AB_ANALOG_BODY_RE.match(part_s) and re.search(r"um058|digital\s+i/?o", blob, re.I):
        # Digital I/O manual may still mention analog sparsely; allow but do not prefer.
        return True
    return True


def _seed_authoritative_manuals_for_part(part: object, *, query: object = "") -> list[dict[str, Any]]:
    """Inject on-disk authoritative pubs the vector ranker often misses.

    The filesystem-only 1756-UM001 chassis-power seed was removed: it cited
    an on-disk file as answer evidence without any actual retrieval hit,
    which could stand in for (or crowd out) a genuine retrieved source. Now
    that publication-alias pre-validation falls through to real semantic
    retrieval instead of forbidding it (see rag_retrieval._exact_publication_matches),
    UM001/IN619 evidence must come from an actual retrieve() match or not be
    cited at all.
    """
    part_s = str(part or "").strip().upper().replace(" ", "-")
    q = str(query or "")
    q_low = q.lower()
    seeds: list[dict[str, Any]] = []
    root = library_root()
    if not part_s.startswith("1756-"):
        return seeds
    wants_io_table = bool(
        re.search(r"\b(?:ifm|cable|1492|fuse|fusing|compatible|match)\b", q_low)
        or _AB_DIGITAL_BODY_RE.match(part_s)
    )
    if wants_io_table and _AB_DIGITAL_BODY_RE.match(part_s):
        for rel in _AB_DIGITAL_IO_MANUAL_SOURCES:
            abs_path = os.path.join(root, rel) if root else ""
            if abs_path and os.path.isfile(abs_path):
                seeds.append(
                    {
                        "source": rel.replace("\\", "/"),
                        "score": 0.99,
                        "match_kind": "authoritative_seed",
                        "retrieval": "smedley_authoritative_seed",
                        "part_number": part_s,
                        "document_identity": {
                            "title": "ControlLogix Digital I/O Modules User Manual",
                            "doc_no": "1756-UM058",
                        },
                    }
                )
    return seeds


def _is_chassis_power_manual(source: object = "", title: object = "") -> bool:
    """True for ControlLogix system/power pubs; false for I/O-module manuals."""
    blob = f"{source or ''} {title or ''}".lower().replace("\\", "/")
    if re.search(r"um009|analog\s+i/?o|digital\s+i/?o|um058", blob):
        return False
    return bool(
        re.search(
            # 1756-td005 is the "ControlLogix Power Supplies Specifications
            # Technical Data" publication -- confirmed by rendered PDF title
            # and its "Power Load and Transformer Sizing" section -- and is
            # therefore chassis-power evidence even though its filename alone
            # carries no "power supply" wording.
            r"um001|in619|in620|\btd0*05(?:[_\-]|\b)|power\s+suppl|redundant\s+power|system\s+user\s+manual",
            blob,
        )
    )


def _extract_chassis_power_facts(text: object, query: object = "") -> str:
    """Pull ControlLogix chassis/power-supply sizing lines from an authoritative manual.

    TOC / 'see installation instructions' pointers alone are not sizing evidence.
    Analog-module 'current wiring' examples are not chassis power-supply sizing.
    """
    raw = str(text or "")
    if not raw:
        return ""
    q = str(query or "").lower()
    slot_m = _SLOT_FOLLOWUP_RE.match(str(query or "").strip()) or re.search(
        r"\b(\d{1,2})\s*-?\s*slot", q
    )
    slot_n = slot_m.group(1) if slot_m else ""
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in raw.splitlines()]
    lines = [ln for ln in lines if ln]
    scored: list[tuple[int, str]] = []
    for line in lines:
        low = line.lower()
        if re.search(r"\bbefore you begin\b|\bsee the following publications\b", low):
            continue
        if re.search(r"\binstallation instructions\b", low) and not re.search(
            r"1756-p[ab]\w*|\bwatt|\bsizing\b|\bcurrent\b", low
        ):
            continue
        # Reject I/O module wiring examples that mention "module current".
        if re.search(r"\b(?:wiring example|input circuit|transmitter|if\d|of\d)\b", low):
            continue
        if not re.search(
            r"\b(?:1756-p[ab]\w*|power\s+suppl|watt|redundan|"
            r"backplane\s+current|sizing\s+worksheet|chassis\s+load)\b",
            low,
        ):
            continue
        score = 0
        if re.search(r"1756-p[ab]\w*", low):
            score += 6
        if "power supply" in low or "power-supply" in low:
            score += 2
        if "watt" in low:
            score += 3
        if "redundan" in low:
            score += 2
        if "sizing" in low or "worksheet" in low:
            score += 4
        if "backplane current" in low:
            score += 4
        if "chassis load" in low:
            score += 3
        if slot_n and re.search(rf"\b{re.escape(slot_n)}\s*-?\s*slot", low):
            score += 5
        if score < 4:
            continue
        scored.append((score, line[:320]))
    if not scored:
        return ""
    scored.sort(key=lambda item: (-item[0], len(item[1])))
    out: list[str] = []
    seen: set[str] = set()
    for _score, line in scored:
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
        if len(out) >= 5:
            break
    return "\n".join(out)[:1600].strip()


def _opinionated_electrical_leak(text: object) -> bool:
    """Detect free-agent opinion / slang that must never ship as electrical guidance."""
    return bool(
        re.search(
            r"(?i)\b(?:serious juice|bite the bullet|handles thermal load better|"
            r"based on my experience|in my experience|i(?:'| a)d recommend|"
            r"let me search|thinking out loud|as an ai)\b",
            str(text or ""),
        )
    )

def _load_manual_text_for_evidence(selected: dict[str, Any]) -> str:
    source = _active_document_source(selected)
    if not source:
        return ""
    if os.path.splitext(source)[1].lower() == ".pdf":
        pdf_path = resolve_active_document_filesystem_path(selected)
        if pdf_path:
            try:
                return "\n".join(_pdf_page_texts(pdf_path))
            except Exception as exc:  # noqa: BLE001
                logger.warning("engineering PDF extract failed: %s", type(exc).__name__)
    try:
        return fetch_active_document_text(source)
    except Exception as exc:  # noqa: BLE001
        logger.warning("engineering RAG preview failed: %s", type(exc).__name__)
        return ""


def _evidence_record_from_match(
    match: dict[str, Any], *, public_origin: object = "", part: str = ""
) -> dict[str, Any]:
    origin = normalize_public_origin(public_origin)
    item = neutralize_match(match, public_origin=origin)
    source0 = library_relpath_from_source(item.get("source") or "") or str(
        item.get("source") or ""
    ).replace("\\", "/")
    ident = item.get("document_identity") if isinstance(item.get("document_identity"), dict) else {}
    selected = {
        "source": source0,
        "url": str(item.get("url") or ""),
        "title": str((ident or {}).get("title") or source0.rsplit("/", 1)[-1]),
        "document_kind": "manual",
    }
    if ident:
        for key in ("doc_no", "filename", "category", "pages", "status"):
            if ident.get(key) is not None:
                selected[key] = ident.get(key)
    if match.get("part_number"):
        selected["part_number"] = str(match.get("part_number"))
    if part:
        selected["part_number"] = part
    if match.get("revision"):
        selected["revision"] = str(match.get("revision"))
    # Ensure URL is a single canonical sidecar path.
    selected["url"] = normalize_corpus_url(
        selected.get("url"), source=source0, public_origin=origin
    ) or selected.get("url")
    return selected


def _resolve_query_part(query: object, active_document: object = None) -> str:
    parts = extract_query_part_numbers(query)
    if parts:
        return parts[0]
    if isinstance(active_document, dict):
        return str(active_document.get("part_number") or "").strip()
    return ""


def _strip_chain_of_thought(text: object) -> str:
    """Remove self-dialogue / hidden-search narration if any model path leaks it."""
    out = str(text or "")
    if not out:
        return ""
    lines = []
    for line in out.splitlines():
        if _CHAIN_OF_THOUGHT_RE.search(line):
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    cleaned = _CHAIN_OF_THOUGHT_RE.sub("", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _extract_part_scoped_facts(text: object, part: object, *, query: object = "") -> str:
    """Pull fuse/IFM/voltage lines that explicitly mention the exact part."""
    raw = str(text or "")
    part_s = str(part or "").strip()
    if not raw or not part_s:
        return ""
    q = str(query or "").lower()
    wants_ifm = bool(re.search(r"\b(?:ifm|cable|1492|compatible|match|fusible)\b", q))
    wants_fuse = bool(re.search(r"\b(?:fuse|fusing|internal\s+fus)\w*\b", q)) and not wants_ifm
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in raw.splitlines()]
    lines = [ln for ln in lines if ln]
    voltage_hits: list[str] = []
    fuse_hits: list[str] = []
    ifm_hits: list[str] = []
    for index, line in enumerate(lines):
        if not _text_mentions_part(line, part_s):
            continue
        low = line.lower()
        # Prefer compact single-line facts that name this exact catalog number.
        if re.search(
            r"\b(?:10\s*…\s*30|10\s*\.\.\.\s*30|10-30).{0,12}v\s*dc\b|"
            r"\b(?:74\s*…\s*132|74\s*\.\.\.\s*132|79\s*…\s*132).{0,12}v\s*ac\b|"
            r"\bv\s*dc\b.{0,40}isolated|\bv\s*ac\b.{0,40}(?:input|output|isolated)",
            low,
        ):
            voltage_hits.append(line)
        elif re.search(r"\b(?:v\s*dc|vdc|v\s*ac|vac|10…30|74…132|79…132)\b", low):
            voltage_hits.append(line)
        if wants_fuse and re.search(
            r"\b(?:none\s*[—\-–]\s*fused ifm|fused ifm can be used|recommended fuse|"
            r"fusing on the module|electronically fused|not protected)\b",
            low,
        ):
            fuse_hits.append(line)
        if wants_ifm and (
            re.search(r"\b(?:1492-[\w-]+|ifm|fusible|cable|cabl)\b", low)
            or _text_mentions_part(line, part_s)
        ):
            # Keep nearby IFM/cable catalog lines from the same wiring-system table block.
            block = []
            for j in range(index, min(len(lines), index + 14)):
                nxt = lines[j]
                if re.search(r"\b1492-[\w-]+\b", nxt) or re.search(
                    r"\b(?:fusible|feed-through|status-indicating|cable|cabl)\b", nxt, re.I
                ):
                    block.append(nxt)
                    continue
                # Sibling catalog aliases in the same cell (IA16K / OB16IEF…) — skip, don't break.
                if re.match(r"^1756-[A-Z0-9]+K?,?\s*$", nxt, re.I):
                    continue
                if j > index and re.match(r"^1756-", nxt) and not _text_mentions_part(nxt, part_s):
                    # New primary module row.
                    break
            if block:
                ifm_hits.append(" | ".join(block)[:900])
    ordered: list[str] = []
    for item in voltage_hits[:1] + fuse_hits[:2] + ifm_hits[:3]:
        if item and item not in ordered:
            ordered.append(item)
    if not ordered and (wants_fuse or wants_ifm):
        # Last resort: any part-tagged fuse/IFM line.
        for line in lines:
            if not _text_mentions_part(line, part_s):
                continue
            low = line.lower()
            if "fuse" in low or "1492-" in low or "ifm" in low:
                ordered.append(line)
            if len(ordered) >= 3:
                break
    if not ordered:
        return ""
    # Hard gate: every retained line must still mention the exact part OR be a
    # 1492 continuation line attached to a part-tagged block already accepted.
    return "\n".join(ordered[:5])[:1600].strip()


def _compact_electrical_spoken(part: str, passage: str) -> str:
    """Build a short, non-truncated spoken summary from extracted evidence."""
    low = passage.lower()
    bits = [f"For {part},"] if part else []
    if re.search(r"10\s*[…\.]{1,3}\s*30\s*v\s*dc|10-30\s*v\s*dc", low):
        bits.append("the manual lists it as a 10 to 30 volt DC module.")
    if re.search(r"74\s*[…\.]{1,3}\s*132\s*v\s*ac|79\s*[…\.]{1,3}\s*132\s*v\s*ac", low):
        bits.append("the manual lists it as a 74 to 132 volt AC input module.")
    if "none" in low and "fused ifm" in low:
        bits.append("On-module fusing is none; a fused IFM can be used to protect outputs.")
    m = re.search(r"(\d+(?:\.\d+)?\s*a\s+(?:quick acting|slo-?blow|medium lag)[^\n|]{0,40})", passage, re.I)
    if m:
        bits.append(f"Recommended external fuse: {m.group(1).strip()}.")
    cats = re.findall(r"1492-[A-Z0-9-]+", passage, flags=re.I)
    if cats:
        uniq = list(dict.fromkeys(cats))[:4]
        bits.append("Matching 1492 IFM or cable catalog numbers include " + ", ".join(uniq) + ".")
    if len(bits) <= 1:
        compact = re.sub(r"\s+", " ", passage)
        bits.append(compact[:180].rsplit(" ", 1)[0] + ".")
    bits.append("Source link is on screen.")
    spoken = " ".join(bits)
    if len(spoken) > 380:
        spoken = spoken[:377].rsplit(" ", 1)[0] + "."
    return spoken


def _query_wants_ifm_pairing(query: object) -> bool:
    return bool(
        re.search(
            r"\b(?:ifm|interface\s+modules?|pre-?wired|cable|1492|compatible|compatibility|match)\b",
            str(query or ""),
            re.I,
        )
    )


def _ab_wiring_index_link(*, public_origin: object = "") -> str:
    """One openable Smedley-served sidecar link for the AB wiring lookup index."""
    href = normalize_corpus_url(
        "", source=_AB_WIRING_INDEX_SOURCE, public_origin=public_origin
    ) or absolutize_sidecar_href(
        sidecar_preview_path(_AB_WIRING_INDEX_SOURCE), public_origin=public_origin
    )
    if not href:
        return f"📄 {_AB_WIRING_INDEX_TITLE}"
    return f"📄 [{_AB_WIRING_INDEX_TITLE}]({href})"


def _electrical_ifm_index_fallback_reply(
    part: str,
    *,
    public_origin: object = "",
) -> tuple[str, str, dict[str, Any]]:
    """Unresolved IFM/cable pairing → prescribed AB lookup index (never a guessed pairing)."""
    who = f" for **{part}**" if part else ""
    link = _ab_wiring_index_link(public_origin=public_origin)
    reply = (
        f"I cannot authoritatively verify an IFM/cable pairing{who} from a part-validated "
        "module publication, so I will not guess a pairing or substitute an unrelated manual.\n\n"
        "Prescribed next lookup resource "
        "(**lookup index**, not an I/O module manual; does **not** prove compatibility):\n\n"
        f"**{_AB_WIRING_INDEX_TITLE}**\n\n"
        f"{link}\n\n"
        "Use this index to resolve the correct technical note / IFM relationship for the "
        "queried I/O catalog number. I will not extract wiring diagrams from the index."
    )
    if part:
        reply += (
            f"\n\nWant me to use this index to look up the technical note / IFM relationship "
            f"for **{part}**?"
        )
    spoken = (
        "I cannot authoritatively verify that IFM or cable pairing"
        + (f" for {part}" if part else "")
        + ". I am not guessing a pairing. The prescribed next resource is the Allen-Bradley "
        "Wiring Diagram Knowledgebase Technote IDs by Part Number lookup index. "
        "It is a lookup index, not a module manual, and it does not prove compatibility. "
        "The openable index link is on screen."
    )
    if part:
        spoken += f" Want me to use that index for {part}?"
    pending = {
        "action": _PENDING_USE_AB_INDEX_ACTION,
        "part_number": part or None,
        "index_source": _AB_WIRING_INDEX_SOURCE,
        "index_title": _AB_WIRING_INDEX_TITLE,
        "index_smb": _AB_WIRING_INDEX_SMB,
    }
    return reply, spoken, pending


def _use_ab_wiring_index_for_part(
    part: str,
    *,
    public_origin: object = "",
) -> tuple[str, str]:
    """Look up technote/IFM pointers in the AB index without treating it as a manual."""
    link = _ab_wiring_index_link(public_origin=public_origin)
    text = ""
    try:
        text = fetch_active_document_text(_AB_WIRING_INDEX_SOURCE) or ""
    except Exception:  # noqa: BLE001
        text = ""
    hits: list[str] = []
    if text and part:
        needles = _part_match_needles(part)
        for raw in text.splitlines():
            line = re.sub(r"\s+", " ", raw).strip()
            if not line or len(line) < 8:
                continue
            low = line.lower()
            if not any(n.lower() in low for n in needles):
                continue
            # Keep technote / IFM / cable oriented rows.
            if re.search(r"\b(?:1492|ifm|technote|tech\s*note|wiring|cable)\b", low) or re.search(
                r"\b\d{6,}\b", line
            ):
                hits.append(line[:240])
            if len(hits) >= 5:
                break
    if hits:
        body = "\n".join(f"- {h}" for h in hits)
        reply = (
            f"From the **{_AB_WIRING_INDEX_TITLE}** for **{part}** "
            "(lookup index only — **not** an I/O module manual; does **not** prove compatibility):\n\n"
            f"{body}\n\n"
            f"{link}\n\n"
            "Use the listed technical-note / wiring-system pointers to continue the lookup. "
            "I will not extract diagrams from this index."
        )
        spoken = (
            f"I looked up {part} in the Allen-Bradley wiring diagram knowledgebase lookup index. "
            "Matching index rows are on screen. This is a lookup index, not a module manual, "
            "and it does not prove compatibility."
        )
        return reply, spoken
    reply = (
        f"I opened the **{_AB_WIRING_INDEX_TITLE}** for **{part}**, but I could not yet resolve "
        "a clear technical-note / IFM relationship row for that exact catalog number from the "
        "index text.\n\n"
        f"{link}\n\n"
        "This remains a lookup index only — not a module manual and not proof of compatibility. "
        "Open the index and search the part number there, or provide a technical-note ID."
    )
    spoken = (
        f"I checked the Allen-Bradley wiring diagram knowledgebase lookup index for {part}, "
        "but I could not resolve a clear technical note or IFM relationship row yet. "
        "The openable index link is on screen. It is not a module manual and does not prove compatibility."
    )
    return reply, spoken


def _electrical_not_found_reply(
    part: str,
    *,
    query: object = "",
    next_family: str = "",
    public_origin: object = "",
    chassis_slots: object = "",
) -> tuple[str, str, dict[str, Any] | None]:
    """Fail closed without dumping research onto the owner or citing a wrong hit.

    Unresolved IFM/cable pairings return the prescribed AB wiring lookup index.
    Chassis/power misses retrieve 1756-UM001 themselves.
    Other missing electrical facts stay on the cannot-yet-verify / next-retrieval path.
    """
    who = f" for **{part}**" if part else ""
    wants_ifm = _query_wants_ifm_pairing(query)
    wants_chassis = bool(
        _CHASSIS_POWER_TOPIC_RE.search(str(query or ""))
        or re.search(
            r"\b(?:power\s+suppl(?:y|ies)|psu|chassis|watt(?:age)?s?|redundan(?:t|cy)|slots?)\b",
            str(query or ""),
            re.I,
        )
    )
    slot_n = str(chassis_slots or "").strip() or _slot_count_from_text(query)
    if wants_ifm and not wants_chassis:
        return _electrical_ifm_index_fallback_reply(part, public_origin=public_origin)
    if wants_chassis:
        next_family = next_family or (
            "ControlLogix power-supply sizing publications "
            "(1756-UM001 system manual + 1756-IN619 / redundant-supply instructions)"
        )
        retrieval_query = (
            "ControlLogix chassis power supply sizing 1756-UM001"
            + (f" {slot_n}-slot" if slot_n else "")
        )
        reply = (
            f"I cannot yet verify a ControlLogix chassis/power-supply recommendation{who} "
            "from a part-validated engineering-library excerpt. "
            "I will not substitute model memory, operational opinion, or an unsourced catalog pattern.\n\n"
            f"Next I will retrieve **{next_family}**"
            + (f" for this **{part}** context" if part else "")
            + (f" (**{slot_n}-slot**)" if slot_n else "")
            + ".\n\n"
            "Want me to run that retrieval now?"
        )
        spoken = (
            "I cannot yet verify that ControlLogix chassis or power-supply recommendation"
            + (f" for {part}" if part else "")
            + " from a part-validated library source, so I will not guess. "
            f"Next I can retrieve {next_family}. Want me to run that now?"
        )
        pending = {
            "action": _PENDING_CHASSIS_SIZING_ACTION,
            "kind": "retrieval",
            "status": "pending",
            "part_number": part or None,
            "next_family": next_family,
            "topic": "controllogix_chassis_power",
            "chassis_slots": slot_n or None,
            "retrieval_query": retrieval_query,
        }
        return reply, spoken, pending
    if not next_family:
        if part and part.upper().startswith("1756-"):
            next_family = "the ControlLogix module publication family"
        else:
            next_family = "the governing vendor catalog/manual"
    reply = (
        f"I cannot yet verify that{who} from a part-validated engineering-library source. "
        "I will not substitute model memory, a generic family claim, or an unrelated manual link.\n\n"
        f"Next I will retrieve **{next_family}** for this exact catalog number.\n\n"
        "Want me to run that retrieval now?"
    )
    spoken = (
        f"I cannot yet verify that"
        + (f" for {part}" if part else "")
        + " from a part-validated library source, so I will not guess. "
        f"Next I can retrieve {next_family}. Want me to run that now?"
    )
    pending = None
    if part:
        pending = {
            "action": "retrieve_part_manual",
            "kind": "retrieval",
            "status": "pending",
            "part_number": part,
            "next_family": next_family,
            "retrieval_query": f"{part} engineering manual datasheet",
        }
    return reply, spoken, pending


def _electrical_retrieval_exhausted_reply(
    part: str,
    *,
    pending: object = None,
    public_origin: object = "",
    candidate_source: object = "",
    candidate_title: object = "",
) -> tuple[str, str, None]:
    """Honest result after an offered retrieval already ran — never re-offer the same ask."""
    pend = pending if isinstance(pending, dict) else {}
    next_family = str(pend.get("next_family") or "the offered publications").strip()
    slot_n = str(pend.get("chassis_slots") or "").strip()
    who = f" for **{part}**" if part else ""
    slot_bit = f" (**{slot_n}-slot**)" if slot_n else ""
    source = library_relpath_from_source(candidate_source) or str(candidate_source or "").strip()
    title = str(candidate_title or "").strip()
    link = markdown_link_for_source(source, public_origin=public_origin) if source else ""
    if source and _is_chassis_power_manual(source, title):
        in619_note = ""
        if "UM001" in (title + source).upper() or "um001" in source.lower():
            # Availability language must reflect the live publication
            # manifest, never a hardcoded assumption — 1756-IN619 may have
            # been ingested since this offer was written.
            in619_alias = resolve_ab_1756_publication_alias("1756-IN619")
            if isinstance(in619_alias, dict) and in619_alias.get("status") == "absent":
                in619_note = ", and **1756-IN619** is not available in this library"
        reply = (
            f"I ran the retrieval for **{next_family}**{who}{slot_bit}. "
            "The library returned "
            f"**{title or source}**, but it does not contain a verified power-supply sizing "
            "excerpt I can cite for a catalog part number"
            + in619_note
            + ". I will not invent a 1756-PAxx / 1756-PBxx selection.\n\n"
            f"Source: {link}"
        )
        spoken = (
            "I ran that retrieval"
            + (f" for the {slot_n}-slot chassis" if slot_n else "")
            + ". The system manual is on screen, but it does not contain a verified sizing excerpt "
            "I can cite for a power-supply part number, so I will not guess. Source link is on screen."
        )
    else:
        reply = (
            f"I ran the retrieval for **{next_family}**{who}{slot_bit}. "
            "No part-validated sizing excerpt is available in the engineering library for this ask. "
            "I will not invent a power-supply catalog number or repeat the retrieval offer."
        )
        spoken = (
            "I ran that retrieval"
            + (f" for the {slot_n}-slot chassis" if slot_n else "")
            + ". No verified sizing excerpt is available in the library, so I will not guess a power-supply part number."
        )
    return reply, spoken, None


def _best_engineering_excerpt(text: object, query: object) -> str:
    """Return a compact evidence passage most responsive to an engineering ask."""
    # Legacy Word previews often arrive as one enormous HTML text node.  Split
    # it into sentences first so a matching requirement does not get buried
    # behind the opening scope paragraph.
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in re.split(r"(?<=[.!?])\s+|\n+", str(text or ""))
    ]
    lines = [line for line in lines if line]
    tokens = set(re.findall(r"[a-z0-9]{3,}", str(query or "").lower()))
    tokens -= {"what", "which", "where", "when", "with", "from", "that", "this", "does", "need", "shall", "should", "according"}
    best_index, best_score = -1, 0
    asks_recommendation = bool(_ACTIVE_DOCUMENT_RECOMMENDATION_RE.search(str(query or "")))
    for index, line in enumerate(lines):
        folded = line.lower()
        hits = {token for token in tokens if token in folded}
        score = len(hits) + 3 * len(hits & _ENGINEERING_PRIORITY_TERMS)
        if asks_recommendation and ("preferred" in folded or "recommended" in folded):
            score += 3
        if asks_recommendation and " or " in folded:
            score += 2
        if score > best_score:
            best_index, best_score = index, score
    # One generic overlap (for example, just "pump" in a scope clause) is
    # not evidence for a specific requirement such as shaft hardness.
    if best_score < 2:
        return ""
    return lines[best_index][:1800].strip()


def try_engineering_rag_answer(
    query: object,
    *,
    public_origin: object = "",
    active_document: object = None,
) -> Optional[dict[str, Any]]:
    """Retrieve and quote a source for an engineering question; never guess a value.

    Electrical equipment facts (fuse/rating/IFM/compatibility) are fail-closed:
    claims require an authoritative excerpt tied to the exact part number. Linked
    sources must themselves be part/family-validated — never an unrelated "closest hit".
    """
    msg = str(query or "").strip()
    # Governing-source guidance ("That is the manual to use when asked about
    # 1756 power supplies.") is an instruction, not an engineering question --
    # it must not be independently answered here just because it happens to
    # name an engineering topic. try_active_document_review already handles
    # it when there is a document to bind; with none bound, it must reach
    # ordinary chat, not get treated as if the user actually asked the topic
    # question.
    if is_governing_source_guidance(msg):
        return None
    compatibility = is_active_part_compatibility_followup(msg, active_document)
    chassis_followup = is_active_chassis_power_followup(msg, active_document)
    chassis_topic = bool(
        _CHASSIS_POWER_TOPIC_RE.search(msg)
        or chassis_followup
        or (
            isinstance(active_document, dict)
            and (
                active_document.get("topic") == "controllogix_chassis_power"
                or active_document.get("chassis_power")
            )
            and compatibility
        )
    )
    pending_lookup = False
    pending_use_index = False
    pending_chassis = False
    pending_payload: dict[str, Any] | None = None
    if isinstance(active_document, dict) and is_affirmative_followup(msg):
        pending = active_document.get("pending_action")
        if isinstance(pending, dict):
            action = str(pending.get("action") or "")
            pending_payload = dict(pending)
            pending_payload["status"] = "running"
            if action == _PENDING_USE_AB_INDEX_ACTION:
                pending_use_index = True
            elif action == _PENDING_CHASSIS_SIZING_ACTION:
                pending_chassis = True
                chassis_topic = True
            elif action in {_PENDING_IFM_LOOKUP_ACTION, "retrieve_part_manual"}:
                pending_lookup = True
    if not (
        is_engineering_rag_question(msg)
        or compatibility
        or pending_lookup
        or pending_use_index
        or pending_chassis
        or chassis_followup
    ):
        return None
    origin = normalize_public_origin(public_origin)
    part = _resolve_query_part(msg, active_document)
    if (pending_lookup or pending_use_index or pending_chassis) and not part and isinstance(
        active_document, dict
    ):
        part = str(
            (pending_payload or {}).get("part_number")
            or active_document.get("part_number")
            or ""
        ).strip()

    if pending_use_index and part:
        reply, spoken = _use_ab_wiring_index_for_part(part, public_origin=origin)
        keep = {
            "part_number": part,
            "lookup_index_source": _AB_WIRING_INDEX_SOURCE,
            "lookup_index_title": _AB_WIRING_INDEX_TITLE,
            "document_kind": "index",
        }
        return {
            "handled": True,
            "reply": reply,
            "spoken_reply": spoken,
            "source": _AB_WIRING_INDEX_SOURCE,
            "active_document": keep,
            "pending_action": None,
            "error": None,
            "engineering_rag_answer": True,
            "verification": "lookup_index",
            "part_number": part,
            "document_kind": "index",
        }

    electrical = (
        is_electrical_equipment_fact_question(msg)
        or compatibility
        or pending_lookup
        or pending_chassis
        or chassis_topic
        or bool(part and re.search(r"\b(?:ifm|cable|1492|fuse|fusing|match)\b", msg, re.I))
    )
    retrieval_query = msg
    slot_n = _slot_count_from_text(msg)
    if not slot_n and isinstance(active_document, dict):
        slot_n = str(active_document.get("chassis_slots") or "").strip()
    if not slot_n and pending_payload:
        slot_n = str(pending_payload.get("chassis_slots") or "").strip()
    if pending_chassis or chassis_topic:
        stored_q = str((pending_payload or {}).get("retrieval_query") or "").strip()
        if pending_chassis and stored_q:
            retrieval_query = stored_q
        else:
            retrieval_query = (
                f"ControlLogix chassis power supply sizing 1756-UM001"
                + (f" {slot_n}-slot" if slot_n else "")
                + (f" {msg}" if msg and not is_affirmative_followup(msg) and not _SLOT_FOLLOWUP_RE.match(msg) else "")
            )
    elif pending_lookup and part:
        stored_q = str((pending_payload or {}).get("retrieval_query") or "").strip()
        retrieval_query = stored_q or f"{part} 1492 IFM cable wiring system 1756-UM058"
    elif compatibility and part:
        retrieval_query = f"{msg} {part}"
    elif part and part.lower() not in msg.lower():
        retrieval_query = f"{msg} {part}"
    if electrical and part and re.search(r"\b(?:ifm|cable|1492|match|compatible)\b", retrieval_query, re.I):
        retrieval_query = f"{retrieval_query} 1492 IFM 1756-UM058"

    try:
        matches = list(
            retrieve_documents(retrieval_query, topk=8, public_origin=origin).get("matches") or []
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("engineering RAG retrieve failed: %s", type(exc).__name__)
        reply = "I could not reach the engineering library to verify that requirement."
        keep = (
            dict(active_document)
            if isinstance(active_document, dict)
            else ({"part_number": part} if part else None)
        )
        return {
            "handled": True,
            "reply": reply,
            "spoken_reply": reply,
            "source": None,
            "active_document": keep,
            "error": type(exc).__name__,
            "engineering_rag_answer": True,
        }

    seeded = _seed_authoritative_manuals_for_part(part, query=retrieval_query)
    if seeded:
        seen_sources = {
            str(m.get("source") or "").replace("\\", "/")
            for m in matches
            if isinstance(m, dict)
        }
        for seed in seeded:
            src = str(seed.get("source") or "").replace("\\", "/")
            if src and src not in seen_sources:
                matches.insert(0, seed)
                seen_sources.add(src)

    # Governing-source continuity: a document the operator explicitly bound as
    # the authoritative reference for this same topic (via governing-source
    # guidance) must be consulted first, ahead of fresh generic retrieval --
    # not merely retained as inert metadata. It stays in effect only while the
    # question remains in-topic; an explicit different source/topic or a
    # cleared/replaced active_document ends it naturally (nothing here
    # special-cases expiry -- it simply requires the still-current
    # active_document to carry the matching governing_topic_key).
    governing_key = ""
    governing_source = ""
    if isinstance(active_document, dict):
        governing_key = str(active_document.get("governing_topic_key") or "").strip()
        governing_source = str(active_document.get("source") or "").strip()
    governing_in_topic = bool(
        governing_key
        and governing_source
        and chassis_topic
        and governing_key == "controllogix_chassis_power"
    )

    priority_match: dict[str, Any] | None = active_document if governing_in_topic else None
    priority_source = governing_source.replace("\\", "/") if governing_in_topic else ""
    if not priority_match and chassis_topic:
        # 1756-TD005 ("ControlLogix Power Supplies Specifications Technical
        # Data") is the authoritative SIZING/SELECTION document -- it has an
        # actual Power Load and Transformer Sizing section, unlike
        # installation-instructions manuals such as IN619 that merely rank
        # higher on generic similarity. Prefer it when this chassis-power
        # question actually retrieved it -- never fabricate/seed it if
        # retrieval did not genuinely surface it.
        for m in matches:
            if not isinstance(m, dict):
                continue
            src = str(m.get("source") or "").replace("\\", "/")
            if re.search(r"\btd0*05(?:[_\-]|\b)", src, re.I):
                priority_match = m
                priority_source = src
                break

    candidates: list[dict[str, Any]] = []
    if priority_match is not None:
        candidates.append(priority_match)
    primary = select_engineering_evidence_match(matches, query=retrieval_query)
    if isinstance(primary, dict) and primary is not priority_match:
        candidates.append(primary)
    for match in matches:
        if not isinstance(match, dict) or match is primary or match is priority_match:
            continue
        source = str(match.get("source") or "").replace("\\", "/")
        if priority_source and source == priority_source:
            continue  # already the priority candidate above; do not re-add.
        title = _match_title(match)
        if classify_document_kind(source, title) != "manual":
            continue
        if chassis_topic and not _is_chassis_power_manual(source, title):
            continue
        if part and not source_family_compatible_with_part(source, title, part):
            continue
        candidates.append(match)
    if chassis_topic and primary and not _is_chassis_power_manual(
        primary.get("source"), _match_title(primary)
    ):
        # Drop a wrong-family primary that slipped in (e.g. analog UM009).
        candidates = [c for c in candidates if c is not primary]
    if (
        not candidates
        and isinstance(active_document, dict)
        and active_document.get("source")
        and source_family_compatible_with_part(
            active_document.get("source"),
            active_document.get("title"),
            part or active_document.get("part_number"),
        )
    ):
        candidates.append(active_document)

    if not electrical:
        selected = (
            _evidence_record_from_match(candidates[0], public_origin=origin, part=part)
            if candidates
            else None
        )
        if selected and _active_document_source(selected):
            handoff = try_jarvis_n8n_engineering_handoff(msg, matches, public_origin=origin)
            if handoff and handoff.get("handled"):
                handoff["reply"] = _strip_chain_of_thought(handoff.get("reply") or "")
                handoff["active_document"] = selected
                return handoff

    selected: dict[str, Any] | None = None
    passage = ""
    for match in candidates:
        trial = _evidence_record_from_match(match, public_origin=origin, part=part)
        if chassis_topic and not _is_chassis_power_manual(
            trial.get("source"), trial.get("title")
        ):
            continue
        if part and not source_family_compatible_with_part(
            trial.get("source"), trial.get("title"), part
        ):
            continue
        text = _load_manual_text_for_evidence(trial)
        if not text:
            continue
        if part and not chassis_topic and not _text_mentions_part(text, part):
            continue
        trial_passage = ""
        if electrical and chassis_topic:
            trial_passage = _extract_chassis_power_facts(
                text, query=(f"{retrieval_query} {slot_n}-slot" if slot_n else retrieval_query)
            )
        if not trial_passage and electrical and part and not chassis_topic:
            trial_passage = _extract_part_scoped_facts(text, part, query=retrieval_query)
        if not trial_passage and not chassis_topic:
            trial_passage = _best_engineering_excerpt(text, retrieval_query)
            if electrical and part and trial_passage and not _text_mentions_part(
                trial_passage, part
            ):
                trial_passage = ""
        # Chassis/power asks: only strong sizing excerpts — never TOC soft-matches.
        if trial_passage and not _opinionated_electrical_leak(trial_passage):
            selected = trial
            passage = trial_passage
            break

    keep_part_ctx: dict[str, Any] | None = None
    if isinstance(active_document, dict) and (
        active_document.get("part_number")
        or active_document.get("source")
        or active_document.get("topic")
        or active_document.get("chassis_power")
    ):
        keep_part_ctx = dict(active_document)
    if part:
        keep_part_ctx = dict(keep_part_ctx or {})
        keep_part_ctx["part_number"] = part
    if chassis_topic:
        keep_part_ctx = dict(keep_part_ctx or {})
        keep_part_ctx["topic"] = "controllogix_chassis_power"
        keep_part_ctx["chassis_power"] = True
        if slot_n:
            keep_part_ctx["chassis_slots"] = slot_n

    if not (selected and passage):
        # Chassis misses must still retain chassis context for "13 slot" follow-ups.
        reply_query = msg
        if chassis_topic and slot_n and "slot" not in msg.lower():
            reply_query = f"{msg} {slot_n}-slot chassis"
        elif chassis_topic and not _CHASSIS_POWER_TOPIC_RE.search(msg):
            reply_query = f"ControlLogix chassis power supply {msg}"

        # Affirmative pending retrieval already ran — never echo the original offer.
        if pending_chassis or pending_lookup:
            candidate_source = ""
            candidate_title = ""
            for match in candidates:
                if not isinstance(match, dict):
                    continue
                trial = _evidence_record_from_match(match, public_origin=origin, part=part)
                src = str(trial.get("source") or "")
                title = str(trial.get("title") or "")
                if pending_chassis and _is_chassis_power_manual(src, title):
                    candidate_source, candidate_title = src, title
                    break
                if pending_lookup and src and (
                    not part
                    or source_family_compatible_with_part(src, title, part)
                ):
                    candidate_source, candidate_title = src, title
                    break
            if not candidate_source:
                for match in matches:
                    if not isinstance(match, dict):
                        continue
                    src = str(match.get("source") or "")
                    title = _match_title(match)
                    if pending_chassis and _is_chassis_power_manual(src, title):
                        candidate_source, candidate_title = src, title
                        break
            reply, spoken, _pending_clear = _electrical_retrieval_exhausted_reply(
                part,
                pending=pending_payload,
                public_origin=origin,
                candidate_source=candidate_source,
                candidate_title=candidate_title,
            )
            keep = dict(keep_part_ctx or {})
            if part:
                keep["part_number"] = part
            if chassis_topic or pending_chassis:
                keep["topic"] = "controllogix_chassis_power"
                keep["chassis_power"] = True
                if slot_n:
                    keep["chassis_slots"] = slot_n
            keep.pop("pending_action", None)
            source_out = (
                library_relpath_from_source(candidate_source)
                or str(candidate_source or "").strip()
                or None
            )
            if source_out:
                keep["source"] = source_out
                keep["title"] = candidate_title or keep.get("title")
                keep["url"] = normalize_corpus_url(
                    "", source=source_out, public_origin=origin
                ) or keep.get("url")
            return {
                "handled": True,
                "reply": reply,
                "spoken_reply": spoken,
                "source": source_out,
                "active_document": keep or None,
                "pending_action": None,
                "error": None,
                "engineering_rag_answer": True,
                "verification": "retrieval_exhausted",
                "part_number": part or None,
                "document_kind": "manual" if source_out else None,
            }

        reply, spoken, pending = _electrical_not_found_reply(
            part,
            query=reply_query if chassis_topic else msg,
            public_origin=origin,
            chassis_slots=slot_n,
        )
        verification = (
            "lookup_index"
            if pending and str(pending.get("action") or "") == _PENDING_USE_AB_INDEX_ACTION
            else "not_found"
        )
        source_out = (
            _AB_WIRING_INDEX_SOURCE if verification == "lookup_index" else None
        )
        if keep_part_ctx is None and (part or chassis_topic):
            keep_part_ctx = {}
            if part:
                keep_part_ctx["part_number"] = part
            if chassis_topic:
                keep_part_ctx["topic"] = "controllogix_chassis_power"
                keep_part_ctx["chassis_power"] = True
                if slot_n:
                    keep_part_ctx["chassis_slots"] = slot_n
        if keep_part_ctx is not None and pending:
            keep_part_ctx = dict(keep_part_ctx)
            keep_part_ctx["pending_action"] = pending
            keep_part_ctx["part_number"] = part or keep_part_ctx.get("part_number")
            if chassis_topic:
                keep_part_ctx["topic"] = "controllogix_chassis_power"
                keep_part_ctx["chassis_power"] = True
                if slot_n:
                    keep_part_ctx["chassis_slots"] = slot_n
            if verification == "lookup_index":
                keep_part_ctx["lookup_index_source"] = _AB_WIRING_INDEX_SOURCE
                keep_part_ctx["lookup_index_title"] = _AB_WIRING_INDEX_TITLE
                keep_part_ctx["document_kind"] = "index"
                # Never bind the xlsx as the extractable active manual source.
                if classify_document_kind(
                    keep_part_ctx.get("source"), keep_part_ctx.get("title")
                ) == "index" or str(keep_part_ctx.get("source") or "").lower().endswith(
                    (".xlsx", ".xls", ".csv")
                ):
                    keep_part_ctx.pop("source", None)
                    keep_part_ctx.pop("url", None)
            if keep_part_ctx.get("source") and part and not source_family_compatible_with_part(
                keep_part_ctx.get("source"), keep_part_ctx.get("title"), part
            ):
                keep_part_ctx.pop("source", None)
                keep_part_ctx.pop("url", None)
        return {
            "handled": True,
            "reply": reply,
            "spoken_reply": spoken,
            "source": source_out,
            "active_document": keep_part_ctx,
            "pending_action": pending,
            "error": None,
            "engineering_rag_answer": True,
            "verification": verification,
            "part_number": part or None,
            "document_kind": "index" if verification == "lookup_index" else None,
        }

    source = library_relpath_from_source(_active_document_source(selected)) or _active_document_source(
        selected
    )
    link = markdown_link_for_source(source, public_origin=origin)
    title = str(selected.get("title") or selected.get("doc_no") or "").strip()
    selected = dict(selected)
    selected["source"] = source
    selected.pop("pending_action", None)
    if part:
        selected["part_number"] = part
    if chassis_topic:
        selected["topic"] = "controllogix_chassis_power"
        selected["chassis_power"] = True
        if slot_n:
            selected["chassis_slots"] = slot_n
    if governing_in_topic:
        # Still in-topic for the bound governing source -- carry the binding
        # forward so a later same-topic follow-up keeps consulting it too,
        # even if this turn's cited passage came from a supplementing source.
        selected["governing_topic"] = active_document.get("governing_topic")
        selected["governing_topic_key"] = governing_key

    # A generic chassis-power ask with no chassis slot count is missing the
    # input that actually determines which catalog number applies. Dumping
    # the raw catalog-table excerpt (or picking one number from it) would
    # look like a sizing answer without being one. Disclose that real,
    # cited evidence was found and ask for the minimum missing sizing facts
    # instead -- unless a slot count is already known (query, active
    # document, or pending payload), in which case the evidence unambiguously
    # narrows the answer and the existing sizing-facts extraction proceeds.
    generic_chassis_ask = chassis_topic and (not part or part == "1756-CHASSIS")
    # A worksheet/backplane-current/chassis-load excerpt IS the sizing answer
    # (the evidence unambiguously supplies it) -- only a bare catalog-number
    # listing with no such sizing determination is unsafe to present as-is,
    # regardless of whether the chassis slot count is already known (a slot
    # count alone does not determine AC/DC or redundancy).
    passage_is_unambiguous_sizing = bool(
        re.search(r"sizing\s+worksheet|backplane\s+current|chassis\s+load", passage, re.I)
    )
    if generic_chassis_ask and not passage_is_unambiguous_sizing:
        missing: list[str] = []
        if not slot_n:
            missing.append("Chassis slot count.")
        missing.append(
            "Supply input available (line 120/240 VAC, or 24 VDC for a redundant-supply "
            "input), and whether redundant power is required."
        )
        found_bit = (
            f"for a **{slot_n}-slot** ControlLogix chassis " if slot_n else ""
        )
        reply = (
            f"I found grounded ControlLogix chassis-power evidence {found_bit}in "
            f"**{title or 'the engineering library'}**, but I will not pick a specific power-supply "
            "catalog number without the sizing inputs that determine it. To size/select the supply "
            "I need:\n\n"
            + "\n".join(f"{i}. {fact}" for i, fact in enumerate(missing, 1))
            + f"\n\nSource: {link}"
        )
        spoken = (
            "I found real chassis-power evidence"
            + (f" for a {slot_n}-slot chassis" if slot_n else "")
            + ", but I need the supply input you have"
            + ("" if slot_n else " and the slot count")
            + " before I can size or select a specific power supply. Source link is on screen."
        )
        return {
            "handled": True,
            "reply": reply,
            "spoken_reply": spoken,
            "source": source,
            "active_document": selected,
            "error": None,
            "engineering_rag_answer": True,
            "verification": "source_grounded",
            "part_number": part or None,
        }

    header = f"From the engineering library"
    if part:
        header += f" for **{part}**"
    elif chassis_topic:
        header += " for ControlLogix chassis/power supply sizing"
        if slot_n:
            header += f" (**{slot_n}-slot**)"
    if title:
        header += f" ({title})"
    header += ":"
    reply = f"{header}\n\n{passage}\n\nSource: {link}"
    if electrical:
        if chassis_topic:
            spoken = (
                "From the ControlLogix system manual"
                + (f" for a {slot_n}-slot chassis" if slot_n else "")
                + ", "
                + re.sub(r"\s+", " ", passage)[:220].rsplit(" ", 1)[0]
                + ". Source link is on screen."
            )
        else:
            spoken = _compact_electrical_spoken(part, passage)
        if re.search(r"\b120\s*v\b", msg, re.I) and re.search(
            r"v\s*dc|10…30|10 to 30 volt DC", passage, re.I
        ):
            reply += (
                "\n\nNote: the cited publication classifies this catalog number as "
                "**DC**, not a 120 VAC module. Use the manual voltage class."
            )
    else:
        compact = re.sub(r"\s+", " ", passage)
        if len(compact) > 220:
            compact = compact[:217].rsplit(" ", 1)[0] + "."
        spoken = ("For " + part + ", " if part else "") + compact + " Source link is on screen."

    reply = _strip_chain_of_thought(reply)
    spoken = _strip_chain_of_thought(spoken)
    if _opinionated_electrical_leak(reply) or _opinionated_electrical_leak(spoken):
        # Hard fail-closed if any opinion slang leaked into the grounded path.
        if pending_chassis or pending_lookup:
            reply, spoken, _pending_clear = _electrical_retrieval_exhausted_reply(
                part,
                pending=pending_payload,
                public_origin=origin,
                candidate_source=source,
                candidate_title=title,
            )
            keep = dict(selected)
            keep.pop("pending_action", None)
            return {
                "handled": True,
                "reply": reply,
                "spoken_reply": spoken,
                "source": source,
                "active_document": keep,
                "pending_action": None,
                "error": None,
                "engineering_rag_answer": True,
                "verification": "retrieval_exhausted",
                "part_number": part or None,
            }
        reply, spoken, pending = _electrical_not_found_reply(
            part,
            query=msg if not chassis_topic else f"ControlLogix chassis power {msg}",
            public_origin=origin,
            chassis_slots=slot_n,
        )
        keep = dict(selected)
        if pending:
            keep["pending_action"] = pending
        return {
            "handled": True,
            "reply": reply,
            "spoken_reply": spoken,
            "source": None,
            "active_document": keep,
            "pending_action": pending,
            "error": None,
            "engineering_rag_answer": True,
            "verification": "not_found",
            "part_number": part or None,
        }
    # Keep spoken compact and complete — never truncated mid-thought.
    if len(spoken) > 420:
        spoken = spoken[:417].rsplit(" ", 1)[0] + "."
    if "Source link is on screen" not in spoken:
        spoken = spoken.rstrip(".") + ". Source link is on screen."
    return {
        "handled": True,
        "reply": reply,
        "spoken_reply": spoken,
        "source": source,
        "active_document": selected,
        "error": None,
        "engineering_rag_answer": True,
        "verification": "source_grounded",
        "part_number": part or None,
    }



def jarvis_n8n_handoff_enabled() -> bool:
    """Opt-in gate for Smedley Library → Jarvis-N8N PA briefing handoff."""
    raw = (os.environ.get(JARVIS_N8N_HANDOFF_ENABLE_ENV) or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _load_jarvis_n8n_propose_token() -> str:
    token = (os.environ.get(JARVIS_N8N_TOKEN_ENV) or "").strip()
    path = (os.environ.get(JARVIS_N8N_TOKEN_FILE_ENV) or "").strip()
    if path:
        try:
            file_token = open(path, encoding="utf-8").read().strip()
            if file_token:
                token = file_token
        except OSError:
            pass
    return token


def _jarvis_n8n_briefing_url() -> str:
    return (
        os.environ.get(JARVIS_N8N_BRIEFING_URL_ENV) or DEFAULT_JARVIS_N8N_BRIEFING_URL
    ).strip()


def _extract_jarvis_briefing_speak(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("speak", "answer", "summary"):
        value = payload.get(key)
        if value:
            return str(value).strip()
    for nest_key in ("briefing", "biggy_direct_reply", "briefing_response", "response"):
        nested = payload.get(nest_key)
        if isinstance(nested, dict):
            for key in ("speak", "answer", "summary", "text"):
                value = nested.get(key)
                if value:
                    return str(value).strip()
    return ""


def try_jarvis_n8n_engineering_handoff(
    query: object,
    matches: list[dict[str, Any]],
    *,
    public_origin: object = "",
) -> Optional[dict[str, Any]]:
    """Send Smedley Library retrieve evidence through Jarvis PA governed briefing.

    Preserves Smedley RAG as the evidence source. Returns None when handoff is
    disabled, unauthenticated, or Jarvis fails — callers keep local excerpt fallback.
    """
    if not jarvis_n8n_handoff_enabled():
        return None
    token = _load_jarvis_n8n_propose_token()
    if not token:
        logger.info("jarvis n8n handoff skipped: propose token not configured")
        return None
    origin = normalize_public_origin(public_origin)
    excerpts: list[str] = []
    citations: list[dict[str, str]] = []
    for match in (matches or [])[:5]:
        if not isinstance(match, dict):
            continue
        source = str(match.get("source") or "").strip()
        if not source:
            continue
        link = markdown_link_for_source(source, public_origin=origin)
        snip = str(match.get("snippet") or match.get("text") or "").strip()[:400]
        cite = {
            "source": source,
            "url": str(match.get("url") or link),
            "provenance": "smedley_library_rag",
        }
        if match.get("match_kind"):
            cite["match_kind"] = str(match.get("match_kind"))
        if match.get("part_number"):
            cite["part_number"] = str(match.get("part_number"))
        if match.get("observed_part"):
            cite["observed_part"] = str(match.get("observed_part"))
        if isinstance(match.get("document_identity"), dict):
            cite["document_identity"] = match.get("document_identity")
        if match.get("revision"):
            cite["revision"] = str(match.get("revision"))
        if match.get("page_hint") is not None:
            cite["page_hint"] = match.get("page_hint")
        if match.get("index_href"):
            cite["index_href"] = str(match.get("index_href"))
        if match.get("retrieval"):
            cite["retrieval"] = str(match.get("retrieval"))
        citations.append(cite)
        excerpts.append(f"- {source}: {snip}" if snip else f"- {source} ({link})")
    if not excerpts:
        return None

    import uuid
    from datetime import datetime, timezone

    corr = "smedley-rag-jarvis-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    corr = f"{corr}-{uuid.uuid4().hex[:8]}"
    objective = (
        "Smedley engineering RAG handoff. Using ONLY the Smedley Library excerpts "
        "below, answer the operator question. Cite the library source path/URL. "
        "Do not invent documents or values.\n\n"
        f"Operator question: {str(query or '').strip()}\n\n"
        "Smedley Library excerpts:\n" + "\n".join(excerpts)
    )
    payload = {
        "schema": "jarvis.briefing_request.v1",
        "type": "jarvis.briefing_request",
        "correlation_id": corr,
        "objective": objective,
        "source": "smedley_rag_call",
        "authority": "owner_authorized_smedley_handoff",
        "authorization_ref": "smedley-engineering-rag-jarvis-n8n",
        "requester": "smedley",
        "response_channel": "biggy_direct_speak",
        "smedley_rag": {
            "schema": "smedley.library_retrieve.v1",
            "match_count": len(matches or []),
            "citations": citations,
        },
    }
    request = urllib.request.Request(
        _jarvis_n8n_briefing_url(),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-GPT-Propose-Token": token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read()
            status = getattr(response, "status", 200)
    except urllib.error.HTTPError as exc:
        body = exc.read() if hasattr(exc, "read") else b""
        status = int(getattr(exc, "code", 0) or 0)
        logger.warning(
            "jarvis n8n handoff HTTP %s: %s",
            status,
            body[:200].decode("utf-8", "replace"),
        )
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("jarvis n8n handoff failed: %s", type(exc).__name__)
        return None
    try:
        parsed = json.loads(body.decode("utf-8"))
    except Exception:
        return None
    speak = _extract_jarvis_briefing_speak(parsed)
    if status != 200 or not speak:
        return None
    active_document = active_document_from_matches(matches, query=query, public_origin=origin)
    source = _active_document_source(active_document)
    # Keep sidecar provenance visible even when Jarvis speak omits the markdown link.
    if source and WEBUI_CORPUS_SIDECAR not in speak:
        speak = f"{speak.rstrip()}\n\nSource: {markdown_link_for_source(source, public_origin=origin)}"
    return {
        "handled": True,
        "reply": speak,
        "spoken_reply": sanitize_for_spoken_output(speak),
        "source": source,
        "active_document": active_document,
        "jarvis_n8n_handoff": True,
        "correlation_id": corr,
        "error": None,
    }


def _has_explicit_document_identity_token(msg: str) -> bool:
    """True when the query names a concrete document identity (doc number,
    Honeywell part number, AB 1756 publication token, spec number) rather
    than merely matching a generic verb/noun proximity heuristic.

    A no-match reply for a query WITHOUT an explicit identity token is not a
    deliberate request to move to a different document, so it must not clear
    an existing active_document binding on its own.
    """
    if not msg:
        return False
    if extract_ab_1756_publication_tokens(msg):
        return True
    if _DOCNUM.search(msg):
        return True
    if _HW_PART.search(msg):
        return True
    if is_specification_number_request(msg):
        return True
    return False


def try_document_route(
    query: object,
    *,
    topk: int = 8,
    public_origin: object = "",
    prior_validated_part: object = None,
    active_document: object = None,
) -> Optional[dict[str, Any]]:
    """If query is a document request, retrieve and return a deterministic reply.

    Returns None when the query is not a document request (ordinary chat).
    """
    if not document_route_enabled():
        return None
    msg = str(query or "").strip()
    if is_library_path_operation(msg):
        return {
            "handled": True,
            "query": msg,
            "reply": (
                "That SMB/library path is not a chat extract. Use the right-rail "
                "**INGEST TO RAG** folder picker and **Rescan selected library** "
                "(or drop the file there). Watcher identity, phase, and reason "
                "show in the ingest queue — not in this conversation."
            ),
            "spoken_reply": (
                "Use the ingest sidebar to rescan the selected library. "
                "Do not paste an SMB path into chat."
            ),
            "matches": [],
            "collection": None,
            "active_document": None,
            "pending_action": None,
            "retrieval": "library_path_rejected",
            "error": None,
        }
    validated_part, part_identity_source = resolve_validated_part(
        msg,
        prior_validated_part=prior_validated_part,
        active_document=active_document,
    )
    query_intent = classify_retrieval_intent(msg)
    retrieval_msg = msg
    carried_wiring = (
        part_identity_source == "prior_turn_validated"
        and is_wiring_narrowing_followup(msg)
        and bool(validated_part)
    )
    if carried_wiring:
        retrieval_msg = f"{validated_part} wiring schematic"
        query_intent = "wiring_schematic"
    if not is_document_request(msg) and not carried_wiring:
        return None
    origin = normalize_public_origin(public_origin)
    alias = resolve_ab_1756_publication_alias(msg)
    if alias:
        if alias.get("status") == "present":
            match = _match_from_ab_1756_alias(alias, public_origin=origin)
            matches = [match]
            reply, pending = build_operator_document_reply(
                matches, query=msg, public_origin=origin
            )
            active_document = active_document_from_matches(
                matches, query=msg, public_origin=origin
            )
            if isinstance(active_document, dict):
                active_document = dict(active_document)
                active_document["publication_alias"] = True
                active_document["publication_identifier"] = (
                    (match.get("document_identity") or {}).get("publication_identifier")
                )
                active_document["family"] = "1756 ControlLogix"
                active_document["vendor"] = "Allen-Bradley / Rockwell Automation"
            reply = neutralize_lan_url_text(reply, public_origin=origin)
            spoken = build_compact_spoken_document_reply(matches, query=msg)
            spoken = re.sub(r"\s+", " ", str(spoken or "")).strip()
            receipt = build_retrieval_receipt(matches, query=msg)
            return {
                "handled": True,
                "query": msg,
                "reply": reply,
                "spoken_reply": spoken,
                "matches": matches,
                "collection": "ab_1756_publication_alias",
                "active_document": active_document if active_document else None,
                "pending_action": pending,
                "retrieval": "ab_1756_publication_alias",
                "retrieval_receipt": receipt,
                "verification": "publication_alias",
                "error": None,
            }
        reply = _ab_1756_absent_reply(alias)
        return {
            "handled": True,
            "query": msg,
            "reply": reply,
            "spoken_reply": sanitize_for_spoken_output(reply),
            "matches": [],
            "collection": "ab_1756_publication_alias",
            "active_document": None,
            "pending_action": None,
            "retrieval": "ab_1756_publication_alias",
            "verification": "publication_absent",
            "error": None,
        }
    payload: dict[str, Any] | None = None
    rejected_planning: list[dict[str, Any]] = []
    if validated_part and _HW_PART.search(validated_part):
        # TDC3000 Process Manager I/O Installation (PM20-520) is the first and
        # only authoritative resolver for MU/MC IOP/FTA identity and wiring.
        # Do not consult semantic RAG or HP02-500 planning ranking.
        rejected_planning.append(
            {
                "source": "hp02500.pdf",
                "title": "High-Performance Process Manager Planning",
                "reason": "planning_manual_never_authoritative_for_pm_io_fta",
            }
        )
        payload = retrieve_pm_io_installation_payload(
            validated_part, query=retrieval_msg, public_origin=origin
        )
    if payload is None:
        try:
            retrieval_query = (
                project_spec_lookup_query(retrieval_msg)
                if is_specification_number_request(retrieval_msg)
                else retrieval_msg
            )
            payload = retrieve_documents(retrieval_query, topk=topk, public_origin=origin)
        except Exception as exc:  # noqa: BLE001
            logger.warning("smedley document route retrieve failed: %s", type(exc).__name__)
            reply = (
                "Document request detected, but Smedley RAG retrieval is unavailable "
                f"({type(exc).__name__}). Ordinary chat was not used for this turn."
            )
            return {
                "handled": True,
                "query": msg,
                "reply": reply,
                "spoken_reply": sanitize_for_spoken_output(reply),
                "matches": [],
                "collection": "",
                "error": type(exc).__name__,
            }
    matches = payload.get("matches") or []
    for raw in matches:
        if not isinstance(raw, dict):
            continue
        src = str(raw.get("source") or "")
        title = _match_title(raw)
        if _is_planning_manual(src, title):
            rejected_planning.append(
                {
                    "source": src,
                    "title": title,
                    "reason": "planning_manual_insufficient_for_wiring_intent"
                    if query_intent in {"wiring_schematic", "fta_connection"}
                    else "planning_manual_demoted_for_honeywell_part_lookup",
                }
            )
    if is_specification_number_request(retrieval_msg):
        matches = prioritize_gp_brewton_spec_matches(matches, retrieval_msg)
        # A spec-number request needs the governing identity, not a long list
        # of generic handbooks that happened to rank nearby.
        if matches:
            matches = matches[:1]
    # Exact Honeywell part-number index hits: keep the canonical exact PDF only.
    # Apply vendor/kind gates before truncating so an unrelated corpus hit
    # (e.g. Allen-Bradley knowledgebase xlsx) cannot displace the Honeywell manual.
    if _HW_PART.search(retrieval_msg):
        if validated_part:
            for m in matches:
                if isinstance(m, dict) and not m.get("part_number"):
                    m["part_number"] = validated_part
        manual, index = select_operator_document_match(matches, query=retrieval_msg)
        gated: list[dict[str, Any]] = []
        if isinstance(manual, dict):
            gated.append(manual)
        if isinstance(index, dict) and index is not manual:
            gated.append(index)
        if gated:
            matches = gated
        exact = [
            m
            for m in matches
            if isinstance(m, dict) and str(m.get("match_kind") or "") == "exact"
        ]
        if exact:
            matches = exact[:1]
        elif matches:
            matches = matches[:1]
    reply, pending = build_operator_document_reply(
        matches, query=retrieval_msg, public_origin=origin
    )
    active_out = active_document_from_matches(
        matches, query=retrieval_msg, public_origin=origin
    )
    if validated_part and isinstance(active_out, dict) and active_out.get("source"):
        active_out = dict(active_out)
        active_out["part_number"] = validated_part
        active_out["part_identity_source"] = part_identity_source
    elif (
        validated_part
        and query_intent in {"wiring_schematic", "fta_connection"}
        and _HW_PART.search(validated_part)
    ):
        existing = dict(active_out) if isinstance(active_out, dict) else {}
        existing["part_number"] = validated_part
        existing["part_identity_source"] = part_identity_source
        active_out = existing
    if pending and isinstance(active_out, dict) and active_out.get("source"):
        # Bind the offered follow-up to the exact active manual shown to the operator.
        pending = dict(pending)
        pending["source"] = str(active_out.get("source") or pending.get("source") or "")
        pending["title"] = str(active_out.get("title") or pending.get("title") or "")
        if active_out.get("part_number"):
            pending["part_number"] = active_out.get("part_number")
        if active_out.get("doc_no") or active_out.get("revision"):
            pending["doc_no"] = active_out.get("doc_no") or active_out.get("revision")
        active_out = dict(active_out)
        active_out["pending_action"] = pending
    # Hard fail-closed: never leave LAN/loopback corpus URLs in the emitted reply.
    reply = neutralize_lan_url_text(reply, public_origin=origin)
    assert "192.168.0.15:8789" not in reply
    assert "127.0.0.1:8789" not in reply
    assert "localhost:8789" not in reply
    assert "lan_url" not in reply.lower()
    spoken = build_compact_spoken_document_reply(matches, query=retrieval_msg)
    # Compact spoken is already TTS-safe prose; do not re-run chrome strippers that
    # can mangle part numbers / document identities.
    spoken = re.sub(r"\s+", " ", str(spoken or "")).strip()
    receipt = build_retrieval_receipt(matches, query=retrieval_msg)
    receipt["query_intent"] = query_intent
    receipt["part_identity_source"] = part_identity_source
    receipt["validated_part"] = validated_part or None
    receipt["rejected_planning"] = rejected_planning
    terminal_status = "document_match" if matches else "no_match"
    reply_l = (reply or "").lower()
    if query_intent in {"wiring_schematic", "fta_connection"}:
        if "cannot yet verify" in reply_l or "no authoritative schematic" in reply_l:
            terminal_status = "evidence_unavailable"
            spoken = (
                "No verified wiring or FTA connection diagram was found. "
                "I will not substitute a planning manual."
            )
        elif "figure" in reply_l and "connection diagram" in reply_l:
            terminal_status = "wiring_packet"
            figs = []
            for m in matches:
                if isinstance(m, dict) and isinstance(m.get("figures"), list):
                    figs.extend(m.get("figures") or [])
            if figs:
                f0 = figs[0]
                spoken = compact_fta_connection_spoken(
                    validated_part or part_identity_source,
                    f0.get("figure"),
                    f0.get("printed_page"),
                ) or (
                    f"Verified FTA connection diagram for {validated_part or part_identity_source}, "
                    f"figure {f0.get('figure')}."
                )
            else:
                spoken = re.sub(r"\s+", " ", sanitize_for_spoken_output(reply)).strip()
    receipt["terminal_status"] = terminal_status
    return {
        "handled": True,
        "query": msg,
        "reply": reply,
        "spoken_reply": spoken,
        "matches": matches,
        "collection": payload.get("collection") or "",
        "active_document": active_out if active_out else None,
        "pending_action": pending,
        "retrieval": payload.get("retrieval") or "",
        "retrieval_receipt": receipt,
        "query_intent": query_intent,
        "part_identity_source": part_identity_source,
        "validated_part": validated_part or None,
        "rejected_planning": rejected_planning,
        "terminal_status": terminal_status,
        # Distinguishes a deliberate new-document ask (safe to clear a stale
        # binding on no match) from a heuristic-only is_document_request()
        # false-positive that named no document at all (must not clobber a
        # valid existing active_document just because this turn found nothing).
        "has_explicit_identity": _has_explicit_document_identity_token(msg),
        "error": None,
    }


def maybe_rewrite_sidecar_rag_json(
    extension_id: object,
    proxy_path: object,
    body: bytes,
    content_type: object = "",
    *,
    public_origin: object = "",
) -> bytes:
    """Neutralize lan_url fields on smedley-engineering RAG JSON proxy responses."""
    if str(extension_id or "") != "smedley-engineering":
        return body
    path = str(proxy_path or "").lstrip("/")
    if not (path == "rag/retrieve" or path.startswith("rag/")):
        return body
    ctype = str(content_type or "").lower()
    if ctype and "json" not in ctype and "text/" not in ctype and "octet-stream" not in ctype:
        # Unknown binary — leave alone.
        if not body[:1] in (b"{", b"["):
            return body
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return body
    if not isinstance(payload, dict) or "matches" not in payload:
        return body
    rewritten = neutralize_retrieve_payload(
        payload, public_origin=normalize_public_origin(public_origin)
    )
    return json.dumps(rewritten, ensure_ascii=False).encode("utf-8")
