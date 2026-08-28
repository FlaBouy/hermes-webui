"""Voice-safe spoken-output sanitizer for Smedley document replies + TTS.

Visible chat keeps clickable markdown/WebUI sidecar links. Before TTS / PTT
response-audio we strip raw URLs, markdown link syntax, filenames/link titles,
document-route/card-title boilerplate, scores, UI metadata, and raw retrieval
payload — speaking only the normal answer prose.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import api.smedley_document_route as docroute
from tests.js_source_extract import extract_function

ROOT = Path(__file__).resolve().parents[1]
LIVE_EXT = (
    Path.home()
    / ".hermes"
    / "webui"
    / "extensions"
    / "smedley-engineering"
    / "smedley-engineering.v0.2.5.js"
)
ORIGIN = "https://smedley.example:9111"
SOURCE = "Library/NEC/02-315.pdf"
HREF = f"{ORIGIN}/api/extensions/smedley-engineering/sidecar/doc/{SOURCE}"


def _sample_document_reply() -> str:
    return (
        f'Document links for “Pull the document 02-315” (sidecar preview):\n\n'
        f"- 📄 [02-315.pdf]({HREF}) (score=0.880)\n"
        f"  Conductor ampacity table."
    )


def test_sanitize_strips_urls_markdown_filenames_and_doc_route_boilerplate():
    reply = _sample_document_reply()
    # Visible reply must still carry the clickable absolute sidecar link.
    assert HREF in reply
    assert "02-315.pdf" in reply

    spoken = docroute.sanitize_for_spoken_output(reply)
    assert HREF not in spoken
    assert "http" not in spoken.lower()
    assert "/api/extensions/" not in spoken
    assert "sidecar preview" not in spoken.lower()
    assert "document links" not in spoken.lower()
    assert "score=" not in spoken.lower()
    assert "[" not in spoken and "](" not in spoken
    # Filenames / link titles are not spoken — answer prose only.
    assert "02-315.pdf" not in spoken
    assert ".pdf" not in spoken.lower()
    assert "Conductor ampacity table" in spoken


def test_sanitize_ordinary_assistant_reply_keeps_prose_drops_filename_and_url():
    raw = (
        "Ampacity is in 📄 [02-315.pdf]("
        f"{HREF}). See Article 310."
    )
    spoken = docroute.sanitize_for_spoken_output(raw)
    assert "Ampacity is in" in spoken
    assert "Article 310" in spoken
    assert "02-315.pdf" not in spoken
    assert HREF not in spoken
    assert "http" not in spoken.lower()


def test_sanitize_strips_relative_sidecar_and_ui_meta():
    raw = (
        "Open [/api/extensions/smedley-engineering/sidecar/preview/Library/x.docx] "
        "(card title: Owner ACK) lan_url: http://192.168.0.15:8789/x.docx"
    )
    spoken = docroute.sanitize_for_spoken_output(raw)
    assert "/api/extensions/" not in spoken
    assert "lan_url" not in spoken.lower()
    assert "card title" not in spoken.lower()
    assert "192.168.0.15" not in spoken
    assert "http" not in spoken.lower()
    assert ".docx" not in spoken.lower()


def test_sanitize_strips_raw_retrieval_payload():
    raw = json.dumps(
        {
            "matches": [
                {
                    "source": SOURCE,
                    "score": 0.88,
                    "url": HREF,
                    "snippet": "Conductor ampacity table.",
                }
            ],
            "collection": "jarvis_kb",
        }
    )
    spoken = docroute.sanitize_for_spoken_output(raw)
    assert spoken == ""
    assert "matches" not in spoken.lower()
    assert "collection" not in spoken.lower()
    assert "jarvis_kb" not in spoken
    assert HREF not in spoken
    assert "02-315.pdf" not in spoken


def test_try_document_route_reply_vs_spoken_reply(monkeypatch):
    monkeypatch.setattr(
        docroute,
        "retrieve_documents",
        lambda query, topk=8, public_origin="": {
            "matches": [
                {
                    "source": SOURCE,
                    "snippet": "Conductor ampacity table.",
                    "url": HREF,
                    "markdown": f"📄 [02-315.pdf]({HREF})",
                    "score": 0.88,
                }
            ],
            "collection": "jarvis_kb",
        },
    )
    result = docroute.try_document_route(
        "Pull the document 02-315", public_origin=ORIGIN
    )
    assert result is not None and result["handled"] is True
    reply = result["reply"]
    spoken = result["spoken_reply"]
    # Visible: absolute clickable sidecar URL preserved.
    assert HREF in reply
    assert "📄" in reply or "02-315.pdf" in reply
    # Spoken: compact TTS — no URL / filename / route chrome.
    assert HREF not in spoken
    assert "02-315.pdf" not in spoken
    assert "sidecar preview" not in spoken.lower()
    assert "score=" not in spoken.lower()
    assert "http" not in spoken.lower()
    assert "The manual is on screen" in spoken or "I found" in spoken


def test_strip_for_tts_js_matches_voice_safe_contract():
    """Client TTS chokepoint must strip the same document/URL chrome."""
    ui_src = (ROOT / "static" / "ui.js").read_text(encoding="utf-8")
    fn = extract_function(ui_src, "_stripForTTS")
    assert "Document links" in fn
    assert "score" in fn
    assert "smedley-engineering" in fn
    assert "https?" in fn
    assert "pdf|docx" in fn or "pdf" in fn

    sample = _sample_document_reply()
    script = f"""
