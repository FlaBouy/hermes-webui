"""Project Review eligibility and durable generation activation; no startup I/O.

All readers and writers must share ARGUS_REVIEW_STATE_DIR. Deployment must wire
this contract at every serving boundary before ingesting candidate generations.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid
import threading

from review_owner import identity, demonstrably_dead

STATES = frozenset('DETECTED INGESTING OCR_REQUIRED OCR_RUNNING INDEXING VALIDATING READY NEEDS_REVIEW FAILED RETRYING'.split())
ABSTAIN = 'I do not have sufficient grounded information from the requested source.'


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def usable(text):
    return re.sub(r'<!--.*?-->', '', str(text or ''), flags=re.S).strip()


class NotReady(RuntimeError):
    def __init__(self, message, state='NEEDS_REVIEW', manifest=None):
        super().__init__(message)
        self.state = state
        self.manifest = manifest or {}


class Registry:
    """One atomic pointer per collection/source; old generations retained for rollback.

    BEGIN IMMEDIATE and a per-source lease serialize writers without holding a
    database transaction across OCR. Expired writers cannot activate a candidate.
    """
    def __init__(self, root=None):
        value = root or os.environ.get('ARGUS_REVIEW_STATE_DIR')
        if not value:
            raise NotReady('Shared ARGUS_REVIEW_STATE_DIR is not configured', 'FAILED')
        self.root = Path(value)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'generations.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS documents (key TEXT PRIMARY KEY, active TEXT, token TEXT, lease REAL, record TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS owners (token TEXT PRIMARY KEY, owner TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS generations (key TEXT NOT NULL, generation TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(key,generation))')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('PRAGMA synchronous=FULL')
        return db

    @staticmethod
    def key(collection, source):
        return json.dumps([collection, source], separators=(',', ':'))

    def begin(self, collection, source):
        token = uuid.uuid4().hex
        key = self.key(collection, source)
        self.reconcile(collection)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT active,token,lease FROM documents WHERE key=?', (key,)).fetchone()
            if row and row[1] and row[2] > time.time():
                raise NotReady('Ingestion already in progress for this source', 'RETRYING')
            record = {'state': 'DETECTED', 'source': source, 'history': [], 'timings': {}, 'owner': identity()}
            db.execute('INSERT INTO owners VALUES (?,?)', (token, json.dumps(record['owner'])))
            db.execute('INSERT INTO documents VALUES (?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET token=excluded.token,lease=excluded.lease,record=excluded.record',
                       (key, row[0] if row else None, token, time.time() + 60, json.dumps(record)))
        return token, record

    def notice(self, collection, source, path, detected_at):
        """Publish a new intake without taking a long-running writer lease."""
        record={'state':'DETECTED','source':source,'path':str(Path(path).resolve()),'collection':collection,
                'detected_at':detected_at,'published_at':time.time(),'queue_owner':identity(),
                'history':[{'state':'DETECTED','seconds':0}],'timings':{}}
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO documents VALUES (?,?,?,?,?)',
                       (self.key(collection,source),None,None,0,json.dumps(record)))

    def request_retry(self, collection, source):
        """Queue operator-requested ingestion without stealing a live writer."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            key = self.key(collection, source)
            row = db.execute('SELECT token,lease,record FROM documents WHERE key=?', (key,)).fetchone()
            if not row or (row[0] and row[1] > time.time()):
                return False
            record = json.loads(row[2])
            record.update(state='RETRYING', published_at=time.time(), error='Operator requested ingestion')
            db.execute('UPDATE documents SET token=NULL,lease=0,record=? WHERE key=?', (json.dumps(record),key))
        return True

    def update(self, collection, source, token, record, *, activate=None, release=False):
        if record['state'] not in STATES:
            raise ValueError('Unknown readiness state')
        key = self.key(collection, source)
        record['published_at'] = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT active,token,lease FROM documents WHERE key=?', (key,)).fetchone()
            if not row or row[1] != token or row[2] <= time.time():
                raise NotReady('Ingestion lease lost; candidate cannot activate', 'FAILED')
            record['active_generation'] = activate or row[0]
            if activate:
                if record['state'] != 'READY' or not record.get('canary', {}).get('passed') or record.get('chunks', 0) < 1:
                    raise NotReady('Activation requires a validated READY receipt', 'FAILED')
                db.execute('INSERT INTO generations VALUES (?,?,?)', (key, activate, json.dumps(record)))
            db.execute('UPDATE documents SET active=?,token=?,lease=?,record=? WHERE key=?',
                       (activate or row[0], None if release else token, 0 if release else time.time() + 60, json.dumps(record), key))

    def heartbeat(self, collection, source, token):
        with self.connect() as db:
            now = time.time()
            db.execute('UPDATE documents SET lease=? WHERE key=? AND token=? AND lease>?',
                       (now + 60, self.key(collection, source), token, now))

    def fail(self, collection, source, token, record):
        """An expired owner may report failure, but may never activate or replace a new owner."""
        with self.connect() as db:
            row = db.execute('SELECT active,token FROM documents WHERE key=?', (self.key(collection, source),)).fetchone()
            if row and row[1] == token:
                record.update(active_generation=row[0], published_at=time.time())
                db.execute('UPDATE documents SET token=NULL,lease=0,record=? WHERE key=? AND token=?',
                           (json.dumps(record), self.key(collection, source), token))

    def reconcile(self, collection):
        changes = []
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('SELECT key,active,token,lease,record FROM documents').fetchall()
            for key, active, token, lease, raw in rows:
                if json.loads(key)[0] != collection:
                    continue
                record = json.loads(raw)
                reason = None
                if token:
                    owner_row = db.execute('SELECT owner FROM owners WHERE token=?', (token,)).fetchone()
                    dead = owner_row and demonstrably_dead(json.loads(owner_row[0]))
                    if dead or lease <= time.time():
                        reason = 'Writer process is gone' if dead else 'Writer lease expired'
                elif record.get('state') in {'INGESTING', 'OCR_RUNNING', 'INDEXING', 'VALIDATING', 'DETECTED'}:
                    queued=record.get('state')=='DETECTED' and record.get('queue_owner')
                    if not queued or demonstrably_dead(record['queue_owner']):
                        reason = 'Pending state has no writer lease'
                target_state = 'RETRYING'
                if not token and record.get('state') == 'READY' and record.get('path') and not Path(record['path']).is_file():
                    reason = 'Validated source is missing or inaccessible'
                    target_state = 'FAILED'
                if reason:
                    record.update(state=target_state, error=reason, active_generation=active, published_at=time.time())
                    record.setdefault('reconciliation', []).append({'at': time.time(), 'reason': reason})
                    db.execute('UPDATE documents SET token=NULL,lease=0,record=? WHERE key=?', (json.dumps(record), key))
                    changes.append(record)
        return changes

    def rollback(self, collection, source, generation):
        """Explicit operator rollback to a retained validated generation.

        Never inferred from failures. This does not claim that the old revision
        matches a newer source file; UI source-hash validation remains in force.
        """
        key = self.key(collection, source)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT token,lease FROM documents WHERE key=?', (key,)).fetchone()
            if current and current[0] and current[1] > time.time():
                raise NotReady('Cannot rollback during active ingestion', 'RETRYING')
            previous = db.execute('SELECT record FROM generations WHERE key=? AND generation=?', (key, generation)).fetchone()
            if not previous:
                raise NotReady('Rollback generation has no validated receipt', 'FAILED')
            record = json.loads(previous[0])
            record['rollback_at'] = time.time()
            db.execute('UPDATE documents SET active=?,token=NULL,lease=0,record=? WHERE key=?', (generation, json.dumps(record), key))
        return record

    def active(self, collection):
        with self.connect() as db:
            rows = db.execute('SELECT key,active FROM documents WHERE active IS NOT NULL').fetchall()
        return {json.loads(key)[1]: active for key, active in rows if json.loads(key)[0] == collection}

    def record(self, collection, source):
        with self.connect() as db:
            row = db.execute('SELECT record FROM documents WHERE key=?', (self.key(collection, source),)).fetchone()
        return json.loads(row[0]) if row else {'state': 'DETECTED'}


