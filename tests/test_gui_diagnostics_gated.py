"""GUI diagnostics overlay is production-hidden; debug-gated only."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BIGGY_JS = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
SMEDLEY_JS = Path.home() / ".hermes/webui/extensions/smedley-engineering/smedley-engineering.v0.2.5.js"


def test_biggy_diagnostics_default_off_and_gated():
    assert "diagnosticsEnabledDefault: false" in BIGGY_JS
    assert "function diagnosticsEnabled()" in BIGGY_JS
    assert "hermes_gui_debug" in BIGGY_JS
    assert "hermes-gui-debug:${GUI_ID}" in BIGGY_JS or "hermes-gui-debug:" in BIGGY_JS
    # Production path removes overlay DOM when disabled.
    assert "if (!diagnosticsEnabled())" in BIGGY_JS
    assert "stale.remove()" in BIGGY_JS
    # Instrumentation retained without requiring visible overlay.
    assert "dataset.guiDiagnostics" in BIGGY_JS
    assert "stampGuiIdentity" in BIGGY_JS
    # Must not always append a visible fixed overlay on boot.
    assert "Production default: no overlay DOM at all" in BIGGY_JS or "no overlay DOM" in BIGGY_JS


def test_biggy_diagnostics_zindex_below_panels():
    # Overlay must not sit above composer/tool chrome (z-index 9999 was the bug class).
    assert "z-index:20" in BIGGY_JS
    assert "z-index:9999" not in BIGGY_JS


def test_smedley_diagnostics_default_off_and_gated():
    assert SMEDLEY_JS.exists()
    text = SMEDLEY_JS.read_text(encoding="utf-8")
    assert "diagnosticsEnabledDefault:false" in text or "diagnosticsEnabledDefault: false" in text
    assert "function diagnosticsEnabled()" in text
    assert "hermes_gui_debug" in text
    assert "if(!diagnosticsEnabled())" in text
    assert "smedleyGuiDiagnostics" in text  # id retained for debug/create path
    assert "dataset.guiDiagnostics" in text
    assert "z-index:20" in text
    assert "z-index:9999" not in text
    # Old always-on production paint must be gone.
    assert "pointer-events:none';document.body.appendChild(node);}const sid=" not in text
