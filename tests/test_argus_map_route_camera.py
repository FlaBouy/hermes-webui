"""Route-card camera fit: full geometry + endpoints, delayed/resize lifecycle."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from tests.js_source_extract import extract_function

ROOT = Path(__file__).resolve().parents[1]
BIGGY_JS = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
BIGGY_CSS = (ROOT / "static" / "biggy-brand.css").read_text(encoding="utf-8")

LYNN_HAVEN = [-85.648, 30.245]
GRAND_CANYON = [-112.140, 36.057]
DALLAS_BULGE = [-96.797, 32.776]


def _camera_source() -> str:
    names = [
        "decodePolyline",
        "decodeRouteCoordinates",
        "routeCameraBounds",
        "routeCameraPadding",
        "shouldApplyRouteCameraFit",
        "simplifyRouteCoordinates",
        "mapViewportKey",
        "travelMapCameraFitPlan",
        "clampTravelMapZoomStep",
        "nextTravelMapZoomState",
        "travelMapZoomAvailability",
        "routeCameraLngLatToWorld",
        "routeCameraCenterZoom",
        "travelMapFitBounds",
        "staticMapUrl",
    ]
    chunks = [extract_function(BIGGY_JS, name) for name in names]
    return "\n".join(chunks)


def _run_camera(script_body: str):
    source = _camera_source()
    harness = f"""
const MAP_CAMERA_MIN_WIDTH = 80;
const MAP_CAMERA_MIN_HEIGHT = 80;
const MAP_ZOOM_STEP_MIN = -4;
const MAP_ZOOM_STEP_MAX = 6;
{source}
{script_body}
"""
    result = subprocess.run(
        ["node", "-e", harness],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def _long_cross_country_line(count: int = 400):
    points = []
    for i in range(count):
        t = i / (count - 1)
        lon = LYNN_HAVEN[0] + (GRAND_CANYON[0] - LYNN_HAVEN[0]) * t
        lat = LYNN_HAVEN[1] + (GRAND_CANYON[1] - LYNN_HAVEN[1]) * t
        if i == count // 2:
            points.append(DALLAS_BULGE)
        else:
            points.append([round(lon, 6), round(lat, 6)])
    return points


def _bounds_contains(bounds, lon, lat) -> bool:
    return (
        lon >= bounds["west"]
        and lon <= bounds["east"]
        and lat >= bounds["south"]
        and lat <= bounds["north"]
    )


def test_complete_route_bounds_include_decoded_geometry_and_both_endpoints():
    line = [
        [-85.65, 30.24],
        [-87.0, 30.7],
        [-90.1, 32.3],
        [-95.4, 31.8],
        [-106.4, 35.1],
        [-112.14, 36.05],
    ]
    origin = {"lon": -85.70, "lat": 30.20}
    destination = {"lon": -112.20, "lat": 36.10}
    out = _run_camera(
        f"""
const mvm = {{
  origin: {json.dumps(origin)},
  destination: {json.dumps(destination)},
  route: {{ geometry: {{ type: 'LineString', coordinates: {json.dumps(line)} }} }},
}};
const decoded = decodeRouteCoordinates(mvm.route.geometry);
const bounds = routeCameraBounds(decoded.concat([
  [{origin['lon']}, {origin['lat']}],
  [{destination['lon']}, {destination['lat']}],
]));
const url = staticMapUrl(mvm, 'test-token', {{ width: 640, height: 420, padding: routeCameraPadding(640, 420) }});
console.log(JSON.stringify({{ bounds, url, padding: routeCameraPadding(640, 420) }}));
"""
    )
    assert out["bounds"]["west"] <= origin["lon"]
    assert out["bounds"]["east"] >= destination["lon"] or out["bounds"]["west"] <= destination["lon"]
    assert _bounds_contains(out["bounds"], origin["lon"], origin["lat"])
    assert _bounds_contains(out["bounds"], destination["lon"], destination["lat"])
    assert _bounds_contains(out["bounds"], -106.4, 35.1)
    assert out["padding"] == round(max(24, min(72, min(640, 420) * 0.08)))
    overlay = json.loads(
        unquote(urlparse(out["url"]).path.split("/static/geojson(", 1)[1].rsplit(")/auto/", 1)[0])
    )
    points = [
        tuple(feature["geometry"]["coordinates"])
        for feature in overlay["features"]
        if feature["geometry"]["type"] == "Point"
    ]
    assert (origin["lon"], origin["lat"]) in points
    assert (destination["lon"], destination["lat"]) in points


def test_long_cross_country_route_keeps_endpoints_and_extrema_in_overlay():
    line = _long_cross_country_line(400)
    out = _run_camera(
        f"""
