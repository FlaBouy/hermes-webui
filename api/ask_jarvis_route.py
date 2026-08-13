"""Hard-bind explicit leading ``Ask Jarvis:`` to Jarvis PA briefing webhook.

Bypasses LLM soft tool selection and native file/RAG. Invokes the Biggy
profile ``ask_jarvis.py`` skill script (authenticated local briefing webhook)
and returns its cited answer for the same chat turn.

Splits presentation at this renderer only:
  - spoken_text / spoken_reply → natural answer for TTS/PTT
  - evidence_footer → kept empty for chat (no Citations/receipt on screen); citations stay structured on payload
  - reply → spoken answer only (no citation footer)

Gated by callers. Does not mutate kanban / Owner-ACK / queue.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

_ASK_JARVIS_LEADING = re.compile(r"^\s*ask\s+jarvis\s*:\s*", re.IGNORECASE)
# Conversational Biggy/PTT forms, including past-tense STT:
# "Ask Jarvis to …" / "I asked Jarvis to …" / "asking Jarvis for …" / "tell Jarvis to …"
_ASK_JARVIS_EMBEDDED = re.compile(
    r"(?i)(?:^|[\s,;])(?:ask(?:ed|ing)?|tell|have)\s+jarvis\b(?:\s*:|\s+to\b|\s+for\b)"
)
# Role/meta talk about Ask Jarvis without a concrete travel/task handoff.
_ASK_JARVIS_META_ROLE = re.compile(
    r"(?i)\b(?:you will|you'll|biggy(?:'s)? role|point\s*3|number\s*3|conduit|hand(?:ing)?\s+(?:the\s+)?prompt)\b.*\bask(?:ed|ing)?\s+jarvis\b"
    r"|\bask(?:ed|ing)?\s+jarvis\b.*\b(?:speak to me directly|using his own voice|respond to my ask)\b"
)

# Strip citation / receipt tails from Jarvis speak for TTS only — do not alter routing.
_CITATION_SPLIT = re.compile(
    r"(?:\n\s*)?(?:\*\*Citations?\*\*|Citations?)\s*[:：].*\Z",
    re.IGNORECASE | re.DOTALL,
)
_RECEIPT_SPLIT = re.compile(
    r"(?:\n\s*)?\[Jarvis receipt:[^\]]*\]\s*\Z",
    re.IGNORECASE | re.DOTALL,
)
_INLINE_SOURCE = re.compile(r"\s*\(sources?:\s*[^)]+\)", re.IGNORECASE)
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_BARE_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_BARE_HOSTNAME = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|org|net|edu|gov|io|info)\b", re.IGNORECASE)
_BRACKET_META = re.compile(
    r"\[(?:Jarvis receipt:[^\]]*|citation[^\]]*|source[^\]]*|map_view_model[^\]]*)\]",
    re.IGNORECASE,
)
_JSONISH = re.compile(r"\{[^{}]{0,400}\"(?:schema|map_view_model|coordinates)\"[^{}]{0,800}\}")
_CITATION_INLINE = re.compile(r"(?:^|\s)Citations?\s*[:：]\s*.+$", re.IGNORECASE | re.MULTILINE)

_ASK_JARVIS_SCRIPT = Path(
    "/Users/rick/.hermes/profiles/biggy/skills/governance/ask-jarvis/scripts/ask_jarvis.py"
)

# Ask Jarvis hard-bind spoken TTS only (James Michael). Biggy PTT default
# remains Austin via ~/.hermes/config.yaml tts.elevenlabs.voice_id.
# Credential remains ELEVENLABS_API_KEY in env — never embedded here.
_JARVIS_ELEVENLABS_VOICE_ID = "dzRy05hNK3bab9ViJ0oU"
_JARVIS_TTS_ENGINE = "elevenlabs"
_SMEDLEY_SPEAK_URL = "http://127.0.0.1:5004/speak"
_TIMING_DIR = Path("/Users/rick/jarvis-n8n/validation/ask-jarvis-timing")

# Biggy default Austin (Hermes config.yaml tts.elevenlabs.voice_id). Ack only.
_AUSTIN_VOICE_ID = "Bj9UqZbhQsanLzgalpEG"
_ACK_SPOKEN_TEXT = "On it. I'm getting Jarvis on that."
_PENDING_VISUAL = "Working with Jarvis…"

import threading as _threading
_TTS_ONCE_LOCK = _threading.Lock()
_ACK_ONCE: set[str] = set()
_FINAL_ONCE: set[str] = set()
_POST_ACK_ONCE: set[str] = set()
_ACK_DONE: dict[str, _threading.Event] = {}
_ACK_DONE_AT: dict[str, float] = {}
_FINAL_DONE: dict[str, _threading.Event] = {}
_FINAL_DONE_AT: dict[str, float] = {}


def mint_correlation_id() -> str:
    return f"biggy-ask-jarvis-{time.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"


def ack_spoken_text() -> str:
    return _ACK_SPOKEN_TEXT


def austin_voice_id() -> str:
    return _AUSTIN_VOICE_ID


def pending_visual_text() -> str:
    return _PENDING_VISUAL


def _utc(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts if ts is not None else time.time()))


def _ms(a: float, b: float) -> int:
    return int(round((b - a) * 1000))


def timing_path_for(correlation_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(correlation_id))[:120]
    return _TIMING_DIR / f"{safe}.json"


def _merge_timing(timing_path: Path | None, correlation_id: str | None, patch: dict[str, Any]) -> None:
    if not timing_path or not correlation_id:
        return
    try:
        timing_path.parent.mkdir(parents=True, exist_ok=True)
        prev: dict[str, Any] = {}
        if timing_path.is_file():
            try:
                prev = json.loads(timing_path.read_text(encoding="utf-8"))
            except Exception:
                prev = {}
        ts = dict(prev.get("timestamps_utc") or {})
        segs = dict(prev.get("segments_ms") or {})
        ts.update(dict((patch.get("timestamps_utc") or {})))
        segs.update(dict((patch.get("segments_ms") or {})))
        prev.update(patch)
        prev["schema"] = "jarvis.ask_jarvis_correlation_timing.v1"
        prev["correlation_id"] = correlation_id
        prev["timestamps_utc"] = ts
        prev["segments_ms"] = segs
        timing_path.write_text(json.dumps(prev, indent=2) + "\n", encoding="utf-8")
    except Exception:
        logger.exception("ask_jarvis timing merge failed")


def _ack_event(correlation_id: str) -> _threading.Event:
    corr = str(correlation_id or "").strip()
    with _TTS_ONCE_LOCK:
        ev = _ACK_DONE.get(corr)
        if ev is None:
            ev = _threading.Event()
            _ACK_DONE[corr] = ev
        return ev


def mark_ack_playback_complete(correlation_id: str, *, at: float | None = None) -> float:
    """Signal Austin ack playback finished for correlation (release gate)."""
    corr = str(correlation_id or "").strip()
    ts = float(at if at is not None else time.time())
    with _TTS_ONCE_LOCK:
        _ACK_DONE_AT[corr] = ts
    _ack_event(corr).set()
    return ts


def wait_ack_playback_complete(
    correlation_id: str, *, timeout_s: float = 120.0
) -> dict[str, Any]:
    """Block until Austin ack playback completes for correlation (real signal)."""
    corr = str(correlation_id or "").strip()
    ev = _ack_event(corr)
    t0 = time.time()
    ok = ev.wait(timeout=max(1.0, float(timeout_s or 120.0)))
    waited_ms = _ms(t0, time.time())
    at = _ACK_DONE_AT.get(corr)
    return {
        "ok": bool(ok),
        "correlation_id": corr,
        "ack_complete_at": at,
        "ack_complete_utc": _utc(at) if at else None,
        "waited_ms": waited_ms,
        "timed_out": not ok,
    }


def _final_event(correlation_id: str) -> _threading.Event:
    corr = str(correlation_id or "").strip()
    with _TTS_ONCE_LOCK:
        ev = _FINAL_DONE.get(corr)
        if ev is None:
            ev = _threading.Event()
            _FINAL_DONE[corr] = ev
        return ev


def mark_final_playback_complete(correlation_id: str, *, at: float | None = None) -> float:
    """Signal compact final TTS playback finished (gates post-ack visual line)."""
    corr = str(correlation_id or "").strip()
    ts = float(at if at is not None else time.time())
    with _TTS_ONCE_LOCK:
        _FINAL_DONE_AT[corr] = ts
    _final_event(corr).set()
    return ts


def wait_final_playback_complete(
    correlation_id: str, *, timeout_s: float = 180.0
) -> dict[str, Any]:
    """Block until compact final TTS playback completes for correlation."""
    corr = str(correlation_id or "").strip()
    ev = _final_event(corr)
    t0 = time.time()
    ok = ev.wait(timeout=max(1.0, float(timeout_s or 180.0)))
    waited_ms = _ms(t0, time.time())
    at = _FINAL_DONE_AT.get(corr)
    return {
        "ok": bool(ok),
        "correlation_id": corr,
        "final_complete_at": at,
        "final_complete_utc": _utc(at) if at else None,
        "waited_ms": waited_ms,
        "timed_out": not ok,
    }


def _queue_smedley_speak(
    spoken_text: str,
    *,
    voice_id: str,
    voice_name: str,
    role: str,
    correlation_id: str | None = None,
    timing_path: Path | None = None,
    delay_s: float = 0.0,
    once_set: set[str] | None = None,
    wait_complete: bool = False,
    wait_final_before_speak: bool = False,
) -> dict[str, Any]:
    """Queue one Smedley /speak. Optional once_set enforces single fire per correlation.

    When wait_complete=True, /speak blocks until playback finishes (ack/final gate).
    When wait_final_before_speak=True, block until compact final playback completes.
    """
    import urllib.request

    spoken = str(spoken_text or "").strip()
    if not spoken:
        return {"queued": False, "reason": "empty_spoken_text", "role": role}
    corr = str(correlation_id or "").strip() or None
    if role == "ack" and corr:
        _ack_event(corr)  # ensure waiters can block before thread starts
    if role == "final" and corr:
        _final_event(corr)  # ensure post-ack can wait before final thread starts
    if once_set is not None and corr:
        with _TTS_ONCE_LOCK:
            if corr in once_set:
                return {
                    "queued": False,
                    "reason": "already_fired",
                    "role": role,
                    "correlation_id": corr,
                    "duplicate_prevented": True,
                }
            once_set.add(corr)

    vid = str(voice_id or "").strip()
    # Hard cap avoids truncation mid-sentence in compact travel TTS (short by design).
    spoken_dispatch = spoken[:800]
    body_obj: dict[str, Any] = {"text": spoken_dispatch, "voice_id": vid}
    if wait_complete:
        body_obj["wait"] = True
    payload = json.dumps(body_obj).encode("utf-8")
    t_queue = time.time()
    t_queue_utc = _utc(t_queue)
    delay = max(0.0, float(delay_s or 0.0))
    # Playback wait can take tens of seconds; this is real completion, not a timer.
    http_timeout = 180 if wait_complete else 5

    def _run() -> None:
        speak_http_ms = None
        speak_err = None
        t_http_start = None
        t_http_end = None
        playback_complete_at = None
        final_gate = None
        try:
            if wait_final_before_speak and corr:
                final_gate = wait_final_playback_complete(corr, timeout_s=180.0)
                if final_gate.get("timed_out"):
                    logger.warning(
                        "ask_jarvis post-ack waited for final TTS timeout corr=%s",
                        corr,
                    )
            if delay:
                time.sleep(delay)
            t_http_start = time.time()
            req = urllib.request.Request(
                _SMEDLEY_SPEAK_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=http_timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            t_http_end = time.time()
            speak_http_ms = _ms(t_http_start, t_http_end)
            if wait_complete:
                playback_complete_at = t_http_end
            logger.info(
                "ask_jarvis Smedley TTS role=%s voice=%s wait=%s status=%s body=%s",
                role,
                vid,
                wait_complete,
                getattr(resp, "status", None) or 200,
                body[:120],
            )
        except Exception as exc:  # noqa: BLE001
            speak_err = f"{type(exc).__name__}: {exc}"
            logger.exception("ask_jarvis Smedley TTS role=%s failed", role)
            t_http_end = time.time()
            if wait_complete:
                playback_complete_at = t_http_end
        prefix = "ack" if role == "ack" else ("post_ack" if role == "post_ack_visual" else "final")
        patch: dict[str, Any] = {
            "timestamps_utc": {
                f"{prefix}_tts_queue_start": t_queue_utc,
                f"{prefix}_tts_speak_http_start": _utc(t_http_start) if t_http_start else None,
                f"{prefix}_tts_speak_http_end": _utc(t_http_end) if t_http_end else None,
            },
            "segments_ms": {
                f"{prefix}_tts_dispatch_delay_ms": int(round(delay * 1000)),
                f"{prefix}_tts_speak_http_ms": speak_http_ms,
                f"{prefix}_tts_queue_to_speak_http_end_ms": (
                    _ms(t_queue, t_http_end) if t_http_end else None
                ),
            },
            f"tts_{prefix}": {
                "queued": speak_err is None,
                "voice_id": vid,
                "voice_name": voice_name,
                "role": role,
                "wait_complete": wait_complete,
                "wait_final_before_speak": bool(wait_final_before_speak),
                "error": speak_err,
                "text": spoken_dispatch,
                "text_prefix": spoken_dispatch[:80],
                "text_len": len(spoken_dispatch),
                "truncated": len(spoken_dispatch) < len(spoken),
            },
        }
        if final_gate is not None:
            patch["final_release_gate"] = final_gate
            if final_gate.get("final_complete_utc"):
                patch["timestamps_utc"]["final_playback_complete"] = final_gate.get(
                    "final_complete_utc"
                )
            if t_http_start and final_gate.get("final_complete_at"):
                patch["segments_ms"]["final_complete_to_post_ack_speak_ms"] = _ms(
                    float(final_gate["final_complete_at"]), t_http_start
                )
        if role == "ack" and corr:
            done_at = mark_ack_playback_complete(corr, at=playback_complete_at or time.time())
            patch["timestamps_utc"]["ack_playback_complete"] = _utc(done_at)
            patch["segments_ms"]["ack_playback_wall_ms"] = (
                _ms(t_http_start, done_at) if t_http_start else None
            )
        if role == "final" and corr:
            done_at = mark_final_playback_complete(
                corr, at=playback_complete_at or time.time()
            )
            patch["timestamps_utc"]["final_playback_complete"] = _utc(done_at)
            patch["segments_ms"]["final_playback_wall_ms"] = (
                _ms(t_http_start, done_at) if t_http_start else None
            )
        _merge_timing(timing_path, corr, patch)

    _threading.Thread(target=_run, daemon=True, name=f"ask-jarvis-tts-{role}").start()
    return {
        "queued": True,
        "delayed_s": delay,
        "voice_id": vid,
        "voice_name": voice_name,
        "role": role,
        "wait_complete": wait_complete,
        "wait_final_before_speak": bool(wait_final_before_speak),
        "correlation_id": corr,
        "duplicate_prevented": False,
        "text": spoken_dispatch,
        "timestamps_utc": {f"{role}_tts_queue_start": t_queue_utc},
        "segments_ms": {f"{role}_tts_dispatch_delay_ms": int(round(delay * 1000))},
    }


def queue_biggy_austin_ack(
    *,
    correlation_id: str,
    timing_path: Path | None = None,
) -> dict[str, Any]:
    """Immediate Austin acknowledgement — once per correlation. Does not start Jarvis.

    Speaks with wait_complete so playback completion can gate final release.
    """
    return _queue_smedley_speak(
        _ACK_SPOKEN_TEXT,
        voice_id=_AUSTIN_VOICE_ID,
        voice_name="Austin",
        role="ack",
        correlation_id=correlation_id,
        timing_path=timing_path,
        delay_s=0.0,
        once_set=_ACK_ONCE,
        wait_complete=True,
    )


def queue_ask_jarvis_smedley_tts(
    spoken_text: str,
    *,
    voice_id: str | None = None,
    correlation_id: str | None = None,
    timing_path: Path | None = None,
    delay_s: float = 0.0,
) -> dict[str, Any]:
    """Queue Ask Jarvis final spoken_text as James Michael — once per correlation.

    ``speak_async`` on Smedley stops any in-flight Austin ack when this fires.
    Prose must already be sanitized by caller. No Agent/tool changes here.
    wait_complete=True so compact final finishes before post-ack visual line.
    """
    return _queue_smedley_speak(
        spoken_text,
        voice_id=str(voice_id or _JARVIS_ELEVENLABS_VOICE_ID),
        voice_name="James Michael",
        role="final",
        correlation_id=correlation_id,
        timing_path=timing_path,
        delay_s=delay_s,
        once_set=_FINAL_ONCE,
        wait_complete=True,
    )


def is_ask_jarvis_command(message: str) -> bool:
    msg = str(message or "")
    if not (_ASK_JARVIS_LEADING.match(msg) or _ASK_JARVIS_EMBEDDED.search(msg)):
        return False
    # Keep role-definition chatter on the agent; do not hard-bind empty meta prompts.
    if _ASK_JARVIS_META_ROLE.search(msg) and not re.search(
        r"(?i)\b(route|map|travel|drive|lodging|accommodations?|hotel|tickets?|ballpark|stadium|game|weather|calendar|schedule)\b",
        msg,
    ):
        return False
    return True


def _sanitize_spoken_prose(text: str) -> str:
    """Speakable prose only: strip citations, markdown, brackets, URLs, JSON, map metadata."""
    spoken = str(text or "").strip()
    spoken = _RECEIPT_SPLIT.sub("", spoken)
    spoken = _CITATION_SPLIT.sub("", spoken)
    spoken = _CITATION_INLINE.sub("", spoken)
    spoken = _INLINE_SOURCE.sub("", spoken)
    spoken = _BRACKET_META.sub("", spoken)
    spoken = _MD_LINK.sub(r"\1", spoken)
    spoken = _BARE_URL.sub("", spoken)
    spoken = _BARE_HOSTNAME.sub("", spoken)
    spoken = _JSONISH.sub("", spoken)
    # Markdown headings / emphasis — never speak hash markers or bold stars.
    spoken = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", spoken)
    spoken = re.sub(r"[#]{2,}", " ", spoken)
    spoken = re.sub(r"\*+", "", spoken)
    spoken = re.sub(r"`+", "", spoken)
    # Collapse leftover citation host crumbs after "source:" prose
    spoken = re.sub(r"\s*\(source:\s*[^)]*\)", "", spoken, flags=re.IGNORECASE)
    spoken = re.sub(r"[ \t]{2,}", " ", spoken)
    spoken = re.sub(r"\n{3,}", "\n\n", spoken)
    spoken = re.sub(r"\s+", " ", spoken).strip(" \n\t-;,:")
    # Dedupe adjacent/repeated sentences (e.g. "I put. I put lodging…").
    parts = re.split(r"(?<=[.!?])\s+", spoken)
    deduped: list[str] = []
    prev_norm = ""
    for part in parts:
        p = part.strip()
        if not p:
            continue
        norm = re.sub(r"[^a-z0-9]+", "", p.lower())
        if norm and norm == prev_norm:
            continue
        # Also drop a truncated fragment that is a prefix of the next kept sentence.
        if deduped:
            prev = deduped[-1]
            prev_n = re.sub(r"[^a-z0-9]+", "", prev.lower())
            if prev_n and norm.startswith(prev_n) and len(norm) > len(prev_n):
                deduped[-1] = p
                prev_norm = norm
                continue
            if norm and prev_n.startswith(norm) and len(prev_n) > len(norm):
                continue
        deduped.append(p)
        prev_norm = norm
    spoken = " ".join(deduped).strip()
    spoken = re.sub(r"\b(I put\.)\s+(I put\b)", r"\2", spoken, flags=re.IGNORECASE)
    return spoken.strip(" \n\t-;,:")


def _strip_visual_claims(text: str, *, recommendation_category: str | None = None) -> str:
    """Never claim on-screen/map/visuals in TTS without client render acknowledgement.

    Initial hard-bind speak always strips visual claims; client ack is recorded separately.
    Also drop stale lodging language when the requested category is not lodging.
    """
    spoken = str(text or "")
    spoken = re.sub(r"(?i)\bI put[^.!\n]*on the screen\.?\s*", " ", spoken)
    spoken = re.sub(
        r"(?i)\b(on the screen|in the center (?:panel|dialog|map)|map is (?:ready|up|shown)|showing the (?:map|route)|I (?:showed|put) (?:the )?map)\b[.!]?",
        " ",
        spoken,
    )
    cat = (recommendation_category or "").strip().lower()
    if cat and cat != "lodging":
        spoken = re.sub(r"(?i)[^.!\n]*\blodging\b[^.!\n]*[.!?]?", " ", spoken)
        spoken = re.sub(r"(?i)\bhotels?\b options", "options", spoken)
    # Bullet / markdown leftovers for TTS
    spoken = re.sub(r"(?m)^\s*[-•*]\s+", "", spoken)
    spoken = re.sub(r"[#_]+", " ", spoken)
    return _sanitize_spoken_prose(spoken)


_VISUAL_CLAIM_RE = re.compile(
    r"(?i)\b(?:I put[^.!\n]*on the screen\.?|(?:lodging|meal|restaurant|steak house|entertainment|fuel)?\s*options are on the screen\.?)"
)
_REDACTION_RE = re.compile(r"(?:\u2588+|\[(?:redacted|censored|\.\.\.|…)\]|\*{3,}|_{3,})")
_NUMBERED_RESULT_RE = re.compile(r"(?m)^\s*\d+\.\s+")
_REC_ENUM_RE = re.compile(
    r"(?i)\b(?:here are some|regarding dining|steakhouse recommendations?|lodging options|recommended steakhouses?|you can find a list|best steakhouses?)\b[^.!\n]*[.!?]?"
)


def _is_venue_sentence(s: str) -> bool:
    return bool(
        re.search(
            r"(?i)\b(?:venue|stadium|arena|mercedes-benz|takes place|will take place|scheduled for|event (?:is|at)|game (?:is|at)|destination)\b",
            s,
        )
    )


def _is_route_sentence(s: str) -> bool:
    return bool(
        re.search(
            r"(?i)\b(?:route|distance|miles?\b|ETA|estimated travel|travel time|drive|from\b.{0,40}\bto\b)\b",
            s,
        )
    ) and not _is_recommendation_sentence(s)


def _is_calendar_sentence(s: str) -> bool:
    return bool(
        re.search(
            r"(?i)\b(?:schedule conflicts?|calendar|no schedule conflicts?|travel window|no scheduling conflicts?)\b",
            s,
        )
    )


def _is_recommendation_sentence(s: str) -> bool:
    return bool(
        re.search(
            r"(?i)\b(?:steakhouse|steak house|lodging|hotel|motel|yelp|opentable|tripadvisor|dining options|recommended|recommendations?|restaurants? near)\b",
            s,
        )
    ) and not _is_calendar_sentence(s) and not (
        re.search(r"(?i)\b(?:venue|stadium|arena|route|distance|miles|ETA|travel time)\b", s)
        and not re.search(r"(?i)\b(?:yelp|opentable|tripadvisor|here are|recommended)\b", s)
    )


def compact_travel_tts(text: str, *, recommendation_category: str | None = None, lodging_names: list[str] | None = None) -> str:
    """Admit only compact venue + route + calendar prose for initial TTS.

    Never speak card titles, source cues, hostnames, numbered results,
    raw recommendation text, visual claims, or redaction remnants.
    """
    raw = str(text or "")
    raw = _VISUAL_CLAIM_RE.sub(" ", raw)
    raw = _REDACTION_RE.sub(" ", raw)
    raw = _REC_ENUM_RE.sub(" ", raw)
    raw = _BARE_URL.sub("", raw)
    raw = _BARE_HOSTNAME.sub("", raw)
    raw = re.sub(
        r"(?i)\b(?:source confidence|citations?)\s*:\s*(?:High|Medium|Low)?(?:\s*\([^)]{0,120}\))?",
        " ",
        raw,
    )
    raw = re.sub(
        r"(?i)\b(?:This information is\s+)?(?:supported by|sourced from|trusted web|verified through)[^.\n]{0,160}\.?",
        " ",
        raw,
    )
    raw = re.sub(r"(?i)\b(?:yelp|opentable|tripadvisor|espn|ncaa|stubhub|auburntigers)\b", " ", raw)
    raw = re.sub(r"(?i)(?:^|\n)\s*\d+\.\s+[^\n]+", " ", raw)
    raw = re.sub(r"(?i)\b(?:official event page|multiple sources|including the)\b", " ", raw)

    venue = None
    stadium = re.search(
        r"(?i)\b(Mercedes-Benz Stadium|Jordan-Hare Stadium|Bryant-Denny Stadium|[A-Z][A-Za-z0-9\-]{2,40} Stadium|[A-Z][A-Za-z0-9\-]{2,40} Arena)\b",
        raw,
    )
    ev = re.search(r"(?i)\b([A-Za-z]+\s+vs\.?\s+[A-Za-z]+)(?:\s+game)?\b", raw)
    if stadium:
        place = stadium.group(1).strip()
        if ev:
            venue = f"The {ev.group(1).strip()} game is at {place}."
        else:
            venue = f"Venue is {place}."

    route = None
    m_mi = re.search(r"(?i)(\d+(?:\.\d+)?)\s*miles\b", raw)
    m_hm = re.search(
        r"(?i)(?:ETA|estimated travel time|travel time)\D{0,16}(\d+)\s*hours?\s*(?:and\s*)?(\d+)?\s*minutes?",
        raw,
    )
    if not m_hm:
        m_hm = re.search(r"(?i)(\d+)\s*hours?\s*(?:and\s*)?(\d+)\s*minutes?", raw)
    if m_mi:
        mi = m_mi.group(1)
        if m_hm:
            h, mins = m_hm.group(1), m_hm.group(2) or "0"
            if mins and mins != "0":
                route = f"Route is {mi} miles with ETA {h} hours and {mins} minutes."
            else:
                route = f"Route is {mi} miles with ETA {h} hours."
        else:
            route = f"Route is {mi} miles."

    calendar = None
    if re.search(r"(?i)no schedule conflicts|no scheduling conflicts", raw):
        calendar = "No schedule conflicts for the travel window."
    elif re.search(r"(?i)schedule conflicts?", raw):
        calendar = "Schedule conflicts were checked for the travel window."

    dest = None
    m_to = re.search(
        r"(?i)\bto\s+([A-Z][A-Za-z.\-]+(?:\s+[A-Z][A-Za-z.\-]+){0,3}),\s*"
        r"(Alabama|Georgia|Florida|AL|GA|FL|Mississippi|MS|Tennessee|TN)\b",
        raw,
    )
    if m_to and not re.search(r"(?i)lynn\s*haven", m_to.group(1)):
        dest = f"Destination is {m_to.group(1)}, {m_to.group(2)}."
    else:
        for m in re.finditer(
            r"(?i)\b([A-Z][A-Za-z.\-]+(?:\s+[A-Z][A-Za-z.\-]+){0,3}),\s*"
            r"(Alabama|Georgia|Florida|AL|GA|FL|Mississippi|MS|Tennessee|TN)\b",
            raw,
        ):
            if re.search(r"(?i)lynn\s*haven", m.group(1)):
                continue
            dest = f"Destination is {m.group(1)}, {m.group(2)}."
            break

    lodging = None
    preferred = None
    for cand in (lodging_names or []):
        c = re.sub(r"\s+", " ", str(cand or "")).strip()
        c = re.sub(r"&amp;", "&", c, flags=re.I)
        if c and not re.search(r"(?i)\b(?:best hotels|top\s*\d+|hotels in|trivago|tripadvisor)\b", c):
            preferred = c
            break
    if preferred:
        preferred = re.sub(r"(?i)\s*[-–—|]\s*book now\b.*$", "", preferred).strip()
        preferred = re.sub(r"(?i)\s*by choice hotels\b.*$", "", preferred).strip()
        preferred = re.sub(r"[®™©]", "", preferred).strip()
        preferred = re.sub(r"\s+", " ", preferred).strip(" ,.-")
        if preferred:
            lodging = f"{preferred} is a lodging option near the destination."
    m_lodge = re.search(
        r"(?i)\b((?:Best Western|Holiday Inn|Hampton(?: Inn)?|Marriott|Hilton|Hyatt|Courtyard|Residence Inn|Days Inn|Quality Inn)\s+"
        r"[A-Za-z0-9'.\- ]{2,40}?|[A-Z][A-Za-z0-9'.\- ]{2,40}?)\b(?:Inn|Hotel|Motel|Suites|Resort|Lodge)\b",
        raw,
    )
    if not lodging and m_lodge:
        name = re.sub(r"\s+", " ", m_lodge.group(0)).strip(" ,.-")
        name = re.sub(r"(?i)^(may consider the|consider the|the|is the)\s+", "", name).strip()
        if name and not re.search(r"(?i)\b(?:best hotels|top\s*\d+|hotels in)\b", name):
            lodging = f"{name} is a lodging option near the destination."
    elif re.search(
        r"(?i)no (?:local )?accommodations|lodging (?:options )?(?:were )?not (?:identified|confirmed|available)|"
        r"could not find.*(?:lodging|accommodations)|accommodations were not",
        raw,
    ):
        lodging = "Lodging was not confirmed for that window."

    parts = [x for x in (venue, dest, route, calendar, lodging) if x]
    out = _sanitize_spoken_prose(" ".join(parts))
    # Reject source-cue / remnant leftovers hard.
    if re.search(r"(?i)\b(?:verified through|official event page|multiple sources|including the)\b", out):
        safe_parts = [
            x
            for x in parts
            if x and not re.search(r"(?i)verified|official event|sources", x)
        ]
        out = _sanitize_spoken_prose(" ".join(safe_parts))
        if not out and (route or calendar):
            out = _sanitize_spoken_prose(" ".join(x for x in (route, calendar) if x))
    if reject_tts_residue(out):
        safe = [x for x in parts if x and not reject_tts_residue(x)]
        out = _sanitize_spoken_prose(" ".join(safe))
    return out.strip()


def post_render_visual_line(*, category: str | None = None) -> str:
    """Single allowed post-ack visual claim line (after compact final completes)."""
    cat = (category or "").strip().lower()
    if cat in ("", "lodging"):
        return "Lodging options are on the screen."
    if cat in ("steakhouse", "meals", "restaurant"):
        if cat == "steakhouse":
            return "Steak house options are on the screen."
        if cat == "restaurant":
            return "Restaurant options are on the screen."
        return "Meal options are on the screen."
    if cat == "entertainment":
        return "Entertainment options are on the screen."
    if cat == "fuel":
        return "Fuel options are on the screen."
    if cat == "other":
        return "Options are on the screen."
    return "Options are on the screen."


def queue_post_render_visual_tts(
    *,
    correlation_id: str,
    category: str | None = None,
    timing_path: Path | None = None,
    voice_id: str | None = None,
) -> dict[str, Any]:
    """Queue post-render visual line only after compact final playback completes."""
    line = post_render_visual_line(category=category)
    return _queue_smedley_speak(
        line,
        voice_id=str(voice_id or _JARVIS_ELEVENLABS_VOICE_ID),
        voice_name="James Michael",
        role="post_ack_visual",
        correlation_id=correlation_id,
        timing_path=timing_path,
        delay_s=0.0,
        once_set=_POST_ACK_ONCE,
        wait_complete=True,
        wait_final_before_speak=True,
    )


def reject_tts_residue(text: str) -> list[str]:
    """Return rejection reasons if TTS text still contains forbidden residue."""
    reasons: list[str] = []
    s = str(text or "")
    if _VISUAL_CLAIM_RE.search(s):
        reasons.append("visual_claim_before_ack")
    if re.search(r"https?://", s, re.I):
        reasons.append("url")
    if re.search(r"\b(?:[a-z0-9-]+\.)+(?:com|org|net|edu|gov|io)\b", s, re.I):
        reasons.append("hostname")
    if _NUMBERED_RESULT_RE.search(s) or re.search(r"(?i)\b\d+\.\s+[A-Z]", s):
        reasons.append("numbered_results")
    if _REDACTION_RE.search(s):
        reasons.append("redaction_remnant")
    if re.search(
        r"(?i)\b(?:yelp|opentable|tripadvisor|source_host|citations?:|source confidence|espn|ncaa|stubhub|verified through|official event page|multiple sources)\b",
        s,
    ):
        reasons.append("source_cue_or_card_chrome")
    if re.search(r"(?i)\b(?:here are some|recommended steakhouses?|best steakhouses?)\b", s):
        reasons.append("raw_recommendation_text")
    if re.search(r"[#*_`]{2,}", s):
        reasons.append("markdown_residue")
    return reasons


def _int_to_words(n: int) -> str | None:
    try:
        n = int(round(float(n)))
    except Exception:
        return None
    if n < 0:
        w = _int_to_words(-n)
        return f"minus {w}" if w else None
    if n < 20:
        return _ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return _TENS[t] if o == 0 else f"{_TENS[t]}-{_ONES[o]}"
    if n < 200:
        r = n % 100
        return "one hundred" if r == 0 else f"one hundred {_int_to_words(r)}"
    return str(n)


def _bearing_to_cardinal(deg: Any) -> str | None:
    try:
        d = float(deg)
    except Exception:
        return None
    d = d % 360.0
    return _CARDINALS[int(round(d / 45.0)) % 8]


def build_weather_speech_from_currents(currents: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(currents, dict):
        return None
    clauses: list[str] = []
    fields: dict[str, Any] = {}
    if currents.get("temp") is not None:
        try:
            t = int(round(float(currents["temp"])))
        except Exception:
            t = None
        tw = _int_to_words(t) if t is not None else None
        if tw:
            clauses.append(f"Temperature {tw} degrees.")
            fields["temperature_f"] = t
            fields["temperature_words"] = tw
    wind = currents.get("wind") if isinstance(currents.get("wind"), dict) else {}
    if wind.get("speed") is not None:
        try:
            s = int(round(float(wind["speed"])))
        except Exception:
            s = None
        sw = _int_to_words(s) if s is not None else None
        card = _bearing_to_cardinal(wind.get("direction"))
        if sw and card:
            clauses.append(f"Wind {sw} miles per hour from the {card}.")
            fields.update({"wind_mph": s, "wind_words": sw, "wind_from": card})
        elif sw:
            clauses.append(f"Wind {sw} miles per hour.")
            fields.update({"wind_mph": s, "wind_words": sw})
    if not clauses:
        return None
    return {
        "schema": "jarvis.weather_speech.v1",
        "spoken": " ".join(clauses),
        "clauses": clauses,
        "fields": fields,
        "source": "normalized_from_currents",
        "never_raw_tool_fragments": True,
    }


def accept_weather_spoken(text: str) -> dict[str, Any]:
    """Acceptance check for normalized weather speech schema TTS only."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    reasons: list[str] = []
    if not t:
        return {"ok": False, "reasons": ["empty"], "text": t}
    if re.search(r"\d", t):
        reasons.append("digit_residue")
    if re.search(
        r"[°º]|°F|\bmph\b|\bkg/h\b|\bkm/h\b|\bRH\b|\btemp\b\s*:|\bhumidity\b\s*:|\bwind\b\s*:|\bobs_time|\bstation_id\b|\bcurrents\b",
        t,
        re.IGNORECASE,
    ):
        reasons.append("abbrev_or_field_label")
    if re.search(r"[{}\[\]|]", t):
        reasons.append("raw_fragment_chars")
    if not re.search(r"\b(temperature|wind|degrees|miles per hour)\b", t, re.IGNORECASE):
        reasons.append("not_weather_prose")
        return {"ok": False, "reasons": reasons, "text": t}
    parts = [
        re.sub(r"[^a-z0-9]+", "", p.strip().lower())
        for p in re.split(r"(?<=[.!?])\s+", t)
        if p.strip()
    ]
    for i in range(1, len(parts)):
        if parts[i] and parts[i] == parts[i - 1]:
            reasons.append("repeated_clause")
            break
    for clause in [p.strip() for p in re.split(r"(?<=\.)\s+", t) if p.strip()]:
        if re.match(
            r"^Temperature\s+[a-z]+(?:-[a-z]+)?(?:\s+[a-z]+(?:-[a-z]+)?)?\s+degrees\.$",
            clause,
            re.IGNORECASE,
        ):
            continue
        if re.match(
            r"^Wind\s+[a-z]+(?:-[a-z]+)?(?:\s+[a-z]+(?:-[a-z]+)?)?\s+miles per hour(?:\s+from the\s+[a-z]+)?\.$",
            clause,
            re.IGNORECASE,
        ):
            continue
        reasons.append("non_schema_clause:" + clause[:48])
    return {"ok": len(reasons) == 0, "reasons": reasons, "text": t}


