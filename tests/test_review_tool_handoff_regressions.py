"""Regressions pinned to the owner's missed feeder card and clipped decimal."""
import json

import pytest

from api.project_review_electrical import requested_tool, retained_circuit, tool_form_reply, voltage_drop_reply
from api.biggy_voice_route import request_fast_voice_reply

PROMPT = ('We have a 480V 3P 10HP motor sitting 750 ft from the bucket and feeder '
          'will be ran in cable tray. Size the feeder for that motor using copper conductors')


@pytest.mark.parametrize('prompt,tool', [
    (PROMPT, 'feeder-size'),
    ('What size feeder do I need for this motor?', 'feeder-size'),
    ('Calculate the fill for this conduit', 'conduit-fill'),
    ('Size the conductors for this circuit', 'conductor-sets'),
    ('Check the voltage drop on this run', 'voltage-drop'),
    ('Size the motor starter', 'motor-starter'),
    ('Check cable tray fill', 'cable-tray-fill'),
])
def test_natural_tool_requests(prompt, tool):
    assert requested_tool(prompt) == tool


@pytest.mark.parametrize('prompt', [
    'Explain what feeder sizing means', 'Do not size the feeder yet',
    'We will calculate conduit fill later', 'What is a motor starter?',
])
def test_discussion_and_deferred_requests_do_not_open_tools(prompt):
    assert requested_tool(prompt) is None


def test_exact_owner_inputs_and_followup():
    values = retained_circuit([], PROMPT)
    assert values['phase'] == 3
    assert values['installation_method'] == 'aluminum_ladder_tray'
    assert values['material'] == 'copper'
    assert values['length_ft'] == 750
    assert values['hp'] == 10
    action = tool_form_reply('feeder-size', [], PROMPT)['tool_action']
    assert action['params']['target_vd_pct'] == 2.5
    follow = retained_circuit([{'role':'user','content':PROMPT}], 'Make that 900 ft and 1P instead')
    assert follow['phase'] == 1 and follow['length_ft'] == 900
    assert follow['installation_method'] == 'aluminum_ladder_tray'


def test_tray_material_is_not_conductor_material():
    values = retained_circuit([], '480V 3-phase 10HP, 750 ft in aluminum cable tray using copper conductors')
    assert values['material'] == 'copper'
    assert values['installation_method'] == 'aluminum_ladder_tray'


def test_unavailable_service_still_opens_card_with_retained_inputs():
    def unavailable(*args, **kwargs):
        raise TimeoutError('unavailable')
    result = voltage_drop_reply([{'role': 'user', 'content': PROMPT}],
                                'Re-run for 2% VD', opener=unavailable)
    assert result['model'] == 'deterministic-electrical'
    assert result['tool_action']['id'] == 'conductor-sets'
    assert result['tool_action']['params']['length_ft'] == 750
    assert result['tool_action']['params']['target_vd_pct'] == 2
    assert 'no heavy agent or substitute estimate' in result['reply']


def test_no_supported_solution_still_opens_card():
    class NoSolution:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"status":"ok","result":{"solution_found":false}}'
    result = voltage_drop_reply([], PROMPT, opener=lambda *a, **k: NoSolution())
    assert result['tool_action']['id'] == 'conductor-sets'
    assert 'no guessed replacement' in result['reply']


class ChunkStream:
    def __init__(self, chunks): self.chunks = chunks
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def __iter__(self):
        for chunk in self.chunks:
            yield ('data: ' + json.dumps({'choices':[{'delta':{'content':chunk}}]}) + '\n').encode()
        yield b'data: [DONE]\n'


@pytest.mark.parametrize('chunks', [
    ['The target is 2.', '5% (approx. 1.', '75% calculated drop). Confirm the assumptions.'],
    list('The target is 2.5% (approx. 1.75% calculated drop). Confirm the assumptions.'),
    ['The target is 2.5% (approx. 1.75% calculated drop). Confirm the assumptions.'],
])
def test_stream_boundaries_never_truncate_decimal_or_abbreviation(chunks):
    result = request_fast_voice_reply('Summarize the example.', personality='smedley',
                                      opener=lambda *a,**k: ChunkStream(chunks))
    assert result['reply'] == 'The target is 2.5% (approx. 1.75% calculated drop). Confirm the assumptions.'
