"""Thirty-day, strategy-only durable learning for Jarvis II PA.

This store intentionally contains no user prompts, answers, document text,
citations, credentials, URLs, or cached retrieval results.  It only lets the
PA learn which approved tool/provider combinations produced verified evidence.
Every factual request must still make a fresh tool call and fresh verification.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


RETENTION_DAYS = 30
_LOCK = threading.Lock()
_DEFAULT_PATH = Path("/Users/rick/.hermes/profiles/biggy/memories/jarvis-pa-strategy.json")
_ALLOWED_TOOLS = frozenset({
    "rag_core", "weather", "maps", "lodging_poi", "calendar_read", "gmail_read", "research",
})
_ALLOWED_OUTCOMES = frozenset({"verified", "unverified", "not_found", "transport_error"})


def _path() -> Path:
    return Path(os.environ.get("JARVIS_PA_STRATEGY_MEMORY_PATH") or _DEFAULT_PATH)


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_stamp(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_active() -> list[dict[str, str]]:
    try:
        payload = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("records") if isinstance(payload, dict) else []
    cutoff = _now()
    active: list[dict[str, str]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        expires = _parse_stamp(row.get("expires_at"))
        if not expires or expires <= cutoff:
            continue
        tool, outcome = str(row.get("tool") or ""), str(row.get("outcome") or "")
        if tool not in _ALLOWED_TOOLS or outcome not in _ALLOWED_OUTCOMES:
            continue
        active.append({
            "recorded_at": str(row.get("recorded_at") or ""),
            "expires_at": _stamp(expires),
            "tool": tool,
            "provider": str(row.get("provider") or "unknown")[:80],
            "outcome": outcome,
            "evidence_status": str(row.get("evidence_status") or "unknown")[:80],
        })
    return active


def _save(rows: list[dict[str, str]]) -> None:
    target = _path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "jarvis.pa.strategy_memory.v1",
        "retention_days": RETENTION_DAYS,
        "records": rows[-240:],
    }
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
        json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
        handle.write("\n")
        temp_name = handle.name
    os.replace(temp_name, target)


def record_outcome(*, tools: list[Any], outcome: str, provider: str, evidence_status: str) -> int:
    """Persist a sanitized result for each approved tool, expiring in 30 days."""
    normalized_tools = sorted({str(tool) for tool in tools if str(tool) in _ALLOWED_TOOLS})
    if not normalized_tools or outcome not in _ALLOWED_OUTCOMES:
        return 0
    now = _now()
    row_base = {
        "recorded_at": _stamp(now),
        "expires_at": _stamp(now + timedelta(days=RETENTION_DAYS)),
        "provider": str(provider or "unknown")[:80],
        "outcome": outcome,
        "evidence_status": str(evidence_status or "unknown")[:80],
    }
    with _LOCK:
        rows = _load_active()
        for tool in normalized_tools:
            rows.append({**row_base, "tool": tool})
        _save(rows)
    return len(normalized_tools)


def purge_records(*, tools: list[str], provider: str | None = None) -> int:
    """Remove known-invalid strategy rows without exposing their contents."""
    target_tools = {str(tool) for tool in tools}
    if not target_tools:
        return 0
    with _LOCK:
        rows = _load_active()
        kept = [
            row for row in rows
            if not (row["tool"] in target_tools and (provider is None or row["provider"] == provider))
        ]
        removed = len(rows) - len(kept)
        if removed:
            _save(kept)
    return removed


def strategy_context() -> dict[str, Any]:
    """Return an aggregate-only context block safe to show the decision agent."""
    with _LOCK:
        rows = _load_active()
    summary: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {"verified": 0, "other": 0})
    for row in rows:
        item = summary[(row["tool"], row["provider"])]
        if row["outcome"] == "verified":
            item["verified"] += 1
        else:
            item["other"] += 1
    strategies = [
        {"tool": tool, "provider": provider, **counts}
        for (tool, provider), counts in sorted(summary.items())
    ]
    return {
        "schema": "jarvis.pa.strategy_context.v1",
        "retention_days": RETENTION_DAYS,
        "record_count": len(rows),
        "strategies": strategies[:32],
        "rule": "Strategy hints may guide approved tool selection only. They never replace a fresh tool call or fresh evidence verification.",
    }