const fnSource = {json.dumps(fn)};
const ctx = {{}};
new Function('out', fnSource + '; out.fn = _stripForTTS;')(ctx);
const sample = {json.dumps(sample)};
const ordinary = {json.dumps(f"See [02-315.pdf]({HREF}) for ampacity.")};
const out = {{
  doc: ctx.fn(sample),
  ordinary: ctx.fn(ordinary),
}};
console.log(JSON.stringify(out));
"""
    result = subprocess.run(
        ["node", "-e", script], check=True, capture_output=True, text=True
    )
    out = json.loads(result.stdout)
    for key in ("doc", "ordinary"):
        spoken = out[key]
        assert "02-315.pdf" not in spoken, spoken
        assert HREF not in spoken, spoken
        assert "http" not in spoken.lower(), spoken
        assert "sidecar preview" not in spoken.lower(), spoken
        assert "score=" not in spoken.lower(), spoken
        assert "](" not in spoken, spoken
    assert "ampacity" in out["ordinary"].lower()
    assert "Conductor ampacity table" in out["doc"]


def test_wiring_document_route_auto_read_and_spoken_reply_field():
    routes = (ROOT / "api" / "routes.py").read_text(encoding="utf-8")
    messages = (ROOT / "static" / "messages.js").read_text(encoding="utf-8")
    biggy = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
    assert "spoken_reply" in routes
    assert "spoken_reply" in messages or "autoReadLastAssistant" in messages
    assert "document_route" in messages
    assert "setTimeout(()=>autoReadLastAssistant(), 300)" in messages
    assert "stripForSmedleySpeak" in biggy
    assert "smedley-engineering" in biggy
    assert "Document links" in biggy


def test_smedley_distributed_voice_uses_voice_safe_text_before_speak():
    """The Smedley /speak override must not bypass the client TTS sanitizer."""
    if not LIVE_EXT.is_file():
        return
    src = LIVE_EXT.read_text(encoding="utf-8")
    body = extract_function(src, "installSmedleyVoiceOutput")
    assert "function voiceSafeText(raw)" in body
    assert "window._stripForTTS" in body
    assert "voiceSafeText(text)" in body
    assert "JSON.stringify({text:spoken})" in body or "JSON.stringify(body)" in body


# Exact 05:13 typed Smedley reply (session 9311944c733a, assistant id 4).
_SMEDLEY_0513_DISPLAY = (
    "Systems green across the board:\n\n"
    "- Hermes Agent API server: running and responding\n"
    "- Local file access: operational (home at /Users/rick)\n"
    "- Toolset loaded: all major tools available (terminal, web_search, memory, skill_view, etc.)\n"
    "- Workspace directory: ready (/Users/rick/.hermes/profiles/smedley/workspace)\n"
    "- Model active: qwen/qwen3.5-35b-a3b via LM Studio\n"
    "- Skills catalog loaded: 20+ skills available including hermes-agent, github, debugging, and fleet tools\n\n"
    "No red flags or blocked resources. What's the first order of business?"
)


def test_gateway_spoken_text_keeps_display_and_closing_question():
    display = _SMEDLEY_0513_DISPLAY
    spoken = docroute.spoken_text_for_gateway_reply(display)

    assert display == _SMEDLEY_0513_DISPLAY
    assert "- Hermes Agent API server" in display
    assert spoken != display
    assert len(spoken) <= docroute.GATEWAY_SPOKEN_MAX_CHARS
    assert "What's the first order of business?" in spoken
    assert spoken.rstrip().endswith("What's the first order of business?")
    assert "[" not in spoken
    assert "]" not in spoken
    assert "(" not in spoken
    assert ")" not in spoken
    assert "board:." not in spoken
    assert "…" not in spoken
    assert "..." not in spoken
    assert not re.search(r"(?m)^\s*[-*•]\s+", spoken)
    assert "- Hermes" not in spoken
    assert "Systems green across the board" in spoken


_SMELL_DISPLAY = (
    "*I can smell it.*\n\n"
    "I can't literally smell it, but if this place had a scent it'd be hot flux, "
    "ozone, and burnt phenolic — shop floor, not a lithium pack cooking off. "
    "What's the first meter reading you want?"
)


def test_smell_it_display_kept_spoken_omits_stage_and_false_sensors():
    display = _SMELL_DISPLAY
    spoken = docroute.spoken_text_for_gateway_reply(display)
    assert "*I can smell it.*" in display
    assert "shop floor" in display
    assert "I can smell it" not in spoken
    assert "*" not in spoken
    assert "can't literally smell" in spoken.lower() or "cannot literally smell" in spoken.lower()
    assert "shop floor" in spoken.lower() or "hot flux" in spoken.lower()
    assert not re.search(r"\b(my sensors?|atmospheric scan|verified (?:lithium|hazard))\b", spoken, re.I)
    assert "What's the first meter reading you want?" in spoken
    assert spoken.rstrip().endswith("What's the first meter reading you want?")
    assert "(" not in spoken and ")" not in spoken


def test_long_ptt_spoken_text_complete_and_capped():
    display = _SMEDLEY_0513_DISPLAY
    msgs = [{"role": "assistant", "content": display}]
    spoken = docroute.attach_spoken_text_to_last_assistant(msgs)
    assert msgs[0]["content"] == display
    assert msgs[0]["spoken_text"] == spoken
    assert len(spoken) <= docroute.GATEWAY_SPOKEN_MAX_CHARS
    assert "What's the first order of business?" in spoken
    assert spoken.rstrip().endswith("What's the first order of business?")
    assert "…" not in spoken
    sync_src = (ROOT / "api" / "routes.py").read_text(encoding="utf-8")
    assert "attach_spoken_text_to_last_assistant" in sync_src
    assert '"spoken_text": spoken_text or None' in sync_src


def test_explicit_story_request_speaks_full_narrative():
    story = " ".join(
        f"Sentence {index} carries the story forward with enough detail."
        for index in range(1, 70)
    )
    msgs = [
        {"role": "user", "content": "Hey Biggy, tell me a story about a Marine."},
        {"role": "assistant", "content": story},
    ]

    spoken = docroute.attach_spoken_text_to_last_assistant(msgs)

    assert spoken == story.rstrip(".")
    assert "Sentence 69 carries the story forward" in spoken
    assert len(spoken) > docroute.GATEWAY_SPOKEN_MAX_CHARS
    assert msgs[-1]["spoken_text"] == spoken


def test_gateway_chat_writeback_attaches_spoken_text_not_spoken_reply():
    src = (ROOT / "api" / "gateway_chat.py").read_text(encoding="utf-8")
    assert "spoken_text_for_gateway_reply" in src
    assert 'assistant_msg["spoken_text"] = spoken' in src
    assert 'assistant_msg["spoken_reply"]' not in src
    live = LIVE_EXT.read_text(encoding="utf-8") if LIVE_EXT.is_file() else ""
    if live:
        assert "m.spoken_text||m.spoken_reply" in live.replace(" ", "")
