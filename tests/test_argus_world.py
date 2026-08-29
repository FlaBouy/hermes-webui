"""A.R.G.U.S. 3D world embed: narrow allowlist, chrome suppression, fallback."""

from __future__ import annotations

import json
from pathlib import Path

import api.argus_world as world


ROOT = Path(__file__).resolve().parents[1]
BIGGY_JS = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
BIGGY_CSS = (ROOT / "static" / "biggy-brand.css").read_text(encoding="utf-8")
ROUTES = (ROOT / "api" / "routes.py").read_text(encoding="utf-8")


def test_allowlist_is_narrow():
    assert set(world.ALLOWED_ASSETS) == {"3d.html", "graph-data.js"}


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
        "<body><div id=\"j-orb\"></div><div id=\"jarvis\"></div>"
        '<aside><img src="logo.png" alt="logo"></aside>'
        "<script>fetch('/api/brand').then(r=>r.ok?r.json():Promise.reject())"
        ".then(boot).catch(()=>{});</script>"
        "<script>Graph.onEngineStop(fitOnce);\nsetTimeout(fitOnce, 9000);</script>"
        '<script type="importmap">{"imports":{'
        '"three": "https://esm.sh/three",'
        '"three/webgpu": "https://esm.sh/three/webgpu",'
        '"three/tsl": "https://esm.sh/three/tsl",'
        '"three/addons/": "https://esm.sh/three/addons/",'
        '"three/examples/jsm/": "https://esm.sh/three/examples/jsm/",'
        '"3d-force-graph": "https://esm.sh/3d-force-graph?external=three",'
        '"three-spritetext": "https://esm.sh/three-spritetext?external=three"'
        '}}</script>'
        '<script type="module" src="fx.js?v=1"></script>'
        '<script type="module" src="missions.js?v=1"></script>'
        '<script type="module" src="lang.js?v=1"></script>'
        '<script type="module" src="tools.js?v=1"></script>'
        '<script type="module" src="hands.js?v=1"></script>'
        '<script type="module" src="calls.js?v=1"></script>'
        "</body></html>",
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
    # Biggy must own the viewer chrome before the iframe can paint; hiding
    # standalone controls only from an iframe load callback creates a visible
    # multi-stage boot flash.
    assert "#side,#collapse,#legend,#hud,#brand,#hint,#toast" in text
    assert "setTimeout(fitOnce, 9000);" not in text
    assert "fetch('/api/brand')" not in text
    assert 'src="logo.png"' not in text
    assert '<img alt="logo">' in text
    for module in ("fx.js", "missions.js", "lang.js", "tools.js", "hands.js", "calls.js"):
        assert f'src="{module}?v=1"' not in text
    # Keep the upstream module graph intact. Pinning only a subset of this
    # dependency family can make esm.sh resolve incompatible Three builds.
    assert '"three": "https://esm.sh/three"' in text
    assert '"3d-force-graph": "https://esm.sh/3d-force-graph?external=three"' in text
    assert '"three-spritetext": "https://esm.sh/three-spritetext?external=three"' in text
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
    assert "prompt:argus" in ids
    prompt = next(node for node in graph["nodes"] if node["id"] == "prompt:argus")
    assert prompt["label"] == "BIGGY PROMPT"
    assert (prompt["fx"], prompt["fy"], prompt["fz"]) == (0, 0, 0)
    assert graph["groups"]["prompt"]["c"] == "#f4a93a"
    by_id = {node["id"]: i for i, node in enumerate(graph["nodes"])}
    # The Prompt root connects directly to the top-level NAS folder; only
    # descendants continue through folder-to-folder links.
    assert {"s": by_id["prompt:argus"], "t": by_id["dir:Vendor Data"]} in graph["links"]
    assert "dir:Vendor Data/Allen Bradley/1756" in ids
    assert "doc:Vendor Data/Allen Bradley/1756/manual.pdf" in ids


