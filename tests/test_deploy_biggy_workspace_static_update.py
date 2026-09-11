"""Mock/local regressions for Workspace static-update deploy helper."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "deploy_biggy_workspace_static_update.py"
)


def _load():
    import sys

    name = "workspace_static_update_deploy"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_script_compiles_and_static_only_paths():
    mod = _load()
    assert mod.STATIC_REL_PATHS == (
        "biggy_workspace/static/app.js",
        "biggy_workspace/static/index.html",
    )
    assert mod.STAGED_PREFIX == "static-update-"
    assert mod.REMOTE_CONTAINER == "biggy-workspace-poc-biggy-workspace-1"


def test_parse_working_dir_label_requires_releases_parent():
    mod = _load()
    ok = (
        "/mnt/DATA_Hot/Biggy_Workspace/releases/"
        "session-bridge-20260911-132100"
    )
    assert mod.parse_working_dir_label(ok) == ok
    with pytest.raises(mod.DeployError):
        mod.parse_working_dir_label("")
    with pytest.raises(mod.DeployError):
        mod.parse_working_dir_label("/tmp/not-releases/foo")
    with pytest.raises(mod.DeployError):
        mod.parse_working_dir_label(ok + "/../escape")


def test_parse_compose_file_args_from_label():
    mod = _load()
    wd = "/mnt/DATA_Hot/Biggy_Workspace/releases/live"
    files = mod.parse_compose_file_args(
        f"{wd}/compose.yaml,{wd}/compose.session-bridge.yaml",
        wd,
    )
    assert files == ["compose.yaml", "compose.session-bridge.yaml"]
    assert mod.parse_compose_file_args("", wd) == ["compose.yaml"]


def test_required_compose_env_and_inference_optional():
    mod = _load()
    env = mod.required_compose_env(release_id="static-update-1")
    assert env["BIGGY_WORKSPACE_STATE_DIR"] == mod.KNOWN_STATE_DIR
    assert env["BIGGY_WORKSPACE_EXTERNAL_ORIGIN"] == mod.UPSTREAM_ORIGIN
    assert "BIGGY_WORKSPACE_LOCAL_INFERENCE_URL" not in env
    with_inf = mod.required_compose_env(
        release_id="static-update-1",
        local_inference_url="http://127.0.0.1:1234",
    )
    assert with_inf["BIGGY_WORKSPACE_LOCAL_INFERENCE_URL"] == "http://127.0.0.1:1234"
    with pytest.raises(mod.DeployError):
        mod.required_compose_env(release_id="")


def test_local_static_markers_match_acceptance(tmp_path, monkeypatch):
    mod = _load()
    root = tmp_path / "ws"
    static = root / "biggy_workspace" / "static"
    static.mkdir(parents=True)
    (static / "index.html").write_text("<main class='planner-shell'></main>\n", encoding="utf-8")
    (static / "app.js").write_text(
        "const res = await fetch(apiUrl(path), Object.assign({}, options));\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "LOCAL_WORKSPACE_ROOT", root)
    mod.assert_local_static_markers()

    (static / "index.html").write_text('<div class="mode-banner"></div>\n', encoding="utf-8")
    with pytest.raises(mod.DeployError) as exc:
        mod.assert_local_static_markers()
    assert "mode-banner" in str(exc.value)


def test_ssh_remote_quoting_preserves_compound_commands():
    mod = _load()
    remote = "printf '%s' \"hello\" && echo ok"
    argv = mod.ssh_remote_bash_lc_argv(remote)
    joined = " ".join(argv)
    good = subprocess.run(
        ["bash", "-c", joined],
        capture_output=True,
        check=False,
    )
    assert good.returncode == 0
    assert b"hello" in good.stdout


def test_discover_live_release_uses_remote_label_only(monkeypatch):
    mod = _load()
    ev = mod.Evidence()
    live = (
        "/mnt/DATA_Hot/Biggy_Workspace/releases/"
        "session-bridge-20260911-132100"
    )

    def fake_ssh(remote: str, **kwargs):
        if "com.docker.compose.project.working_dir" in remote or "Labels" in remote:
            return (
                f"{live}|{live}/compose.yaml,{live}/compose.session-bridge.yaml|"
                "running|sha256:abcabcabcabcabcab|biggy-workspace-poc:local"
            )
        if "DIR_OK" in remote or "test -d" in remote:
            return "DIR_OK\nCOMPOSE_OK\nFILE_OK:compose.session-bridge.yaml"
        if "BIGGY_WORKSPACE_RELEASE_ID" in remote:
            return "session-bridge-20260911-132100"
        if "BIGGY_WORKSPACE_LOCAL_INFERENCE_URL" in remote:
            return "http://127.0.0.1:1234"
        return ""

    monkeypatch.setattr(mod, "ssh", fake_ssh)
    info = mod.discover_live_release(ev)
    assert info["live_release_dir"] == live
    assert info["compose_files"] == ["compose.yaml", "compose.session-bridge.yaml"]
    assert info["local_inference_url"] == "http://127.0.0.1:1234"
    assert info["image_id"].startswith("sha256:")


def test_rollback_retags_previous_release_no_build(monkeypatch):
    mod = _load()
    ev = mod.Evidence()
    remotes = []
    live = "/mnt/DATA_Hot/Biggy_Workspace/releases/session-bridge-20260911-132100"

    def fake_ssh(remote: str, **kwargs):
        remotes.append(remote)
        if "config --quiet" in remote:
            return "COMPOSE_CONFIG_OK"
        return "ROLLBACK_COMPOSE_OK"

    monkeypatch.setattr(mod, "ssh", fake_ssh)
    info = {
        "live_release_dir": live,
        "live_release_id": "session-bridge-20260911-132100",
        "compose_files": ["compose.yaml", "compose.session-bridge.yaml"],
        "local_inference_url": "",
        "rollback_image_id": "sha256:oldimage",
        "rollback_image_tag": "biggy-workspace-poc:static-update-rollback-1",
        "rollback_compose_env": mod.required_compose_env(
            release_id="session-bridge-20260911-132100"
        ),
    }
    mod.rollback_remote(ev, "/tmp/staged", info)
    blob = "\n".join(remotes)
    assert "--no-build" in blob
    assert live in blob
    assert "BIGGY_WORKSPACE_STATE_DIR=" in blob
    assert "compose.session-bridge.yaml" in blob
    assert "session-bridge-20260911-132100" in blob


def test_build_requires_release_id_match_staged_dir(monkeypatch):
    mod = _load()
    ev = mod.Evidence()
    monkeypatch.setattr(mod, "ssh", lambda *a, **k: "RECREATE_OK")
    staged = f"{mod.RELEASES_PARENT}/static-update-20260911-999999"
    env = mod.required_compose_env(release_id="static-update-20260911-999999")
    mod.build_and_recreate(ev, staged, env, ["compose.yaml"])
    bad = mod.required_compose_env(release_id="other-id")
    with pytest.raises(mod.DeployError):
        mod.build_and_recreate(ev, staged, bad, ["compose.yaml"])


def test_main_preflight_nonzero_on_failure(monkeypatch):
    mod = _load()

    def boom(ev):
        raise mod.DeployError("container missing compose working_dir label")

    monkeypatch.setattr(mod, "preflight", boom)
    assert mod.main(["--preflight-only"]) == 1