const mvm = {{
  origin: {{ lon: {LYNN_HAVEN[0]}, lat: {LYNN_HAVEN[1]}, label: 'Lynn Haven, FL' }},
  destination: {{ lon: {GRAND_CANYON[0]}, lat: {GRAND_CANYON[1]}, label: 'Grand Canyon' }},
  route: {{ geometry: {{ type: 'LineString', coordinates: {json.dumps(line)} }} }},
}};
const simplified = simplifyRouteCoordinates(decodeRouteCoordinates(mvm.route.geometry));
const bounds = routeCameraBounds(simplified);
const url = staticMapUrl(mvm, 'test-token', {{ width: 640, height: 480, padding: routeCameraPadding(640, 480) }});
console.log(JSON.stringify({{ bounds, url, simplified }}));
"""
    )
    assert _bounds_contains(out["bounds"], *LYNN_HAVEN)
    assert _bounds_contains(out["bounds"], *GRAND_CANYON)
    assert _bounds_contains(out["bounds"], *DALLAS_BULGE)
    parsed = urlparse(out["url"])
    assert parsed.path.endswith("/auto/640x480@2x")
    padding = parse_qs(parsed.query).get("padding", [""])[0]
    assert padding == str(round(max(24, min(72, min(640, 480) * 0.08))))
    overlay = json.loads(unquote(parsed.path.split("/static/geojson(", 1)[1].rsplit(")/auto/", 1)[0]))
    points = [
        tuple(feature["geometry"]["coordinates"])
        for feature in overlay["features"]
        if feature["geometry"]["type"] == "Point"
    ]
    assert (LYNN_HAVEN[0], LYNN_HAVEN[1]) in points
    assert (GRAND_CANYON[0], GRAND_CANYON[1]) in points
    line_coords = next(
        feature["geometry"]["coordinates"]
        for feature in overlay["features"]
        if feature["geometry"]["type"] == "LineString"
    )
    assert any(pt[0] == DALLAS_BULGE[0] and pt[1] == DALLAS_BULGE[1] for pt in line_coords)


def test_simplified_route_keeps_extrema_in_original_index_order_without_return_leg():
    count = 200
    stride = (count + 79) // 80
    assert stride == 3
    west_i, east_i, north_i, south_i = 50, 52, 100, 101
    for index in (west_i, east_i, north_i, south_i):
        assert index % stride != 0
        assert 0 < index < count - 1
    line = []
    for i in range(count):
        t = i / (count - 1)
        line.append([round(t * 100.0, 6), 0.0])
    line[west_i] = [-15.0, 0.0]
    line[east_i] = [115.0, 0.0]
    line[north_i] = [line[north_i][0], 40.0]
    line[south_i] = [line[south_i][0], -25.0]
    out = _run_camera(
        f"""
const original = {json.dumps(line)};
const simplified = simplifyRouteCoordinates(original);
const indexes = simplified.map((point) => original.findIndex((candidate) => candidate[0] === point[0] && candidate[1] === point[1]));
const increasing = indexes.every((index, i) => index >= 0 && (i === 0 || index > indexes[i - 1]));
const lastOriginal = original[original.length - 1];
const lastSimplified = simplified[simplified.length - 1];
const appendedReturnLeg = lastSimplified[0] !== lastOriginal[0] || lastSimplified[1] !== lastOriginal[1]
  || indexes[indexes.length - 1] !== original.length - 1;