def _split_sentences(text: str) -> list[str]:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if not t:
        return []
    parts = re.split(r"(?<=[.!?])\s+", t)
    return [p.strip() for p in parts if p.strip()]


_WEATHER_SENTENCE_CUE_RE = re.compile(
    r"\b(?:temperature|temp\b|°|degrees?\b|humidity|humid\b|wind\b|mph|fahrenheit|farenheit|"
    r"conditions?\b|barometer|precip|forecast|weather\b)\b",
    re.IGNORECASE,
)


def _is_weather_sentence(sentence: str) -> bool:
    """Whole-sentence weather classifier — never partial in-sentence edits."""
    return bool(_WEATHER_SENTENCE_CUE_RE.search(sentence or ""))


def gate_weather_tts(
    spoken_text: str, *, schema_speech: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any]]:
    """Admit weather to TTS only from accepted jarvis.weather_speech.v1 — or omit.

    Never strip regex fragments from agent weather prose (that leaves numeric residue).
    Drop every weather-classified sentence wholesale; append schema.spoken only when accepted.
    """
    original = re.sub(r"\s+", " ", str(spoken_text or "")).strip()
    sentences = _split_sentences(original)
    kept: list[str] = []
    dropped_weather: list[str] = []
    for s in sentences:
        if _is_weather_sentence(s):
            dropped_weather.append(s)
        else:
            kept.append(s)

    schema_spoken = ""
    schema_ok_identity = False
    if isinstance(schema_speech, dict):
        schema_ok_identity = str(schema_speech.get("schema") or "") == "jarvis.weather_speech.v1"
        schema_spoken = str(schema_speech.get("spoken") or "").strip() if schema_ok_identity else ""

    report: dict[str, Any] = {
        "schema": "jarvis.weather_speech_gate.v1",
        "policy": "schema_only_or_omit",
        "sampled_payload_before": original[:500],
        "dropped_weather_sentences": dropped_weather,
        "non_weather_sentences": kept,
        "schema_speech": schema_spoken or None,
        "schema_fields": (schema_speech or {}).get("fields") if schema_ok_identity else None,
        "schema_identity_ok": schema_ok_identity,
        "action": "none",
        "acceptance": None,
        "weather_source": None,
        "sampled_payload_after": None,
        "dispatch_allowed_weather": False,
        "weather_tts_exactly_schema_spoken": False,
    }

    admitted_weather = ""
    if schema_spoken and schema_ok_identity:
        acc = accept_weather_spoken(schema_spoken)
        report["acceptance"] = acc
        if acc.get("ok"):
            admitted_weather = schema_spoken
            report["action"] = "admit_schema_speech_only"
            report["weather_source"] = "jarvis.weather_speech.v1"
            report["dispatch_allowed_weather"] = True
            report["weather_tts_exactly_schema_spoken"] = True
        else:
            report["action"] = "omit_weather_schema_failed_acceptance"
            report["weather_source"] = None
            report["dispatch_allowed_weather"] = False
    else:
        report["action"] = (
            "omit_weather_no_schema"
            if dropped_weather
            else "no_weather_present"
        )
        report["acceptance"] = {
            "ok": False,
            "reasons": ["schema_unavailable"] if not schema_ok_identity else ["schema_spoken_empty"],
            "text": "",
        }
        report["dispatch_allowed_weather"] = False

    final_parts = list(kept)
    if admitted_weather:
        final_parts.append(admitted_weather)
    final = re.sub(r"\s+", " ", " ".join(final_parts)).strip()

    if admitted_weather:
        if final == admitted_weather or final.endswith(admitted_weather):
            non_wx = final[: -len(admitted_weather)].strip() if final.endswith(admitted_weather) else ""
            report["weather_tts_exactly_schema_spoken"] = True
            report["non_weather_prefix"] = non_wx[:300]
        else:
            final = re.sub(r"\s+", " ", " ".join(kept)).strip()
            report["action"] = "omit_weather_composition_drift"
            report["dispatch_allowed_weather"] = False
            report["weather_tts_exactly_schema_spoken"] = False
            admitted_weather = ""

    report["sampled_payload_after"] = final[:500]
    report["admitted_weather_tts"] = admitted_weather or None
    return final, report


