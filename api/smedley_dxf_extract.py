#!/usr/bin/env python3
"""Native DXF extraction for Smedley Project Review.

Uses ezdxf locally. Expands block definitions with composed world transforms,
preserves insert occurrence chains, resolves layer-0 inheritance, never fetches
XREFs, never executes scripts, never claims DWG/RVT support.
"""

from __future__ import annotations

from api.smedley_source_snapshot import materialize_source_snapshot

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

SCHEMA = "smedley.dxf_extraction.v2"
# Bounded defaults sized for owner-supplied interconnect DXFs (~115MiB / hundreds of
# thousands of LINE entities) without unbounded retention. Geometry is sampled;
# TEXT/MTEXT/ATTRIB/INSERT keep separate budgets so late text is not starved.
DEFAULT_MAX_BYTES = int(os.environ.get("SMEDLEY_DXF_MAX_BYTES", str(256 * 1024 * 1024)))
DEFAULT_MAX_TEXT = int(os.environ.get("SMEDLEY_DXF_MAX_TEXT", "50000"))
DEFAULT_MAX_INSERTS = int(os.environ.get("SMEDLEY_DXF_MAX_INSERTS", "20000"))
DEFAULT_MAX_GEOMETRY_SAMPLES = int(os.environ.get("SMEDLEY_DXF_MAX_GEOMETRY_SAMPLES", "2000"))
DEFAULT_MAX_DEPTH = int(os.environ.get("SMEDLEY_DXF_MAX_DEPTH", "12"))
# Soft scan budget sized for ~115MiB interconnect-class drawings (~400k+ LINE) without
# unbounded walk. After this soft cap, geometry/unsupported are skipped but TEXT/MTEXT/
# ATTDEF/INSERT continue so late-in-file attributes are not starved by LINE floods.
DEFAULT_MAX_SCAN = int(os.environ.get("SMEDLEY_DXF_MAX_SCAN", "1500000"))
DEFAULT_MAX_WALK = int(os.environ.get("SMEDLEY_DXF_MAX_WALK", "5000000"))
UNSUPPORTED_DIRECT = {".dwg", ".rvt", ".rfa", ".ifc"}

UNIT_NAMES = {
    0: "unitless", 1: "inches", 2: "feet", 3: "miles", 4: "millimeters",
    5: "centimeters", 6: "meters", 7: "kilometers", 8: "microinches", 9: "mils",
    10: "yards", 11: "angstroms", 12: "nanometers", 13: "microns", 14: "decimeters",
    15: "decameters", 16: "hectometers", 17: "gigameters", 18: "astronomical_units",
    19: "light_years", 20: "parsecs",
}


def _iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_sha256(path: str, *, max_bytes: int | None = None) -> str:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if max_bytes is not None and size > max_bytes:
                raise ValueError("DXF exceeds bounded file size limit")
            digest.update(chunk)
    return digest.hexdigest()


def capabilities() -> dict[str, Any]:
    try:
        import ezdxf  # noqa: F401
        import importlib.metadata as metadata

        version = metadata.version("ezdxf")
        available = True
        detail = f"ezdxf {version}"
    except Exception as exc:  # pragma: no cover
        version = None
        available = False
        detail = f"ezdxf unavailable: {exc}"
    return {
        "schema": "smedley.dxf_capabilities.v2",
        "dxf_parser_available": available,
        "parser": "ezdxf",
        "parser_version": version,
        "detail": detail,
        "direct_support": [".dxf"],
        "requires_approved_export": sorted(UNSUPPORTED_DIRECT),
        "fetches_xrefs": False,
        "executes_embedded_code": False,
        "expands_block_definitions": True,
        "bounds": {
            "max_bytes": DEFAULT_MAX_BYTES,
            "max_text": DEFAULT_MAX_TEXT,
            "max_inserts": DEFAULT_MAX_INSERTS,
            "max_geometry_samples": DEFAULT_MAX_GEOMETRY_SAMPLES,
            "max_scan": DEFAULT_MAX_SCAN,
            "max_walk": DEFAULT_MAX_WALK,
            "max_depth": DEFAULT_MAX_DEPTH,
        },
    }


