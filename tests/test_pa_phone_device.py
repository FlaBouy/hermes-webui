"""Regression tests for Planner Android adb phone-device connection."""

from types import SimpleNamespace

import pytest

from api import pa_phone_device as phone


class _Proc:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


_DUMP = (
    '<?xml version="1.0"?>'
    '<hierarchy rotation="0">'
    '<node text="Inbox" password="false" content-desc=""/>'
    "</hierarchy>"
)


def _authorized_run(dump=_DUMP):
    def fake_run(args, *, check=True):
        joined = " ".join(args)
        if args == ["devices"]:
            return "List of devices attached\nSERIAL\tdevice\n"
        if "uiautomator" in joined:
            return ""
        if "cat" in joined:
            return dump
        raise AssertionError(f"unexpected adb args: {args}")

    return fake_run


def test_devices_returns_structured_status_when_adb_list_fails(monkeypatch):
    monkeypatch.setattr(phone, "adb_path", lambda: "/fake/adb")

    def boom(*_a, **_k):
        raise ValueError("Phone command failed. Check that the phone is connected, unlocked and authorized.")

    monkeypatch.setattr(phone, "run", boom)
    status = phone.devices()
    assert status["devices"] == []
    assert status["ready"] is False
    assert "USB" in status["detail"] or "authorized" in status["detail"].lower()


def test_devices_reports_unauthorized_without_ready(monkeypatch):
    monkeypatch.setattr(phone, "adb_path", lambda: "/fake/adb")
    monkeypatch.setattr(
        phone,
        "run",
        lambda *_a, **_k: "List of devices attached\nSERIAL\tunauthorized\n",
    )
    status = phone.devices()
    assert status["ready"] is False
    assert status["devices"] == [{"id": "SERIAL", "state": "unauthorized"}]
    assert "USB debugging" in status["detail"]


def test_read_succeeds_when_cleanup_rm_fails_and_surfaces_warning(monkeypatch):
    """Successful accessibility dump must not be discarded by a failed temp cleanup."""
    monkeypatch.setattr(phone, "adb_path", lambda: "/fake/adb")
    monkeypatch.setattr(phone, "run", _authorized_run())
    monkeypatch.setattr(phone, "_cleanup_window_dump", lambda _ident: False)
    result = phone.operate({"device": "SERIAL", "action": "read"})
    assert "Inbox" in result["text"]
    assert "warning" in result
    assert "argus-window.xml" in result["warning"]
    assert "cleanup failed" in result["detail"].lower()


def test_read_cleanup_success_omits_warning(monkeypatch):
    monkeypatch.setattr(phone, "adb_path", lambda: "/fake/adb")
    monkeypatch.setattr(phone, "run", _authorized_run())
    monkeypatch.setattr(phone, "_cleanup_window_dump", lambda _ident: True)
    result = phone.operate({"device": "SERIAL", "action": "read"})
    assert "Inbox" in result["text"]
    assert "warning" not in result
    assert "cleanup failed" not in result["detail"].lower()


def test_read_still_cleans_up_after_dump_failure(monkeypatch):
    monkeypatch.setattr(phone, "adb_path", lambda: "/fake/adb")
    cleaned = {"called": False}

    def fake_run(args, *, check=True):
        joined = " ".join(args)
        if args == ["devices"]:
            return "List of devices attached\nSERIAL\tdevice\n"
        if "uiautomator" in joined:
            raise ValueError("Phone command failed. Check that the phone is connected, unlocked and authorized.")
        raise AssertionError(f"unexpected adb args: {args}")

    def fake_cleanup(_ident):
        cleaned["called"] = True
        return True

    monkeypatch.setattr(phone, "run", fake_run)
    monkeypatch.setattr(phone, "_cleanup_window_dump", fake_cleanup)
    with pytest.raises(ValueError, match="Phone command failed"):
        phone.operate({"device": "SERIAL", "action": "read"})
    assert cleaned["called"] is True


def test_cleanup_window_dump_false_on_nonzero(monkeypatch):
    monkeypatch.setattr(phone, "adb_path", lambda: "/fake/adb")
    monkeypatch.setattr(
        phone.subprocess,
        "run",
        lambda *_a, **_k: _Proc(stdout=b"", returncode=1),
    )
    assert phone._cleanup_window_dump("SERIAL") is False


def test_cleanup_window_dump_true_on_zero(monkeypatch):
    monkeypatch.setattr(phone, "adb_path", lambda: "/fake/adb")
    monkeypatch.setattr(
        phone.subprocess,
        "run",
        lambda *_a, **_k: _Proc(stdout=b"", returncode=0),
    )
    assert phone._cleanup_window_dump("SERIAL") is True


def test_run_check_false_does_not_raise_on_nonzero(monkeypatch):
    monkeypatch.setattr(phone, "adb_path", lambda: "/fake/adb")
    monkeypatch.setattr(
        phone.subprocess,
        "run",
        lambda *_a, **_k: _Proc(stdout=b"", returncode=1),
    )
    assert phone.run(["shell", "rm", "-f", "/sdcard/argus-window.xml"], check=False) == ""


def test_handle_get_returns_devices_payload_not_400_on_list_failure(monkeypatch):
    monkeypatch.setattr(
        phone,
        "devices",
        lambda: {"devices": [], "ready": False, "detail": "No phone detected."},
    )
    captured = {}

    def fake_j(_handler, payload, status=200, **_k):
        captured["payload"] = payload
        captured["status"] = status
        return payload

    monkeypatch.setattr("api.helpers.j", fake_j)
    handler = SimpleNamespace(headers={}, rfile=SimpleNamespace(read=lambda _n: b""))
    phone.handle(handler, parsed=None, post=False)
    assert captured["status"] == 200
    assert captured["payload"]["ready"] is False
    assert captured["payload"]["devices"] == []
