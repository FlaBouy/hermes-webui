import {mountVisual, mountPhone} from './visual-ui.js?v=whiteboard-20260911-view';
import {mountEvidence} from './evidence-ui.js?v=20260909';
import {mountSituation} from './situation-ui.js?v=20260909';
import {actionDrafts,workGaps,suggestWork,meetingBrief} from './work-tools.js?v=meeting-prep-20260909';
import {dayKey,quickTask,visibleTasks,snoozed} from './model.js';
const $=id=>document.getElementById(id),node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
let rows=[],view='Today',editing=null,busy=false,calendarBusy=false,calendarData=null,calendarLoadedAt=null,draftSaved=null,tasksLoadedAt=null;
const pageParams=new URLSearchParams(location.search);
const reviewId=pageParams.get('review_id')||'';
const workspaceMode=pageParams.get('workspace')==='1';
let reviewName='';
if(workspaceMode){
 document.body.classList.add('workspace-board');
 document.title='Local Visual Planner';
 const heading=document.querySelector('h1');if(heading)heading.textContent='Local visual planner';
}
const views=['Inbox','Today','Upcoming','Waiting','Snoozed','Completed','All'];
async function request(body){
 if(body?.action==='create'&&reviewId&&!Object.hasOwn(body.task||{},'review_project_id')){body.task={...body.task,review_project_id:reviewId,project:reviewName||body.task.project||'Project Review',source:body.task.source||'Project Review '+reviewId};}
 const response=await fetch('/api/biggy/pa/planner',body?{method:'POST',headers:{'Content-Type':'application/json','X-Hermes-CSRF-Token':window.parent.__HERMES_CONFIG__?.csrfToken||''},body:JSON.stringify(body)}:{});
 const result=await response.json();if(!response.ok)throw Error(result.error||'Planner unavailable');return result;
}
async function load(){try{rows=(await request()).tasks;if(reviewId)rows=rows.filter(t=>t.review_project_id===reviewId);tasksLoadedAt=new Date();render();}catch(e){$('status').textContent=e.message;}}
async function act(body){if(busy)return;busy=true;try{await request(body);await load();window.dispatchEvent(new Event('planner-changed'));$('status').textContent='Saved.';return true;}catch(e){$('status').textContent=e.message;await load();throw e;}finally{busy=false;}}
function edit(row=null,onSaved=null){editing=row?.id?row:null;draftSaved=onSaved;const form=$('edit-form');form.reset();const values={review_project_id:reviewId,project:reviewName,...(row||{timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,estimate:30,status:'open',priority:'normal',recurrence:'none'})};for(const el of form.elements)if(el.name)el.value=values[el.name]??'';$('edit-error').textContent='';$('editor').showModal();form.elements.title.focus();}
function button(label,fn){const b=node('button',label);b.onclick=async()=>{b.disabled=true;try{await fn();}catch(e){$('status').textContent=e.message;}finally{b.disabled=false;}};return b;}
function render(){
 const now=new Date();prepChoices();$('views').replaceChildren();for(const name of views){const b=button(`${name} · ${visibleTasks(rows,name,'',now).length}`,()=>{view=name;render();});b.setAttribute('aria-pressed',String(view===name));$('views').append(b);}
 const today=visibleTasks(rows,'Today','',now),overdue=today.filter(r=>r.due<dayKey(now,r.timezone));
 $('brief').replaceChildren(node('strong',`Today · ${dayKey(now)}`),node('div',`${today.length} due or overdue · ${overdue.length} overdue · ${visibleTasks(rows,'Waiting','',now).length} waiting on others`));
 const priorities=[...today].sort((a,b)=>({high:0,normal:1,low:2}[a.priority]-{high:0,normal:1,low:2}[b.priority])).slice(0,3);if(priorities.length)$('brief').append(node('div','Suggested priorities: '+priorities.map(r=>r.title).join(' · ')));
 const shown=visibleTasks(rows,view,$('search').value,now);$('tasks').replaceChildren();
 if(!shown.length)$('tasks').append(node('p','No tasks in this view. Capture one above or choose another list.'));
 for(const row of shown){const card=node('article','');if(row.due&&row.due<dayKey(now,row.timezone)&&row.status!=='done')card.className='overdue';card.append(node('h3',row.title));const meta=node('p',[row.due?`Due ${row.due}`:'No due date',row.priority+' priority',row.estimate+' min',row.recurrence!=='none'?'Repeats '+row.recurrence:'',row.project,row.waiting_on?'Waiting on '+row.waiting_on:''].filter(Boolean).join(' · '));meta.className='meta';card.append(meta);
 if(row.notes)card.append(node('p',row.notes));if(row.source)card.append(node('p','Reference: '+row.source));if(snoozed(row,now))card.append(node('p','Snoozed until '+new Date(row.snoozed_until).toLocaleString()));
 const actions=node('div','');actions.className='actions';const update=action=>act({action,id:row.id,version:row.version});
 if(row.status!=='done'){actions.append(button('Complete',()=>update('complete')),button('Edit',()=>edit(row)));actions.append(snoozed(row,now)?button('Unsnooze',()=>update('unsnooze')):button('Snooze 1 hour',()=>act({action:'snooze',id:row.id,version:row.version,minutes:60})));}
 else if(row.recurrence==='none')actions.append(button('Reopen',()=>update('reopen')));
 actions.append(button('Archive',()=>{if(confirm('Archive this task? It remains in your export.'))return update('archive');}));card.append(actions);$('tasks').append(card);}
}
$('capture').onsubmit=async e=>{e.preventDefault();if(busy)return;const task=quickTask($('quick').value);try{if(await act({action:'create',task})){$('quick').value='';view=task.due?(task.due>dayKey(new Date(),task.timezone)?'Upcoming':'Today'):'Inbox';render();$('status').textContent=`Added “${task.title}”${task.due?' · due '+task.due:''}.`;}}catch{}};
$('edit-form').onsubmit=async e=>{e.preventDefault();const task=Object.fromEntries(new FormData(e.target));task.estimate=Number(task.estimate);try{if(await act({action:editing?'update':'create',id:editing?.id,version:editing?.version,task})){$('editor').close();draftSaved?.();draftSaved=null;}}catch(err){$('edit-error').textContent=err.message;}};
$('close').onclick=()=>$('editor').close();$('new').onclick=()=>edit();$('refresh').onclick=load;$('search').oninput=render;
$('export').onclick=()=>{const blob=new Blob([JSON.stringify({schema:'office-planner-export-v1',exported:new Date().toISOString(),tasks:rows},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=node('a','');a.href=url;a.download='office-tasks.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
async function calendar(){if(calendarBusy)return;calendarBusy=true;calendarData=null;$('work-suggestions').replaceChildren();$('meetings').textContent='Loading calendar…';try{const start=new Date();start.setHours(0,0,0,0);const end=new Date(start);end.setDate(end.getDate()+1);const r=await fetch('/api/biggy/pa/calendar?'+new URLSearchParams({start:start.toISOString(),end:end.toISOString()}),{signal:AbortSignal.timeout(20000)});if(!r.ok)throw Error();const data=await r.json();$('meetings').replaceChildren();if(!data.connected||data.error){$('meetings').textContent=data.reconnect_required?'Google calendar authorization expired. Open PA → Calendar to reconnect. Your task lists still work.':'Calendar unavailable or not connected. Your task lists still work.';return;}calendarData=data;calendarLoadedAt=new Date();prepChoices(true);const events=data.events||[];if(!events.length)$('meetings').append(node('p','No appointments returned for today.'));for(const event of events){const raw=event.start?.dateTime||event.start?.date||event.start;const time=raw&&String(raw).includes('T')?new Date(raw).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'}):'All day';const meeting=node('div','');meeting.append(node('p',`${time} · ${event.summary||event.title||'Appointment'}`),button('Create meeting task',()=>edit({...quickTask('Prepare for '+(event.summary||event.title||'appointment')),source:event.url||event.summary||'Calendar appointment'})));$('meetings').append(meeting);}$('meetings').append(node('small','Calendar is read-only here. Updated '+new Date().toLocaleTimeString()));}catch{$('meetings').textContent='Calendar could not be loaded. Task lists remain available.';}finally{calendarBusy=false;}}
$('calendar-refresh').onclick=calendar;load();calendar();setInterval(()=>{if(!document.hidden&&(!window.frameElement||window.frameElement.getClientRects().length)&&!$('editor').open&&!busy)load();},15000);

$('review-actions').onclick=()=>{
 const drafts=actionDrafts($('meeting-notes').value),source=$('meeting-source').value.trim(),notes=$('meeting-notes').value;
 $('action-drafts').replaceChildren();if(!drafts.length){$('action-drafts').append(node('p','Add notes above first.'));return;}
 $('action-drafts').append(node('p',`${drafts.length} candidates · review each before saving. Candidates stay only on this screen until saved.`));
 for(const title of drafts){const article=node('article',''),field=node('textarea','');field.value=title;field.maxLength=240;field.setAttribute('aria-label','Proposed action');
 const save=button('Review and save task',()=>{const task={...quickTask(field.value),source,notes};edit(task,()=>{save.disabled=true;save.textContent='Saved to planner';field.disabled=true;});});article.append(field,save);$('action-drafts').append(article);}
};
$('plan-work').onclick=()=>{
 const out=$('work-suggestions');out.replaceChildren();
 if(!calendarData||!calendarLoadedAt||Date.now()-calendarLoadedAt>300000||dayKey(calendarLoadedAt)!==dayKey()){out.append(node('p','Load today’s calendar first. Suggestions require a successful calendar read within the last five minutes.'));return;}
 try{
  const day=dayKey(),start=new Date(day+'T'+$('work-start').value),end=new Date(day+'T'+$('work-end').value);
  if(!Number.isFinite(+start)||!Number.isFinite(+end)||end<=start)throw Error('Choose a finish time later than the start time.');
  const now=new Date(),gaps=workGaps(calendarData.events||[],start,end,now),tasks=visibleTasks(rows,'Today','',now),plan=suggestWork(tasks,gaps),clock=s=>new Date(s).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});
  out.append(node('p',`${gaps.length} available ${gaps.length===1?'period':'periods'} of at least 15 minutes · ${Intl.DateTimeFormat().resolvedOptions().timeZone} · calendar checked ${calendarLoadedAt.toLocaleTimeString()}`));
  for(const gap of gaps)out.append(node('p',`${clock(gap.start)}–${clock(gap.end)} · ${gap.minutes} minutes`));
  if(plan.suggestions.length)out.append(node('h3','Suggested task placement'));
  for(const item of plan.suggestions)out.append(node('p',`${clock(item.start)}–${clock(item.end)} · ${item.task.title}`));
  if(plan.unplaced.length)out.append(node('p',`${plan.unplaced.length} due tasks do not fit the remaining gaps. Adjust estimates or work hours.`));
  if(!tasks.length)out.append(node('p','No due or overdue tasks to place. Add tasks to Today to get suggestions.'));
  out.append(node('small','Preview only. No calendar events or task deadlines were changed.'));
 }catch(e){out.replaceChildren(node('p',e.message));}
};

function prepChoices(resetMeeting=false){
 const scope=$('prep-project'),prior=scope.value;scope.replaceChildren(new Option('Choose task scope',''),new Option('All projects','*'),new Option('Unassigned tasks','unassigned'));
 for(const name of [...new Set(rows.filter(t=>t.status!=='archived'&&t.project).map(t=>t.project))].sort())scope.append(new Option(name,'project:'+name));
 if([...scope.options].some(o=>o.value===prior))scope.value=prior;
 const meeting=$('prep-meeting'),selected=meeting.value;meeting.replaceChildren(new Option('No appointment selected',''));
 for(const [i,e] of (calendarData?.events||[]).entries())if(e.status!=='cancelled')meeting.append(new Option(e.summary||e.title||'Appointment',String(i)));
 if(!resetMeeting&&[...meeting.options].some(o=>o.value===selected))meeting.value=selected;
}
$('build-brief').onclick=()=>{
 if(!tasksLoadedAt||Date.now()-tasksLoadedAt>300000){$('prep-status').textContent='Refresh planner tasks before building this brief.';return;}
 const scope=$('prep-project').value;if(!scope){$('prep-status').textContent='Choose which project tasks to include.';return;}
 const chosen=$('prep-meeting').value;
 if(chosen!==''&&(!calendarLoadedAt||Date.now()-calendarLoadedAt>300000||dayKey(calendarLoadedAt)!==dayKey())){$('prep-status').textContent='Reload today’s calendar before preparing this appointment.';return;}
 const event=chosen===''?null:calendarData?.events?.[Number(chosen)];
 if(chosen!==''&&!event){$('prep-status').textContent='Reload the calendar and select the appointment again.';return;}
 $('prep-output').value=meetingBrief(rows,{event,project:scope==='*'?'*':scope==='unassigned'?'':scope.slice(8),agenda:$('prep-agenda').value});
 $('prep-status').textContent='Brief prepared from saved task records'+(event?' and the selected appointment.':'.')+' Review and edit before sharing.';
 $('copy-brief').disabled=false;$('export-brief').disabled=false;
};
$('copy-brief').onclick=async()=>{try{await navigator.clipboard.writeText($('prep-output').value);$('prep-status').textContent='Brief copied.';}catch{$('prep-output').focus();$('prep-output').select();$('prep-status').textContent='Select and copy the brief using your keyboard.';}};
$('export-brief').onclick=()=>{const url=URL.createObjectURL(new Blob([$('prep-output').value],{type:'text/markdown'})),a=node('a','');a.href=url;a.download='meeting-preparation-'+dayKey()+'.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};

window.addEventListener('message',e=>{
 if(e.source!==window.parent||e.origin!==location.origin||e.data?.type!=='argus-review-context'||e.data.project_id!==reviewId)return;
 reviewName=String(e.data.name||'Project Review').slice(0,128);document.querySelector('h1').textContent='Review planner · '+reviewName;
 $('meeting-source').value='Project Review: '+reviewName+' ['+reviewId+']';
 if(e.data.text){$('meeting-notes').value=String(e.data.text).slice(0,5000);$('meeting-capture').open=true;}
});

// Document candidates are previews. Only the existing task editor can save one.
$('document-planning').hidden=!reviewId;
async function reviewDocumentRequest(path,body){
 const response=await fetch('/api/biggy/projects/reviews/'+path+(body?'':'?'+new URLSearchParams({project_id:reviewId})),body?{method:'POST',headers:{'Content-Type':'application/json','X-Hermes-CSRF-Token':window.parent.__HERMES_CONFIG__?.csrfToken||''},body:JSON.stringify({...body,project_id:reviewId}),signal:AbortSignal.timeout(30000)}:{signal:AbortSignal.timeout(15000)});
 const data=await response.json();if(!response.ok)throw Error(data.error||'Document preview unavailable');return data;
}
$('load-documents').onclick=async()=>{
 const b=$('load-documents');b.disabled=true;
 try{const data=await reviewDocumentRequest('planning-documents');$('planning-document').replaceChildren(new Option('Choose a document',''));for(const path of data.documents)$('planning-document').append(new Option(path,path));$('document-status').textContent=data.limited?'Showing a bounded selection of documents (up to 200).':`${data.documents.length} supported documents available.`;}
 catch(e){$('document-status').textContent=e.message;}finally{b.disabled=false;}
};
$('preview-document').onclick=async()=>{
 const path=$('planning-document').value;if(!path){$('document-status').textContent='Choose a document first.';return;}
 const b=$('preview-document');b.disabled=true;$('document-candidates').replaceChildren();$('document-text').replaceChildren();$('document-status').textContent='Reading selected document…';
 try{
  const data=await reviewDocumentRequest('planning-preview',{path,start:Number($('planning-start').value)});
  $('document-status').textContent=`${data.candidates.length} candidates · units ${data.start}–${data.start+data.sections.length-1} of ${data.total_units}. ${data.coverage}`+(data.next_start?` Continue at ${data.next_start} to review more.`:'')+(data.candidate_limit?' Candidate limit reached; review source text for additional items.':'')+(data.empty_units.length?' Some pages have no native text; image-only content was not read.':'')+(data.sections.some(s=>s.truncated)?' Some source text was truncated.':'');
  for(const section of data.sections){const pre=node('pre',section.text||'No native text available.');pre.style.whiteSpace='pre-wrap';pre.style.overflowWrap='anywhere';$('document-text').append(node('h3',section.reference),pre);}
  for(const candidate of data.candidates){
   const card=node('article',''),source=`${data.document} · ${candidate.reference} · SHA256 ${data.sha256}`;
   card.append(node('h3',candidate.category),node('p',candidate.excerpt),node('small',candidate.reference+' · '+candidate.date_note));
   const save=button('Review task and date',()=>edit({title:candidate.title,due:'',priority:'normal',status:'open',recurrence:'none',estimate:30,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,review_project_id:reviewId,project:reviewName,source:source.slice(0,1000),notes:`Document planning proposal (${candidate.category}). Verify wording and date against the original.\n${candidate.excerpt}\n\n${source}`.slice(0,5000)},()=>{save.disabled=true;save.textContent='Saved to planner';}));
   if(rows.some(t=>t.source===source.slice(0,1000))){save.disabled=true;save.textContent='Already captured';}
   card.append(save);$('document-candidates').append(card);
  }
 }catch(e){$('document-status').textContent=e.message;}finally{b.disabled=false;}
};

mountSituation({reviewId,editTask:edit});

mountEvidence({reviewId,editTask:edit});

const incomingDraft=new URLSearchParams(location.search);
if(incomingDraft.get('draft_title'))edit({title:incomingDraft.get('draft_title').slice(0,240),source:(incomingDraft.get('draft_source')||'Conversation proposal').slice(0,1000),review_project_id:reviewId,due:'',status:'open',priority:'normal',recurrence:'none',estimate:15,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,notes:'Proposed in conversation. Confirm wording and deadline before saving.'});

mountVisual({edit, reviewId, getTasks:()=>rows, workspace:workspaceMode});
mountPhone({edit});

if(pageParams.get('phone')==='1'){const panel=document.getElementById('phone-device-panel');panel.open=true;panel.scrollIntoView();}
if(workspaceMode){
 const visual=document.getElementById('visual-panel');
 if(visual){visual.open=true;visual.scrollIntoView({block:'start'});}
}