def eligible_payload(payload, active):
    return bool(payload.get('generation') and active.get(payload.get('source')) == payload.get('generation')
                and payload.get('quality_state') == 'verified' and payload.get('source_hash')
                and isinstance(payload.get('pdf_page'), int) and payload['pdf_page'] > 0
                and payload.get('chunk_id') and usable(payload.get('text')))


def active_filter(collection, registry=None):
    active = (registry or Registry()).active(collection)
    # Empty registry must match nothing, never fall back to legacy unverified vectors.
    return {'must': [{'key': 'generation', 'match': {'any': list(active.values()) or ['__no_ready_generation__']}},
                     {'key': 'quality_state', 'match': {'value': 'verified'}}]}


def filter_hits(hits, collection, registry=None):
    try:
        active = (registry or Registry()).active(collection)
    except (NotReady, OSError, sqlite3.Error):
        return []
    return [h for h in hits if eligible_payload(h.get('payload') or {}, active)]


def validate_manifest(manifest, source_hash):
    if manifest.get('source_hash') != source_hash or not manifest.get('source_readable'):
        raise NotReady('Source identity/readability is unproven', manifest=manifest)
    pages = manifest.get('pages') or []
    count = manifest.get('page_count')
    if not isinstance(count, int) or count < 1 or [p.get('pdf_page') for p in pages] != list(range(1, count + 1)):
        raise NotReady('Expected page coverage is incomplete', manifest=manifest)
    if not any(usable(p.get('text')) for p in pages):
        raise NotReady('Zero usable chunks', 'FAILED', manifest)
    if manifest.get('quality_state') != 'verified':
        raise NotReady('Extraction requires review: ' + '; '.join(manifest.get('warnings') or []), manifest=manifest)
    for page in pages:
        if page.get('quality_state') != 'verified' or not page.get('processed'):
            raise NotReady('Page quality is unknown or degraded', manifest=manifest)
        if not usable(page.get('text')) and not page.get('blank_verified'):
            raise NotReady('Page is unaccounted for', manifest=manifest)
        if not page.get('extraction_method'):
            raise NotReady('Missing extraction provenance', manifest=manifest)


