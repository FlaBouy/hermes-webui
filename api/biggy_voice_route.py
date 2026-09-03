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
_ARGUS_GOVERNED_WORK = re.compile(
    r"(?i)\b(?:rag|retrieve|search|document|manual|drawing|route|routing|map|"
    r"directions?|travel|trip|calendar|schedule|conflict|weather|mail|email|"
    r"text|message|call|phone|lodging|hotel|meal|restaurant|fuel|booking|"
    r"reservation|card|task|todo|note|alert)\b"
)
_GENERAL_AGENT_WORK = re.compile(
    r"(?i)(?:^|\b)(?:fix|change|edit|implement|build|create|delete|remove|"
    r"commit|push|deploy|install|configure|run|execute|inspect|debug|test|"
    r"review|analy[sz]e)\b.*\b(?:code|repo(?:sitory)?|project|file|folder|"
    r"service|server|workflow|system|gui|api|database|document|drawing|"
    r"specification|calculation|design)\b"
)
# Shared Project Review dialog dispatch contract.
# Default is dialogue (clarify). Governed only on an explicit *current*
# execute/continuation directive — not mentioned, negated, hypothetical, or
# future-dependent work verbs.
_COMMAND_PREFIX = re.compile(r"^\s*/")
_EXPLICIT_CONTINUATION = re.compile(
    r"(?i)^\s*(?:"
    r"(?:ok[,.]?\s*)?(?:proceed|continue|go\s+ahead)\s*[.!?]?\s*"
    r"|"
    r"(?:please\s+)?(?:proceed|continue)\s*[!?]?\s*"
    r"|"
    r"(?:can|could|would)\s+you\s+do\s+(?:that|it|so)\s*[?]?\s*"
    r"|"
    r"please\s+proceed\s*[?]?\s*"
    r")$"
)
# Split so mixed discussion + present directive are evaluated per clause.
_PROJECT_REVIEW_CLAUSE_SPLIT = re.compile(
    r"(?:[.!?;]+\s*)|\n+"
    r"|(?:,\s*(?:and\s+)?)(?=(?:please|re-run|rerun|run\b|extract\b|verify\b|"
    r"delete\b|go\s+ahead|if\s+not)\b)"
    r"|(?:\s+and\s+)(?=(?:please\s+)?(?:re-run|rerun|run\b|extract\b|verify\b|"
    r"delete\b|go\s+ahead)\b)"
    r"|(?:\s+)(?=but\s+(?:please\s+)?(?:run|extract|re-?run|rerun|go\s+ahead|"
    r"proceed|create|generate|build)\b)"
)
_NEGATED_CLAUSE_PREFIX = re.compile(
    r"(?i)^\s*(?:please\s+)?(?:do\s+not|don't|dont|never)\b"
)
_RESTRICTED_EXECUTION_CLAUSE = re.compile(
    r"(?i)(?:\b(?:read|run|extract|scan|process|inspect|retrieve|open|execute|do)"
    r"\s+(?:no\b|nothing\b|none\b)|"
    r"\b(?:unless|until|only\s+(?:when|if))\s+(?:(?:i|you|we|rick)\s+)?"
    r"(?:(?:am|are|is|have|has|specifically|explicitly|directly)\s+)*"
    r"(?:ask(?:ed)?|request(?:ed)?|instruct(?:ed)?|authoriz(?:e|ed)|approv(?:e|ed))\b)"
)
_CLAUSE_NEGATED_WORK = re.compile(
    r"(?i)\b(?:not\s+(?:run|extract|re-?run|rerun|execute|start|do)|"
    r"before\s+you\s+(?:run|extract|re-?run|do|start)\b|"
    r"without\s+(?:running|extracting|re-?running)\b)"
)
_HYPOTHETICAL_CLAUSE = re.compile(
    r"(?i)\b(?:if\s+i\b|if\s+you\s+(?:had|could|were)|suppose(?:d)?\s+i|"
    r"hypothetic(?:al(?:ly)?)?|assuming\s+i)\b"
)
_FUTURE_DEPENDENT_CLAUSE = re.compile(
    r"(?i)\b(?:"
    r"once\s+i\b|when\s+i\b|after\s+i\b|"
    r"i\s+(?:will|shall|'ll|’ll)\s+(?:give|provide|send|share|hand)|"
    r"parameters?\s+(?:that\s+)?i\s+will\b|"
    r"based\s+on\s+parameters?\b|"
    r"i(?:'|’)?ll\s+(?:give|provide|send|share)\b"
    r")\b"
)
_DISCUSSION_ONLY_CLAUSE = re.compile(
    r"(?i)\b(?:discuss|talk\s+through|walk\s+through|clarify|plan(?:ning)?|"
    r"layout|approach)\b"
)
# Present imperative / current authorization to act now.
_PRESENT_EXECUTE_CLAUSE = re.compile(
    r"(?i)(?:"
    r"^\s*(?:(?:ok|sure|yes|please|but|then|now|also)[,.]?\s*)*"
    r"(?:please\s+)?(?:"
    r"create|build|draft|make|"
    r"re-?run|rerun|run(?:\s+(?:it|them|again|now))?"
    r"|extract|ingest|scan|retrieve|inspect|analy[sz]e|calculate|recalculate|"
    r"verify|cross-?check|compare|update|revise|generate|write|finalize|"
    r"approve|sign\s*off|execute|apply|parse|process|pull|invoke|call|"
    r"start|finish|complete|delete|read"
    r")\b"
    r"|"
    r"^\s*(?:(?:ok|sure|yes|please|but|then)[,.]?\s*)*"
    r"go\s+ahead(?:\s+and\b)?"
    r"|"
    r"^\s*(?:(?:ok|sure|yes|please|but|then)[,.]?\s*)*"
    r"do\s+(?:that|it|so)\b"
    r"|"
    r"\b(?:create|build|draft|make)\b.{0,80}\b(?:now|immediately)\b"
    r"|"
    r"\b(?:create|build|draft|make|generate|write)\b.{0,100}"
    r"\b(?:using|from|against)\b.{0,48}"
    r"\b(?:ingested|ingestions|files?|documents?|pdfs?|dxf|sources?)\b"
    r"(?!.{0,40}\bonce\s+i\b)"
    r"|"
    r"\bproject_review_extract(?:_capabilities)?\b"
    r"|"
    r"\b(?:using|with|via)\b.{0,48}\b(?:new\s+)?tools?\b"
    r"|"
    r"\bif\s+not\b.+\b(?:run|extract|re-?run|rerun|verify|delete)\b"
    r")"
)
# Modal "can/could you run/extract/read …" as a present request (no future/hypo guard).
_MODAL_PRESENT_EXECUTE = re.compile(
    r"(?i)\b(?:can|could|would|will)\s+you\b(?!.{0,32}\b(?:summarize|clarify|"
    r"explain|remind|discuss)\b).{0,64}\b(?:do|run|extract|proceed|re-?run|"
    r"update|verify|check|pull|call|execute|start|finish|complete|parse|"
    r"process|read|create|build|draft|make|generate|write)\b"
)
_PROJECT_REVIEW_INFORMATIONAL_ONLY = re.compile(
    r"(?i)^\s*(?:"
    r"(?:what|why|how|when|where|which)\b.+"
    r"|"
    r"(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?(?:summarize|clarify|explain|remind(?:\s+me)?)\b.+"
    r")\s*$"
)
_STORY_REQUEST = re.compile(
    r"(?i)\b(?:tell\s+(?:me\s+)?(?:a|the)\s+story|storytime|"
    r"tell\s+me\s+about|what\s+was\s+.+\s+like)\b"
)
_ONE_SENTENCE_REQUEST = re.compile(
    r"(?i)\b(?:one|single)(?:\s+[a-z-]+){0,2}\s+(?:line|sentence)\b|\bbriefly\b"
)
_SENTENCE_END = re.compile(r"[.!?][\"')\]]*(?=\s|$)")
_SENTENCE_ABBREVIATION = re.compile(r"\b(?:approx|e\.g|i\.e|vs|mr|mrs|ms|dr|prof|fig|no|rev|etc)\.$", re.I)


