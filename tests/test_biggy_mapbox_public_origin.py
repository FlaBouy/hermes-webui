"""Biggy Mapbox public-config origin gate + Referrer-Policy for URL-restricted tokens."""

from __future__ import annotations

from api import biggy_mapbox_config as mapbox
from api.helpers import _security_headers


PUBLIC = "https://smedley.example.ts.net"


class _HeaderSink:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}

    def send_header(self, key: str, value: str) -> None:
        self.headers[key] = value


def test_configured_public_origin_allowed_by_exact_origin(monkeypatch):
    monkeypatch.setenv(mapbox.PUBLIC_ORIGIN_ENV, PUBLIC)
    assert mapbox.origin_allowed(PUBLIC) is True
    assert mapbox.origin_allowed(PUBLIC + "/") is True


def test_configured_public_origin_allowed_by_exact_referer(monkeypatch):
    monkeypatch.setenv(mapbox.PUBLIC_ORIGIN_ENV, PUBLIC)
    assert (
        mapbox.origin_allowed(
            None,
            referer=f"{PUBLIC}/api/biggy/mapbox-public-config?x=1",
        )
        is True
    )


def test_loopback_origins_still_allowed_without_public_origin(monkeypatch):
    monkeypatch.delenv(mapbox.PUBLIC_ORIGIN_ENV, raising=False)
    assert mapbox.origin_allowed("http://127.0.0.1:8790") is True
    assert mapbox.origin_allowed("http://localhost:8787") is True
    assert mapbox.origin_allowed(None, host="127.0.0.1:8790") is True


def test_rejects_malformed_configured_public_origin(monkeypatch):
    monkeypatch.setenv(mapbox.PUBLIC_ORIGIN_ENV, "not a url")
    assert mapbox.origin_allowed("not a url") is False
    monkeypatch.setenv(mapbox.PUBLIC_ORIGIN_ENV, "https://user:pass@smedley.example.ts.net")
    assert mapbox.origin_allowed("https://smedley.example.ts.net") is False
    monkeypatch.setenv(mapbox.PUBLIC_ORIGIN_ENV, "https://smedley.example.ts.net?x=1")
    assert mapbox.origin_allowed("https://smedley.example.ts.net") is False
    monkeypatch.setenv(mapbox.PUBLIC_ORIGIN_ENV, "https://smedley.example.ts.net#frag")
    assert mapbox.origin_allowed("https://smedley.example.ts.net") is False
    monkeypatch.setenv(mapbox.PUBLIC_ORIGIN_ENV, "https://*.example.ts.net")
    assert mapbox.origin_allowed("https://evil.example.ts.net") is False

    # Valid configured origin still rejects credentialed / pathful request Origin.
    monkeypatch.setenv(mapbox.PUBLIC_ORIGIN_ENV, PUBLIC)
    assert mapbox.origin_allowed("https://user:pass@smedley.example.ts.net") is False
    assert mapbox.origin_allowed(PUBLIC + "/extra") is False
    assert (
        mapbox.origin_allowed(
            None,
            referer="https://user:pass@smedley.example.ts.net/path",
        )
        is False
    )


def test_rejects_suffix_lookalike_origins(monkeypatch):
    monkeypatch.setenv(mapbox.PUBLIC_ORIGIN_ENV, PUBLIC)
    assert mapbox.origin_allowed("https://smedley.example.ts.net.evil.com") is False
    assert mapbox.origin_allowed("https://evil-smedley.example.ts.net") is False
    assert mapbox.origin_allowed("https://smedley.example.ts.net.attacker") is False
    assert (
        mapbox.origin_allowed(
            None,
            referer="https://smedley.example.ts.net.evil.com/path",
        )
        is False
    )


def test_arbitrary_host_does_not_authorize_public_origin(monkeypatch):
    monkeypatch.setenv(mapbox.PUBLIC_ORIGIN_ENV, PUBLIC)
    # Host alone must never unlock the configured public origin.
    assert mapbox.origin_allowed(None, host="smedley.example.ts.net") is False
    assert mapbox.origin_allowed(None, host="smedley.example.ts.net:443") is False
    assert mapbox.origin_allowed(None, host="evil.example.com") is False


def test_mapbox_config_fail_closed_omits_token_when_origin_denied(monkeypatch):
    monkeypatch.setenv(mapbox.PUBLIC_ORIGIN_ENV, PUBLIC)
    # Provide a syntactically valid public token via env without printing it.
    monkeypatch.setenv(mapbox.TOKEN_ENV, "pk." + ("a" * 40))
    cfg = mapbox.mapbox_public_config(origin="https://evil.example.com")
    assert cfg["origin_allowed"] is False
    assert cfg["available"] is False
    assert cfg["token"] is None
    assert cfg["token_set"] is False
    assert cfg["reason"] == "ORIGIN_NOT_ALLOWED"
    # Allowed path still resolves without exposing the value in assertions beyond presence.
    ok = mapbox.mapbox_public_config(origin=PUBLIC)
    assert ok["origin_allowed"] is True
    assert ok["available"] is True
    assert ok["token_set"] is True
    assert isinstance(ok["token"], str) and ok["token"].startswith("pk.")
    assert len(ok["token"]) >= 20


def test_security_headers_use_strict_origin_referrer_policy():
    sink = _HeaderSink()
    _security_headers(sink)
    assert sink.headers.get("Referrer-Policy") == "strict-origin"
