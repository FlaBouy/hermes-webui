#!/usr/bin/env python3
"""Deterministic Atlas deploy for Biggy Workspace ↔ Hermes session bridge only.

Modes:
  --preflight-only   Inspect remote/local readiness; no mutation
  --apply            Preflight then apply (release overlay, secrets, compose,
                     recreate workspace service only, update LaunchAgent, restart
                     ai.biggy.webui only)

Never prints secret values. Never puts secrets on argv. Does not change owner
password, Tailscale, or model services. Cursor must not run --apply; Atlas does.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import secrets
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ── Fixed contract (Atlas card) ─────────────────────────────────────────────
SSH_HOST = "192.168.0.25"
SSH_USER = "root"
SSH_CONNECT_TIMEOUT = "10"
REMOTE_CONTAINER = "biggy-workspace-poc-biggy-workspace-1"
COMPOSE_PROJECT = "biggy-workspace-poc"
COMPOSE_SERVICE = "biggy-workspace"
LIVE_RELEASE_DIR = (
    "/mnt/DATA_Hot/Biggy_Workspace/releases/"
    "f65a720d9e339d5954a171ec80473d3b34176019"
)
LIVE_RELEASE_ID = "f65a720d9e339d5954a171ec80473d3b34176019"
RELEASES_PARENT = "/mnt/DATA_Hot/Biggy_Workspace/releases"
KNOWN_STATE_DIR = "/mnt/DATA_Hot/Biggy_Workspace/state"
STATE_HINTS = (
    KNOWN_STATE_DIR,
    "/var/lib/biggy-workspace",
)
COMPOSE_INTERPOLATION_REQUIRED = (
    "BIGGY_WORKSPACE_STATE_DIR",
    "BIGGY_WORKSPACE_EXTERNAL_ORIGIN",
    "BIGGY_WORKSPACE_RELEASE_ID",
)
LOCAL_WORKSPACE_ROOT = Path("/Users/rick/Projects/biggy-workspace")
RUNTIME_REL_PATHS = (
    "biggy_workspace/auth.py",
    "biggy_workspace/app.py",
    "biggy_workspace/static/app.js",
    "biggy_workspace/static/index.html",
)
EMBED_ORIGIN = "http://127.0.0.1:8790"
UPSTREAM_ORIGIN = "https://plato.tail061f03.ts.net"
LAUNCH_AGENT_LABEL = "ai.biggy.webui"
LAUNCH_AGENT_PLIST = Path(
    "/Users/rick/Library/LaunchAgents/ai.biggy.webui.plist"
)
LOCAL_SECRET_PATH = Path(
    "/Users/rick/.hermes/profiles/biggy/secrets/biggy_hermes_bridge_secret"
)
REMOTE_SECRET_REL = "secrets/biggy_hermes_bridge_secret.txt"
COMPOSE_OVERRIDE_NAME = "compose.session-bridge.yaml"
CONTAINER_UID = 10001
CONTAINER_GID = 10001
WORKSPACE_LOOPBACK_HEALTH = "http://127.0.0.1:18765/health"
WORKSPACE_LOOPBACK_SESSION = "http://127.0.0.1:18765/api/v1/session"
LOCAL_GUI_HEALTH = "http://127.0.0.1:8790/health"
COMPOSE_IMAGE_NAME = "biggy-workspace-poc:local"
OWNER_SESSION_READY = frozenset({"login_required", "authenticated"})
_SMOKE_REMOTE_ZLIB_B64 = "eJzFVW1v2zYQ/q5fwREoIGGybKdtkmXThzTztqBpXDQGtn4SaOtsc5FJjaSSeEH+++5IxZbTeGuLArMBUyTv5bl7Hp8iuaq1cexPq1XK7NqmrDFVJacZGKPNZmfgrwasiyzMDDiWk2lmXSkVXomykgriBA+MrOMkknNWgYqDccJ+YsPDk4jhpzZSuZhfvRu/HRW/nJ5fsGBT2CWi4MmPzAhpgV2trYPV6E66+CCJohLmbCaqKl6BW+rSo0rZVJfr/FIrSNkSMYCxfpeEVKVwAnHSCUM8ZMykDXuoMAeVnJXNqrYxXSYZqJkusQzvjgWj92712Yewxj49JcjpJ2UBVh6W4D/Xhl2n7IZJxeIWHsOz+4ckk1ibjVucbbJMlGUR7GLyC1GcWW+tbqVbPkWEW11jq3GfMidXoBuXHydMWAxq662zTyNusSY696S1lW5BuMYoRgQtwAnnTEymKeMWd43lKTsYDJIkDZ2rtChtjCGzEkLfqDx+/8BDWLibQe121JT9Npm8H9ET4UODTgc8NDxqkRFltJvXgawpBd5Y77TF60qsCQ+G+CxsHXwjv0it9gW8f+jQtOkQYaPI2I3WNIqsQyXgJTp5sXo//n58NeFpeF46V5/0+8ODo2yA3+HJ8Pjo8HVf1LJ/M+xbsBaB9JdgVmB7UyPLBbSu9w/tugHDTxtUm5F/C0LPTxh/A8IAlsm+b/9V6db4TCsHyvUm6xrIVtR1JWfetU8t4x3bP3pv5GKx7p1VEl2CtWwNEEYSOX1NEwAFQuVmqJaYt+ALvAPFQ7/5zkSwjn2Xk4ToruOI4gJ0wDsusCRMScCg5GSntGMYsjs9tkA7Y8T3Peg0f2H9E9DDUtgACTdb/bxg8SNZOyBopugqRockCKWdBU9n0ssk2plk784vJ8X4LarLi6AEJaH8Whk4Ya/tI+3cSVd5xnBCNlXZw9hr/qkYzrS+lt5uStwV+laBKVpScpIEFvWVehgbuZBeYQTcInK4kVUGd2JVV9AVxoblV4OXxF5oRGixnwAtz9pHLAzMG4tE73s3tGZUcodbH4jofKTxmSzJHuJePSFu/OH81/PL4ufR5ccOf8iavv1GBP6fVO1APD76YfCEq7bOXX7yT/khKpHX3PP6H2T5mP/G1nNJ99H1+lFSOQ2OoR8q1F1Ob9U20D48jYK7GmY4SApyKXAg+qmyJ9Xh88o4vbgY/47S+NKKPFTVF1jbblwMGJT2D8800Vk="


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
        print("=== session-bridge deploy evidence (sanitized) ===")
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
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run a command. Never log argv elements that might contain secrets."""
    try:
        return subprocess.run(
            list(argv),
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=check,
            timeout=timeout,
            env=dict(env) if env is not None else None,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or b"").decode("utf-8", "replace").strip()
        # Sanitize: drop lines that look like env assignments of secrets.
        safe = []
        for line in err.splitlines()[:20]:
            upper = line.upper()
            if any(k in upper for k in ("SECRET", "PASSWORD", "TOKEN", "CREDENTIAL", "BEARER")):
                safe.append("<redacted-line>")
            else:
                safe.append(line[:200])
        raise DeployError(
            f"command failed ({exc.returncode}): {' '.join(argv[:3])}… :: "
            + " | ".join(safe)
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
    """Remote argv for `bash -lc <one-quoted-script>`.

    OpenSSH joins argv after the host with spaces. Without quoting, a compound
    `remote` string is split so `-lc` only sees the first word (e.g. `printf`),
    yielding exit 2 usage errors. Quote the entire script as one word.
    """
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


def generate_bridge_secret() -> str:
    # urlsafe, >=32 bytes entropy; never logged.
    return secrets.token_urlsafe(32)


def write_secret_file(path: Path, value: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write via temp + replace so partial files are not left readable.
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".bridge-secret.")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(value)
            fh.write("\n")
        os.chmod(tmp, mode)
        tmp.replace(path)
        os.chmod(path, mode)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def local_runtime_files() -> list[Path]:
    missing = []
    files = []
    for rel in RUNTIME_REL_PATHS:
        path = LOCAL_WORKSPACE_ROOT / rel
        if not path.is_file():
            missing.append(rel)
        else:
            files.append(path)
    if missing:
        raise DeployError(f"missing local runtime files: {', '.join(missing)}")
    return files


def compose_override_yaml() -> str:
    # Preserve existing compose; additive override only.
    return (
        "# Generated by deploy_biggy_workspace_session_bridge.py — session bridge only.\n"
        "# Does not alter owner password, Tailscale, or model services.\n"
        "services:\n"
        f"  {COMPOSE_SERVICE}:\n"
        "    environment:\n"
        "      BIGGY_WORKSPACE_HERMES_BRIDGE_SECRET_FILE: /run/secrets/biggy_hermes_bridge_secret\n"
        f"      BIGGY_WORKSPACE_HERMES_EMBED_ORIGINS: \"{EMBED_ORIGIN}\"\n"
        "    secrets:\n"
        "      - biggy_hermes_bridge_secret\n"
        "secrets:\n"
        "  biggy_hermes_bridge_secret:\n"
        f"    file: ./{REMOTE_SECRET_REL}\n"
    )


def required_compose_env(
    *,
    release_id: str,
    local_inference_url: str = "",
) -> dict[str, str]:
    """Exact Compose interpolation env for apply and rollback (no secrets)."""
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
        raise DeployError(
            "missing compose interpolation env: " + ", ".join(missing)
        )
    return dict(env)


def compose_env_shell_prefix(env: Mapping[str, str]) -> str:
    assert_required_compose_env(env)
    return " ".join(
        f"{key}={shlex.quote(str(env[key]))}"
        for key in (
            *COMPOSE_INTERPOLATION_REQUIRED,
            *(
                ["BIGGY_WORKSPACE_LOCAL_INFERENCE_URL"]
                if "BIGGY_WORKSPACE_LOCAL_INFERENCE_URL" in env
                else []
            ),
        )
    )


def release_id_for_staged_dir(release_dir: str) -> str:
    return Path(str(release_dir).rstrip("/")).name


def probe_live_local_inference_url() -> str:
    """Whitelist-only read of LOCAL_INFERENCE_URL from live Config.Env (no Env dump)."""
    inspect_tpl = "{{range .Config.Env}}{{println .}}{{end}}"
    awk_prog = (
        '$1=="BIGGY_WORKSPACE_LOCAL_INFERENCE_URL" '
        '{print substr($0, index($0,"=")+1); exit}'
    )
    raw = ssh(
        "set +e; "
        f"docker inspect -f {shlex.quote(inspect_tpl)} {REMOTE_CONTAINER} 2>/dev/null "
        f"| awk -F= {shlex.quote(awk_prog)}"
    ).strip()
    if not raw or "\n" in raw:
        return ""
    if any(
        tok in raw.upper()
        for tok in ("CREDENTIAL", "PASSWORD", "SECRET", "TOKEN")
    ):
        return ""
    return raw


def validate_compose_config(
    ev: Evidence,
    release_dir: str,
    env: Mapping[str, str],
    *,
    with_override: bool = False,
) -> None:
    """Fail closed on missing interpolation before backup/mutation/recreate."""
    assert_required_compose_env(env)
    files = "-f compose.yaml"
    if with_override:
        files += f" -f {COMPOSE_OVERRIDE_NAME}"
    prefix = compose_env_shell_prefix(env)
    out = ssh(
        f"set -e; cd {release_dir!r}; "
        f"{prefix} docker compose -p {COMPOSE_PROJECT} {files} config --quiet "
        f"&& echo COMPOSE_CONFIG_OK"
    ).strip()
    if "COMPOSE_CONFIG_OK" not in out.splitlines()[-1:]:
        raise DeployError(f"docker compose config --quiet failed under {release_dir}")
    rid = env["BIGGY_WORKSPACE_RELEASE_ID"]
    ev.add(
        f"compose_config=ok release_dir={release_dir} "
        f"release_id={rid} override={int(with_override)} "
        f"inference={'set' if 'BIGGY_WORKSPACE_LOCAL_INFERENCE_URL' in env else 'unset'}"
    )


def compose_up_cmd(
    release_dir: str,
    env: Mapping[str, str],
    *,
    with_override: bool,
    build: bool,
) -> str:
    assert_required_compose_env(env)
    files = "-f compose.yaml"
    if with_override:
        files += f" -f {COMPOSE_OVERRIDE_NAME}"
    prefix = compose_env_shell_prefix(env)
    parts = [
        f"set -e; cd {release_dir!r}; ",
    ]
    if build:
        parts.append(
            f"{prefix} docker compose -p {COMPOSE_PROJECT} {files} "
            f"build {COMPOSE_SERVICE}; "
        )
    no_build = " --no-build" if not build else ""
    parts.append(
        f"{prefix} docker compose -p {COMPOSE_PROJECT} {files} "
        f"up -d --no-deps --force-recreate{no_build} {COMPOSE_SERVICE}; "
    )
    return "".join(parts)


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


def preflight(ev: Evidence) -> dict[str, Any]:
    info: dict[str, Any] = {}
    local_runtime_files()
    ev.add(f"local_runtime_files=ok count={len(RUNTIME_REL_PATHS)}")

    if not LAUNCH_AGENT_PLIST.is_file():
        raise DeployError(f"LaunchAgent missing: {LAUNCH_AGENT_PLIST}")
    ev.add(f"launch_agent_plist=present label={LAUNCH_AGENT_LABEL}")

    # SSH + remote layout
    who = ssh("printf '%s' \"$(hostname)\" && echo && id -u && docker --version | head -1").strip()
    ev.add("ssh=ok")
    info["remote_banner"] = who.splitlines()[0] if who else "unknown"

    live_check = ssh(
        f"test -d {LIVE_RELEASE_DIR!r} && echo LIVE_OK || echo LIVE_MISSING; "
        f"test -f {LIVE_RELEASE_DIR!r}/compose.yaml && echo COMPOSE_OK || echo COMPOSE_MISSING; "
        f"docker inspect -f '{{{{.State.Status}}}}|{{{{.Image}}}}|{{{{.Config.Image}}}}' "
        f"{REMOTE_CONTAINER} 2>/dev/null || echo 'missing|none|none'"
    ).strip().splitlines()
    if not live_check or live_check[0] != "LIVE_OK":
        raise DeployError(f"live release dir missing: {LIVE_RELEASE_DIR}")
    if len(live_check) < 2 or live_check[1] != "COMPOSE_OK":
        raise DeployError("live compose.yaml missing")
    status_image = live_check[2] if len(live_check) > 2 else "missing|none|none"
    container_status, image_id, image_tag = parse_container_inspect_line(status_image)
    if container_status == "missing" or image_id in {"", "none"}:
        raise DeployError(f"container not found or missing Image ID: {REMOTE_CONTAINER}")
    info["container_status"] = container_status
    info["image_id"] = image_id
    info["image_tag"] = image_tag
    info["image"] = image_tag
    ev.add(
        f"container={REMOTE_CONTAINER} status={container_status} "
        f"image_id={image_id[:19]}… tag={image_tag}"
    )

    # State path discovery (no env dump)
    state_probe = ssh(
        "set -e; "
        f"for p in {' '.join(repr(x) for x in STATE_HINTS)}; do "
        "  if [ -d \"$p\" ]; then echo DIR:$p; "
        "    if [ -f \"$p/workspace.sqlite3\" ]; then echo DB:$p/workspace.sqlite3; fi; "
        "  fi; "
        "done; "
        f"docker inspect -f '{{{{range .Mounts}}}}{{{{println .Source .Destination}}}}{{{{end}}}}' "
        f"{REMOTE_CONTAINER} 2>/dev/null | awk '/workspace/ {{print \"MOUNT:\" $0}}' || true"
    )
    info["state_probe"] = state_probe.strip()
    ev.add("state_probe=" + (state_probe.strip().replace("\n", "; ")[:300] or "none"))

    # Owner session setup state — no login, no secrets
    session_raw = ssh(
        "curl -fsS --max-time 5 "
        f"{WORKSPACE_LOOPBACK_SESSION} || echo '{{\"state\":\"unreachable\"}}'"
    ).strip()
    try:
        session = json.loads(session_raw)
    except json.JSONDecodeError:
        session = {"state": "unreachable"}
    state = parse_owner_session_state(session if isinstance(session, dict) else {})
    info["owner_session_state"] = state
    ev.add(f"owner_session_state={state}")
    assert_owner_session_ready(state)

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

    # Whitelist-only inference URL (never dump full Config.Env / secrets).
    inference = probe_live_local_inference_url()
    info["local_inference_url"] = inference
    ev.add(f"local_inference_url={'set' if inference else 'unset'}")

    # Prove live compose interpolates with reconstructed required env (no mutation).
    live_env = required_compose_env(
        release_id=LIVE_RELEASE_ID,
        local_inference_url=inference,
    )
    info["rollback_compose_env"] = live_env
    validate_compose_config(ev, LIVE_RELEASE_DIR, live_env, with_override=False)

    # Disk / zfs availability note
    zfs = ssh("command -v zfs >/dev/null && echo zfs_yes || echo zfs_no").strip()
    info["zfs"] = zfs
    ev.add(f"zfs={zfs}")

    info["live_release"] = LIVE_RELEASE_DIR
    info["live_release_id"] = LIVE_RELEASE_ID
    return info


def _remote_db_path(state_probe: str) -> str | None:
    for line in state_probe.splitlines():
        if line.startswith("DB:"):
            return line[3:].strip()
    return None


def backup_remote_state(ev: Evidence, info: dict[str, Any]) -> str:
    stamp = _utc_stamp()
    db = _remote_db_path(str(info.get("state_probe") or ""))
    backup_root = f"/mnt/DATA_Hot/Biggy_Workspace/backups/session-bridge-{stamp}"
    ssh(f"mkdir -p {backup_root!r}")
    if db:
        # Prefer SQLite online backup API via remote python (no secret content printed).
        ssh(
            "python3 - <<'PY'\n"
            "import sqlite3\n"
            f"src = {db!r}\n"
            f"dst = {backup_root + '/workspace.sqlite3.bak'!r}\n"
            "s = sqlite3.connect(src)\n"
            "d = sqlite3.connect(dst)\n"
            "s.backup(d)\n"
            "d.close(); s.close()\n"
            "print('sqlite_backup_ok')\n"
            "PY",
            timeout=180,
        )
        ev.add(f"state_backup=sqlite path={backup_root}/workspace.sqlite3.bak")
    elif info.get("zfs") == "zfs_yes":
        # Best-effort dataset snapshot if state dir is on ZFS; ignore failure shape.
        snap = ssh(
            "set +e; "
            "ds=$(df -h /mnt/DATA_Hot/Biggy_Workspace/state 2>/dev/null | awk 'NR==2{print $1}'); "
            f"if [ -n \"$ds\" ] && zfs list -H -o name \"$ds\" >/dev/null 2>&1; then "
            f"  zfs snapshot \"$ds@session-bridge-{stamp}\" && echo SNAP:$ds@session-bridge-{stamp}; "
            "else echo SNAP_SKIP; fi"
        ).strip()
        ev.add(f"state_backup={snap}")
    else:
        # Copy state directory if present
        ssh(
            "set -e; "
            "if [ -d /mnt/DATA_Hot/Biggy_Workspace/state ]; then "
            f"  cp -a /mnt/DATA_Hot/Biggy_Workspace/state {backup_root}/state; "
            "  echo STATE_COPY_OK; "
            "else echo STATE_COPY_SKIP; fi"
        )
        ev.add(f"state_backup=dir_copy root={backup_root}")
    ev.add_rollback(f"state_backup={backup_root}")
    return backup_root


def create_immutable_release(ev: Evidence, release_dir: str) -> str:
    """Copy live release to a fresh staged dir. Never deletes prior staged releases."""
    new_dir = str(release_dir).rstrip("/")
    rid = release_id_for_staged_dir(new_dir)
    if not rid.startswith("session-bridge-"):
        raise DeployError(f"staged release id must be session-bridge-* got={rid}")
    ssh(
        f"set -e; test ! -e {new_dir!r}; "
        f"cp -a {LIVE_RELEASE_DIR!r} {new_dir!r}; "
        f"echo COPIED",
        timeout=300,
    )
    ev.add(f"release_copy={new_dir} from={LIVE_RELEASE_DIR} release_id={rid}")
    ev.add_rollback(f"previous_release={LIVE_RELEASE_DIR}")
    ev.add_rollback(f"new_release={new_dir}")
    return new_dir


def overlay_runtime_files(ev: Evidence, release_dir: str) -> None:
    for rel in RUNTIME_REL_PATHS:
        local = LOCAL_WORKSPACE_ROOT / rel
        remote = f"{release_dir}/{rel}"
        # Ensure parent exists; scp file
        ssh(f"mkdir -p $(dirname {remote!r})")
        scp_to_remote(local, remote)
        # Match packaged non-root readability (world read on app files is typical in image;
        # host overlay for build context: readable).
        ssh(f"chmod 644 {remote!r}")
    ev.add(f"overlay_runtime_files={len(RUNTIME_REL_PATHS)}")


def install_remote_secret(ev: Evidence, release_dir: str, secret: str) -> None:
    remote_path = f"{release_dir}/{REMOTE_SECRET_REL}"
    ssh(f"mkdir -p $(dirname {remote_path!r})")
    # Stream secret on stdin — never argv. Mode 640 root:10001 for container readability.
    ssh(
        f"umask 077; cat > {remote_path!r}; "
        f"chown {CONTAINER_UID}:{CONTAINER_GID} {remote_path!r}; "
        f"chmod 640 {remote_path!r}; "
        f"test -s {remote_path!r} && echo SECRET_INSTALLED",
        input_bytes=(secret + "\n").encode("utf-8"),
    )
    # Confirm metadata only
    meta = ssh(f"stat -c '%U:%G %a %s' {remote_path!r}").strip()
    # If GNU stat unavailable, try BSD-like — PLATO is Linux.
    ev.add(f"remote_secret_meta={meta} path={REMOTE_SECRET_REL}")


def write_remote_compose_override(ev: Evidence, release_dir: str) -> None:
    remote_path = f"{release_dir}/{COMPOSE_OVERRIDE_NAME}"
    payload = compose_override_yaml().encode("utf-8")
    ssh(
        f"cat > {remote_path!r} && chmod 644 {remote_path!r} && echo OVERRIDE_OK",
        input_bytes=payload,
    )
    ev.add(f"compose_override={COMPOSE_OVERRIDE_NAME}")


def preserve_rollback_image(ev: Evidence, info: dict[str, Any], release_dir: str) -> str:
    """Tag immutable Image ID uniquely BEFORE build overwrites :local."""
    image_id = str(info.get("image_id") or "").strip()
    if not image_id or image_id == "none":
        raise DeployError("cannot preserve rollback image: missing Image ID")
    stamp = _utc_stamp()
    unique_tag = f"biggy-workspace-poc:session-bridge-rollback-{stamp}"
    ssh(
        f"set -e; docker image inspect {image_id!r} >/dev/null; "
        f"docker tag {image_id!r} {unique_tag!r}; "
        f"printf '%s\\n' {image_id!r} > {release_dir}/.session-bridge-rollback-image-id; "
        f"printf '%s\\n' {unique_tag!r} > {release_dir}/.session-bridge-rollback-image-tag; "
        f"printf '%s\\n' {LIVE_RELEASE_DIR!r} > {release_dir}/.session-bridge-rollback-release; "
        f"echo PRESERVED"
    )
    info["rollback_image_id"] = image_id
    info["rollback_image_tag"] = unique_tag
    ev.add(f"rollback_image_preserved id={image_id[:19]}… tag={unique_tag}")
    ev.add_rollback(f"rollback_image_tag={unique_tag}")
    return unique_tag

def build_and_recreate_workspace(
    ev: Evidence,
    release_dir: str,
    env: Mapping[str, str],
) -> None:
    assert_required_compose_env(env)
    expected_rid = release_id_for_staged_dir(release_dir)
    if env.get("BIGGY_WORKSPACE_RELEASE_ID") != expected_rid:
        raise DeployError(
            "compose RELEASE_ID must match staged directory: "
            f"env={env.get('BIGGY_WORKSPACE_RELEASE_ID')!r} dir={expected_rid!r}"
        )
    remote = compose_up_cmd(
        release_dir, env, with_override=True, build=True
    ) + "echo RECREATE_OK"
    ssh(remote, timeout=900)
    ev.add(
        f"compose_recreate={COMPOSE_SERVICE} project={COMPOSE_PROJECT} "
        f"release_id={expected_rid}"
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
            break
        last = f"keys={list(payload)[:6] if isinstance(payload, dict) else type(payload)}"
        time.sleep(2)
    else:
        raise DeployError(f"workspace health JSON not ok after retries last={last}")

    sess = ssh(
        f"curl -fsS --max-time 5 {WORKSPACE_LOOPBACK_SESSION} 2>/dev/null "
        f"|| echo '{{\"state\":\"unreachable\"}}'"
    ).strip()
    try:
        state = parse_owner_session_state(json.loads(sess))
    except json.JSONDecodeError:
        state = "unknown"
    ev.add(f"owner_session_state_post={state}")
    assert_owner_session_ready(state)

def bridge_smoke_and_origin_proof(ev: Evidence, secret: str) -> None:
    """Secret-safe S2S mint + Origin allow/deny; no lasting task writes.

    Uses `python3 -c` so stdin stays reserved for the bridge secret. A heredoc
    would consume stdin and yield SMOKE_FAIL secret_short.
    """
    remote = smoke_remote_bash_command()
    if secret and secret in remote:
        raise DeployError("bridge smoke remote command unexpectedly contains secret")
    out = ssh(
        remote,
        timeout=60,
        input_bytes=(secret + "\n").encode("utf-8"),
    )
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    for ln in lines:
        if ln.startswith("SMOKE_"):
            ev.add(sanitize_smoke_diagnostic(ln, secret=secret))
    if "SMOKE_ALL_OK" not in lines:
        smoke_lines = [
            sanitize_smoke_diagnostic(ln, secret=secret)
            for ln in lines
            if ln.startswith("SMOKE_")
        ]
        fails = [ln for ln in smoke_lines if ln.startswith("SMOKE_FAIL")]
        diag = fails or smoke_lines[-6:] or ["no-output"]
        raise DeployError("bridge smoke/origin proof failed: " + " | ".join(diag))


def smoke_remote_bash_command(source: str | None = None) -> str:
    """Remote shell command: python3 -c <quoted nonsecret source>; stdin = secret."""
    src = _smoke_remote_source() if source is None else source
    return f"python3 -c {shlex.quote(src)}"


def sanitize_smoke_diagnostic(line: str, *, secret: str = "") -> str:
    """Keep SMOKE_* diagnostics; never echo secret/token material."""
    text = str(line or "")
    if secret:
        text = text.replace(secret, "[REDACTED]")
    # Defensive: redact common token-bearing shapes if ever present.
    lowered = text.lower()
    if "session_token=" in lowered or "bearer " in lowered:
        parts = []
        for tok in text.split():
            if tok.lower().startswith("bearer") or "session_token=" in tok.lower():
                parts.append("[REDACTED]")
            else:
                parts.append(tok)
        text = " ".join(parts)
    return text


def rollback_remote(ev: Evidence, release_dir: str | None, info: dict[str, Any]) -> None:
    """Retag preserved Image ID onto :local and recreate without rebuild."""
    prev = LIVE_RELEASE_DIR
    tag = str(info.get("rollback_image_tag") or "").strip()
    image_id = str(info.get("rollback_image_id") or "").strip()
    if release_dir and (not tag or not image_id or tag == "none" or image_id == "none"):
        meta = ssh(
            f"set +e; "
            f"id=$(cat {release_dir}/.session-bridge-rollback-image-id 2>/dev/null); "
            f"tg=$(cat {release_dir}/.session-bridge-rollback-image-tag 2>/dev/null); "
            f"echo ID:${{id:-none}}; echo TAG:${{tg:-none}}"
        )
        for line in meta.splitlines():
            if line.startswith("ID:") and line[3:] != "none":
                image_id = line[3:].strip()
            if line.startswith("TAG:") and line[4:] != "none":
                tag = line[4:].strip()
    try:
        if not image_id or image_id == "none":
            raise DeployError("rollback missing preserved Image ID")
        src = tag if tag and tag != "none" else image_id
        rollback_env = info.get("rollback_compose_env")
        if not isinstance(rollback_env, dict) or not rollback_env:
            rollback_env = required_compose_env(
                release_id=LIVE_RELEASE_ID,
                local_inference_url=str(info.get("local_inference_url") or ""),
            )
        assert_required_compose_env(rollback_env)
        if rollback_env.get("BIGGY_WORKSPACE_RELEASE_ID") != LIVE_RELEASE_ID:
            raise DeployError(
                "rollback RELEASE_ID must be live release id "
                f"got={rollback_env.get('BIGGY_WORKSPACE_RELEASE_ID')!r}"
            )
        validate_compose_config(ev, prev, rollback_env, with_override=False)
        up = compose_up_cmd(prev, rollback_env, with_override=False, build=False)
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
            f"release_id={LIVE_RELEASE_ID} "
            f"restored_via={src[:40]} -> {COMPOSE_IMAGE_NAME}"
        )
    except DeployError as exc:
        ev.add(f"rollback_compose=FAILED detail={exc}")


def backup_and_update_launchagent(ev: Evidence, secret_path: Path) -> Path:
    if not LAUNCH_AGENT_PLIST.is_file():
        raise DeployError("LaunchAgent plist missing")
    stamp = _utc_stamp()
    backup = LAUNCH_AGENT_PLIST.with_suffix(f".plist.session-bridge-{stamp}.bak")
    shutil.copy2(LAUNCH_AGENT_PLIST, backup)
    ev.add(f"plist_backup={backup}")
    ev.add_rollback(f"plist_backup={backup}")

    data = plistlib.loads(LAUNCH_AGENT_PLIST.read_bytes())
    env = dict(data.get("EnvironmentVariables") or {})
    env["HERMES_WEBUI_BIGGY_WORKSPACE_UPSTREAM"] = UPSTREAM_ORIGIN
    env["HERMES_WEBUI_BIGGY_WORKSPACE_BRIDGE_SECRET_FILE"] = str(secret_path)
    data["EnvironmentVariables"] = env
    # Atomic replace
    fd, tmp_name = tempfile.mkstemp(
        dir=str(LAUNCH_AGENT_PLIST.parent), prefix=".ai.biggy.webui.", suffix=".plist"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            plistlib.dump(data, fh, sort_keys=False)
        os.chmod(tmp, 0o644)
        tmp.replace(LAUNCH_AGENT_PLIST)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    # Verify keys present without printing values
    verify = plistlib.loads(LAUNCH_AGENT_PLIST.read_bytes())
    venv = verify.get("EnvironmentVariables") or {}
    if venv.get("HERMES_WEBUI_BIGGY_WORKSPACE_UPSTREAM") != UPSTREAM_ORIGIN:
        raise DeployError("plist upstream not applied")
    if venv.get("HERMES_WEBUI_BIGGY_WORKSPACE_BRIDGE_SECRET_FILE") != str(secret_path):
        raise DeployError("plist secret file path not applied")
    # Preserve other fields: label unchanged
    if verify.get("Label") != LAUNCH_AGENT_LABEL:
        raise DeployError("plist label mutated unexpectedly")
    ev.add(
        "plist_updated=keys "
        "HERMES_WEBUI_BIGGY_WORKSPACE_UPSTREAM,"
        "HERMES_WEBUI_BIGGY_WORKSPACE_BRIDGE_SECRET_FILE"
    )
    return backup


def restore_launchagent(backup: Path, ev: Evidence) -> None:
    if backup.is_file():
        shutil.copy2(backup, LAUNCH_AGENT_PLIST)
        ev.add(f"plist_restored_from={backup}")


def restart_launchagent(ev: Evidence) -> None:
    """Unload/reload on-disk plist so EnvironmentVariables are picked up.

    kickstart alone retains the previously loaded job definition/env.
    """
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


def install_local_secret(ev: Evidence, secret: str) -> tuple[Path, Path | None]:
    """Write local bridge secret; backup any existing file first for rollback."""
    prior_backup: Path | None = None
    if LOCAL_SECRET_PATH.is_file():
        stamp = _utc_stamp()
        prior_backup = LOCAL_SECRET_PATH.with_suffix(f".secret.pre-bridge-{stamp}.bak")
        shutil.copy2(LOCAL_SECRET_PATH, prior_backup)
        os.chmod(prior_backup, 0o600)
        ev.add(f"local_secret_backup={prior_backup}")
        ev.add_rollback(f"local_secret_backup={prior_backup}")
    write_secret_file(LOCAL_SECRET_PATH, secret, mode=0o600)
    st = LOCAL_SECRET_PATH.stat()
    ev.add(
        f"local_secret_meta=mode={oct(st.st_mode & 0o777)} size={st.st_size} "
        f"path={LOCAL_SECRET_PATH}"
    )
    return LOCAL_SECRET_PATH, prior_backup


def restore_local_secret(backup: Path | None, ev: Evidence) -> None:
    if backup is not None and backup.is_file():
        shutil.copy2(backup, LOCAL_SECRET_PATH)
        os.chmod(LOCAL_SECRET_PATH, 0o600)
        ev.add(f"local_secret_restored_from={backup}")


def apply(ev: Evidence) -> None:
    info = preflight(ev)  # fails closed on setup_required / unreachable
    release_dir: str | None = None
    plist_backup: Path | None = None
    secret_backup: Path | None = None
    secret = generate_bridge_secret()
    try:
        # Fresh staged release id (= directory basename). Do not reuse/delete prior
        # session-bridge-* staged dirs or backups from earlier attempts.
        stamp = _utc_stamp()
        release_id = f"session-bridge-{stamp}"
        staged_dir = f"{RELEASES_PARENT}/{release_id}"
        inference = str(info.get("local_inference_url") or "")
        apply_env = required_compose_env(
            release_id=release_id,
            local_inference_url=inference,
        )
        rollback_env = required_compose_env(
            release_id=LIVE_RELEASE_ID,
            local_inference_url=inference,
        )
        info["apply_compose_env"] = apply_env
        info["rollback_compose_env"] = rollback_env

        # Exact env config proof BEFORE any backup/mutation/recreate.
        validate_compose_config(ev, LIVE_RELEASE_DIR, apply_env, with_override=False)
        validate_compose_config(ev, LIVE_RELEASE_DIR, rollback_env, with_override=False)

        backup_remote_state(ev, info)
        release_dir = create_immutable_release(ev, staged_dir)
        if release_id_for_staged_dir(release_dir) != release_id:
            raise DeployError("staged release id mismatch after copy")
        preserve_rollback_image(ev, info, release_dir)  # BEFORE build
        overlay_runtime_files(ev, release_dir)
        install_remote_secret(ev, release_dir, secret)
        write_remote_compose_override(ev, release_dir)
        validate_compose_config(ev, release_dir, apply_env, with_override=True)
        build_and_recreate_workspace(ev, release_dir, apply_env)
        remote_health_check(ev)
        bridge_smoke_and_origin_proof(ev, secret)
        local_path, secret_backup = install_local_secret(ev, secret)
        secret = ""
        plist_backup = backup_and_update_launchagent(ev, local_path)
        restart_launchagent(ev)
        local_gui_health(ev)
        ev.add("apply=SUCCESS")
        ev.add(
            f"NEXT: Open Workspace from GUI {EMBED_ORIGIN} — expect no owner login panel"
        )
    except Exception as exc:
        ev.add(f"apply=FAILED error={exc.__class__.__name__}: {exc}")
        if release_dir is not None:
            rollback_remote(ev, release_dir, info)
        if plist_backup is not None:
            try:
                restore_launchagent(plist_backup, ev)
                restart_launchagent(ev)
            except Exception as restore_exc:
                ev.add(f"plist_rollback=FAILED {restore_exc.__class__.__name__}")
        if secret_backup is not None:
            try:
                restore_local_secret(secret_backup, ev)
            except Exception as restore_exc:
                ev.add(f"local_secret_rollback=FAILED {restore_exc.__class__.__name__}")
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Atlas-only Biggy Workspace session-bridge deploy (Hermes↔PLATO)"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    ev = Evidence()
    try:
        if args.preflight_only:
            preflight(ev)  # raises on setup_required / unreachable / bad health
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


# ── Testable pure helpers (mocks exercise these) ────────────────────────────
def parse_owner_session_state(payload: Mapping[str, Any]) -> str:
    return str(payload.get("state") or "unknown")


def assert_owner_session_ready(state: str) -> str:
    normalized = str(state or "unknown").strip() or "unknown"
    if normalized not in OWNER_SESSION_READY:
        raise DeployError(
            f"owner_session_not_ready state={normalized} "
            f"(need one of {sorted(OWNER_SESSION_READY)} before mutations)"
        )
    return normalized


def workspace_health_ok(payload: Mapping[str, Any]) -> bool:
    return str(payload.get("status") or "") == "ok"


def gui_health_ok(payload: Mapping[str, Any]) -> bool:
    return str(payload.get("status") or "") == "ok"


def sanitize_stat_line(line: str) -> str:
    return line.strip()[:120]


def parse_container_inspect_line(line: str) -> tuple[str, str, str]:
    parts = (line or "").strip().split("|")
    while len(parts) < 3:
        parts.append("none")
    return parts[0], parts[1], parts[2]


def _smoke_remote_source() -> str:
    import base64
    import zlib
    return zlib.decompress(base64.b64decode(_SMOKE_REMOTE_ZLIB_B64)).decode("utf-8")


if __name__ == "__main__":
    sys.exit(main())
