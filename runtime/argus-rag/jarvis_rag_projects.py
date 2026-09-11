#!/usr/bin/env python3
"""Project watcher candidate: content identity, bounded retries and READY receipts.

Explicit state paths prevent accidental use of owner state during development.
The original production watcher is recorded in baseline_hashes.json.
"""
import json
import os
from pathlib import Path
import sys
import time

from review_readiness import Registry, NotReady, digest, ingest
from review_pdf import extract_pdf

INTERVAL = 30
MAX_ATTEMPTS = 3


def scan(root):
    root = Path(root)
    # os.scandir propagates missing, permission and I/O failures; rglob can hide them.
    with os.scandir(root) as entries:
        list(entries)
    return {str(p): digest(p) for p in root.rglob('*.pdf') if p.is_file()}


def ingest_file(path, *, root, engine=None, registry=None, detected_at=None):
    relative = Path(path).resolve().relative_to(Path(root).resolve())
    if len(relative.parts) < 2:
        raise NotReady('File must belong to a project subfolder', 'FAILED')
    if engine is None:
        import jarvis_rag_poc as engine
    library = os.environ.get('ARGUS_RAG_LIBRARY_ROOT')
    source = Path(path).resolve().relative_to(Path(library).resolve()).as_posix() if library else 'Projects/' + relative.as_posix()
    return ingest(path, source=source, project=relative.parts[0],
                  collection=engine.COLLECTION, extract_fn=getattr(engine, 'extract', extract_pdf),
                  embed_fn=engine.embed, qd_fn=engine.qd, registry=registry, detected_at=detected_at)


def poll(root, receipts, *, ingest_fn, now=None):
    """Advance successful version only after READY; surface bounded retry state."""
    now = time.time() if now is None else now
    current = scan(root)
    for path, identity in current.items():
        previous = receipts.get(path, {})
        if previous.get('ready_hash') == identity:
            continue
        if previous.get('attempt_hash') != identity:
            previous = dict(previous, attempt_hash=identity, attempts=0, next_retry=0, detected_at=now, state='DETECTED')
        if previous.get('attempts', 0) >= MAX_ATTEMPTS or previous.get('next_retry', 0) > now:
            receipts[path] = previous
            continue
        previous['attempts'] += 1
        previous['state'] = 'INGESTING'
        try:
            result = ingest_fn(path, detected_at=previous['detected_at'])
            if result.get('state') != 'READY' or result.get('chunks', 0) < 1:
                raise NotReady('Ingest did not produce a nonzero READY receipt', 'FAILED')
            if digest(path) != identity:
                raise NotReady('File changed before watcher receipt', 'RETRYING')
            previous.update(ready_hash=identity, state='READY', receipt=result, error=None)
        except Exception as exc:
            terminal = getattr(exc, 'state', 'FAILED')
            previous.update(state=terminal, error=str(exc))
            if terminal != 'NEEDS_REVIEW' and previous['attempts'] < MAX_ATTEMPTS:
                previous.update(state='RETRYING', next_retry=now + INTERVAL * 2 ** previous['attempts'])
            else:
                previous['attempts'] = MAX_ATTEMPTS
        receipts[path] = previous
    return receipts


def main():
    if '--active' in sys.argv:
        from review_session import ReviewSession
        config_path = Path(sys.argv[sys.argv.index('--active') + 1])
        ReviewSession(json.loads(config_path.read_text())).run()
        return
    root = os.environ['ARGUS_PROJECT_ROOT']
    state_path = Path(os.environ['ARGUS_PROJECT_WATCH_STATE'])
    registry = Registry()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    receipts = json.loads(state_path.read_text()) if state_path.exists() else {}
    while True:
        poll(root, receipts, ingest_fn=lambda path, detected_at: ingest_file(path, root=root, registry=registry, detected_at=detected_at))
        temporary = state_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(receipts, indent=2))
        os.replace(temporary, state_path)
        if '--once' in sys.argv:
            return
        time.sleep(INTERVAL)


if __name__ == '__main__':
    main()