const extrema = {json.dumps([west_i, east_i, north_i, south_i])};
console.log(JSON.stringify({{
  indexes, increasing, first: indexes[0], last: indexes[indexes.length - 1],
  extremaKept: extrema.every((index) => indexes.includes(index)),
  appendedReturnLeg, length: simplified.length,
}}));
"""
    )
    assert out["increasing"] is True
    assert out["first"] == 0
    assert out["last"] == count - 1
    assert out["extremaKept"] is True
    assert out["appendedReturnLeg"] is False
    assert out["length"] > 80 / stride


def test_delayed_open_and_resize_wait_for_final_visible_size():
    out = _run_camera(
        """
const delayed = shouldApplyRouteCameraFit({ containerWidth: 0, containerHeight: 0 });
const stillHidden = shouldApplyRouteCameraFit({ containerWidth: 40, containerHeight: 120 });
const ready = shouldApplyRouteCameraFit({ containerWidth: 640, containerHeight: 420 });
const resize = shouldApplyRouteCameraFit({ containerWidth: 720, containerHeight: 480 });
const padSmall = routeCameraPadding(200, 160);
const padLarge = routeCameraPadding(900, 720);
console.log(JSON.stringify({ delayed, stillHidden, ready, resize, padSmall, padLarge }));
"""
    )
    assert out["delayed"] is False
    assert out["stillHidden"] is False
    assert out["ready"] is True
    assert out["resize"] is True
    assert out["padSmall"] == 24
    assert out["padLarge"] == 58
    assert "waitForVisibleMapCanvas" in BIGGY_JS
    assert "scheduleTravelMapCameraFit('open')" in BIGGY_JS
    assert "scheduleTravelMapCameraFit('resize')" in BIGGY_JS
    assert "pendingMapCameraViewport" in BIGGY_JS
    assert "mapCameraUserAdjusted" not in BIGGY_JS
    assert "collectRouteFitCoordinates" not in BIGGY_JS
    assert "boundsContainsLngLat" not in BIGGY_JS
    assert "object-fit:contain" in BIGGY_CSS
    assert "object-fit:cover" not in BIGGY_CSS.split(".biggy-travel-static-map")[1].split("}")[0]
    assert "new mapboxgl.Map" not in extract_function(
        BIGGY_JS, "renderMapViewModelOnce", prefix="async function"
    )
    assert "data-testid=\"biggy-map-zoom-out\"" in BIGGY_JS
    assert "data-testid', 'biggy-nav-waze'" in BIGGY_JS
    assert "data-testid', 'biggy-nav-gmaps'" in BIGGY_JS
    assert "biggy-travel-map-zoom" in BIGGY_CSS


def test_map_zoom_plus_minus_bounds_persist_and_reset():
    out = _run_camera(
        """
const min = clampTravelMapZoomStep(-99);
const max = clampTravelMapZoomStep(99);
const plus = [];
let step = 0;
for (let i = 0; i < 12; i += 1) {
  step = nextTravelMapZoomState({ step, delta: 1, routeKey: 'r1', previousRouteKey: 'r1' }).step;
  plus.push(step);
}
const minus = [];
step = 0;
for (let i = 0; i < 12; i += 1) {
  step = nextTravelMapZoomState({ step, delta: -1, routeKey: 'r1', previousRouteKey: 'r1' }).step;
  minus.push(step);
}
const persist = nextTravelMapZoomState({
  step: 2, delta: 0, routeKey: 'r1', previousRouteKey: 'r1',
});
const reset = nextTravelMapZoomState({
  step: 2, delta: 0, routeKey: 'r2', previousRouteKey: 'r1',
});
console.log(JSON.stringify({ min, max, plus, minus, persist, reset }));
"""
    )
    assert out["min"] == -4
    assert out["max"] == 6
    assert out["plus"][-1] == 6
    assert out["plus"] == [1, 2, 3, 4, 5, 6, 6, 6, 6, 6, 6, 6]
    assert out["minus"][-1] == -4
    assert out["minus"][0] == -1
    assert out["persist"] == {"step": 2, "reset": False}
    assert out["reset"] == {"step": 0, "reset": True}


def test_map_zoom_changes_static_url_camera_and_keeps_endpoints():
    line = [[-85.65, 30.24], [-96.8, 32.78], [-112.14, 36.05]]
    origin = {"lon": -85.65, "lat": 30.24, "label": "Lynn Haven"}
    destination = {"lon": -112.14, "lat": 36.05, "label": "Grand Canyon"}
    out = _run_camera(
        f"""
