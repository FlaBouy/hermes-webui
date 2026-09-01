"""Biggy tools-rail embed must call biggy-brand sidecar, not smedley-engineering.

Biggy's profile only installs biggy-brand. Shared calculator JS still talks to the
same loopback tools sidecar (:5004), but the WebUI extension proxy path must use
the host profile's consented extension id.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINEERING_JS = ROOT / "extensions" / "smedley-engineering" / "smedley-engineering.v0.2.5.js"
BRAND_JS = ROOT / "static" / "biggy-brand.js"
NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _proxy_block() -> str:
    src = ENGINEERING_JS.read_text(encoding="utf-8")
    start = src.index("const GUI_ID=")
    end = src.index("const PTT_INSTANCE=")
    return src[start:end]


def test_source_selects_host_profile_sidecar_for_tools_embed():
    block = _proxy_block()
    assert "TOOLS_ONLY_EMBED" in block
    assert "'/api/extensions/biggy-brand/sidecar'" in block
    assert "'/api/extensions/smedley-engineering/sidecar'" in block
    assert "smedley-engineering.v0.2.5.js" in BRAND_JS.read_text(encoding="utf-8")


@requires_node
def test_biggy_gui_uses_biggy_brand_sidecar_native_smedley_keeps_smedley_engineering():
    block = _proxy_block()
    harness = f"""
function resolve(guiId) {{
  const window = {{ __HERMES_GUI_ID__: guiId }};
  {block}
  return RAG_PROXY;
}}
const out = {{
  biggy: resolve('biggy'),
  smedley: resolve('smedley'),
  other: resolve('jarvis'),
}};
process.stdout.write(JSON.stringify(out));
"""
    proc = subprocess.run(
        [NODE, "-e", harness],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["biggy"] == "/api/extensions/biggy-brand/sidecar", payload
    assert payload["smedley"] == "/api/extensions/smedley-engineering/sidecar", payload
    assert payload["other"] == "/api/extensions/smedley-engineering/sidecar", payload


@requires_node
def test_engineering_extension_syntax():
    proc = subprocess.run(
        [NODE, "--check", str(ENGINEERING_JS)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
