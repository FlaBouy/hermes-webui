#!/usr/bin/env python3
"""Independent Argus/Smedley black-box release gate (stdlib only)."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def request_json(url: str, *, body=None, headers=None, timeout=20.0):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Accept": "application/json", **(headers or {})},
        method="POST" if body is not None else "GET",
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        status = int(getattr(response, "status", 200) or 200)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return status, json.loads(raw.decode("utf-8")), elapsed_ms


def load_token() -> str:
    direct = str(os.environ.get("GPT_BIGGY_PROPOSE_TOKEN") or "").strip()
    if direct:
        return direct
    path = str(os.environ.get("GPT_BIGGY_PROPOSE_TOKEN_FILE") or "").strip()
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def run_case(name, call, validate):
    started = time.time()
    try:
        status, payload, duration_ms = call()
        error = validate(status, payload)
        ok = not error
    except Exception as exc:  # noqa: BLE001
        payload = None
        duration_ms = int((time.time() - started) * 1000)
        error = f"{type(exc).__name__}: {exc}"
        ok = False
    return {
        "case": name,
        "ok": ok,
        "duration_ms": duration_ms,
        "error": error or None,
        "correlation_id": payload.get("correlationId") or payload.get("correlation_id")
        if isinstance(payload, dict)
        else None,
    }


def call_biggy_adapter(objective: str, correlation_id: str):
    from api.argus_route import try_argus_pa_core

    started = time.monotonic()
    result = try_argus_pa_core(
        objective,
        correlation_id=correlation_id,
        session_id="argus-release-gate",
    )
    return 200, result, int((time.monotonic() - started) * 1000)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--live-pa", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    token = load_token()
    results = []
    for _ in range(max(1, args.repeat)):
        results.append(run_case(
            "argus_core_health",
            lambda: request_json("http://127.0.0.1:5014/health", timeout=3),
            lambda status, body: None if status == 200 and body.get("ok") is True else "core unhealthy",
        ))
        results.append(run_case(
            "smedley_ingest_status",
            lambda: request_json("http://127.0.0.1:5004/ingest-status", timeout=3),
            lambda status, body: None if status == 200 and isinstance(body, dict) else "ingest status unavailable",
        ))
    # Retrieval and PA calls are deliberately sampled once per run; --repeat
    # stresses the cheap liveness plane without multiplying model/Qdrant load.
    results.append(run_case(
        "smedley_direct_retrieval",
        lambda: request_json(
            "http://127.0.0.1:5004/rag/retrieve",
            body={
                "query": "1756-IB32 manual",
                "topk": 5,
                "correlation_id": "argus-eval-smedley-" + uuid4().hex[:10],
            },
            headers={"Content-Type": "application/json"},
            timeout=15,
        ),
        lambda status, body: None
        if status == 200 and isinstance(body.get("matches"), list) and body["matches"]
        else "Smedley returned no direct corpus matches",
    ))
    results.append(run_case(
        "argus_verified_manual",
        lambda: request_json(
            "http://127.0.0.1:5014/resolve",
            body={"query": "Find the verified 1756-IB32 manual."},
            headers={"Content-Type": "application/json"},
            timeout=30,
        ),
        lambda status, body: None
        if status == 200 and body.get("status") in {"VERIFIED_MANUAL", "VERIFIED_EVIDENCE", "NO_VERIFIED_EVIDENCE"}
        else "invalid evidence contract",
    ))
    if args.live_pa:
        corr = "argus-eval-" + uuid4().hex[:12]
        results.append(run_case(
            "argus_pa_map",
            lambda corr=corr: request_json(
                "http://127.0.0.1:5680/webhook/jarvis-ii-pa",
                body={
                    "objective": "Map a route from Lynn Haven, Florida to Grand Canyon National Park.",
                    "authority": "owner_local_biggy_chat",
                    "source": "argus-evaluator",
                    "requester": "argus-evaluator",
                    "correlation_id": corr,
                },
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
                timeout=30,
            ),
            lambda status, body: None
            if status == 200 and body.get("status") == "COMPLETED" and isinstance(body.get("map_view_model"), dict)
            else "map did not reach a completed card contract",
        ))
        os.environ.setdefault(
            "GPT_BIGGY_PROPOSE_TOKEN_FILE",
            "/Users/rick/.jarvis-ptt/gpt-biggy-propose-token",
        )
        adapter_corr = "argus-eval-biggy-" + uuid4().hex[:10]
        results.append(run_case(
            "biggy_argus_adapter_map",
            lambda: call_biggy_adapter(
                    "Ask Argus: map a route from Lynn Haven, Florida to Grand Canyon National Park.",
                    adapter_corr,
            ),
            lambda status, body: None
            if body.get("ok") is True
            and isinstance(body.get("map_view_model"), dict)
            and bool(body.get("spoken_text"))
            else "Biggy adapter did not return a spoken completed map contract",
        ))
    passed = sum(1 for result in results if result["ok"])
    summary = {
        "schema": "argus.blackbox.report.v1",
        "passed": passed,
        "failed": len(results) - passed,
        "total": len(results),
        "latency_ms": {
            "median": int(statistics.median([item["duration_ms"] for item in results])),
            "max": max(item["duration_ms"] for item in results),
        },
        "results": results,
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Argus black-box: {passed}/{len(results)} passed; max {summary['latency_ms']['max']} ms")
        for result in results:
            print(("PASS" if result["ok"] else "FAIL"), result["case"], result["duration_ms"], result["error"] or "")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