const mvm = {{
  origin: {json.dumps(origin)},
  destination: {json.dumps(destination)},
  route: {{ geometry: {{ type: 'LineString', coordinates: {json.dumps(line)} }} }},
}};
const viewport = {{ width: 640, height: 480, padding: routeCameraPadding(640, 480) }};
const fit = staticMapUrl(mvm, 'test-token', Object.assign({{}}, viewport, {{ zoomStep: 0 }}));
const zoomedIn = staticMapUrl(mvm, 'test-token', Object.assign({{}}, viewport, {{ zoomStep: 2 }}));
const zoomedOut = staticMapUrl(mvm, 'test-token', Object.assign({{}}, viewport, {{ zoomStep: -2 }}));
const parseCam = (url) => {{
  const path = url.split('?')[0];
  const after = path.split(')/')[1];
  const camera = after.split('/')[0];
  if (camera === 'auto') return {{ mode: 'auto' }};
  const parts = camera.split(',');
  return {{ mode: 'explicit', lon: Number(parts[0]), lat: Number(parts[1]), zoom: Number(parts[2]) }};
}};
const overlay = (url) => JSON.parse(decodeURIComponent(url.split('/static/geojson(')[1].split(')/')[0]));
console.log(JSON.stringify({{
  fit: parseCam(fit),
  zoomedIn: parseCam(zoomedIn),
  zoomedOut: parseCam(zoomedOut),
  fitHasAuto: fit.includes('/auto/640x480@2x'),
  overlayIn: overlay(zoomedIn),
}}));
"""
    )
    assert out["fit"]["mode"] == "auto"
    assert out["fitHasAuto"] is True
    assert out["zoomedIn"]["mode"] == "explicit"
    assert out["zoomedOut"]["mode"] == "explicit"
    assert out["zoomedIn"]["zoom"] > out["zoomedOut"]["zoom"]
    points = [
        tuple(feature["geometry"]["coordinates"])
        for feature in out["overlayIn"]["features"]
        if feature["geometry"]["type"] == "Point"
    ]
    line_coords = next(
        feature["geometry"]["coordinates"]
        for feature in out["overlayIn"]["features"]
        if feature["geometry"]["type"] == "LineString"
    )
    assert (origin["lon"], origin["lat"]) in points
    assert (destination["lon"], destination["lat"]) in points
    assert line_coords[0] == line[0]
    assert line_coords[-1] == line[-1]
    same_size = _run_camera(
        """
const same = travelMapCameraFitPlan({
  containerWidth: 640, containerHeight: 420,
  lastViewportKey: mapViewportKey(640, 420, routeCameraPadding(640, 420), 2),
  pendingViewport: '', hasImage: true, inFlight: false, zoomStep: 2,
});
const zoomChange = travelMapCameraFitPlan({
  containerWidth: 640, containerHeight: 420,
  lastViewportKey: mapViewportKey(640, 420, routeCameraPadding(640, 420), 0),
  pendingViewport: '', hasImage: true, inFlight: false, zoomStep: 2,
});
console.log(JSON.stringify({ same, zoomChange }));
"""
    )
    assert same_size["same"]["action"] == "skip"
    assert same_size["zoomChange"]["action"] == "render"


def test_inflight_resize_open_coalesces_one_final_rerender():
    out = _run_camera(
        """
