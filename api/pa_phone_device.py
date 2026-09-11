"""Bounded Android device adapter. No shell commands supplied by clients."""
import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


def adb_path():
    candidate = Path.home()/'Library/Android/sdk/platform-tools/adb'
    return shutil.which('adb') or (str(candidate) if candidate.is_file() else None)


def run(args):
    binary = adb_path()
    if not binary:
        raise ValueError('Android Platform Tools are not installed. Device pairing is required before phone control.')
    result = subprocess.run([binary, *args], capture_output=True, timeout=15, check=False, env={**os.environ, "ADB_LIBUSB": "1"})
    if result.returncode:
        raise ValueError('Phone command failed. Check that the phone is connected, unlocked and authorized.')
    return result.stdout.decode('utf-8', errors='replace')


def devices():
    if not adb_path():
        return {'devices': [], 'ready': False, 'detail': 'Install Android Platform Tools and authorize this Mac on the phone. Existing SMS and calling remain available.'}
    rows = []
    for line in run(['devices']).splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            rows.append({'id': parts[0], 'state': parts[1]})
    ready = any(r['state'] == 'device' for r in rows)
    if ready:
        detail = 'Choose a device. Reading the screen requires an unlocked phone; no screen is read automatically.'
    elif not rows:
        detail = 'No phone detected. Connect an Android phone with a USB data cable, enable USB debugging and unlock it, then refresh devices.'
    elif any(r['state'] == 'unauthorized' for r in rows):
        detail = 'Unlock the phone and approve this Mac in the USB debugging prompt, then refresh devices.'
    elif any(r['state'] == 'offline' for r in rows):
        detail = 'The phone is offline. Reconnect the USB data cable and unlock the phone, then refresh devices.'
    else:
        detail = 'No authorized phone is ready. Check the connection and USB debugging authorization, then refresh devices.'
    return {'devices': rows, 'ready': ready, 'detail': detail}


def operate(body):
    if not isinstance(body, dict):
        raise ValueError('Invalid phone request')
    ident = body.get('device')
    if not isinstance(ident, str) or ident not in [d['id'] for d in devices()['devices'] if d['state'] == 'device']:
        raise ValueError('Choose a connected, authorized device')
    action = body.get('action')
    if action in ('screen', 'tap', 'swipe', 'close_app') or (body.get('visual') is True and action in ('home', 'back', 'recents')):
        from api.pa_phone_screen import operate as screen_operate
        return screen_operate(ident, body)
    if action in ('home', 'back', 'recents'):
        run(['-s', ident, 'shell', 'input', 'keyevent', {'home':'3','back':'4','recents':'187'}[action]])
        return {'detail': 'Navigation command sent. Read the screen to verify the result.'}
    if action == 'apps':
        packages = run(['-s', ident, 'shell', 'pm', 'list', 'packages', '-3'])
        return {'apps': sorted(p[8:] for p in packages.splitlines() if p.startswith('package:') and re.fullmatch(r'[A-Za-z0-9_.]+', p[8:])), 'detail': 'Installed user apps. Choose one to open.'}
    if action == 'launch':
        package = body.get('package', '')
        if not isinstance(package, str) or not re.fullmatch(r'[A-Za-z0-9_.]{1,240}', package):
            raise ValueError('Choose an installed application')
        installed = run(['-s', ident, 'shell', 'pm', 'list', 'packages', '-3']).splitlines()
        if 'package:' + package not in installed:
            raise ValueError('Application is not installed')
        run(['-s', ident, 'shell', 'monkey', '-p', package, '-c', 'android.intent.category.LAUNCHER', '1'])
        return {'detail': 'App launch requested. Read the current screen to verify.'}
    if action == 'read':
        try:
            run(['-s', ident, 'shell', 'uiautomator', 'dump', '/sdcard/argus-window.xml'])
            content = run(['-s', ident, 'shell', 'cat', '/sdcard/argus-window.xml'])
        finally:
            # A failed dump/read can still leave a partial accessibility capture.
            run(['-s', ident, 'shell', 'rm', '/sdcard/argus-window.xml'])
        root = ET.fromstring(content)
        items = []
        for item in root.iter('node'):
            if item.get('password') == 'true':
                continue
            text = item.get('text') or item.get('content-desc')
            if text:
                items.append(text[:1000])
        return {'text': '\n'.join(dict.fromkeys(items))[:16000], 'detail': 'Current screen only. Text stays in this pane unless you choose to create a task.', 'source': 'Android accessibility tree'}
    raise ValueError('Unsupported phone action')


def handle(handler, parsed, post=False):
    from api.helpers import j
    try:
        if not post:
            return j(handler, devices())
        length = int(handler.headers.get('Content-Length', '0'))
        if not 0 < length <= 4096:
            raise ValueError('Invalid request size')
        return j(handler, operate(json.loads(handler.rfile.read(length))), extra_headers={'Cache-Control': 'no-store'})
    except (ValueError, TypeError, OSError, ET.ParseError, subprocess.TimeoutExpired):
        return j(handler, {'error': 'Device unavailable or action failed. Unlock the phone and refresh its screen or device connection before retrying.'}, status=400)