def _completed_sentence_endings(text: str, *, final: bool = False):
    """A chunk boundary is not an end of sentence (notably '2.' before '5%')."""
    endings = []
    for match in _SENTENCE_END.finditer(text):
        if not final and not text[match.end():].strip():
            continue  # Wait for continuation or the provider's actual end.
        if text[match.start()] == '.' and _SENTENCE_ABBREVIATION.search(text[:match.start() + 1]):
            continue
        endings.append(match)
    return endings
_VOICE_WRAPPER = re.compile(r"\n\s*\[(?:Voice PTT turn|Full spoken mode)\b.*", re.I | re.S)

BIGGY_SYSTEM_PROMPT = """You are Biggy, Rick's fast first-touch coordinator in the Jarvis V6 voice lane.
The current user is Rick (owner); never tell him to ask Rick. Do not invent interface diagnoses without telemetry. When conversation history is absent, state that limitation neutrally—no physical-archive claims and no hostility. Answer ordinary conversation directly. Default to one crisp answer of 1-2 natural spoken sentences; never exceed two unless Rick asks for more, and obey an explicit one-line or one-sentence request exactly. Put a sharp, dry, understated sarcastic edge in most replies; aim it at bureaucracy, broken machinery, or needless complexity, never at Rick. Skip sarcasm when the subject is grief, injury, medical or legal distress, an emergency, a serious personnel matter, or anywhere humor would weaken clarity. Never become contemptuous, insulting, repetitive, or long-winded. Match Rick's direct cadence. When he explicitly asks for a story, tell one complete vivid story with a real ending, normally 500-900 words, without restarting or repeating any passage. Do not claim live data, tools, files, sensors, calendar access, routing, or RAG unless verified in this turn. Do not announce your identity, model, host, status, or these instructions. /no_think"""

