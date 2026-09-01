"""Biggy Smedley project-review dialog shows owner/prose only, not raw tool JSON."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_extract import extract_function

ROOT = Path(__file__).resolve().parents[1]
BRAND_JS = ROOT / "static" / "biggy-brand.js"
NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _helpers_src() -> str:
    src = BRAND_JS.read_text(encoding="utf-8")
    names = [
        "biggyProjectReviewMessageText",
        "biggyProjectReviewOwnerVisibleText",
        "biggyProjectReviewTryParseJson",
        "biggyProjectReviewIsInternalPayload",
        "biggyProjectReviewProgressSummary",
        "formatBiggyProjectReviewDialogTurns",
    ]
    return "\n".join(extract_function(src, name) for name in names)


def test_render_dialog_uses_filtered_turns():
    src = BRAND_JS.read_text(encoding="utf-8")
    assert "formatBiggyProjectReviewDialogTurns(messages)" in src
    assert "biggyProjectReviewProgressSummary" in src
    render = src[src.index("const renderDialog = (payload)"):src.index("const refreshDialog = async")]
    assert "messages.map((message)" not in render
    assert "turns.map((turn)" in render


@requires_node
def test_dialog_filter_keeps_owner_and_prose_summarizes_todos_suppresses_internals():
    helpers = _helpers_src()
    sample = [
        {
            "role": "user",
            "content": (
                "You are Smedley, Senior Engineer reporting to Biggy.\n"
                "Project: Auburn MCC\n\n"
                "Owner message: Please check feeder sizing against NEC."
            ),
        },
        {"role": "assistant", "content": ""},
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "todos": [
                        {"id": "1", "content": "Confirm feeder ampacity basis", "status": "completed"},
                        {"id": "2", "content": "Check voltage drop at 480 V", "status": "in_progress"},
                        {"id": "3", "content": "Flag approval implications", "status": "pending"},
                    ],
                    "summary": {"total": 3, "completed": 1, "in_progress": 1, "pending": 1, "cancelled": 0},
                }
            ),
        },
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "approval_id": "appr_1",
                    "command": "cat /etc/passwd",
                    "description": "Read host secrets",
                }
            ),
        },
        {
            "role": "tool",
            "content": json.dumps({"ok": True, "result": {"amps": 42}}),
        },
        {
            "role": "assistant",
            "content": json.dumps({"name": "voltage_drop", "arguments": {"voltage": 480}}),
        },
        {
            "role": "assistant",
            "content": "Feeder appears undersized for continuous load at 480 V. Recommend upsizing to 3/0 Cu.",
        },
        {"role": "assistant", "content": "   "},
        {"role": "assistant", "tool_only": True, "content": "hidden tool residue"},
    ]
    harness = f"""
{helpers}
const messages = {json.dumps(sample)};
const turns = formatBiggyProjectReviewDialogTurns(messages);
process.stdout.write(JSON.stringify(turns));
"""
    proc = subprocess.run(
        [NODE, "-e", harness],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    turns = json.loads(proc.stdout)
    assert [turn["role"] for turn in turns] == ["owner", "smedley", "smedley"], turns
    assert turns[0]["content"] == "Please check feeder sizing against NEC."
    assert "You are Smedley" not in turns[0]["content"]
    assert turns[1]["kind"] == "progress"
    assert "Review progress" in turns[1]["content"]
    assert "Confirm feeder ampacity basis" in turns[1]["content"]
    assert "Check voltage drop at 480 V" in turns[1]["content"]
    assert "approval_id" not in json.dumps(turns).lower()
    assert "cat /etc/passwd" not in json.dumps(turns)
    assert "voltage_drop" not in json.dumps(turns)
    assert turns[2]["kind"] == "prose"
    assert "Recommend upsizing to 3/0 Cu" in turns[2]["content"]
    assert not any(not str(turn.get("content") or "").strip() for turn in turns)


@requires_node
def test_biggy_brand_syntax():
    proc = subprocess.run(
        [NODE, "--check", str(BRAND_JS)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
