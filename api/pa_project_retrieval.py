"""Read-only project generation selection for the existing RAG retrieve endpoint."""
import json
import os
from pathlib import PurePosixPath, Path
import sqlite3


def active_sources(collection):
    root = os.environ.get('ARGUS_REVIEW_STATE_DIR')
    if not root:
        raise RuntimeError('Review registry unavailable')
    with sqlite3.connect((Path(root) / 'generations.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        rows = db.execute('SELECT key,active FROM documents WHERE active IS NOT NULL').fetchall()
    return {json.loads(key)[1]: generation for key, generation in rows if json.loads(key)[0] == collection}


def project_matches(query, folder, *, embed_fn, qd_fn, collection, active=None):
    if not isinstance(folder, str) or not folder.startswith('Projects/') or '..' in PurePosixPath(folder).parts or '\\' in folder:
        raise ValueError('A scoped Projects folder is required')
    folder = folder.rstrip('/') + '/'
    active = active_sources(collection) if active is None else active
    scoped = {source: generation for source, generation in active.items() if source.startswith(folder)}
    if not scoped:
        return {'matches': [], 'scope': folder, 'coverage': 'No active indexed generations in this project.'}
    vectors = embed_fn([query])
    if len(vectors) != 1 or len(vectors[0]) != 768:
        raise ValueError('Valid query embedding required')
    response = qd_fn('/collections/' + collection + '/points/search', {
        'vector': vectors[0], 'limit': 16, 'with_payload': True,
        'filter': {'must': [{'key': 'generation', 'match': {'any': list(scoped.values())}},
                            {'key': 'quality_state', 'match': {'value': 'verified'}}]}})
    matches = []
    for hit in response.get('result', []):
        p = hit.get('payload') or {}
        if (p.get('source') not in scoped or p.get('generation') != scoped[p['source']]
                or p.get('quality_state') != 'verified' or not p.get('source_hash')
                or type(p.get('pdf_page')) is not int or p['pdf_page'] < 1 or not p.get('chunk_id')):
            continue
        text = str(p.get('text') or '').strip()
        if not text:
            continue
        matches.append({k: p.get(k) for k in ('source', 'source_hash', 'generation', 'pdf_page', 'chunk_id')}
                       | {'snippet': text[:4000]})
    return {'matches': matches, 'scope': folder,
            'coverage': 'Up to 16 relevant chunks from active indexed project generations. Current source files were not rehashed; missing/unindexed material and unretrieved passages are not covered.'}
