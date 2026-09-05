"""Material capability tests. No network, live calculations, or agent calls."""
import json
from io import BytesIO
import os
from pathlib import Path
import runpy
import sys

import pytest

from api import smedley_cable_tray as adapter
from api.project_review_electrical import (
    is_voltage_drop_question, retained_circuit, tool_form_reply, voltage_drop_reply,
)


@pytest.mark.parametrize('material', ['aluminum', 'aluminium', 'silver', '', None, 0, [], {}, True])
@pytest.mark.parametrize('cable', ['individual', 'tc_er'])
def test_unsupported_material_never_reaches_calculator(material, cable):
    calls = []
    ns = dict(get_ampacity=lambda *a: 100, get_impedance=lambda *a: {},
              minimum_size_for_ampacity=lambda *a: '4',
              _error=lambda error: dict(status='error', error=error),
              TOOL_HANDLERS={'/tools/conductor-sets': lambda p: calls.append(p)})
    result = adapter.install_adapter(ns)('/tools/conductor-sets', dict(material=material, cable_construction=cable))
    assert result['status'] == 'error'
    assert not calls


def test_omitted_default_and_explicit_normalization():
    assert adapter.accepted_material({}) == 'copper'
    assert adapter.accepted_material({'material': ' COPPER '}) == 'copper'
    assert adapter.installation({'material': 'copper', 'conduit_type': 'aluminum'}) is None


@pytest.mark.parametrize('prompt', ['Try aluminum instead', 'Re-run at 2%', 'Re-run same 480V 14A circuit at 2.5% VD', '480V 14A 1200ft voltage drop at 2.5%'])
def test_retained_aluminum_refused_without_network(prompt):
    history = [{'role': 'user', 'content': '480V 14A 1200 ft aluminum conductors; voltage drop?'}]
    assert is_voltage_drop_question(prompt, history)
    def no_network(*a, **k):
        pytest.fail('Unsupported material reached the service')
    reply = voltage_drop_reply(history, prompt, opener=no_network)
    assert 'Aluminum conductor calculations are not currently supported' in reply['reply']
    assert 'electrical_result' not in reply and 'tool_action' not in reply
    assert tool_form_reply('voltage-drop', history, prompt)['error'] == 'unsupported_material'


def test_support_material_not_conductor_material_and_edits_retained():
    values = retained_circuit([], '480V 14A 1200ft copper cable in aluminum conduit')
    assert values['material'] == 'copper' and values['conduit_type'] == 'aluminum'
    values = retained_circuit([], '480V 14A 1200ft in aluminum ladder tray')
    assert 'material' not in values
    history = [{'role': 'user', 'calculator_inputs': dict(voltage=480, amps=14, length_ft=1200, material='aluminum')}]
    assert retained_circuit(history, 'Use copper instead')['material'] == 'copper'
    assert retained_circuit(history, 'Change conductor material to silver')['material'] == 'silver'


@pytest.mark.parametrize('material', [None, {}, '', 'silver'])
def test_malformed_retained_material_does_not_default(material):
    history = [{'role': 'user', 'calculator_inputs': dict(voltage=480, amps=14, length_ft=1200, material=material)}]
    reply = voltage_drop_reply(history, 'Re-run at 2%', opener=lambda *a, **k: pytest.fail('Unexpected service request'))
    assert reply['error'] == 'unsupported_material'


def response_for(data):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return json.dumps(data).encode()
    return Response()