def page_chunks(manifest, limit=1600):
    """Keep page and complete lines. Repeat a table header for each later row.

    Oversized lines remain complete; no scalar truncation of engineering facts.
    Structured items remain attached as provenance; exact bounding boxes must
    be selected from the supporting item, not inferred from the chunk box.
    """
    for page in manifest['pages']:
        header = None
        group = []
        size = 0
        for line in usable(page.get('text')).splitlines():
            if not line.strip():
                continue
            if '|' in line and header is None:
                header = line
            if group and size + len(line) > limit:
                yield dict(page, text='\n'.join(group))
                group, size = [], 0
            if '|' in line and header and line != header and header not in group:
                group.append(header)
                size += len(header)
            group.append(line)
            size += len(line) + 1
        if group:
            yield dict(page, text='\n'.join(group))


def _ack(result):
    if not isinstance(result, dict) or (result.get('result') or {}).get('status') != 'completed':
        raise RuntimeError('Vector write not acknowledged as completed')


def payload_matches(actual, expected, trail=()):
    """Exact provenance except at most two binary64 ULPs in bbox coordinates.

    Remote JSON codecs can round a coordinate by one representable float.
    This does not tolerate changes to text, identity, pages, structure or IDs.
    """
    import math
    if isinstance(expected, dict):
        return isinstance(actual, dict) and actual.keys() == expected.keys() and all(
            payload_matches(actual[k],v,trail+(k,)) for k,v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual,list) and len(actual)==len(expected) and all(
            payload_matches(a,e,trail+(i,)) for i,(a,e) in enumerate(zip(actual,expected,strict=True)))
    if type(actual) is not type(expected):
        return False
    if isinstance(expected,float) and len(trail)==4 and trail[0]=='items' and trail[2]=='bbox' and trail[3] in {'l','r','t','b'}:
        return math.isfinite(actual) and math.isfinite(expected) and abs(actual-expected)<=2*max(math.ulp(actual),math.ulp(expected))
    return actual == expected


