"""Bounded PA conversation dispatch; never writes planner or calendar state."""
import re
from urllib.parse import urlencode


def intent(text):
    if re.search(r'\b(?:do not|don.t|never)\b', text, re.I):
        return None
    if re.search(r'\b(?:prepare|draft)\b.*\bfollow[ -]?up\b', text, re.I):
        return 'draft'
    if re.search(r'(?:blocking|holding|delaying).*(?:project|review)|(?:project|review).*(?:blocked|deadline|planner|commitment)|(?:promise|promised).*vendor|compare.*(?:deadline|planner)|(?:what|which).*(?:commitments|dependencies)', text, re.I):
        return 'evidence'
    return None


def last_context(messages):
    for message in reversed(messages or []):
        if message.get('role') == 'assistant':
            return message.get('pa_context') or {}
    return {}


def route(text, projects, messages, current='', *, assess_fn):
    previous = last_context(messages)
    choice = re.fullmatch(r'\s*(?:project\s+)?(\d+)\s*[.!]?\s*', text, re.I)
    kind = intent(text)
    selected = None
    selected_draft = None
    if choice and previous.get('draft_choices'):
        index = int(choice[1]) - 1
        if 0 <= index < len(previous['draft_choices']):
            selected_draft = previous['draft_choices'][index]
            kind = 'draft'
    if choice and previous.get('choices'):
        index = int(choice[1]) - 1
        if 0 <= index < len(previous['choices']):
            selected = next((p for p in projects if p['project_id'] == previous['choices'][index]), None)
            text = previous.get('question', text)
            kind = previous.get('intent', 'evidence')
    if not kind:
        if choice and (previous.get('choices') or previous.get('draft_choices')):
            return {'reply': 'Choose one of the numbered options shown above.', 'spoken_text': 'Choose one of the numbered options shown above.', 'pa_context': previous, 'provider_calls': 0, 'model': 'local-pa-resolver'}
        return None
    def response(reply, context=None, spoken=None):
        return {'reply': reply, 'spoken_text': spoken or reply[:450], 'model': 'local-pa-resolver',
                'provider_calls': 0, 'pa_context': context or {}}
    if kind == 'draft':
        draft = selected_draft or previous.get('draft')
        if not draft and previous.get('candidates'):
            choices = previous['candidates'][:6]
            return response('Which item should I draft? Reply with its number.\n'+'\n'.join(f"{i}. {c['title']}" for i,c in enumerate(choices,1)), {'draft_choices':choices}, 'Which item should I follow up? Choose a numbered item on screen.')
        if not draft:
            return response('Ask about the project evidence first, then choose the item to follow up. I do not have an unambiguous item to draft.')
        params = urlencode({'review_id': draft['project_id'], 'draft_title': draft['title'], 'draft_source': draft['source']})
        return response('Proposed follow-up: '+draft['title']+'\n\n[Review this unsaved task](/static/office-planner/index.html?'+params+')\n\nNo task or deadline has been saved.', previous,
                        'I prepared an unsaved follow-up. Open Review this unsaved task to check its wording and date.')
    named = [p for p in projects if p.get('name') and (p['name'].casefold() in text.casefold() or (len(p['project_id'])>=6 and p['project_id'].casefold() in text.casefold()))]
    if selected is None:
        if len(named) == 1:
            selected = named[0]
        elif not named and current:
            selected = next((p for p in projects if p['project_id'] == current), None)
        elif not named and previous.get('project_id'):
            selected = next((p for p in projects if p['project_id'] == previous['project_id']), None)
    if selected is None:
        choices = named or projects
        if not choices:
            return response('No Project Review is available. Create or select a review before asking about its commitments.')
        choices = choices[:12]
        return response('Which project should I use? Reply with its number.\n'+ '\n'.join(f"{i}. {p['name']} ({p['project_id']})" for i, p in enumerate(choices, 1)),
                        {'choices': [p['project_id'] for p in choices], 'question': text, 'intent': kind}, 'Which project should I use? The numbered choices are on screen.')
    data = assess_fn(selected, text)
    reply = '**'+str(selected.get('name') or 'Project')+'**\n\n'+data['answer']
    cited = set(re.findall(r'\[([DM]\d+)\]', data['answer']))
    for e in data['evidence']:
        if e['id'] in cited:
            reply += '\n\n['+e['id']+'] '+e['reference']+' · snapshot '+e['source_hash']+'\n> '+e['text'][:500].replace('\n', '\n> ')
    reply += '\n\n'+ ' '.join(data['coverage'])
    reply += '\n\n[Open project planner](/static/office-planner/index.html?'+urlencode({'review_id': selected['project_id']})+')'
    context = {'project_id': selected['project_id']}
    # "That" only identifies a single cited candidate. Never choose the first of many.
    candidates = [c for c in data['candidates'] if c['evidence_id'] in cited]
    drafts = []
    for c in candidates[:6]:
        source = next(e for e in data['evidence'] if e['id'] == c['evidence_id'])
        drafts.append({'project_id': selected['project_id'], 'title': ('Follow up: '+c['text'])[:240], 'source': (source['reference']+' · SHA256 '+source['source_hash'])[:900]})
    context['candidates'] = drafts
    if len(drafts) == 1:
        context['draft'] = drafts[0]
    spoken = re.sub(r'\[[DM]\d+\]', '', data['answer'])[:400]+' Source references are on screen.'
    return response(reply, context, spoken)
