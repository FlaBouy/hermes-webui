"""Regression: TD/desktop electrical-tool modal uses a compact two-column form."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (
    ROOT
    / "extensions"
    / "smedley-engineering"
    / "smedley-engineering.v0.2.5.css"
).read_text()
MANIFEST = (
    ROOT / "extensions" / "smedley-engineering" / "manifest.json"
).read_text()
ENGINEERING_JS = (
    ROOT
    / "extensions"
    / "smedley-engineering"
    / "smedley-engineering.v0.2.5.js"
).read_text()


def _rule_body(selector: str) -> str:
    match = re.search(
        rf"{re.escape(selector)}\{{([^}}]*)\}}",
        CSS,
    )
    assert match, f"missing CSS rule for {selector}"
    return match.group(1)


def _balanced_block(start: int) -> str:
    assert CSS[start] == "{", f"expected '{{' at {start}"
    depth = 0
    for index, char in enumerate(CSS[start:], start=start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return CSS[start + 1 : index]
    raise AssertionError("unbalanced CSS block")


def _media_block(max_width_px: int) -> str:
    marker = f"@media(max-width:{max_width_px}px)"
    start = CSS.find(marker)
    assert start >= 0, f"missing {marker}"
    brace = CSS.find("{", start)
    assert brace > start
    return _balanced_block(brace)


def test_manifest_points_at_layout_stylesheet():
    assert "smedley-engineering.v0.2.5.css" in MANIFEST


def test_desktop_form_is_compact_two_column_grid():
    form = _rule_body(".smedley-engineering-form")
    assert "display:grid" in form
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in form
    assert "overflow-y:auto" in form
    assert "min-height:0" in form


def test_action_button_and_textarea_span_form_width():
    span = _rule_body(
        ".smedley-engineering-form label:has(textarea),"
        ".smedley-engineering-form>.smedley-engineering-primary"
    )
    assert "grid-column:1/-1" in span


def test_tool_body_keeps_results_alongside_wider_form():
    body = _rule_body(".smedley-engineering-tool-body")
    assert "grid-template-columns:minmax(420px,.95fr) minmax(360px,1.1fr)" in body
    assert "340px 1fr" not in body
    assert "min-height:0" in body
    assert "overflow:hidden" in body
    result = _rule_body(".smedley-engineering-result")
    assert "min-height:0" in result
    assert "overflow:auto" in result


def test_modal_is_constrained_above_docks_with_internal_scroll_envelope():
    backdrop = _rule_body(".smedley-engineering-modal-backdrop")
    assert "inset:72px 0 68px" in backdrop
    modal = _rule_body(".smedley-engineering-modal")
    assert "display:flex" in modal
    assert "flex-direction:column" in modal
    assert "max-height:100%" in modal
    assert "overflow:hidden" in modal
    assert "min(980px" in modal


def test_midwidth_and_narrow_screens_keep_single_column_form():
    mid = _media_block(900)
    assert ".smedley-engineering-form{grid-template-columns:1fr}" in mid
    narrow = _media_block(760)
    assert ".smedley-engineering-tool-body{grid-template-columns:1fr}" in narrow
    assert "grid-template-columns:1fr" in _rule_body_from(
        narrow, ".smedley-engineering-form"
    )
    assert "max-height:42vh" in narrow


def _rule_body_from(block: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\{{([^}}]*)\}}", block)
    assert match, f"missing CSS rule for {selector} in media block"
    return match.group(1)


def test_voltage_drop_fields_remain_dense_enough_for_two_column_benefit():
    match = re.search(
        r"'voltage-drop'\s*:\s*\[(.*?)\]\s*,\s*'feeder-size'",
        ENGINEERING_JS,
        flags=re.S,
    )
    assert match, "voltage-drop field list missing"
    field_count = match.group(1).count("['")
    assert field_count >= 10, (
        "voltage-drop should keep enough fields that a single narrow column "
        "overflows at 1080p; two-column layout is the intended TD fix"
    )
    assert "RECALCULATE" in ENGINEERING_JS
    assert "smedley-engineering-primary" in ENGINEERING_JS


def test_only_one_electrical_tool_modal_can_be_open():
    assert "let activeToolClose = null" in ENGINEERING_JS
    assert "if (activeToolClose) activeToolClose();" in ENGINEERING_JS
    assert "activeToolClose = close;" in ENGINEERING_JS
    assert "if (activeToolClose === close) activeToolClose = null;" in ENGINEERING_JS
    assert "if (live && typeof live.dispose === 'function') live.dispose();" in ENGINEERING_JS


def test_voltage_drop_has_electrical_conductor_comparison_controls():
    assert "smedley-conductor-compare" in ENGINEERING_JS
    assert "◀ SMALLER" in ENGINEERING_JS
    assert "LARGER ▶" in ENGINEERING_JS
    assert "baseline_recommended_size" in ENGINEERING_JS
    assert "ampacity_pass_fail" in ENGINEERING_JS
    assert "voltage_drop_pass_fail" in ENGINEERING_JS
