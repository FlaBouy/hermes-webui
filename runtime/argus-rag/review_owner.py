"""Local writer identity; an unknown/remote process is never declared dead."""
import os
import socket
import subprocess
import sys
from functools import lru_cache


@lru_cache(maxsize=1)
def boot_identity():
    try:
        if sys.platform.startswith('linux'):
            from pathlib import Path
            return Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        return subprocess.check_output(['sysctl','-n','kern.boottime'], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def process_start(pid):
    try:
        if sys.platform.startswith('linux'):
            # field 22, after the parenthesized process name (which may contain spaces).
            from pathlib import Path
            return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
        value = subprocess.check_output(['ps', '-p', str(int(pid)), '-o', 'lstart='], text=True, stderr=subprocess.DEVNULL).strip()
        return value or None
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None


def identity():
    return {'host': socket.gethostname(), 'pid': os.getpid(), 'start': process_start(os.getpid()), 'boot':boot_identity()}


def demonstrably_dead(owner):
    if owner.get('host') != socket.gethostname() or not owner.get('start'):
        return False
    if owner.get('boot') and boot_identity() and owner['boot'] != boot_identity():
        return True
    try:
        os.kill(int(owner['pid']), 0)
    except ProcessLookupError:
        return True
    except (OSError, ValueError, KeyError):
        return False
    actual = process_start(owner['pid'])
    return actual is not None and actual != owner['start']
