# Smedley Project Review — DXF + Verified OCR (task smedley-dxf-verified-ocr-20260902)

Status: **MCP tools registered live under Smedley profile; Biggy WebUI restarted by Turing. Callable extract verified via registered MCP stdio. Table/BOM structure remains unresolved — not engineering-verified. External producer/watch patches still staged only.**

## Exact capability limits

| Capability | Limit / behavior |
| --- | --- |
| DXF native | `.dxf` only via ezdxf; **DWG/RVT/IFC** → `needs_approved_export` |
| DXF file bound | **256 MiB** (`SMEDLEY_DXF_MAX_BYTES`) |
| DXF scan | soft text-priority **1.5M** entities; hard walk **5M**; text/insert budgets independent of geometry flood |
| XREFs | never fetched; reported in `missing_xrefs` |
| PDF file / pages | **64 MiB**; default **max_pages=8**; render pixel budget enforced |
| OCR engines | RapidOCR + Tesseract required for cross-check; native-text-only pages skip OCR |
| Default OCR trigger | `force` / producer OCR modes **or** `raster_detected` **or** (`native_fragments ≤ 5` **and** significant page image coverage). No mode hint required for sparse P&ID-like sheets |
| Orientation | OCR confidence sweep over **0/90/180/270 CW** using readable-token coverage × mean confidence only (no content/cue lexicon). Per-probe Tesseract timeout. Within uncertainty margin → leave at 0. Source `page_renders/` unrotated; oriented copies in `ocr_page_renders/` |
| Table verify | **Preferred:** embedded page image XObjects (pypdfium2) at native DPI + pad + geometry/OCR orientation; ruled-grid per raster. **Fallback:** whole-page render when no dense embedded table qualifies. Footer-contaminated whole-page bboxes → unverified. **`cells_verified` never true** from agreement alone. WB3339-012 fixtures: page render BOM/device + embedded BOM **12×8**. |
| Cell OCR | Under known geometry: **cell-isolated crops** (modest inset + pad; no whole-image grid wipe). RapidOCR **one load per cell batch** with **`use_cls=False` when orientation established** and **`use_det=False` for single ink-line cells** (recognition-only via horizontal ink projection / connected bands after excluding edge rules — **not** absolute height/DPI; genuine multiline ink and inconclusive merged-cell spans keep the detector). Tesseract PSM from cell geometry; real per-cell timeout + shared deadline. **Only pure zero-ink** inset crops → **`geometric_blank`** before engines; ellipsis / dashes / small punctuation are content (never blank-skipped). Durable `table_geometry` from actual row/col indices (no invented 9-col BOM on 8-col grids). Agreement ≠ approval; **`cells_verified` never from engines alone**. |
| Embedded rasters | Provenance: `source_sha256`, `image_sha256`, PDF `source_bbox_pdf`, `placement_matrix`, dpi/bpp metadata, oriented PNG path. Size-threshold skips are **`unprocessed_non_table_candidate`** (e.g. speed-calc strips), not ornament claims; **`coverage_complete` scoped to detected table candidates**, not full drawing coverage. Budgets: max images/page, min edge/pixels, max pixels/image. **Partial coverage:** any failed/significant-skipped table candidate → `coverage_complete=false` / `structure_verified=false` while good rasters remain in evidence. |
| Aligned cell reports | Full engine-A/B cell lists + full discrepancy lists persisted under evidence `aligned_cell_reports/`; manifest carries counts + bounded previews + paths only. |
| WB3339 / BOM | Guarded OCR evidence only; **do not claim approved 11-row / verified cells** |
| Provenance | Parse **immutable hashed snapshot** under evidence `source_snapshot/` via exclusive `mkstemp` names (outside library). Live path is provenance only |
| Ledger | Live trials / samples: **`update_ledger=false`** |
| Scope | Path must stay under the selected Project Review `rag_folder`; no client `output_dir` |
| `12-1-0104.pdf` | **TEST ONLY** — remain exactly where placed under 26HOS-006; do not move/rewrite; do not fold into production Hosford review findings |
| Automatic DXF watcher ingestion | **Not claimed** — external producer/watch patches remain staged, not deployed |
| Review dialog tool follow-through | See `docs/smedley-review-followthrough.md` — shared dispatch contract; ROUTING SIMULATION vs ACTUAL tool-loop checks distinguished there |

