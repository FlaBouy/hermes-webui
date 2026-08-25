"""Profile-scoped Google PA sources and guarded write actions for Biggy.

Credentials remain under ``HERMES_HOME`` and are never returned to the
browser.  Mail is draft-first: creating a draft is separate from the explicit,
confirmed send action.  Calendar writes are validated here and destructive
actions require an explicit confirmation flag.
"""

from __future__ import annotations

import base64
import copy
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.utils import getaddresses, parseaddr
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


_CACHE_TTL = 30.0
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_LOCK = threading.Lock()

GMAIL_READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
REQUIRED_WRITE_SCOPES = frozenset((GMAIL_COMPOSE_SCOPE, CALENDAR_EVENTS_SCOPE))
_SAFE_GOOGLE_ID = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
_SAFE_ZIP = re.compile(r"^\d{5}$")
_WEATHER_CACHE_TTL = 600.0
_WEATHER_LAST_GOOD: dict[str, dict[str, Any]] = {}
_HAL_WEATHER_URL = "http://192.168.0.13:8088/weather_status.json"
_WEATHER_USER_AGENT = "Biggy-ARGUS/1.0 (local weather card)"


def _hermes_home() -> Path:
    value = os.environ.get("HERMES_HOME", "").strip()
    return Path(value) if value else Path.home() / ".hermes"


def _google_paths() -> tuple[Path, Path, Path]:
    home = _hermes_home()
    script = home / "skills" / "productivity" / "google-workspace" / "scripts" / "google_api.py"
    return script, home / "google_token.json", home / "google_client_secret.json"


def _connection_payload() -> dict[str, Any]:
    script, token, client = _google_paths()
    connected = script.is_file() and token.is_file()
    reason = "connected" if connected else ("missing_token" if script.is_file() else "skill_unavailable")
    return {
        "connected": connected,
        "reason": reason,
        "oauth_ready": client.is_file(),
        "profile": _hermes_home().name,
        "write_ready": connected and not _missing_write_scopes(),
        "missing_write_scopes": _missing_write_scopes() if connected else [],
    }


