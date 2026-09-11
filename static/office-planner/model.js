export function dayKey(now=new Date(),timezone=Intl.DateTimeFormat().resolvedOptions().timeZone){return new Intl.DateTimeFormat('en-CA',{timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit'}).format(now);}
export function quickTask(text,now=new Date(),timezone=Intl.DateTimeFormat().resolvedOptions().timeZone){
 let title=text.trim(),due='',recurrence='none',priority='normal';
 if(/!high\b/i.test(title)){priority='high';title=title.replace(/!high\b/ig,'');}
 const today=dayKey(now,timezone),base=new Date(today+'T12:00:00Z');
 if(/\btomorrow\b/i.test(title)){base.setUTCDate(base.getUTCDate()+1);due=base.toISOString().slice(0,10);title=title.replace(/\btomorrow\b/i,'');}
 else if(/\btoday\b/i.test(title)){due=today;title=title.replace(/\btoday\b/i,'');}
 for(const [phrase,value] of [['every weekday','weekdays'],['every day','daily'],['every week','weekly'],['every month','monthly']])if(title.toLowerCase().includes(phrase)){recurrence=value;due||=today;title=title.replace(new RegExp(phrase,'i'),'');break;}
 if(recurrence==='weekdays'){const d=new Date(due+'T12:00:00Z');while(d.getUTCDay()===0||d.getUTCDay()===6)d.setUTCDate(d.getUTCDate()+1);due=d.toISOString().slice(0,10);}
 return {title:title.replace(/\s+/g,' ').trim(),due,recurrence,priority,status:'open',timezone,estimate:30};
}
export const snoozed=(r,now)=>!!r.snoozed_until&&Date.parse(r.snoozed_until)>now.getTime();
export function visibleTasks(rows,view,query='',now=new Date()){
 return rows.filter(r=>{
  if(r.status==='archived')return false;
  if(query&&!`${r.title} ${r.notes} ${r.project} ${r.waiting_on}`.toLowerCase().includes(query.toLowerCase()))return false;
  if(view==='Completed')return r.status==='done';if(r.status==='done')return false;
  const today=dayKey(now,r.timezone);
  if(view==='Snoozed')return snoozed(r,now);
  if(snoozed(r,now))return false;
  if(view==='Waiting')return r.status==='waiting';
  if(view==='Inbox')return !r.due&&r.status==='open';
  if(view==='Today')return r.status==='open'&&!!r.due&&r.due<=today;
  if(view==='Upcoming')return r.status==='open'&&r.due>today;
  return true;
 }).sort((a,b)=>(a.due||'9999').localeCompare(b.due||'9999')||({high:0,normal:1,low:2}[a.priority]-{high:0,normal:1,low:2}[b.priority])||a.created.localeCompare(b.created));
}
