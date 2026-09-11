"""Page-scoped Docling extraction with source-bound cache and conservative quality.

Native evidence is retained. Raster/geometry pages are supplemented with OCR and
remain NEEDS_REVIEW unless an independent, source-bound review is supplied.
"""
from __future__ import annotations

import hashlib
from importlib.metadata import version, PackageNotFoundError
import json
import os
from pathlib import Path
import re
import time
import threading

_WARM = threading.local()

from review_readiness import digest, usable

SCHEMA = 'argus.pdf.pages.v2'


def options():
    try:
        engine = version('docling')
    except PackageNotFoundError:
        engine = 'unavailable'
    return {'schema': SCHEMA, 'engine': 'docling', 'version': engine,
            'furniture': True, 'tables': True, 'page_ocr': True}


def cache_key(path):
    return hashlib.sha256((digest(path) + json.dumps(options(), sort_keys=True)).encode()).hexdigest()


def _bound(manifest, path, count, text_hash=None):
    return (manifest.get('source_hash') == digest(path) and manifest.get('page_count') == count
            and manifest.get('processing_options') == options()
            and (text_hash is None or manifest.get('sidecar_hash') == text_hash))


def _native_profile(page, number):
    from pypdf.generic import ContentStream
    positions = []

    def visitor(text, cm, tm, font, size):
        if usable(text):
            positions.append(float(tm[5]) + float(cm[5]))

    text = page.extract_text(visitor_text=visitor) or ''
    operations = ContentStream(page.get_contents(), page.pdf).operations
    geometry = sum(op in (b'l', b'c', b're', b'm') for args, op in operations)
    images = len(page.images)
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    concentrated = bool(positions) and (max(positions) - min(positions)) < height * .25
    drawing = max(width, height) >= 1000 or geometry > 80
    suspicious = images > 0 or drawing or (geometry > 15 and concentrated) or len(usable(text)) < 80
    return {'pdf_page': number, 'native_text': text, 'geometry_operations': geometry,
            'image_count': images, 'native_text_concentrated': concentrated,
            'requires_visual_validation': suspicious, 'needs_ocr': suspicious,
            'width_points': width, 'height_points': height}


def _items(document, number):
    values = []
    from docling_core.types.doc.document import ContentLayer
    for item, _level in document.iterate_items(included_content_layers={ContentLayer.BODY, ContentLayer.FURNITURE}):
        text = getattr(item, 'text', '') or ''
        if not text and hasattr(item, 'export_to_markdown'):
            text = item.export_to_markdown(doc=document)
        if not usable(text):
            continue
        for prov in getattr(item, 'prov', []):
            if prov.page_no == number:
                box = prov.bbox.model_dump(mode='json') if getattr(prov, 'bbox', None) else None
                values.append({'text': text, 'pdf_page': number, 'bbox': box,
                               'label': str(getattr(item, 'label', '')), 'content_layer': str(getattr(item, 'content_layer', ''))})
    return values


def _engineering_tokens(text):
    return set(re.findall(r'\b[A-Z]{2,}[-_]\w+|(?<!\w)(?:\d+\.\d+|\.\d+)\b', text))


