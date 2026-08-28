"""Durable, operator-owned settings for the Biggy cockpit."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any


_SETTINGS_PATH = Path.home() / ".config" / "argus" / "biggy-operator-settings.json"
_LOCK = RLock()
_DEFAULTS = {"speech_sync_gain": 1.1, "speech_sync_lead_ms": 80}


def _clamp_number(value: Any, *, low: float, high: float, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = fallback
    return max(low, min(high, number))


def _normalized(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    return {
        "schema": "biggy.operator_settings.v1",
        "speech_sync_gain": _clamp_number(
            source.get("speech_sync_gain"), low=0.5, high=2.0,
            fallback=_DEFAULTS["speech_sync_gain"],
        ),
        "speech_sync_lead_ms": int(round(_clamp_number(
            source.get("speech_sync_lead_ms"), low=-250, high=300,
            fallback=_DEFAULTS["speech_sync_lead_ms"],
        ))),
    }


def read_operator_settings() -> dict[str, Any]:
    """Read the durable settings, returning bounded defaults on any damage."""
    with _LOCK:
        try:
            payload = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            payload = {}
        return _normalized(payload)


def write_operator_settings(payload: dict[str, Any]) -> dict[str, Any]:
    """Atomically persist the cockpit settings shared by every Biggy browser."""
    current = read_operator_settings()
    merged = _normalized({**current, **(payload if isinstance(payload, dict) else {})})
    with _LOCK:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=".biggy-operator-settings-", suffix=".json", dir=_SETTINGS_PATH.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(merged, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, _SETTINGS_PATH)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
    return merged