def test_ingest_overview_reports_visible_counts_and_pins_issues_above_recent_success(tmp_path):
    ledger = tmp_path / "ingest_ledger.json"
    ledger.write_text(
        '{"files":{'
        '"good":{"source":"Alpha/complete.pdf","phase":"indexed","updated_at":"2026-08-22T10:00:00Z"},'
        '"bad":{"source":"Beta/problem.pdf","phase":"failed","reason":"extract timeout","updated_at":"2026-08-22T09:00:00Z"}'
        '}}',
        encoding="utf-8",
    )
    overview = world._ingest_overview(ledger)
    assert overview["node_count"] == 5  # Prompt + two folders + two files
    assert overview["link_count"] == 4
    assert overview["store_count"] == 1
    assert overview["recent"][0]["file"] == "problem.pdf"
    assert overview["recent"][0]["state"] == "issue"


def test_ingest_overview_exposes_five_radar_rows_when_history_allows(tmp_path):
    files = {
        f"row{i}": {
            "source": f"Vendor Data/manual-{i}.pdf",
            "phase": "indexed",
            "updated_at": f"2026-08-22T10:0{i}:00Z",
        }
        for i in range(6)
    }
    ledger = tmp_path / "ingest_ledger.json"
    ledger.write_text(json.dumps({"files": files}), encoding="utf-8")

    overview = world._ingest_overview(ledger)

    assert len(overview["recent"]) == 5
    assert [row["file"] for row in overview["recent"]] == [
        "manual-5.pdf", "manual-4.pdf", "manual-3.pdf", "manual-2.pdf", "manual-1.pdf"
    ]


