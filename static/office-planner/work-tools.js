// Local planning helpers. These produce suggestions only; no calendar writes.
export function actionDrafts(text) {
 const lines=String(text).split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
 const marked=lines.filter(s=>/^(?:action(?: item)?\s*:|todo\s*:|[-*]\s*\[ \])/i.test(s));
 const candidates=marked.length?marked:lines;
 return [...new Set(candidates.map(s=>s.replace(/^(?:action(?: item)?\s*:|todo\s*:|[-*]\s*\[ \]|[-*]\s+|\d+[.)]\s+)/i,'').trim()).filter(Boolean))].slice(0,30);
}
export function workGaps(events,start,end,now=new Date(),minimum=15) {
 const lo=Math.max(+start,+now),hi=+end;
 if(!Number.isFinite(lo)||!Number.isFinite(hi)||hi<=lo)return [];
 const busy=[];
 for(const event of events){
  if(event.status==='cancelled'||event.transparency==='transparent')continue;
  const rawStart=event.start?.dateTime||event.start?.date||event.start;
  const rawEnd=event.end?.dateTime||event.end?.date||event.end;
  // Date-only calendar intervals end exclusively, in the viewer's local day.
  const parse=raw=>typeof raw!=='string'||!raw?NaN:/^\d{4}-\d{2}-\d{2}$/.test(raw)?+new Date(raw+'T00:00:00'):+new Date(raw);
  const a=parse(rawStart),b=parse(rawEnd);
  if(!Number.isFinite(a)||!Number.isFinite(b)||b<=a)throw Error('An appointment has an incomplete time. Work suggestions are unavailable until the calendar can be verified.');
  if(b>lo&&a<hi)busy.push([Math.max(a,lo),Math.min(b,hi)]);
 }
 busy.sort((a,b)=>a[0]-b[0]);let cursor=lo;const gaps=[];
 const add=(a,b)=>{if(b-a>=minimum*60000)gaps.push({start:new Date(a).toISOString(),end:new Date(b).toISOString(),minutes:Math.floor((b-a)/60000)});};
 for(const [a,b] of busy){add(cursor,a);cursor=Math.max(cursor,b);}add(cursor,hi);return gaps;
}
export function suggestWork(tasks,gaps){
 const remaining=[...tasks].sort((a,b)=>({high:0,normal:1,low:2}[a.priority]-{high:0,normal:1,low:2}[b.priority])||(a.due||'').localeCompare(b.due||''));
 const suggestions=[];
 for(const gap of gaps){let cursor=+new Date(gap.start),end=+new Date(gap.end);
  while(remaining.length){const i=remaining.findIndex(t=>Number.isFinite(t.estimate)&&t.estimate>=5&&t.estimate*60000<=end-cursor);if(i<0)break;
   const [task]=remaining.splice(i,1);const finish=cursor+task.estimate*60000;suggestions.push({task,start:new Date(cursor).toISOString(),end:new Date(finish).toISOString()});cursor=finish;
  }
 }
 return {suggestions,unplaced:remaining};
}

export function meetingBrief(tasks,{event=null,project='*',agenda='',now=new Date()}={}){
 const scoped=tasks.filter(t=>t.status!=='archived'&&(project==='*'||(t.project||'')===project));
 const active=scoped.filter(t=>t.status==='open'||t.status==='waiting');
 const completed=scoped.filter(t=>t.status==='done'&&Number.isFinite(Date.parse(t.completed))&&Date.parse(t.completed)>=+now-7*86400000&&Date.parse(t.completed)<=+now);
 const line=value=>String(value||'').replace(/[\r\n]+/g,' ').trim();
 const out=[`# ${line(event?.summary||event?.title||'Project preparation')}`,`Prepared: ${now.toISOString()}`,`Task scope: ${project==='*'?'All projects (explicitly selected)':project||'Unassigned tasks'}`,''];
 if(event){out.push(`Appointment: ${line(event.start?.dateTime||event.start?.date||event.start)} → ${line(event.end?.dateTime||event.end?.date||event.end)}`);if(event.location)out.push(`Location: ${line(event.location)}`);if(event.url)out.push(`Calendar source: ${line(event.url)}`);out.push('');}
 out.push('## Agenda',agenda.trim()||'Add the purpose, decisions needed and discussion points.','');
 const section=(heading,items)=>{out.push('## '+heading);if(!items.length)out.push('None recorded in this scope.');for(const t of items){out.push(`- ${line(t.title)} | ${line(t.priority)} priority${t.due?' | due '+line(t.due):''}${t.waiting_on?' | waiting on '+line(t.waiting_on):''}${t.snoozed_until&&Date.parse(t.snoozed_until)>+now?' | snoozed until '+line(t.snoozed_until):''}`);if(t.source)out.push('  Source: '+line(t.source));out.push(`  Planner record: ${line(t.id)} · version ${t.version||1}`);}out.push('');};
 const today=t=>new Intl.DateTimeFormat('en-CA',{timeZone:t.timezone||'UTC',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
 section('Due and overdue',active.filter(t=>t.status==='open'&&t.due&&t.due<=today(t)));
 section('Waiting on others',active.filter(t=>t.status==='waiting'));
 section('Other open work',active.filter(t=>t.status==='open'&&(!t.due||t.due>today(t))));
 section('Completed in the last seven days',completed);
 out.push('## Coverage',(event?'Prepared from the selected calendar entry and saved planner records. ':'Prepared from saved planner records; no appointment selected. ')+'Project scope is selected by you; no meeting-to-project relationship is inferred. Documents, mailbox, RAG and unrecorded decisions were not searched. This is a snapshot, not a live agenda.');
 return out.join('\n');
}
