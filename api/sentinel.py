"""Opt-in, same-origin bridge to the fixed local SENTINEL service."""

import os
import urllib.error
import urllib.request

LIMIT = 32 * 1024 * 1024


def handle_get(handler, parsed):
    if not parsed.path.startswith("/sentinel/"):
        return False
    if os.environ.get("ARGUS_SENTINEL_ENABLED") != "1":
        handler.send_error(404)
        return True

    # No client-supplied destination, credentials, cookies or redirect following.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    url = "http://127.0.0.1:8795" + parsed.path
    if parsed.query:
        url += "?" + parsed.query
    try:
        with urllib.request.build_opener(NoRedirect).open(url, timeout=18) as response:
            data = response.read(LIMIT + 1)
            if len(data) > LIMIT:
                raise ValueError("SENTINEL response exceeds bound")
            handler.send_response(200)
            for key in (
                "Content-Type",
                "Content-Security-Policy",
                "Referrer-Policy",
                "X-Content-Type-Options",
            ):
                if response.headers.get(key):
                    handler.send_header(key, response.headers[key])
            handler.send_header("Cache-Control", "no-store")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
    except urllib.error.HTTPError as error:
        handler.send_error(404 if error.code == 404 else 502, "SENTINEL unavailable")
        error.close()
    except (OSError, ValueError):
        handler.send_error(502, "SENTINEL unavailable")
    return True


def handle_post(handler, parsed):
    """Called only after the parent route's authentication and CSRF checks."""
    allowed = {"/sentinel/api/knowledge/ask", "/sentinel/api/knowledge/speak", "/sentinel/api/infrastructure/action"}
    if not parsed.path.startswith("/sentinel/"):
        return False
    if os.environ.get("ARGUS_SENTINEL_ENABLED") != "1" or parsed.path not in allowed:
        handler.send_error(404)
        return True
    try:
        length = int(handler.headers.get("Content-Length", "0"))
        if (
            not 0 < length <= 16384
            or parsed.query
            or handler.headers.get("Content-Type") != "application/json"
        ):
            raise ValueError("Invalid request")
        body = handler.rfile.read(length)
        if len(body) != length:
            raise ValueError("Incomplete request")
    except ValueError:
        handler.send_error(400)
        return True

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    request = urllib.request.Request(
        "http://127.0.0.1:8795" + parsed.path.removeprefix("/sentinel"),
        data=body,
        headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:8795"},
    )
    try:
        with urllib.request.build_opener(NoRedirect).open(
            request, timeout=35
        ) as response:
            kind = response.headers.get("Content-Type", "")
            if kind not in ("application/json", "audio/mpeg"):
                raise ValueError("Invalid response type")
            data = response.read(8_000_001)
            if len(data) > 8_000_000:
                raise ValueError("Response exceeds bound")
            handler.send_response(200)
            handler.send_header("Content-Type", kind)
            handler.send_header("Cache-Control", "no-store")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
    except urllib.error.HTTPError as error:
        handler.send_error(
            error.code if error.code in (400, 403, 404, 409, 413, 429, 503) else 502,
            "SENTINEL request unavailable",
        )
        error.close()
    except (OSError, ValueError):
        handler.send_error(502, "SENTINEL request unavailable")
    return True
