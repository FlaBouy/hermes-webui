#!/usr/bin/env python3
"""Static regression check: rewriteCorpusAnchors must not unconditionally set href.

installCorpusLinkFix observes href mutations on #msgInner and calls
rewriteCorpusAnchors. An unguarded a.setAttribute('href', next) retriggers the
observer forever (Chrome RESULT_CODE_HUNG on corpus-link conversations).

This validator fails closed if rewriteCorpusAnchors contains an unguarded
href write. It also self-checks that a known-bad fixture is rejected.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

EXT_DIR = Path(__file__).resolve().parent
DEFAULT_TARGET = EXT_DIR / "smedley-engineering.v0.2.5.js"

UNGUARDED_FIXTURE = """
function rewriteCorpusAnchors(root){
  scope.querySelectorAll('a[href]').forEach((a)=>{
    const next=rewriteCorpusHref(a.getAttribute('href')||a.href);
    if(!next) return;
    a.setAttribute('href', next);
  });
}
"""


def extract_function(js: str, name: str) -> str:
    marker = f"function {name}("
    start = js.find(marker)
    if start < 0:
        raise AssertionError(f"{name} not found")
    brace = js.find("{", start)
    if brace < 0:
        raise AssertionError(f"{name} opening brace not found")
    depth = 1
    i = brace + 1
    while i < len(js) and depth:
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
        i += 1
    if depth != 0:
        raise AssertionError(f"{name} braces unbalanced")
    return js[start:i]


def assert_href_rewrite_idempotent(fn_src: str, label: str) -> None:
    """Fail if setAttribute('href', ...) runs without an inequality guard."""
    compact = re.sub(r"\s+", " ", fn_src)
    writes = list(
        re.finditer(r"""\.setAttribute\(\s*['"]href['"]\s*,\s*([^)]+)\)""", compact)
    )
    if not writes:
        raise AssertionError(f"{label}: no setAttribute('href', ...) in rewriteCorpusAnchors")

    for m in writes:
        window_start = max(0, m.start() - 120)
        window = compact[window_start : m.end()]
        guarded = bool(
            re.search(
                r"""if\s*\(\s*\(\s*a\.getAttribute\(\s*['"]href['"]\s*\)\s*\|\|\s*['"]['"]\s*\)\s*!==\s*next\s*\)""",
                window,
            )
            or re.search(r"""if\s*\(\s*next\s*!==\s*(?:cur|raw|prev)\s*\)""", window)
            or re.search(r"""if\s*\(\s*(?:cur|raw|prev)\s*!==\s*next\s*\)""", window)
        )
        if not guarded:
            raise AssertionError(
                f"{label}: unguarded href setAttribute would self-trigger "
                f"MutationObserver — snippet: {window[-160:]!r}"
            )


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else DEFAULT_TARGET
    if not target.is_file():
        print(f"FAIL: missing {target}", file=sys.stderr)
        return 2

    try:
        assert_href_rewrite_idempotent(UNGUARDED_FIXTURE, "unguarded-fixture")
    except AssertionError:
        pass
    else:
        print("FAIL: validator accepted unguarded fixture", file=sys.stderr)
        return 1

    js = target.read_text(encoding="utf-8")
    if "attributeFilter:['href']" not in js and 'attributeFilter:["href"]' not in js:
        print("FAIL: installCorpusLinkFix href observer not found", file=sys.stderr)
        return 1
    if "function rewriteCorpusAnchors" not in js or "function installCorpusLinkFix" not in js:
        print("FAIL: required corpus-link functions missing", file=sys.stderr)
        return 1

    fn = extract_function(js, "rewriteCorpusAnchors")
    assert_href_rewrite_idempotent(fn, target.name)
    print(f"PASS: {target.name} rewriteCorpusAnchors href writes are idempotent-guarded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