const first = travelMapCameraFitPlan({
  containerWidth: 320, containerHeight: 200,
  lastViewportKey: '', pendingViewport: '', hasImage: false, inFlight: false,
});
const duringWait = travelMapCameraFitPlan({
  containerWidth: 320, containerHeight: 200,
  lastViewportKey: '', pendingViewport: '', hasImage: false, inFlight: true,
});
const resizeWhileInflight = travelMapCameraFitPlan({
  containerWidth: 640, containerHeight: 420,
  lastViewportKey: '', pendingViewport: duringWait.pendingViewport, hasImage: false, inFlight: true,
});
const openWhileInflight = travelMapCameraFitPlan({
  containerWidth: 720, containerHeight: 480,
  lastViewportKey: '', pendingViewport: resizeWhileInflight.pendingViewport, hasImage: false, inFlight: true,
});
const firstFitted = mapViewportKey(320, 200, routeCameraPadding(320, 200));
const finalViewport = mapViewportKey(720, 480, routeCameraPadding(720, 480));
const afterSettle = travelMapCameraFitPlan({
  containerWidth: 720, containerHeight: 480,
  lastViewportKey: firstFitted, pendingViewport: openWhileInflight.pendingViewport,
  hasImage: true, inFlight: false,
});
const afterFinal = travelMapCameraFitPlan({
  containerWidth: 720, containerHeight: 480,
  lastViewportKey: finalViewport, pendingViewport: '',
  hasImage: true, inFlight: false,
});
const discardedSameAttempt = openWhileInflight.pendingViewport === firstFitted;
const rerunOnce = afterSettle.action === 'render' && afterSettle.pendingViewport === '';
const noLoop = afterFinal.action === 'skip';
console.log(JSON.stringify({
  first, duringWait, resizeWhileInflight, openWhileInflight, afterSettle, afterFinal,
  firstFitted, finalViewport, discardedSameAttempt, rerunOnce, noLoop,
}));
"""
    )
    assert out["first"]["action"] == "render"
    assert out["resizeWhileInflight"]["action"] == "pend"
    assert out["openWhileInflight"]["action"] == "pend"
    assert out["openWhileInflight"]["pendingViewport"] == out["finalViewport"]
    assert out["openWhileInflight"]["pendingViewport"] != out["firstFitted"]
    assert out["discardedSameAttempt"] is False
    assert out["rerunOnce"] is True
    assert out["afterSettle"]["action"] == "render"
    assert out["noLoop"] is True
    finally_src = extract_function(BIGGY_JS, "renderMapViewModel")
    assert "pendingMapCameraViewport" in finally_src
    assert "applyTravelMapCameraFit()" in finally_src
    assert "lastAttemptedViewportKey" in finally_src


def test_inflight_session_hydration_queues_latest_route_model_for_one_retry():
    render_src = extract_function(BIGGY_JS, "renderMapViewModel")
    invalidation_src = extract_function(BIGGY_JS, "invalidateTravelVisuals")
    assert "pendingMapViewModel = mvm" in render_src
    assert "const queuedModel = pendingMapViewModel" in render_src
    assert "pendingMapViewModel = null" in render_src
    assert "return renderMapViewModel(queuedModel)" in render_src
    assert render_src.index("mapRenderPromise = null") < render_src.index(
        "return renderMapViewModel(queuedModel)"
    )
    assert "pendingMapViewModel = null" in invalidation_src


def test_new_argus_visual_generation_clears_every_stale_travel_surface_first():
    invalidation_src = extract_function(BIGGY_JS, "invalidateTravelVisuals")
    handoff_src = extract_function(
        BIGGY_JS, "handoffTravelVisualsFromMessages", prefix="async function"
    )
    for stale_surface in (
        "biggyTravelMapMeta",
        "biggyTravelMapCanvas",
        "biggyTravelMapActions",
        "biggyTravelMapNote",
        "biggyTravelLodgingCards",
        "biggyTravelLodgingNote",
    ):
        assert stale_surface in invalidation_src
    assert "Object.keys(recommendationModelsByCategory)" in invalidation_src
    assert "invalidateTravelVisuals();" in handoff_src
    assert handoff_src.index("invalidateTravelVisuals();") < handoff_src.index(
        "renderRecommendationViewModel(rvm)"
    )
    assert "isUsableTravelVisual" in handoff_src


def test_unavailable_empty_recommendation_is_not_a_visual_card():
    source = extract_function(BIGGY_JS, "isUsableTravelVisual")
    script = f"""
{source}
const unavailable = isUsableTravelVisual({{available:false, options:[]}}, 'recommendation');
const map = isUsableTravelVisual({{available:true, route:{{}}}}, 'map');
const cards = isUsableTravelVisual({{available:true, options:[{{name:'Hotel'}}]}}, 'recommendation');
console.log(JSON.stringify({{ unavailable, map, cards }}));
"""
    result = subprocess.run(
        ["node", "-e", script], check=True, capture_output=True, text=True, timeout=30
    )
    assert json.loads(result.stdout) == {"unavailable": False, "map": True, "cards": True}


def test_map_zoom_control_order_and_availability_lifecycle():
    zoom_html = BIGGY_JS.split('id="biggyTravelMapZoom"', 1)[1].split("</div>", 1)[0]
    assert zoom_html.index("biggy-map-zoom-in") < zoom_html.index("biggy-map-zoom-out")
    assert zoom_html.index("Zoom in") < zoom_html.index("Zoom out")
    assert ".biggy-travel-map-zoom-btn:hover" in BIGGY_CSS
    assert ".biggy-travel-map-zoom-btn:focus-visible" in BIGGY_CSS
    assert "outline:1px solid rgba(103,232,249,.72)" in BIGGY_CSS
    render_once = extract_function(BIGGY_JS, "renderMapViewModelOnce", prefix="async function")
    assert "applyTravelMapZoomControls({ loading: !keepExisting, hasImage: keepExisting })" in render_once
    assert "applyTravelMapZoomControls({ loading: true, hasImage: false })" in render_once
    assert "applyTravelMapZoomControls({ failed: true, hasImage: false })" in render_once
    assert "applyTravelMapZoomControls({ hasImage: true })" in render_once
    assert "staticMapImage = image;" in render_once
    assert render_once.index("image.addEventListener('load'") < render_once.index("staticMapImage = image;")
    release = extract_function(BIGGY_JS, "releaseTravelMap")
    assert "applyTravelMapZoomControls({ failed: false, loading: false })" in release
    category = extract_function(BIGGY_JS, "ensureTravelMapDialog")
    assert "applyTravelMapZoomControls({ travelCategoryVisible: showTravel })" in category
    assert "mapZoom.hidden = !showTravel" not in category
    out = _run_camera(
        """
