import json
import importlib.util
import subprocess
import sys
from pathlib import Path
from api import biggy_fleet as fleet
from api import argus_world as world


def test_smedley_does_not_invent_idle(monkeypatch):
    monkeypatch.setattr(fleet, '_read_worker', lambda _: {})
    monkeypatch.setattr(fleet, '_tcp_online', lambda *_: False)
    assert fleet._machine_state({'id': 'SMEDLEY'}, 1000)[0] != 'online'


def test_smedley_fresh_worker_busy(monkeypatch):
    monkeypatch.setattr(fleet, '_read_worker', lambda _: {'state': 'busy', 'updated_at': 990})
    assert fleet._machine_state({'id': 'SMEDLEY'}, 1000)[0] == 'busy'


def test_galaxy_preserves_ingestion_phase(tmp_path):
    ledger = tmp_path / 'ledger.json'
    ledger.write_text(json.dumps({'files': {p: {'source': 'Projects/' + p + '.pdf', 'phase': p} for p in ['detected', 'queued', 'indexed', 'duplicate']}}))
    graph = world._build_rag_pool_graph(ledger)
    docs = [n for n in graph['nodes'] if n['g'] == 'document']
    assert {n.get('ingestion_phase') for n in docs} == {'detected', 'queued', 'indexed', 'duplicate'}
    assert graph['groups']['document']['name'] != 'Indexed document'


def test_log_generations_are_bounded(tmp_path):
    spec = importlib.util.spec_from_file_location('bounded', Path(__file__).parents[1] / 'scripts/bounded_process_log.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / 'test.log'
    for content in [b'aaaa', b'bbbb', b'cccc', b'dddd']:
        module.append_chunk(path, content, limit=4, backups=2)
    assert path.read_bytes() == b'dddd'
    assert Path(str(path) + '.1').read_bytes() == b'cccc'
    assert Path(str(path) + '.2').read_bytes() == b'bbbb'
    assert len(list(tmp_path.iterdir())) == 3


def test_log_wrapper_preserves_exit_and_output(tmp_path):
    path = tmp_path / 'child.log'
    run = subprocess.run([sys.executable, str(Path(__file__).parents[1] / 'scripts/bounded_process_log.py'),
                          '--log', str(path), '--', sys.executable, '-c',
                          'print("bounded stdout"); raise SystemExit(7)'], capture_output=True, timeout=10)
    assert run.returncode == 7
    assert path.read_text() == 'bounded stdout\n'
    assert run.stdout == b''


def test_staged_tools_rejects_oversized_body_before_read():
    import ast
    import os
    import pytest
    from http.server import BaseHTTPRequestHandler
    from urllib.parse import urlparse
    source = os.environ.get('ASTRA_TOOLS_SOURCE')
    if not source:
        pytest.skip('Set ASTRA_TOOLS_SOURCE to staged/deployed tools entrypoint')
    tree = ast.parse(Path(source).read_text())
    handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ToolsHandler')
    ns = {'BaseHTTPRequestHandler': BaseHTTPRequestHandler, 'urlparse': urlparse,
          'TOOL_HANDLERS': {'/tools/voltage-drop': None}, '_error': lambda msg: {'error': msg}}
    exec(compile(ast.Module(body=[handler], type_ignores=[]), source, 'exec'), ns)
    for length in ['65537', '-1']:
        instance = object.__new__(ns['ToolsHandler'])
        instance.path = '/tools/voltage-drop'
        instance.headers = {'Content-Length': length}
        instance.rfile = None  # Any attempted body read fails this test.
        sent = []
        instance._send = lambda code, body, sent=sent: sent.append((code, body))
        instance.do_POST()
        assert sent[0][0] == 413
        assert instance.close_connection is True
    assert ns['ToolsHandler'].timeout == 10