def test_narrative_uses_service_normalized_values_not_request_assumptions():
    payload = adapter.normalize_result(dict(status='ok', inputs=dict(
        voltage=240, phase=1, fla=20, length_ft=200, conduit_type='steel'),
        result=dict(solution_found=True, selected_size='4', vd_threshold_pct=2,
                    voltage_drop_pct=1, voltage_drop_volts=2.4), assumptions=['Service assumption']),
        {'material': 'copper'}, None)
    reply = voltage_drop_reply([], '480V 14A 1200ft voltage drop in PVC conduit?',
                               opener=lambda *a, **k: response_for(payload))
    text = reply['reply']
    assert '240 V, 1-phase' in text and '200 ft' in text and '20 A' in text
    assert 'steel' in text and 'PVC' not in text and 'copper' in text
    assert 'accepted 2%' in text and 'Service assumption' in text
    assert reply['electrical_inputs']['conduit_type'] == 'steel'
    payload['calculation']['material'] = 'aluminum'
    failed = voltage_drop_reply([], '480V 14A 1200ft voltage drop?', opener=lambda *a, **k: response_for(payload))
    assert 'electrical_result' not in failed
    assert 'no heavy agent or substitute estimate' in failed['reply']


@pytest.fixture
def offline_service(monkeypatch):
    """Optional real-source integration, explicitly supplied; never start server."""
    source = os.environ.get('SMEDLEY_OFFLINE_SERVICE_SOURCE')
    if not source:
        pytest.skip('Set SMEDLEY_OFFLINE_SERVICE_SOURCE for offline source integration')
    source = Path(source)
    monkeypatch.setitem(sys.modules, 'smedley_cable_tray', adapter)
    monkeypatch.syspath_prepend(str(source.parent))
    return runpy.run_path(str(source), run_name='offline_contract_test')


@pytest.mark.parametrize('material', ['copper', ' COPPER ', None])
@pytest.mark.parametrize('cable', ['individual', 'tc_er'])
def test_real_calculator_offline_copper_and_omitted(offline_service, material, cable):
    params = dict(voltage=480, phase=3, amps=14, length_ft=1200, conduit_type='steel',
                  target_vd_pct=2.5, cable_construction=cable)
    if material is not None:
        params['material'] = material
    result = offline_service['calculate_with_installation']('/tools/conductor-sets', params)
    assert result['status'] == 'ok' and result['result']['solution_found']
    normalized = result['calculation']
    assert normalized['material'] == 'copper'
    assert all(value is not None for value in normalized.values())
    assert normalized['conduit_type'] == 'steel' and normalized['target_vd_pct'] == 2.5
    reply = voltage_drop_reply([], '480V 14A 1200ft voltage drop?', opener=lambda *a, **k: response_for(result))
    assert 'electrical_result' in reply


def test_real_dispatch_all_api_tools_reject_before_calculation(offline_service):
    for tool in offline_service['TOOL_HANDLERS']:
        result = offline_service['calculate_with_installation'](tool, {'material': 'aluminum'})
        assert result['status'] == 'error' and 'Aluminum conductor' in result['error']


@pytest.mark.parametrize('material', ['aluminum', None, [], 'silver'])
def test_http_handler_rejects_unsupported_material_without_server(offline_service, material):
    handler = object.__new__(offline_service['ToolsHandler'])
    body = json.dumps({'material': material}).encode()
    handler.path = '/tools/voltage-drop'
    handler.headers = {'Content-Length': str(len(body))}
    handler.rfile = BytesIO(body)
    sent = []
    handler._send = lambda code, payload: sent.append((code, payload))
    handler.do_POST()
    assert sent[0][0] == 400 and sent[0][1]['status'] == 'error'
    assert not sent[0][1].get('result')


@pytest.mark.parametrize('tool', ['voltage-drop', 'feeder-size', 'conductor-sets'])
def test_real_raceway_entry_points_report_accepted_material(offline_service, tool):
    result = offline_service['calculate_with_installation']('/tools/' + tool, dict(
        voltage=480, phase=3, amps=14, length_ft=1200, conduit_type='aluminum', conductor_awg='4'))
    assert result['status'] == 'ok'
    assert result['inputs']['material'] == 'copper'
    assert result['calculation']['conduit_type'] == 'aluminum'
    assert result['calculation']['material'] == 'copper'