def _token_payload() -> dict[str, Any]:
    _script, token, _client = _google_paths()
    try:
        payload = json.loads(token.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _token_scopes() -> set[str]:
    payload = _token_payload()
    raw = payload.get("scopes") or payload.get("scope") or []
    if isinstance(raw, str):
        return {scope for scope in raw.split() if scope}
    if isinstance(raw, list):
        return {str(scope) for scope in raw if str(scope).strip()}
    return set()


def _missing_write_scopes() -> list[str]:
    return sorted(REQUIRED_WRITE_SCOPES - _token_scopes())


def _invalidate(*keys: str) -> None:
    with _LOCK:
        for key in keys:
            _CACHE.pop(key, None)


def _google_service(api: str, version: str):
    """Build an authenticated Google service without exposing credentials."""
    _script, token, _client = _google_paths()
    if not token.is_file():
        raise RuntimeError("Google authorization is required")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except Exception as exc:  # pragma: no cover - depends on optional runtime extra
        raise RuntimeError("Google Workspace runtime is unavailable") from exc

    scopes = sorted(_token_scopes()) or None
    creds = Credentials.from_authorized_user_file(str(token), scopes=scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        refreshed = json.loads(creds.to_json())
        refreshed["type"] = refreshed.get("type") or "authorized_user"
        tmp = token.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(refreshed, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, token)
    if not creds.valid:
        raise RuntimeError("Google authorization must be refreshed")
    return build(api, version, credentials=creds, cache_discovery=False)


def _require_scope(scope: str) -> None:
    if scope not in _token_scopes():
        raise PermissionError("Google authorization must be upgraded before this action is available")


def _clean_text(value: Any, name: str, *, maximum: int, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{name} is required")
    if len(text) > maximum:
        raise ValueError(f"{name} is too long")
    return text


def _safe_id(value: Any, name: str) -> str:
    item_id = _clean_text(value, name, maximum=256, required=True)
    if not _SAFE_GOOGLE_ID.fullmatch(item_id):
        raise ValueError(f"invalid {name}")
    return item_id


def _email_list(value: Any, name: str, *, required: bool = False) -> list[str]:
    raw = _clean_text(value, name, maximum=4096, required=required)
    if not raw:
        return []
    addresses = [address.strip() for _display, address in getaddresses([raw]) if address.strip()]
    if not addresses or len(addresses) > 20:
        raise ValueError(f"invalid {name}")
    for address in addresses:
        parsed = parseaddr(address)[1]
        if parsed != address or "@" not in address or address.startswith("@") or address.endswith("@"):
            raise ValueError(f"invalid {name}")
    return addresses


def _event_time(value: Any, name: str) -> str:
    text = _clean_text(value, name, maximum=80, required=True)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO 8601 date and time") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return text


def _cached(key: str, loader) -> dict[str, Any]:
    now = time.monotonic()
    with _LOCK:
        prior = _CACHE.get(key)
        if prior and now - prior[0] < _CACHE_TTL:
            return prior[1]
    value = loader()
    with _LOCK:
        _CACHE[key] = (now, value)
    return value


def _weather_json(url: str, *, timeout: float = 4.0) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": _WEATHER_USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"weather source unavailable: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("weather source returned an invalid response")
    return payload


def _number(value: Any) -> int | float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else round(number, 1)


def _normalize_hal_weather(payload: dict[str, Any], zip_code: str) -> dict[str, Any]:
    forecast: list[dict[str, Any]] = []
    for row in payload.get("forecast") or []:
        if not isinstance(row, dict):
            continue
        forecast.append({
            "day": str(row.get("day") or "").strip(),
            "date": str(row.get("date") or "").strip(),
            "high_f": _number(row.get("hi")),
            "low_f": _number(row.get("lo")),
            "precip_percent": _number(row.get("pop")),
            "summary": str(row.get("short") or row.get("summary") or "").strip(),
        })
    current = payload.get("current") if isinstance(payload.get("current"), dict) else {}
    if not forecast:
        raise RuntimeError("HAL weather feed returned no forecast")
    return {
        "schema": "biggy.pa.weather.v1",
        "ok": True,
        "zip": zip_code,
        "location": str(payload.get("location") or "Lynn Haven, FL"),
        "source": "HAL weather feed · National Weather Service",
        "updated": str(payload.get("updated") or ""),
        "current": {
            "temp_f": _number(current.get("temp")),
            "summary": str(current.get("cond") or current.get("summary") or "").strip(),
            "humidity_percent": _number(current.get("humidity")),
            "wind_mph": _number(current.get("wind_mph")),
        },
        "forecast": forecast[:7],
        "stale": False,
        "warning": "",
    }


def _nws_weather(zip_code: str) -> dict[str, Any]:
    postal = _weather_json(f"https://api.zippopotam.us/us/{quote(zip_code)}")
    places = postal.get("places") or []
    place = places[0] if places and isinstance(places[0], dict) else {}
    latitude = float(place.get("latitude"))
    longitude = float(place.get("longitude"))
    location = ", ".join(filter(None, (
        str(place.get("place name") or "").strip(),
        str(place.get("state abbreviation") or "").strip(),
    ))) or zip_code

    point = _weather_json(f"https://api.weather.gov/points/{latitude:.4f},{longitude:.4f}")
    properties = point.get("properties") if isinstance(point.get("properties"), dict) else {}
    forecast_url = str(properties.get("forecast") or "")
    stations_url = str(properties.get("observationStations") or "")
    if not forecast_url:
        raise RuntimeError("National Weather Service forecast is unavailable for this ZIP")

    forecast_payload = _weather_json(forecast_url)
    forecast_props = forecast_payload.get("properties") if isinstance(forecast_payload.get("properties"), dict) else {}
    periods = [row for row in (forecast_props.get("periods") or []) if isinstance(row, dict)]
    days: list[dict[str, Any]] = []
    for period in periods:
        is_day = bool(period.get("isDaytime"))
        name = str(period.get("name") or "").strip()
        if is_day or not days:
            if len(days) >= 7:
                break
            days.append({
                "day": name,
                "date": str(period.get("startTime") or "")[:10],
                "high_f": _number(period.get("temperature")) if is_day else None,
                "low_f": None if is_day else _number(period.get("temperature")),
                "precip_percent": _number((period.get("probabilityOfPrecipitation") or {}).get("value")),
                "summary": str(period.get("shortForecast") or "").strip(),
            })
            continue
        current_day = days[-1]
        current_day["low_f"] = _number(period.get("temperature"))
        night_pop = _number((period.get("probabilityOfPrecipitation") or {}).get("value"))
        if night_pop is not None:
            current_day["precip_percent"] = max(current_day.get("precip_percent") or 0, night_pop)

    current: dict[str, Any] = {"temp_f": None, "summary": "", "humidity_percent": None, "wind_mph": None}
    if stations_url:
        try:
            stations = _weather_json(stations_url)
            features = stations.get("features") or []
            station_id = ""
            if features and isinstance(features[0], dict):
                station_id = str((features[0].get("properties") or {}).get("stationIdentifier") or "")
            if station_id:
                observation = _weather_json(f"https://api.weather.gov/stations/{quote(station_id)}/observations/latest")
                obs = observation.get("properties") if isinstance(observation.get("properties"), dict) else {}
                celsius = _number((obs.get("temperature") or {}).get("value"))
                wind_kph = _number((obs.get("windSpeed") or {}).get("value"))
                current = {
                    "temp_f": round((float(celsius) * 9 / 5) + 32) if celsius is not None else None,
                    "summary": str(obs.get("textDescription") or "").strip(),
                    "humidity_percent": _number((obs.get("relativeHumidity") or {}).get("value")),
                    "wind_mph": round(float(wind_kph) * 0.621371, 1) if wind_kph is not None else None,
                }
        except Exception:
            pass
    if not days:
        raise RuntimeError("National Weather Service returned no forecast periods")
    return {
        "schema": "biggy.pa.weather.v1",
        "ok": True,
        "zip": zip_code,
        "location": location,
        "source": "National Weather Service",
        "updated": str(forecast_props.get("updated") or ""),
        "current": current,
        "forecast": days[:7],
        "stale": False,
        "warning": "",
    }


def weather_snapshot(zip_code: str = "32444") -> dict[str, Any]:
    """Return a durable 5–7 day weather card for the requested US ZIP."""
    zip_code = str(zip_code or "32444").strip()
    if not _SAFE_ZIP.fullmatch(zip_code):
        raise ValueError("ZIP must be five digits")
    cache_key = f"weather:{zip_code}"
    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(cache_key)
        if cached and now - cached[0] < _WEATHER_CACHE_TTL:
            return cached[1]
    try:
        if zip_code == "32444":
            try:
                result = _normalize_hal_weather(_weather_json(_HAL_WEATHER_URL, timeout=2.5), zip_code)
            except Exception:
                result = _nws_weather(zip_code)
        else:
            result = _nws_weather(zip_code)
        with _LOCK:
            _CACHE[cache_key] = (now, result)
            _WEATHER_LAST_GOOD[zip_code] = copy.deepcopy(result)
        return result
    except Exception as exc:
        with _LOCK:
            prior = _WEATHER_LAST_GOOD.get(zip_code)
        if prior:
            stale = dict(prior)
            stale["stale"] = True
            stale["warning"] = "Live weather refresh failed; showing the last good forecast."
            return stale
        return {
            "schema": "biggy.pa.weather.v1",
            "ok": False,
            "zip": zip_code,
            "location": zip_code,
            "source": "National Weather Service",
            "updated": "",
            "current": {},
            "forecast": [],
            "stale": False,
            "warning": "",
            "error": str(exc),
        }


def _run_google(args: list[str]) -> list[dict[str, Any]]:
    script, token, _client = _google_paths()
    if not script.is_file() or not token.is_file():
        return []
    proc = subprocess.run(
        [os.environ.get("PYTHON") or sys.executable, str(script), *args],
        cwd=str(_hermes_home()),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=12,
        check=False,
    )
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "Google source unavailable").strip().splitlines()[-1]
        raise RuntimeError(message[:240])
    raw = proc.stdout.strip()
    if not raw or raw == "No messages found.":
        return []
    data = json.loads(raw)
    return data if isinstance(data, list) else []


def mail_snapshot() -> dict[str, Any]:
    def load() -> dict[str, Any]:
        connection = _connection_payload()
        rows: list[dict[str, Any]] = []
        error = ""
        if connection["connected"]:
            try:
                for item in _run_google(["gmail", "search", "in:inbox newer_than:7d", "--max", "10"]):
                    rows.append({
                        "id": str(item.get("id") or ""),
                        "from": str(item.get("from") or ""),
                        "subject": str(item.get("subject") or "(no subject)"),
                        "date": str(item.get("date") or ""),
                        "snippet": str(item.get("snippet") or ""),
                        "unread": "UNREAD" in (item.get("labels") or []),
                    })
            except Exception as exc:
                error = str(exc)
        drafts: list[dict[str, Any]] = []
        if connection["write_ready"]:
            try:
                service = _google_service("gmail", "v1")
                result = service.users().drafts().list(userId="me", maxResults=5).execute()
                for item in result.get("drafts", []):
                    draft_id = str(item.get("id") or "")
                    message_id = str((item.get("message") or {}).get("id") or "")
                    if not draft_id:
                        continue
                    detail = service.users().drafts().get(
                        userId="me", id=draft_id, format="metadata"
                    ).execute()
                    headers = {
                        str(header.get("name") or "").lower(): str(header.get("value") or "")
                        for header in ((detail.get("message") or {}).get("payload") or {}).get("headers", [])
                    }
                    drafts.append({
                        "id": draft_id,
                        "message_id": message_id or str((detail.get("message") or {}).get("id") or ""),
                        "to": headers.get("to", ""),
                        "subject": headers.get("subject", "(no subject)"),
                        "snippet": str((detail.get("message") or {}).get("snippet") or ""),
                    })
            except Exception as exc:
                error = error or str(exc)
        return {
            "schema": "biggy.pa.mail.v2",
            **connection,
            "messages": rows,
            "drafts": drafts,
            "error": error,
        }

    return _cached("mail", load)


def calendar_snapshot() -> dict[str, Any]:
    def load() -> dict[str, Any]:
        connection = _connection_payload()
        rows: list[dict[str, Any]] = []
        error = ""
        if connection["connected"]:
            now = datetime.now(timezone.utc)
            end = now + timedelta(days=10)
            try:
                for item in _run_google([
                    "calendar", "list", "--start", now.isoformat(), "--end", end.isoformat(), "--max", "20",
                ]):
                    rows.append({
                        "id": str(item.get("id") or ""),
                        "summary": str(item.get("summary") or "(no title)"),
                        "start": str(item.get("start") or ""),
                        "end": str(item.get("end") or ""),
                        "location": str(item.get("location") or ""),
                        "description": str(item.get("description") or ""),
                        "status": str(item.get("status") or ""),
                        "url": str(item.get("htmlLink") or ""),
                    })
            except Exception as exc:
                error = str(exc)
        return {"schema": "biggy.pa.calendar.v2", **connection, "events": rows, "error": error}

    return _cached("calendar", load)


def create_mail_draft(payload: dict[str, Any]) -> dict[str, Any]:
    _require_scope(GMAIL_COMPOSE_SCOPE)
    recipients = _email_list(payload.get("to"), "to", required=True)
    cc = _email_list(payload.get("cc"), "cc")
    subject = _clean_text(payload.get("subject"), "subject", maximum=998, required=True)
    body_text = _clean_text(payload.get("body"), "body", maximum=50_000, required=True)

    message = MIMEText(body_text, "plain", "utf-8")
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    if cc:
        message["Cc"] = ", ".join(cc)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    result = _google_service("gmail", "v1").users().drafts().create(
        userId="me", body={"message": {"raw": raw}}
    ).execute()
    draft_id = _safe_id(result.get("id"), "draft_id")
    _invalidate("mail")
    return {
        "schema": "biggy.pa.mail_draft.v1",
        "ok": True,
        "status": "drafted",
        "draft": {
            "id": draft_id,
            "to": ", ".join(recipients),
            "cc": ", ".join(cc),
            "subject": subject,
            "body": body_text,
        },
    }


def send_mail_draft(payload: dict[str, Any]) -> dict[str, Any]:
    _require_scope(GMAIL_COMPOSE_SCOPE)
    draft_id = _safe_id(payload.get("draft_id"), "draft_id")
    if payload.get("confirmed") is not True:
        raise ValueError("explicit send confirmation is required")
    result = _google_service("gmail", "v1").users().drafts().send(
        userId="me", body={"id": draft_id}
    ).execute()
    _invalidate("mail")
    return {
        "schema": "biggy.pa.mail_send.v1",
        "ok": True,
        "status": "sent",
        "message_id": str(result.get("id") or ""),
        "thread_id": str(result.get("threadId") or ""),
    }


def discard_mail_draft(payload: dict[str, Any]) -> dict[str, Any]:
    _require_scope(GMAIL_COMPOSE_SCOPE)
    draft_id = _safe_id(payload.get("draft_id"), "draft_id")
    if payload.get("confirmed") is not True:
        raise ValueError("explicit discard confirmation is required")
    _google_service("gmail", "v1").users().drafts().delete(
        userId="me", id=draft_id
    ).execute()
    _invalidate("mail")
    return {"schema": "biggy.pa.mail_draft.v1", "ok": True, "status": "discarded", "draft_id": draft_id}


def _calendar_event_body(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if partial and ("start" in payload) != ("end" in payload):
        raise ValueError("start and end must be updated together")
    if not partial or "summary" in payload:
        body["summary"] = _clean_text(payload.get("summary"), "summary", maximum=500, required=True)
    for key, maximum in (("location", 1000), ("description", 10_000)):
        if key in payload:
            body[key] = _clean_text(payload.get(key), key, maximum=maximum)
    if not partial or "start" in payload:
        body["start"] = {"dateTime": _event_time(payload.get("start"), "start")}
    if not partial or "end" in payload:
        body["end"] = {"dateTime": _event_time(payload.get("end"), "end")}
    if "start" in body and "end" in body:
        start = datetime.fromisoformat(body["start"]["dateTime"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(body["end"]["dateTime"].replace("Z", "+00:00"))
        if end <= start:
            raise ValueError("end must be after start")
    if partial and not body:
        raise ValueError("at least one calendar field is required")
    return body


def create_calendar_event(payload: dict[str, Any]) -> dict[str, Any]:
    _require_scope(CALENDAR_EVENTS_SCOPE)
    event = _calendar_event_body(payload)
    result = _google_service("calendar", "v3").events().insert(
        calendarId="primary", body=event, sendUpdates="none"
    ).execute()
    _invalidate("calendar")
    return {
        "schema": "biggy.pa.calendar_event.v1",
        "ok": True,
        "status": "created",
        "event": {
            "id": str(result.get("id") or ""),
            "summary": str(result.get("summary") or event["summary"]),
            "url": str(result.get("htmlLink") or ""),
        },
    }


def update_calendar_event(payload: dict[str, Any]) -> dict[str, Any]:
    _require_scope(CALENDAR_EVENTS_SCOPE)
    event_id = _safe_id(payload.get("event_id"), "event_id")
    event = _calendar_event_body(payload, partial=True)
    result = _google_service("calendar", "v3").events().patch(
        calendarId="primary", eventId=event_id, body=event, sendUpdates="none"
    ).execute()
    _invalidate("calendar")
    return {
        "schema": "biggy.pa.calendar_event.v1",
        "ok": True,
        "status": "updated",
        "event": {
            "id": str(result.get("id") or event_id),
            "summary": str(result.get("summary") or event.get("summary") or ""),
            "url": str(result.get("htmlLink") or ""),
        },
    }


def delete_calendar_event(payload: dict[str, Any]) -> dict[str, Any]:
    _require_scope(CALENDAR_EVENTS_SCOPE)
    event_id = _safe_id(payload.get("event_id"), "event_id")
    if payload.get("confirmed") is not True:
        raise ValueError("explicit delete confirmation is required")
    _google_service("calendar", "v3").events().delete(
        calendarId="primary", eventId=event_id, sendUpdates="none"
    ).execute()
    _invalidate("calendar")
    return {
        "schema": "biggy.pa.calendar_event.v1",
        "ok": True,
        "status": "deleted",
        "event_id": event_id,
    }
