"""Bounded project evidence assessment. Excerpts are data, never instructions."""
from datetime import datetime, timezone
import hashlib
import json
import re
import urllib.request


def retrieve(query, folder):
    request = urllib.request.Request('http://127.0.0.1:5004/rag/retrieve',
        data=json.dumps({'query': query, 'filter': {'library_only': True, 'project_folder': folder}}).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=18) as response:
        data = response.read(512000)
    result = json.loads(data)
    if result.get('scope') != folder.rstrip('/') + '/':
        raise ValueError('RAG service did not confirm the selected project scope')
    return result


def commitments(excerpt):
    findings = []
    for sentence in re.split(r'(?<=[.!?])\s+|\n+', excerpt):
        category = next((label for label, pattern in [
            ('Dependency', r'\b(blocked|waiting|depends on|awaiting|until)\b'),
            ('Decision', r'\b(approve|approval|decision|decide)\b'),
            ('Commitment', r'\b(will|shall|must|submit|deliver|deadline|due|milestone)\b'),
        ] if re.search(pattern, sentence, re.I)), None)
        if category:
            dates = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', sentence)
            findings.append({'category': category, 'text': sentence.strip()[:1200], 'dates': dates})
    return findings[:12]


def assess(project, query, tasks, messages, *, retrieve_fn=retrieve):
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 1000:
        raise ValueError('Ask a project question of 1–1000 characters')
    folder = str(project['review'].get('rag_folder') or '').rstrip('/')
    evidence = []
    coverage = []
    try:
        data = retrieve_fn(query.strip(), folder)
        coverage.append(data.get('coverage', 'Indexed excerpts only.'))
        for match in data.get('matches', [])[:16]:
            source = str(match.get('source') or '')
            if not source.startswith(folder + '/') or not match.get('source_hash') or not match.get('pdf_page'):
                continue
            evidence.append({'id': 'D' + str(len(evidence) + 1), 'kind': 'Indexed document',
                'reference': source + ' · page ' + str(match['pdf_page']), 'source_hash': match['source_hash'],
                'text': str(match.get('snippet') or '')[:4000], 'generation': match.get('generation'),
                'chunk_id': match.get('chunk_id')})
    except Exception:
        coverage.append('Project RAG unavailable or scope unconfirmed. No document conclusions were made.')
    terms = set(re.findall(r'[a-z0-9]{3,}', query.lower())) - {'what', 'this', 'that', 'project', 'the', 'are', 'and', 'for', 'with'}
    recent = []
    for index, message in list(enumerate(messages))[-100:]:
        if not isinstance(message, dict):
            continue
        if message.get('role') not in ('user', 'assistant') or message.get('_pending'):
            continue
        text = message.get('content')
        if not isinstance(text, str):
            continue
        # Owner messages may carry an internal routing preamble.
        if message.get('role') == 'user' and 'Owner message:' in text:
            text = text.split('Owner message:', 1)[1].strip()
        text = text[:6000]
        score = sum(term in text.lower() for term in terms)
        if score or commitments(text):
            recent.append((score, index, message.get('role'), text))
    for _, index, role, text in sorted(recent, key=lambda r: (r[0], r[1]), reverse=True)[:12]:
        evidence.append({'id': 'M' + str(index + 1), 'kind': 'Review conversation (' + role + ')',
                         'reference': 'Review message ' + str(index + 1), 'text': text,
                         'source_hash': hashlib.sha256(text.encode()).hexdigest()})
    coverage.append('Up to 12 matching/commitment-bearing messages from the last 100 stored review messages. Conversation claims are not independently verified; later messages can supersede them.')
    linked = [t for t in tasks if t.get('review_project_id') == project['project_id'] and t.get('status') != 'archived']
    candidates = []
    for e in evidence:
        for candidate in commitments(e['text']):
            words = set(re.findall(r'[a-z0-9]{4,}', candidate['text'].lower())) - {'shall', 'must', 'will', 'with', 'that', 'this'}
            matching = []
            for task in linked:
                title_words = set(re.findall(r'[a-z0-9]{4,}', task.get('title', '').lower()))
                overlap = len(words & title_words)
                if overlap >= 2 and overlap / max(1, len(title_words)) >= 0.5:
                    matching.append({'id': task['id'], 'title': task['title'], 'due': task.get('due', ''), 'status': task.get('status')})
            candidate['evidence_id'] = e['id']
            candidate['related_tasks'] = matching
            candidate['comparison'] = ('Possible related tasks; confirm the relationship.' if matching else 'No similar task title found in this review. This is a possible planning gap, not proof of a missing commitment.')
            if matching and candidate['dates'] and any(t['due'] and t['due'] not in candidate['dates'] for t in matching):
                candidate['comparison'] += ' A task date differs from a date in the excerpt; confirm which date governs.'
            candidates.append(candidate)
            if len(candidates) == 50:
                break
        if len(candidates) == 50:
            break
    relevant = candidates
    if re.search(r'blocked|holding|waiting|depend', query, re.I):
        relevant = [c for c in candidates if c['category'] in ('Dependency', 'Decision')]
    elif re.search(r'date|deadline|schedule|when', query, re.I):
        relevant = [c for c in candidates if c['dates'] or re.search(r'due|deadline|schedule', c['text'], re.I)]
    answer = 'The retrieved evidence suggests these items to check; their current status requires confirmation:\n' + '\n'.join(
        c['category'] + ': ' + c['text'][:350] + ' [' + c['evidence_id'] + ']' for c in relevant[:6]) if relevant else 'I did not find a supported answer in the checked excerpts. This does not establish that the project has no outstanding commitments.'
    return {'project_id': project['project_id'], 'project_name': project.get('name'), 'question': query,
            'answer': answer, 'evidence': evidence, 'candidates': candidates,
            'coverage': coverage + ['Up to 50 keyword-based commitment candidates are shown. Dates and task relationships require owner confirmation. No messages, tasks, schedules or evidence readiness were changed.'],
            'checked_at': datetime.now(timezone.utc).isoformat()}
