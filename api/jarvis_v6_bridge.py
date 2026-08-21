"""Same-origin Jarvis V6 bridge for the Biggy GUI.

The browser talks only to Biggy (`/api/biggy/v6/*`). This adapter proxies a
narrow allowlist to the local Jarvis V6 service. Upstream must be loopback.
Config is local-only (never commit keys or config.json).
"""

from __future__ import annotations

import json
import logging
import os
import socket
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:4719"
DEFAULT_HEALTH_TIMEOUT_S = 3.0
DEFAULT_CHAT_TIMEOUT_S = 120.0
MAX_QUESTION_CHARS = 8000
MAX_CONTEXT_FIELD_CHARS = 500
MAX_BODY_BYTES = 64 * 1024

ALLOWED_UPSTREAM = frozenset(
    {
        ("GET", "/api/model"),
        ("GET", "/api/status"),
        ("POST", "/chat"),
    }
)

_PROFILE_CONFIG = Path.home() / ".hermes" / "profiles" / "biggy" / "jarvis-v6-bridge.json"
_REPO_LOCAL_CONFIG = Path(__file__).resolve().parents[1] / "jarvis-v6-bridge.local.json"


class JarvisBridge:
    """Loopback-only proxy onto Jarvis V6 health/status and /chat."""

    def __init__(self, base_url: str | None = None) -> None:
        cfg = load_bridge_config()
        raw = (base_url or cfg.get("base_url") or DEFAULT_BASE_URL).strip()
        self.base_url = raw.rstrip("/")
        self.health_timeout_s = _positive_float(
            cfg.get("health_timeout_s"), DEFAULT_HEALTH_TIMEOUT_S
        )
        self.chat_timeout_s = _positive_float(
            cfg.get("chat_timeout_s"), DEFAULT_CHAT_TIMEOUT_S
        )
        self._upstream_error = _validate_loopback_base(self.base_url)

    def health(self) -> tuple[dict[str, Any], int]:
        if self._upstream_error:
            return _payload(
                state="error",
                online=False,
                error=self._upstream_error,
                base_url_safe=_safe_base(self.base_url),
            ), 503
        status, body, err, kind = self._request(
            "GET", "/api/model", timeout_s=self.health_timeout_s
        )
        if kind == "offline":
            return _payload(
                state="offline",
                online=False,
                error=err or "Jarvis V6 is offline",
                http_status=status,
                base_url_safe=_safe_base(self.base_url),
            ), 200
        if err or status != 200 or not isinstance(body, dict):
            return _payload(
                state="error",
                online=False,
                error=err or f"Jarvis V6 health failed (HTTP {status})",
                http_status=status,
                base_url_safe=_safe_base(self.base_url),
            ), 200
        model = str(body.get("model") or "").strip()
        if not model:
            return _payload(
                state="error",
                online=False,
                error="Jarvis V6 /api/model did not report a model",
                http_status=status,
                upstream=body,
                base_url_safe=_safe_base(self.base_url),
            ), 200
        return _payload(
            state="online",
            online=True,
            error=None,
            http_status=status,
            model=model,
            provider=str(body.get("provider") or "").strip() or None,
            upstream=body,
            base_url_safe=_safe_base(self.base_url),
        ), 200

    def chat(
        self,
        message: str,
        *,
        session: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], int]:
        if self._upstream_error:
            return {
                "ok": False,
                "state": "error",
                "error": self._upstream_error,
                "answer": None,
            }, 503
        question = str(message or "").strip()
        if not question:
            return {"ok": False, "state": "error", "error": "empty question", "answer": None}, 400
        if len(question) > MAX_QUESTION_CHARS:
            return {
                "ok": False,
                "state": "error",
                "error": f"question exceeds {MAX_QUESTION_CHARS} characters",
                "answer": None,
            }, 400
        composed = compose_question(question, context)
        payload = {
            "question": composed,
            "session": str(session or "biggy-v6").strip() or "biggy-v6",
        }
        status, body, err, kind = self._request(
            "POST",
            "/chat",
            timeout_s=self.chat_timeout_s,
            json_body=payload,
        )
        if kind == "offline":
            return {
                "ok": False,
                "state": "offline",
                "error": err or "Jarvis V6 is offline",
                "answer": None,
                "http_status": status,
            }, 200
        if err or status != 200 or not isinstance(body, dict):
            return {
                "ok": False,
                "state": "error",
                "error": err or f"Jarvis V6 /chat failed (HTTP {status})",
                "answer": None,
                "http_status": status,
            }, 200
        if body.get("error"):
            return {
                "ok": False,
                "state": "error",
                "error": str(body.get("error")),
                "answer": None,
                "http_status": status,
            }, 200
        answer = str(body.get("answer") or "").strip()
        if not answer:
            return {
                "ok": False,
                "state": "error",
                "error": "Jarvis V6 returned an empty answer",
                "answer": None,
                "http_status": status,
            }, 200
        return {
            "ok": True,
            "state": "online",
            "error": None,
            "answer": answer,
            "http_status": status,
            "model": body.get("model"),
        }, 200

    def _request(
        self,
        method: str,
        path: str,
        *,
        timeout_s: float,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, Any, str | None, str]:
        method = method.upper()
        if (method, path) not in ALLOWED_UPSTREAM:
            return 403, None, f"upstream path not allowlisted: {method} {path}", "error"
        url = self.base_url + path
        data = None
        headers = {"Accept": "application/json"}
        if json_body is not None:
            raw = json.dumps(json_body).encode("utf-8")
            if len(raw) > MAX_BODY_BYTES:
                return 413, None, "request too large", "error"
            data = raw
            headers["Content-Type"] = "application/json"
        req = Request(url, data=data, method=method, headers=headers)
        try:
            with urlopen(req, timeout=timeout_s) as resp:
                raw_body = resp.read(MAX_BODY_BYTES + 1)
                if len(raw_body) > MAX_BODY_BYTES:
                    return 502, None, "Jarvis V6 response too large", "error"
                parsed = _parse_json(raw_body)
                return int(getattr(resp, "status", 200) or 200), parsed, None, "ok"
        except socket.timeout:
            return 0, None, f"Jarvis V6 timed out after {timeout_s:.0f}s", "offline"
        except TimeoutError:
            return 0, None, f"Jarvis V6 timed out after {timeout_s:.0f}s", "offline"
        except HTTPError as exc:
            raw_body = b""
            try:
                raw_body = exc.read(MAX_BODY_BYTES)
            except Exception:
                pass
            parsed = _parse_json(raw_body) if raw_body else None
            detail = ""
            if isinstance(parsed, dict) and parsed.get("error"):
                detail = str(parsed.get("error"))
            return int(exc.code or 0), parsed, detail or f"HTTP {exc.code}", "error"
        except URLError as exc:
            reason = str(getattr(exc, "reason", exc) or exc)
            return 0, None, f"Jarvis V6 unreachable ({reason})", "offline"
        except OSError as exc:
            return 0, None, f"Jarvis V6 unreachable ({exc})", "offline"
        except Exception:
            logger.exception("jarvis v6 bridge request failed")
            return 0, None, "Jarvis V6 bridge request failed", "error"