## Live operational state (2026-09-02)

| Item | State |
| --- | --- |
| Hermes-agent venv deps | **Live** — Turing installed 11 pinned packages; main verified `pip check` clean + versions |
| MCP registration | **Live** — `smedley_project_review` in `/Users/rick/.hermes/profiles/smedley/config.yaml` (`enabled: true`, command = repo `.venv`, `HERMES_WEBUI_STATE_DIR` = Biggy webui-state). Model/provider/personality untouched |
| Service restart | **Done by Turing** — `ai.biggy.webui` only; `/health` on `:8790` → `status=ok`, `server_started_at=1788350261.069769`, `active_runs=0` |
| HTTP extract/capabilities | **Auth obstacle** — `auth_enabled=true`, unauthenticated GET → **401**; no session cookie available in this pass (auth not disabled) |
| Registered MCP stdio | **Live-tested** (exact config command/env; project `bdd341b152a4`; no monkeypatch) |
| External producer/watch patches | **Staged only** — not deployed; automatic DXF watcher ingestion not claimed |

### Live MCP outcomes (`project_id=bdd341b152a4`, `update_ledger=false`)

- **initialize / tools/list:** OK — tools `project_review_extract_capabilities`, `project_review_extract`
- **capabilities:** `callable=true`, DXF parser available, PDF OCR `available`, state_dir = Biggy webui-state
- **Out-of-project path:** rejected — `path is outside the selected Project Review RAG folder` (temp sample)
- **DXF** `SK-26BR-102-03 Interconnects.dxf`: `ok`, `state=extracted`, ~23.0 s / 22379 ms, scanned 468961, text 7643, inserts 598, geometry samples 2000, truncated=false, AC1027
  evidence: `~/.jarvis_rag_status/project_review_evidence/0734b698eec9665d/SK-26BR-102-03_Interconnects.dxf/`
- **PDF** `12-1-0104.pdf` (**TEST ONLY**, defaults, no force/mode): `ok`, `state=needs_review`, `ocr_verification_state=structure_unverified`, ~28.6 s / 27757 ms; native=2, `raster_detected=false`, `ocr_trigger=sparse_native_with_image_coverage`, rotate **270° CW**, `cells_verified=false`
  evidence: `~/.jarvis_rag_status/project_review_evidence/3a0e7380e7075c92/12-1-0104.pdf/`
- **Sources:** DXF/PDF SHA256 + mtime **unchanged** after runs
- **projects.json:** unchanged; **ingest_ledger.json:** unchanged (`update_ledger=false`)
- Note: `library.json` heartbeat/`last_file` changed during the window (concurrent live `rag-library-watch` likely); **not** a ledger attach and **not** a full reingest

## Repo pytest

```bash
./scripts/test.sh \
  tests/test_smedley_project_review_dxf_ocr.py \
  tests/test_biggy_typed_fast_lane.py \
  tests/test_biggy_project_review_lifecycle.py
# → 31 passed
```

## MCP config (live)

```yaml
smedley_project_review:
  command: /Users/rick/hermes-webui/.venv/bin/python
  args: [/Users/rick/hermes-webui/scripts/smedley_project_review_mcp.py]
  env:
    HERMES_WEBUI_STATE_DIR: /Users/rick/.hermes/profiles/biggy/webui-state
  connect_timeout: 45.0
  enabled: true
```

Known review: `project_id=bdd341b152a4` (`26HOS-006`, `rag_folder=Projects/Projects - 2026/26HOS-006`).

## Remaining limits

- HTTP capabilities/extract still need a logged-in session (401 without auth)
- **Not engineering-verified** while table geometry is `structure_unverified` / cells unverified
- WB3339 / Hosford BOM: guarded only — no approved 11-row claim
- Producer/watch patches staged; no automatic DXF library ingestion claim
- `12-1-0104.pdf` stays TEST ONLY in place; no production review findings from it

## WB3339-012 (Hosford; guarded)

Gutter-split yields two tables; agreements are **not** verified cells; missing crisp 11-row assurance → acceptable guarded `structure_unverified`, never approved / not engineering-verified.
