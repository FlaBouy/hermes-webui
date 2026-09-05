"""Bounded voltage-drop Q&A: retain owner inputs, call the electrical service once.

Never use an assistant's earlier guesses as design inputs or generate scratch code.
Other engineering work remains on its existing governed path.
"""
import json
import re
from urllib.request import Request, urlopen
from api.smedley_cable_tray import accepted_material

TOOL_LABELS = {
    'voltage-drop': 'Voltage Drop', 'feeder-size': 'Feeder Size',
    'conductor-sets': 'Conductor Sets', 'ocpd-size': 'OCPD Size',
    'conduit-fill': 'Conduit Fill', 'grounding': 'Grounding',
    'cable-tray-fill': 'Cable Tray Fill', 'motor-circuit': 'Motor Circuit',
    'motor-starter': 'Motor Starter', 'mcc-bucket': 'MCC Bucket', 'vfd-circuit': 'VFD Circuit',
}


def requested_tool(text):
    """Resolve an electrical action and its subject, not a literal menu label."""
    text = str(text or '').lower()
    if re.search(r"\b(?:do not|don't|don’t|never)\s+(?:open|run|calculate|use|size|check)\b", text):
        return None
    if re.search(r'\b(?:later|not yet|tomorrow)\b', text) or re.match(r'\s*(?:explain|define|what is|what are)\b', text):
        return None
    if not re.search(r'\b(?:open|show|use|calculate|size|sizing|check|compute|determine|select)\b', text):
        return None
    subjects = (
        ('voltage-drop', r'voltage\s*drop|vd'),
        ('cable-tray-fill', r'(?:cable\s+)?tray\s+fill|fill\b.{0,40}\btray'),
        ('conduit-fill', r'conduit'),
        ('motor-starter', r'(?:motor\s+)?starter'),
        ('mcc-bucket', r'mcc\s*bucket'),
        ('vfd-circuit', r'vfd|variable\s+frequency\s+drive'),
        ('ocpd-size', r'ocpd|overcurrent\s+(?:device|protection)|breaker|fuse'),
        ('grounding', r'grounding|ground\s+(?:wire|conductor)|egc|gec'),
        ('feeder-size', r'feeder(?:s|\s+size)?'),
        ('conductor-sets', r'conductors?|conductor\s+sets|cable\s+size'),
        ('motor-circuit', r'motor\s+circuit'),
    )
    for tool, subject in subjects:
        if re.search(r'\b(?:' + subject + r')\b', text):
            return tool
    return None


def tool_form_reply(tool, messages, prompt):
    params = retained_circuit(messages, prompt)
    params.setdefault('target_vd_pct', 2.5)
    try:
        params['material'] = accepted_material(params)
    except ValueError as error:
        return {'reply': str(error), 'model': 'deterministic-electrical', 'error': 'unsupported_material'}
    return {'reply': f"Use the {TOOL_LABELS[tool]} tool to enter or adjust the parameters. Known circuit inputs are carried forward; missing inputs still need confirmation.",
            'model': 'deterministic-electrical', 'tool_action': {'id': tool, 'params': params}}


def owner_text(row):
    if row.get('role') != 'user':
        return ''
    text = str(row.get('content') or '')
    return text.split('Owner message: ', 1)[-1]


def is_voltage_drop_question(text, messages=None):
    text = str(text or '').lower()
    direct = bool(re.search(r'\b(?:voltage\s*drop|vd|cable\s+size|conductor\s+size)\b', text)
                and re.search(r'\d', text)
                and not re.search(r'\b(?:do not|don.t|never)\s+(?:calculate|run|rerun|re-run)\b', text))
    prior = retained_circuit(messages, '')
    followup = bool(prior.get('voltage') and prior.get('length_ft')
                    and (re.search(r'\d+(?:\.\d+)?\s*%', text) or re.search(r'\b(?:copper|alumin[ui]m|material|conduit|raceway)\b', text))
                    and re.search(r'\b(?:re-?run|try|target|below|limit|instead|change|use|using)\b', text)
                    and not re.search(r'\b(?:do not|don.t|never)\b', text))
    return direct or followup