def _matrix_list(matrix: Any) -> list[float] | None:
    if matrix is None:
        return None
    try:
        values = list(matrix)
        if len(values) == 16:
            return [float(v) for v in values]
    except Exception:
        pass
    try:
        out: list[float] = []
        for row in range(4):
            for col in range(4):
                out.append(float(matrix[row, col]))
        return out
    except Exception:
        return None


def _entity_text(entity: Any) -> str:
    dxftype = entity.dxftype()
    if dxftype == "MTEXT":
        return str(getattr(entity, "text", None) or entity.dxf.get("text", "") or "")
    if dxftype in {"TEXT", "ATTRIB", "ATTDEF"}:
        return str(entity.dxf.get("text", "") or "")
    return ""


def _point3(value: Any) -> list[float] | None:
    if value is None:
        return None
    try:
        return [float(value[0]), float(value[1]), float(value[2]) if len(value) > 2 else 0.0]
    except Exception:
        return None


def _is_xref_block(doc: Any, block_name: str) -> bool:
    try:
        layout = doc.blocks.get(block_name)
    except Exception:
        return False
    if layout is None:
        return True  # missing block definition treated as unresolved external
    record = getattr(layout, "block_record", None)
    if record is None:
        return False
    try:
        flag = getattr(record, "is_xref", False)
        return bool(flag() if callable(flag) else flag)
    except Exception:
        return False


def _geometry_payload(entity: Any, *, layer: str, layout_name: str, handle: str | None, wcs_points: list[list[float]] | None = None) -> dict[str, Any]:
    dxftype = entity.dxftype()
    meta: dict[str, Any] = {
        "type": dxftype,
        "handle": handle,
        "layer": layer,
        "layout": layout_name,
    }
    try:
        if dxftype == "LINE":
            meta["start"] = wcs_points[0] if wcs_points else _point3(entity.dxf.start)
            meta["end"] = wcs_points[1] if wcs_points and len(wcs_points) > 1 else _point3(entity.dxf.end)
        elif dxftype == "CIRCLE":
            meta["center"] = wcs_points[0] if wcs_points else _point3(entity.dxf.center)
            meta["radius"] = float(entity.dxf.radius)
        elif dxftype == "ARC":
            meta["center"] = wcs_points[0] if wcs_points else _point3(entity.dxf.center)
            meta["radius"] = float(entity.dxf.radius)
            meta["start_angle"] = float(entity.dxf.start_angle)
            meta["end_angle"] = float(entity.dxf.end_angle)
        elif dxftype in {"LWPOLYLINE", "POLYLINE"}:
            meta["points"] = wcs_points or []
            meta["closed"] = bool(getattr(entity, "closed", False))
        elif dxftype == "POINT":
            meta["location"] = wcs_points[0] if wcs_points else _point3(entity.dxf.location)
        elif dxftype == "SPLINE":
            meta["control_points"] = wcs_points or []
        else:
            meta["note"] = "geometry type recorded with limited metadata"
    except Exception as exc:
        meta["geometry_error"] = str(exc)
    return meta


