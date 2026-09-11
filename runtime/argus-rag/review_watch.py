"""Bounded active-review intake: native events plus mount-safe reconciliation.

Publication contract: atomic rename preferred; direct copies require two unchanged
metadata observations and a complete PDF EOF. The ingestion contract rechecks bytes
before activation. One native and one OCR slot prevent OCR head-of-line blocking.
"""
import errno
import json
import os
from pathlib import Path
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from review_pdf import _native_profile
from review_readiness import digest


def atomic_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2))
    temp.replace(path)


class ActiveReviewWatcher:
    def __init__(self, root, state, registry, collection, ingest, event):
        self.root = Path(root)
        self.state = Path(state)
        self.registry = registry
        self.collection = collection
        self.ingest = ingest
        self.event = event
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.paused = lambda: False
        self.required_mount = None
        self.seen = {}
        self.pending = {}
        self.running = {}
        self.lock = threading.RLock()
        self.pools = {lane: ThreadPoolExecutor(max_workers=1, thread_name_prefix='review-'+lane) for lane in ['native', 'ocr']}
        self.receipt_path = self.state / 'watcher.json'
        self.receipts = json.loads(self.receipt_path.read_text()) if self.receipt_path.exists() else {}
        self.observer = None
        self.last_fault = None
        self.fault_path = self.state / 'root-health.json'
        self.reconcile()

    def reconcile(self):
        for record in self.registry.reconcile(self.collection):
            self.event('reconciled', source=record.get('source'), reason=record.get('error'))
        with self.lock:
            receipts = list(self.receipts.items())
        for path, old in receipts:
            if any(p == path for p, _ in self.running.values()):
                continue
            source = Path(path).relative_to(Path(os.environ.get('ARGUS_RAG_LIBRARY_ROOT', self.root.parent))).as_posix()
            record = self.registry.record(self.collection, source)
            if old.get('state') != record.get('state'):
                old.update(state=record.get('state', 'DETECTED'), attempts=0)
                old.pop('attempt_signature', None)
                self.event('receipt_reconciled', path=path, state=old['state'])

    def fault(self, code, reason):
        value = {'state': 'FAILED' if code else 'READY', 'fault': code, 'reason': reason,
                 'root': str(self.root), 'at': time.time()}
        atomic_json(self.fault_path, value)
        if code != self.last_fault:
            self.event('root_fault' if code else 'root_restored', **value)
            self.last_fault = code

    def scan_metadata(self):
        if self.required_mount and not os.path.ismount(self.required_mount):
            self.fault('MISSING_MOUNT', 'Required review mount is unavailable')
            return None
        found = {}
        def visit(directory):
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.name.startswith('.') or entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        visit(entry.path)
                    elif entry.name.lower().endswith('.pdf'):
                        st = entry.stat(follow_symlinks=False)
                        found[entry.path] = [st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino]
        try:
            visit(self.root)
        except OSError as exc:
            code = {errno.ENOENT: 'MISSING_ROOT', errno.EACCES: 'PERMISSION_DENIED', errno.ENOTDIR: 'NOT_DIRECTORY'}.get(exc.errno, 'IO_FAILURE')
            self.fault(code, str(exc))
            return None
        self.fault(None, 'Review root accessible' if found else 'Review root accessible and empty')
        return found

    def start_events(self):
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
            outer = self
            class Events(FileSystemEventHandler):
                def on_any_event(self, event):
                    if not event.is_directory:
                        outer.event('filesystem_event', event=event.event_type, path=event.src_path)
                        outer.wake.set()
            self.observer = Observer()
            # Watch parent so root disappearance/restoration does not require restart.
            self.observer.schedule(Events(), str(self.root.parent), recursive=True)
            self.observer.start()
            self.event('event_observer_started', observer=type(self.observer).__name__)
        except (ImportError, OSError) as exc:
            self.event('event_observer_unavailable', error=str(exc))

    def classify(self, path):
        from pypdf import PdfReader
        at = time.time()
        reader = PdfReader(path)
        profiles = [_native_profile(p, i) for i, p in enumerate(reader.pages, 1)]
        lane = 'ocr' if any(p['needs_ocr'] for p in profiles) else 'native'
        self.event('intake_profile', path=path, lane=lane, pages=len(profiles), seconds=time.time()-at)
        return lane

    def run_one(self, path, item):
        start = time.time()
        self.event('scheduled', path=path, detected_at=item['detected_at'], queue_wait=start-item['detected_at'], lane=item['lane'])
        try:
            result = self.ingest(path, detected_at=item['detected_at'])
            receipt = {'state': result['state'], 'receipt': result,
                       'ready_hash': result.get('manifest', {}).get('source_hash'), 'attempts': 0}
        except Exception as exc:
            old = self.receipts.get(path, {})
            receipt = dict(old, state=getattr(exc, 'state', 'FAILED'), error=str(exc), attempts=old.get('attempts', 0)+1)
            receipt['terminal_hash'] = getattr(exc, 'manifest', {}).get('source_hash')
        receipt.update(attempt_signature=item['signature'], detected_at=item['detected_at'], finished_at=time.time())
        with self.lock:
            self.receipts[path] = receipt
            atomic_json(self.receipt_path, self.receipts)
        self.wake.set()

    def loop(self):
        self.start_events()
        try:
            while not self.stop.is_set():
                now = time.time()
                current = self.scan_metadata()
                if current is not None:
                    if now - getattr(self, 'last_reconcile', 0) > 1:
                        self.reconcile()
                        self.last_reconcile = now
                    for path in set(self.seen) - set(current):
                        self.pending.pop(path, None)
                        self.seen.pop(path, None)
                        self.event('source_missing', path=path)
                    for path, sig in current.items():
                        old = self.seen.get(path)
                        if not old or old['signature'] != sig:
                            self.seen[path] = {'signature': sig, 'detected_at': now, 'stable': 0}
                            source=Path(path).relative_to(Path(os.environ.get('ARGUS_RAG_LIBRARY_ROOT',self.root.parent))).as_posix()
                            self.registry.notice(self.collection,source,path,now)
                            self.event('metadata_detected', path=path, signature=sig)
                            continue
                        old['stable'] += 1
                        if now - old['detected_at'] < .25:
                            continue
                        receipt = self.receipts.get(path, {})
                        if path in self.pending or any(p == path for p, _ in self.running.values()):
                            continue
                        if receipt.get('attempt_signature') == sig and receipt.get('state') not in {'DETECTED', 'RETRYING'}:
                            continue
                        if receipt.get('attempts', 0) >= 3 and receipt.get('attempt_signature') == sig:
                            continue
                        try:
                            reusable_hash = receipt.get('ready_hash') if receipt.get('state') == 'READY' else receipt.get('terminal_hash')
                            if reusable_hash and receipt.get('state') in {'READY','NEEDS_REVIEW'} and digest(path) == reusable_hash:
                                with self.lock:
                                    receipt['attempt_signature'] = sig
                                    atomic_json(self.receipt_path, self.receipts)
                                self.event('unchanged_source_reused', path=path)
                                continue
                            with open(path, 'rb') as stream:
                                stream.seek(max(0, sig[0]-2048))
                                complete = b'%%EOF' in stream.read()
                            if not complete:
                                continue
                            lane = self.classify(path)
                            if len(self.pending) >= 32:
                                self.event('queue_capacity', path=path, limit=32)
                                continue
                            self.pending[path] = dict(old, lane=lane)
                        except (OSError, ValueError) as exc:
                            self.event('stable_gate_wait', path=path, reason=str(exc))
                    for lane, (_path, future) in list(self.running.items()):
                        if future.done():
                            future.result()
                            self.running.pop(lane)
                    for lane in self.pools:
                        if self.paused() or lane in self.running:
                            continue
                        candidates = [(p, v) for p, v in self.pending.items() if v['lane'] == lane]
                        if candidates:
                            path, item = max(candidates, key=lambda x: x[1]['detected_at'])
                            self.pending.pop(path)
                            self.running[lane] = (path, self.pools[lane].submit(self.run_one, path, item))
                # 250 ms metadata-only reconciliation covers SMB event loss;
                # no source hashing or PDF parsing occurs for unchanged receipts.
                self.wake.wait(.25)
                self.wake.clear()
        finally:
            if self.observer:
                self.observer.stop()
                self.observer.join(timeout=2)
            for pool in self.pools.values():
                pool.shutdown(wait=True)
