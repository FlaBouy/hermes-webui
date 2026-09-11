#!/usr/bin/env python3
"""Atlas-only static update for Biggy Workspace (app.js + index.html only).

Modes:
  --preflight-only   Discover live release via remote docker labels; read-only
  --apply            Timestamped release copy, overlay static, rebuild service,
                     restart local ai.biggy.webui only

Discovers the live Compose working directory from container label
com.docker.compose.project.working_dir (no hardcoded release SHA).

Does not rotate credentials, rewrite compose overrides, or mutate the state DB.
Never prints secret values. Cursor must not run --apply; Atlas does.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ── Fixed contract ──────────────────────────────────────────────────────────
SSH_HOST = "192.168.0.25"
SSH_USER = "root"
SSH_CONNECT_TIMEOUT = "10"
REMOTE_CONTAINER = "biggy-workspace-poc-biggy-workspace-1"
COMPOSE_PROJECT = "biggy-workspace-poc"
COMPOSE_SERVICE = "biggy-workspace"
COMPOSE_IMAGE_NAME = "biggy-workspace-poc:local"
RELEASES_PARENT = "/mnt/DATA_Hot/Biggy_Workspace/releases"
KNOWN_STATE_DIR = "/mnt/DATA_Hot/Biggy_Workspace/state"
UPSTREAM_ORIGIN = "https://plato.tail061f03.ts.net"
LOCAL_WORKSPACE_ROOT = Path("/Users/rick/Projects/biggy-workspace")
STATIC_REL_PATHS = (
    "biggy_workspace/static/app.js",
    "biggy_workspace/static/index.html",
)
LAUNCH_AGENT_LABEL = "ai.biggy.webui"
LAUNCH_AGENT_PLIST = Path("/Users/rick/Library/LaunchAgents/ai.biggy.webui.plist")
WORKSPACE_LOOPBACK_HEALTH = "http://127.0.0.1:18765/health"
WORKSPACE_LOOPBACK_INDEX = "http://127.0.0.1:18765/"
WORKSPACE_LOOPBACK_APP_JS = "http://127.0.0.1:18765/static/app.js"
LOCAL_GUI_HEALTH = "http://127.0.0.1:8790/health"
COMPOSE_INTERPOLATION_REQUIRED = (
    "BIGGY_WORKSPACE_STATE_DIR",
    "BIGGY_WORKSPACE_EXTERNAL_ORIGIN",
    "BIGGY_WORKSPACE_RELEASE_ID",
)
WORKING_DIR_LABEL = "com.docker.compose.project.working_dir"
CONFIG_FILES_LABEL = "com.docker.compose.project.config_files"
MODE_BANNER_MARKER = "mode-banner"
APP_JS_FETCH_MARKER = "fetch(apiUrl(path)"
STAGED_PREFIX = "static-update-"


class DeployError(RuntimeError):
    pass


class Evidence:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.rollback: list[str] = []

    def add(self, msg: str) -> None:
        self.lines.append(msg)

    def add_rollback(self, msg: str) -> None:
        self.rollback.append(msg)

    def dump(self) -> None:
        print("=== workspace static-update evidence (sanitized) ===")
        for line in self.lines:
            print(line)
        if self.rollback:
            print("=== rollback paths ===")
            for line in self.rollback:
                print(line)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _run(
    argv: Sequence[str],
    *,
    input_bytes: bytes | None = None,
    check: bool = True,
    timeout: int = 120,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            list(argv),
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=check,
            timeout=timeout,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or b"").decode("utf-8", "replace").strip()
        safe = [a for a in argv[:6] if "secret" not in a.lower()]
        raise DeployError(
            f"command failed rc={exc.returncode}: {' '.join(safe)}… "
            + (err.splitlines()[-1] if err else "")
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DeployError(f"command timed out: {' '.join(argv[:3])}…") from exc


def ssh_argv(*remote_cmd: str) -> list[str]:
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"{SSH_USER}@{SSH_HOST}",
        "--",
        *remote_cmd,
    ]


def ssh_remote_bash_lc_argv(remote: str) -> list[str]:
    return ["bash", "-lc", shlex.quote(remote)]


def ssh(remote: str, *, timeout: int = 120, input_bytes: bytes | None = None) -> str:
    proc = _run(
        ssh_argv(*ssh_remote_bash_lc_argv(remote)),
        timeout=timeout,
        input_bytes=input_bytes,
    )
    return (proc.stdout or b"").decode("utf-8", "replace")


def scp_to_remote(local: Path, remote_path: str) -> None:
    _run(
        [
            "scp",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
            str(local),
            f"{SSH_USER}@{SSH_HOST}:{remote_path}",
        ],
        timeout=180,
    )


def release_id_for_dir(release_dir: str) -> str:
    return Path(str(release_dir).rstrip("/")).name


def parse_working_dir_label(raw: str) -> str:
    value = str(raw or "").strip()
    if not value or value in {"", "<no value>", "<no value>"}:
        raise DeployError("container missing compose working_dir label")
    if "\n" in value or ".." in value.split("/"):
        raise DeployError("invalid compose working_dir label")
    if not value.startswith(RELEASES_PARENT + "/"):
        raise DeployError(
            f"working_dir must be under {RELEASES_PARENT}/ got={value!r}"
        )
    return value.rstrip("/")


def parse_compose_file_args(raw: str, working_dir: str) -> list[str]:
    """Map label config_files to compose -f basenames relative to working_dir."""
    files: list[str] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith(working_dir.rstrip("/") + "/"):
            rel = part[len(working_dir.rstrip("/")) + 1 :]
        else:
            rel = Path(part).name
        if not rel or ".." in rel.split("/"):
            raise DeployError(f"unsafe compose config file entry: {part!r}")
        if rel not in files:
            files.append(rel)
    return files or ["compose.yaml"]


def required_compose_env(
    *,
    release_id: str,
    local_inference_url: str = "",
) -> dict[str, str]:
    rid = str(release_id or "").strip()
    env = {
        "BIGGY_WORKSPACE_STATE_DIR": KNOWN_STATE_DIR,
        "BIGGY_WORKSPACE_EXTERNAL_ORIGIN": UPSTREAM_ORIGIN,
        "BIGGY_WORKSPACE_RELEASE_ID": rid,
    }
    inference = str(local_inference_url or "").strip()
    if inference:
        env["BIGGY_WORKSPACE_LOCAL_INFERENCE_URL"] = inference
    assert_required_compose_env(env)
    return env


def assert_required_compose_env(env: Mapping[str, str]) -> dict[str, str]:
    missing = [
        key
        for key in COMPOSE_INTERPOLATION_REQUIRED
        if not str(env.get(key) or "").strip()
    ]
    if missing:
        raise DeployError("missing compose interpolation env: " + ", ".join(missing))
    return dict(env)


def compose_env_shell_prefix(env: Mapping[str, str]) -> str:
    assert_required_compose_env(env)
    keys = list(COMPOSE_INTERPOLATION_REQUIRED)
    if "BIGGY_WORKSPACE_LOCAL_INFERENCE_URL" in env:
        keys.append("BIGGY_WORKSPACE_LOCAL_INFERENCE_URL")
    return " ".join(f"{k}={shlex.quote(str(env[k]))}" for k in keys)


def compose_file_flags(files: Sequence[str]) -> str:
    return " ".join(f"-f {shlex.quote(name)}" for name in files)


def local_static_files() -> list[Path]:
    missing = []
    files = []
    for rel in STATIC_REL_PATHS:
        path = LOCAL_WORKSPACE_ROOT / rel
        if not path.is_file():
            missing.append(rel)
        else:
            files.append(path)
    if missing:
        raise DeployError(f"missing local static files: {', '.join(missing)}")
    return files


def assert_local_static_markers() -> None:
    index = (LOCAL_WORKSPACE_ROOT / "biggy_workspace/static/index.html").read_text(
        encoding="utf-8"
    )
    app_js = (LOCAL_WORKSPACE_ROOT / "biggy_workspace/static/app.js").read_text(
        encoding="utf-8"
    )
    if MODE_BANNER_MARKER in index:
        raise DeployError(
            f"local index.html still contains {MODE_BANNER_MARKER!r} — refuse apply"
        )
    if APP_JS_FETCH_MARKER not in app_js:
        raise DeployError(
            f"local app.js missing {APP_JS_FETCH_MARKER!r} — refuse apply"
        )


def workspace_health_ok(payload: Mapping[str, Any]) -> bool:
    return str(payload.get("status") or "") == "ok"


def gui_health_ok(payload: Mapping[str, Any]) -> bool:
    return str(payload.get("status") or "") == "ok"


def parse_container_inspect_line(line: str) -> tuple[str, str, str]:
    parts = (line or "").strip().split("|")
    while len(parts) < 3:
        parts.append("none")
    return parts[0], parts[1], parts[2]


def probe_json(url: str, *, timeout: float = 5.0) -> tuple[int, dict[str, Any]]:
    req = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            status = int(getattr(resp, "status", 200))
    except HTTPError as exc:
        body = exc.read() if exc.fp else b"{}"
        status = int(exc.code)
    except (URLError, TimeoutError, OSError) as exc:
        raise DeployError(f"probe failed for {url}: {exc.__class__.__name__}") from exc
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return status, payload


def probe_whitelisted_env(var_name: str) -> str:
    """Whitelist-only Config.Env read (never dump full Env / secrets)."""
    allowed = {
        "BIGGY_WORKSPACE_LOCAL_INFERENCE_URL",
        "BIGGY_WORKSPACE_RELEASE_ID",
        "BIGGY_WORKSPACE_EXTERNAL_ORIGIN",
    }
    if var_name not in allowed:
        raise DeployError(f"env probe not whitelisted: {var_name}")
    inspect_tpl = "{{range .Config.Env}}{{println .}}{{end}}"
    awk_prog = f'$1=="{var_name}" {{print substr($0, index($0,"=")+1); exit}}'
    raw = ssh(
        "set +e; "
        f"docker inspect -f {shlex.quote(inspect_tpl)} {REMOTE_CONTAINER} 2>/dev/null "
        f"| awk -F= {shlex.quote(awk_prog)}"
    ).strip()
    if not raw or "\n" in raw:
        return ""
    if any(tok in raw.upper() for tok in ("CREDENTIAL", "PASSWORD", "SECRET", "TOKEN")):
        return ""
    return raw


def discover_live_release(ev: Evidence) -> dict[str, Any]:
    """Read-only remote discovery via docker inspect labels (never local path guess)."""
    inspect = ssh(
        "set -e; "
        f"docker inspect -f "
        f"'{{{{index .Config.Labels \"{WORKING_DIR_LABEL}\"}}}}"
        f"|{{{{index .Config.Labels \"{CONFIG_FILES_LABEL}\"}}}}"
        f"|{{{{.State.Status}}}}|{{{{.Image}}}}|{{{{.Config.Image}}}}' "
        f"{REMOTE_CONTAINER}"
    ).strip()
    parts = inspect.split("|")
    while len(parts) < 5:
        parts.append("")
    working_dir = parse_working_dir_label(parts[0])
    compose_files = parse_compose_file_args(parts[1], working_dir)
    status, image_id, image_tag = parse_container_inspect_line(
        "|".join(parts[2:5])
    )
    if status in {"", "missing"} or image_id in {"", "none"}:
        raise DeployError(f"container not ready: {REMOTE_CONTAINER}")

    file_checks = ""
    for name in compose_files:
        if name == "compose.yaml":
            continue
        file_checks += f"test -f {working_dir!r}/{name} && echo FILE_OK:{name}; "
    layout = ssh(
        f"set -e; "
        f"test -d {working_dir!r} && echo DIR_OK; "
        f"test -f {working_dir!r}/compose.yaml && echo COMPOSE_OK; "
        f"{file_checks}"
    )
    if "DIR_OK" not in layout or "COMPOSE_OK" not in layout:
        raise DeployError(f"remote release layout incomplete under {working_dir}")

    # Ensure labeled override files exist; fall back to compose.yaml only if absent.
    present = {"compose.yaml"}
    for line in layout.splitlines():
        if line.startswith("FILE_OK:"):
            present.add(line.split(":", 1)[1])
    compose_files = [f for f in compose_files if f in present] or ["compose.yaml"]

    live_release_id = probe_whitelisted_env("BIGGY_WORKSPACE_RELEASE_ID") or release_id_for_dir(
        working_dir
    )
    inference = probe_whitelisted_env("BIGGY_WORKSPACE_LOCAL_INFERENCE_URL")

    info: dict[str, Any] = {
        "live_release_dir": working_dir,
        "live_release_id": live_release_id,
        "compose_files": compose_files,
        "container_status": status,
        "image_id": image_id,
        "image_tag": image_tag,
        "local_inference_url": inference,
    }
    ev.add(
        f"live_release={working_dir} release_id={live_release_id} "
        f"compose_files={','.join(compose_files)} "
        f"status={status} image_id={image_id[:19]}… "
        f"inference={'set' if inference else 'unset'}"
    )
    return info


def validate_compose_config(
    ev: Evidence,
    release_dir: str,
    env: Mapping[str, str],
    compose_files: Sequence[str],
) -> None:
    assert_required_compose_env(env)
    prefix = compose_env_shell_prefix(env)
    flags = compose_file_flags(compose_files)
    out = ssh(
        f"set -e; cd {release_dir!r}; "
        f"{prefix} docker compose -p {COMPOSE_PROJECT} {flags} config --quiet "
        f"&& echo COMPOSE_CONFIG_OK"
    ).strip()
    if "COMPOSE_CONFIG_OK" not in out.splitlines()[-1:]:
        raise DeployError(f"docker compose config --quiet failed under {release_dir}")
    ev.add(
        f"compose_config=ok dir={release_dir} "
        f"release_id={env['BIGGY_WORKSPACE_RELEASE_ID']} "
        f"files={','.join(compose_files)} "
        f"inference={'set' if 'BIGGY_WORKSPACE_LOCAL_INFERENCE_URL' in env else 'unset'}"
    )


def compose_up_cmd(
    release_dir: str,
    env: Mapping[str, str],
    compose_files: Sequence[str],
    *,
    build: bool,
) -> str:
    assert_required_compose_env(env)
    prefix = compose_env_shell_prefix(env)
    flags = compose_file_flags(compose_files)
    parts = [f"set -e; cd {release_dir!r}; "]
    if build:
        parts.append(
            f"{prefix} docker compose -p {COMPOSE_PROJECT} {flags} "
            f"build {COMPOSE_SERVICE}; "
        )
    no_build = " --no-build" if not build else ""
    parts.append(
        f"{prefix} docker compose -p {COMPOSE_PROJECT} {flags} "
        f"up -d --no-deps --force-recreate{no_build} {COMPOSE_SERVICE}; "
    )
    return "".join(parts)


def preflight(ev: Evidence) -> dict[str, Any]:
    local_static_files()
    assert_local_static_markers()
    ev.add(
        f"local_static=ok files={len(STATIC_REL_PATHS)} "
        f"no_{MODE_BANNER_MARKER}=1 has_apiUrl_fetch=1"
    )
    if not LAUNCH_AGENT_PLIST.is_file():
        raise DeployError(f"LaunchAgent missing: {LAUNCH_AGENT_PLIST}")
    ev.add(f"launch_agent_plist=present label={LAUNCH_AGENT_LABEL}")

    who = ssh(
        "printf '%s' \"$(hostname)\" && echo && id -u && docker --version | head -1"
    ).strip()
    ev.add("ssh=ok")
    info = discover_live_release(ev)
    info["remote_banner"] = who.splitlines()[0] if who else "unknown"

    health_raw = ssh(
        f"curl -fsS --max-time 5 {WORKSPACE_LOOPBACK_HEALTH} || echo '{{}}'"
    ).strip()
    try:
        health_payload = json.loads(health_raw)
    except json.JSONDecodeError:
        health_payload = {}
    if not isinstance(health_payload, dict) or not workspace_health_ok(health_payload):
        raise DeployError(
            f"workspace health JSON not ok preflight keys={list(health_payload)[:6]}"
        )
    ev.add("workspace_health_preflight=ok status=ok")

    live_env = required_compose_env(
        release_id=str(info["live_release_id"]),
        local_inference_url=str(info.get("local_inference_url") or ""),
    )
    info["rollback_compose_env"] = live_env
    validate_compose_config(
        ev,
        str(info["live_release_dir"]),
        live_env,
        list(info["compose_files"]),
    )
    return info


def create_immutable_release(ev: Evidence, live_dir: str, staged_dir: str) -> str:
    rid = release_id_for_dir(staged_dir)
    if not rid.startswith(STAGED_PREFIX):
        raise DeployError(f"staged release id must be {STAGED_PREFIX}* got={rid}")
    ssh(
        f"set -e; test ! -e {staged_dir!r}; "
        f"cp -a {live_dir!r} {staged_dir!r}; "
        f"echo COPIED",
        timeout=300,
    )
    ev.add(f"release_copy={staged_dir} from={live_dir} release_id={rid}")
    ev.add_rollback(f"previous_release={live_dir}")
    ev.add_rollback(f"new_release={staged_dir}")
    return staged_dir


def overlay_static_files(ev: Evidence, release_dir: str) -> None:
    for rel in STATIC_REL_PATHS:
        local = LOCAL_WORKSPACE_ROOT / rel
        remote = f"{release_dir}/{rel}"
        ssh(f"mkdir -p $(dirname {remote!r})")
        scp_to_remote(local, remote)
        ssh(f"chmod 644 {remote!r}")
    ev.add(f"overlay_static_files={len(STATIC_REL_PATHS)} only=app.js,index.html")


def preserve_rollback_image(ev: Evidence, info: dict[str, Any], release_dir: str) -> str:
    image_id = str(info.get("image_id") or "").strip()
    if not image_id or image_id == "none":
        raise DeployError("cannot preserve rollback image: missing Image ID")
    stamp = _utc_stamp()
    unique_tag = f"biggy-workspace-poc:static-update-rollback-{stamp}"
    prev = str(info["live_release_dir"])
    ssh(
        f"set -e; docker image inspect {image_id!r} >/dev/null; "
        f"docker tag {image_id!r} {unique_tag!r}; "
        f"printf '%s\\n' {image_id!r} > {release_dir}/.static-update-rollback-image-id; "
        f"printf '%s\\n' {unique_tag!r} > {release_dir}/.static-update-rollback-image-tag; "
        f"printf '%s\\n' {prev!r} > {release_dir}/.static-update-rollback-release; "
        f"echo PRESERVED"
    )
    info["rollback_image_id"] = image_id
    info["rollback_image_tag"] = unique_tag
    ev.add(f"rollback_image_preserved id={image_id[:19]}… tag={unique_tag}")
    ev.add_rollback(f"rollback_image_tag={unique_tag}")
    return unique_tag


def build_and_recreate(
    ev: Evidence,
    release_dir: str,
    env: Mapping[str, str],
    compose_files: Sequence[str],
) -> None:
    expected = release_id_for_dir(release_dir)
    if env.get("BIGGY_WORKSPACE_RELEASE_ID") != expected:
        raise DeployError(
            "compose RELEASE_ID must match staged directory: "
            f"env={env.get('BIGGY_WORKSPACE_RELEASE_ID')!r} dir={expected!r}"
        )
    remote = (
        compose_up_cmd(release_dir, env, compose_files, build=True)
        + "echo RECREATE_OK"
    )
    ssh(remote, timeout=900)
    ev.add(
        f"compose_recreate={COMPOSE_SERVICE} project={COMPOSE_PROJECT} "
        f"release_id={expected} files={','.join(compose_files)}"
    )


def remote_health_check(ev: Evidence) -> None:
    last = ""
    for attempt in range(1, 13):
        raw = ssh(
            f"curl -fsS --max-time 5 {WORKSPACE_LOOPBACK_HEALTH} 2>/dev/null || echo '{{}}'"
        ).strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict) and workspace_health_ok(payload):
            ev.add(f"workspace_health_post=ok attempt={attempt} status=ok")
            return
        last = f"keys={list(payload)[:6] if isinstance(payload, dict) else type(payload)}"
        time.sleep(2)
    raise DeployError(f"workspace health JSON not ok after retries last={last}")


def verify_served_static_markers(ev: Evidence) -> None:
    """Confirm live loopback HTML/JS match acceptance markers (remote curl only)."""
    index = ssh(
        f"curl -fsS --max-time 8 {WORKSPACE_LOOPBACK_INDEX} 2>/dev/null || true"
    )
    app_js = ssh(
        f"curl -fsS --max-time 8 {WORKSPACE_LOOPBACK_APP_JS} 2>/dev/null || true"
    )
    if not index.strip():
        raise DeployError("served index empty")
    if MODE_BANNER_MARKER in index:
        raise DeployError(f"served HTML still contains {MODE_BANNER_MARKER}")
    if APP_JS_FETCH_MARKER not in app_js:
        raise DeployError(f"served app.js missing {APP_JS_FETCH_MARKER}")
    ev.add(
        f"served_static=ok no_{MODE_BANNER_MARKER}=1 "
        f"has_fetch_apiUrl=1 index_bytes={len(index.encode())} "
        f"js_bytes={len(app_js.encode())}"
    )


def rollback_remote(ev: Evidence, release_dir: str | None, info: dict[str, Any]) -> None:
    prev = str(info.get("live_release_dir") or "").strip()
    tag = str(info.get("rollback_image_tag") or "").strip()
    image_id = str(info.get("rollback_image_id") or "").strip()
    compose_files = list(info.get("compose_files") or ["compose.yaml"])
    if release_dir and (not tag or not image_id or tag == "none" or image_id == "none"):
        meta = ssh(
            f"set +e; "
            f"id=$(cat {release_dir}/.static-update-rollback-image-id 2>/dev/null); "
            f"tg=$(cat {release_dir}/.static-update-rollback-image-tag 2>/dev/null); "
            f"prev=$(cat {release_dir}/.static-update-rollback-release 2>/dev/null); "
            f"echo ID:${{id:-none}}; echo TAG:${{tg:-none}}; echo PREV:${{prev:-none}}"
        )
        for line in meta.splitlines():
            if line.startswith("ID:") and line[3:] != "none":
                image_id = line[3:].strip()
            if line.startswith("TAG:") and line[4:] != "none":
                tag = line[4:].strip()
            if line.startswith("PREV:") and line[5:] != "none":
                prev = line[5:].strip()
    try:
        if not prev:
            raise DeployError("rollback missing previous release dir")
        if not image_id or image_id == "none":
            raise DeployError("rollback missing preserved Image ID")
        src = tag if tag and tag != "none" else image_id
        rollback_env = info.get("rollback_compose_env")
        if not isinstance(rollback_env, dict) or not rollback_env:
            rollback_env = required_compose_env(
                release_id=str(info.get("live_release_id") or release_id_for_dir(prev)),
                local_inference_url=str(info.get("local_inference_url") or ""),
            )
        assert_required_compose_env(rollback_env)
        validate_compose_config(ev, prev, rollback_env, compose_files)
        up = compose_up_cmd(prev, rollback_env, compose_files, build=False)
        ssh(
            f"set -e; "
            f"docker image inspect {src!r} >/dev/null; "
            f"docker tag {src!r} {COMPOSE_IMAGE_NAME!r}; "
            f"{up}"
            f"echo ROLLBACK_COMPOSE_OK",
            timeout=600,
        )
        ev.add(
            f"rollback_compose=ok release={prev} "
            f"release_id={rollback_env['BIGGY_WORKSPACE_RELEASE_ID']} "
            f"restored_via={src[:40]} -> {COMPOSE_IMAGE_NAME}"
        )
    except DeployError as exc:
        ev.add(f"rollback_compose=FAILED detail={exc}")


def restart_launchagent(ev: Evidence) -> None:
    uid = os.getuid()
    domain = f"gui/{uid}"
    target = f"{domain}/{LAUNCH_AGENT_LABEL}"
    plist = str(LAUNCH_AGENT_PLIST)
    _run(["launchctl", "bootout", domain, plist], check=False, timeout=60)
    _run(["launchctl", "bootstrap", domain, plist], timeout=60)
    _run(["launchctl", "enable", target], check=False, timeout=30)
    _run(["launchctl", "kickstart", "-k", target], timeout=60)
    ev.add(f"launchagent_restart=bootout+bootstrap {plist}")


def local_gui_health(ev: Evidence) -> None:
    last = ""
    for attempt in range(1, 16):
        try:
            status, payload = probe_json(LOCAL_GUI_HEALTH, timeout=3.0)
            if status == 200 and gui_health_ok(payload):
                ev.add(f"local_gui_health=ok attempt={attempt} status=ok")
                return
            last = f"http={status} json_status={payload.get('status')!r}"
        except DeployError as exc:
            last = str(exc)
        time.sleep(2)
    raise DeployError(f"local GUI health JSON not ok last={last}")


def apply(ev: Evidence) -> None:
    info = preflight(ev)
    release_dir: str | None = None
    try:
        stamp = _utc_stamp()
        release_id = f"{STAGED_PREFIX}{stamp}"
        staged_dir = f"{RELEASES_PARENT}/{release_id}"
        inference = str(info.get("local_inference_url") or "")
        compose_files = list(info["compose_files"])
        apply_env = required_compose_env(
            release_id=release_id, local_inference_url=inference
        )
        rollback_env = required_compose_env(
            release_id=str(info["live_release_id"]),
            local_inference_url=inference,
        )
        info["apply_compose_env"] = apply_env
        info["rollback_compose_env"] = rollback_env

        # Exact env proof BEFORE any mutation (against live tree / live compose files).
        validate_compose_config(
            ev, str(info["live_release_dir"]), apply_env, compose_files
        )
        validate_compose_config(
            ev, str(info["live_release_dir"]), rollback_env, compose_files
        )

        release_dir = create_immutable_release(
            ev, str(info["live_release_dir"]), staged_dir
        )
        preserve_rollback_image(ev, info, release_dir)
        overlay_static_files(ev, release_dir)
        validate_compose_config(ev, release_dir, apply_env, compose_files)
        build_and_recreate(ev, release_dir, apply_env, compose_files)
        remote_health_check(ev)
        verify_served_static_markers(ev)
        restart_launchagent(ev)
        local_gui_health(ev)
        ev.add("apply=SUCCESS")
        ev.add(
            "NEXT: Open Workspace from GUI — expect no mode-banner and planner calendar"
        )
    except Exception as exc:
        ev.add(f"apply=FAILED error={exc.__class__.__name__}: {exc}")
        if release_dir is not None:
            rollback_remote(ev, release_dir, info)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Atlas-only Biggy Workspace static update "
            "(app.js + index.html; discover live release via compose working_dir label)"
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    ev = Evidence()
    try:
        if args.preflight_only:
            preflight(ev)
            ev.add("mode=preflight-only result=OK")
            ev.dump()
            return 0
        apply(ev)
        ev.dump()
        return 0
    except Exception as exc:
        ev.add(f"result=FAILED {exc.__class__.__name__}: {exc}")
        ev.dump()
        return 1


if __name__ == "__main__":
    sys.exit(main())
