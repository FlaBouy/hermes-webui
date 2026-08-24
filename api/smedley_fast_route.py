"""Deterministic Smedley fast routes — before the general agent/tool loop.

Physical glass is truth. Feeds, n8n, browser DOM, APIs, and files are not
proof of the primary display. Greetings and short operator acknowledgements
must not open skills/terminal/web/n8n/browser/workspace. Explicit service
health may make one allowlisted loopback health GET, then stop.
"""

from __future__ import annotations

import os
import re
import urllib.error
import urllib.request
from typing import Any, Callable

HEALTH_TIMEOUT_S = 2.0
DEFAULT_HEALTH_URL = "http://127.0.0.1:8787/health"
ALLOWED_HEALTH_URLS = frozenset(
    {
        "http://127.0.0.1:8787/health",
        "http://localhost:8787/health",
    }
)
PHYSICAL_GLASS_VERIFIER_ENV = "SMEDLEY_PHYSICAL_GLASS_VERIFIER"

GLASS_UNAVAILABLE_REPLY = (
    "I cannot verify the primary physical glass from this session. "
    "Feeds, n8n, browser DOM, APIs, and files are not proof of what is on "
    "that display, so I will not search them."
)
GREETING_REPLY = "Morning. Standing by."
STATUS_ACK_REPLY = "I'm here. I did not run a service discovery sweep."
HEALTH_UNAVAILABLE_REPLY = (
    "Smedley service health is unavailable. I will not search n8n, the "
    "browser, or the filesystem for a substitute."
)
INGEST_UNAVAILABLE_REPLY = (
    "The authoritative RAG ingest status is unavailable right now. "
    "I stopped there instead of opening an agent or filesystem search."
)

_GLASS_RE = re.compile(
    r"\b(?:primary\s+glass|physical\s+glass|physical\s+display|"
    r"active\s+cards?\s+(?:are\s+)?on\s+(?:the\s+)?(?:primary\s+)?glass|"
    r"cards?\s+on\s+(?:the\s+)?(?:primary|physical)\s+glass)\b",
    re.IGNORECASE,
)
_HEALTH_RE = re.compile(
    r"\b(?:(?:run|check|show|get)\s+(?:the\s+)?(?:smedley\s+)?"
    r"(?:webui\s+)?(?:service\s+)?health|service\s+health|health\s+check)\b",
    re.IGNORECASE,
)
_WORKSPACE_PREFIX_RE = re.compile(r"^\[Workspace::[^\]]*\]\s*", re.IGNORECASE)
_PTT_WRAP_RE = re.compile(r"\[Voice PTT turn:[^\]]*\]", re.IGNORECASE)
_REPLACEMENT_JUNK_RE = re.compile(r"[\ufffd\u0000-\u0008\u000b\u000c\u000e-\u001f]+")
_FILLER_LEAD_RE = re.compile(
    r"^(?:yeah|yep|yup|ya|ok(?:ay)?|alright|sure|well|so|uh+|um+|hmm+)\b[\s,.:;\-]*",
    re.IGNORECASE,
)
_GREETING_RE = re.compile(
    r"^(?:good\s+)?(?:mornin['g]?|hello|hi|hey)"
    r"(?:[,\s]+(?:smedley|spadley|smedly|rick))?"
    r"[\s,;:]*$",
    re.IGNORECASE,
)
_STATUS_ACK_RE = re.compile(
    r"^(?:"
    r"just\s+checking(?:\s+in)?(?:\s+to\s+see(?:\s+if\s+all\s+systems\s+are\s+"
    r"(?:online|up|ok))?)?|"
    r"(?:are\s+)?you\s+(?:there|ready)|ready|"
    r"all\s+systems\s+(?:online|up)|"
    r"(?:just\s+)?(?:doing\s+)?(?:a\s+)?(?:quick\s+)?systems?\s+check(?:\s+in)?|"
    r"(?:just\s+)?(?:a\s+)?quick\s+(?:systems?\s+)?check(?:[- ]in)?"
    r")$",
    re.IGNORECASE,
)
_ASK_BACKEND_RE = re.compile(r"^\s*ask\s+(?:argus|jarvis)\b", re.IGNORECASE)
_INGEST_STATUS_RE = re.compile(
    r"\b(?:rag\s+)?(?:ingest(?:ion)?|index(?:ing)?)\b.*"
    r"\b(?:status|state|issue|problem|failure|failed|detected|flagged|check)\b|"
    r"\b(?:status|state|issue|problem|failure|failed|detected|flagged|check)\b.*"
    r"\b(?:rag\s+)?(?:ingest(?:ion)?|index(?:ing)?)\b",
    re.IGNORECASE,
)
_INGEST_ACTION_RE = re.compile(
    r"\b(?:re[- ]?ingest|re[- ]?index|retry\s+(?:the\s+)?(?:ingest(?:ion)?|index(?:ing)?)|"
    r"start\s+(?:the\s+)?re[- ]?(?:ingest|index))\b",
    re.IGNORECASE,
)


