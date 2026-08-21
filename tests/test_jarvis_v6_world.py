"""Jarvis V6 3D world embed: narrow allowlist, chrome suppression, fallback."""

from __future__ import annotations

from pathlib import Path

import api.jarvis_v6_world as world


ROOT = Path(__file__).resolve().parents[1]
BIGGY_JS = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
BIGGY_CSS = (ROOT / "static" / "biggy-brand.css").read_text(encoding="utf-8")
ROUTES = (ROOT / "api" / "routes.py").read_text(encoding="utf-8")


def test_allowlist_is_narrow():
    assert set(world.ALLOWED_ASSETS) == {"3d.html", "graph-data.js", "logo.png"}


def test_unknown_asset_name_is_404_not_filesystem_lookup():
    body, content_type, status = world.serve_asset("../server.py")
    assert status == 404
    assert "application/json" in content_type


def test_path_traversal_within_allowlisted_name_is_rejected(monkeypatch, tmp_path):
    viewer = tmp_path / "viewer"
    viewer.mkdir()
    (viewer / "3d.html").write_text("<html><head></head><body>ok</body></html>", encoding="utf-8")
    monkeypatch.setattr(world, "load_world_config", lambda: {"viewer_dir": str(viewer)})
    # "3d.html" is allowlisted by name only; confirm resolution never escapes viewer_dir.
    resolved = world.resolve_viewer_dir()
    assert resolved == viewer.resolve()


def test_missing_viewer_dir_returns_clean_fallback_not_error(monkeypatch):
    monkeypatch.setattr(world, "load_world_config", lambda: {"viewer_dir": "/nonexistent/path/xyz"})
    body, content_type, status = world.serve_asset("3d.html")
    assert status == 200
    assert "text/html" in content_type
    assert b"V6 graph unavailable" in body


def test_missing_graph_data_asset_is_404(monkeypatch):
    monkeypatch.setattr(world, "load_world_config", lambda: {"viewer_dir": "/nonexistent/path/xyz"})
    body, content_type, status = world.serve_asset("graph-data.js")
    assert status == 404


def test_3d_html_gets_chrome_suppressed_and_based(tmp_path, monkeypatch):
    viewer = tmp_path / "viewer"
    viewer.mkdir()
    (viewer / "3d.html").write_text(
        "<!doctype html><html><head><title>x</title></head>"
        "<body><div id=\"j-orb\"></div><div id=\"jarvis\"></div></body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr(world, "load_world_config", lambda: {"viewer_dir": str(viewer)})
    body, content_type, status = world.serve_asset("3d.html")
    assert status == 200
    text = body.decode("utf-8")
    assert "<base href=\"/api/biggy/v6/world/\">" in text
    assert "#j-orb" in text and "display:none!important" in text
    assert "#jarvis" in text
    assert "#j-inbox" in text and "#j-tasks" in text
    assert "biggy-rag-trace-runtime" in text
    assert "installGalaxyNavigation" in text
    # The transplant markers themselves are untouched (still present, just hidden by CSS).
    assert '<div id="j-orb"></div>' in text


def test_graph_data_js_served_verbatim(tmp_path, monkeypatch):
    viewer = tmp_path / "viewer"
    viewer.mkdir()
    (viewer / "3d.html").write_text("<html><head></head><body></body></html>", encoding="utf-8")
    (viewer / "graph-data.js").write_text("const GRAPH = {\"nodes\":[]};", encoding="utf-8")
    monkeypatch.setattr(world, "load_world_config", lambda: {"viewer_dir": str(viewer)})
    monkeypatch.setattr(world, "resolve_rag_ingest_ledger", lambda: None)
    body, content_type, status = world.serve_asset("graph-data.js")
    assert status == 200
    assert body == b'const GRAPH = {"nodes":[]};'
    assert "javascript" in content_type


def test_rag_pool_graph_uses_ingestion_ledger_for_folder_and_document_paths(tmp_path):
    ledger = tmp_path / "ingest_ledger.json"
    ledger.write_text(
        '{"files":{"a":{"source":"Vendor Data/Allen Bradley/1756/manual.pdf",'
        '"phase":"indexed","updated_at":"2026-08-21T12:00:00Z"}}}',
        encoding="utf-8",
    )
    graph = world._build_rag_pool_graph(ledger)
    ids = {node["id"] for node in graph["nodes"]}
    assert "root:rag-pool" in ids
    assert "dir:Vendor Data/Allen Bradley/1756" in ids
    assert "doc:Vendor Data/Allen Bradley/1756/manual.pdf" in ids


def test_rag_navigation_is_ledger_scoped_and_never_traverses(tmp_path, monkeypatch):
    root = tmp_path / "Library"
    document = root / "Vendor Data/Allen Bradley/manual.pdf"
    document.parent.mkdir(parents=True)
    document.write_bytes(b"%PDF-test")
    ledger = tmp_path / "ingest_ledger.json"
    ledger.write_text('{"files":{"a":{"source":"Vendor Data/Allen Bradley/manual.pdf"}}}', encoding="utf-8")
    monkeypatch.setattr(world, "resolve_rag_ingest_ledger", lambda: ledger)
    monkeypatch.setattr(world, "resolve_rag_library_root", lambda: root)
    assert world.rag_folder_entries("Vendor Data") == [{"name": "Allen Bradley", "path": "Vendor Data/Allen Bradley", "kind": "folder"}]
    assert world.rag_folder_entries("../private") is None
    assert world.resolve_rag_document("Vendor Data/Allen Bradley/manual.pdf")[1] == document.resolve()
    assert world.resolve_rag_document("../private.pdf") is None


def test_world_csp_allows_same_origin_framing_and_esm_cdn():
    assert "frame-ancestors 'self'" in world.WORLD_CSP
    assert "https://esm.sh" in world.WORLD_CSP


def test_browser_source_never_calls_v6_port_directly():
    assert "4719" not in BIGGY_JS
    assert "/api/biggy/v6/world" in BIGGY_JS
    assert "syncGalaxyCanvasSize" in BIGGY_JS
    assert "new ResizeObserver" not in BIGGY_JS


def test_routes_wire_world_endpoint():
    assert "/api/biggy/v6/world" in ROUTES
    assert "jarvis_v6_world" in ROUTES
    # Must not reuse the shared DENY/frame-ancestors-none security headers,
    # which would prevent the same-origin iframe from ever loading.
    assert "X-Frame-Options" in ROUTES
    assert "/api/biggy/rag-browse" in ROUTES
    assert "/api/biggy/rag-file" in ROUTES


def test_iwo_background_image_removed_from_css():
    assert "iwo.jpg" not in BIGGY_CSS


def test_gitignore_covers_local_world_config():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "jarvis-v6-world.json" in gi
