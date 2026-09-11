"""Mock-only regression tests for session-bridge deploy script corrections."""

from __future__ import annotations

import importlib.util
import plistlib
from pathlib import Path
from unittest import mock

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "deploy_biggy_workspace_session_bridge.py"
)


def _load():
    import sys
    name = "session_bridge_deploy_v2"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_script_compiles_and_constants():
    mod = _load()
    assert mod.EMBED_ORIGIN == "http://127.0.0.1:8790"
    assert mod.COMPOSE_IMAGE_NAME == "biggy-workspace-poc:local"
    assert "login_required" in mod.OWNER_SESSION_READY
    assert mod.KNOWN_STATE_DIR == "/mnt/DATA_Hot/Biggy_Workspace/state"
    assert mod.LIVE_RELEASE_ID == "f65a720d9e339d5954a171ec80473d3b34176019"
    assert mod.UPSTREAM_ORIGIN == "https://plato.tail061f03.ts.net"


def test_owner_session_ready_fails_closed():
    mod = _load()
    assert mod.assert_owner_session_ready("login_required") == "login_required"
    assert mod.assert_owner_session_ready("authenticated") == "authenticated"
    for bad in ("setup_required", "unreachable", "unknown", ""):
        with pytest.raises(mod.DeployError):
            mod.assert_owner_session_ready(bad)


def test_health_helpers_require_status_ok():
    mod = _load()
    assert mod.workspace_health_ok({"status": "ok"}) is True
    assert mod.workspace_health_ok({"status": "degraded"}) is False
    assert mod.workspace_health_ok({"ok": True}) is False
    assert mod.gui_health_ok({"status": "ok"}) is True
    assert mod.gui_health_ok({}) is False


def test_parse_container_inspect_line():
    mod = _load()
    status, image_id, tag = mod.parse_container_inspect_line(
        "running|sha256:abc123|biggy-workspace-poc:local"
    )
    assert status == "running"
    assert image_id.startswith("sha256:")
    assert tag == "biggy-workspace-poc:local"