def test_ingest_status_retains_ledger_truth_while_monitor_reconnects(tmp_path, monkeypatch):
    ledger = tmp_path / "ingest_ledger.json"
    ledger.write_text(
        '{"files":{"good":{"source":"Vendor Data/manual.pdf",'
        '"phase":"indexed","updated_at":"2026-08-22T10:00:00Z"}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(world, "resolve_rag_ingest_ledger", lambda: ledger)

    def unavailable(*_args, **_kwargs):
        raise OSError("watcher restarting")

    monkeypatch.setattr(world, "urlopen", unavailable)
    status = world.ingest_status()

    assert status["ok"] is True
    assert status["state"] == "monitor_offline"
    assert status["monitor_online"] is False
    assert status["node_count"] == 3
    assert status["link_count"] == 2
    assert status["store_count"] == 1
    assert status["recent"][0]["file"] == "manual.pdf"


def test_ingest_overlay_treats_monitor_reconnect_as_amber_not_failure():
    assert "INGEST MONITOR RECONNECTING" in BIGGY_JS
    assert "state === 'monitor_offline'" in BIGGY_JS


def test_embedded_world_keeps_native_animation_and_full_resolution():
    source = (ROOT / "api" / "argus_world.py").read_text(encoding="utf-8")
    assert "function installBudgetedRenderLoop" not in source
    assert "renderer.setPixelRatio" not in source
    assert "window.requestAnimationFrame =" not in source
    assert "g.resumeAnimation()" in source


def test_retry_is_confined_to_a_ledger_known_failed_file(tmp_path, monkeypatch):
    root = tmp_path / "Library"
    document = root / "Alpha" / "problem.pdf"
    document.parent.mkdir(parents=True)
    document.write_bytes(b"%PDF-test")
    ledger = tmp_path / "ingest_ledger.json"
    ledger.write_text(
        '{"files":{"bad":{"source":"Alpha/problem.pdf","phase":"failed"}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(world, "resolve_rag_ingest_ledger", lambda: ledger)
    monkeypatch.setattr(world, "resolve_rag_library_root", lambda: root)
    assert world._safe_rag_rel("../private.pdf") is None
    # The public retry function must reject traversal / unrecorded sources
    # before it can reach the ingest event module.
    try:
        world.retry_ingest_source("../private.pdf")
    except ValueError as exc:
        assert "unknown RAG ledger source" in str(exc)
    else:
        raise AssertionError("traversal source was accepted")


def test_detected_ledger_file_can_be_explicitly_requeued(tmp_path, monkeypatch):
    root = tmp_path / "Library"
    document = root / "Alpha" / "detected.pdf"
    document.parent.mkdir(parents=True)
    document.write_bytes(b"%PDF-test")
    ledger = tmp_path / "ingest_ledger.json"
    ledger.write_text(
        '{"files":{"row":{"source":"Alpha/detected.pdf","phase":"detected"}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(world, "resolve_rag_ingest_ledger", lambda: ledger)
    monkeypatch.setattr(world, "resolve_rag_library_root", lambda: root)
    import api.jarvis_rag_ingest_events as events

    seen = []
    monkeypatch.setattr(events, "requeue_ingest_source", lambda path: seen.append(path) or {"status": "queued", "queued": True})
    result = world.retry_ingest_source("Alpha/detected.pdf")
    assert result["ok"] is True
    assert result["state"] == "queued"
    assert seen == [str(document.resolve())]


def test_operator_can_resolve_known_ingest_issue(tmp_path, monkeypatch):
    root = tmp_path / "Library"
    document = root / "Alpha" / "problem.pdf"
    document.parent.mkdir(parents=True)
    document.write_bytes(b"%PDF-test")
    ledger = tmp_path / "ingest_ledger.json"
    ledger.write_text(
        '{"files":{"row":{"source":"Alpha/problem.pdf","phase":"failed"}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(world, "resolve_rag_ingest_ledger", lambda: ledger)
    monkeypatch.setattr(world, "resolve_rag_library_root", lambda: root)
    import api.jarvis_rag_ingest_events as events

    seen = []
    monkeypatch.setattr(events, "resolve_ingest_source", lambda path: seen.append(path) or {"status": "resolved"})
    result = world.disposition_ingest_source("Alpha/problem.pdf", "resolve")
    assert result["ok"] is True
    assert result["state"] == "resolved"
    assert seen == [str(document.resolve())]


def test_ingest_radar_exposes_clickable_disposition_for_detected_and_failed_rows():
    assert "V6_WORLD_DISPOSITION_PATH" in BIGGY_JS
    assert "data-argus-ingest-action" in BIGGY_JS
    assert "Single-click for ingestion actions" in BIGGY_JS
    assert "event.stopPropagation()" in BIGGY_JS
    assert "button[data-argus-ingest-action]" in BIGGY_CSS
    assert "RESOLVE" in BIGGY_JS
    assert "RE-INGEST" in BIGGY_JS
    assert "detected|failed|quarantined" in BIGGY_JS


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


def test_rag_navigation_opens_ledger_known_html_indexes(tmp_path, monkeypatch):
    root = tmp_path / "Library"
    rel = (
        "Vendor Data/Honeywell/Experian PKS/TDC3000/Honeywell TDC/"
        "_TDC_INDEX/TDC_Library.html"
    )
    document = root / rel
    document.parent.mkdir(parents=True)
    document.write_text("<!doctype html><title>TDC Library</title>", encoding="utf-8")
    ledger = tmp_path / "ingest_ledger.json"
    ledger.write_text(
        '{"files":{"tdc":{"source":"' + rel + '"}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(world, "resolve_rag_ingest_ledger", lambda: ledger)
    monkeypatch.setattr(world, "resolve_rag_library_root", lambda: root)

    resolved = world.resolve_rag_document(rel)

    assert resolved is not None
    assert resolved[1] == document.resolve()
    assert resolved[2] == "text/html"
    assert resolved[3] == "inline"


def test_rag_directory_tree_matches_the_bounded_world_projection(tmp_path, monkeypatch):
    ledger = tmp_path / "ingest_ledger.json"
    ledger.write_text(
        '{"files":{'
        '"a":{"source":"Vendor Data/Allen Bradley/1756/manual.pdf","updated_at":"2026-08-21T12:00:00Z"},'
        '"b":{"source":"Electrical Resources/NFPA/code.pdf","updated_at":"2026-08-21T13:00:00Z"}'
        '}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(world, "resolve_rag_ingest_ledger", lambda: ledger)
    tree = world.rag_directory_tree()
    assert tree["schema"] == "biggy.rag_tree.v1"
    assert tree["root"]["path"] == ""
    top = {child["path"]: child for child in tree["root"]["children"]}
    assert set(top) == {"Electrical Resources", "Vendor Data"}
    vendor = top["Vendor Data"]
    allen = vendor["children"][0]
    assert allen["path"] == "Vendor Data/Allen Bradley"
    assert allen["children"][0]["path"] == "Vendor Data/Allen Bradley/1756"
    assert allen["children"][0]["children"][0] == {
        "name": "manual.pdf",
        "path": "Vendor Data/Allen Bradley/1756/manual.pdf",
        "kind": "document",
    }


def test_filter_rail_tree_and_iframe_subtree_contracts_are_present():
    categories = BIGGY_JS.split("const TRAVEL_CATEGORIES = [", 1)[1].split("];", 1)[0]
    assert categories.index("'Filter'") < categories.index("'Travel'")
    assert "V6_WORLD_TREE_PATH" in BIGGY_JS
    assert 'id="biggyGalaxyFilterState"' in BIGGY_JS
    assert "refreshGalaxyFilterPanel(dlg)" in BIGGY_JS
    assert "biggy-galaxy-filter-focus" in BIGGY_JS
    assert "biggy-galaxy-filter-focused" in BIGGY_JS
    assert "if (c === 'filter') return 'filter';" in BIGGY_JS
    assert "biggy-galaxy-filter-toggle" in BIGGY_JS
    assert "childGroup.hidden = !nextExpanded" in BIGGY_JS
    assert "biggy-galaxy-filter-children[hidden]" in BIGGY_CSS
    runtime = world._TRACE_RUNTIME
    assert "function applyDirectoryFilter(path)" in runtime
    assert "g.nodeVisibility(node =>" in runtime
    assert "g.linkVisibility(link =>" in runtime
    assert "nodePath(node).startsWith(`${rel}/`)" in runtime
    assert "frameFilteredSubtree(selected, visible)" in runtime
    assert "directoryFilterPath" in runtime
    assert "if (directoryFilterPath && String(node && node.g) === 'folder')" in runtime
    assert "if (directoryFilterPath && String(node && node.g) === 'document')" in runtime


def test_home_restores_full_galaxy_after_directory_filter():
    runtime = world._TRACE_RUNTIME
    restore = runtime.split("function restore()", 1)[1].split("function apply(trace)", 1)[0]
    assert "restoreDirectoryFilter();" in restore
    assert "g.nodeVisibility(nativeNodeVisibility" in runtime
    assert "g.linkVisibility(nativeLinkVisibility" in runtime
    assert "resetLandingCamera();" in restore
    assert "controls.target.set(0, 0, 0)" in runtime


def test_world_csp_allows_same_origin_framing_and_esm_cdn():
    assert "frame-ancestors 'self'" in world.WORLD_CSP
    assert "https://esm.sh" in world.WORLD_CSP


def test_browser_source_never_calls_v6_port_directly():
    assert "4719" not in BIGGY_JS
    assert "/api/biggy/v6/world" in BIGGY_JS
    assert "syncGalaxyCanvasSize" in BIGGY_JS
    assert "new ResizeObserver" not in BIGGY_JS
    assert "biggy-world-chrome-reset" not in BIGGY_JS
    assert "iframe.dataset.biggyLayer = 'galaxy'" in BIGGY_JS
    assert "const keys = ['prompt:argus']" in world._TRACE_RUNTIME
    assert "controls.target.set(0, 0, 0)" in world._TRACE_RUNTIME
    assert "node.p) === 'key:prompt:argus'" in world._TRACE_RUNTIME
    assert "d3ReheatSimulation" not in world._TRACE_RUNTIME


def test_renderer_copy_preserves_prompt_fixed_coordinates():
    source = (
        "<html><head></head><body><script>"
        "const data = { nodes: GRAPH.nodes.map((n, i) => ({ id: i, "
        "val: 1 + Math.sqrt(deg[i]) * 1.6, heat: heatColor(deg[i]) })), };"
        "ForceGraph3D()(el).showNavInfo(false)\n  .graphData(data)\n  .backgroundColor(theme.bg);"
        "</script></body></html>"
    ).encode()
    patched = world._patch_index_html(source).decode()
    assert "fx: n.fx, fy: n.fy, fz: n.fz" in patched
    assert "anchor.val = Math.max(Number(anchor.val) || 0, 22)" in world._TRACE_RUNTIME
    assert "A.R.G.U.S." in BIGGY_JS
    assert "biggy-argus-rag-overview" in BIGGY_JS


def test_receipt_driven_trace_walks_to_folder_frames_family_and_pulses_file():
    runtime = world._TRACE_RUNTIME
    assert "for (let i = 0; i < route.length - 1; i++)" in runtime
    assert "frameDestination(resolved.folder)" in runtime
    assert "destinationFamily(folderId)" in runtime
    assert "ForceGraph3D.zoomToFit still walks the complete" in runtime
    assert "g.cameraPosition({" in runtime
    assert "startWinnerPulse(resolved.document, token)" in runtime
    assert "The dormant galaxy already owns ambient particles" in runtime
    assert "drawTraceOverlay(route, failed)" in runtime
    assert "new THREE.CylinderGeometry" in runtime
    assert "traceGroup.name = 'biggy-rag-trace'" in runtime
    assert "window.__os = { Graph, data, THREE," in world._patch_index_html(
        b"window.__os = { Graph, data,"
    ).decode()
    assert "Never call a ForceGraph link" in runtime
    assert "accessor setter here" in runtime
    assert "key === failed ? '#ef4444' : '#34d399'" in runtime
    assert "activePages.set(resolved.rel" in runtime
    assert "#page=${Math.floor(page)}" in runtime
    assert "restoreBaseGalaxyVisibility();\n    const resolved" in runtime
    assert "activePages.has(rel)" in runtime
    assert "openNode(node);\n          return;" in runtime


def test_browser_trace_forwards_verified_page_metadata_only():
    assert "receipt.pdf_page || receipt.page_hint" in BIGGY_JS
    assert "active && active.page_hint" in BIGGY_JS
    assert "printedPage" in BIGGY_JS
    assert "if (receipt && source)" in BIGGY_JS
    assert "window.__biggyHandleDocumentResult" in BIGGY_JS
    assert "message.rag_evidence" in BIGGY_JS
    assert "retrieval_receipt: citation" in BIGGY_JS
    assert "function isGalaxyTraceEligibleMessage(message)" in BIGGY_JS
    assert "message.map_view_model" in BIGGY_JS
    assert "message.trip_plan_view_model" in BIGGY_JS
    assert "clearRagTrace();\n\n      let recInfo" in BIGGY_JS
    assert "galaxyTraceCitation(message)" in BIGGY_JS
    assert "message.retrieval_receipt" in BIGGY_JS
    assert "message.active_document" in BIGGY_JS
    assert "must never resurrect travel cards" in BIGGY_JS
    assert "hideTravelMap();" in BIGGY_JS


def test_trace_waits_for_world_ready_and_does_not_replay_saved_receipt_on_boot():
    assert "if (!ragWorldReady)" in BIGGY_JS
    assert "pendingRagTrace = trace" in BIGGY_JS
    assert "data.type === 'biggy-rag-world-ready'" in BIGGY_JS
    assert "parent.postMessage({ type: 'biggy-rag-world-ready' }" in world._TRACE_RUNTIME
    assert "One boot-time restore for the latest completed turn" in BIGGY_JS
    assert "hideTravelMap();" in BIGGY_JS
    assert "function clearRagTrace()" in BIGGY_JS
    assert "frame.removeAttribute('data-rag-trace')" in BIGGY_JS
    assert "biggy-rag-trace-cleared" in BIGGY_JS
    assert "biggy-rag-trace-cleared" in world._TRACE_RUNTIME
    assert "clearRagTrace();" in BIGGY_JS
    assert "resetLandingCamera();" in world._TRACE_RUNTIME
    assert "controls.target.set(0, 0, 0)" in world._TRACE_RUNTIME
    assert "const LANDING_CAMERA_FALLBACK = Object.freeze({ x: 0, y: 0, z: 2400 })" in world._TRACE_RUNTIME
    assert "function fullCorpusCameraPosition()" in world._TRACE_RUNTIME
    assert "radius / Math.sin(limitingFov / 2) * 1.18 * HOME_SAFE_FIT_SCALE" in world._TRACE_RUNTIME
    assert "const HOME_SAFE_FIT_SCALE = 1.3" in world._TRACE_RUNTIME
    assert "function applyHomeViewOffset(g)" in world._TRACE_RUNTIME
    assert "parent.document.getElementById('biggyCockpitStrip')" in world._TRACE_RUNTIME
    assert "parent.document.getElementById('j-orb')" in world._TRACE_RUNTIME
    assert "desiredCenterX = promptRect.left + (promptRect.width / 2) - frameRect.left" in world._TRACE_RUNTIME
    assert "camera.setViewOffset(innerWidth, innerHeight, shiftLeft, shiftUp, innerWidth, innerHeight)" in world._TRACE_RUNTIME
    assert "biggy-home-centerline-sync" in world._TRACE_RUNTIME
    assert "controls.autoRotate = false" in world._TRACE_RUNTIME
    assert "liveControls.autoRotate = true" in world._TRACE_RUNTIME
    assert "activePages.clear();" in world._TRACE_RUNTIME
    assert "restoreBaseGalaxyVisibility();\n    resetLandingCamera();" in world._TRACE_RUNTIME
    assert "typeof os.clearFocus === 'function'" in world._TRACE_RUNTIME
    assert "idleContrastInstalled = false" in world._TRACE_RUNTIME
    assert "g.nodeOpacity(1)" in world._TRACE_RUNTIME
    assert "const FULL_SCOPE_NODE_SCALE = 6.4" in world._TRACE_RUNTIME
    assert "const SYNAPSE_WIDTH_SCALE = 2.2" in world._TRACE_RUNTIME
    assert "g.nodeRelSize(Math.max" in world._TRACE_RUNTIME
    assert "'#82ffe7'" in world._TRACE_RUNTIME
    assert "'#6acbed'" in world._TRACE_RUNTIME
    assert "const idleNodeColor = node =>" in world._TRACE_RUNTIME
    assert "new THREE.AmbientLight(0xffffff, 2.4)" in world._TRACE_RUNTIME
    assert "scene.fog.density = 0.000035" in world._TRACE_RUNTIME
    assert ".nodeColor(idleNodeColor)" in world._TRACE_RUNTIME
    assert "place(3.4, 0.24)" in world._TRACE_RUNTIME
    assert "place(1.25, 1)" in world._TRACE_RUNTIME
    assert "function startTraceFlow()" in world._TRACE_RUNTIME
    assert "new THREE.SphereGeometry(5.2, 10, 8)" in world._TRACE_RUNTIME
    assert "segment.object.position.lerpVectors" in world._TRACE_RUNTIME
    assert "/ 135" in world._TRACE_RUNTIME
    assert "state: 'unresolved'" in world._TRACE_RUNTIME
    assert "segments: 0" in world._TRACE_RUNTIME
    assert "Keep the evidence path available for inspection" in world._TRACE_RUNTIME


def test_saved_travel_cards_are_not_replayed_into_clean_boot():
    start = BIGGY_JS.index("async function scanMessagesForMapModel()")
    end = BIGGY_JS.index("\n  function applyShell()", start)
    boot_scan = BIGGY_JS[start:end]
    assert "await handoffTravelVisualsFromMessages(list)" in boot_scan
    assert "dlg.__biggySetCollapsed(true)" in boot_scan
    assert "setTimeout(scanMessagesForMapModel" not in BIGGY_JS
    assert "AUGMENTED RETRIEVAL &amp; GROUNDED UNDERSTANDING SYSTEM" in BIGGY_JS
    assert "data-argus-ingest-action" in BIGGY_JS


def test_biggy_root_boot_does_not_restore_native_or_private_saved_session():
    boot = (ROOT / "static" / "boot.js").read_text()
    assert "const _biggyCleanRoot=!urlSession&&String(S.activeProfile||'').toLowerCase()==='biggy'" in boot
    assert "if(_biggyCleanRoot)" in boot
    assert "localStorage.removeItem('hermes-webui-session')" in boot
    start = BIGGY_JS.index("async function tryStart()")
    end = BIGGY_JS.index("\n  function start()", start)
    startup = BIGGY_JS[start:end]
    assert "await ensureGuiSession()" not in startup
    assert "ensureGuiSession().then" not in startup


def test_operational_cards_use_large_responsive_workspace():
    assert "min(38vw, 720px)" in BIGGY_CSS
    assert "height:min(68vh, 720px)" in BIGGY_CSS
    assert "Math.max(480, Math.min(860" in BIGGY_JS


def test_right_rail_utility_labels_remain_canonical():
    assert "routeBtn.textContent = muted ? 'MUTE' : shownRoute.toUpperCase()" in BIGGY_JS
    assert "active === 'headset' ? 'mute' : 'headset'" in BIGGY_JS
    assert '>● PTT</button>' in BIGGY_JS
    assert 'id="biggyOpenSmedley"' not in BIGGY_JS


def test_argus_conversation_lane_is_removed_from_active_glass():
    shell = BIGGY_JS[BIGGY_JS.index("function applyShell()"):BIGGY_JS.index("async function tryStart()")]
    assert "installArgusConversationLane(mainChat)" not in shell
    assert ".biggy-argus-conversation-lane" not in BIGGY_CSS


def test_embedded_world_brightens_only_the_stock_star_field():
    source = (ROOT / "api" / "argus_world.py").read_text(encoding="utf-8")
    assert "positions.count === 1800" in source
    assert "child.material.isPointsMaterial" in source
    assert "starField.material.color.set('#7189b8')" in source
    assert "starField.material.opacity = 0.92" in source


def test_owner_prompt_renderer_never_exposes_private_voice_context():
    """The glass may show the utterance, never the appended PTT control prompt."""
    start = BIGGY_JS.index("function argusVisibleOwnerPrompt")
    end = BIGGY_JS.index("function argusConversationIdentity", start)
    boundary = BIGGY_JS[start:end]
    assert r"\[Voice PTT turn\b" in boundary
    assert r"\[Full spoken mode\b" in boundary
    assert r"Active Operator behavior\s*:" in boundary
    render = BIGGY_JS[BIGGY_JS.index("function renderArgusConversationLane"):BIGGY_JS.index("window.__biggyRenderArgusConversationLaneNow")]
    assert "message.role === 'user'" in render
    assert "argusVisibleOwnerPrompt(message)" in render


def test_map_handoff_is_single_flight_and_uses_static_map_not_second_webgl_scene():
    assert "let mapRenderPromise = null" in BIGGY_JS
    render_fn = BIGGY_JS[BIGGY_JS.index("function renderMapViewModel(mvm)"):BIGGY_JS.index("window.__biggyRenderMapViewModel")]
    assert "if (mapRenderPromise)" in render_fn
    assert "return mapRenderPromise" in render_fn
    assert "pendingMapCameraViewport" in render_fn
    assert "mapbox_static_timeout" in BIGGY_JS
    assert "styles/v1/mapbox/streets-v12/static/geojson" in BIGGY_JS
    assert "Math.ceil(valid.length / 80)" in BIGGY_JS
    assert "waitForVisibleMapCanvas(canvas)" in BIGGY_JS
    assert "routeCameraPadding(measured.width, measured.height)" in BIGGY_JS
    render_start = BIGGY_JS.index("async function renderMapViewModelOnce")
    render_end = BIGGY_JS.index("function renderMapViewModel(mvm)", render_start)
    assert "new mapboxgl.Map" not in BIGGY_JS[render_start:render_end]
    assert "setTimeout(_render" not in (ROOT / "static" / "messages.js").read_text(encoding="utf-8")


def test_ptt_completion_is_retryable_and_rehydrates_dialogs_and_cards():
    assert "async function refreshCompletedPttTurn(status, reason)" in BIGGY_JS
    assert "renderArgusConversationLane();" in BIGGY_JS
    assert "await window.__biggyHandoffTravelVisualsFromMessages(messages);" in BIGGY_JS
    assert "if (refreshed) lastCompletionTimestamp = completionTs" in BIGGY_JS
    assert "await syncActiveSession(completionSid)" in BIGGY_JS
    assert "completion hydration returned no messages" in BIGGY_JS
    assert "await loadSess(completionSid" not in BIGGY_JS
    assert "__biggyHandoffTravelVisualsFromMessages(messages)" in BIGGY_JS
    assert "async function refreshPttProgress(status)" in BIGGY_JS
    assert "phase !== 'processing' && phase !== 'speaking'" in BIGGY_JS
    assert "{ includeVisuals: false }" in BIGGY_JS
    assert "await refreshPttProgress(status)" in BIGGY_JS
    assert "message._ack_spoken_text" in BIGGY_JS


def test_completion_card_hydration_does_not_wait_for_mapbox_and_caches_all_trip_categories():
    handoff = BIGGY_JS.split("async function handoffTravelVisualsFromMessages", 1)[1].split(
        "window.__biggyHandoffTravelVisualsFromMessages", 1
    )[0]
    assert "cacheTripPlanViewModels(tpm)" in handoff
    assert "Promise.resolve(renderMapViewModel(mvm)).then" in handoff
    assert "await renderMapViewModel(mvm)" not in handoff
    assert "recommendation card hydration failed" in handoff
    assert "map card hydration failed" in handoff


def test_rag_completion_without_visual_model_invalidates_prior_travel_generation():
    handoff = BIGGY_JS.split("async function handoffTravelVisualsFromMessages", 1)[1].split(
        "window.__biggyHandoffTravelVisualsFromMessages", 1
    )[0]
    assert "if (!hasVisual)" in handoff
    assert "isGalaxyTraceEligibleMessage(m)" in handoff
    assert "invalidateTravelVisuals();" in handoff


def test_travel_categories_do_not_leak_stale_cards_and_map_survives_category_switches():
    category = BIGGY_JS.split("const setActiveCategory =", 1)[1].split(
        "dlg.__biggySetActiveCategory", 1
    )[0]
    collapsed = BIGGY_JS.split("const setCollapsed =", 1)[1].split(
        "dlg.__biggySetCollapsed", 1
    )[0]
    assert "key === recommendationKey" in category
    assert "lodging.hidden = !showRecommendation" in category
    assert "releaseTravelMap()" not in category
    assert "releaseTravelMap()" not in collapsed
    assert "section.setAttribute('data-rec-category', railKey)" in BIGGY_JS


def test_rag_palette_matches_argus_hud_after_conversation_stack_removal():
    assert ".biggy-argus-rag-subtitle{margin-top:5px;color:#b59cff" in BIGGY_CSS
    assert ".biggy-argus-conversation-lane" not in BIGGY_CSS
    assert "border-left-color:#62dbff" in BIGGY_CSS


def test_rag_status_requires_three_missed_polls_before_offline():
    assert "let ragWorldStatusFailures = 0" in BIGGY_JS
    assert "ragWorldStatusFailures >= 3 || !lastGoodRagWorldStatus" in BIGGY_JS
    assert "lastGoodRagWorldStatus = status" in BIGGY_JS


def test_recommendation_links_prefer_addresses_and_repair_lon_lat():
    assert "function safeRecommendationHref(opt)" in BIGGY_JS
    assert "encodeURIComponent(address)" in BIGGY_JS
    assert "Math.abs(first) > 90" in BIGGY_JS
    assert "const href = safeRecommendationHref(opt)" in BIGGY_JS


def test_argus_browser_voice_fallback_is_alistar():
    assert "rvugSNzdY0NcpG2PKe4B" in BIGGY_JS
    assert "dzRy05hNK3bab9ViJ0oU" not in BIGGY_JS


def test_routes_wire_world_endpoint():
    assert "/api/biggy/v6/world" in ROUTES
    assert "/api/biggy/v6/world/tree" in ROUTES
    assert "argus_world" in ROUTES
    # Must not reuse the shared DENY/frame-ancestors-none security headers,
    # which would prevent the same-origin iframe from ever loading.
    assert "X-Frame-Options" in ROUTES
    assert "/api/biggy/rag-browse" in ROUTES
    assert "/api/biggy/rag-file" in ROUTES
    assert "/api/biggy/v6/world/retry" in ROUTES


def test_iwo_background_image_removed_from_css():
    assert "iwo.jpg" not in BIGGY_CSS
    assert ".biggy-argus-rag-overview" in BIGGY_CSS
    assert "padding:10px 84px 52px" in BIGGY_CSS


def test_gitignore_covers_local_world_config():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "jarvis-v6-world.json" in gi
