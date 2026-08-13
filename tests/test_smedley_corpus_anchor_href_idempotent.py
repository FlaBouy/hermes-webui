"""t_bb80c128: rewriteCorpusAnchors must not unconditionally rewrite href.

installCorpusLinkFix observes href attribute mutations. An unconditional
setAttribute('href', next) re-fires the observer and hangs Chrome. The live
extension must calculate the current raw href and call setAttribute only when
it differs from next.
"""
from __future__ import annotations

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


def test_rewrite_corpus_anchors_href_setattribute_is_idempotent():
    assert LIVE_EXT.is_file(), f"live extension missing: {LIVE_EXT}"
    src = LIVE_EXT.read_text(encoding="utf-8")
    body = extract_function(src, "rewriteCorpusAnchors")

    assert "const raw=a.getAttribute('href')||a.href;" in body
    assert "const next=rewriteCorpusHref(raw);" in body
    assert "if(raw !== next) a.setAttribute('href', next);" in body
    # Reject the self-triggering unconditional write.
    assert "if(!next) return;\n      a.setAttribute('href', next);" not in body
