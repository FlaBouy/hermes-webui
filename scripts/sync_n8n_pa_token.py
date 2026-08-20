#!/usr/bin/env python3
"""Synchronize n8n's internal PA bearer token from its protected source file."""

from __future__ import annotations

from pathlib import Path


ENV_PATH = Path("/Users/rick/jarvis-n8n/.env")
TOKEN_PATH = Path("/Users/rick/.jarvis-ptt/gpt-biggy-propose.token")


def main() -> None:
    token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("protected PA token file is empty")
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    replacement = f"GPT_BIGGY_PROPOSE_TOKEN={token}"
    found = False
    updated = []
    for line in lines:
        if line.startswith("GPT_BIGGY_PROPOSE_TOKEN="):
            updated.append(replacement)
            found = True
        else:
            updated.append(line)
    if not found:
        updated.append(replacement)
    ENV_PATH.write_text("\n".join(updated) + "\n", encoding="utf-8")
    print("n8n PA token synchronized from protected source")


if __name__ == "__main__":
    main()