def extract_pdf(path, state=lambda value: None, *, verifier=None):
    from pypdf import PdfReader
    timings = {'page_profiling': 0, 'native_extraction': 0, 'ocr': 0}
    started = time.monotonic()
    identity = digest(path)
    timings['extraction_source_hash'] = time.monotonic() - started
    started = time.monotonic()
    reader = PdfReader(path)
    count = len(reader.pages)
    timings['page_count'] = time.monotonic() - started
    started = time.monotonic()
    profiles = [_native_profile(page, i) for i, page in enumerate(reader.pages, 1)]
    timings['page_profiling'] = time.monotonic() - started
    manifest = {'schema': SCHEMA, 'source_hash': identity, 'source_version': identity,
                'source_readable': True, 'page_count': count, 'quality_state': 'needs_review',
                'pages': [], 'warnings': [], 'processing_options': options(), 'timings': timings}
    sidecar = Path(path).with_suffix('.ocr.txt')
    if sidecar.exists():
        # Bind BOTH source and derivative. Producer "verified" never bypasses
        # independent fidelity evaluation and per-page checks.
        try:
            bound = json.loads(sidecar.with_suffix('.manifest.json').read_text())
            if not _bound(bound, path, count, digest(sidecar)):
                raise ValueError('source/derivative/options mismatch')
            manifest['sidecar_binding'] = 'valid; Docling page validation still required'
        except (OSError, ValueError):
            manifest['sidecar_binding'] = 'rejected'
            manifest['warnings'].append('Stale or unbound sidecar ignored')
    cache_root = os.environ.get('ARGUS_REVIEW_CACHE_DIR')
    cache = Path(cache_root) / (cache_key(path) + '.json') if cache_root else None
    if cache and cache.exists():
        try:
            cached = json.loads(cache.read_text())
            # Only re-use machine extraction; re-evaluate reviewer evidence.
            if _bound(cached, path, count) and cached.get('schema') == SCHEMA:
                manifest['pages'] = cached['pages']
                for page in manifest['pages']:
                    page['quality_state'] = page['machine_quality_state']
                manifest['cache_hit'] = True
        except (OSError, ValueError, KeyError):
            pass
    if not manifest['pages']:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling_core.types.doc.document import ContentLayer
        if not hasattr(_WARM, 'converters'):
            _WARM.converters = {}
        converters = _WARM.converters
        for profile in profiles:
            number = profile['pdf_page']
            decision_at = time.monotonic()
            ocr = profile['needs_ocr']
            timings['ocr_decision'] = timings.get('ocr_decision', 0) + time.monotonic() - decision_at
            if ocr:
                state('OCR_REQUIRED')
                state('OCR_RUNNING')
            if ocr not in converters:
                opts = PdfPipelineOptions()
                opts.do_ocr = ocr
                opts.ocr_options.force_full_page_ocr = ocr
                opts.do_table_structure = True
                converters[ocr] = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
            at = time.monotonic()
            result = converters[ocr].convert(path, page_range=(number, number))
            timings['ocr' if ocr else 'native_extraction'] += time.monotonic() - at
            document = result.document
            exported = document.export_to_markdown(included_content_layers={ContentLayer.BODY, ContentLayer.FURNITURE}).strip()
            items = _items(document, number)
            # Preserve all furniture, including notes without numerical tokens;
            # exact repeated lines are deduplicated only within this same page.
            native = profile.pop('native_text')
            merged = '\n'.join(dict.fromkeys(line for line in (exported + '\n' + native).splitlines() if line.strip()))
            page_warnings = []
            if str(result.status).lower().split('.')[-1] != 'success':
                page_warnings.append('incomplete conversion')
            if not usable(exported):
                page_warnings.append('empty page conversion')
            if _engineering_tokens(native) - _engineering_tokens(exported):
                page_warnings.append('native/Docling identifier disagreement')
            if profile['requires_visual_validation']:
                page_warnings.append('independent visual fidelity review required')
            if not usable(merged):
                page_warnings.append('empty page')
            printed = re.search(r'\bPrinted page\s+(\S+)', merged, re.I)
            state_value = 'needs_review' if page_warnings else 'verified'
            manifest['pages'].append(dict(profile, text=merged, items=items, processed=True,
                printed_page=printed.group(1) if printed else None,
                quality_state=state_value, machine_quality_state=state_value,
                extraction_method='native+docling_page_ocr' if ocr else 'native+docling', warnings=page_warnings))
    # The independent verifier adapter is injected by the caller. Its conclusion
    # is accepted only for the same content hash and explicit per-page approval.
    if verifier:
        evidence = verifier(path, manifest)
        manifest['verifier'] = evidence
        if evidence.get('quality_state') not in ('verified', 'human_verified'):
            for page in manifest['pages']:
                page['quality_state'] = 'needs_review'
                page.setdefault('warnings', []).append('independent verifier did not approve')
        if evidence.get('source_hash') == identity and evidence.get('quality_state') in ('verified', 'human_verified'):
            approved = set(evidence.get('approved_pages') or [])
            for page in manifest['pages']:
                if page['pdf_page'] in approved and usable(page['text']) and page.get('processed'):
                    page['quality_state'] = 'verified'
    manifest['quality_state'] = ('verified' if count > 0 and all(p['quality_state'] == 'verified' for p in manifest['pages']) else 'needs_review')
    if not any(usable(p['text']) for p in manifest['pages']):
        manifest['quality_state'] = 'failed'
    for page in manifest['pages']:
        if page['quality_state'] != 'verified':
            manifest['warnings'].extend(f"page {page['pdf_page']}: {reason}" for reason in page.get('warnings', []))
    if digest(path) != identity:
        raise RuntimeError('PDF changed during extraction')
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_suffix('.' + str(os.getpid()) + '.tmp')
        temporary.write_text(json.dumps(manifest, ensure_ascii=False))
        os.replace(temporary, cache)
    return '\n\n'.join(p['text'] for p in manifest['pages']), manifest
