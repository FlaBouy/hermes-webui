#!/usr/bin/env python3
"""Bounded immutable source snapshots for Project Review extraction.

Copies the live library file into a server-owned evidence snapshot, hashes the
snapshot bytes, and returns paths so parsers never re-open a mutating live path.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from typing import Any


def file_sha256(path: str, *, max_bytes: int | None = None) -> str:
    digest = hashlib.sha256()
    total = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes is not None and total > int(max_bytes):
                raise ValueError("file exceeds bounded hash size limit")
            digest.update(chunk)
    return digest.hexdigest()


def materialize_source_snapshot(
    source_path: str,
    *,
    evidence_dir: str,
    max_bytes: int,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Copy source into evidence_dir/source_snapshot and hash the snapshot.

    Parsers must open ``snapshot_path`` only. ``source_path`` is provenance only.
    If ``expected_sha256`` is supplied (wrapper pre-hash) and the snapshot hash
    differs, the source mutated and extraction fails closed.
    """
    real = os.path.realpath(source_path)
    if not os.path.isfile(real):
        raise FileNotFoundError("source file not found")
    st = os.stat(real)
    size_bytes = int(st.st_size)
    if size_bytes > int(max_bytes):
        raise ValueError("source exceeds bounded file size limit")
    mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))

    snap_root = os.path.join(evidence_dir, "source_snapshot")
    os.makedirs(snap_root, exist_ok=True)
    basename = os.path.basename(real) or "source.bin"
    # Exclusive create (mkstemp) — avoids same-second/same-pid collisions.
    fd, snapshot_path = tempfile.mkstemp(
        prefix="src.",
        suffix="." + basename,
        dir=snap_root,
    )
    os.close(fd)

    # Copy then hash the immutable snapshot (never hash-then-reopen live path).
    shutil.copyfile(real, snapshot_path)
    try:
        shutil.copystat(real, snapshot_path, follow_symlinks=True)
    except Exception:
        pass
    # Best-effort immutability for the snapshot inode on supporting filesystems.
    try:
        mode = os.stat(snapshot_path).st_mode
        os.chmod(snapshot_path, mode & ~0o222)
    except Exception:
        pass

    snap_st = os.stat(snapshot_path)
    if int(snap_st.st_size) != size_bytes:
        raise ValueError("snapshot size mismatch vs source at copy time")
    source_sha = file_sha256(snapshot_path, max_bytes=max_bytes)
    if expected_sha256 and str(expected_sha256).lower() != source_sha.lower():
        raise ValueError(
            "source changed between wrapper hash and snapshot materialization; "
            "refusing mismatched extraction"
        )

    return {
        "source_path": real,
        "snapshot_path": snapshot_path,
        "source_sha256": source_sha,
        "source_size_bytes": size_bytes,
        "source_mtime_ns": mtime_ns,
        "snapshot_size_bytes": int(snap_st.st_size),
        "original_unmodified": True,
        "parse_path": snapshot_path,
        "note": "Parsers must open snapshot_path; source_path is provenance only.",
    }
