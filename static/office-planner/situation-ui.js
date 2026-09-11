import {resolve,assess,calendarConflicts} from './situation.js?v=20260909';
const $=id=>document.getElementById(id),node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
export function mountSituation({reviewId,editTask}){
 let checked=null;
 window.addEventListener('planner-changed',()=>{checked=null;$('situation-status').textContent='Planner records changed. Refresh the Situation Brief.';});
 const get=async path=>{const r=await fetch(path,{signal:AbortSignal.timeout(20000)});if(!r.ok)throw Error('Source unavailable');return r.json();};
 for(const id of ['situation-subject','situation-question'])$(id).addEventListener('input',()=>{checked=null;$('situation-results').replaceChildren();$('situation-matches').replaceChildren();$('situation-status').textContent='Build the brief for this selection.';});
 const labelTime=d=>new Date(d).toLocaleString();
 const action=(label,fn)=>{const b=node('button',label);b.onclick=fn;return b;};
 $('situation-refresh').onclick=async()=>{
  const trigger=$('situation-refresh');trigger.disabled=true;checked=null;
  $('situation-results').replaceChildren();$('situation-matches').replaceChildren();$('situation-status').textContent='Checking tasks, review context and calendar…';
  const now=new Date(),end=new Date(now);end.setDate(end.getDate()+7);
  const query=$('situation-subject').value,question=$('situation-question').value;
  const results=await Promise.allSettled([get('/api/biggy/pa/planner'),get('/api/biggy/pa/review-context'),get('/api/biggy/pa/calendar?'+new URLSearchParams({start:now.toISOString(),end:end.toISOString()}))]);
  trigger.disabled=false;
  if(query!==$('situation-subject').value||question!==$('situation-question').value){$('situation-status').textContent='Your selection changed. Build the brief again for the new selection.';return;}
  checked=new Date();
  const taskData=results[0].status==='fulfilled'?results[0].value:null,reviewData=results[1].status==='fulfilled'?results[1].value:null,calendar=results[2].status==='fulfilled'?results[2].value:null;
  if(!taskData||!Array.isArray(taskData.tasks)){$('situation-status').textContent='Planner unavailable. No task assessment was made. Refresh to retry.';checked=null;return;}
  const tasks=taskData.tasks,projects=reviewData?.projects||[],resolution=resolve(query,tasks,projects,reviewId);
  const sources=[`Planner retrieved ${labelTime(checked)} (saved records; real-world completion is not verified).`,reviewData?`Review metadata retrieved ${labelTime(checked)}.`:'Review metadata unavailable; project resolution may be incomplete.',calendar?.connected&&!calendar.error?`Primary calendar retrieved ${labelTime(checked)} for the next seven days; provider cache may apply. Up to 250 events; other calendars are not included.`:'Calendar unavailable or disconnected; scheduling conflicts could not be checked.','Document text, review conversations and mail are not searched by this brief. Source references point to saved task evidence.'];
  const render=subject=>{
   $('situation-matches').replaceChildren();const out=$('situation-results');out.replaceChildren(node('h2',subject.type+' · '+subject.label));
   const summary=assess(tasks,subject,now),allowed={today:['Overdue','Today','Waiting','Snoozed commitment'],week:['Overdue','Today','Upcoming','Waiting','Missing date','Decision candidate','Snoozed commitment'],blocked:['Waiting','Missing date','Decision candidate']};
   const findings=summary.findings.filter(f=>question==='all'||allowed[question].includes(f.kind));
   out.append(node('p',`${summary.active} active task records · ${findings.length} signals (a task can have several).`));
   if(!findings.length)out.append(node('p','No matching signals in the loaded task records. This does not establish that all work is on track.'));
   const project=projects.find(p=>subject.type==='Review'&&p.id===subject.id);
   if(project)out.append(node('p','Saved review state: '+project.state+'. Evidence readiness was not rechecked.'));
   for(const finding of findings){const t=finding.task,card=node('article','');card.append(node('h3',finding.kind+' · '+t.title),node('p',(finding.inference?'Needs confirmation: ':'Recorded: ')+finding.reason),node('small','Task '+t.id+' · version '+t.version+(t.updated?' · saved '+labelTime(t.updated):'')));
    if(t.source)card.append(node('p','Source: '+t.source));
    card.append(action('Review task',()=>editTask(t)));
    if(finding.kind==='Waiting'||finding.kind==='Decision candidate')card.append(action('Prepare follow-up task',()=>editTask({title:('Follow up: '+t.title).slice(0,240),notes:'Proposed follow-up; confirm need before saving.\n'+finding.reason+'\nOriginal task: '+t.id,source:t.source||'Planner task '+t.id,project:t.project||'',review_project_id:t.review_project_id||'',due:'',status:'open',priority:'normal',recurrence:'none',estimate:15,timezone:t.timezone||Intl.DateTimeFormat().resolvedOptions().timeZone})));
    out.append(card);
   }
   if(calendar?.connected&&!calendar.error){const c=calendarConflicts(calendar.events||[],now);out.append(node('h3','Calendar context · account-wide, not project-linked'),node('p',`${c.overlaps.length} potential timed overlaps in returned events. All-day entries are not treated as reserved work hours.`));
    if(c.invalid.length)out.append(node('p',`${c.invalid.length} events have unusable times and could not be checked.`));
    for(const pair of c.overlaps.slice(0,20)){const card=node('article','');for(const e of pair){card.append(node('p',(e.summary||'Appointment')+' · '+(e.start?.dateTime||e.start)));
      try{const url=new URL(e.url);if(url.protocol==='https:'){const a=node('a','Open calendar source');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';card.append(a);}}catch{}
     }out.append(card);}
    if(c.overlaps.length>20)out.append(node('p','Showing the first 20 overlaps.'));
   }
   const coverage=node('details','');coverage.append(node('summary','Sources and coverage'));for(const s of sources)coverage.append(node('p',s));coverage.open=true;out.append(coverage);
   $('situation-status').textContent='Snapshot built '+labelTime(checked)+'. Refresh after changes. Suggestions do not change schedules or send messages.';
  };
  if(resolution.matches.length===1)render(resolution.matches[0]);
  else if(!resolution.matches.length)$('situation-status').textContent='No matching subject in saved context. Try a project, person, task or source name. Nothing was inferred.';
  else{$('situation-status').textContent='Several subjects match. Choose one to continue.';for(const subject of resolution.matches)$('situation-matches').append(action(subject.type+' · '+subject.label+(subject.id?' · '+subject.id.slice(-8):''),()=>render(subject)));}
 };
 setInterval(()=>{if(checked&&Date.now()-checked>300000)$('situation-status').textContent='This brief is more than five minutes old. Refresh before using it to plan.';},30000);
}
