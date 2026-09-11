"""Minimal read-only review context for PA situation resolution."""
from datetime import datetime, timezone


def review_context(projects):
    rows = []
    for project in projects:
        review = project.get('review')
        if project.get('profile') != 'biggy' or not isinstance(review, dict) or review.get('review_owner') != 'smedley':
            continue
        rows.append({'id': str(project.get('project_id') or ''),
                     'name': str(project.get('name') or 'Unnamed review'),
                     'state': str(review.get('state') or 'unknown'),
                     'scope': str(review.get('scope') or '')[:1000]})
    return {'projects': rows, 'checked_at': datetime.now(timezone.utc).isoformat(),
            'coverage': 'Saved review metadata only. Document contents, evidence readiness and review conversations were not refreshed.'}