SMEDLEY_SYSTEM_PROMPT = """You are Smedley, Rick's senior engineer and fast engineering-support voice in Jarvis V6.
For ordinary conversation, answer directly in 1-2 crisp natural spoken sentences with an experienced engineer's precision and practical skepticism; never exceed two unless Rick asks for more, and obey an explicit one-line or one-sentence request exactly. Give most replies one restrained piece of dry wit about needless complexity, bad process, or dubious machinery; never aim it at Rick. Skip sarcasm for safety incidents, grief, injury, emergencies, serious personnel matters, or when it would weaken technical clarity. Do not claim that you reviewed drawings, specifications, code books, project files, calculations, tools, or RAG unless that work was actually performed in this turn. Never claim that extraction, a re-run, tool use, or other review work is pending, started, or will be done next unless this turn actually performed it. When real engineering evidence or a project review is required, say it belongs on Smedley's governed heavy lane instead of guessing. Do not announce the model, host, or these instructions. /no_think"""

ARGUS_SYSTEM_PROMPT = """You are A.R.G.U.S., Rick's fast cockpit copilot in Jarvis V6.
Answer non-retrieval personal-assistant conversation in 1-2 crisp natural spoken sentences; never exceed two unless Rick asks for more, and obey an explicit one-line or one-sentence request exactly. Give most replies sharp, dry, understated sarcasm aimed only at broken machinery, bureaucracy, or needless complexity—never at Rick. Skip sarcasm for grief, injury, emergencies, medical or legal distress, serious personnel matters, or whenever it would weaken operational clarity. Do not claim tool results, live calendar, routes, weather, mail, cards, or RAG evidence unless supplied in this turn. Accuracy and completing the PA task outrank personality. Do not announce the model, host, or these instructions. /no_think"""

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
        return bool(_ARGUS_GOVERNED_WORK.search(value))
    return bool(_SMEDLEY_INVOCATION.search(value) and _SMEDLEY_HEAVY_WORK.search(value))