def retained_circuit(messages, prompt):
    values = {}
    patterns = {
        'voltage': r'(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(?:v\b|volts?\b)',
        'hp': r'(?<![\w.])(\d+(?:\.\d+)?)\s*(?:hp\b|horsepower\b)',
        'amps': r'(?<![\w.])(\d+(?:\.\d+)?)\s*(?:amps?\b|a\b)',
        'length_ft': r'(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(?:ft\b|feet\b|foot\b)',
        'target_vd_pct': r'(\d+(?:\.\d+)?)\s*%',
        'power_factor': r'(?:power\s*factor|pf)\s*(?:of|=|:)?\s*(0?\.\d+|1(?:\.0+)?)',
        'phase': r'\b([13])\s*[- ]?\s*(?:phase|ph|p|ø|φ)\b',
    }
    # Carry only the latest circuit discussion, not every number in a long review.
    rows = list(messages or [])[-40:] + [{'role': 'user', 'content': prompt}]
    for row in rows:
        text = owner_text(row)
        if row.get('role') == 'user' and isinstance(row.get('calculator_inputs'), dict):
            values.update(row['calculator_inputs'])
            if 'amps' in row['calculator_inputs']:
                values.pop('hp', None)
            continue
        found = {}
        for key, pattern in patterns.items():
            match = re.search(pattern, text, re.I)
            if match:
                found[key] = float(match[1].replace(',', ''))
        if 'voltage' in found and ('hp' in found or 'amps' in found) and not re.search(r'\b(?:re-?run|same|instead|change|still)\b', text, re.I):
            # Restating numbers is not consent to replace an unsupported material.
            # Only an explicitly new circuit clears that material constraint.
            retained_material = {key: values[key] for key in ('material',) if key in values}
            values = {} if re.search(r'\bnew\s+circuit\b', text, re.I) else retained_material
        values.update(found)
        if re.search(r'\btc[- ]?er\b', text, re.I):
            values['cable_construction'] = 'tc_er'
        if re.search(r'\b(?:cable\s+tray|ladder\s+tray)\b', text, re.I):
            # Owner's established tray profile; explicit form changes still win.
            values.update(installation_method='aluminum_ladder_tray', cable_construction='tc_er', rung_spacing_in=9)
        if re.search(r'\b(?:in|using|use)\s+(?:\w+\s+)?(?:conduit|raceway)\b', text, re.I):
            values['installation_method'] = 'raceway'
        conduit = re.search(r'\b(steel|aluminum|pvc)\s+(?:conduit|raceway)\b', text, re.I)
        if conduit:
            values.update(conduit_type=conduit[1].lower(), installation_method='raceway')
        # Support material edits while excluding aluminum supports/raceways.
        material = re.search(r'\b(copper|aluminum|aluminium|silver|gold|brass|bronze|cca)\b(?!\s+(?:(?:ladder|cable)\s+)?(?:tray|conduit|raceway)\b)', text, re.I)
        explicit_material = re.search(r'\b(?:conductor\s+)?material\s*(?:is|=|:|to)\s*([\w-]+)', text, re.I)
        if explicit_material:
            values['material'] = explicit_material[1].lower()
        elif material:
            values['material'] = material[1].lower()
    return values


def voltage_drop_reply(messages, prompt, *, opener=urlopen):
    values = retained_circuit(messages, prompt)
    try:
        values['material'] = accepted_material(values)
    except ValueError as error:
        return {'reply': str(error), 'model': 'deterministic-electrical', 'error': 'unsupported_material'}
    missing = [name for name in ('voltage', 'length_ft') if not values.get(name)]
    if not values.get('hp') and not values.get('amps'):
        missing.append('motor horsepower or load amps')
    if missing:
        return {**tool_form_reply('voltage-drop', messages, prompt), 'reply': 'I need ' + ', '.join(missing) + '. Enter those in the Voltage Drop tool; known inputs are retained.'}
    for key, value in [('phase', 3), ('power_factor', .85), ('target_vd_pct', 2.5)]:
        values.setdefault(key, value)
    params = dict(circuit_type='branch', continuous_load=True, temp_rating=75, ambient_temp_c=30,
                  num_conductors=3, conduit_type='pvc', installation_method='aluminum_ladder_tray' if values.get('cable_construction') == 'tc_er' else 'raceway',
                  cable_series='southwire_45253', tray_cover='none', rung_spacing_in=9)
    params.update(values)
    params['phase'] = int(values['phase'])
    try:
        req = Request('http://127.0.0.1:8801/tools/conductor-sets', data=json.dumps(params).encode(), headers={'Content-Type': 'application/json'})
        with opener(req, timeout=8) as response:
            data = json.loads(response.read())
        result = data.get('result') or {}
        if data.get('status') != 'ok' or not result.get('solution_found'):
            return {**tool_form_reply('conductor-sets', messages, prompt), 'reply': 'The electrical tool did not establish a cable size: ' + str(data.get('error') or 'no supported catalog size met both constraints') + '. Adjust the retained inputs in Conductor Sets; no guessed replacement result was issued.'}
        normalized = data.get('calculation') or {}
        required = ('material', 'conductor_size', 'voltage', 'phase', 'current', 'length_ft', 'conduit_type',
                    'target_vd_pct', 'voltage_drop_pct', 'voltage_drop_volts', 'calculator_family', 'installation')
        if (any(normalized.get(key) is None for key in required)
                or accepted_material(normalized) != normalized['material']
                or data.get('inputs', {}).get('material') != normalized['material']):
            raise ValueError('Calculator response lacks the accepted-input contract.')
        size = normalized['conductor_size']
        unit = 'kcmil' if str(size).isdigit() and int(size) >= 250 else 'AWG'
        reply = (f"At the accepted {normalized['target_vd_pct']:g}% target, the smallest supported catalog size satisfying ampacity and running voltage drop is {size} {unit} {normalized['material']}: "
                 f"{normalized['voltage_drop_volts']:.2f} V drop ({normalized['voltage_drop_pct']:.2f}%) over {normalized['length_ft']:g} ft at {normalized['voltage']:g} V, {normalized['phase']:g}-phase. "
                 f"Tool load current: {normalized['current']:g} A. Conduit/raceway basis: {normalized['conduit_type']}. "
                 f"Calculator: {normalized['calculator_family']}; installation: {normalized['installation']['method']}.\n\n"
                 'Calculation assumptions to confirm: ' + '; '.join(data.get('assumptions') or []) + '. '
                 'This is a provisional running-load calculation, not approval: check starting voltage, tray fill/bonding, installed cable ground size and manufacturer/plant requirements. '
                 'Earlier conversational size estimates are superseded by this tool result.')
        accepted = dict(params, **data['inputs'], amps=normalized['current'], target_vd_pct=normalized['target_vd_pct'])
        return {'reply': reply, 'model': 'deterministic-electrical', 'electrical_inputs': accepted, 'electrical_result': data,
                'tool_action': {'id': 'voltage-drop', 'params': accepted}}
    except Exception:
        return {**tool_form_reply('conductor-sets', messages, prompt), 'reply': 'The electrical calculation service did not return a verified result within this request. Your circuit inputs remain available in Conductor Sets; no heavy agent or substitute estimate was started. Please retry.'}
