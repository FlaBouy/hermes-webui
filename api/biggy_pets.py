"""Read-only, local pet catalog. Never serves arbitrary paths or active content."""

import hashlib
import json
import os
from pathlib import Path
import re
import stat

_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_MIME = {".webp": "image/webp", ".png": "image/png"}


def _root():
    return Path(os.environ.get("BIGGY_PETS_DIR") or Path.home() / ".codex" / "pets")


def _read_at(directory, name, limit):
    # Hold the directory and file handles; reject symlinks at point of use.
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("unsupported pet file")
        data = source.read(limit + 1)
        if len(data) > limit:
            raise ValueError("pet file too large")
        return data


def _load(pet_id):
    if not _ID.fullmatch(pet_id):
        raise ValueError("invalid pet")
    try:
        root_fd = os.open(_root(), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            folder_fd = os.open(pet_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
            try:
                manifest = json.loads(_read_at(folder_fd, "pet.json", 16384))
                if not isinstance(manifest, dict) or manifest.get("id") != pet_id:
                    raise ValueError("unsupported pet manifest")
                if manifest.get("spriteVersionNumber") == 2:
                    layout = dict(columns=8, rows=11, idleFrames=7, frameWidth=192, frameHeight=208,
                                  frameDurations=[160] * 7)
                elif manifest.get("format") == "strip-v1":
                    count = manifest.get("frames")
                    width, height = manifest.get("frameWidth"), manifest.get("frameHeight")
                    durations = manifest.get("frameDurations")
                    if (type(count) is not int or not 1 <= count <= 32
                            or any(type(n) is not int or not 1 <= n <= 2048 for n in (width, height))
                            or not isinstance(durations, list) or len(durations) != count
                            or any(type(n) is not int or not 40 <= n <= 10000 for n in durations)):
                        raise ValueError("unsupported strip layout")
                    layout = dict(columns=count, rows=1, idleFrames=count, frameWidth=width,
                                  frameHeight=height, frameDurations=durations)
                else:
                    raise ValueError("unsupported pet manifest")
                filename = manifest.get("spritesheetPath", "")
                if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9_-]+\.(webp|png)", filename):
                    raise ValueError("invalid sprite filename")
                data = _read_at(folder_fd, filename, 16 * 1024 * 1024)
                mime = _MIME[Path(filename).suffix]
                if mime == "image/webp" and not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
                    raise ValueError("invalid WebP")
                if mime == "image/png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError("invalid PNG")
                label = manifest.get("displayName")
                if not isinstance(label, str) or not label.strip():
                    label = pet_id
                item = {"id": pet_id, "displayName": label[:80], "spriteVersionNumber": manifest.get("spriteVersionNumber"),
                        **layout, "defaultAnchor": "dialog-right" if manifest.get("defaultAnchor") == "dialog-right" else "prompt-above",
                        "spriteUrl": f"/api/biggy/pets/{pet_id}/sprite?v={hashlib.sha256(data).hexdigest()[:16]}"}
                return item, data, mime
            finally:
                os.close(folder_fd)
        finally:
            os.close(root_fd)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("pet unavailable") from exc


def catalog():
    pets, unavailable = [], 0
    try:
        entries = sorted(_root().iterdir(), key=lambda entry: entry.name)
    except FileNotFoundError:
        return {"pets": [], "unavailable": 0}
    for entry in entries[:200]:
        if not _ID.fullmatch(entry.name):
            continue
        try:
            pets.append(_load(entry.name)[0])
        except ValueError:
            unavailable += 1
    return {"pets": pets, "unavailable": unavailable}


def sprite(pet_id):
    _, data, mime = _load(pet_id)
    return data, mime
