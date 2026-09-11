"""Bounded, memory-only Android video-frame preview; no persistent recorder."""
import os
import select
import shutil
import struct
import subprocess
import time

MAX_VIDEO_BYTES = 2 * 1024 * 1024
PNG_END = b'\x00\x00\x00\x00IEND\xaeB`\x82'


def decoder_path():
    return shutil.which('ffmpeg') or next((p for p in ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg') if os.path.isfile(p)), None)


def preview_size(width, height):
    scale = min(1, 1560 / max(width, height))
    return tuple(max(2, int(side * scale) // 2 * 2) for side in (width, height))


def read_video(process):
    """End after a quiet burst; strict decoding rejects incomplete frames."""
    data = bytearray()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if not select.select([process.stdout], [], [], .2)[0]:
            if len(data) > 1024:
                break
            continue
        chunk = os.read(process.stdout.fileno(), 65536)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_VIDEO_BYTES:
            raise ValueError('Preview exceeded its transfer bound.')
    if not data:
        raise ValueError('No preview frame received.')
    return bytes(data)


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
    if process.stdout:
        process.stdout.close()


def capture(device, width, height):
    from api.pa_phone_device import adb_path
    decoder = decoder_path()
    if not decoder:
        raise ValueError('Preview decoder unavailable.')
    target = preview_size(width, height)
    process = subprocess.Popen(
        [adb_path(), '-s', device, 'exec-out', 'screenrecord', '--output-format=h264',
         '--size', f'{target[0]}x{target[1]}', '--bit-rate', '2000000', '--time-limit', '1', '-'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env={**os.environ, 'ADB_LIBUSB': '1'},
    )
    try:
        video = read_video(process)
    finally:
        stop(process)
    result = subprocess.run(
        [decoder, '-hide_banner', '-loglevel', 'error', '-xerror', '-err_detect', 'explode',
         '-f', 'h264', '-i', 'pipe:0', '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', 'pipe:1'],
        input=video, capture_output=True, timeout=3, check=False,
    )
    data = result.stdout
    if (result.returncode or not 24 <= len(data) <= 8 * 1024 * 1024
            or data[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
            or not data.endswith(PNG_END) or struct.unpack('>II', data[16:24]) != target):
        raise ValueError('Preview could not be decoded completely.')
    return data