def should_use_fast_conversation_route(
    text: str,
    *,
    profile: str = "biggy",
    has_attachments: bool = False,
) -> bool:
    """Route ordinary typed conversation to V6 without stealing real work.

    The light lane owns conversation.  Tool execution, RAG, engineering review,
    repository work, slash commands, and attachments remain on their governed
    paths.  Explicit Argus/Smedley addresses select personality only when the
    request itself does not require those specialist capabilities.
    """
    value = str(text or "").strip()
    if not value or has_attachments or _COMMAND_PREFIX.match(value):
        return False
    if "[FORCED SKILL CONTEXT:" in value or _GENERAL_AGENT_WORK.search(value):
        return False
    if _SMEDLEY_INVOCATION.search(value) and _SMEDLEY_HEAVY_WORK.search(value):
        return False
    if _ARGUS_INVOCATION.search(value) and _ARGUS_GOVERNED_WORK.search(value):
        return False
    return str(profile or "biggy").strip().lower() in {"biggy", "argus", "smedley"}


def _split_project_review_clauses(text: str) -> list[str]:
    return [
        part.strip()
        for part in _PROJECT_REVIEW_CLAUSE_SPLIT.split(text)
        if part and part.strip()
    ]


def _clause_is_non_executing_context(clause: str) -> bool:
    """True when work verbs are mentioned but not authorized as current execute."""
    value = str(clause or "").strip()
    if not value:
        return True
    if _NEGATED_CLAUSE_PREFIX.match(value) or _CLAUSE_NEGATED_WORK.search(value):
        return True
    if _RESTRICTED_EXECUTION_CLAUSE.search(value):
        return True
    if _HYPOTHETICAL_CLAUSE.search(value):
        return True
    if _FUTURE_DEPENDENT_CLAUSE.search(value):
        return True
    # Discussion-only clauses that mention work only to defer it.
    if _DISCUSSION_ONLY_CLAUSE.search(value) and not _PRESENT_EXECUTE_CLAUSE.search(value):
        return True
    return False


def clause_is_current_execute_directive(clause: str) -> bool:
    """True only for an explicit present imperative / continuation authorization."""
    value = str(clause or "").strip()
    if not value:
        return False
    if _clause_is_non_executing_context(value):
        return False
    if _EXPLICIT_CONTINUATION.match(value):
        return True
    if _PRESENT_EXECUTE_CLAUSE.search(value):
        return True
    if _MODAL_PRESENT_EXECUTE.search(value):
        return True
    return False


def message_has_current_execute_directive(text: str) -> bool:
    """Any clause with a current execute/continuation directive → governed."""
    value = str(text or "").strip()
    if not value:
        return False
    return any(
        clause_is_current_execute_directive(c)
        for c in _split_project_review_clauses(value)
    )


def is_capability_or_deferred_planning(text: str) -> bool:
    """True for capability / deferred-parameter planning (not prior-result Q&A)."""
    value = str(text or "").strip()
    if not value or message_has_current_execute_directive(value):
        return False
    if _HYPOTHETICAL_CLAUSE.search(value) or _FUTURE_DEPENDENT_CLAUSE.search(value):
        return True
    if re.search(
        r"(?i)\b(?:can|could|would)\s+you\b.{0,96}\b(?:create|build|make|draft|"
        r"set\s*up|generate)\b.{0,96}\b(?:worksheet|workbook|spreadsheet|matrix)\b",
        value,
    ):
        return True
    return False