def ingest(path, *, source, collection, extract_fn, embed_fn, qd_fn, project=None, registry=None, detected_at=None):
    registry = registry or Registry()
    if str(path).lower().endswith('.ocr.txt'):
        raise NotReady('OCR sidecars belong to their source PDF', 'FAILED')
    token, record = registry.begin(collection, source)
    heartbeat_stop = threading.Event()
    def renew():
        while not heartbeat_stop.wait(10):
            with contextlib.suppress(sqlite3.Error):
                registry.heartbeat(collection, source, token)
    heartbeat_thread = threading.Thread(target=renew, daemon=True)
    heartbeat_thread.start()
    start = time.monotonic()
    record['detected_at'] = detected_at or time.time()
    record['project'] = project
    record['path'] = str(Path(path).resolve())
    record['collection'] = collection
    record['history'].append({'state': 'DETECTED', 'seconds': 0})
    timings = record['timings']

    def state(value):
        record['state'] = value
        record['history'].append({'state': value, 'seconds': round(time.monotonic() - start, 6)})
        registry.update(collection, source, token, record)

    try:
        state('INGESTING')
        at = time.monotonic()
        source_hash = digest(path)
        timings['intake'] = time.monotonic() - at
        at = time.monotonic()
        text, manifest = extract_fn(path, state)
        record['manifest'] = manifest
        timings.update(manifest.get('timings') or {})
        timings['extraction_total'] = time.monotonic() - at
        validate_manifest(manifest, source_hash)
        at = time.monotonic()
        chunks = list(page_chunks(manifest))
        if not chunks:
            raise NotReady('Zero usable chunks', 'FAILED', manifest)
        timings['chunking'] = time.monotonic() - at
        at = time.monotonic()
        vectors = embed_fn([c['text'] for c in chunks])
        if len(vectors) != len(chunks) or any(not v or len(v) != 768 or any(not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x) for x in v) or not any(v) for v in vectors):
            raise RuntimeError('Embedding count, dimension or values invalid')
        timings['embeddings'] = time.monotonic() - at
        generation = uuid.uuid4().hex
        record['candidate_generation'] = generation
        state('INDEXING')
        points = []
        for i, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, source + generation + str(i)))
            payload = {k: chunk.get(k) for k in ('pdf_page', 'printed_page', 'items', 'extraction_method', 'text')}
            payload.update(source=source, abspath=str(Path(path).resolve()), source_hash=source_hash,
                           source_version=source_hash, generation=generation, chunk=i, chunk_id=point_id,
                           quality_state='verified', extraction_quality='verified', project=project,
                           page_count=manifest['page_count'], extraction_manifest={'schema': manifest.get('schema'), 'source_hash': source_hash, 'processing_options': manifest.get('processing_options')})
            points.append({'id': point_id, 'vector': vector, 'payload': payload})
        at = time.monotonic()
        for offset in range(0, len(points), 64):
            _ack(qd_fn(f'/collections/{collection}/points?wait=true', {'points': points[offset:offset + 64]}, method='PUT'))
        timings['indexing'] = time.monotonic() - at
        state('VALIDATING')
        at = time.monotonic()
        candidate_filter = {'must': [{'key': 'generation', 'match': {'value': generation}}, {'key': 'source', 'match': {'value': source}}]}
        response = qd_fn(f'/collections/{collection}/points/count', {'filter': candidate_filter, 'exact': True})
        if (response.get('result') or {}).get('count') != len(points):
            raise RuntimeError('Candidate vector count mismatch')
        # Read back exact IDs and compare all required metadata, not just count.
        for offset in range(0, len(points), 64):
            batch = points[offset:offset + 64]
            read = qd_fn(f'/collections/{collection}/points', {'ids': [p['id'] for p in batch], 'with_payload': True})
            actual = {str(p['id']): p.get('payload') for p in read.get('result', [])}
            if any(not payload_matches(actual.get(p['id']), p['payload']) for p in batch):
                raise RuntimeError('Candidate provenance did not survive indexing')
        timings['validation'] = time.monotonic() - at
        at = time.monotonic()
        probe = next((line for line in chunks[0]['text'].splitlines() if re.search(r'\w', line)), '')
        probe_vector = embed_fn([probe])
        if len(probe_vector) != 1 or len(probe_vector[0]) != 768:
            raise RuntimeError('Canary embedding failed')
        canary = qd_fn(f'/collections/{collection}/points/search', {'vector': probe_vector[0], 'filter': candidate_filter, 'limit': 3, 'with_payload': True})
        if not any(payload_matches(h.get('payload'), p['payload']) for h in canary.get('result', []) for p in points):
            raise RuntimeError('Post-ingest retrieval canary failed')
        timings['retrieval_canary'] = time.monotonic() - at
        at = time.monotonic()
        if digest(path) != source_hash:
            raise NotReady('Source changed during ingestion', 'RETRYING', manifest)
        timings['activation_source_hash'] = time.monotonic() - at
        record.update(state='READY', chunks=len(points), canary={'query': probe, 'passed': True})
        record['history'].append({'state': 'READY', 'seconds': time.monotonic() - start})
        timings['time_to_ready'] = max(0, time.time() - record['detected_at'])
        # Only this transaction makes candidate evidence eligible. Old points
        # are deliberately retained; bounded retirement is a deployment task.
        at = time.monotonic()
        registry.update(collection, source, token, record, activate=generation, release=True)
        timings['registry_activation'] = time.monotonic() - at
        return record
    except Exception as exc:
        record['state'] = getattr(exc, 'state', 'FAILED')
        record['error'] = str(exc)
        record['manifest'] = getattr(exc, 'manifest', None) or record.get('manifest', {})
        record['timings']['elapsed_to_terminal'] = time.monotonic() - start
        record['history'].append({'state': record['state'], 'seconds': time.monotonic() - start})
        registry.fail(collection, source, token, record)
        raise
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1)


