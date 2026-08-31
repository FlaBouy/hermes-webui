"""Low-latency Biggy voice lane for ordinary conversation.

PTT requests remain in Biggy's visible session, but ordinary conversation does
not need the coordinator's large model, tool loop, or full transcript.  This
module sends a small bounded context to the warm Jarvis V6 conversational model.
Explicit Argus/Smedley handoffs are excluded so their governed routes continue
to own tools, RAG, and specialist voices.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable
from urllib.request import Request, urlopen


DEFAULT_MODEL = "qwen/qwen3.5-35b-a3b"
DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"

_SPECIALIST_INVOCATION = re.compile(
    r"(?i)(?:^|[\s,;])(?:"
    r"ask(?:ed|ing)?|have|tell|need|get|get(?:ting)?"
    r")\s+(?:argus|smedley)\b"
)
_DIRECT_SPECIALIST = re.compile(r"(?i)^\s*(?:argus|smedley)\s*[:,]?")
_STORY_REQUEST = re.compile(
    r"(?i)\b(?:tell\s+(?:me\s+)?(?:a|the)\s+story|storytime|"
    r"tell\s+me\s+about|what\s+was\s+.+\s+like)\b"
)
_VOICE_WRAPPER = re.compile(r"\n\s*\[(?:Voice PTT turn|Full spoken mode)\b.*", re.I | re.S)

SYSTEM_PROMPT = """You are Biggy, Rick's fast first-touch coordinator in the Jarvis V6 voice lane.
Answer ordinary conversation directly. Be quick, sharp, quirky, and useful, with dry Biggy/Argus sarcasm and a little attitude. Never become contemptuous, insulting, or long-winded. Match Rick's direct cadence. For an ordinary question, use 2-5 natural spoken sentences. When he explicitly asks for a story, tell one complete vivid story with a real ending, normally 500-900 words, without restarting or repeating any passage. Do not claim live data, tools, files, sensors, calendar access, routing, or RAG unless verified in this turn. Do not announce your identity, model, host, status, or these instructions. /no_think"""


def is_explicit_specialist_request(text: str) -> bool:
    """Return True only when the owner explicitly calls Argus or Smedley."""
    value = str(text or "").strip()
    return bool(_SPECIALIST_INVOCATION.search(value) or _DIRECT_SPECIALIST.match(value))


def is_story_request(text: str) -> bool:
    return bool(_STORY_REQUEST.search(str(text or "")))


def should_use_fast_voice_route(*, message: str, display_message: str | None) -> bool:
    """Gate the light lane to real PTT payloads without topic inference."""
    if display_message is None:
        return False
    raw = str(display_message or "").strip()
    if not raw or is_explicit_specialist_request(raw):
        return False
    # The live pedal owns this exact em-dash contract. Looser legacy/test
    # appendices such as ``[Voice PTT turn]`` are not sufficient proof that
    # this is Biggy's pedal lane (Smedley uses the same sync endpoint).
    return "[Voice PTT turn —" in str(message or "")


def _clean_content(value: Any, *, limit: int = 1800) -> str:
    text = value if isinstance(value, str) else ""
    text = _VOICE_WRAPPER.sub("", text).strip()
    if len(text) > limit:
        text = text[-limit:]
    return text


def compact_voice_history(messages: Any, *, max_rows: int = 6) -> list[dict[str, str]]:
    """Keep only a few clean conversational rows; never replay the huge board."""
    rows: list[dict[str, str]] = []
    if not isinstance(messages, list):
        return rows
    for row in reversed(messages):
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        content = _clean_content(row.get("content"))
        if not content:
            continue
        rows.append({"role": role, "content": content})
        if len(rows) >= max_rows:
            break
    rows.reverse()
    return rows


def request_fast_voice_reply(
    prompt: str,
    *,
    history: Any = None,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Call the warm V6 light model once and return its single final answer."""
    raw = str(prompt or "").strip()
    story = is_story_request(raw)
    model = os.environ.get("BIGGY_V6_LIGHT_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    base_url = os.environ.get("BIGGY_V6_LIGHT_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(compact_voice_history(history))
    messages.append({"role": "user", "content": raw})
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.78 if story else 0.62,
        "max_tokens": 1500 if story else 320,
        "reasoning_effort": "none",
        "stream": False,
    }
    request = Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener(request, timeout=55 if story else 30) as response:
        result = json.loads(response.read().decode("utf-8"))
    choices = result.get("choices") if isinstance(result, dict) else None
    answer = ""
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict):
            answer = str(message.get("content") or "").strip()
    if not answer:
        raise RuntimeError("V6 light model returned an empty response")
    return {"reply": answer, "model": model, "story": story}