HealthGetter = Callable[[str, float], dict[str, Any]]
GlassVerifier = Callable[[], dict[str, Any] | None]
IngestStatusGetter = Callable[[], dict[str, Any]]
IngestRetry = Callable[[str], dict[str, Any]]


def _norm(message: object) -> str:
    text = str(message or "")
    text = _PTT_WRAP_RE.sub(" ", text)
    text = _REPLACEMENT_JUNK_RE.sub("", text)
    text = _WORKSPACE_PREFIX_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _ack_key(message: object) -> str:
    """Normalize greetings/check-ins: workspace wrap, fillers, punctuation."""
    msg = _norm(message)
    while True:
        nxt = _FILLER_LEAD_RE.sub("", msg, count=1).strip()
        if nxt == msg:
            break
        msg = nxt
    msg = re.sub(r"[.!?…,;:]+$", "", msg).strip()
    msg = re.sub(r"\s+", " ", msg)
    return msg


def is_primary_glass_request(message: object) -> bool:
    msg = _norm(message)
    if not msg or _ASK_BACKEND_RE.search(msg):
        return False
    return bool(_GLASS_RE.search(msg))


def is_explicit_service_health_request(message: object) -> bool:
    msg = _norm(message)
    if not msg or _ASK_BACKEND_RE.search(msg) or is_primary_glass_request(msg):
        return False
    return bool(_HEALTH_RE.search(msg))


def is_greeting_or_status_ack(message: object) -> bool:
    raw = _norm(message)
    if not raw or len(raw) > 160 or _ASK_BACKEND_RE.search(raw):
        return False
    if is_primary_glass_request(raw) or is_explicit_service_health_request(raw):
        return False
    key = _ack_key(raw)
    if not key:
        return False
    return bool(_GREETING_RE.match(key) or _STATUS_ACK_RE.match(key))


def is_ingest_status_request(message: object) -> bool:
    msg = _norm(message)
    if not msg or _ASK_BACKEND_RE.search(msg):
        return False
    return bool(_INGEST_STATUS_RE.search(msg))


def is_ingest_action_request(message: object) -> bool:
    """Return true only for an affirmative, narrowly scoped ingest retry."""
    msg = _norm(message)
    return bool(msg and _INGEST_ACTION_RE.search(msg))