def grounded_answer(question, hits):
    """Conservative extractive engineering support; unsupported relations abstain.

    This P0 gate intentionally does not approve arbitrary model-generated prose.
    General semantic entailment remains outside the qualified envelope.
    """
    q = question.lower()
    documents = re.findall(r'\b\d{2}-\d{2,}[a-z0-9]*\b', q)
    tags = re.findall(r'\b[a-z]{2,}-\d+[a-z0-9]*\b', q)
    qualified = []
    for hit in hits:
        p = hit.get('payload') or hit
        if p.get('quality_state') != 'verified' or not p.get('source_hash') or not isinstance(p.get('pdf_page'), int) or p.get('pdf_page', 0) < 1 or not p.get('chunk_id'):
            continue
        source = str(p.get('source') or '')
        if documents and not all(d in source.lower() for d in documents):
            continue
        text = usable(p.get('text'))
        for tag in tags:
            candidates = set(re.findall(r'\b' + re.escape(tag) + r'[a-z0-9]*\b', text.lower()))
            if candidates and candidates != {tag}:
                return {'answer': ABSTAIN + ' The identifier is ambiguous; provide its complete value.', 'citations': [], 'status': 'NEEDS_REVIEW'}
        qualified.append(p)
    # A complete, contiguous clearance-hole callout must carry count, diameter
    # and hardware relationship together. Adjacent dimensions cannot substitute.
    if 'clearance' in q and 'hole' in q:
        hardware = re.findall(r'\b\d+-\d+\b', q)
        hardware = [h for h in hardware if h not in documents]
        count_match = re.search(r'\b(\d+)\s+(?:clearance\s+)?holes\b', q)
        count = count_match.group(1) if count_match else ('4' if 'four' in q else None)
        evidence = []
        for p in qualified:
            pattern = r'(?P<count>\d+)\s*[xX]\s*[Øø⌀]\s*(?P<diameter>\.?\d+(?:\.\d+)?)\s*(?:["″])?\s*(?:THRU\s*)?(?:\(?\s*CLEARANCE\s+(?:HOLES?\s+)?(?:FOR\s+)?|\(?\s*FOR\s+)(?P<hardware>\d+-\d+)\b[^\n]*'
            for match in re.finditer(pattern, p['text'], re.I):
                if count and match['count'] != count:
                    continue
                if not hardware or match['hardware'] not in hardware:
                    continue
                quote = match.group(0).strip()
                evidence.append((f"{match['count']}X Ø{match['diameter']}", quote, p))
        if evidence and len({x[0] for x in evidence}) == 1:
            value, quote, p = evidence[0]
            citation = {k: p.get(k) for k in ('source', 'source_hash', 'pdf_page', 'printed_page', 'chunk_id')}
            citation['support'] = quote
            citation['bbox'] = next((i.get('bbox') for i in p.get('items') or [] if quote in i.get('text', '')), None)
            return {'answer': value, 'citations': [citation], 'status': 'SUPPORTED'}
    return {'answer': ABSTAIN, 'citations': [], 'status': 'NEEDS_REVIEW'}


