// Deterministic local resolution and evidence-based signals. No model or writes.
import {dayKey} from './model.js';
const normalize=s=>String(s||'').toLowerCase().replace(/[^\p{L}\p{N}]+/gu,' ').trim();
export function entities(tasks,projects){
 const result=projects.map(p=>({key:'review:'+p.id,type:'Review',label:p.name,id:p.id}));
 const add=(type,label)=>{if(label&&!result.some(e=>e.type===type&&e.label===label))result.push({key:type+':'+label,type,label});};
 for(const t of tasks){if(t.status==='archived')continue;
  if(!t.review_project_id)add('Project',t.project);add('Person',t.waiting_on);
  if(t.source)add('Source',t.source.split(' · ')[0]);
  result.push({key:'task:'+t.id,type:'Task',label:t.title,id:t.id});
 }return result;
}
export function resolve(query,tasks,projects,currentReview=''){
 const all=entities(tasks,projects),q=normalize(query);
 if(!q)return {matches:[currentReview?all.find(e=>e.key==='review:'+currentReview)||{key:'review:'+currentReview,type:'Review',label:'Current review',id:currentReview}:{key:'all',type:'All',label:'All planner work'}]};
 const exact=all.filter(e=>normalize(e.label)===q||normalize(e.id)===q);
 const matches=exact.length?exact:all.filter(e=>{const name=normalize(e.label);return name.includes(q)||(name.length>=3&&q.includes(name));});
 return {matches};
}
export function scopedTasks(tasks,subject){
 return tasks.filter(t=>t.status!=='archived'&&(subject.key==='all'||
  subject.type==='Review'&&t.review_project_id===subject.id||
  subject.type==='Project'&&!t.review_project_id&&t.project===subject.label||
  subject.type==='Person'&&t.waiting_on===subject.label||
  subject.type==='Source'&&t.source?.split(' · ')[0]===subject.label||
  subject.type==='Task'&&t.id===subject.id));
}
const addDays=(day,n)=>{const d=new Date(day+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+n);return d.toISOString().slice(0,10);};
export function assess(tasks,subject,now=new Date()){
 const active=scopedTasks(tasks,subject).filter(t=>['open','waiting'].includes(t.status));
 const findings=[];
 for(const t of active){const today=dayKey(now,t.timezone||'UTC');
  const add=(kind,reason,inference=false)=>findings.push({kind,reason,inference,task:t});
  if(t.due&&t.due<today)add('Overdue',`Due ${t.due}; task remains ${t.status}.`);
  else if(t.due===today)add('Today','Due today in the task’s timezone.');
  else if(t.due&&t.due<=addDays(today,7))add('Upcoming',`Due ${t.due}, within seven days.`);
  if(t.status==='waiting')add('Waiting',t.waiting_on?`Recorded as waiting on ${t.waiting_on}.`:'Recorded as waiting; no responsible person identified.');
  if(!t.due)add('Missing date','No deadline is recorded. Confirm whether one is needed.',true);
  if(/\b(approve|approval|decision|decide)\b/i.test(t.title+' '+(t.notes||'')))add('Decision candidate','Task wording mentions a decision or approval; confirm whether it is still required.',true);
  if(t.snoozed_until&&Date.parse(t.snoozed_until)>+now&&t.due&&t.due<=today)add('Snoozed commitment','A due or overdue task is snoozed until '+t.snoozed_until+'.');
 }
 return {active:active.length,findings};
}
export function calendarConflicts(events,now=new Date()){
 const valid=[],invalid=[];
 for(const e of events){if(e.status==='cancelled'||e.transparency==='transparent')continue;
  const a=e.start?.dateTime||e.start?.date||e.start,b=e.end?.dateTime||e.end?.date||e.end;
  // All-day events are contextual, not assumed to reserve working hours.
  if(/^\d{4}-\d{2}-\d{2}$/.test(a)&&/^\d{4}-\d{2}-\d{2}$/.test(b))continue;
  const start=Date.parse(a),end=Date.parse(b);
  if(!Number.isFinite(start)||!Number.isFinite(end)||end<=start){invalid.push(e);continue;}
  if(end>+now)valid.push({event:e,start,end});
 }
 valid.sort((a,b)=>a.start-b.start);const overlaps=[];
 for(let i=0;i<valid.length;i++)for(let j=i+1;j<valid.length&&valid[j].start<valid[i].end;j++){
  if(valid[j].end>valid[i].start&&Math.min(valid[i].end,valid[j].end)>+now)overlaps.push([valid[i].event,valid[j].event]);
 }
 return {overlaps,invalid};
}
