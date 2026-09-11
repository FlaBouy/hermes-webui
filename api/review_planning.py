"""Read-only, bounded document planning proposals; never changes evidence or tasks."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

SUPPORTED = {'.pdf', '.txt', '.md'}
MAX_BYTES = 20 * 1024 * 1024


def documents(rag_folder):
    from api.smedley_project_review_extract import LIBRARY_ROOT, _safe_rel_folder
    root = Path(LIBRARY_ROOT).resolve()
    folder = root / _safe_rel_folder(rag_folder)
    folder = folder.resolve()
    if folder == root or root not in folder.parents or not folder.is_dir():
        raise ValueError('Selected review folder is unavailable')
    found = []
    visited = 0
    for parent, dirs, files in os.walk(folder, followlinks=False):
        visited += 1
        if visited > 3000:
            return {'documents': found, 'limited': True}
        dirs[:] = sorted(d for d in dirs if not Path(parent, d).is_symlink())
        for name in sorted(files):
            visited += 1
            if visited > 3000 or len(found) >= 200:
                return {'documents': found, 'limited': True}
            path = Path(parent, name)
            if path.suffix.lower() in SUPPORTED and not path.is_symlink():
                found.append(str(path.relative_to(folder)))
    return {'documents': found, 'limited': False}


def proposals(sections):
    """Keyword candidates only. Dates remain unset for explicit owner review."""
    found = []
    patterns = [
        ('Decision', r'\b(decision|approve|approval|decide)\b'),
        ('Milestone', r'\b(milestone|commissioning|completion|kickoff)\b'),
        ('Deliverable', r'\b(deliverable|submit|deliver|submission|provide)\b'),
        ('Deadline / action', r'\b(deadline|due|shall|must|action|todo)\b'),
    ]
    for section in sections:
        for number, line in enumerate(section['text'].splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            category = next((name for name, pattern in patterns if re.search(pattern, line, re.I)), None)
            if not category:
                continue
            reference = f"{section['reference']}, line {number}"
            found.append({'title': line[:240], 'excerpt': line[:2000], 'reference': reference,
                          'category': category, 'due': '',
                          'date_note': 'Confirm any date against the source. Relative dates and dates without a year are not inferred.'})
            if len(found) == 50:
                return found, True
    return found, False


def extract(rag_folder, path, start=1):
    from api.smedley_project_review_extract import _resolve_scoped_path
    source = Path(_resolve_scoped_path(path, rag_folder=rag_folder))
    if source.suffix.lower() not in SUPPORTED:
        raise ValueError('Select a PDF, UTF-8 text or Markdown document')
    if type(start) is not int or not 1 <= start <= 100000:
        raise ValueError('Choose a valid starting page / text block')
    if source.stat().st_size > MAX_BYTES:
        raise ValueError('Planning preview supports documents up to 20 MB')
    # Parse an immutable bounded copy. Parsing is isolated and time-limited.
    with source.open('rb') as stream:
        content = stream.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValueError('Document exceeds 20 MB')
    digest = hashlib.sha256(content).hexdigest()
    with tempfile.TemporaryDirectory(prefix='review-plan-') as temp:
        snapshot = Path(temp, 'source' + source.suffix.lower())
        snapshot.write_bytes(content)
        try:
            result = subprocess.run([sys.executable, __file__, str(snapshot), str(start)],
                                    capture_output=True, timeout=20, check=True)
            payload = json.loads(result.stdout)
        except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
            raise ValueError('Document preview could not be read within its limits. Use a text export or a smaller document.') from exc
    candidates, limited = proposals(payload['sections'])
    return {**payload, 'candidates': candidates, 'candidate_limit': limited,
            'document': str(path), 'sha256': digest,
            'coverage': 'Keyword suggestions from native text only; not exhaustive, OCR-verified, or engineering-verified. Review original context before saving.'}


def read_snapshot(path, start):
    if path.suffix == '.pdf':
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(str(path)) as doc:
            total = len(doc)
            if start > total:
                raise ValueError('Start exceeds document length')
            sections = []
            for i in range(start - 1, min(total, start + 7)):
                page = doc[i]
                text = page.get_textpage()
                try:
                    count = text.count_chars()
                    sections.append({'reference': f'Page {i + 1}',
                                     'text': text.get_text_range(0, min(count, 12000)),
                                     'truncated': count > 12000})
                finally:
                    text.close()
                    page.close()
    else:
        text = path.read_text(encoding='utf-8-sig')
        # Stable blocks preserve line references without silently cutting long files.
        lines = text.splitlines()
        total = max(1, (len(lines) + 99) // 100)
        if start > total:
            raise ValueError('Start exceeds document length')
        sections = [{'reference': f'Text block {i + 1} (source lines {i * 100 + 1}–{min(len(lines), (i + 1) * 100)})',
                     'text': '\n'.join(lines[i * 100:(i + 1) * 100])[:12000],
                     'truncated': len('\n'.join(lines[i * 100:(i + 1) * 100])) > 12000}
                    for i in range(start - 1, min(total, start + 7))]
    return {'sections': sections, 'total_units': total, 'start': start,
            'next_start': start + len(sections) if start + len(sections) <= total else None,
            'empty_units': [s['reference'] for s in sections if not s['text'].strip()]}


if __name__ == '__main__':
    print(json.dumps(read_snapshot(Path(sys.argv[1]), int(sys.argv[2]))))
