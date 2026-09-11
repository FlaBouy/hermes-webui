/* Optional Biggy extension. Existing cockpit controls retain their own handlers. */
(() => {
 'use strict';
 if(window.__sentinelHost)return;window.__sentinelHost=true;
 let button,panel,frame,healthTimer=0;
 const HEALTH_PATH='/sentinel/health';

 function setAvailability(available){
  if(!button)return;
  button.classList.toggle('is-online',!!available);
  button.classList.toggle('is-offline',!available);
  // Availability must never set selection chrome (ok / border / text).
  button.classList.remove('ok','down','muted','active','biggy-cockpit-action');
 }

 async function refreshAvailability(){
  if(!button||document.hidden)return;
  try{
   const response=await fetch(HEALTH_PATH,{credentials:'same-origin',cache:'no-store'});
   setAvailability(response.ok);
  }catch(_err){
   setAvailability(false);
  }
 }

 function close(restore=true){
  document.body.classList.remove('argus-sentinel-active');
  if(!panel)return;
  frame?.contentWindow?.postMessage({type:'argus-sentinel:dispose'},location.origin);
  panel.remove();panel=null;frame=null;
  button?.setAttribute('aria-expanded','false');
  if(restore)button?.focus();
 }

 function position(){
  if(!panel)return;
  const rail=document.querySelector('.biggy-top-rail-group');
  panel.style.top=`${Math.max(76,(rail?.getBoundingClientRect().bottom||64)+12)}px`;
 }

 function open(){
  if(panel){close();return;}
  panel=document.createElement('section');
  panel.id='argusSentinelPanel';
  panel.setAttribute('aria-label','SENTINEL workspace');
  const bar=document.createElement('div');bar.className='sentinel-host-bar';
  const title=document.createElement('b');title.textContent='SENTINEL';
  const exit=document.createElement('button');exit.type='button';exit.textContent='Close SENTINEL';exit.onclick=()=>close();
  bar.append(title,exit);
  frame=document.createElement('iframe');frame.title='SENTINEL geospatial workspace';frame.src='/sentinel/?embedded=1';
  panel.append(bar,frame);document.body.append(panel);
  document.body.classList.add('argus-sentinel-active');
  button.setAttribute('aria-expanded','true');
  position();exit.focus();
 }

 function install(){
  const rag=document.getElementById('biggyCockpitRag');
  if(!rag||document.getElementById('biggyCockpitSentinel'))return;
  button=document.createElement('button');
  button.id='biggyCockpitSentinel';
  button.type='button';
  button.className='biggy-fleet-machine is-offline';
  button.innerHTML='<span class="biggy-fleet-state" aria-hidden="true"></span><span>SENTINEL</span>';
  button.setAttribute('aria-expanded','false');
  button.setAttribute('aria-controls','argusSentinelPanel');
  button.onclick=open;
  rag.after(button);
  refreshAvailability().catch(()=>{});
  if(healthTimer)window.clearInterval(healthTimer);
  healthTimer=window.setInterval(()=>{refreshAvailability().catch(()=>{});},15000);
 }

 const observer=new MutationObserver(install);
 observer.observe(document.body,{childList:true,subtree:true});
 install();
 window.addEventListener('resize',position);
 window.addEventListener('message',event=>{
  if(event.origin===location.origin&&event.source===frame?.contentWindow&&event.data?.type==='argus-sentinel:close')close();
 });
 document.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&panel){event.preventDefault();close();}
 });
 document.addEventListener('click',event=>{
  if(panel&&event.target.closest('.biggy-top-rail-group button')&&!event.target.closest('#biggyCockpitSentinel,#biggyPtt,#biggyAudioRoute'))close(false);
 },true);
 window.addEventListener('pagehide',()=>{observer.disconnect();if(healthTimer)window.clearInterval(healthTimer);close(false);},{once:true});
})();