def _lodging_only_spoken_line(lvm: dict[str, Any] | None) -> str | None:
    # Deprecated: never force "on the screen" lodging TTS (requires client render ack).
    return None

def _split_spoken_and_evidence(
    speak: str, *, citations: list[Any], correlation_id: str, receipt: Any
) -> tuple[str, str]:
    """Split Jarvis speak into natural spoken_text + visual evidence footer."""
    raw = str(speak or "").strip()
    spoken = _sanitize_spoken_prose(raw)
    if not spoken:
        # Fail soft to a short prose fallback (still no brackets/URLs).
        spoken = _sanitize_spoken_prose(re.sub(r"[\[\]{}]", " ", raw)) or "Jarvis briefing ready."

    # Owner UX: do not show Citations or receipt chrome on screen.
    # Structured citations remain on the Ask Jarvis payload for audit.
    evidence_footer = ""
    return spoken, evidence_footer


def try_ask_jarvis(message: str, *, biggy_ingress_ts: float | None = None, correlation_id: str | None = None) -> dict[str, Any] | None:
    """If message is an explicit leading Ask Jarvis: command, hard-bind to webhook.

    Returns ``{handled: True, reply, spoken_reply, evidence_footer, ...}`` or None.
    Optional ``biggy_ingress_ts`` (epoch seconds) stamps Biggy ingress→Jarvis timing.
    """
    text = str(message or "")
    if not is_ask_jarvis_command(text):
        return None

    t_ingress = float(biggy_ingress_ts) if biggy_ingress_ts is not None else time.time()
    t_bind_start = time.time()

    if not _ASK_JARVIS_SCRIPT.is_file():
        logger.error("ask_jarvis script missing: %s", _ASK_JARVIS_SCRIPT)
        return {
            "handled": True,
            "ok": False,
            "reply": "Jarvis briefing unavailable — ask_jarvis.py missing. Fail closed.",
            "spoken_reply": "Jarvis briefing unavailable.",
            "spoken_text": "Jarvis briefing unavailable.",
            "evidence_footer": "",
            "error": "ask_jarvis_script_missing",
            "correlation_id": None,
        }

    corr = str(correlation_id or "").strip() or mint_correlation_id()
    t_script_start = time.time()
    try:
        proc = subprocess.run(
            [
                "python3",
                str(_ASK_JARVIS_SCRIPT),
                "--source",
                "biggy_chat",
                "--correlation-id",
                corr,
                "--text",
                text,
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("ask_jarvis hard-bind failed")
        return {
            "handled": True,
            "ok": False,
            "reply": f"Jarvis briefing call failed ({type(exc).__name__}). Fail closed.",
            "spoken_reply": "Jarvis briefing failed.",
            "spoken_text": "Jarvis briefing failed.",
            "evidence_footer": "",
            "error": "ask_jarvis_exec_failed",
            "correlation_id": corr,
        }
    t_script_end = time.time()

    raw = (proc.stdout or "").strip()
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    speak = str(payload.get("speak") or "").strip()
    if not speak:
        err = (proc.stderr or raw or "empty speak").strip()[:400]
        speak = f"Jarvis briefing returned no speak. Fail closed. ({err})"

    citations = payload.get("citations") or []
    correlation_id = str(payload.get("correlation_id") or corr)
    receipt = payload.get("receipt") or payload.get("execution_id") or correlation_id

    t_split_start = time.time()
    spoken_text, evidence_footer = _split_spoken_and_evidence(
        speak,
        citations=citations if isinstance(citations, list) else [],
        correlation_id=correlation_id,
        receipt=receipt,
    )
    # Chat bubble: spoken answer only — never append Citations/receipt footer.
    reply = spoken_text
    t_hard_bind_ready = time.time()

    child_timing = payload.get("correlation_timing") if isinstance(payload.get("correlation_timing"), dict) else {}
    child_ts = dict(child_timing.get("timestamps_utc") or {})
    child_segs = dict(child_timing.get("segments_ms") or {})
    wh = child_segs.get("jarvis_webhook_wall_ms")
    script_wall = _ms(t_script_start, t_script_end)
    # ingress → Jarvis HTTP start ≈ script spawn + (script overhead before HTTP)
    ingress_to_req = _ms(t_ingress, t_script_start)
    if isinstance(wh, int):
        ingress_to_req = _ms(t_ingress, t_script_start) + max(0, script_wall - wh)
    timing = {
        "schema": "jarvis.ask_jarvis_correlation_timing.v1",
        "correlation_id": correlation_id,
        "timestamps_utc": {
            "biggy_ingress": _utc(t_ingress),
            "ask_jarvis_script_start": _utc(t_script_start),
            "ask_jarvis_script_end": _utc(t_script_end),
            "jarvis_request_start": child_ts.get("jarvis_request_start"),
            "jarvis_request_end": child_ts.get("jarvis_request_end"),
            "hard_bind_package_ready": _utc(t_hard_bind_ready),
        },
        "segments_ms": {
            "biggy_ingress_to_jarvis_request_ms": ingress_to_req,
            "biggy_ingress_to_script_start_ms": _ms(t_ingress, t_script_start),
            "ask_jarvis_script_wall_ms": script_wall,
            "jarvis_webhook_wall_ms": wh,
            "hard_bind_split_package_ms": _ms(t_split_start, t_hard_bind_ready),
            "biggy_ingress_to_hard_bind_ready_ms": _ms(t_ingress, t_hard_bind_ready),
            "try_ask_jarvis_wall_ms": _ms(t_bind_start, t_hard_bind_ready),
        },
    }

    try:
        path = timing_path_for(correlation_id)
        _merge_timing(path, correlation_id, timing)
    except Exception:
        logger.exception("ask_jarvis timing write failed")

    mvm = payload.get("map_view_model")
    lvm = payload.get("lodging_view_model")
    rvm = payload.get("recommendation_view_model")
    rec_cat = None
    if isinstance(rvm, dict):
        rec_cat = str(rvm.get("category") or "") or None
        # Never retain lodging cards when category is not lodging.
        if rec_cat and rec_cat != "lodging":
            lvm = None
    # TTS contract: compact venue/route/calendar only for travel packages from n8n.
    # Travel interpretation/defaulting lives in n8n B1 — not here.
    pre_compact = spoken_text
    is_travel_package = bool(
        (isinstance(mvm, dict) and str(mvm.get("schema") or "").startswith("jarvis.map_view_model"))
        or (isinstance(lvm, dict) and str(lvm.get("schema") or "").startswith("jarvis.lodging_view_model"))
        or (isinstance(rvm, dict) and (rvm.get("category") or rvm.get("schema")))
    )
    tts_spoken = pre_compact
    if is_travel_package:
        _lodge_names = []
        for _vm in (payload.get("recommendation_view_model"), payload.get("lodging_view_model")):
            if isinstance(_vm, dict):
                for _o in (_vm.get("options") or []):
                    if isinstance(_o, dict) and _o.get("name"):
                        _lodge_names.append(str(_o.get("name")))
        tts_spoken = compact_travel_tts(pre_compact, recommendation_category=rec_cat, lodging_names=_lodge_names)
        if reject_tts_residue(tts_spoken):
            tts_spoken = ""
        # destination_unresolved confirm-asks have no miles/ETA — keep sanitized prose.
        if not tts_spoken and pre_compact:
            tts_spoken = _sanitize_spoken_prose(pre_compact)
            if reject_tts_residue(tts_spoken):
                tts_spoken = pre_compact
    elif reject_tts_residue(tts_spoken):
        tts_spoken = _sanitize_spoken_prose(pre_compact) or pre_compact
    weather_speech = payload.get("weather_speech") if isinstance(payload.get("weather_speech"), dict) else None
    weather_gate_from_jarvis = (
        payload.get("weather_speech_gate") if isinstance(payload.get("weather_speech_gate"), dict) else None
    )
    tts_spoken, weather_tts_gate = gate_weather_tts(tts_spoken, schema_speech=weather_speech)
    # Prefer final pre-dispatch gate; keep upstream gate for audit.
    weather_speech_gate = {
        "schema": "jarvis.weather_speech_gate.v1",
        "upstream": weather_gate_from_jarvis,
        "pre_dispatch": weather_tts_gate,
    }
    try:
        path = timing_path_for(correlation_id)
        _merge_timing(
            path,
            correlation_id,
            {
                "weather_speech_gate": weather_speech_gate,
                "timestamps_utc": {"weather_tts_gate": _utc()},
            },
        )
    except Exception:
        logger.exception("ask_jarvis weather tts gate timing merge failed")
    # Chat bubble = speakable answer only (no Citations / receipt footer on screen).
    reply = tts_spoken or ""
    return {
        "handled": True,
        "ok": bool(payload.get("ok", True) and proc.returncode == 0 and payload.get("speak")),
        "reply": reply,
        "spoken_text": tts_spoken,
        "spoken_reply": tts_spoken,  # TTS/PTT only (no citations/receipt)
        "evidence_footer": evidence_footer,  # chat visual + audit only
        "tts_engine": _JARVIS_TTS_ENGINE,
        "tts_voice_id": _JARVIS_ELEVENLABS_VOICE_ID,
        "tts_voice_profile": "jarvis",
        "correlation_id": correlation_id,
        "receipt": receipt,
        "citations": citations,
        "map_view_model": mvm if isinstance(mvm, dict) else None,
        "lodging_view_model": lvm if isinstance(lvm, dict) else None,
        "recommendation_view_model": rvm if isinstance(rvm, dict) else None,
        "weather_speech": weather_speech,
        "weather_speech_gate": weather_speech_gate,
        "response_channel": payload.get("response_channel") or "biggy_direct_speak",
        "transport": "jarvis_webhook_jarvis-pa-biggy-briefing",
        "hard_bind": True,
        "error": payload.get("error"),
        "correlation_timing": timing,
        "timing_path": str(timing_path_for(correlation_id)),
    }