const hidden = { visible: false, inEnabled: false, outEnabled: false };
const beforeImage = travelMapZoomAvailability({ travelCategoryVisible: true, hasImage: false });
const loading = travelMapZoomAvailability({ travelCategoryVisible: true, hasImage: false, loading: true });
const failed = travelMapZoomAvailability({ travelCategoryVisible: true, hasImage: true, failed: true });
const otherCategory = travelMapZoomAvailability({ travelCategoryVisible: false, hasImage: true });
const ready = travelMapZoomAvailability({ travelCategoryVisible: true, hasImage: true, zoomStep: 0 });
const atMax = travelMapZoomAvailability({ travelCategoryVisible: true, hasImage: true, zoomStep: 6 });
const atMin = travelMapZoomAvailability({ travelCategoryVisible: true, hasImage: true, zoomStep: -4 });
const loadingKeepsOldImageHidden = travelMapZoomAvailability({
  travelCategoryVisible: true, hasImage: true, loading: true,
});
console.log(JSON.stringify({
  beforeImage, loading, failed, otherCategory, ready, atMax, atMin, loadingKeepsOldImageHidden,
  hiddenMatch: JSON.stringify(beforeImage) === JSON.stringify(hidden),
}));
"""
    )
    hidden = {"visible": False, "inEnabled": False, "outEnabled": False}
    assert out["beforeImage"] == hidden
    assert out["loading"] == hidden
    assert out["failed"] == hidden
    assert out["otherCategory"] == hidden
    assert out["loadingKeepsOldImageHidden"] == hidden
    assert out["ready"] == {"visible": True, "inEnabled": True, "outEnabled": True}
    assert out["atMax"] == {"visible": True, "inEnabled": False, "outEnabled": True}
    assert out["atMin"] == {"visible": True, "inEnabled": True, "outEnabled": False}
