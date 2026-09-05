"""Run a service with bounded stdout; stderr and environment remain inherited.

Five 32 MiB generations plus current stdout. Historical logs are not inputs.
"""
import argparse
import os
from pathlib import Path
import signal
import subprocess


def append_chunk(path, chunk, limit=32 * 1024 * 1024, backups=5):
    path = Path(path)
    if path.exists() and path.stat().st_size + len(chunk) > limit:
        oldest = Path(str(path) + f'.{backups}')
        oldest.unlink(missing_ok=True)
        for number in range(backups - 1, 0, -1):
            source = Path(str(path) + f'.{number}')
            if source.exists():
                source.replace(str(path) + f'.{number + 1}')
        path.replace(str(path) + '.1')
    with path.open('ab') as stream:
        stream.write(chunk)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--log', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command and command[0] == '--':
        command = command[1:]
    if not command:
        parser.error('child command required')
    path = Path(args.log)
    path.parent.mkdir(parents=True, exist_ok=True)
    child = subprocess.Popen(command, stdout=subprocess.PIPE, start_new_session=True)
    def forward(signum, _frame):
        if child.poll() is None:
            try:
                os.killpg(child.pid, signum)
            except ProcessLookupError:
                pass
    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    try:
        while chunk := os.read(child.stdout.fileno(), 65536):
            append_chunk(path, chunk)
        return child.wait()
    finally:
        child.stdout.close()
        if child.poll() is None:
            forward(signal.SIGTERM, None)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                forward(signal.SIGKILL, None)
                child.wait()


if __name__ == '__main__':
    raise SystemExit(main())
