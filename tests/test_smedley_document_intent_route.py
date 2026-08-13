"""t_e2207f21: document-intent routes to RAG; pure source → absolute sidecar URLs.

Contract:
  1. Natural-language find/pull/open/provide/link document asks are routed to
     retrieveFromComposer (RAG retrieve), not ordinary chat.
  2. corpusUrlForSource (source alone) emits absolute canonical sidecar URLs
     using Smedley's WebUI origin — never relative-only /api when origin is
     known, and never http://192.168.0.15:8789.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.js_source_extract import extract_function

LIVE_EXT = (
    Path.home()
    / ".hermes"
    / "webui"
    / "extensions"
    / "smedley-engineering"
    / "smedley-engineering.v0.2.5.js"
)

FORBIDDEN_LAN = "192.168.0.15:8789"


def _src() -> str:
    assert LIVE_EXT.is_file(), f"live extension missing: {LIVE_EXT}"
    return LIVE_EXT.read_text(encoding="utf-8")


def test_document_intent_detector_and_send_routing_present():
    src = _src()
    body = extract_function(src, "isDocumentLinkRequest")
    assert "pull|" in body or "pull" in body
    assert "find" in body
    assert "provide" in body
    assert "link" in body
    assert "document" in body.lower()
    assert "<retrieved_library_context>" in body

    install = extract_function(src, "installDocumentIntentRouting")
    assert "window.send" in install
    assert "isDocumentLinkRequest" in install
    assert "retrieveFromComposer" in install

    init = extract_function(src, "init")
    assert "installDocumentIntentRouting()" in init

    retrieve = extract_function(src, "retrieveFromComposer")
    assert "/rag/retrieve" in retrieve
    assert "buildGroundedPrompt" in retrieve


def test_pure_source_contract_absolute_sidecar_never_lan():
    """Behavioral: source alone → absolute Smedley WebUI sidecar; never :8789."""
    src = _src()
    # Slice the pure URL helpers (no DOM / RAG I/O).
    start = src.index("const RAG_PROXY = ")
    end = src.index("function rewriteCorpusHref")
    helpers = src[start:end]
    harness = f"""
const window = {{ location: {{ origin: 'http://smedley.example:9111' }} }};
{helpers}
const fromSource = corpusUrlForSource('Library/NEC/02-315.pdf');
const fromLan = normalizeCorpusSidecarUrl('http://192.168.0.15:8789/Library/NEC/note.docx');
const badOrigin = (() => {{
  window.location.origin = 'http://192.168.0.15:8789';
  return corpusUrlForSource('Library/x.pdf');
}})();
const out = {{
  fromSource,
  fromLan,
  badOrigin,
  hasForbidden: [fromSource, fromLan, badOrigin].some((v) => String(v).includes('{FORBIDDEN_LAN}')),
}};
process.stdout.write(JSON.stringify(out));
"""
    proc = subprocess.run(
        ["node", "-e", harness],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["fromSource"] == (
        "http://smedley.example:9111/api/extensions/smedley-engineering/"
        "sidecar/doc/Library/NEC/02-315.pdf"
    ), payload
    assert payload["fromLan"] == (
        "http://smedley.example:9111/api/extensions/smedley-engineering/"
        "sidecar/preview/Library/NEC/note.docx"
    ), payload
    # Fail closed: corpus-serve origin must not be promoted as WebUI origin.
    assert FORBIDDEN_LAN not in payload["badOrigin"], payload
    assert payload["badOrigin"].startswith(
        "/api/extensions/smedley-engineering/sidecar/doc/"
    ), payload
    assert payload["hasForbidden"] is False, payload


def test_grounded_prompt_forbids_lan_and_uses_canonical_helpers():
    src = _src()
    body = extract_function(src, "buildGroundedPrompt")
    assert "corpusUrlForSource" in body
    assert "normalizeCorpusSidecarUrl" in body
    assert "Never lan_url" in body or "never lan_url" in body.lower() or "NEVER emit http://192.168.0.15:8789" in body
    assert "lan_url" in body
    # Must not construct the corpus-serve absolute URL as the citation target.
    assert "http://192.168.0.15:8789/'+" not in body
    assert 'http://192.168.0.15:8789/"+rel' not in body


def test_live_extension_node_syntax():
    assert LIVE_EXT.is_file()
    proc = subprocess.run(
        ["node", "--check", str(LIVE_EXT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout

