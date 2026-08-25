"""Profile-local Twilio seam for Biggy's phone cockpit.

The browser never receives Twilio credentials.  With no profile config this
module is deliberately disconnected; calls and messages fail closed.
"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


_PROFILE_CONFIG = Path.home() / ".hermes" / "profiles" / "biggy" / "biggy-phone.json"
_TWILIO_BASE = "https://api.twilio.com/2010-04-01"
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def _config_path() -> Path:
    override = str(os.getenv("BIGGY_PHONE_CONFIG") or "").strip()
    return Path(override).expanduser() if override else _PROFILE_CONFIG


def _load_config() -> dict[str, Any]:
    path = _config_path()
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"_config_error": "Phone profile config is not valid JSON."}
    return value if isinstance(value, dict) else {"_config_error": "Phone profile config must be an object."}


def _safe_identity(cfg: dict[str, Any]) -> dict[str, str]:
    return {
        "device_label": str(cfg.get("device_label") or "Galaxy S25 Ultra"),
        "carrier": str(cfg.get("carrier") or "Verizon"),
    }


def _safe_contacts(cfg: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    raw_groups = cfg.get("contacts")
    raw_groups = raw_groups if isinstance(raw_groups, dict) else {}
    result: dict[str, list[dict[str, str]]] = {"EGS": [], "Personal": []}
    for label in result:
        raw_items = raw_groups.get(label)
        if not isinstance(raw_items, list):
            continue
        for item in raw_items[:100]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            try:
                number = _phone(item.get("number"), "contact number")
            except ValueError:
                continue
            result[label].append({"name": name or number, "number": number})
    return result


def _readiness(cfg: dict[str, Any]) -> tuple[bool, list[str]]:
    missing: list[str] = []
    sid = str(cfg.get("account_sid") or "").strip()
    token = str(cfg.get("auth_token") or "").strip()
    from_number = str(cfg.get("from_number") or "").strip()
    if not sid.startswith("AC"):
        missing.append("Twilio Account SID")
    if not token:
        missing.append("Twilio auth token")
    if not _E164.fullmatch(from_number):
        missing.append("Twilio E.164 phone number")
    return not missing, missing


def phone_status() -> dict[str, Any]:
    cfg = _load_config()
    ready, missing = _readiness(cfg)
    identity = _safe_identity(cfg)
    config_error = str(cfg.get("_config_error") or "")
    state = "error" if config_error else ("ready" if ready else "disconnected")
    return {
        "schema": "biggy.phone.status.v1",
        "state": state,
        "connected": ready,
        **identity,
        "sms_ready": ready,
        "voice_ready": ready and bool(str(cfg.get("voice_url") or "").strip()),
        "history_ready": ready,
        "contacts": _safe_contacts(cfg),
        "missing": missing,
        "error": config_error or None,
        "config_path_hint": "~/.hermes/profiles/biggy/biggy-phone.json",
    }


def _require_ready(cfg: dict[str, Any]) -> None:
    ready, missing = _readiness(cfg)
    if not ready:
        raise RuntimeError("Phone is not connected: " + ", ".join(missing))


def _phone(value: Any, field: str = "phone number") -> str:
    text = re.sub(r"[^\d+]", "", str(value or "").strip())
    if len(re.sub(r"\D", "", text)) == 10 and not text.startswith("+"):
        text = "+1" + text
    if not _E164.fullmatch(text):
        raise ValueError(f"{field} must be a valid E.164 number")
    return text


def _twilio_request(cfg: dict[str, Any], resource: str, *, method: str = "GET", data: dict[str, Any] | None = None) -> dict[str, Any]:
    _require_ready(cfg)
    sid = str(cfg["account_sid"]).strip()
    token = str(cfg["auth_token"]).strip()
    url = f"{_TWILIO_BASE}/Accounts/{sid}/{resource.lstrip('/')}"
    body = urlencode(data).encode("utf-8") if data is not None else None
    request = Request(url, data=body, method=method)
    request.add_header("Authorization", "Basic " + base64.b64encode(f"{sid}:{token}".encode()).decode())
    request.add_header("Accept", "application/json")
    if body is not None:
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("message")
        except Exception:
            detail = None
        raise RuntimeError(str(detail or f"Twilio returned HTTP {exc.code}")) from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("Twilio is unreachable") from exc
    return payload if isinstance(payload, dict) else {}


def phone_history(limit: int = 20) -> dict[str, Any]:
    cfg = _load_config()
    _require_ready(cfg)
    page_size = max(1, min(int(limit or 20), 50))
    messages = _twilio_request(cfg, f"Messages.json?PageSize={page_size}").get("messages", [])
    calls = _twilio_request(cfg, f"Calls.json?PageSize={page_size}").get("calls", [])
    items: list[dict[str, Any]] = []
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, dict):
            continue
        items.append({
            "kind": "sms",
            "direction": str(message.get("direction") or ""),
            "from": str(message.get("from") or ""),
            "to": str(message.get("to") or ""),
            "body": str(message.get("body") or "")[:2000],
            "status": str(message.get("status") or ""),
            "date": str(message.get("date_sent") or message.get("date_created") or ""),
        })
    for call in calls if isinstance(calls, list) else []:
        if not isinstance(call, dict):
            continue
        items.append({
            "kind": "call",
            "direction": str(call.get("direction") or ""),
            "from": str(call.get("from") or ""),
            "to": str(call.get("to") or ""),
            "status": str(call.get("status") or ""),
            "duration": str(call.get("duration") or ""),
            "date": str(call.get("start_time") or call.get("date_created") or ""),
        })
    items.sort(key=lambda item: str(item.get("date") or ""), reverse=True)
    return {"schema": "biggy.phone.history.v1", "items": items[:page_size]}


def send_sms(body: dict[str, Any]) -> dict[str, Any]:
    if body.get("confirmed") is not True:
        raise PermissionError("explicit confirmation is required before sending a text")
    cfg = _load_config()
    text = str(body.get("body") or "").strip()
    if not text:
        raise ValueError("message body is required")
    if len(text) > 1600:
        raise ValueError("message body is too long")
    payload = _twilio_request(cfg, "Messages.json", method="POST", data={
        "To": _phone(body.get("to"), "recipient"),
        "From": _phone(cfg.get("from_number"), "Twilio number"),
        "Body": text,
    })
    return {"schema": "biggy.phone.sms.v1", "ok": True, "sid": str(payload.get("sid") or ""), "status": str(payload.get("status") or "queued")}


def start_call(body: dict[str, Any]) -> dict[str, Any]:
    if body.get("confirmed") is not True:
        raise PermissionError("explicit confirmation is required before starting a call")
    cfg = _load_config()
    voice_url = str(cfg.get("voice_url") or "").strip()
    if not voice_url.startswith("https://"):
        raise RuntimeError("Phone voice is not configured with an HTTPS TwiML URL")
    payload = _twilio_request(cfg, "Calls.json", method="POST", data={
        "To": _phone(body.get("to"), "recipient"),
        "From": _phone(cfg.get("voice_from_number") or cfg.get("from_number"), "Twilio number"),
        "Url": voice_url,
    })
    return {"schema": "biggy.phone.call.v1", "ok": True, "sid": str(payload.get("sid") or ""), "status": str(payload.get("status") or "queued")}
