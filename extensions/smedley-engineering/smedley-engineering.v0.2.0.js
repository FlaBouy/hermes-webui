(() => {
  'use strict';
  if (window.__smedleyEngineeringLoaded) return;
  window.__smedleyEngineeringLoaded = true;

  const RAG_PROXY = '/api/extensions/smedley-engineering/sidecar';
  const TOOLS_BASE = 'http://127.0.0.1:8801';
  const CONDUCTORS = ['14','12','10','8','6','4','3','2','1','1/0','2/0','3/0','4/0','250','300','350','400','500','600','750','1000'];
  const TOOLS = [
    ['voltage-drop','Voltage Drop','standard'],['feeder-size','Feeder Size','standard'],
    ['conductor-sets','Conductor Sets','standard'],['ocpd-size','OCPD Size','standard'],
    ['conduit-fill','Conduit Fill','standard'],['grounding','Grounding','standard'],
    ['cable-tray-fill','Cable Tray Fill','standard'],['motor-circuit','Motor Circuit','motor'],
    ['motor-starter','Motor Starter','motor'],['mcc-bucket','MCC Bucket','motor'],
    ['vfd-circuit','VFD Circuit','motor']
  ];
  const FIELDS = {
    'voltage-drop': [['voltage','System voltage (V)','number','480'],['phase','Phase','select','3|1'],['amps','Load amps','number',''],['length_ft','One-way length (ft)','number',''],['conductor_awg','Conductor size','select',CONDUCTORS.join('|')],['conduit_type','Conduit type','select','steel|aluminum|pvc'],['circuit_type','Circuit type','select','feeder|branch'],['parallel_sets','Parallel sets','number','1'],['power_factor','Power factor','number','0.85']],
    'feeder-size': [['voltage','System voltage (V)','number','480'],['phase','Phase','select','3|1'],['circuit_type','Circuit type','select','feeder|branch'],['length_ft','One-way length (ft)','number',''],['_fla_src','FLA source','select','amps|nameplate_fla|hp'],['_fla_val','FLA / HP value','number',''],['conduit_type','Conduit type','select','steel|aluminum|pvc'],['parallel_sets','Parallel sets','number','1'],['ambient_temp_c','Ambient temp (C)','number','30'],['num_conductors','Current-carrying conductors','number','3'],['temp_rating','Temp rating (C)','select','75|90|60']],
    'conductor-sets': [['voltage','System voltage (V)','number','480'],['phase','Phase','select','3|1'],['circuit_type','Circuit type','select','feeder|branch'],['length_ft','One-way length (ft)','number',''],['_fla_src','FLA source','select','amps|nameplate_fla|hp'],['_fla_val','FLA / HP value','number',''],['conduit_type','Conduit type','select','steel|aluminum|pvc'],['ambient_temp_c','Ambient temp (C)','number','30']],
    'ocpd-size': [['amps','Calculated amps','number',''],['circuit_type','Circuit type','select','feeder|branch'],['note','Basis / note','text','']],
    'conduit-fill': [['conduit_type','Conduit type','select','emt|imc|rmc|pvc_40|pvc_80'],['conductor_size','Conductor size','select',CONDUCTORS.join('|')],['num_current_carrying','Current-carrying conductors','number','3'],['ocpd_amps','OCPD rating for EGC','number',''],['trade_size','Check trade size (optional)','text','']],
    'grounding': [['mode','Mode','select','both|egc|gec'],['ocpd_amps','OCPD amps (EGC)','number',''],['service_conductor_size','Service conductor (GEC)','select',CONDUCTORS.join('|')],['circuit_conductor_size','Circuit conductor (EGC cap)','select','|'+CONDUCTORS.join('|')],['parallel_sets','Parallel sets','number','1']],
    'cable-tray-fill': [['tray_depth_in','Tray depth (in)','select','4|3|6'],['cable_type','Cable type','select','mc_4/0_plus|mc_smaller_4/0|sc_1000_plus|sc_250_to_1000|sc_1/0_to_4/0|control_signal|over_2000v'],['tray_style','Tray style','select','ladder|solid_bottom|vented_channel'],['check_width_in','Check width (optional)','number',''],['cables','Cables JSON','textarea','[{"cable_designation":"3C-10","count":3}]']],
    'motor-circuit': [['voltage','System voltage (V)','number','480'],['phase','Phase','select','3|1'],['length_ft','One-way length (ft)','number',''],['_fla_src','FLA source','select','hp|nameplate_fla|amps'],['_fla_val','HP / FLA value','number',''],['ocpd_type','OCPD type','select','itcb|tdf|itf|nfb'],['motor_type','Motor type','select','design_b|design_c|design_d|wound_rotor'],['conduit_type','Conduit type','select','steel|aluminum|pvc'],['service_factor','Service factor','number','1.15']],
    'motor-starter': [['voltage','System voltage (V)','number','480'],['phase','Phase','select','3|1'],['_fla_src','FLA source','select','hp|nameplate_fla|amps'],['_fla_val','HP / FLA value','number',''],['starter_type','Starter type','select','e300|e100|nema'],['circuit_type','Circuit type','select','fvnr|fvr'],['comms_type','Comms','select','enet|hardwired'],['control_voltage','Control voltage','select','120v|24v']],
    'mcc-bucket': [['voltage','System voltage (V)','number','480'],['phase','Phase','select','3|1'],['_fla_src','FLA source','select','hp|nameplate_fla|amps'],['_fla_val','HP / FLA value','number',''],['starter_type','Starter type','select','e300|e100|nema'],['circuit_type','Circuit type','select','fvnr|fvr|vfd'],['control_voltage','Control voltage','select','120v|24v'],['cable_entry','Cable entry','select','top|bottom'],['comms_type','Comms','select','enet|hardwired'],['include_cpt','Include CPT','select','true|false']],
    'vfd-circuit': [['voltage','System voltage (V)','number','480'],['phase','Phase','select','3|1'],['_fla_src','FLA source','select','hp|nameplate_fla|amps'],['_fla_val','HP / FLA value','number',''],['drive_input_fla','Drive input FLA','number',''],['length_ft','Output cable length (ft)','number','50'],['conduit_type','Conduit type','select','steel|aluminum|pvc'],['has_bypass','Bypass contactor','select','false|true'],['drive_model','Drive model','select','generic|pf700|pf525|pf755']]
  };

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const el = (tag, className, html) => { const node=document.createElement(tag); if(className) node.className=className; if(html!==undefined) node.innerHTML=html; return node; };
  let currentProject = '';
  let searchScope = 'global';

  async function jsonRequest(url, options={}) {
    const response = url.startsWith('/api/') && typeof window.api === 'function'
      ? await window.api(url, options)
      : await fetch(url, {...options, cache:'no-store'}).then(async (r) => { if(!r.ok) throw new Error(`HTTP ${r.status}: ${(await r.text()).slice(0,300)}`); return r.json(); });
    return response;
  }

  function sendThroughHermes(text) {
    const composer=document.getElementById('msg');
    if(!composer || typeof window.send!=='function') throw new Error('Hermes composer is not ready');
    composer.value=String(text||'').slice(0,32000);
    composer.dispatchEvent(new Event('input',{bubbles:true}));
    if(typeof window.autoResize==='function') window.autoResize();
    window.send();
  }

  function buildGroundedPrompt(question, matches) {
    const rows=(Array.isArray(matches)?matches:[]).slice(0,6).map((match,index)=>{
      const score=typeof match.score==='number'?` score=${match.score.toFixed(3)}`:'';
      return `[${index+1}] ${String(match.source||'unknown source').trim()}${score}\n${String(match.snippet||'').replace(/\s+/g,' ').trim()}`;
    }).filter(Boolean);
    if(!rows.length) return question;
    return `${question}\n\nUse the retrieved engineering-library excerpts below as evidence. Answer directly, separate facts from assumptions, cite sources by filename, and say plainly when the excerpts are insufficient.\n\n<retrieved_library_context>\n${rows.join('\n\n')}\n</retrieved_library_context>`;
  }

  async function proxyJson(path, options={}) {
    return jsonRequest(`${RAG_PROXY}${path}`, options);
  }

  function makeLeftRail() {
    const rail=el('aside','smedley-engineering-rail smedley-engineering-rail--left'); rail.id='smedleyEngineeringLeft';
    rail.innerHTML=`
      <section class="smedley-engineering-section">
        <h3>PROJECT</h3>
        <select id="smedleyProject"><option value="">— NONE —</option></select>
        <button id="smedleyNewProject" class="smedley-engineering-secondary">+ NEW PROJECT</button>
      </section>
      <section class="smedley-engineering-section">
        <h3>SEARCH SCOPE</h3>
        <div class="smedley-engineering-scope">
          <label><input type="radio" name="smedleyScope" value="global" checked> PROJECT + GLOBAL</label>
          <label><input type="radio" name="smedleyScope" value="project"> PROJECT ONLY</label>
          <label><input type="radio" name="smedleyScope" value="library"> GLOBAL ONLY</label>
        </div>
      </section>
      <section class="smedley-engineering-section">
        <h3>HERMES SESSION</h3>
        <div class="smedley-engineering-session-state"><span class="smedley-live-dot"></span> MEMORY + CONTINUITY ACTIVE</div>
        <p class="smedley-engineering-help">The native Hermes conversation history is the session record.</p>
      </section>
      <section class="smedley-engineering-section">
        <h3>REFERENCE UPLOAD</h3>
        <p class="smedley-engineering-kicker">STORED IN PROJECT — NOT INGESTED</p>
        <label class="smedley-engineering-drop" id="smedleyReferenceDrop">DROP FILES OR CLICK TO BROWSE<input id="smedleyReferenceFiles" type="file" multiple hidden></label>
        <div id="smedleyReferenceStatus" class="smedley-engineering-note"></div>
      </section>
      <div class="smedley-engineering-list-title">PROJECT FILES</div>
      <div id="smedleyProjectFiles" class="smedley-engineering-file-list"><em>No project selected</em></div>`;

    const project=rail.querySelector('#smedleyProject');
    const files=rail.querySelector('#smedleyProjectFiles');
    const upload=rail.querySelector('#smedleyReferenceFiles');
    const uploadStatus=rail.querySelector('#smedleyReferenceStatus');
    async function loadFiles(){
      files.innerHTML=currentProject?'<em>Loading…</em>':'<em>No project selected</em>';
      if(!currentProject)return;
      try{const data=await proxyJson(`/project-files?project=${encodeURIComponent(currentProject)}`);const rows=data.files||[];files.innerHTML=rows.length?rows.map((name)=>`<div title="${esc(name)}">📄 ${esc(name)}</div>`).join(''):'<em>No files uploaded</em>';}catch(error){files.innerHTML=`<em>${esc(error.message||error)}</em>`;}
    }
    async function loadProjects(){
      try{const data=await proxyJson('/projects');project.innerHTML='<option value="">— NONE —</option>';(data.projects||[]).forEach((name)=>{const option=el('option');option.value=name;option.textContent=String(name).toUpperCase();project.appendChild(option);});project.value=currentProject;}catch(error){project.innerHTML='<option value="">PROJECT API OFFLINE</option>';}
    }
    project.addEventListener('change',()=>{currentProject=project.value;loadFiles();});
    rail.querySelectorAll('input[name="smedleyScope"]').forEach((radio)=>radio.addEventListener('change',()=>{searchScope=radio.value;}));
    rail.querySelector('#smedleyNewProject').addEventListener('click',async()=>{const name=window.prompt('New project name');if(!name)return;try{const data=await proxyJson('/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name.trim()})});currentProject=data.project||name.trim();await loadProjects();await loadFiles();}catch(error){window.alert(`Project creation failed: ${error.message||error}`);}});
    upload.addEventListener('change',async()=>{if(!currentProject){uploadStatus.textContent='Select a project first.';return;}for(const file of upload.files){const body=new FormData();body.append('file',file);uploadStatus.textContent=`Uploading ${file.name}…`;try{const response=await fetch(`${RAG_PROXY}/upload?project=${encodeURIComponent(currentProject)}`,{method:'POST',body});if(!response.ok)throw new Error(`HTTP ${response.status}`);uploadStatus.textContent=`Uploaded ${file.name}`;}catch(error){uploadStatus.textContent=`Upload failed: ${error.message||error}`;break;}}upload.value='';loadFiles();});
    loadProjects();
    return rail;
  }

  function fieldControl(field) {
    const [name,label,type,initial]=field; const wrapper=el('label'); const caption=el('span');caption.textContent=label;wrapper.appendChild(caption);let control;
    if(type==='select'){control=el('select');String(initial).split('|').forEach((value)=>{const option=el('option');option.value=value;option.textContent=value||'—';control.appendChild(option);});}
    else if(type==='textarea'){control=el('textarea');control.rows=4;control.value=initial;}
    else{control=el('input');control.type=type;control.value=initial;}
    control.name=name;wrapper.appendChild(control);return wrapper;
  }
  function valueFor(control){if(control.value==='')return undefined;if(control.name==='cables')return JSON.parse(control.value);if(control.type==='number')return Number(control.value);if(control.value==='true')return true;if(control.value==='false')return false;return control.value;}
  function openTool(tool) {
    const backdrop=el('div','smedley-engineering-modal-backdrop');const modal=el('div','smedley-engineering-modal');const head=el('div','smedley-engineering-modal-head',`<h2>${esc(tool[1])}</h2><button type="button" aria-label="Close">×</button>`);const body=el('div','smedley-engineering-tool-body');const form=el('div','smedley-engineering-form');const result=el('div','smedley-engineering-result','<p>Validated results, assumptions, warnings, and NEC basis appear here.</p>');
    (FIELDS[tool[0]]||[]).forEach((field)=>form.appendChild(fieldControl(field)));const run=el('button','smedley-engineering-primary');run.textContent='RUN DETERMINISTIC TOOL';form.appendChild(run);body.append(form,result);modal.append(head,body);backdrop.appendChild(modal);const workspace=document.getElementById('mainChat');(workspace||document.body).appendChild(backdrop);
    const close=()=>backdrop.remove();head.querySelector('button').addEventListener('click',close);backdrop.addEventListener('mousedown',(event)=>{if(event.target===backdrop)close();});
    run.addEventListener('click',async()=>{run.disabled=true;run.textContent='CALCULATING…';try{const params={};form.querySelectorAll('input,select,textarea').forEach((control)=>{const value=valueFor(control);if(value!==undefined)params[control.name]=value;});if(params._fla_src&&params._fla_val!==undefined){params[params._fla_src]=params._fla_val;delete params._fla_src;delete params._fla_val;}const data=await jsonRequest(`${TOOLS_BASE}/tools/${tool[0]}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(params)});result.innerHTML=`<pre>${esc(JSON.stringify(data,null,2))}</pre>`;}catch(error){result.innerHTML=`<pre>${esc(JSON.stringify({status:'error',error:String(error.message||error)},null,2))}</pre>`;}finally{run.disabled=false;run.textContent='RUN DETERMINISTIC TOOL';}});
  }
  function makeRightRail(){
    const rail=el('aside','smedley-engineering-rail smedley-engineering-rail--right');rail.id='smedleyEngineeringRight';
    rail.innerHTML=`
      <section class="smedley-engineering-section"><h3>INGEST TO RAG</h3><p class="smedley-engineering-kicker">DROP TO LIBRARY FOLDER — WATCHER INDEXES</p><div class="smedley-engineering-inline"><span>FOLDER</span><button id="smedleyRefreshFolders" type="button">↺</button></div><select id="smedleyLibraryFolder"><option value="">LOADING…</option></select><label class="smedley-engineering-drop">DROP FILE TO INGEST<input id="smedleyIngestFile" type="file" hidden></label><div id="smedleyIngestUploadStatus" class="smedley-engineering-note"></div></section>
      <section class="smedley-engineering-section"><h3 class="smedley-engineering-heading-row">INGEST STATUS <span id="smedleyWatcherDot">●</span></h3><div id="smedleyIngestJobs" class="smedley-engineering-ingest-job">⏸ <span>Watcher idle</span></div><div class="smedley-engineering-heartbeat"><i></i></div><div id="smedleyQuarantine" class="smedley-engineering-note"></div></section>
      <section class="smedley-engineering-section"><h3>NEW LIBRARY FOLDER</h3><div class="smedley-engineering-new-folder"><input id="smedleyNewFolderName" type="text" placeholder="FOLDER NAME"><button id="smedleyCreateFolder" type="button">+</button></div><div id="smedleyFolderStatus" class="smedley-engineering-note"></div></section>
      <section class="smedley-engineering-section"><h3>CORPUS STATUS</h3><div id="smedleyCorpusVectors" class="smedley-engineering-corpus">—</div><div id="smedleyCorpusCollection" class="smedley-engineering-note"></div></section>
      <section class="smedley-engineering-section"><h3>LOW-LATENCY PATH</h3><div class="smedley-engineering-flow">EMBED → QDRANT → HERMES</div><p class="smedley-engineering-help">One Hermes response with memory and continuity.</p></section>`;
    const folder=rail.querySelector('#smedleyLibraryFolder'),upload=rail.querySelector('#smedleyIngestFile'),uploadStatus=rail.querySelector('#smedleyIngestUploadStatus');
    async function refreshFolders(){try{const data=await proxyJson('/library-folders');folder.innerHTML='';(data.folders||[]).forEach((name)=>{const option=el('option');option.value=name;option.textContent=String(name).toUpperCase();folder.appendChild(option);});if(!folder.options.length)folder.innerHTML='<option value="">NO FOLDERS FOUND</option>';}catch(error){folder.innerHTML='<option value="">FOLDER API OFFLINE</option>';}}
    async function refreshStatus(){try{const health=await proxyJson('/health');const status=await proxyJson('/ingest-status').catch(()=>null);const count=health.vector_count??health.vectors??health.qdrant_vectors??'—';rail.querySelector('#smedleyCorpusVectors').textContent=`${count} VECTORS`;rail.querySelector('#smedleyCorpusCollection').textContent=health.collection||health.qdrant_collection||'jarvis_kb';const jobs=rail.querySelector('#smedleyIngestJobs');const stale=!status||!status.heartbeat||((Date.now()/1000)-Number(status.heartbeat)>90);if(status&&!stale&&status.status==='active'){jobs.className='smedley-engineering-ingest-job active';jobs.innerHTML=`⚙ <span>${esc(status.last_file||'Indexing…')}</span>`;}else if(status&&!stale){jobs.className='smedley-engineering-ingest-job';jobs.innerHTML='⏸ <span>Watcher idle</span>';}else{jobs.className='smedley-engineering-ingest-job error';jobs.innerHTML=`⚠ <span>${status&&status.heartbeat?'Watcher stale':'Watcher unreachable'}</span>`;}rail.querySelector('#smedleyWatcherDot').classList.toggle('ok',!stale);const quarantined=status&&(status.quarantine_count??status.quarantined);rail.querySelector('#smedleyQuarantine').textContent=quarantined?`${quarantined} quarantined file(s)`:'';}catch(error){rail.querySelector('#smedleyCorpusVectors').textContent='CORPUS OFFLINE';}}
    rail.querySelector('#smedleyRefreshFolders').addEventListener('click',refreshFolders);
    upload.addEventListener('change',async()=>{const file=upload.files[0];if(!file||!folder.value)return;const body=new FormData();body.append('file',file);uploadStatus.textContent=`Uploading ${file.name}…`;try{const response=await fetch(`${RAG_PROXY}/ingest-upload?folder=${encodeURIComponent(folder.value)}`,{method:'POST',body});if(!response.ok)throw new Error(`HTTP ${response.status}`);uploadStatus.textContent=`Queued ${file.name}`;}catch(error){uploadStatus.textContent=`Ingest upload failed: ${error.message||error}`;}upload.value='';refreshStatus();});
    rail.querySelector('#smedleyCreateFolder').addEventListener('click',async()=>{const input=rail.querySelector('#smedleyNewFolderName'),name=input.value.trim();if(!name)return;try{await proxyJson('/library-folders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});rail.querySelector('#smedleyFolderStatus').textContent=`Created ${name}`;input.value='';refreshFolders();}catch(error){rail.querySelector('#smedleyFolderStatus').textContent=`Create failed: ${error.message||error}`;}});
    refreshFolders();refreshStatus();setInterval(refreshStatus,15000);return rail;
  }

  function retrieveFromComposer(note){const composer=document.getElementById('msg'),q=(composer&&composer.value||'').trim();if(!q){note.textContent='Type the engineering question in the Hermes message box first.';return;}note.textContent='Searching the engineering library…';const filter=searchScope==='library'?{library_only:true}:currentProject&&searchScope!=='library'?{project:currentProject,scope:searchScope}:{};proxyJson('/rag/retrieve',{method:'POST',body:JSON.stringify({query:q,topk:8,snippet_chars:900,filter})}).then((data)=>{composer.value='';composer.dispatchEvent(new Event('input',{bubbles:true}));sendThroughHermes(buildGroundedPrompt(q,data.matches));note.textContent=`${(data.matches||[]).length} source excerpt(s) sent to Hermes.`;}).catch((error)=>{note.textContent=`Retrieval failed: ${error.message||error}`;});}

  function currentHermesSessionId(){
    try{
      const activeRow=document.querySelector('.session-item.active[data-sid]');
      const activeSid=activeRow&&activeRow.dataset&&activeRow.dataset.sid;
      if(activeSid&&/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/.test(activeSid))return activeSid;
    }catch(_){}
    try{
      if(typeof S!=='undefined'&&S&&S.session&&S.session.session_id)return String(S.session.session_id);
    }catch(_){}
    try{
      const stored=localStorage.getItem('hermes-webui-session');
      if(stored&&/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/.test(stored))return stored;
    }catch(_){}
    return '';
  }

  function installPttBridge(header){
    const ptt=header.querySelector('#smedleyPtt');
    const routeBtn=header.querySelector('#smedleyAudioRoute');
    const note=header.querySelector('#smedleyHeaderNote');
    if(!ptt)return;
    const SESSION_REPOST_INTERVAL_MS=10000;
    let postedSession='';
    let lastSessionPostAt=0;
    let lastCompletionTimestamp=0;
    let completionBaselineEstablished=false;
    let routePending=false;

    function applyAudioRouteStatus(status){
      if(!routeBtn)return;
      const active=String(status.active_route||'room').toLowerCase();
      const desired=String(status.desired_route||active).toLowerCase();
      const switching=!!status.route_switching||routePending;
      const headsetAvailable=!!status.headset_available;
      routeBtn.textContent=active==='headset'?'HEADSET':'ROOM';
      routeBtn.classList.remove('ok','active','down');
      if(!status.pedal_alive){
        routeBtn.classList.add('down');
      }else if(switching){
        routeBtn.classList.add('active');
        note.textContent=`Switching to ${desired==='headset'?'Headset':'Room'}…`;
      }else if(desired==='headset'&&!headsetAvailable){
        routeBtn.classList.add('down');
        note.textContent='Headset is not connected to Smedley.';
      }else{
        routeBtn.classList.add('ok');
      }
    }

    if(routeBtn){
      routeBtn.addEventListener('click',async()=>{
        if(routePending)return;
        let status;
        try{status=await proxyJson('/ptt/status');}catch(_){return;}
        const active=String(status.active_route||'room').toLowerCase();
        const target=active==='headset'?'room':'headset';
        if(target==='headset'&&!status.headset_available){
          note.textContent='Headset is not connected to Smedley.';
          applyAudioRouteStatus(status);
          return;
        }
        routePending=true;
        applyAudioRouteStatus({...status,route_switching:true});
        try{
          await proxyJson('/ptt/audio-route',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({route:target})});
        }catch(_){
          note.textContent='Audio route request failed.';
        }finally{
          routePending=false;
        }
      });
    }

    function applyPttStatus(status){
      const pedalAlive=!!status.pedal_alive;
      const phase=String(status.phase||'idle');
      const busy=pedalAlive&&['listening','processing','speaking'].includes(phase);
      ptt.classList.remove('ok','active','down');
      if(!pedalAlive)ptt.classList.add('down');
      else if(busy)ptt.classList.add('active');
      else ptt.classList.add('ok');
      applyAudioRouteStatus(status);
    }

    async function syncActiveSession(){
      const sid=currentHermesSessionId();
      if(!sid)return;
      const now=Date.now();
      const sessionChanged=sid!==postedSession;
      const heartbeatStale=(now-lastSessionPostAt)>=SESSION_REPOST_INTERVAL_MS;
      if(!sessionChanged&&!heartbeatStale)return;
      try{
        await proxyJson('/ptt/active-session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sid})});
        postedSession=sid;
        lastSessionPostAt=now;
      }catch(_){}
    }

    async function pollPttStatus(){
      await syncActiveSession();
      try{
        const status=await proxyJson('/ptt/status');
        applyPttStatus(status);
        const sid=currentHermesSessionId();
        const completionSid=String(status.completion_session_id||'');
        const completionTimestamp=Number(status.completion_timestamp||0);
        if(!completionBaselineEstablished){
          lastCompletionTimestamp=completionTimestamp;
          completionBaselineEstablished=true;
          return;
        }
        if(
          completionSid
          &&completionTimestamp>lastCompletionTimestamp
          &&typeof loadSession==='function'
        ){
          lastCompletionTimestamp=completionTimestamp;
          if(sid&&completionSid===sid){
            await loadSession(sid,{force:true,externalRefreshReason:'ptt-completion'});
          }else if(completionSid!==sid){
            await loadSession(completionSid,{force:true,externalRefreshReason:'ptt-completion'});
            postedSession='';
          }
        }
      }catch(_){
        ptt.classList.remove('ok','active');
        ptt.classList.add('down');
        if(routeBtn){
          routeBtn.classList.remove('ok','active');
          routeBtn.classList.add('down');
        }
      }
    }

    pollPttStatus();
    setInterval(pollPttStatus,3000);
    setInterval(syncActiveSession,10000);
  }

  function makeHeader(left,right){const header=el('div','smedley-engineering-header');header.innerHTML='<img class="smedley-engineering-ega" src="/extensions/smedley-engineering/ega.jpg" alt="EGA"><div class="smedley-engineering-heading"><div class="smedley-engineering-title">SMEDLEY BUTLER\'S RAG CALL</div><div class="smedley-engineering-subtitle">JARVIS INTELLIGENCE PLATFORM · HERMES MEMORY · SMEDLEY</div></div><img class="smedley-engineering-ega" src="/extensions/smedley-engineering/ega.jpg" alt="EGA"><div class="smedley-engineering-status"><span id="smedleyRagBadge" class="smedley-engineering-badge">RAG</span><span id="smedleyToolsBadge" class="smedley-engineering-badge">TOOLS</span><button id="smedleyPtt" type="button" data-testid="smedley-ptt">● PTT</button><button id="smedleyAudioRoute" type="button" data-testid="smedley-audio-route">ROOM</button><span class="smedley-engineering-drawer-btns"><button type="button" data-drawer="left">Project</button><button type="button" data-drawer="right">Corpus</button></span></div><div id="smedleyHeaderNote" class="smedley-engineering-header-note"></div>';
    header.querySelectorAll('[data-drawer]').forEach((button)=>button.addEventListener('click',()=>{const target=button.dataset.drawer==='left'?left:right;target.classList.toggle('open');}));
    async function status(){const rag=header.querySelector('#smedleyRagBadge'),tools=header.querySelector('#smedleyToolsBadge');try{const value=await proxyJson('/health');rag.classList.toggle('ok',!!(value.api_alive&&value.lmstudio_reachable&&value.embed_model_loaded&&value.qdrant_reachable));rag.classList.toggle('down',!rag.classList.contains('ok'));}catch(_){rag.classList.add('down');rag.classList.remove('ok');}try{const value=await jsonRequest(`${TOOLS_BASE}/health`);tools.classList.toggle('ok',value.status==='ok');tools.classList.toggle('down',value.status!=='ok');}catch(_){tools.classList.add('down');tools.classList.remove('ok');}}
    const note=header.querySelector('#smedleyHeaderNote');
    header.querySelector('#smedleyPtt').addEventListener('click',()=>{note.textContent='PTT uses the physical pedal, microphone, and soundbar on Smedley.';});
    installPttBridge(header);
    status();setInterval(status,15000);return header;
  }

  function makeToolsDock(){const dock=el('div','smedley-engineering-tools-dock');for(const [kind,title] of [['standard','⚡ GENERIC CIRCUIT TOOLS'],['motor','⚙ MOTOR & STARTER TOOLS']]){const half=el('section','smedley-engineering-tools-half');half.innerHTML=`<h3>${title}</h3>`;const row=el('div','smedley-engineering-tools-row');TOOLS.filter((tool)=>tool[2]===kind).forEach((tool)=>{const button=el('button');button.textContent=tool[1];button.addEventListener('click',()=>openTool(tool));row.appendChild(button);});half.appendChild(row);dock.appendChild(half);}return dock;}

  function installOperatorChip(){
    const footer=document.querySelector('.composer-footer');
    if(!footer||document.getElementById('smedleyOperatorChipWrap'))return;
    const wrap=el('div','smedley-operator-chip-wrap');wrap.id='smedleyOperatorChipWrap';
    const chip=el('button','smedley-operator-chip loading');chip.id='smedleyOperatorChip';chip.type='button';chip.dataset.testid='smedley-operator-chip';chip.textContent='Operator';
    const dropdown=el('div','smedley-operator-dropdown');dropdown.id='smedleyOperatorDropdown';dropdown.dataset.testid='smedley-operator-dropdown';
    wrap.append(chip,dropdown);
    const profileWrap=document.getElementById('profileChipWrap');
    if(profileWrap&&profileWrap.parentElement===footer)footer.insertBefore(wrap,profileWrap);
    else footer.insertBefore(wrap,footer.firstChild);

    let operators=[];
    let activeId='';
    let open=false;

    const closeDropdown=()=>{open=false;dropdown.classList.remove('open');chip.classList.remove('active');};
    const renderDropdown=()=>{
      dropdown.innerHTML='';
      operators.forEach((operator)=>{
        const option=el('button','smedley-operator-option');
        option.type='button';
        option.dataset.operatorId=operator.operator_id;
        option.dataset.testid='smedley-operator-option';
        option.textContent=operator.display_name||operator.operator_id;
        if(operator.operator_id===activeId)option.classList.add('active');
        option.addEventListener('click',async()=>{
          if(operator.operator_id===activeId){closeDropdown();return;}
          option.disabled=true;
          try{
            const data=await proxyJson('/operators/active',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({operator_id:operator.operator_id})});
            activeId=data.operator_id||operator.operator_id;
            chip.textContent=data.display_name||operator.display_name||activeId;
            renderDropdown();
          }catch(_error){
            chip.textContent=operators.find((row)=>row.operator_id===activeId)?.display_name||'Operator';
          }finally{option.disabled=false;closeDropdown();}
        });
        dropdown.appendChild(option);
      });
    };

    chip.addEventListener('click',()=>{
      if(chip.classList.contains('loading')||!operators.length)return;
      open=!open;
      dropdown.classList.toggle('open',open);
      chip.classList.toggle('active',open);
    });
    document.addEventListener('click',(event)=>{
      if(!event.target.closest('#smedleyOperatorChipWrap'))closeDropdown();
    });

    (async()=>{
      try{
        const [listData,activeData]=await Promise.all([proxyJson('/operators'),proxyJson('/operators/active')]);
        operators=listData.operators||[];
        activeId=activeData.operator_id||listData.active||'';
        const active=operators.find((row)=>row.operator_id===activeId)||activeData;
        chip.textContent=active.display_name||activeId||'Operator';
        chip.classList.remove('loading');
        renderDropdown();
      }catch(_error){
        chip.textContent='Smedley';
        chip.classList.remove('loading');
      }
    })();
  }

  function removeHermesCenterPlaceholders(){document.querySelectorAll('#msgInner div').forEach((node)=>{if(node.textContent.trim()==='Loading conversation...')node.remove();});}

  function init(){const layout=document.querySelector('.layout');const main=document.querySelector('main.main');const mainChat=document.getElementById('mainChat');const rightPanel=document.querySelector('.rightpanel');if(!layout||!main||!mainChat)return;const left=makeLeftRail(),right=makeRightRail();layout.insertBefore(left,main);layout.insertBefore(right,rightPanel||null);mainChat.classList.add('smedley-engineering-iwo');mainChat.insertBefore(makeHeader(left,right),mainChat.firstChild);mainChat.appendChild(makeToolsDock());installOperatorChip();const msgInner=document.getElementById('msgInner');if(msgInner){removeHermesCenterPlaceholders();new MutationObserver(removeHermesCenterPlaceholders).observe(msgInner,{childList:true,subtree:true});}const sync=()=>{const shown=getComputedStyle(mainChat).display!=='none';left.hidden=!shown;right.hidden=!shown;if(!shown){left.classList.remove('open');right.classList.remove('open');}};new MutationObserver(sync).observe(mainChat,{attributes:true,attributeFilter:['class','style','hidden']});sync();}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
