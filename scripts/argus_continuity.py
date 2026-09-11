#!/usr/bin/env python3
"""Explicit local continuity inspection/checkpoint/health operations.

No worker dispatch, service restart, model call or corpus scan. Use --state-root
for isolated trials; the default is the existing WebUI state directory.
"""
import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.argus_continuity import Store, package, probe_services, scope_for  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root', type=Path)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('capabilities')
    scope = sub.add_parser('scope')
    scope.add_argument('--profile', default='default')
    scope.add_argument('--project', required=True, help='Exact project ID, or workspace for unassociated sessions')
    show = sub.add_parser('show')
    show.add_argument('--scope', required=True)
    show.add_argument('--session')
    checkpoint = sub.add_parser('checkpoint')
    checkpoint.add_argument('--scope', required=True)
    checkpoint.add_argument('--file', type=Path, required=True)
    checkpoint.add_argument('--expected-revision', type=int, required=True)
    health = sub.add_parser('health')
    health.add_argument('--service', action='append', required=True)
    health.add_argument('--request-id', required=True)
    promote = sub.add_parser('promote')
    promote.add_argument('--scope', required=True)
    promote.add_argument('--name', required=True)
    promote.add_argument('--value', required=True)
    promote.add_argument('--evidence', required=True)
    promote.add_argument('--source', required=True, choices=['owner_correction', 'accepted_release', 'verified_implementation'])
    promote.add_argument('--baseline', required=True)
    promote.add_argument('--expected-revision', required=True, type=int)
    args = parser.parse_args()
    store = Store(args.state_root)
    if args.command == 'capabilities':
        result = package()
    elif args.command == 'scope':
        binding = scope_for(SimpleNamespace(profile=args.profile, project_id=args.project), role='argus')
        result = {'scope': binding[0], 'project': binding[1]} if binding else {'disabled': True}
    elif args.command == 'promote':
        result = {'revision': store.promote(args.scope, args.name, value=args.value, evidence=args.evidence,
                                          source=args.source, baseline=args.baseline, expected=args.expected_revision)}
    elif args.command == 'show':
        result = store.latest(args.scope, args.session)
    elif args.command == 'checkpoint':
        with args.file.open('rb') as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            raise ValueError('checkpoint too large')
        record = json.loads(raw)
        required = {'project', 'session_id', 'task_id', 'objective', 'status', 'decisions',
                    'files_touched', 'git', 'tests', 'deployment_state', 'blockers',
                    'next_action', 'workers', 'pending_owner_decisions', 'evidence', 'baseline'}
        if not required.issubset(record) or not record['evidence'] or not record['session_id']:
            raise ValueError('complete checkpoint and evidence required; see example schema')
        result = {'revision': store.checkpoint(args.scope, record['session_id'], record,
                                             expected=args.expected_revision)}
    else:
        result = probe_services(args.service, request_id=args.request_id, root=args.state_root)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
