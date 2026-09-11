"""Persistent extraction process; caches Docling pipelines within one lane."""
import json
import sys
from review_pdf import extract_pdf

for line in sys.stdin:
    try:
        req = json.loads(line)
        def state(value):
            print(json.dumps({'event': 'state', 'state': value}), flush=True)
        text, manifest = extract_pdf(req['path'], state)
        print(json.dumps({'event': 'result', 'text': text, 'manifest': manifest}), flush=True)
    except Exception as exc:
        print(json.dumps({'event': 'error', 'error': str(exc)}), flush=True)
