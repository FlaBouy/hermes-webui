"""Capture allowlisted runtime identity, never service environment or credentials."""
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path('/Users/rick')
NAS = ROOT / 'Mounts/Z/DATA/n8n_share/Staging/RAG-build'
LABELS = ['ai.biggy.webui', 'com.flabo.smedley.hermes-webui',
          'com.flabo.smedley.jarvis-tools-api', 'com.flabo.smedley.rag-api',
          'com.flabo.smedley.rag-library-watch', 'com.flabo.smedley.rag-project-watch',
          'com.flabo.smedley.whisperd', 'com.flabo.smedley.jarvis-pedal',
          'ai.jarvis.rag-core.vnext', 'ai.biggy.google-messages']
FILES = [NAS / name for name in ['jarvis_tools_api.py', 'smedley_cable_tray.py',
          'nec_tables.py', 'jarvis_rag_watch.py', 'jarvis_rag_projects.py', 'jarvis_rag_poc.py']]
FILES += [ROOT / name for name in [
    'bin/smedley-rag-api.py', 'bin/wait-for-z-then-exec.sh', 'bin/jarvis-rag-watch-guard.sh',
    '.hermes/webui/extensions/smedley-engineering/smedley-engineering.v0.2.5.js',
    '.hermes/webui/extensions/smedley-engineering/voltage-drop-sizing.js',
    'voice-pipeline-poc/whisper-daemon.py', 'jarvis-pedal/run.sh']]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def main():
    result = {'captured_at': datetime.now(timezone.utc).isoformat(), 'host': 'Smedley',
              'ports': {'Biggy': 8790, 'Smedley': 8787, 'tools': 8801, 'RAG': 5004,
                        'LM_Studio': 1234, 'Whisper': 5001},
              'services': [], 'artifacts': [], 'environments': []}
    for label in LABELS:
        path = ROOT / 'Library/LaunchAgents' / (label + '.plist')
        if not path.is_file():
            result['services'].append({'label': label, 'missing': True})
            continue
        data = plistlib.loads(path.read_bytes())
        result['services'].append({'label': label, 'owner': 'rick/gui/502', 'plist': str(path),
                                   'sha256': digest(path), 'command': data.get('ProgramArguments'),
                                   'cwd': data.get('WorkingDirectory')})
    for path in FILES:
        result['artifacts'].append({'path': str(path), 'sha256': digest(path)})
    for relative in ['hermes-webui/.venv/bin/python', '.hermes/hermes-agent/venv/bin/python',
                     'jarvis-rag/docling-venv/bin/python', 'voice-pipeline-poc/.venv/bin/python']:
        exe = ROOT / relative
        code = 'import importlib.metadata as m,json,sys; print(json.dumps({"python":sys.version,"packages":sorted((d.metadata["Name"],d.version) for d in m.distributions())}))'
        run = subprocess.run([str(exe), '-c', code], capture_output=True, text=True, timeout=30)
        result['environments'].append({'executable': str(exe), 'inventory': json.loads(run.stdout) if run.returncode == 0 else {'unavailable': True}})
    result['component_sha'] = subprocess.check_output(['git', '-C', str(ROOT / 'hermes-webui'), 'rev-parse', 'HEAD'], text=True).strip()
    Path(sys.argv[1]).write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
