"""Profile-local office tasks. Independent of chat todos and fleet worker boards."""
import calendar
import json
import os
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class Conflict(ValueError):
    pass


def zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, TypeError, ValueError) as exc:
        raise ValueError('Choose a valid timezone') from exc


def clean(value):
    if not isinstance(value, dict):
        raise ValueError('Task must be an object')
    row = {}
    for key, limit in [('title', 240), ('notes', 5000), ('project', 120), ('waiting_on', 120), ('source', 1000)]:
        v = value.get(key, '')
        if not isinstance(v, str) or len(v) > limit:
            raise ValueError(f'Invalid {key}')
        row[key] = v.strip()
    review_id = value.get('review_project_id', '')
    if not isinstance(review_id, str) or (review_id and not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', review_id)):
        raise ValueError('Invalid review project reference')
    row['review_project_id'] = review_id
    if not row['title']:
        raise ValueError('A task needs a title')
    for key, options, default in [('status', ('open', 'waiting', 'done', 'archived'), 'open'), ('priority', ('high', 'normal', 'low'), 'normal'), ('recurrence', ('none', 'daily', 'weekdays', 'weekly', 'monthly'), 'none')]:
        row[key] = value.get(key, default)
        if row[key] not in options:
            raise ValueError(f'Invalid {key}')
    row['timezone'] = value.get('timezone', 'America/Chicago')
    zone(row['timezone'])
    row['due'] = value.get('due', '')
    if not isinstance(row['due'], str):
        raise ValueError('Invalid due date')
    if row['due']:
        if date.fromisoformat(row['due']).isoformat() != row['due']:
            raise ValueError('Invalid due date')
    if row['recurrence'] != 'none' and not row['due']:
        raise ValueError('Recurring tasks need a first due date')
    row['estimate'] = value.get('estimate', 30)
    if type(row['estimate']) is not int or not 5 <= row['estimate'] <= 480:
        raise ValueError('Estimated work must be 5–480 minutes')
    return row


def next_due(row, today):
    current = date.fromisoformat(row['due'])
    anchor = row.get('recurrence_day', current.day)
    while True:
        if row['recurrence'] == 'monthly':
            year, month = current.year + current.month // 12, current.month % 12 + 1
            current = date(year, month, min(anchor, calendar.monthrange(year, month)[1]))
        else:
            current += timedelta(days=7 if row['recurrence'] == 'weekly' else 1)
            if row['recurrence'] == 'weekdays':
                while current.weekday() >= 5:
                    current += timedelta(days=1)
        if current > today:
            return current.isoformat()


class Planner:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, payload TEXT NOT NULL, parent TEXT UNIQUE)')
        db.execute('CREATE TABLE IF NOT EXISTS history (seq INTEGER PRIMARY KEY, task_id TEXT, at TEXT, action TEXT)')
        return db

    def snapshot(self):
        with closing(self.connect()) as db:
            rows = [json.loads(r[0]) for r in db.execute('SELECT payload FROM tasks ORDER BY id')]
        return {'schema': 'office-planner-v1', 'tasks': rows, 'server_time': datetime.now(timezone.utc).isoformat()}

    def act(self, request, now=None):
        if not isinstance(request, dict):
            raise ValueError('Invalid request')
        now = now or datetime.now(timezone.utc)
        stamp = now.isoformat()
        action = request.get('action')
        if action not in ('create', 'update', 'complete', 'reopen', 'archive', 'snooze', 'unsnooze'):
            raise ValueError('Unknown planner action')
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            old = None
            if action != 'create':
                found = db.execute('SELECT payload FROM tasks WHERE id=?', (str(request.get('id', '')),)).fetchone()
                if not found:
                    raise ValueError('Task not found')
                old = json.loads(found[0])
                if request.get('version') != old['version']:
                    raise Conflict('This task changed on another screen. Refresh and try again.')
                if old['status'] == 'archived':
                    raise ValueError('Archived tasks cannot be changed')
            if action in ('create', 'update'):
                row = clean(request.get('task'))
                if row['status'] in ('done', 'archived'):
                    raise ValueError('Use the Complete or Archive action')
                if old and old['status'] == 'done':
                    raise ValueError('Reopen this task before editing')
                row.update(id=old['id'] if old else uuid.uuid4().hex, created=old['created'] if old else stamp,
                           snoozed_until=old.get('snoozed_until') if old else None)
                row['recurrence_day'] = (old.get('recurrence_day') if old and old['due'] == row['due'] else None) or (date.fromisoformat(row['due']).day if row['due'] else 1)
            else:
                row = dict(old)
                if action == 'complete':
                    if row['status'] == 'done':
                        raise Conflict('Task is already complete')
                    row.update(status='done', completed=stamp, snoozed_until=None)
                    if row['recurrence'] != 'none':
                        today = now.astimezone(zone(row['timezone'])).date()
                        child = {**row, 'id': uuid.uuid4().hex, 'due': next_due(row, today), 'status': 'open', 'created': stamp, 'updated': stamp, 'version': 1}
                        child.pop('completed', None)
                        db.execute('INSERT INTO tasks VALUES (?,?,?)', (child['id'], json.dumps(child), row['id']))
                elif action == 'reopen':
                    if row['recurrence'] != 'none' and row['status'] == 'done':
                        raise ValueError('The next recurring task already exists; edit that occurrence instead')
                    row.update(status='open', snoozed_until=None)
                    row.pop('completed', None)
                elif action == 'archive':
                    row['status'] = 'archived'
                elif action == 'snooze':
                    minutes = request.get('minutes')
                    if type(minutes) is not int or not 1 <= minutes <= 43200 or row['status'] == 'done':
                        raise ValueError('Invalid snooze duration')
                    row['snoozed_until'] = (now + timedelta(minutes=minutes)).isoformat()
                elif action == 'unsnooze':
                    row['snoozed_until'] = None
            row.update(updated=stamp, version=old['version']+1 if old else 1)
            if old:
                db.execute('UPDATE tasks SET payload=? WHERE id=?', (json.dumps(row), row['id']))
            else:
                db.execute('INSERT INTO tasks VALUES (?,?,NULL)', (row['id'], json.dumps(row)))
            db.execute('INSERT INTO history(task_id,at,action) VALUES (?,?,?)', (row['id'], stamp, action))
        return {'task': row}


def store():
    root = Path(os.environ.get('HERMES_WEBUI_STATE_DIR', str(Path.home()/'.hermes/webui-state')))
    return Planner(root/'office-planner/tasks.sqlite')


def handle_get(handler, parsed):
    if parsed.path != '/api/biggy/pa/planner':
        return False
    from api.helpers import j
    return j(handler, store().snapshot())


def handle_post(handler, parsed):
    # Parent router already checked authentication and CSRF.
    from api.helpers import j
    try:
        length = int(handler.headers.get('Content-Length', '0'))
        if not 0 < length <= 16384:
            raise ValueError('Invalid request size')
        body = json.loads(handler.rfile.read(length))
        result = store().act(body)
        return j(handler, result)
    except Conflict as exc:
        return j(handler, {'error': str(exc)}, status=409)
    except (ValueError, TypeError) as exc:
        return j(handler, {'error': str(exc)}, status=400)
