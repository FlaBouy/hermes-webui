"""Short-lived PA conversation context for explicit Biggy -> Jarvis follow-ups.

This is deliberately process-local: it is not durable memory, it has no disk
backing, and it expires after one hour of inactivity.  It provides only enough
recent task context to resolve a follow-up such as "yes, dig deeper".  The PA
still has to perform fresh tool calls and evidence verification.
"""

from __future__ import annotations

from collections import defaultdict, deque
from threading import RLock
from time import time
from typing import Any


_MAX_TURNS = 10
_TTL_SECONDS = 60 * 60
_LOCK = RLock()
_TURNS: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=_MAX_TURNS))


def _safe_session_id(value: str | None) -> str:
    return "".join(ch for ch in str(value or "") if ch.isalnum() or ch in "-_")[:128]


def recent_context(session_id: str | None) -> list[dict[str, Any]]:
    """Return non-durable context for one Biggy chat, purging expired turns."""
    key = _safe_session_id(session_id)
    if not key:
        return []
    now = time()
    with _LOCK:
        turns = _TURNS.get(key)
        if not turns:
            return []
        kept = [turn for turn in turns if now - float(turn["at"]) <= _TTL_SECONDS]
        if not kept:
            _TURNS.pop(key, None)
            return []
        _TURNS[key] = deque(kept, maxlen=_MAX_TURNS)
        return [
            {
                "objective": turn["objective"],
                "status": turn["status"],
                "summary": turn["summary"],
                "tools": turn["tools"],
            }
            for turn in kept
        ]


def record_turn(
    session_id: str | None,
    *,
    objective: str,
    status: str,
    spoken_summary: str,
    tools: list[Any] | None,
) -> None:
    """Keep one bounded, non-durable PA turn for same-chat follow-ups only."""
    key = _safe_session_id(session_id)
    if not key:
        return
    allowed_tools = {"rag_core", "weather", "maps", "lodging_poi", "calendar_read", "gmail_read", "research"}
    safe_tools = [str(tool) for tool in (tools or []) if str(tool) in allowed_tools][:7]
    turn = {
        "at": time(),
        "objective": str(objective or "").strip()[:500],
        "status": str(status or "unknown").strip()[:80],
        "summary": str(spoken_summary or "").strip()[:1000],
        "tools": safe_tools,
    }
    with _LOCK:
        recent_context(key)
        _TURNS[key].append(turn)
