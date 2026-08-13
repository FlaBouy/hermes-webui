"""Ephemeral OpenAI Realtime credentials for browser GPT Voice mode.

Hermes remains the conversation authority. The Realtime session is an audio
I/O layer only: short-lived client secrets are minted server-side so the
browser never sees a permanent OpenAI API key.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_OPENAI_CLIENT_SECRETS_URL = "https://api.openai.com/v1/realtime/client_secrets"
_DEFAULT_MODEL = "gpt-realtime"
_DEFAULT_VOICE = "marin"
_AUDIO_IO_INSTRUCTIONS = (
    "You are a low-latency speech interface for Hermes WebUI. "
    "Hermes is the sole assistant and conversation authority. "
    "Never answer the user's questions yourself. Never invent facts, "
    "never call tools, and never start a separate conversation. "
    "When the user finishes speaking, remain silent and wait. "
    "When you are given Hermes reply text to speak, read that text aloud "
    "verbatim, then stop."
)


class RealtimeConfigError(ValueError):
    """Server-side configuration prevents minting a session (fail closed)."""

    category = "configuration"


class RealtimeUpstreamError(RuntimeError):
    """OpenAI rejected or could not serve the session-create request."""

    category = "session"

    def __init__(self, message: str, *, category: str = "session"):
        super().__init__(message)
        self.category = category


def error_category(exc: BaseException) -> str:
    """Best-effort category for a realtime failure: configuration | session."""
    category = getattr(exc, "category", None)
    if isinstance(category, str) and category:
        return category
    return "configuration" if isinstance(exc, ValueError) else "session"


def _env_flag(name: str) -> bool | None:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return None
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


def realtime_voice_env_enabled() -> bool:
    """Kill-switch / force-enable from process env. Default: allowed."""
    flag = _env_flag("HERMES_WEBUI_GPT_REALTIME_VOICE")
    return True if flag is None else flag


def resolve_openai_api_key() -> str:
    """Resolve a server-side OpenAI key without exposing it to callers."""
    for name in ("VOICE_TOOLS_OPENAI_KEY", "OPENAI_API_KEY", "HERMES_OPENAI_API_KEY"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    try:
        from api.onboarding import _load_env_file
        from api.profiles import get_active_hermes_home

        env_cfg = _load_env_file(get_active_hermes_home() / ".env")
        if isinstance(env_cfg, dict):
            for name in ("VOICE_TOOLS_OPENAI_KEY", "OPENAI_API_KEY", "HERMES_OPENAI_API_KEY"):
                value = str(env_cfg.get(name) or "").strip()
                if value:
                    return value
    except Exception:
        logger.debug("realtime_voice: hermes .env key lookup failed", exc_info=True)
    return ""


def realtime_voice_status() -> dict[str, Any]:
    """Capability probe for the UI (no secrets)."""
    env_ok = realtime_voice_env_enabled()
    key_present = bool(resolve_openai_api_key())
    return {
        "ok": True,
        "enabled": bool(env_ok and key_present),
        "env_enabled": env_ok,
        "api_key_configured": key_present,
        "model": os.getenv("HERMES_WEBUI_GPT_REALTIME_MODEL", _DEFAULT_MODEL).strip()
        or _DEFAULT_MODEL,
        "voice": os.getenv("HERMES_WEBUI_GPT_REALTIME_VOICE_NAME", _DEFAULT_VOICE).strip()
        or _DEFAULT_VOICE,
    }


def _session_config() -> dict[str, Any]:
    model = (
        os.getenv("HERMES_WEBUI_GPT_REALTIME_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
    )
    voice = (
        os.getenv("HERMES_WEBUI_GPT_REALTIME_VOICE_NAME", _DEFAULT_VOICE).strip()
        or _DEFAULT_VOICE
    )
    # turn_detection lives under audio.input in the GA Realtime schema.
    # PTT default uses server_vad with a very long silence window so natural
    # pauses do not end the turn, while input transcription stays enabled.
    # (turn_detection=null + a partial session.update previously wiped
    # transcription and produced commits with no transcripts.)
    # create_response=false keeps Hermes as the only answerer.
    return {
        "type": "realtime",
        "model": model,
        "instructions": _AUDIO_IO_INSTRUCTIONS,
        "audio": {
            "input": {
                "transcription": {"model": "gpt-4o-mini-transcribe"},
                "turn_detection": {
                    "type": "server_vad",
                    "create_response": False,
                    "interrupt_response": True,
                    "silence_duration_ms": 10000,
                    "prefix_padding_ms": 300,
                },
            },
            "output": {"voice": voice},
        },
    }


def _summarize_upstream_error(detail: str) -> str:
    """Pull the human-readable message out of an OpenAI error body."""
    try:
        parsed = json.loads(detail)
        message = parsed.get("error", {}).get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()[:200]
    except Exception:
        pass
    return (detail or "no detail").strip()[:200]


def _safety_identifier(seed: str | None) -> str:
    raw = (seed or "anonymous").strip() or "anonymous"
    return hashlib.sha256(f"hermes-webui-gpt-voice:{raw}".encode("utf-8")).hexdigest()[:32]


def create_ephemeral_client_secret(*, safety_seed: str | None = None) -> dict[str, Any]:
    """Mint a short-lived Realtime client secret for the browser.

    Raises ValueError for fail-closed configuration errors and RuntimeError for
    upstream failures. Never returns the permanent API key.
    """
    if not realtime_voice_env_enabled():
        raise RealtimeConfigError(
            "GPT Realtime Voice is disabled by HERMES_WEBUI_GPT_REALTIME_VOICE"
        )
    api_key = resolve_openai_api_key()
    if not api_key:
        raise RealtimeConfigError("OpenAI API key not configured for GPT Realtime Voice")

    body = json.dumps({"session": _session_config()}).encode("utf-8")
    req = urllib.request.Request(
        _OPENAI_CLIENT_SECRETS_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "OpenAI-Safety-Identifier": _safety_identifier(safety_seed),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            detail = str(exc)
        logger.warning("realtime client_secrets HTTP %s: %s", exc.code, detail)
        # 4xx other than rate limiting means our key or session config is wrong,
        # which the operator fixes in server config rather than by retrying.
        if exc.code in (400, 401, 403, 404, 422):
            raise RealtimeUpstreamError(
                f"OpenAI rejected the Realtime session config ({exc.code}): "
                f"{_summarize_upstream_error(detail)}",
                category="configuration",
            ) from exc
        raise RealtimeUpstreamError(
            f"OpenAI Realtime session create failed ({exc.code})"
        ) from exc
    except Exception as exc:
        logger.exception("realtime client_secrets request failed")
        raise RealtimeUpstreamError(
            "Could not reach OpenAI to create the Realtime session"
        ) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RealtimeUpstreamError("OpenAI Realtime session returned invalid JSON") from exc

    value = data.get("value") if isinstance(data, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise RealtimeUpstreamError("OpenAI Realtime session missing ephemeral value")

    expires_at = data.get("expires_at") if isinstance(data, dict) else None
    session = data.get("session") if isinstance(data, dict) else None
    return {
        "ok": True,
        "value": value.strip(),
        "expires_at": expires_at,
        "session": session if isinstance(session, dict) else None,
        "model": _session_config()["model"],
        "voice": _session_config()["audio"]["output"]["voice"],
        "upstream_status": status,
    }
