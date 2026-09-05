import json
import subprocess
from pathlib import Path

from api.biggy_project_review_runtime import build_review_agent_context_messages
from api.project_review_electrical import retained_circuit, voltage_drop_reply, is_voltage_drop_question, requested_tool, tool_form_reply, TOOL_LABELS
from tests.js_source_extract import extract_function


def test_wrapped_owner_question_survives_context_cleanup():
    question = '480V 10HP motor 1200 ft away. TC-ER cable size and voltage drop?'
    messages = [{'role': 'user', 'content': 'Project-review context for this reply (CANONICAL):\nSTALE PATH\nOwner message: ' + question},
                {'role': 'assistant', 'content': 'Prior response.'}]
    clean = build_review_agent_context_messages(messages)
    assert any(row['content'] == question for row in clean)
    assert 'STALE PATH' not in json.dumps(clean)
    assert 'STALE PATH' in messages[0]['content']  # Durable transcript untouched.


def test_followup_keeps_owner_inputs_not_assistant_guesses():
    messages = [
        {'role': 'user', 'content': 'Owner message: 480V 10HP motor 1,200 feet away using TC-ER; what cable size and voltage drop?'},
        {'role': 'assistant', 'content': '4800V 100HP 19,000 feet. Trust me.'},
    ]
    values = retained_circuit(messages, 'Re-run that shooting for 2% VD')
    assert values == dict(voltage=480, hp=10, length_ft=1200, cable_construction='tc_er', target_vd_pct=2)
    assert is_voltage_drop_question('Re-run that shooting for 2% VD')
    assert not is_voltage_drop_question('Do not calculate 2% VD now')
    assert is_voltage_drop_question('Re-run to stay below 2.5%', messages)
    assert not is_voltage_drop_question('Re-run to stay below 2.5%', [])


def test_all_named_tools_open_with_owner_parameters_and_default():
    history = [{'role':'user','content':'480V 10HP motor 1200 ft TC-ER'}]
    for tool, label in TOOL_LABELS.items():
        assert requested_tool('Open the ' + label + ' tool') == tool
        result = tool_form_reply(tool, history, 'Open the ' + label + ' tool')
        assert result['tool_action']['id'] == tool
        assert result['tool_action']['params']['target_vd_pct'] == 2.5
        assert result['tool_action']['params']['length_ft'] == 1200
    assert requested_tool('Do not open the Voltage Drop tool') is None


def test_new_circuit_does_not_borrow_old_distance():
    values = retained_circuit([{'role':'user','content':'480V 10HP motor 1200 ft TC-ER'}], 'New circuit: 240V 5HP. What cable size?')
    assert 'length_ft' not in values


def test_tool_edits_survive_followup_and_explicit_target_wins():
    history = [{'role':'user','content':'480V 10HP motor 1200 ft TC-ER'},
               {'role':'user','content':'Calculator parameters updated', 'calculator_inputs': {'amps':15,'length_ft':900,'target_vd_pct':2.5,'tray_cover':'solid','covered_length_ft':20}}]
    values = retained_circuit(history, 'Try 2% VD')
    assert values['amps'] == 15 and values['length_ft'] == 900
    assert values['target_vd_pct'] == 2 and values['tray_cover'] == 'solid'
    assert 'hp' not in values


def test_bounded_tool_request_and_no_model_math():
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self):
            from api.smedley_cable_tray import normalize_result
            return json.dumps(normalize_result({'status':'ok','inputs':{'fla':14,'voltage':480,'phase':3,'length_ft':1200,'conduit_type':'pvc'},'result':{'solution_found':True,'selected_size':'4','voltage_drop_volts':8.4,'voltage_drop_pct':1.75,'vd_threshold_pct':2}}, {'material':'copper'}, None)).encode()
    captured = []
    def opener(req, timeout):
        assert timeout == 8
        captured.append(json.loads(req.data))
        return Response()
    result = voltage_drop_reply([{'role':'user','content':'480V 10HP motor 1200 ft TC-ER'}], 'Re-run at 2% VD', opener=opener)
    assert len(captured) == 1
    assert captured[0]['target_vd_pct'] == 2
    assert captured[0]['length_ft'] == 1200
    assert '4 AWG' in result['reply'] and 'provisional' in result['reply']
    assert result['tool_action']['id'] == 'voltage-drop'
    assert result['tool_action']['params']['amps'] == 14


def test_dictation_local_only_append_and_cancel_on_late_permission():
    src = (Path(__file__).resolve().parents[1] / 'static/biggy-brand.js').read_text()
    helper = extract_function(src, 'createReviewDictation')
    js = helper + r'''
const assert = require('assert');
global.window = {};
let acquire, stopped = 0, fetches = 0;
const tracks = {getTracks:()=>[{stop:()=>stopped++}]};
Object.defineProperty(global, 'navigator', {value:{mediaDevices:{getUserMedia:()=>new Promise(resolve=>acquire=resolve)}},configurable:true});
global.MediaRecorder = class {
  static isTypeSupported(){return true}
  constructor(){global.capture=this;this.state='inactive';this.mimeType='audio/webm'}
  start(){this.state='recording'}
  stop(){this.state='inactive'; this.ondataavailable({data:new Blob(['test'])}); this.onstop()}
};
const button = {classList:{toggle(){}},setAttribute(){},addEventListener(){}};
const input = {value:'Typed draft',maxLength:8000,dispatchEvent(){},focus(){}};
const status = {};
let project = 'a';
const gate = createReviewDictation({input,button,status,projectId:()=>project,visible:()=>true});
global.fetch = async (url,opts)=>{fetches++;assert.equal(url,'/api/transcribe');assert.equal(opts.body.get('local_only'),'true');return {ok:true,json:async()=>({transcript:'spoken words'})}};
(async()=>{
  let work = gate.toggle(); gate.cancel(); acquire(tracks); await work;
  assert.equal(stopped,1);assert.equal(fetches,0);assert.equal(input.value,'Typed draft');
  work = gate.toggle(); acquire(tracks); await work;
  assert.equal(button.textContent,'STOP DICTATION');
  await gate.toggle(); await new Promise(resolve=>setTimeout(resolve,5));
  assert.equal(input.value,'Typed draft spoken words');assert.equal(fetches,1);
  work=gate.toggle();acquire(tracks);await work;project='b';gate.cancel();
  assert.equal(fetches,1);assert.equal(input.value,'Typed draft spoken words');
})().catch(e=>{console.error(e);process.exit(1)});
'''
    subprocess.run(['node','-e',js],check=True,capture_output=True,text=True,timeout=10)
