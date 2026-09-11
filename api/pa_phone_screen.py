"""On-demand Android screenshots and bounded, frame-relative pointer input."""
import base64
import math
import os
import re
import secrets
import struct
import subprocess
import threading
import time
from collections import OrderedDict

FRAME_TTL = 30
MAX_IMAGE_BYTES = 16 * 1024 * 1024
_frames = OrderedDict()
_lock = threading.Lock()


def native_screenshot(device):
    from api.pa_phone_device import adb_path
    binary = adb_path()
    if not binary:
        raise ValueError('Android Platform Tools are unavailable.')
    result = subprocess.run(
        [binary, '-s', device, 'exec-out', 'screencap', '-p'],
        capture_output=True, timeout=15, check=False,
        env={**os.environ, 'ADB_LIBUSB': '1'},
    )
    data = result.stdout
    if result.returncode or not 24 <= len(data) <= MAX_IMAGE_BYTES or data[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR':
        raise ValueError('Phone screenshot unavailable. Unlock the phone and refresh.')
    width, height = struct.unpack('>II', data[16:24])
    if not (0 < width <= 8192 and 0 < height <= 8192):
        raise ValueError('Unsupported phone screen dimensions.')
    return data, width, height


def dimensions(device):
    """Read logical display size without capturing/transferring another image."""
    from api.pa_phone_device import run
    output = run(['-s', device, 'shell', 'dumpsys', 'window', 'displays'])
    for block in re.split(r'(?m)^\s*Display: ', output)[1:]:
        if not re.match(r'mDisplayId=0(?:\s|$)', block):
            continue
        match = re.search(r'\bcur=(\d+)x(\d+)\b', block)
        if match:
            size = tuple(map(int, match.groups()))
            if all(0 < side <= 8192 for side in size):
                return size
    # Unknown Android output formats retain the original screenshot check.
    _, width, height = native_screenshot(device)
    return width, height


def screenshot(device):
    from api.pa_phone_preview import capture
    try:
        width, height = dimensions(device)
        data = capture(device, width, height)
        if dimensions(device) != (width, height):
            raise ValueError('Display changed during preview capture.')
        # Pointer coordinates remain in native display pixels, not preview pixels.
        return data, width, height
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return native_screenshot(device)


def coordinate(value, size):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Pointer position must be inside the displayed screen.')
    return str(round(value * (size - 1)))


def close_foreground_app(device):
    from api.pa_phone_device import run
    state = run(['-s', device, 'shell', 'dumpsys', 'activity', 'activities'])
    packages = set(re.findall(r'topResumedActivity=ActivityRecord\{[^\n}]*\bu0 ([A-Za-z0-9_.]+)/', state))
    if len(packages) != 1:
        return 'No single foreground app to close.'
    package = packages.pop()
    installed = run(['-s', device, 'shell', 'pm', 'list', 'packages', '-3']).splitlines()
    if 'package:' + package not in installed:
        return 'No user app to close. Home and system screens stay available.'
    # Recheck after listing apps so a changed foreground is never stopped blindly.
    latest = run(['-s', device, 'shell', 'dumpsys', 'activity', 'activities'])
    if set(re.findall(r'topResumedActivity=ActivityRecord\{[^\n}]*\bu0 ([A-Za-z0-9_.]+)/', latest)) != {package}:
        return 'The foreground app changed. Refresh before closing it.'
    run(['-s', device, 'shell', 'am', 'force-stop', package])
    run(['-s', device, 'shell', 'input', 'keyevent', '3'])
    return 'App closed on the phone.'


def operate(device, body):
    from api.pa_phone_device import run
    if not _lock.acquire(blocking=False):
        raise ValueError('A phone screen action is already running. Refresh when it finishes.')
    try:
        action = body.get('action')
        notice = ''
        if action not in ('screen', 'tap', 'swipe', 'home', 'back', 'recents', 'close_app'):
            raise ValueError('Unsupported visual phone action.')
        if action == 'close_app':
            notice = close_foreground_app(device)
            time.sleep(.4)
        elif action in ('home', 'back', 'recents'):
            run(['-s', device, 'shell', 'input', 'keyevent', {'home': '3', 'back': '4', 'recents': '187'}[action]])
            # Capture after the closing animation, not during the shrinking app.
            time.sleep(.55)
        elif action != 'screen':
            token = body.get('frame')
            if not isinstance(token, str):
                raise ValueError('Refresh the phone screen before controlling it.')
            frame = _frames.pop(token, None)
            if not frame or frame['device'] != device or time.monotonic() - frame['created'] > FRAME_TTL:
                raise ValueError('Phone screenshot expired. Refresh before controlling it.')
            width, height = frame['width'], frame['height']
            args = ['-s', device, 'shell', 'input', action, coordinate(body.get('x'), width), coordinate(body.get('y'), height)]
            if action == 'swipe':
                args += [coordinate(body.get('end_x'), width), coordinate(body.get('end_y'), height), '220']
            # Reject a rotated/resized screen rather than applying old coordinates.
            current_width, current_height = dimensions(device)
            if (width, height) != (current_width, current_height):
                raise ValueError('Phone orientation changed. Refresh before controlling it.')
            run(args)
            time.sleep(.18 if action == 'swipe' else .4)
        data, width, height = screenshot(device)
        for old_token, old in list(_frames.items()):
            if old['device'] == device or time.monotonic() - old['created'] > FRAME_TTL:
                del _frames[old_token]
        token = secrets.token_urlsafe(24)
        _frames[token] = {'device': device, 'width': width, 'height': height, 'created': time.monotonic()}
        while len(_frames) > 16:
            _frames.popitem(last=False)
        return {
            'image': 'data:image/png;base64,' + base64.b64encode(data).decode('ascii'),
            'width': width, 'height': height, 'frame': token, 'expires_in': FRAME_TTL,
            'notice': notice,
            'detail': 'Screenshot refreshed. Tap or drag on the image to control your phone.',
        }
    finally:
        _lock.release()