def test_restart_launchagent_bootout_bootstrap_not_kickstart_alone(monkeypatch):
    mod = _load()
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        return mock.Mock(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(mod, "_run", fake_run)
    monkeypatch.setattr(mod.os, "getuid", lambda: 501)
    ev = mod.Evidence()
    mod.restart_launchagent(ev)
    joined = [" ".join(c) for c in calls]
    assert any(c.startswith("launchctl bootout ") for c in joined)
    assert any(c.startswith("launchctl bootstrap ") for c in joined)
    # Must not succeed via kickstart-only path
    assert any("bootout+bootstrap" in line for line in ev.lines)
    assert not any(line.startswith("launchagent_restart=kickstart ") for line in ev.lines)


def _fake_ssh_preflight_ok(remote: str, **kwargs):
    if "hostname" in remote:
        return "plato\n0\nDocker"
    if "LIVE_OK" in remote or "test -d" in remote:
        return "LIVE_OK\nCOMPOSE_OK\nrunning|sha256:abcabcabcabcabcab|biggy-workspace-poc:local"
    if "for p in" in remote or "DIR:" in remote:
        return "DIR:/mnt/DATA_Hot/Biggy_Workspace/state\nDB:/mnt/DATA_Hot/Biggy_Workspace/state/workspace.sqlite3"
    if "api/v1/session" in remote:
        return '{"state":"login_required"}'
    if "/health" in remote:
        return '{"status":"ok","service":"biggy-workspace-local"}'
    if "LOCAL_INFERENCE" in remote or "Config.Env" in remote or "range .Config.Env" in remote:
        return ""
    if "compose" in remote and "config" in remote:
        return "COMPOSE_CONFIG_OK"
    if "zfs" in remote:
        return "zfs_no"
    return ""


def test_preflight_fails_before_return_on_setup_required(monkeypatch):
    mod = _load()
    ev = mod.Evidence()

    def fake_ssh(remote: str, **kwargs):
        if "hostname" in remote:
            return "plato\n0\nDocker"
        if "LIVE_OK" in remote or "test -d" in remote:
            return "LIVE_OK\nCOMPOSE_OK\nrunning|sha256:deadbeef|biggy-workspace-poc:local"
        if "for p in" in remote or "DIR:" in remote:
            return "DIR:/mnt/DATA_Hot/Biggy_Workspace/state\nDB:/mnt/DATA_Hot/Biggy_Workspace/state/workspace.sqlite3"
        if "api/v1/session" in remote:
            return '{"state":"setup_required"}'
        if "/health" in remote:
            return '{"status":"ok"}'
        if "zfs" in remote:
            return "zfs_no"
        return ""

    monkeypatch.setattr(mod, "ssh", fake_ssh)
    monkeypatch.setattr(mod, "local_runtime_files", lambda: [Path("/tmp/a")] * 4)
    monkeypatch.setattr(mod, "LAUNCH_AGENT_PLIST", Path(__file__))
    with pytest.raises(mod.DeployError) as exc:
        mod.preflight(ev)
    assert "setup_required" in str(exc.value)


def test_preflight_ok_records_image_id(monkeypatch):
    mod = _load()
    ev = mod.Evidence()
    monkeypatch.setattr(mod, "ssh", _fake_ssh_preflight_ok)
    monkeypatch.setattr(mod, "local_runtime_files", lambda: [Path("/tmp/a")] * 4)
    monkeypatch.setattr(mod, "LAUNCH_AGENT_PLIST", Path(__file__))
    info = mod.preflight(ev)
    assert info["image_id"].startswith("sha256:")
    assert info["owner_session_state"] == "login_required"
    assert info["live_release_id"] == mod.LIVE_RELEASE_ID
    assert "BIGGY_WORKSPACE_STATE_DIR" in info["rollback_compose_env"]
    assert any(line.startswith("compose_config=ok") for line in ev.lines)


def test_preserve_rollback_image_tags_unique(monkeypatch):
    mod = _load()
    ev = mod.Evidence()
    seen = {}

    def fake_ssh(remote: str, **kwargs):
        seen["remote"] = remote
        return "PRESERVED"

    monkeypatch.setattr(mod, "ssh", fake_ssh)
    info = {"image_id": "sha256:abcdef0123456789"}
    tag = mod.preserve_rollback_image(ev, info, "/tmp/release")
    assert tag.startswith("biggy-workspace-poc:session-bridge-rollback-")
    assert "docker tag" in seen["remote"]
    assert "sha256:abcdef0123456789" in seen["remote"]
    assert info["rollback_image_tag"] == tag


def test_rollback_uses_preserved_image_and_no_build(monkeypatch):
    mod = _load()
    ev = mod.Evidence()
    remotes = []

    def fake_ssh(remote: str, **kwargs):
        remotes.append(remote)
        if "config --quiet" in remote:
            return "COMPOSE_CONFIG_OK"
        return "ROLLBACK_COMPOSE_OK"

    monkeypatch.setattr(mod, "ssh", fake_ssh)
    info = {
        "rollback_image_id": "sha256:oldimage",
        "rollback_image_tag": "biggy-workspace-poc:session-bridge-rollback-1",
        "local_inference_url": "http://127.0.0.1:1234",
        "rollback_compose_env": mod.required_compose_env(
            release_id=mod.LIVE_RELEASE_ID,
            local_inference_url="http://127.0.0.1:1234",
        ),
    }
    mod.rollback_remote(ev, "/tmp/rel", info)
    blob = "\n".join(remotes)
    assert "--no-build" in blob
    assert "docker tag" in blob
    assert "biggy-workspace-poc:local" in blob
    assert "session-bridge-rollback-1" in blob
    assert "BIGGY_WORKSPACE_STATE_DIR=" in blob
    assert mod.KNOWN_STATE_DIR in blob
    assert "BIGGY_WORKSPACE_EXTERNAL_ORIGIN=" in blob
    assert mod.UPSTREAM_ORIGIN in blob
    assert f"BIGGY_WORKSPACE_RELEASE_ID={mod.LIVE_RELEASE_ID}" in blob or (
        f"BIGGY_WORKSPACE_RELEASE_ID='{mod.LIVE_RELEASE_ID}'" in blob
    )
    assert "BIGGY_WORKSPACE_LOCAL_INFERENCE_URL=" in blob
    assert "config --quiet" in blob


def test_required_compose_env_fails_closed_on_missing_interpolation():
    mod = _load()
    with pytest.raises(mod.DeployError) as exc:
        mod.assert_required_compose_env(
            {
                "BIGGY_WORKSPACE_STATE_DIR": "",
                "BIGGY_WORKSPACE_EXTERNAL_ORIGIN": mod.UPSTREAM_ORIGIN,
                "BIGGY_WORKSPACE_RELEASE_ID": mod.LIVE_RELEASE_ID,
            }
        )
    assert "BIGGY_WORKSPACE_STATE_DIR" in str(exc.value)

    with pytest.raises(mod.DeployError):
        mod.required_compose_env(release_id="")

    env = mod.required_compose_env(
        release_id="session-bridge-20260911-999999",
        local_inference_url="",
    )
    assert env["BIGGY_WORKSPACE_STATE_DIR"] == mod.KNOWN_STATE_DIR
    assert env["BIGGY_WORKSPACE_EXTERNAL_ORIGIN"] == mod.UPSTREAM_ORIGIN
    assert env["BIGGY_WORKSPACE_RELEASE_ID"] == "session-bridge-20260911-999999"
    assert "BIGGY_WORKSPACE_LOCAL_INFERENCE_URL" not in env


def test_rollback_compose_env_uses_live_release_id_and_known_state():
    mod = _load()
    env = mod.required_compose_env(
        release_id=mod.LIVE_RELEASE_ID,
        local_inference_url="http://127.0.0.1:1234",
    )
    assert env["BIGGY_WORKSPACE_RELEASE_ID"] == mod.LIVE_RELEASE_ID
    assert env["BIGGY_WORKSPACE_STATE_DIR"] == "/mnt/DATA_Hot/Biggy_Workspace/state"
    assert env["BIGGY_WORKSPACE_EXTERNAL_ORIGIN"] == "https://plato.tail061f03.ts.net"
    assert env["BIGGY_WORKSPACE_LOCAL_INFERENCE_URL"] == "http://127.0.0.1:1234"
    prefix = mod.compose_env_shell_prefix(env)
    assert "BIGGY_WORKSPACE_STATE_DIR=" in prefix
    assert "BIGGY_WORKSPACE_RELEASE_ID=" in prefix
    staged = f"{mod.RELEASES_PARENT}/session-bridge-20260911-999999"
    assert mod.release_id_for_staged_dir(staged) == "session-bridge-20260911-999999"
    apply_env = mod.required_compose_env(
        release_id=mod.release_id_for_staged_dir(staged)
    )
    assert apply_env["BIGGY_WORKSPACE_RELEASE_ID"] == "session-bridge-20260911-999999"


def test_build_and_recreate_requires_matching_release_id_and_env(monkeypatch):
    mod = _load()
    ev = mod.Evidence()
    remotes = []

    def fake_ssh(remote: str, **kwargs):
        remotes.append(remote)
        return "RECREATE_OK"

    monkeypatch.setattr(mod, "ssh", fake_ssh)
    staged = f"{mod.RELEASES_PARENT}/session-bridge-20260911-999999"
    env = mod.required_compose_env(release_id="session-bridge-20260911-999999")
    mod.build_and_recreate_workspace(ev, staged, env)
    blob = remotes[0]
    assert "BIGGY_WORKSPACE_STATE_DIR=" in blob
    assert "compose.session-bridge.yaml" in blob
    assert "build" in blob

    bad = mod.required_compose_env(release_id=mod.LIVE_RELEASE_ID)
    with pytest.raises(mod.DeployError) as exc:
        mod.build_and_recreate_workspace(ev, staged, bad)
    assert "must match staged directory" in str(exc.value)


def test_install_local_secret_backs_up_existing(tmp_path, monkeypatch):
    mod = _load()
    secret_path = tmp_path / "bridge.secret"
    secret_path.write_text("old-secret-value-here!!\n", encoding="utf-8")
    monkeypatch.setattr(mod, "LOCAL_SECRET_PATH", secret_path)
    ev = mod.Evidence()
    path, backup = mod.install_local_secret(ev, "new-secret-value-here!!")
    assert path == secret_path
    assert backup is not None and backup.is_file()
    assert backup.read_text(encoding="utf-8").startswith("old-secret")
    assert secret_path.read_text(encoding="utf-8").startswith("new-secret")


def test_main_preflight_returns_nonzero_on_setup_required(monkeypatch):
    mod = _load()

    def boom(ev):
        raise mod.DeployError("owner_session_not_ready state=setup_required")

    monkeypatch.setattr(mod, "preflight", boom)
    assert mod.main(["--preflight-only"]) == 1


def test_smoke_source_decodes_without_secret_material():
    mod = _load()
    src = mod._smoke_remote_source()
    assert "SMOKE_MINT_OK" in src
    assert "origin_refused" in src
    assert "http://127.0.0.1:8790" in src
    assert "unexpected_task_created" in src
    # Mint response shape must match app.py hermes-bridge JSON.
    assert 'mint.get("session_token")' in src
    assert 'mint.get("state") != "authenticated"' in src
    cmd = mod.smoke_remote_bash_command()
    assert cmd.startswith("python3 -c ")
    assert "<<" not in cmd
    assert "sys.stdin.readline" in src


def test_smoke_remote_command_preserves_stdin_through_bash_c():
    """Heredoc ate input_bytes; python3 -c must keep stdin for the secret."""
    import subprocess

    mod = _load()
    synthetic = (
        "import sys\n"
        "s = sys.stdin.readline().strip()\n"
        "if len(s) < 16:\n"
        "    print('SMOKE_FAIL secret_short')\n"
        "    raise SystemExit(2)\n"
        "print('SMOKE_GOT_LEN', len(s))\n"
        "print('SMOKE_ALL_OK')\n"
    )
    secret = "synthetic-secret-16c!"
    remote = mod.smoke_remote_bash_command(synthetic)
    assert secret not in remote
    assert remote.startswith("python3 -c ")

    # Emulate OpenSSH argv join → local bash -c (same path as ssh() quoting).
    joined = " ".join(mod.ssh_remote_bash_lc_argv(remote))
    good = subprocess.run(
        ["bash", "-c", joined],
        input=(secret + "\n").encode("utf-8"),
        capture_output=True,
        check=False,
    )
    assert good.returncode == 0, good.stderr.decode()
    out = good.stdout.decode()
    assert "SMOKE_ALL_OK" in out
    assert "SMOKE_GOT_LEN" in out
    assert secret not in out

    # Exact prior defect: heredoc consumes stdin → secret_short exit 2.
    heredoc = "python3 - <<'PY'\n" + synthetic + "\nPY"
    bad_joined = " ".join(mod.ssh_remote_bash_lc_argv(heredoc))
    bad = subprocess.run(
        ["bash", "-c", bad_joined],
        input=(secret + "\n").encode("utf-8"),
        capture_output=True,
        check=False,
    )
    assert bad.returncode == 2
    assert "SMOKE_FAIL secret_short" in bad.stdout.decode()


def test_sanitize_smoke_diagnostic_redacts_secret_keeps_fail():
    mod = _load()
    secret = "super-secret-bridge-value"
    line = f"SMOKE_FAIL mint status=401 leaked={secret}"
    cleaned = mod.sanitize_smoke_diagnostic(line, secret=secret)
    assert cleaned.startswith("SMOKE_FAIL")
    assert secret not in cleaned
    assert "[REDACTED]" in cleaned


def test_bridge_smoke_fail_exception_includes_sanitized_smoke_fail(monkeypatch):
    mod = _load()
    ev = mod.Evidence()
    secret = "bridge-secret-value!!"

    def fake_ssh(remote: str, **kwargs):
        assert remote.startswith("python3 -c ")
        assert "<<" not in remote
        assert secret not in remote
        assert kwargs.get("input_bytes") == (secret + "\n").encode("utf-8")
        return "SMOKE_FAIL secret_short\n"

    monkeypatch.setattr(mod, "ssh", fake_ssh)
    with pytest.raises(mod.DeployError) as exc:
        mod.bridge_smoke_and_origin_proof(ev, secret)
    msg = str(exc.value)
    assert "SMOKE_FAIL secret_short" in msg
    assert secret not in msg


def test_ssh_remote_quoting_emulates_argv_join_printf_and_stdin():
    """OpenSSH joins remote argv with spaces; unquoted -lc breaks printf compounds."""
    import shlex
    import subprocess

    mod = _load()
    remote = "printf '%s' \"hello-world\" && echo && cat"
    argv = mod.ssh_remote_bash_lc_argv(remote)
    assert argv[0:2] == ["bash", "-lc"]
    assert argv[2] == shlex.quote(remote)

    # Emulate SSH remote argv joining, then execute via local bash -c.
    joined = " ".join(argv)
    good = subprocess.run(
        ["bash", "-c", joined],
        input=b"stdin-payload\n",
        capture_output=True,
        check=False,
    )
    assert good.returncode == 0, good.stderr.decode()
    out = good.stdout.decode()
    assert "hello-world" in out
    assert "stdin-payload" in out

    # Unquoted compound (Atlas bug): -lc only receives the first word "printf".
    bad_joined = " ".join(["bash", "-lc", remote])
    bad = subprocess.run(
        ["bash", "-c", bad_joined],
        input=b"stdin-payload\n",
        capture_output=True,
        check=False,
    )
    assert bad.returncode != 0
