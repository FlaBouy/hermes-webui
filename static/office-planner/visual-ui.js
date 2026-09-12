import {openPhoneScreen} from './phone-screen.js?v=20260910-8';
import {dayKey} from './model.js';
import {LINE_H, layoutFlowchart, pickLatestPlan, wrapTitleLines} from './visual-chart.js?v=whiteboard-20260911';
const el=(tag,text='')=>{const n=document.createElement(tag);n.textContent=text;return n;};
const field=(label,value='',tag='input')=>{const wrap=el('label',label),input=el(tag);input.value=value;wrap.append(input);return {wrap,input};};
async function api(path,body){const r=await fetch('/api/biggy/pa/'+path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Hermes-CSRF-Token':window.parent.__HERMES_CONFIG__?.csrfToken||''},body:JSON.stringify(body)}:{});const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d;}
function button(label,fn,status){const b=el('button',label);b.onclick=async()=>{b.disabled=true;try{await fn();}catch(e){status.textContent=e.message;}finally{b.disabled=false;}};return b;}
const sample=()=>({title:'Project delivery',start:dayKey(new Date()),assumptions:['Example only. Durations use calendar days; review resource availability.'],tasks:[{id:'scope',title:'Confirm scope',days:2,depends:[],source:''},{id:'design',title:'Prepare design',days:3,depends:['scope'],source:''},{id:'review',title:'Review and approve',days:1,depends:['design'],source:''},{id:'delivery',title:'Delivery milestone',days:0,depends:['review'],source:''}]});
function download(value,name,type='application/json'){const u=URL.createObjectURL(new Blob([typeof value==='string'?value:JSON.stringify(value,null,2)],{type}));const a=el('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}

const ACTIVE_PLAN_KEY='argus.visual-plan.active.v1';

export {layoutFlowchart, pickLatestPlan, wrapTitleLines};

function chart(plan,kind){
 const ns='http://www.w3.org/2000/svg';
 const svg=document.createElementNS(ns,'svg');
 const add=(tag,attrs,text)=>{const n=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!=null)n.textContent=text;svg.append(n);return n;};
 svg.setAttribute('role','img');
 svg.setAttribute('aria-label',`${kind} for ${plan.title}`);
 svg.classList.add('visual-plan-chart');

 if(kind==='Gantt'){
  const height=plan.tasks.length*66+45;
  svg.setAttribute('viewBox',`0 0 850 ${height}`);
  svg.style.width='100%';svg.style.minWidth='0';svg.style.height='auto';
  const width=480/Math.max(plan.duration,1);
  const positions=new Map(plan.tasks.map((r,i)=>[r.id,{x:300+r.start_day*width,y:i*66+34}]));
  for(const r of plan.tasks){
   const p=positions.get(r.id);
   add('text',{x:8,y:p.y+4,fill:'#e1f0f3','font-size':13},`${r.id} · ${r.title}`);
   if(r.days===0)add('path',{d:`M ${p.x} ${p.y-7} l 7 7 l -7 7 l -7 -7 Z`,fill:'#efc472'});
   else add('rect',{x:p.x,y:p.y-10,width:Math.max(3,r.days*width),height:20,rx:4,fill:'#55a99d'});
   add('text',{x:300,y:p.y+27,fill:'#a9c2cb','font-size':11},`${r.start_date} → ${r.finish_date} · ${r.days?r.days+' days':'milestone'}`);
  }
  return svg;
 }

 const {positions,width,height}=layoutFlowchart(plan);
 svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
 svg.setAttribute('preserveAspectRatio','xMidYMid meet');
 svg.style.width='100%';svg.style.height='100%';svg.style.minWidth='0';svg.style.display='block';

 for(const r of plan.tasks){
  for(const dep of r.depends){
   const a=positions.get(dep),b=positions.get(r.id);if(!a||!b)continue;
   const x1=a.x+a.w,y1=a.y+a.h/2,x2=b.x,y2=b.y+b.h/2;
   const mid=x1+(x2-x1)/2;
   add('path',{d:`M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`,fill:'none',stroke:'#789aa8','stroke-width':1.8});
   add('polygon',{points:`${x2},${y2} ${x2-8},${y2-5} ${x2-8},${y2+5}`,fill:'#92dfd5'});
  }
 }
 for(const r of plan.tasks){
  const p=positions.get(r.id);if(!p)continue;
  const rounded=kind==='Flowchart'?14:4;
  add('rect',{x:p.x,y:p.y,width:p.w,height:p.h,rx:rounded,fill:'#173c45',stroke:'#8bd6cd','stroke-width':1.5});
  add('text',{x:p.x+10,y:p.y+16,fill:'#8fc6cb','font-size':11,'font-family':'ui-monospace,SFMono-Regular,Menlo,monospace'},r.id);
  p.lines.forEach((line,i)=>add('text',{x:p.x+10,y:p.y+34+i*LINE_H,fill:'#e1f0f3','font-size':13},line));
 }
 return svg;
}

function rememberActive(plan,saved){
 try{
  localStorage.setItem(ACTIVE_PLAN_KEY,JSON.stringify({
   savedAt:Date.now(),
   savedId:saved?.id||plan?.id||null,
   version:saved?.version||plan?.version||null,
   plan,
  }));
 }catch{/* ignore quota / private mode */}
}

function readActive(){
 try{
  const raw=localStorage.getItem(ACTIVE_PLAN_KEY);if(!raw)return null;
  const data=JSON.parse(raw);return data?.plan&&Array.isArray(data.plan.tasks)?data:null;
 }catch{return null;}
}

export function mountVisual({edit,reviewId='',getTasks=()=>[],workspace=false}={}){
 const root=document.getElementById('visual-workspace');if(!root)return;
 const status=el('p');status.setAttribute('role','status');
 const prompt=field('Describe a plan or request a revision','','textarea');
 const title=field('Plan title'),start=field('Start date'),assumptions=field('Assumptions · one per line','','textarea');
 start.input.type='date';prompt.input.rows=3;prompt.input.maxLength=6000;
 const actions=el('div'),rows=el('div'),output=el('div'),choices=el('div'),history=el('select'),view=el('select');
 const board=el('div');board.className='visual-board';board.setAttribute('data-testid','visual-board');
 const boardStage=el('div');boardStage.className='visual-board-stage';
 const toolbar=el('div');toolbar.className='visual-board-toolbar';
 output.className='visual-board-output';
 let plan=null,saved=null,busy=false,scale=1,editOpen=!workspace;

 const kinds=workspace?['Flowchart','Dependencies']:['Flowchart','Dependencies','Gantt'];
 for(const k of kinds)view.append(new Option(k,k));
 view.value='Flowchart';

 const read=()=>{if(!plan)throw Error('Create or load a plan first');return {...plan,title:title.input.value,start:start.input.value,assumptions:assumptions.input.value.split('\n').filter(Boolean),review_project_id:reviewId,tasks:[...rows.children].map(row=>({id:row.querySelector('[name=id]').value,title:row.querySelector('[name=title]').value,days:Number(row.querySelector('[name=days]').value),depends:row.querySelector('[name=depends]').value.split(',').map(s=>s.trim()).filter(Boolean),source:row.querySelector('[name=source]').value}))};};

 function applyScale(){
  const svg=output.querySelector('svg');if(!svg)return;
  svg.style.transformOrigin='top left';
  svg.style.transform=scale===1?'none':`scale(${scale})`;
 }

 function fitBoard(){
  const svg=output.querySelector('svg');if(!svg)return;
  const vb=(svg.getAttribute('viewBox')||'0 0 720 280').split(/\s+/).map(Number);
  const [, , vw, vh]=vb;
  const rect=boardStage.getBoundingClientRect();
  if(!vw||!vh||!rect.width||!rect.height){scale=1;applyScale();return;}
  scale=Math.max(0.45,Math.min(1.35,Math.min((rect.width-16)/vw,(rect.height-16)/vh)));
  applyScale();
  status.textContent=status.textContent||`Fit · ${Math.round(scale*100)}%`;
 }

 function render(p){
  output.replaceChildren(chart(p,view.value));
  applyScale();
  choices.replaceChildren(el('p',`Validate → review assumptions → save revision → review individual planner tasks. ${p.duration} calendar days. No resource or holiday leveling.`));
  for(const task of p.tasks)choices.append(button('Review task: '+task.title,()=>edit({title:task.title,due:task.finish_date,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,estimate:30,project:p.title,review_project_id:reviewId,status:'open',priority:'normal',recurrence:'none',source:task.source||`Visual plan ${saved?.id||'unsaved draft'} / ${task.id}`,notes:`Proposed interval ${task.start_date} to ${task.finish_date}. Dependencies: ${task.depends.join(', ')||'none'}. Effort estimate needs review.`}),status));
  if(workspace)requestAnimationFrame(fitBoard);
 }

 function show(p){
  plan=p;title.input.value=p.title;start.input.value=p.start;assumptions.input.value=(p.assumptions||[]).join('\n');
  rows.replaceChildren();
  for(const task of p.tasks){
   const row=el('details');row.append(el('summary',task.id+' · '+task.title));
   for(const [name,label]of [['id','Step ID'],['title','Step'],['days','Calendar days · 0 = milestone'],['depends','Depends on · comma-separated IDs'],['source','Source / reference']]){
    const f=field(label,Array.isArray(task[name])?task[name].join(', '):task[name]??'');
    f.input.name=name;if(name==='days'){f.input.type='number';f.input.min=0;f.input.max=365;}
    row.append(f.wrap);
   }
   row.append(button('Remove step',()=>{row.remove();output.replaceChildren();},status));
   rows.append(row);
  }
  rememberActive(p,saved);
  render(p);
 }

 const checked=async()=>{const d=await api('visual-plans',{action:'validate',plan:read()});show(d.plan);return d.plan;};

 function syncHistory(plans){
  history.replaceChildren(new Option('Choose revision',''));
  for(const p of plans.filter(p=>!reviewId||p.review_project_id===reviewId)){
   history.append(new Option(`${p.title} · revision ${p.version}`,JSON.stringify(p)));
  }
 }

 async function loadRevisions(){
  const data=await api('visual-plans');
  syncHistory(data.plans||[]);
  status.textContent='Saved revisions loaded.';
  return data.plans||[];
 }

 const formBlock=el('div');formBlock.className='visual-form-block';
 const editorToggle=button(workspace?'Edit plan':'Hide editor',()=>{
  editOpen=!editOpen;formBlock.hidden=!editOpen;
  editorToggle.textContent=editOpen?'Hide editor':'Edit plan';
 },status);

 toolbar.append(
  el('label','Plan'),history,
  button('Load revisions',loadRevisions,status),
  ...(workspace?[]:[button('View',()=>{
   if(plan)rememberActive(plan,saved);
   else if(history.value){
    try{const p=JSON.parse(history.value);saved=p;show(p);rememberActive(p,saved);}
    catch(e){status.textContent=e.message;return;}
   }else{status.textContent='Load or select a revision first.';return;}
   try{window.parent.postMessage({type:'argus-open-visual-whiteboard'},location.origin);}
   catch(e){status.textContent=e.message||'Could not open Visual Planner.';}
  },status)]),
  el('label','Diagram type'),view,
  button('Fit',()=>{fitBoard();status.textContent=`Fit · ${Math.round(scale*100)}%`;},status),
  button('Zoom +',()=>{scale=Math.min(2,scale+0.1);applyScale();},status),
  button('Zoom −',()=>{scale=Math.max(0.4,scale-0.1);applyScale();},status),
  button('Export SVG',async()=>{
   if(!plan)throw Error('Load a plan first');
   if(editOpen)await checked();
   else render(plan);
   download(new XMLSerializer().serializeToString(output.querySelector('svg')),'plan-diagram.svg','image/svg+xml');
  },status),
  editorToggle,
 );

 boardStage.append(output);
 board.append(toolbar,boardStage,status);

 actions.append(
  button('Use current planner tasks',async()=>{
   const tasks=getTasks().filter(t=>!['done','archived'].includes(t.status));
   if(!tasks.length)throw Error('No open tasks in the current planner scope.');
   if(tasks.length>60)throw Error('This scope has more than 60 tasks. Choose a smaller project.');
   saved=null;show((await api('visual-plans',{action:'validate',plan:{title:'Plan from current tasks',start:dayKey(new Date()),review_project_id:reviewId,assumptions:['Imported task references only. One calendar day per step is a placeholder; set durations and dependencies before use. Existing due dates are not changed.'],tasks:tasks.map((t,i)=>({id:'task'+(i+1),title:t.title,days:1,depends:[],source:'Planner task '+t.id}))}})).plan);
  },status),
  button('Example plan',async()=>{saved=null;show((await api('visual-plans',{action:'validate',plan:{...sample(),review_project_id:reviewId}})).plan);status.textContent='Example draft. Nothing saved.';},status),
  button('Ask local AI',async()=>{
   if(busy)return;busy=true;status.textContent='Drafting locally…';
   try{const d=await api('visual-plans',{action:'draft',prompt:prompt.input.value,plan:plan?read():null,review_project_id:reviewId});show(d.plan);status.textContent='AI draft ready. Review steps, dates and assumptions.';}
   finally{busy=false;}
  },status),
  button('Add step',()=>{const p=read();let id='step'+(p.tasks.length+1);while(p.tasks.some(t=>t.id===id))id+='x';p.tasks.push({id,title:'New step',days:1,depends:[],source:''});show(p);output.replaceChildren();},status),
  button('Validate / redraw',checked,status),
  button('Save revision',async()=>{const d=await api('visual-plans',{action:'save',plan:read(),id:saved?.id,version:saved?.version||0});saved=d.plan;show(d.plan);status.textContent='Saved revision '+saved.version;},status),
  button('Export plan',async()=>download(await checked(),'visual-plan.json'),status),
  button('Export diagram SVG',async()=>{await checked();download(new XMLSerializer().serializeToString(output.querySelector('svg')),'plan-diagram.svg','image/svg+xml');},status),
  button('Export workflow handoff',async()=>{const p=await checked();download({schema:'argus-workflow-handoff-v1',authority:'Unreviewed context',stage:'validated draft',next:'Review assumptions and task drafts before committing to schedule',checks:p.checks,plan:p},'planning-handoff.json');},status),
  dictation(prompt.input,status),
 );

 history.onchange=()=>{if(history.value){saved=JSON.parse(history.value);show(saved);status.textContent='Loaded revision '+saved.version;}};
 view.onchange=async()=>{try{if(editOpen&&plan)await checked();else if(plan)render(plan);}catch(e){status.textContent=e.message;}};
 rows.oninput=()=>{output.replaceChildren();choices.replaceChildren();status.textContent='Edits pending validation.';};
 title.input.oninput=start.input.oninput=rows.oninput;

 formBlock.append(el('p','Create a plan with the local AI or start from the example. All views use the same steps and dependencies. Saving a plan does not create tasks or book calendar events.'),prompt.wrap,actions,title.wrap,start.wrap,assumptions.wrap,rows,choices);
 formBlock.hidden=!editOpen;

 root.replaceChildren();
 root.append(board,formBlock);
 if(workspace)root.classList.add('visual-workspace-board');

 (async()=>{
  try{
   const plans=await loadRevisions();
   const active=readActive();
   if(active?.plan&&(!reviewId||active.plan.review_project_id===reviewId||!active.plan.review_project_id)){
    saved=active.savedId?{id:active.savedId,version:active.version,title:active.plan.title}:null;
    show(active.plan);
    status.textContent=active.version?`Restored in-progress plan · revision ${active.version}`:'Restored in-progress plan draft.';
    return;
   }
   if(!workspace)return;
   const latest=pickLatestPlan(plans,reviewId);
   if(latest){
    saved=latest;show(latest);
    status.textContent=`Loaded latest saved plan · revision ${latest.version}`;
    return;
   }
   status.textContent='No saved visual plan yet. Use Edit plan to create one.';
  }catch(e){status.textContent=e.message;}
 })();

 window.addEventListener('resize',()=>{if(workspace&&plan)fitBoard();});
}

function phoneNameKey(id){
 const wireless=id.match(/^adb-(.+)-[^.]+\._adb-tls-connect\._tcp$/);
 return 'argus.phone-name.'+(wireless?wireless[1]:id);
}
function phoneName(id){try{return localStorage.getItem(phoneNameKey(id))||id;}catch{return id;}}
export function mountPhone({edit}){const root=document.getElementById('phone-device-workspace');if(!root)return;const status=el('p'),devices=el('select'),text=field('Selected phone information','','textarea');text.input.rows=5;root.append(el('p','Android device controls · current screen capture is manual. Review and select the text you want to turn into a task.'),devices,button('Refresh devices',async()=>{const d=await api('phone-device');const list=Array.isArray(d.devices)?d.devices:[];devices.replaceChildren(new Option('Choose phone',''));for(const device of list)devices.append(new Option(phoneName(device.id)+' · '+device.state,device.id));status.textContent=d.detail||(d.ready?'Choose a device.':'No authorized phone is ready.');},status));root.append(button('Open visual phone',()=>{if(!devices.value)throw Error('Choose a connected phone first.');const selected=devices.selectedOptions[0];const label=selected?selected.textContent:'';const state=label.includes(' · ')?label.split(' · ').pop():'';if(state!=='device')throw Error('Choose an authorized phone (state must be device). Unlock the phone, approve USB debugging, then refresh devices.');return openPhoneScreen(devices.value,phoneName(devices.value));},status));const name=field('Phone name');name.input.maxLength=80;
 devices.onchange=()=>{name.input.value=devices.value?phoneName(devices.value):'';};
 root.append(name.wrap,button('Save phone name',()=>{
  if(!devices.value)throw Error('Choose a connected phone first.');
  const value=name.input.value.trim();if(!value)throw Error('Enter a phone name.');
  localStorage.setItem(phoneNameKey(devices.value),value);
  for(const option of devices.options){if(option.value&&phoneNameKey(option.value)===phoneNameKey(devices.value)){const state=option.textContent.split(' · ').pop();option.textContent=value+' · '+state;}}
  status.textContent='Phone name saved in this browser.';
 },status));for(const action of ['home','back','recents','read'])root.append(button(action==='read'?'Read current screen':action[0].toUpperCase()+action.slice(1),async()=>{const d=await api('phone-device',{action,device:devices.value});status.textContent=(typeof d.warning==='string'&&d.warning)?d.warning:(d.detail||'');if(d.text!==undefined)text.input.value=d.text;},status));const apps=el('select');root.append(button('List phone apps',async()=>{const d=await api('phone-device',{action:'apps',device:devices.value});apps.replaceChildren(new Option('Choose app',''));for(const name of d.apps)apps.append(new Option(name,name));status.textContent=d.detail;},status),apps,button('Open selected app',async()=>{const d=await api('phone-device',{action:'launch',device:devices.value,package:apps.value});status.textContent=d.detail;},status));root.append(status,text.wrap,button('Review as planner task',()=>{const selected=text.input.value.slice(text.input.selectionStart,text.input.selectionEnd)||text.input.value;if(!selected.trim())throw Error('Read or enter the information first');edit({title:selected.split('\n')[0].slice(0,240),notes:selected.slice(0,5000),source:'Phone screen · user-selected text',timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,estimate:30,status:'open',priority:'normal',recurrence:'none'});},status));}

function dictation(input,status){
 const b=el('button','Dictate plan');let recorder=null,stream=null,timer=null,cancelled=false;
 const release=()=>{clearTimeout(timer);stream?.getTracks().forEach(t=>t.stop());stream=null;};
 b.onclick=async()=>{if(recorder?.state==='recording'){recorder.stop();return;}try{
  if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder)throw Error('Microphone needs a secure browser connection. You can type the plan.');
  cancelled=false;stream=await navigator.mediaDevices.getUserMedia({audio:true});const chunks=[];recorder=new MediaRecorder(stream);const capture=recorder;
  capture.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};capture.onstop=async()=>{release();recorder=null;b.textContent='Dictate plan';if(cancelled)return;b.disabled=true;status.textContent='Transcribing locally…';try{const f=new FormData();f.append('file',new Blob(chunks,{type:capture.mimeType}),'plan.'+(capture.mimeType.includes('mp4')?'mp4':'webm'));f.append('local_only','true');const r=await fetch('/api/transcribe',{method:'POST',body:f,headers:{'X-Hermes-CSRF-Token':window.parent.__HERMES_CONFIG__?.csrfToken||''},signal:AbortSignal.timeout(60000)});const d=await r.json();if(!r.ok)throw Error(d.error||'Transcription unavailable');if(cancelled)return;const words=[input.value,d.transcript].filter(Boolean).join(' ');if(words.length>6000)throw Error('Prompt is too long; shorten it first.');input.value=words;status.textContent='Dictation ready. Review the words, then Ask local AI.';}catch(e){status.textContent=e.message;}finally{b.disabled=false;}};
  capture.start();b.textContent='Stop dictation';status.textContent='Listening · up to 60 seconds';timer=setTimeout(()=>{if(capture.state==='recording')capture.stop();},60000);
 }catch(e){release();status.textContent=e.message;}};
 const cancel=()=>{cancelled=true;if(recorder?.state==='recording')recorder.stop();release();};document.addEventListener('visibilitychange',()=>{if(document.hidden)cancel();});window.addEventListener('pagehide',cancel);return b;
}
