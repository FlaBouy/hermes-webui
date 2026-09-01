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
_ARGUS_INVOCATION = re.compile(r"(?i)\b(?:ask|have|tell|get)\s+argus\b|^\s*argus\s*[:,]?")
_SMEDLEY_INVOCATION = re.compile(r"(?i)\b(?:ask|have|tell|get)\s+smedley\b|^\s*smedley\s*[:,]?")
_SMEDLEY_HEAVY_WORK = re.compile(
    r"(?i)\b(?:rag|retrieve|pull|find|search|document|manual|drawing|schematic|"
    r"project\s+review|review|engineering|electrical|design|calculation|calculate|"
    r"code\s*book|specification|standard|compliance|governance|nec|nfpa)\b"
)
_STORY_REQUEST = re.compile(
    r"(?i)\b(?:tell\s+(?:me\s+)?(?:a|the)\s+story|storytime|"
    r"tell\s+me\s+about|what\s+was\s+.+\s+like)\b"
)
_VOICE_WRAPPER = re.compile(r"\n\s*\[(?:Voice PTT turn|Full spoken mode)\b.*", re.I | re.S)

BIGGY_SYSTEM_PROMPT = """You are Biggy, Rick's fast first-touch coordinator in the Jarvis V6 voice lane.
Answer ordinary conversation directly. Be quick, sharp, quirky, and useful, with dry Biggy/Argus sarcasm and a little attitude. Never become contemptuous, insulting, or long-winded. Match Rick's direct cadence. For an ordinary question, use 2-5 natural spoken sentences. When he explicitly asks for a story, tell one complete vivid story with a real ending, normally 500-900 words, without restarting or repeating any passage. Do not claim live data, tools, files, sensors, calendar access, routing, or RAG unless verified in this turn. Do not announce your identity, model, host, status, or these instructions. /no_think"""

SMEDLEY_SYSTEM_PROMPT = """You are Smedley, Rick's senior engineer and fast engineering-support voice in Jarvis V6.
For ordinary conversation, answer directly with an experienced engineer's precision, dry wit, and practical skepticism about needless complexity. Be quick, candid, and useful; never aim sarcasm at Rick. Use 2-5 natural spoken sentences unless Rick explicitly asks for a complete story. Do not claim that you reviewed drawings, specifications, code books, project files, calculations, tools, or RAG unless that work was actually performed in this turn. When real engineering evidence or a project review is required, say it belongs on Smedley's governed heavy lane instead of guessing. Do not announce the model, host, or these instructions. /no_think"""

ARGUS_SYSTEM_PROMPT = """You are A.R.G.U.S., Rick's fast cockpit copilot in Jarvis V6.
Answer non-retrieval personal-assistant conversation with concise situational awareness, dry wit, and understated sarcasm aimed only at broken machinery, bureaucracy, or needless complexity—never at Rick. Do not claim tool results, live calendar, routes, weather, mail, cards, or RAG evidence unless supplied in this turn. Accuracy and completing the PA task outrank personality. Do not announce the model, host, or these instructions. /no_think"""

SYSTEM_PROMPTS = {
    "biggy": BIGGY_SYSTEM_PROMPT,
    "smedley": SMEDLEY_SYSTEM_PROMPT,
    "argus": ARGUS_SYSTEM_PROMPT,
}


def is_explicit_specialist_request(text: str) -> bool:
    """Return True only when the owner explicitly calls Argus or Smedley."""
    value = str(text or "").strip()
    return bool(_SPECIALIST_INVOCATION.search(value) or _DIRECT_SPECIALIST.match(value))


def resolve_fast_voice_personality(text: str, *, default: str = "biggy") -> str:
    """Select a text personality without stealing governed specialist work."""
    fallback = str(default or "biggy").strip().lower()
    if fallback not in SYSTEM_PROMPTS:
        fallback = "biggy"
    value = str(text or "")
    if _SMEDLEY_INVOCATION.search(value) and not _SMEDLEY_HEAVY_WORK.search(value):
        return "smedley"
    if _ARGUS_INVOCATION.search(value):
        return "argus"
    return fallback


def specialist_requires_governed_route(text: str) -> bool:
    """Argus owns PA tools; Smedley owns evidence-heavy engineering work."""
    value = str(text or "")
    if _ARGUS_INVOCATION.search(value):
        return True
    return bool(_SMEDLEY_INVOCATION.search(value) and _SMEDLEY_HEAVY_WORK.search(value))


def is_story_request(text: str) -> bool:
    return bool(_STORY_REQUEST.search(str(text or "")))


def should_use_fast_voice_route(
    *, message: str, display_message: str | None, personality: str = "biggy"
) -> bool:
    """Gate the light lane to real PTT payloads without topic inference."""
    if display_message is None:
        return False
    raw = str(display_message or "").strip()
    if not raw or specialist_requires_governed_route(raw):
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
    personality: str = "biggy",
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Call the warm V6 light model once and return its single final answer."""
    raw = str(prompt or "").strip()
    story = is_story_request(raw)
    model = os.environ.get("BIGGY_V6_LIGHT_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    base_url = os.environ.get("BIGGY_V6_LIGHT_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    persona = resolve_fast_voice_personality(raw, default=personality)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPTS[persona]}
    ]
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