def load_bridge_config() -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for path in (_PROFILE_CONFIG, _REPO_LOCAL_CONFIG):
        data = _read_json_file(path)
        if isinstance(data, dict):
            merged.update(data)
    env_url = (os.environ.get("JARVIS_V6_BASE_URL") or "").strip()
    if env_url:
        merged["base_url"] = env_url
    return merged


def compose_question(message: str, context: dict[str, Any] | None) -> str:
    envelope = slim_context(context)
    if not envelope:
        return message
    lines = ["Biggy context (identifiers only — no files, vaults, or credentials):"]
    for key in ("project_id", "display_name", "workspace_name", "synopsis"):
        value = envelope.get(key)
        if value:
            lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n\n" + message


def slim_context(context: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(context, dict):
        return {}
    out: dict[str, str] = {}
    for key in ("project_id", "display_name", "workspace_name", "synopsis"):
        value = str(context.get(key) or "").strip()
        if value:
            out[key] = value[:MAX_CONTEXT_FIELD_CHARS]
    return out


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except OSError:
        return None
    except json.JSONDecodeError:
        logger.warning("jarvis v6 bridge config is not valid JSON: %s", path)
        return None


def _validate_loopback_base(base: str) -> str | None:
    try:
        parsed = urlparse(base)
    except Exception:
        return "invalid Jarvis V6 base URL"
    if parsed.scheme not in {"http", "https"}:
        return "Jarvis V6 base URL must be http(s)"
    host = (parsed.hostname or "").strip().lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return "Jarvis V6 base URL must be loopback"
    if parsed.username or parsed.password:
        return "Jarvis V6 base URL must not include credentials"
    if parsed.path not in {"", "/"}:
        return "Jarvis V6 base URL must not include a path"
    return None


def _safe_base(base: str) -> str:
    try:
        parsed = urlparse(base)
        host = parsed.hostname or ""
        port = parsed.port
        if port:
            return f"{parsed.scheme}://{host}:{port}"
        return f"{parsed.scheme}://{host}"
    except Exception:
        return "loopback"


def _positive_float(value: Any, default: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return n if n > 0 else default


def _parse_json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8") or "null")
    except Exception:
        return None


def _payload(**kwargs: Any) -> dict[str, Any]:
    body = {
        "schema": "biggy.jarvis_v6_health.v1",
        "service": "jarvis-v6",
    }
    body.update(kwargs)
    return body