def document_readiness(path):
    """Read-only UI projection; a legacy indexed ledger never supplies READY."""
    root = os.environ.get('ARGUS_REVIEW_STATE_DIR')
    if not root:
        return {'state': 'NEEDS_REVIEW', 'reason': 'Document readiness evidence is unavailable'}
    db_path = Path(root) / 'generations.sqlite3'
    try:
        with sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True) as db:
            rows = db.execute('SELECT active,record FROM documents').fetchall()
        real = str(Path(path).resolve())
        collection = os.environ.get('ARGUS_REVIEW_COLLECTION', 'jarvis_kb')
        for active, raw in rows:
            record = json.loads(raw)
            if record.get('path') != real or record.get('collection') != collection:
                continue
            state = record.get('state', 'NEEDS_REVIEW')
            current_hash = digest(path)
            validated_hash = record.get('manifest', {}).get('source_hash')
            if state == 'READY' and (not active or validated_hash != current_hash):
                return {'state':'NEEDS_REVIEW', 'reason':'Source changed or active generation is unavailable',
                        'generation':active, 'history':record.get('history', []),
                        'source_hash':current_hash, 'validated_source_hash':validated_hash, 'published_at':record.get('published_at')}
            return {'state':state, 'reason':record.get('error') or ('All ingestion and retrieval checks passed' if state == 'READY' else 'Document has not reached review readiness'), 'generation':active, 'timings':record.get('timings', {}), 'history':record.get('history', []), 'source_hash':current_hash, 'validated_source_hash':validated_hash, 'published_at':record.get('published_at')}
    except (OSError, ValueError, sqlite3.Error):
        pass
    return {'state':'NEEDS_REVIEW', 'reason':'No validated ingestion generation for this document'}


def missing_documents(folder):
    """Read-only durable missing-source evidence for the selected folder."""
    root = os.environ.get('ARGUS_REVIEW_STATE_DIR')
    if not root:
        return []
    try:
        with sqlite3.connect((Path(root)/'generations.sqlite3').as_uri()+'?mode=ro', uri=True) as db:
            records = [json.loads(raw) for raw, in db.execute('SELECT record FROM documents')]
        target = Path(folder).resolve()
        return [r for r in records if r.get('collection') == os.environ.get('ARGUS_REVIEW_COLLECTION','jarvis_kb')
                and r.get('path') and Path(r['path']).is_relative_to(target) and not Path(r['path']).is_file()]
    except (OSError, ValueError, sqlite3.Error):
        return []