def physical_glass_verifier_configured(environ: dict[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    return bool(str(env.get(PHYSICAL_GLASS_VERIFIER_ENV) or "").strip())


def allowlisted_health_url(url: object) -> str | None:
    candidate = str(url or "").strip().rstrip("/")
    if candidate in ALLOWED_HEALTH_URLS:
        return candidate
    return None


def _default_health_get(url: str, timeout: float) -> dict[str, Any]:
    allowed = allowlisted_health_url(url)
    if not allowed:
        raise ValueError("health url is not allowlisted")
    req = urllib.request.Request(allowed, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read(4096)
        status = int(getattr(resp, "status", 0) or 0)
    text = body.decode("utf-8", "replace")
    return {"http_status": status, "body": text}


def _result(
    *,
    route: str,
    reply: str,
    tool_calls: int,
    provider_calls: int,
    health_url: str | None = None,
) -> dict[str, Any]:
    spoken = reply
    try:
        from api.smedley_document_route import spoken_text_for_gateway_reply

        spoken = spoken_text_for_gateway_reply(reply) or reply
    except Exception:
        spoken = reply
    return {
        "handled": True,
        "route": route,
        "reply": reply,
        "spoken_text": spoken,
        "spoken_reply": spoken,
        "tool_calls": int(tool_calls),
        "provider_calls": int(provider_calls),
        "health_url": health_url,
        "error": None,
    }


def _glass_route(
    *,
    glass_verifier: GlassVerifier | None,
    environ: dict[str, str] | None,
) -> dict[str, Any]:
    if glass_verifier is None and not physical_glass_verifier_configured(environ):
        return _result(
            route="primary_glass",
            reply=GLASS_UNAVAILABLE_REPLY,
            tool_calls=0,
            provider_calls=0,
        )
    # A configured verifier is still not a substitute discovery path. One
    # call, then stop. No n8n/browser/filesystem fallback.
    if glass_verifier is None:
        return _result(
            route="primary_glass",
            reply=GLASS_UNAVAILABLE_REPLY,
            tool_calls=0,
            provider_calls=0,
        )
    try:
        observed = glass_verifier()
    except Exception:
        observed = None
    if not isinstance(observed, dict) or not observed.get("verified_physical"):
        return _result(
            route="primary_glass",
            reply=GLASS_UNAVAILABLE_REPLY,
            tool_calls=0,
            provider_calls=1,
        )
    cards = str(observed.get("active_cards") or "").strip()
    reply = cards or GLASS_UNAVAILABLE_REPLY
    return _result(
        route="primary_glass",
        reply=reply,
        tool_calls=0,
        provider_calls=1,
    )


def _health_route(*, health_get: HealthGetter | None) -> dict[str, Any]:
    getter = health_get or _default_health_get
    url = DEFAULT_HEALTH_URL
    if allowlisted_health_url(url) is None:
        return _result(
            route="service_health",
            reply=HEALTH_UNAVAILABLE_REPLY,
            tool_calls=0,
            provider_calls=0,
        )
    try:
        payload = getter(url, HEALTH_TIMEOUT_S)
    except Exception:
        return _result(
            route="service_health",
            reply=HEALTH_UNAVAILABLE_REPLY,
            tool_calls=0,
            provider_calls=1,
            health_url=url,
        )
    status = ""
    http_status = None
    if isinstance(payload, dict):
        http_status = payload.get("http_status")
        body = payload.get("body")
        if isinstance(body, str) and '"status"' in body:
            m = re.search(r'"status"\s*:\s*"([^"]+)"', body)
            if m:
                status = m.group(1)
        elif isinstance(payload.get("status"), str):
            status = str(payload.get("status") or "")
    if http_status not in (None, 200) and not status:
        return _result(
            route="service_health",
            reply=HEALTH_UNAVAILABLE_REPLY,
            tool_calls=0,
            provider_calls=1,
            health_url=url,
        )
    label = status or "ok"
    return _result(
        route="service_health",
        reply=f"Smedley WebUI health: {label}.",
        tool_calls=0,
        provider_calls=1,
        health_url=url,
    )


def _default_ingest_status_get() -> dict[str, Any]:
    from api.jarvis_v6_world import ingest_status

    return ingest_status()


def _default_ingest_retry(source: str) -> dict[str, Any]:
    from api.jarvis_v6_world import retry_ingest_source

    return retry_ingest_source(source)


def _ingest_attention_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("recent")
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        state = str(row.get("state") or "").strip().lower()
        phase = str(row.get("phase") or "").strip().lower()
        reason = str(row.get("reason") or "").strip()
        if reason or state not in {"complete", "completed", "indexed"} or phase not in {
            "complete",
            "completed",
            "indexed",
        }:
            out.append(row)
    return out


def _ingest_row_for_message(message: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    rows = [r for r in (payload.get("recent") or []) if isinstance(r, dict)]
    folded = message.casefold()
    attention = _ingest_attention_rows(payload)
    # When the operator explicitly asks about a detected/failed item, prefer
    # the one ledger row needing attention over a shorter completed filename
    # that happens to be a suffix of the requested name.
    if len(attention) == 1 and re.search(
        r"\b(?:issue|problem|failure|failed|detected|flagged)\b", folded
    ):
        return attention[0]
    matches = []
    for row in rows:
        name = str(row.get("file") or "").strip()
        if name and name.casefold() in folded:
            matches.append(row)
    if len(matches) == 1:
        return matches[0]
    if len(attention) == 1:
        return attention[0]
    return None


def _ingest_status_route(
    message: str,
    *,
    ingest_status_get: IngestStatusGetter | None,
) -> dict[str, Any]:
    getter = ingest_status_get or _default_ingest_status_get
    try:
        payload = getter()
    except Exception:
        return _result(
            route="ingest_status",
            reply=INGEST_UNAVAILABLE_REPLY,
            tool_calls=0,
            provider_calls=1,
        )
    if not isinstance(payload, dict) or payload.get("ok") is False:
        return _result(
            route="ingest_status",
            reply=INGEST_UNAVAILABLE_REPLY,
            tool_calls=0,
            provider_calls=1,
        )

    row = _ingest_row_for_message(message, payload)
    monitor = "online" if payload.get("monitor_online") else "reconnecting"
    if row:
        name = str(row.get("file") or row.get("source") or "The file").strip()
        phase = str(row.get("phase") or row.get("state") or "unknown").strip().lower()
        reason = str(row.get("reason") or "").strip()
        if phase in {"complete", "completed", "indexed"}:
            reply = f"{name} is indexed. The ingest monitor is {monitor}."
        else:
            detail = f" Reason: {reason}." if reason else ""
            reply = (
                f"{name} is {phase}. The ingest monitor is {monitor}.{detail} "
                "Use its Ingest Radar item to re-ingest or disposition it."
            )
    else:
        attention = _ingest_attention_rows(payload)
        state = str(payload.get("phase") or payload.get("state") or "unknown").strip().lower()
        if attention:
            names = ", ".join(
                str(r.get("file") or r.get("source") or "unnamed item") for r in attention[:3]
            )
            reply = (
                f"The ingest monitor is {monitor}; {len(attention)} recent item"
                f"{'s need' if len(attention) != 1 else ' needs'} attention: {names}. "
                "Use the Ingest Radar items to re-ingest or disposition them."
            )
        else:
            reply = f"The ingest monitor is {monitor}; current state is {state}."
    return _result(
        route="ingest_status",
        reply=reply,
        tool_calls=0,
        provider_calls=1,
    )


def _ingest_action_route(
    message: str,
    *,
    ingest_status_get: IngestStatusGetter | None,
    ingest_retry: IngestRetry | None,
) -> dict[str, Any]:
    """Resolve and queue exactly one known ledger row, then stop.

    This path intentionally bypasses Biggy's general agent loop.  It performs
    one status lookup and, only when one source is unambiguous, one bounded
    retry call.  Every outcome is terminal so the composer cannot remain hot.
    """
    getter = ingest_status_get or _default_ingest_status_get
    retry = ingest_retry or _default_ingest_retry
    try:
        payload = getter()
    except Exception:
        return _result(
            route="ingest_action",
            reply=INGEST_UNAVAILABLE_REPLY,
            tool_calls=0,
            provider_calls=1,
        )
    if not isinstance(payload, dict) or payload.get("ok") is False:
        return _result(
            route="ingest_action",
            reply=INGEST_UNAVAILABLE_REPLY,
            tool_calls=0,
            provider_calls=1,
        )

    row = _ingest_row_for_message(message, payload)
    source = str((row or {}).get("source") or "").strip()
    if not source:
        return _result(
            route="ingest_action",
            reply="Tell me which file to re-ingest, or select it in the Ingest Radar.",
            tool_calls=0,
            provider_calls=1,
        )
    name = str((row or {}).get("file") or source).strip()
    try:
        result = retry(source)
    except Exception as exc:
        reason = str(exc).strip() or "the ingest service rejected the request"
        return _result(
            route="ingest_action",
            reply=f"I could not queue {name}: {reason}.",
            tool_calls=0,
            provider_calls=2,
        )
    if not isinstance(result, dict) or result.get("ok") is False:
        return _result(
            route="ingest_action",
            reply=f"I could not queue {name}. The request stopped cleanly.",
            tool_calls=0,
            provider_calls=2,
        )
    state = str(result.get("state") or result.get("status") or "queued").strip().lower()
    if state in {"indexed", "indexed_via_sidecar"}:
        reply = f"{name} is already indexed; I did not queue a duplicate pass."
    elif state == "duplicate":
        reply = (
            f"{name} matches content already indexed under another library name. "
            "I reconciled the duplicate and did not grind the same document again."
        )
    else:
        reply = f"{name} re-ingest is queued. The ingest watcher owns it now."
    return _result(
        route="ingest_action",
        reply=reply,
        tool_calls=0,
        provider_calls=2,
    )


def try_smedley_fast_route(
    message: object,
    *,
    health_get: HealthGetter | None = None,
    glass_verifier: GlassVerifier | None = None,
    ingest_status_get: IngestStatusGetter | None = None,
    ingest_retry: IngestRetry | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Return a handled fast-route payload, or None for ordinary agent/RAG."""
    msg = _norm(message)
    if not msg:
        return None
    if is_primary_glass_request(msg):
        return _glass_route(glass_verifier=glass_verifier, environ=environ)
    if is_explicit_service_health_request(msg):
        return _health_route(health_get=health_get)
    if is_ingest_action_request(msg):
        return _ingest_action_route(
            msg,
            ingest_status_get=ingest_status_get,
            ingest_retry=ingest_retry,
        )
    if is_ingest_status_request(msg):
        return _ingest_status_route(msg, ingest_status_get=ingest_status_get)
    if is_greeting_or_status_ack(msg):
        key = _ack_key(msg)
        reply = GREETING_REPLY if _GREETING_RE.match(key) else STATUS_ACK_REPLY
        return _result(
            route="greeting_or_status",
            reply=reply,
            tool_calls=0,
            provider_calls=0,
        )
    return None
