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
_ASK_JARVIS_RE = re.compile(r"^\s*ask\s+jarvis\b", re.IGNORECASE)


HealthGetter = Callable[[str, float], dict[str, Any]]
GlassVerifier = Callable[[], dict[str, Any] | None]


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
    if not msg or _ASK_JARVIS_RE.search(msg):
        return False
    return bool(_GLASS_RE.search(msg))


def is_explicit_service_health_request(message: object) -> bool:
    msg = _norm(message)
    if not msg or _ASK_JARVIS_RE.search(msg) or is_primary_glass_request(msg):
        return False
    return bool(_HEALTH_RE.search(msg))


def is_greeting_or_status_ack(message: object) -> bool:
    raw = _norm(message)
    if not raw or len(raw) > 160 or _ASK_JARVIS_RE.search(raw):
        return False
    if is_primary_glass_request(raw) or is_explicit_service_health_request(raw):
        return False
    key = _ack_key(raw)
    if not key:
        return False
    return bool(_GREETING_RE.match(key) or _STATUS_ACK_RE.match(key))


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


def try_smedley_fast_route(
    message: object,
    *,
    health_get: HealthGetter | None = None,
    glass_verifier: GlassVerifier | None = None,
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
