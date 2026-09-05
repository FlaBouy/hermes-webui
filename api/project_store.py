"""Atomic, revision-checked persistence with the existing list-of-dicts schema."""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
from contextlib import contextmanager

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None
try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None

_LOCK = threading.RLock()


class ProjectStoreError(RuntimeError):
    status = 503


class ProjectConflict(ProjectStoreError):
    status = 409


class ProjectSnapshot(list):
    def __init__(self, rows, revision, path):
        super().__init__(rows)
        self.revision = revision
        self.path = str(path)


def read_projects(path):
    path = Path(path).resolve()
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return ProjectSnapshot([], None, path)
    except OSError as exc:
        raise ProjectStoreError("Project data cannot be read; no changes were made. Check storage and retry.") from exc
    try:
        rows = json.loads(raw)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("expected a list of project objects")
    except (ValueError, UnicodeError) as exc:
        raise ProjectStoreError("Project data is malformed. The original file is preserved; restore a validated copy before retrying.") from exc
    return ProjectSnapshot(rows, hashlib.sha256(raw).hexdigest(), path)


@contextmanager
def _process_lock(path):
    # Permanent lock inode: never unlink it while other writers may be waiting.
    with open(path, "a+b") as lock:
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        elif msvcrt is not None:  # pragma: no cover - Windows
            if os.fstat(lock.fileno()).st_size == 0:
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:  # pragma: no cover
            raise ProjectStoreError("Project storage locking is unavailable; no changes were made.")


def write_projects(path, projects):
    path = Path(path).resolve()
    if not isinstance(projects, list) or any(not isinstance(row, dict) for row in projects):
        raise ProjectStoreError("Expected a list of project objects; no changes were made.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, _process_lock(path.with_name(path.name + ".lock")):
        current = read_projects(path)  # Malformed existing data never gets replaced.
        if isinstance(projects, ProjectSnapshot):
            if projects.path != str(path) or projects.revision != current.revision:
                raise ProjectConflict("Project data changed since it was loaded. Reload and retry; no changes were made.")
        elif current.revision is not None:
            raise ProjectConflict("Save requires a loaded project snapshot. Reload and retry; no changes were made.")
        text = json.dumps(projects, ensure_ascii=False, indent=2)
        fd, name = tempfile.mkstemp(prefix=".projects-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                if path.exists():
                    os.fchmod(stream.fileno(), stat.S_IMODE(path.stat().st_mode))
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
            if isinstance(projects, ProjectSnapshot):
                projects.revision = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if os.name == "posix":
                directory = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)