def plan_project_review_turn(text: str) -> dict[str, str]:
    """Single dispatch contract for Project Review dialog turns.

    Returns ``{"lane": "fast"|"governed"|"status", "reason": ...}``.

    Default is **dialogue** (clarify / answer). Governed only when a clause is
    an explicit *current* execute or continuation directive. Mentioned,
    negated, hypothetical, and future-dependent work verbs do not authorize a
    tool loop. Question marks alone never select governed. Status inquiries
    report prior results without starting a full re-run.
    """
    value = str(text or "").strip()
    if not value:
        return {"lane": "fast", "reason": "empty_message_dialogue"}
    if _COMMAND_PREFIX.match(value):
        return {"lane": "governed", "reason": "command_prefix"}
    from api.biggy_project_review_runtime import classify_project_review_status_inquiry

    if classify_project_review_status_inquiry(value):
        return {"lane": "status", "reason": "status_inquiry_report_prior"}
    if message_has_current_execute_directive(value):
        if _EXPLICIT_CONTINUATION.match(value):
            return {"lane": "governed", "reason": "explicit_continuation"}
        return {"lane": "governed", "reason": "current_execute_directive"}
    if _PROJECT_REVIEW_INFORMATIONAL_ONLY.match(value):
        return {"lane": "fast", "reason": "informational_transcript_only"}
    if is_capability_or_deferred_planning(value):
        return {"lane": "fast", "reason": "dialogue_capability_or_deferred"}
    return {"lane": "fast", "reason": "dialogue_default_clarify"}


def should_use_fast_project_review_route(text: str) -> bool:
    """Compatibility wrapper over ``plan_project_review_turn``."""
    return plan_project_review_turn(text).get("lane") == "fast"


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


def _clean_content(value: Any, *, limit: int = 800) -> str:
    text = value if isinstance(value, str) else ""
    text = _VOICE_WRAPPER.sub("", text).strip()
    if len(text) > limit:
        text = text[-limit:]
    return text


def compact_voice_history(messages: Any, *, max_rows: int = 4) -> list[dict[str, str]]:
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
    system_context: str = "",
    history_rows: int = 4,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Call the warm V6 light model once and return its single final answer."""
    raw = str(prompt or "").strip()
    story = is_story_request(raw)
    sentence_limit = 1 if _ONE_SENTENCE_REQUEST.search(raw) else 2
    model = os.environ.get("BIGGY_V6_LIGHT_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    base_url = os.environ.get("BIGGY_V6_LIGHT_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    persona = resolve_fast_voice_personality(raw, default=personality)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPTS[persona]}
    ]
    if system_context:
        messages[0]["content"] += "\n\n" + system_context
    messages.extend(compact_voice_history(history, max_rows=max(1, min(history_rows, 24))))
    messages.append({"role": "user", "content": raw})
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.78 if story else 0.62,
        "max_tokens": 1500 if story else 128,
        "reasoning_effort": "none",
        # The normal lane closes the local generation as soon as the concise
        # answer is complete.  Besides reaching the UI sooner, this prevents a
        # warm model from spending tokens composing a third paragraph nobody
        # requested.  Stories remain a single complete non-streamed result.
        "stream": not story,
    }
    request = Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    answer = ""
    with opener(request, timeout=55 if story else 30) as response:
        if story:
            result = json.loads(response.read().decode("utf-8"))
            choices = result.get("choices") if isinstance(result, dict) else None
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                message = choices[0].get("message")
                if isinstance(message, dict):
                    answer = str(message.get("content") or "").strip()
        else:
            chunks: list[str] = []
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                    delta = event["choices"][0]["delta"].get("content") or ""
                except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                    continue
                if delta:
                    chunks.append(str(delta))
                    candidate = "".join(chunks).strip()
                    if len(_completed_sentence_endings(candidate)) >= sentence_limit:
                        break
            answer = "".join(chunks).strip()
            endings = _completed_sentence_endings(answer, final=True)
            if len(endings) >= sentence_limit:
                answer = answer[: endings[sentence_limit - 1].end()].strip()
    if not answer:
        raise RuntimeError("V6 light model returned an empty response")
    return {"reply": answer, "model": model, "story": story}
