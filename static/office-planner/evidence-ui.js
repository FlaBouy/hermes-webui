const $=id=>document.getElementById(id),node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
export function mountEvidence({reviewId,editTask}){
 const request=async(path,body)=>{const response=await fetch('/api/biggy/pa/'+path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Hermes-CSRF-Token':window.parent.__HERMES_CONFIG__?.csrfToken||''},body:JSON.stringify(body),signal:AbortSignal.timeout(25000)}:{signal:AbortSignal.timeout(15000)});const data=await response.json();if(!response.ok)throw Error(data.error||'Project evidence unavailable');return data;};
 $('evidence-projects').onclick=async()=>{
  const b=$('evidence-projects');b.disabled=true;
  try{const data=await request('review-context');$('evidence-project').replaceChildren(new Option('Choose a review',''));for(const p of data.projects||[])if(!reviewId||p.id===reviewId)$('evidence-project').append(new Option(p.name+' · '+p.id,p.id));if(reviewId)$('evidence-project').value=reviewId;$('evidence-status').textContent='Select a project and ask your question.';}
  catch(e){$('evidence-status').textContent=e.message;}finally{b.disabled=false;}
 };
 $('evidence-ask').onclick=async()=>{
  const project_id=$('evidence-project').value,query=$('evidence-question').value.trim();if(!project_id||!query){$('evidence-status').textContent='Choose a project and enter a question.';return;}
  const b=$('evidence-ask');b.disabled=true;$('evidence-results').replaceChildren();$('evidence-status').textContent='Checking project sources and saved task relationships…';
  try{const data=await request('project-evidence',{project_id,query});
   if(project_id!==$('evidence-project').value||query!==$('evidence-question').value.trim()){$('evidence-status').textContent='Selection changed. Check evidence again for the new question.';return;}
   const out=$('evidence-results'),answer=node('p',data.answer);answer.style.whiteSpace='pre-wrap';out.append(node('h2',data.project_name||'Project evidence'),answer);
   const coverage=node('details','');coverage.open=true;coverage.append(node('summary','Sources checked and limits'));for(const text of data.coverage)coverage.append(node('p',text));out.append(coverage);
   out.append(node('h3','Proposed commitments and schedule comparison'));
   if(!data.candidates.length)out.append(node('p','No commitment candidates found in the retrieved excerpts.'));
   for(const c of data.candidates){const source=data.evidence.find(e=>e.id===c.evidence_id),card=node('article','');card.append(node('h3',c.category+' · ['+c.evidence_id+']'),node('p',c.text),node('p',c.comparison));
    for(const t of c.related_tasks)card.append(node('p','Possible task: '+t.title+' · '+t.status+' · due '+(t.due||'not set')+' · '+t.id));
    const a=node('a','Inspect source ['+c.evidence_id+']');a.href='#evidence-source-'+c.evidence_id;card.append(a);
    const save=node('button','Review proposed task');save.onclick=()=>editTask({title:c.text.slice(0,240),due:'',status:'open',priority:'normal',recurrence:'none',estimate:30,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,project:data.project_name||'',review_project_id:project_id,source:(`Review ${project_id} · ${source.reference} · SHA256 ${source.source_hash}`).slice(0,1000),notes:('Unconfirmed '+c.category+' candidate.\n'+c.text+'\n'+c.comparison+'\nEvidence '+c.evidence_id+'; question: '+query).slice(0,5000)},()=>{save.disabled=true;save.textContent='Saved to planner';});card.append(save);out.append(card);
   }
   out.append(node('h3','Retrieved source excerpts'));
   for(const e of data.evidence){const card=node('article','');card.id='evidence-source-'+e.id;card.append(node('h3','['+e.id+'] '+e.kind),node('p',e.reference),node('p',e.text),node('small','Snapshot hash: '+e.source_hash+(e.generation?' · generation '+e.generation:'')));out.append(card);}
   $('evidence-status').textContent='Checked '+new Date(data.checked_at).toLocaleString()+'. Refresh after document, conversation or planner changes.';
  }catch(e){$('evidence-status').textContent=e.message;}finally{b.disabled=false;}
 };
}
