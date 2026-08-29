(() => {
  'use strict';
  if (window.BiggyElectricalTools) return;

  const PROXY = '/api/extensions/smedley-engineering/sidecar';
  const CONDUCTORS = ['14','12','10','8','6','4','3','2','1','1/0','2/0','3/0','4/0','250','300','350','400','500','600','750','1000'];
  const FIELDS = Object.freeze({
    'voltage-drop': [['voltage','System voltage (V)','number','480'],['phase','Phase','select','3|1'],['amps','Load amps','number',''],['length_ft','One-way length (ft)','number',''],['material','Conductor material','select','copper'],['temp_rating','Temp / terminal basis (C)','select','75|90|60'],['conduit_type','Conduit type','select','steel|aluminum|pvc'],['circuit_type','Circuit type','select','feeder|branch'],['continuous_load','Continuous load','select','true|false'],['parallel_sets','Parallel sets','number','1'],['power_factor','Power factor','number','0.85'],['ambient_temp_c','Ambient temp (C)','number','30'],['num_conductors','Current-carrying conductors','number','3']],
    'feeder-size': [['voltage','System voltage (V)','number','480'],['phase','Phase','select','3|1'],['circuit_type','Circuit type','select','feeder|branch'],['length_ft','One-way length (ft)','number',''],['_fla_src','FLA source','select','amps|nameplate_fla|hp'],['_fla_val','FLA / HP value','number',''],['conduit_type','Conduit type','select','steel|aluminum|pvc'],['parallel_sets','Parallel sets','number','1'],['ambient_temp_c','Ambient temp (C)','number','30'],['num_conductors','Current-carrying conductors','number','3'],['temp_rating','Temp rating (C)','select','75|90|60']],
    'conductor-sets': [['voltage','System voltage (V)','number','480'],['phase','Phase','select','3|1'],['circuit_type','Circuit type','select','feeder|branch'],['length_ft','One-way length (ft)','number',''],['_fla_src','FLA source','select','amps|nameplate_fla|hp'],['_fla_val','FLA / HP value','number',''],['conduit_type','Conduit type','select','steel|aluminum|pvc'],['ambient_temp_c','Ambient temp (C)','number','30']],
    'ocpd-size': [['amps','Calculated amps','number',''],['circuit_type','Circuit type','select','feeder|branch'],['note','Basis / note','text','']],
    'conduit-fill': [['conduit_type','Conduit type','select','emt|imc|rmc|pvc_40|pvc_80'],['conductor_size','Conductor size','select',CONDUCTORS.join('|')],['num_current_carrying','Current-carrying conductors','number','3'],['ocpd_amps','OCPD rating for EGC','number',''],['trade_size','Check trade size (optional)','text','']],
    'grounding': [['mode','Mode','select','both|egc|gec'],['ocpd_amps','OCPD amps (EGC)','number',''],['service_conductor_size','Service conductor (GEC)','select',CONDUCTORS.join('|')],['circuit_conductor_size','Circuit conductor (EGC cap)','select','|'+CONDUCTORS.join('|')],['parallel_sets','Parallel sets','number','1']],
    'cable-tray-fill': [['tray_depth_in','Tray depth (in)','select','4|3|6'],['cable_type','Cable type','select','mc_4/0_plus|mc_smaller_4/0|sc_1000_plus|sc_250_to_1000|sc_1/0_to_4/0|control_signal|over_2000v'],['tray_style','Tray style','select','ladder|solid_bottom|vented_channel'],['check_width_in','Check width (optional)','number',''],['cables','Cables JSON','textarea','[{"cable_designation":"3C-10","count":3}]']],
    'motor-circuit': [['voltage','System voltage (V)','number','480'],['phase','Phase','select','3|1'],['length_ft','One-way length (ft)','number',''],['_fla_src','FLA source','select','hp|nameplate_fla|amps'],['_fla_val','HP / FLA value','number',''],['ocpd_type','OCPD type','select','itcb|tdf|itf|nfb'],['motor_type','Motor type','select','design_b|design_c|design_d|wound_rotor'],['conduit_type','Conduit type','select','steel|aluminum|pvc'],['service_factor','Service factor','number','1.15']],
    'motor-starter': [['voltage','System voltage (V)','number','480'],['phase','Phase','select','3|1'],['_fla_src','FLA source','select','hp|nameplate_fla|amps'],['_fla_val','HP / FLA value','number',''],['starter_type','Starter type','select','e300|e100|nema'],['circuit_type','Circuit type','select','fvnr|fvr'],['comms_type','Comms','select','enet|hardwired'],['control_voltage','Control voltage','select','120v|24v']],
    'mcc-bucket': [['voltage','System voltage (V)','number','480'],['phase','Phase','select','3|1'],['_fla_src','FLA source','select','hp|nameplate_fla|amps'],['_fla_val','FLA / HP value','number',''],['starter_type','Starter type','select','e300|e100|nema'],['circuit_type','Circuit type','select','fvnr|fvr|vfd'],['control_voltage','Control voltage','select','120v|24v'],['cable_entry','Cable entry','select','top|bottom'],['comms_type','Comms','select','enet|hardwired'],['include_cpt','Include CPT','select','true|false']],
    'vfd-circuit': [['voltage','System voltage (V)','number','480'],['phase','Phase','select','3|1'],['_fla_src','FLA source','select','hp|nameplate_fla|amps'],['_fla_val','HP / FLA value','number',''],['drive_input_fla','Drive input FLA','number',''],['length_ft','Output cable length (ft)','number','50'],['conduit_type','Conduit type','select','steel|aluminum|pvc'],['has_bypass','Bypass contactor','select','false|true'],['drive_model','Drive model','select','generic|pf700|pf525|pf755']],
  });
  const OPTIONAL = new Set(['note','trade_size','check_width_in','circuit_conductor_size','drive_input_fla','ocpd_amps']);
  const NUMBER_RULES = Object.freeze({
    parallel_sets:{min:'1',step:'1'},num_conductors:{min:'1',step:'1'},num_current_carrying:{min:'1',step:'1'},
    power_factor:{min:'0',max:'1',step:'any'},voltage:{min:'0',step:'any'},amps:{min:'0',step:'any'},
    length_ft:{min:'0',step:'any'},_fla_val:{min:'0',step:'any'},ocpd_amps:{min:'0',step:'any'},
    service_factor:{min:'0',step:'any'},drive_input_fla:{min:'0',step:'any'},check_width_in:{min:'0',step:'any'},ambient_temp_c:{step:'any'},
  });
  let activeClose = null;

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const node = (tag, className, html) => { const item=document.createElement(tag); if(className)item.className=className;if(html!==undefined)item.innerHTML=html;return item; };
  async function request(path, options={}) {
    const url = `${PROXY}${path}`;
    if (typeof window.api === 'function') return window.api(url, options);
    const response = await fetch(url, {...options, cache:'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${(await response.text()).slice(0,300)}`);
    return response.json();
  }
  function controlFor([name,label,type,initial]) {
    const wrapper=node('label'); const caption=node('span'); caption.textContent=label; wrapper.appendChild(caption);
    let control;
    if(type==='select') { control=node('select'); String(initial).split('|').forEach((value)=>{const option=node('option');option.value=value;option.textContent=value||'—';control.appendChild(option);}); }
    else if(type==='textarea') { control=node('textarea');control.rows=4;control.value=initial; }
    else { control=node('input');control.type=type;control.value=initial;if(type==='number'){control.inputMode='decimal';const rule=NUMBER_RULES[name]||{};control.step=rule.step||'any';if(rule.min!=null)control.min=rule.min;if(rule.max!=null)control.max=rule.max;} }
    control.name=name;
    if((type==='number'||type==='text'||type==='textarea')&&String(initial??'')===''&&!OPTIONAL.has(name))control.required=true;
    if(name==='cables')control.required=true;
    wrapper.appendChild(control);return wrapper;
  }
  function valueFor(control) {
    if(control.value==='')return undefined;
    if(control.name==='cables')return JSON.parse(control.value);
    if(control.type==='number')return Number(control.value);
    if(control.value==='true')return true;if(control.value==='false')return false;
    return control.value;
  }
  function renderResult(target, toolId, payload) {
    const renderer=window.SmedleyElectricalResults;
    target.innerHTML=renderer&&typeof renderer.renderResultCard==='function'
      ? renderer.renderResultCard(toolId,payload)
      : `<pre>${esc(JSON.stringify(payload,null,2))}</pre>`;
  }

  function open({mount, toolId, label, onClose}) {
    if(!mount||!FIELDS[toolId])throw new Error(`Unknown electrical tool: ${toolId}`);
    if(activeClose)activeClose();
    mount.replaceChildren();
    const shell=node('section','biggy-electrical-tool');
    const body=node('div','smedley-engineering-tool-body');
    const form=node('form','smedley-engineering-form');
    const result=node('div','smedley-engineering-result','<div class="smedley-engineering-result-empty">Enter parameters — results update live.</div>');
    FIELDS[toolId].forEach((field)=>form.appendChild(controlFor(field)));
    const run=node('button','smedley-engineering-primary');run.type='button';run.textContent='RECALCULATE';form.appendChild(run);
    body.append(form,result);shell.appendChild(body);mount.appendChild(shell);
    let live=null;let closed=false;let baseline=null;let compareSequence=0;
    const close=()=>{if(closed)return;closed=true;if(live&&typeof live.dispose==='function')live.dispose();if(activeClose===close)activeClose=null;mount.replaceChildren();if(typeof onClose==='function')onClose();};
    activeClose=close;
    const collect=()=>{const params={};form.querySelectorAll('input,select,textarea').forEach((control)=>{const value=valueFor(control);if(value!==undefined)params[control.name]=value;});if(params._fla_src&&params._fla_val!==undefined){params[params._fla_src]=params._fla_val;delete params._fla_src;delete params._fla_val;}return params;};
    const calculate=async(params)=>{
      if(toolId==='voltage-drop'){
        const sizing=window.SmedleyVoltageDropSizing;
        if(!sizing||typeof sizing.calculate!=='function')throw new Error('Voltage drop auto-sizing helper is not loaded.');
        return sizing.calculate(params,(path,toolParams)=>request(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(toolParams)}));
      }
      return request(`/tools/${toolId}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(params)});
    };
    const requestDrop=(params,size)=>request('/tools/voltage-drop',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({voltage:Number(params.voltage),phase:Number(params.phase),amps:Number(params.amps),length_ft:Number(params.length_ft),conductor_awg:String(size),conduit_type:String(params.conduit_type||'').toLowerCase(),circuit_type:String(params.circuit_type||'').toLowerCase(),parallel_sets:Number(params.parallel_sets||1),...(params.power_factor!==undefined?{power_factor:Number(params.power_factor)}:{})})});
    const addComparison=(data)=>{
      if(toolId!=='voltage-drop'||!baseline?.result)return;
      const sizes=Array.isArray(window.SmedleyVoltageDropSizing?.CONDUCTORS)?window.SmedleyVoltageDropSizing.CONDUCTORS:[];
      const recommended=String(baseline.result.recommended_size||'');const current=String(data?.result?.comparison_size||recommended);const index=sizes.indexOf(current);
      const floor=baseline.result.parallel_minimum_awg;const floorIndex=floor?sizes.indexOf(String(floor)):0;if(!sizes.length||index<0)return;
      const controls=node('div','smedley-conductor-compare');
      const smaller=node('button','smedley-conductor-compare-step');smaller.type='button';smaller.textContent='◀ SMALLER';smaller.disabled=index<=Math.max(0,floorIndex);
      const status=node('div','smedley-conductor-compare-status',`<span>CONDUCTOR COMPARISON</span><strong>${esc(current)} AWG</strong><small>RECOMMENDED ${esc(recommended)} AWG</small>`);
      const reset=node('button','smedley-conductor-compare-reset');reset.type='button';reset.textContent='RECOMMENDED';reset.disabled=current===recommended;
      const larger=node('button','smedley-conductor-compare-step');larger.type='button';larger.textContent='LARGER ▶';larger.disabled=index>=sizes.length-1;
      controls.append(smaller,status,reset,larger);result.prepend(controls);
      const compare=async(next)=>{if(!next||!baseline?.result)return;const requestId=++compareSequence;controls.querySelectorAll('button').forEach((button)=>{button.disabled=true;});status.querySelector('small').textContent=`CHECKING ${next} AWG…`;try{const params=collect();const drop=await requestDrop(params,next);if(requestId!==compareSequence)return;if(!drop||drop.status!=='ok'||!drop.result)throw new Error(drop?.error||`Voltage-drop comparison failed for ${next} AWG.`);const minimum=String(baseline.result.minimum_ampacity_size||recommended);const ampacityPass=sizes.indexOf(next)>=sizes.indexOf(minimum);const dropPass=String(drop.result.pass_fail||'').toUpperCase()==='PASS';const comparison={...drop,inputs:{...(drop.inputs||{}),...params,conductor_awg:next},result:{...drop.result,conductor_awg:next,comparison_size:next,baseline_recommended_size:recommended,recommended_size:recommended,minimum_ampacity_size:baseline.result.minimum_ampacity_size,minimum_voltage_drop_size:baseline.result.minimum_voltage_drop_size,parallel_minimum_awg:baseline.result.parallel_minimum_awg,governing_constraint:baseline.result.governing_constraint,governing_explanation:baseline.result.governing_explanation,design_amps:baseline.result.design_amps,derated_ampacity_A:baseline.result.derated_ampacity_A,ampacity_pass_fail:ampacityPass?'PASS':'FAIL',voltage_drop_pass_fail:dropPass?'PASS':'FAIL',pass_fail:ampacityPass&&dropPass?'PASS':'FAIL'},assumptions:Array.from(new Set([...(drop.assumptions||[]),`ElectriCalc comparison: ${next} AWG trial against automatic ${recommended} AWG recommendation.`])),warnings:Array.from(new Set([...(ampacityPass?[]:[`Trial ${next} AWG is below minimum ampacity/code size ${minimum} AWG.`]),...(drop.warnings||[])])),code_basis:Array.from(new Set([baseline.code_basis,drop.code_basis].filter(Boolean))).join(' | ')};success(comparison,{preserveBaseline:true});}catch(error){failure(error);}};
      smaller.addEventListener('click',()=>compare(sizes[index-1]));larger.addEventListener('click',()=>compare(sizes[index+1]));reset.addEventListener('click',()=>compare(recommended));
    };
    const success=(data,options={})=>{if(toolId==='voltage-drop'&&data?.status==='ok'&&!options.preserveBaseline){baseline=data;compareSequence+=1;}renderResult(result,toolId,data);addComparison(data);};
    const failure=(error)=>renderResult(result,toolId,{status:'error',error:String(error.message||error)});
    const validateExtra=(controls)=>{const byName=Object.fromEntries(controls.map((control)=>[control.name,control]));const errors={};if(toolId==='grounding'){const mode=String(byName.mode?.value||'both');if((mode==='egc'||mode==='both')&&!String(byName.ocpd_amps?.value||'').trim())errors.ocpd_amps='OCPD amps (EGC) is required for this mode.';if((mode==='gec'||mode==='both')&&!String(byName.service_conductor_size?.value||'').trim())errors.service_conductor_size='Service conductor (GEC) is required for this mode.';}if(byName._fla_src&&byName._fla_val&&!String(byName._fla_val.value||'').trim())errors._fla_val='FLA / HP value is required.';return errors;};
    form.addEventListener('submit',(event)=>{event.preventDefault();if(live&&typeof live.calculateNow==='function')live.calculateNow();});
    form.addEventListener('input',()=>{compareSequence+=1;});form.addEventListener('change',()=>{compareSequence+=1;});
    const liveApi=window.SmedleyLiveTools;
    if(liveApi&&typeof liveApi.wire==='function'){
      live=liveApi.wire({form,result,run,collectParams:collect,calculate,renderSuccess:success,renderError:failure,validateExtra});
      const first=form.querySelector('input[required],textarea[required]');if(first&&typeof first.focus==='function')first.focus();
      const initial=liveApi.validateForm(form,validateExtra);if(initial.valid)live.calculateNow();
    }else{
      run.textContent='CALCULATE';run.addEventListener('click',async(event)=>{event.preventDefault();run.disabled=true;run.textContent='CALCULATING…';try{success(await calculate(collect()));}catch(error){failure(error);}finally{run.disabled=false;run.textContent='CALCULATE';}});
    }
    return {close,toolId,label};
  }

  window.BiggyElectricalTools=Object.freeze({open,close:()=>{if(activeClose)activeClose();},fields:FIELDS});
})();