def extract_dxf(
    path: str,
    *,
    evidence_dir: str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_entities: int | None = None,
    max_text: int = DEFAULT_MAX_TEXT,
    max_inserts: int = DEFAULT_MAX_INSERTS,
    max_geometry_samples: int = DEFAULT_MAX_GEOMETRY_SAMPLES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_scan: int = DEFAULT_MAX_SCAN,
    max_walk: int = DEFAULT_MAX_WALK,
    update_ledger: bool = False,
    source_sha256: str | None = None,
    source_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if max_entities is not None:
        max_scan = int(max_entities)
    caps = capabilities()
    real = os.path.realpath(path)
    ext = os.path.splitext(real)[1].lower()
    warnings: list[str] = []
    if ext in UNSUPPORTED_DIRECT:
        return {
            "schema": SCHEMA, "ok": False, "state": "needs_approved_export",
            "reason": f"{ext.upper()} is not directly readable. Export/convert to DXF under an approved workflow.",
            "capabilities": caps, "warnings": warnings,
        }
    if ext != ".dxf":
        return {
            "schema": SCHEMA, "ok": False, "state": "unsupported",
            "reason": f"unsupported extension {ext or '(none)'}; native parser supports .dxf only",
            "capabilities": caps, "warnings": warnings,
        }
    if not caps["dxf_parser_available"]:
        return {
            "schema": SCHEMA, "ok": False, "state": "unavailable", "reason": caps["detail"],
            "capabilities": caps, "warnings": ["DXF parser not installed in this runtime"],
        }
    if not os.path.isfile(real):
        return {"schema": SCHEMA, "ok": False, "state": "failed", "reason": "DXF file not found", "capabilities": caps, "warnings": warnings}

    from ezdxf import recover
    from ezdxf.math import Matrix44, Vec3

    started = time.time()
    out_dir = evidence_dir
    if not out_dir:
        raise ValueError("evidence_dir required (server-owned isolated evidence root)")
    os.makedirs(out_dir, exist_ok=True)
    try:
        if source_snapshot and source_snapshot.get("snapshot_path"):
            snapshot = dict(source_snapshot)
            snap_path = str(snapshot["snapshot_path"])
            if not os.path.isfile(snap_path):
                raise ValueError("supplied source_snapshot path missing")
            got = file_sha256(snap_path, max_bytes=max_bytes)
            if source_sha256 and str(source_sha256).lower() != got.lower():
                raise ValueError("supplied snapshot hash mismatch vs expected_sha256")
            if snapshot.get("source_sha256") and str(snapshot["source_sha256"]).lower() != got.lower():
                raise ValueError("supplied snapshot metadata hash mismatch vs snapshot bytes")
            snapshot["source_sha256"] = got
            snapshot["parse_path"] = snap_path
            snapshot["snapshot_path"] = snap_path
            if "source_size_bytes" not in snapshot:
                snapshot["source_size_bytes"] = int(os.path.getsize(snap_path))
            if "source_mtime_ns" not in snapshot:
                st = os.stat(real)
                snapshot["source_mtime_ns"] = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
        else:
            snapshot = materialize_source_snapshot(
                real,
                evidence_dir=out_dir,
                max_bytes=max_bytes,
                expected_sha256=source_sha256,
            )
    except ValueError as exc:
        return {"schema": SCHEMA, "ok": False, "state": "failed", "reason": str(exc), "capabilities": caps, "warnings": warnings}
    except Exception as exc:
        return {
            "schema": SCHEMA, "ok": False, "state": "failed",
            "reason": f"snapshot materialization failed: {exc}",
            "capabilities": caps, "warnings": warnings,
        }
    source_sha = snapshot["source_sha256"]
    parse_path = snapshot["snapshot_path"]
    size_bytes = int(snapshot["source_size_bytes"])
    mtime_ns = int(snapshot["source_mtime_ns"])
    try:
        doc, auditor = recover.readfile(parse_path)
    except Exception as exc:
        return {
            "schema": SCHEMA, "ok": False, "state": "failed", "reason": f"DXF parse failed: {exc}",
            "source": real, "source_sha256": source_sha, "capabilities": caps, "warnings": warnings,
        }

    if auditor.has_errors:
        warnings.append(f"auditor reported {len(auditor.errors)} structural error(s)")
    if auditor.has_fixes:
        warnings.append(f"auditor applied {len(auditor.fixes)} recovery fix(es)")

    insunits = int(doc.header.get("$INSUNITS", 0) or 0)
    units = {
        "insunits": insunits,
        "name": UNIT_NAMES.get(insunits, f"unknown({insunits})"),
        "measurement": doc.header.get("$MEASUREMENT"),
    }
    layers = sorted({str(layer.dxf.name) for layer in doc.layers})
    layouts = [{
        "name": layout.name,
        "is_modelspace": bool(getattr(layout, "is_modelspace", False)),
        "is_paperspace": bool(getattr(layout, "is_any_paperspace", False) or getattr(layout, "is_paperspace", False)),
    } for layout in doc.layouts]

    texts: list[dict[str, Any]] = []
    inserts: list[dict[str, Any]] = []
    geometry: list[dict[str, Any]] = []
    unsupported: dict[str, int] = {}
    geometry_counts: dict[str, int] = {}
    scan_count = 0
    text_truncated = False
    insert_truncated = False
    scan_truncated = False
    missing_fonts: set[str] = set()
    missing_xrefs: list[str] = []
    identity = Matrix44()
    layout_coverage: dict[str, dict[str, int]] = {}

    def resolve_layer(entity_layer: str, insert_layer: str) -> str:
        return insert_layer if (entity_layer or "0") == "0" else entity_layer

    def transform_point(matrix: Matrix44, point: Any) -> list[float]:
        vec = matrix.transform(Vec3(point))
        return [float(vec.x), float(vec.y), float(vec.z)]

    def bump_layout(layout_name: str, key: str) -> None:
        row = layout_coverage.setdefault(layout_name, {"text": 0, "inserts": 0, "geometry": 0})
        row[key] = int(row.get(key) or 0) + 1

    def consider_layout_entities(
        entities: Any,
        *,
        layout_name: str,
        parent_matrix: Matrix44,
        insert_layer: str,
        insert_chain: list[str],
        block_stack: set[str],
        depth: int,
    ) -> None:
        nonlocal scan_count, text_truncated, insert_truncated, scan_truncated
        text_priority_types = {"TEXT", "MTEXT", "ATTDEF", "INSERT"}
        geometry_types = {"LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC", "SPLINE", "POINT", "HATCH", "DIMENSION"}
        for entity in entities:
            if text_truncated and insert_truncated:
                return
            scan_count += 1
            if scan_count > max_walk:
                if not scan_truncated:
                    scan_truncated = True
                    warnings.append(
                        f"hard walk cap reached ({max_walk}); aborting remaining entity walk"
                    )
                return
            try:
                dxftype = entity.dxftype()
            except Exception:
                unsupported["UNKNOWN"] = unsupported.get("UNKNOWN", 0) + 1
                continue
            soft_over = scan_count > max_scan
            if soft_over and not scan_truncated:
                scan_truncated = True
                warnings.append(
                    f"scan soft-cap reached ({max_scan}); geometry skipped but text/insert walk continues"
                )
            # After soft scan cap, skip non-text entities so LINE floods cannot starve late text.
            if soft_over and dxftype not in text_priority_types:
                if dxftype in geometry_types:
                    geometry_counts[dxftype] = geometry_counts.get(dxftype, 0) + 1
                    bump_layout(layout_name, "geometry")
                else:
                    unsupported[dxftype] = unsupported.get(dxftype, 0) + 1
                continue
            try:
                handle = str(entity.dxf.handle) if entity.dxf.hasattr("handle") else None
                try:
                    raw_layer = str(entity.dxf.layer) if entity.dxf.hasattr("layer") else "0"
                except Exception:
                    raw_layer = "0"
                if not raw_layer:
                    raw_layer = "0"
                layer = resolve_layer(raw_layer, insert_layer)
            except Exception as exc:
                unsupported[dxftype] = unsupported.get(dxftype, 0) + 1
                warnings.append(f"skipped {dxftype} due to attribute error: {exc}")
                continue

            if dxftype == "INSERT":
                if len(inserts) >= max_inserts:
                    if not insert_truncated:
                        insert_truncated = True
                        warnings.append(f"insert cap reached ({max_inserts})")
                    continue
                block_name = str(entity.dxf.get("name", "") or "")
                is_xref = _is_xref_block(doc, block_name)
                try:
                    local_matrix = entity.matrix44()
                except Exception:
                    local_matrix = Matrix44()
                composed = parent_matrix @ local_matrix
                record = {
                    "type": "INSERT",
                    "handle": handle,
                    "definition_handle": None,
                    "layer": layer,
                    "raw_layer": raw_layer,
                    "layout": layout_name,
                    "block": block_name,
                    "insert": transform_point(parent_matrix, entity.dxf.insert),
                    "xscale": float(entity.dxf.get("xscale", 1) or 1),
                    "yscale": float(entity.dxf.get("yscale", 1) or 1),
                    "zscale": float(entity.dxf.get("zscale", 1) or 1),
                    "rotation": float(entity.dxf.get("rotation", 0) or 0),
                    "wcs_transform": _matrix_list(composed),
                    "is_xref": is_xref,
                    "insert_chain": list(insert_chain) + ([handle] if handle else []),
                    "depth": depth,
                    "attribs": [],
                    "provenance": {
                        "source_sha256": source_sha,
                        "entity_handle": handle,
                        "layout": layout_name,
                        "insert_chain": list(insert_chain) + ([handle] if handle else []),
                    },
                }
                try:
                    block_layout = doc.blocks.get(block_name)
                    if block_layout is not None and block_layout.block is not None:
                        record["definition_handle"] = str(block_layout.block.dxf.handle)
                except Exception:
                    pass
                for attrib in getattr(entity, "attribs", []) or []:
                    if len(texts) >= max_text:
                        text_truncated = True
                        break
                    scan_count += 1
                    attrib_handle = str(attrib.dxf.handle) if attrib.dxf.hasattr("handle") else None
                    try:
                        attrib_raw_layer = str(attrib.dxf.layer) if attrib.dxf.hasattr("layer") else "0"
                    except Exception:
                        attrib_raw_layer = "0"
                    attrib_layer = resolve_layer(attrib_raw_layer or "0", layer)
                    texts.append({
                        "type": "ATTRIB",
                        "handle": attrib_handle,
                        "definition_handle": None,
                        "layer": attrib_layer,
                        "raw_layer": attrib_raw_layer or "0",
                        "layout": layout_name,
                        "text": _entity_text(attrib),
                        "insert": _point3(attrib.dxf.insert),
                        "height": float(attrib.dxf.get("height", 0) or 0) if attrib.dxf.hasattr("height") else None,
                        "rotation": float(attrib.dxf.get("rotation", 0) or 0) if attrib.dxf.hasattr("rotation") else None,
                        "tag": str(attrib.dxf.get("tag", "") or "") or None,
                        "parent_insert_handle": handle,
                        "insert_chain": record["insert_chain"],
                        "wcs_transform": None,
                        "transform_note": "attrib_coordinates_already_wcs",
                        "provenance": {
                            "source_sha256": source_sha,
                            "entity_handle": attrib_handle,
                            "layout": layout_name,
                            "insert_chain": record["insert_chain"],
                        },
                    })
                    bump_layout(layout_name, "text")
                    record["attribs"].append({
                        "tag": str(attrib.dxf.get("tag", "") or ""),
                        "text": _entity_text(attrib),
                        "handle": attrib_handle,
                        "insert": _point3(attrib.dxf.insert),
                    })
                inserts.append(record)
                bump_layout(layout_name, "inserts")
                if is_xref:
                    missing_xrefs.append(block_name or handle or "unnamed-xref")
                    warnings.append(
                        f"XREF '{block_name or handle}' referenced but not fetched (external references are never loaded)"
                    )
                    continue
                if depth >= max_depth:
                    warnings.append(f"insert depth cap reached ({max_depth}) at block '{block_name}'")
                    continue
                if block_name in block_stack:
                    warnings.append(f"insert cycle detected at block '{block_name}'; skipping expansion")
                    continue
                try:
                    block_layout = doc.blocks.get(block_name)
                except Exception:
                    block_layout = None
                if block_layout is None:
                    warnings.append(f"missing block definition '{block_name}'")
                    continue
                consider_layout_entities(
                    block_layout,
                    layout_name=layout_name,
                    parent_matrix=composed,
                    insert_layer=layer,
                    insert_chain=record["insert_chain"],
                    block_stack=set(block_stack) | {block_name},
                    depth=depth + 1,
                )
                continue

            if dxftype in {"TEXT", "MTEXT", "ATTDEF"}:
                if len(texts) >= max_text:
                    if not text_truncated:
                        text_truncated = True
                        warnings.append(f"text entity cap reached ({max_text})")
                    continue
                style = str(entity.dxf.get("style", "") or "")
                if style:
                    try:
                        doc.styles.get(style)
                    except Exception:
                        missing_fonts.add(style)
                raw_insert = entity.dxf.get("insert")
                wcs_insert = transform_point(parent_matrix, raw_insert) if raw_insert is not None else None
                texts.append({
                    "type": dxftype,
                    "handle": handle,
                    "definition_handle": handle,
                    "layer": layer,
                    "raw_layer": raw_layer,
                    "layout": layout_name,
                    "text": _entity_text(entity),
                    "insert": wcs_insert,
                    "definition_insert": _point3(raw_insert),
                    "height": float(entity.dxf.get("height", 0) or 0) if entity.dxf.hasattr("height") else (
                        float(entity.dxf.get("char_height", 0) or 0) if entity.dxf.hasattr("char_height") else None
                    ),
                    "rotation": float(entity.dxf.get("rotation", 0) or 0) if entity.dxf.hasattr("rotation") else None,
                    "style": style or None,
                    "tag": str(entity.dxf.get("tag", "") or "") or None if dxftype == "ATTDEF" else None,
                    "parent_insert_handle": insert_chain[-1] if insert_chain else None,
                    "insert_chain": list(insert_chain),
                    "wcs_transform": _matrix_list(parent_matrix) if depth > 0 else None,
                    "provenance": {
                        "source_sha256": source_sha,
                        "entity_handle": handle,
                        "layout": layout_name,
                        "insert_chain": list(insert_chain),
                        "block_depth": depth,
                    },
                })
                bump_layout(layout_name, "text")
                continue

            if dxftype in geometry_types:
                geometry_counts[dxftype] = geometry_counts.get(dxftype, 0) + 1
                bump_layout(layout_name, "geometry")
                if len(geometry) >= max_geometry_samples:
                    continue
                wcs_points = None
                try:
                    if dxftype == "LINE":
                        wcs_points = [transform_point(parent_matrix, entity.dxf.start), transform_point(parent_matrix, entity.dxf.end)]
                    elif dxftype in {"CIRCLE", "ARC"}:
                        wcs_points = [transform_point(parent_matrix, entity.dxf.center)]
                    elif dxftype == "POINT":
                        wcs_points = [transform_point(parent_matrix, entity.dxf.location)]
                    elif dxftype == "LWPOLYLINE":
                        wcs_points = [transform_point(parent_matrix, (p[0], p[1], 0.0)) for p in entity.get_points("xy")]
                except Exception:
                    wcs_points = None
                geometry.append(_geometry_payload(entity, layer=layer, layout_name=layout_name, handle=handle, wcs_points=wcs_points))
                continue

            unsupported[dxftype] = unsupported.get(dxftype, 0) + 1

    ordered_layouts = sorted(
        list(doc.layouts),
        key=lambda layout: (0 if getattr(layout, "is_any_paperspace", False) or getattr(layout, "is_paperspace", False) else 1, layout.name),
    )
    for layout in ordered_layouts:
        consider_layout_entities(
            layout,
            layout_name=layout.name,
            parent_matrix=identity,
            insert_layer="0",
            insert_chain=[],
            block_stack=set(),
            depth=0,
        )

    if unsupported:
        top = ", ".join(f"{k}×{v}" for k, v in sorted(unsupported.items(), key=lambda kv: (-kv[1], kv[0]))[:12])
        warnings.append(f"unsupported/ignored object types: {top}")
    if missing_fonts:
        warnings.append("missing or unresolved text styles/fonts: " + ", ".join(sorted(missing_fonts)[:20]))

    truncated = bool(text_truncated or insert_truncated or scan_truncated)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "ok": True,
        "state": "extracted",
        "source": real,
        "basename": os.path.basename(real),
        "source_sha256": source_sha,
        "source_snapshot": snapshot,
        "parse_path": parse_path,
        "original_preserved": True,
        "source_size_bytes": size_bytes,
        "dxf_version": str(doc.dxfversion),
        "units": units,
        "layers": layers,
        "layouts": layouts,
        "layout_coverage": layout_coverage,
        "counts": {
            "entities_scanned": scan_count,
            "text_entities": len(texts),
            "inserts": len(inserts),
            "geometry_samples": len(geometry),
            "geometry_seen": dict(sorted(geometry_counts.items())),
            "geometry_seen_total": sum(geometry_counts.values()),
            "unsupported_types": len(unsupported),
            "missing_xrefs": len(missing_xrefs),
            "blocks": len(doc.blocks),
        },
        "bounds": {
            "max_bytes": max_bytes,
            "max_text": max_text,
            "max_inserts": max_inserts,
            "max_geometry_samples": max_geometry_samples,
            "max_scan": max_scan,
            "max_walk": max_walk,
            "max_depth": max_depth,
        },
        "texts": texts,
        "inserts": inserts,
        "geometry_samples": geometry,
        "unsupported_object_counts": unsupported,
        "missing_xrefs": missing_xrefs,
        "missing_fonts": sorted(missing_fonts),
        "warnings": warnings,
        "truncated": truncated,
        "text_truncated": text_truncated,
        "insert_truncated": insert_truncated,
        "scan_truncated": scan_truncated,
        "capabilities": caps,
        "extracted_at": _iso(),
        "elapsed_ms": int((time.time() - started) * 1000),
        "quality_state": "needs_review" if warnings else "extracted",
        "verification_note": (
            "DXF native parse expands block TEXT/MTEXT with composed WCS transforms. "
            "Geometry is sampled; text/insert budgets are independent so geometry floods cannot starve text. "
            "External references are never loaded. DWG/RVT require approved export."
        ),
    }

    if not evidence_dir:
        raise ValueError("evidence_dir required (server-owned isolated evidence root)")
    os.makedirs(evidence_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(real))[0]
    manifest_path = os.path.join(evidence_dir, f"{stem}.dxf.json")
    summary_path = os.path.join(evidence_dir, f"{stem}.dxf.summary.json")
    summary = {
        "schema": SCHEMA,
        "source": real,
        "source_snapshot": snapshot,
        "parse_path": parse_path,
        "source_sha256": source_sha,
        "counts": payload["counts"],
        "layout_coverage": layout_coverage,
        "units": units,
        "layouts": layouts,
        "warnings": warnings,
        "truncated": truncated,
        "elapsed_ms": payload["elapsed_ms"],
        "text_sample": [
            {"type": t.get("type"), "text": t.get("text"), "layout": t.get("layout"), "insert": t.get("insert"), "tag": t.get("tag")}
            for t in texts[:80]
        ],
    }
    for path_out, body in ((manifest_path, payload), (summary_path, summary)):
        tmp = path_out + f".tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(body, handle, indent=2)
            handle.write("\n")
        os.replace(tmp, path_out)
    payload["manifest_path"] = manifest_path
    payload["summary_path"] = summary_path

    if update_ledger:
        from api.jarvis_rag_ingest_events import attach_review_extraction_evidence
        attach_review_extraction_evidence(
            real,
            source_sha256=source_sha,
            evidence={
                "kind": "dxf_native",
                "manifest_path": manifest_path,
                "summary_path": summary_path,
                "ocr_verification_state": "not_applicable",
                "quality_state": payload["quality_state"],
                "extraction_mode": "dxf_native",
                "warnings": warnings,
                "truncated": truncated,
                "text_count": len(texts),
            },
        )
    return payload
