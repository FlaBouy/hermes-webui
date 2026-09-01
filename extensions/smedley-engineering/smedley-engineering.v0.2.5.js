(() => {
  'use strict';
  if (window.__smedleyEngineeringLoaded) return;
  window.__smedleyEngineeringLoaded = true;

  const GUI_ID=window.__HERMES_GUI_ID__==='biggy'?'biggy':'smedley';
  const TOOLS_ONLY_EMBED=GUI_ID==='biggy';
  // Biggy's profile only installs biggy-brand.  The shared calculators still
  // talk to the same loopback tools sidecar (:5004), but must use the host
  // profile's consented extension id — smedley-engineering is not present on
  // Biggy and returns "Extension not found".
  const RAG_PROXY = TOOLS_ONLY_EMBED
    ? '/api/extensions/biggy-brand/sidecar'
    : '/api/extensions/smedley-engineering/sidecar';
  const PTT_INSTANCE='smedley';
  // Biggy intentionally locks its own GUI identity.  The shared calculator
  // runtime must not try to replace it when loaded from the Tools rail.
  if(!TOOLS_ONLY_EMBED)window.__HERMES_GUI_ID__=GUI_ID;
  // Independent of Biggy. Owner-ACK / Approvals UI stays off until Smedley owns that surface.
  const FEATURES=Object.freeze({approvalsEnabled:false,diagnosticsEnabledDefault:false,guiId:GUI_ID,profileId:'smedley'});
  if(!TOOLS_ONLY_EMBED)window.__SMEDLEY_FEATURES__=FEATURES;
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
    'voltage-drop': [['voltage','System voltage (V)','number','480'],['phase','Phase','select','3|1'],['amps','Load amps','number',''],['length_ft','One-way length (ft)','number',''],['material','Conductor material','select','copper'],['temp_rating','Temp / terminal basis (C)','select','75|90|60'],['conduit_type','Conduit type','select','steel|aluminum|pvc'],['circuit_type','Circuit type','select','feeder|branch'],['continuous_load','Continuous load','select','true|false'],['parallel_sets','Parallel sets','number','1'],['power_factor','Power factor','number','0.85'],['ambient_temp_c','Ambient temp (C)','number','30'],['num_conductors','Current-carrying conductors','number','3']],
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
    if(!composer || typeof window.send!=='function') throw new Error('Smedley composer is not ready');
    composer.value=String(text||'').slice(0,32000);
    composer.dispatchEvent(new Event('input',{bubbles:true}));
    if(typeof window.autoResize==='function') window.autoResize();
    window.send();
  }

  async function proxyJson(path, options={}) {
    return jsonRequest(`${RAG_PROXY}${path}`, options);
  }



  const CORPUS_LAN_RE = /^https?:\/\/(?:192\.168\.0\.15|127\.0\.0\.1|localhost)(?::8789)\/(.+)$/i;
  const SIDECAR_HREF_RE = /^\/api\/extensions\/smedley-engineering\/sidecar\/(preview|doc)\/(.+)$/i;
  const SIDECAR_ABS_HREF_RE = /^https?:\/\/[^/\s]+\/api\/extensions\/smedley-engineering\/sidecar\/(preview|doc)\/(.+)$/i;

  function smedleyWebuiOrigin(){
    // Canonical WebUI origin for persisted doc links (TD must keep a working href).
    // Never treat corpus-serve 192.168.0.15:8789 as the WebUI origin.
    try{
      const o=String((window.location&&window.location.origin)||'').replace(/\/$/,'');
      if(!o || /192\.168\.0\.15/i.test(o) || /:8789$/i.test(o)) return '';
      return o;
    }catch(_){ return ''; }
  }
  function toAbsoluteSidecarUrl(pathOrUrl){
    const raw=String(pathOrUrl||'').trim();
    if(!raw) return '';
    if(/^https?:\/\//i.test(raw)){
      if(/192\.168\.0\.15:8789/i.test(raw) || /127\.0\.0\.1:8789/i.test(raw) || /localhost:8789/i.test(raw)){
        return '';
      }
      try{
        const u=new URL(raw);
        if(u.pathname.startsWith(RAG_PROXY+'/preview/') || u.pathname.startsWith(RAG_PROXY+'/doc/')){
          return u.origin + u.pathname + (u.search||'');
        }
      }catch(_){}
      return '';
    }
    const path=(raw.startsWith('/')?raw:('/'+raw)).split('#')[0];
    if(!(path.startsWith(RAG_PROXY+'/preview/') || path.startsWith(RAG_PROXY+'/doc/'))) return '';
    const origin=smedleyWebuiOrigin();
    // Prefer absolute Smedley WebUI origin; relative only when origin is unknown.
    return origin ? (origin + path) : path;
  }
  function libraryRelpathFromSource(source){
    let rel=String(source||'').replace(/\\/g,'/').trim();
    if(!rel || rel==='?') return '';
    try{
      const u=new URL(rel, window.location.origin);
      if(/^https?:$/i.test(u.protocol) && u.pathname) rel=u.pathname;
    }catch(_){}
    rel=rel.split('?')[0].split('#')[0];
    const peel=/^(?:\/)?(?:api\/extensions\/smedley-engineering\/sidecar\/(?:preview|doc)\/)+/i;
    while(peel.test(rel)) rel=rel.replace(peel,'');
    const low=rel.toLowerCase();
    const lastDoc=low.lastIndexOf('/api/extensions/smedley-engineering/sidecar/doc/');
    const lastPrev=low.lastIndexOf('/api/extensions/smedley-engineering/sidecar/preview/');
    const last=Math.max(lastDoc, lastPrev);
    if(last>=0){
      const route=lastDoc>=lastPrev?'doc':'preview';
      const prefix=`/api/extensions/smedley-engineering/sidecar/${route}/`;
      rel=rel.slice(last+prefix.length);
    }
    try{ rel=decodeURIComponent(rel); }catch(_){}
    return rel.replace(/^\/+/,'').replace(/\\/g,'/');
  }
  function corpusSidecarPath(source){
    const rel=libraryRelpathFromSource(source);
    if(!rel||rel==='?')return '';
    const ext=(rel.split('.').pop()||'').toLowerCase();
    const route=ext==='pdf'?'doc':'preview';
    // Keep path segments encoded; preserve '/' separators (matches RAG match.url).
    return RAG_PROXY+'/'+route+'/'+rel.split('/').map(encodeURIComponent).join('/');
  }
  function normalizeCorpusSidecarUrl(pathOrUrl){
    const raw=String(pathOrUrl||'').trim();
    if(!raw) return '';
    // Never promote lan_url / corpus-serve.
    if(/192\.168\.0\.15:8789/i.test(raw) || /127\.0\.0\.1:8789/i.test(raw) || /localhost:8789/i.test(raw)){
      const m=raw.match(CORPUS_LAN_RE);
      if(!m) return '';
      let rel=m[1].split('?')[0].split('#')[0];
      try { rel=decodeURIComponent(rel); } catch (_) {}
      rel=libraryRelpathFromSource(rel.replace(/^\/+/,'').replace(/\\/g,'/'));
      return toAbsoluteSidecarUrl(corpusSidecarPath(rel));
    }
    // Collapse already-prefixed / doubled sidecar routes to one canonical path.
    if(/\/api\/extensions\/smedley-engineering\/sidecar\/(?:preview|doc)\//i.test(raw)){
      try{
        const u=new URL(raw, window.location.origin);
        const collapsed=corpusSidecarPath(u.pathname+(u.search||''));
        if(collapsed){
          if(/192\.168\.0\.15:8789/i.test(u.origin) || /:8789$/i.test(u.origin)){
            return toAbsoluteSidecarUrl(collapsed);
          }
          // Prefer current WebUI origin for openable same-cookie links.
          return toAbsoluteSidecarUrl(collapsed);
        }
      }catch(_){
        const collapsed=corpusSidecarPath(raw);
        if(collapsed) return toAbsoluteSidecarUrl(collapsed);
      }
    }
    if(SIDECAR_HREF_RE.test(raw) || raw.startsWith(RAG_PROXY+'/preview/') || raw.startsWith(RAG_PROXY+'/doc/')){
      return toAbsoluteSidecarUrl(corpusSidecarPath(raw.split('#')[0]));
    }
    if(SIDECAR_ABS_HREF_RE.test(raw)){
      return toAbsoluteSidecarUrl(corpusSidecarPath(raw.split('#')[0]));
    }
    // Bare library-relative path.
    if(/\.(?:pdf|docx?|xlsx?|pptx?|txt|md)$/i.test(raw) && !/:\/\//.test(raw)){
      return toAbsoluteSidecarUrl(corpusSidecarPath(raw));
    }
    return '';
  }
  function corpusUrlForSource(source){
    // Pure source contract: absolute canonical sidecar from source alone — never lan_url / 0.15:8789.
    return toAbsoluteSidecarUrl(corpusSidecarPath(source));
  }
  function rewriteCorpusHref(href){
    return normalizeCorpusSidecarUrl(href);
  }
  function corpusMarkdownForSource(source, url){
    const rel=String(source||'').trim();
    const href=normalizeCorpusSidecarUrl(url) || corpusUrlForSource(rel);
    if(!href)return rel||'?';
    const fname=rel.split('/').pop()||rel;
    return `📄 [${fname}](${href})`;
  }
  function rewriteCitationMarkdown(md, fallbackUrl, source){
    let link=String(md||'').trim();
    if(!link) return corpusMarkdownForSource(source, fallbackUrl);
    link=link.replace(/\]\((https?:\/\/(?:192\.168\.0\.15|127\.0\.0\.1|localhost):8789\/[^)]+)\)/gi,(_,u)=>{
      const next=normalizeCorpusSidecarUrl(u) || fallbackUrl || corpusUrlForSource(source);
      return `](${next})`;
    });
    link=link.replace(/\]\(((?:https?:\/\/[^)\s]+)?\/api\/extensions\/smedley-engineering\/sidecar\/(?:preview|doc)\/[^)]+)\)/g,(_,p)=>{
      const next=normalizeCorpusSidecarUrl(p) || p;
      return `](${next})`;
    });
    // Strip any bare lan_url leftovers.
    link=link.replace(/https?:\/\/(?:192\.168\.0\.15|127\.0\.0\.1|localhost):8789\/\S+/gi,'');
    if(/lan_url/i.test(link)) link=link.replace(/lan_url\s*[:=]\s*\S+/gi,'');
    return link.trim() || corpusMarkdownForSource(source, fallbackUrl);
  }
  function buildGroundedPrompt(question, matches) {
    const rows=(Array.isArray(matches)?matches:[]).slice(0,6).map((match,index)=>{
      const source=String(match.source||'unknown source').trim();
      // Use only match.url / match.markdown. Never lan_url.
      const url=normalizeCorpusSidecarUrl(String(match.url||'').trim()) || corpusUrlForSource(source);
      const link=rewriteCitationMarkdown(match.markdown, url, source);
      const score=typeof match.score==='number'?` score=${match.score.toFixed(3)}`:'';
      return `[${index+1}] ${link}${score}\n${String(match.snippet||'').replace(/\s+/g,' ').trim()}`;
    }).filter(Boolean);
    if(!rows.length) return question;
    return `${question}\n\nUse the retrieved engineering-library excerpts below as evidence. Answer directly from those excerpts and COPY the provided markdown links exactly. Open docs via absolute WebUI sidecar URLs only (Smedley origin + /api/extensions/smedley-engineering/sidecar/preview|doc/...). NEVER emit http://192.168.0.15:8789 or lan_url. NEVER claim RAG/API/SMB is down when excerpts are present.\n\n<retrieved_library_context>\n${rows.join('\n\n')}\n</retrieved_library_context>`;
  }

  function promoteCorpusMarkdownLinks(root){
    const scope=root&&root.querySelectorAll?root:(document.getElementById('msgInner')||document.body);
    if(!scope) return;
    const re=/📄?\s*\[([^\]]+)\]\(((?:https?:\/\/[^)\s]+)?\/api\/extensions\/smedley-engineering\/sidecar\/(?:preview|doc)\/[^)\s]+)\)/g;
    const walker=document.createTreeWalker(scope, NodeFilter.SHOW_TEXT, {
      acceptNode(node){
        if(!node||!node.nodeValue) return NodeFilter.FILTER_REJECT;
        if(!node.nodeValue.includes('/api/extensions/smedley-engineering/sidecar/')) return NodeFilter.FILTER_REJECT;
        const p=node.parentElement;
        if(p&&(p.closest('a,code,pre,textarea,script,style'))) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    const nodes=[];
    while(walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((textNode)=>{
      const raw=textNode.nodeValue||'';
      re.lastIndex=0;
      if(!re.test(raw)) return;
      re.lastIndex=0;
      const frag=document.createDocumentFragment();
      let last=0, m;
      while((m=re.exec(raw))){
        if(m.index>last) frag.appendChild(document.createTextNode(raw.slice(last,m.index)));
        const label=(m[1]||'document').trim();
        const href=normalizeCorpusSidecarUrl(m[2])||m[2];
        const a=document.createElement('a');
        a.href=href;
        a.target='_blank';
        a.rel='noopener noreferrer';
        a.textContent='📄 '+label.replace(/^📄\s*/,'');
        frag.appendChild(a);
        last=m.index+m[0].length;
      }
      if(last<raw.length) frag.appendChild(document.createTextNode(raw.slice(last)));
      textNode.parentNode.replaceChild(frag, textNode);
    });
  }

  function rewriteCorpusAnchors(root){
    const scope=root&&root.querySelectorAll?root:document;
    scope.querySelectorAll('a[href*=":8789/"], a[href*="192.168.0.15:8789"], a[href*="/api/extensions/smedley-engineering/sidecar/"]').forEach((a)=>{
      const raw=a.getAttribute('href')||a.href;
      const next=rewriteCorpusHref(raw);
      if(!next) return;
      if(raw !== next) a.setAttribute('href', next);
      if(!a.getAttribute('target')) a.setAttribute('target','_blank');
      a.setAttribute('rel','noopener noreferrer');
      const label=(a.textContent||'').trim();
      if(CORPUS_LAN_RE.test(label) || /192\.168\.0\.15:8789/i.test(label)){
        try {
          const path=decodeURIComponent((label.match(CORPUS_LAN_RE)||[])[1]||'');
          const fname=path.split('/').pop()||'document';
          a.textContent='📄 '+fname;
        } catch (_) {}
      }
    });
  }

  async function openCorpusDocument(url){
    let target=String(url||'').trim();
    if(!target) return;
    // Never fetch LAN corpus-serve / invented paths — rewrite to sidecar or refuse.
    const rewritten=normalizeCorpusSidecarUrl(target);
    if(rewritten) target=rewritten;
    else {
      try{
        const u=new URL(target, window.location.origin);
        if(!(u.pathname.startsWith(RAG_PROXY+'/preview/') || u.pathname.startsWith(RAG_PROXY+'/doc/'))){
          window.alert('Corpus open refused: not a Smedley sidecar document URL.');
          return;
        }
        target=u.href;
      }catch(_){
        window.alert('Corpus open refused: invalid document URL.');
        return;
      }
    }
    // Always fetch same-origin sidecar path so local :8787 cookies authorize the open,
    // even when the rendered markdown href is an absolute Tailscale/public origin.
    try{
      const u=new URL(target, window.location.origin);
      if(u.pathname.startsWith(RAG_PROXY+'/preview/') || u.pathname.startsWith(RAG_PROXY+'/doc/')){
        target=u.pathname+(u.search||'');
      }
    }catch(_){ }
    // Open the authenticated sidecar URL itself.  Fetching it into a blob makes
    // some browsers download the PDF instead of honoring the sidecar's inline
    // Content-Disposition response.
    const win=window.open(target,'_blank','noopener');
    if(!win) window.location.assign(target);
  }

  function installCorpusLinkFix(){
    const run=()=>{const root=document.getElementById('msgInner')||document.body;promoteCorpusMarkdownLinks(root);rewriteCorpusAnchors(root);};
    run();
    const msgInner=document.getElementById('msgInner');
    if(msgInner){
      new MutationObserver(run).observe(msgInner,{childList:true,subtree:true,attributes:true,attributeFilter:['href']});
    }
    document.addEventListener('click',(ev)=>{
      const a=ev.target&&ev.target.closest?ev.target.closest('a[href]'):null;
      if(!a) return;
      const raw=a.getAttribute('href')||a.href||'';
      let next=rewriteCorpusHref(raw);
      if(!next){
        try {
          const u=new URL(raw, window.location.origin);
          if(u.pathname.startsWith(RAG_PROXY+'/preview/') || u.pathname.startsWith(RAG_PROXY+'/doc/')){
            next=normalizeCorpusSidecarUrl(u.href) || u.href;
          }
        } catch (_) {}
      }
      if(!next) return;
      ev.preventDefault();
      ev.stopPropagation();
      a.setAttribute('href', next);
      // Cross-origin absolute Smedley links (e.g. opened from TD) navigate directly.
      try{
        const target=new URL(next, window.location.origin);
        if(target.origin!==window.location.origin){
          window.open(next,'_blank','noopener,noreferrer');
          return;
        }
      }catch(_){}
      openCorpusDocument(next);
    }, true);
  }

  let __smedleyWarmPromise = null;
  function warmModelsOnOpen(){
    if(__smedleyWarmPromise) return __smedleyWarmPromise;
    const note=document.getElementById('smedleyHeaderNote');
    if(note) note.textContent='Warming model…';
    __smedleyWarmPromise = proxyJson('/rag/warm',{method:'GET'})
    .then((data)=>{
      const hermes=(data&&data.results||[]).find((r)=>String(r.model||'').includes('35b'));
      const ok=!!(data&&data.status==='ok');
      if(note){
        if(ok) note.textContent = hermes&&hermes.already_loaded ? 'Model ready' : 'Model warmed';
        else note.textContent='Model warm partial — first reply may still hitch';
      }
      const rag=document.getElementById('smedleyRagBadge');
      if(rag){ rag.classList.toggle('ok', ok); rag.title = JSON.stringify(data&&data.loaded_now||[]); }
      return data;
    }).catch((err)=>{
      if(note) note.textContent='Model warm failed — first reply may hitch';
      console.warn('smedley warm failed', err);
      return null;
    });
    return __smedleyWarmPromise;
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
        <h3>SMEDLEY SESSION</h3>
        <div class="smedley-engineering-session-state"><span class="smedley-live-dot"></span> MEMORY + CONTINUITY ACTIVE</div>
        <p class="smedley-engineering-help">The native Smedley conversation history is the session record.</p>
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

  // Empty defaults that are intentionally optional (check-existing / notes / estimates).
  // ocpd_amps is optional for conduit-fill; grounding requires it only for egc/both via validateExtra.
  const OPTIONAL_EMPTY_FIELDS = new Set([
    'note',
    'trade_size',
    'check_width_in',
    'circuit_conductor_size',
    'drive_input_fla',
    'ocpd_amps',
  ]);

  const FIELD_NUMBER_CONSTRAINTS = Object.freeze({
    parallel_sets: {min: '1', step: '1'},
    num_conductors: {min: '1', step: '1'},
    num_current_carrying: {min: '1', step: '1'},
    power_factor: {min: '0', max: '1', step: 'any'},
    voltage: {min: '0', step: 'any'},
    amps: {min: '0', step: 'any'},
    length_ft: {min: '0', step: 'any'},
    _fla_val: {min: '0', step: 'any'},
    ocpd_amps: {min: '0', step: 'any'},
    service_factor: {min: '0', step: 'any'},
    drive_input_fla: {min: '0', step: 'any'},
    check_width_in: {min: '0', step: 'any'},
    ambient_temp_c: {step: 'any'},
  });

  function fieldControl(field) {
    const [name, label, type, initial] = field;
    const wrapper = el('label');
    const caption = el('span');
    caption.textContent = label;
    wrapper.appendChild(caption);
    let control;
    if (type === 'select') {
      control = el('select');
      String(initial).split('|').forEach((value) => {
        const option = el('option');
        option.value = value;
        option.textContent = value || '—';
        control.appendChild(option);
      });
    } else if (type === 'textarea') {
      control = el('textarea');
      control.rows = 4;
      control.value = initial;
    } else {
      control = el('input');
      control.type = type;
      control.value = initial;
      if (type === 'number') {
        control.inputMode = 'decimal';
        const constraints = FIELD_NUMBER_CONSTRAINTS[name] || {};
        control.step = constraints.step || 'any';
        if (constraints.min != null) control.min = constraints.min;
        if (constraints.max != null) control.max = constraints.max;
      }
    }
    control.name = name;
    if (
      (type === 'number' || type === 'text' || type === 'textarea')
      && String(initial ?? '') === ''
      && !OPTIONAL_EMPTY_FIELDS.has(name)
    ) {
      control.required = true;
    }
    if (name === 'cables') control.required = true;
    wrapper.appendChild(control);
    return wrapper;
  }
  function valueFor(control) {
    if (control.value === '') return undefined;
    if (control.name === 'cables') return JSON.parse(control.value);
    if (control.type === 'number') return Number(control.value);
    if (control.value === 'true') return true;
    if (control.value === 'false') return false;
    return control.value;
  }

  let activeToolClose = null;

  function openTool(tool) {
    if (activeToolClose) activeToolClose();

    const toolId = tool[0];
    const backdrop = el('div', 'smedley-engineering-modal-backdrop');
    const modal = el('div', 'smedley-engineering-modal');
    const head = el(
      'div',
      'smedley-engineering-modal-head',
      `<h2>${esc(tool[1])}</h2><button type="button" aria-label="Close">×</button>`,
    );
    const body = el('div', 'smedley-engineering-tool-body');
    const form = el('form', 'smedley-engineering-form');
    const result = el(
      'div',
      'smedley-engineering-result',
      '<div class="smedley-engineering-result-empty">Enter parameters — results update live.</div>',
    );
    (FIELDS[toolId] || []).forEach((field) => form.appendChild(fieldControl(field)));
    const run = el('button', 'smedley-engineering-primary');
    run.type = 'button';
    run.textContent = 'RECALCULATE';
    form.appendChild(run);
    body.append(form, result);
    modal.append(head, body);
    backdrop.appendChild(modal);
    const workspace = document.getElementById('mainChat');
    (workspace || document.body).appendChild(backdrop);

    let live = null;
    let closed = false;
    let voltageDropBaseline = null;
    let comparisonSequence = 0;
    const close = () => {
      if (closed) return;
      closed = true;
      if (live && typeof live.dispose === 'function') live.dispose();
      if (activeToolClose === close) activeToolClose = null;
      backdrop.remove();
    };
    activeToolClose = close;
    head.querySelector('button').addEventListener('click', close);
    backdrop.addEventListener('mousedown', (event) => {
      if (event.target === backdrop) close();
    });
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      if (live && typeof live.calculateNow === 'function') live.calculateNow();
    });

    const collectParams = () => {
      const params = {};
      form.querySelectorAll('input,select,textarea').forEach((control) => {
        const value = valueFor(control);
        if (value !== undefined) params[control.name] = value;
      });
      if (params._fla_src && params._fla_val !== undefined) {
        params[params._fla_src] = params._fla_val;
        delete params._fla_src;
        delete params._fla_val;
      }
      return params;
    };

    const calculate = async (params) => {
      if (toolId === 'voltage-drop') {
        const sizing = window.SmedleyVoltageDropSizing;
        if (!sizing || typeof sizing.calculate !== 'function') {
          throw new Error('Voltage drop auto-sizing helper is not loaded.');
        }
        return sizing.calculate(params, async (path, toolParams) =>
          proxyJson(path, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(toolParams),
          }),
        );
      }
      return proxyJson(`/tools/${toolId}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(params),
      });
    };

    const requestVoltageDrop = (params, conductorAwg) => proxyJson('/tools/voltage-drop', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        voltage: Number(params.voltage),
        phase: Number(params.phase),
        amps: Number(params.amps),
        length_ft: Number(params.length_ft),
        conductor_awg: String(conductorAwg),
        conduit_type: String(params.conduit_type || '').toLowerCase(),
        circuit_type: String(params.circuit_type || '').toLowerCase(),
        parallel_sets: Number(params.parallel_sets || 1),
        ...(params.power_factor !== undefined
          ? {power_factor: Number(params.power_factor)} : {}),
      }),
    });

    const renderConductorComparison = (data) => {
      if (toolId !== 'voltage-drop' || !voltageDropBaseline?.result) return;
      const sizing = window.SmedleyVoltageDropSizing;
      const sizes = Array.isArray(sizing?.CONDUCTORS) ? sizing.CONDUCTORS : [];
      const recommended = String(voltageDropBaseline.result.recommended_size || '');
      const current = String(data?.result?.comparison_size || recommended);
      const currentIndex = sizes.indexOf(current);
      const parallelFloor = voltageDropBaseline.result.parallel_minimum_awg;
      const floorIndex = parallelFloor ? sizes.indexOf(String(parallelFloor)) : 0;
      if (!sizes.length || currentIndex < 0) return;

      const controls = el('div', 'smedley-conductor-compare');
      const smaller = el('button', 'smedley-conductor-compare-step');
      smaller.type = 'button';
      smaller.textContent = '◀ SMALLER';
      smaller.disabled = currentIndex <= Math.max(0, floorIndex);
      const status = el(
        'div',
        'smedley-conductor-compare-status',
        `<span>CONDUCTOR COMPARISON</span><strong>${esc(current)} AWG</strong>`
          + `<small>RECOMMENDED ${esc(recommended)} AWG</small>`,
      );
      const reset = el('button', 'smedley-conductor-compare-reset');
      reset.type = 'button';
      reset.textContent = 'RECOMMENDED';
      reset.disabled = current === recommended;
      const larger = el('button', 'smedley-conductor-compare-step');
      larger.type = 'button';
      larger.textContent = 'LARGER ▶';
      larger.disabled = currentIndex >= sizes.length - 1;
      controls.append(smaller, status, reset, larger);
      result.prepend(controls);

      const compare = async (nextSize) => {
        if (!nextSize || !voltageDropBaseline?.result) return;
        const requestId = ++comparisonSequence;
        controls.querySelectorAll('button').forEach((button) => { button.disabled = true; });
        status.querySelector('small').textContent = `CHECKING ${nextSize} AWG…`;
        try {
          const params = collectParams();
          const drop = await requestVoltageDrop(params, nextSize);
          if (requestId !== comparisonSequence) return;
          if (!drop || drop.status !== 'ok' || !drop.result) {
            throw new Error(drop?.error || `Voltage-drop comparison failed for ${nextSize} AWG.`);
          }
          const baseline = voltageDropBaseline;
          const ampacityMinimum = String(baseline.result.minimum_ampacity_size || recommended);
          const ampacityPass = sizes.indexOf(nextSize) >= sizes.indexOf(ampacityMinimum);
          const voltageDropPass = String(drop.result.pass_fail || '').toUpperCase() === 'PASS';
          const warnings = Array.from(new Set([...(drop.warnings || [])]));
          if (!ampacityPass) {
            warnings.unshift(
              `Trial ${nextSize} AWG is below minimum ampacity/code size ${ampacityMinimum} AWG.`,
            );
          }
          const comparison = {
            ...drop,
            inputs: {...(drop.inputs || {}), ...params, conductor_awg: nextSize},
            result: {
              ...drop.result,
              conductor_awg: nextSize,
              comparison_size: nextSize,
              baseline_recommended_size: recommended,
              recommended_size: recommended,
              minimum_ampacity_size: baseline.result.minimum_ampacity_size,
              minimum_voltage_drop_size: baseline.result.minimum_voltage_drop_size,
              parallel_minimum_awg: baseline.result.parallel_minimum_awg,
              governing_constraint: baseline.result.governing_constraint,
              governing_explanation: baseline.result.governing_explanation,
              design_amps: baseline.result.design_amps,
              derated_ampacity_A: baseline.result.derated_ampacity_A,
              ampacity_pass_fail: ampacityPass ? 'PASS' : 'FAIL',
              voltage_drop_pass_fail: voltageDropPass ? 'PASS' : 'FAIL',
              pass_fail: ampacityPass && voltageDropPass ? 'PASS' : 'FAIL',
            },
            assumptions: Array.from(new Set([
              ...(drop.assumptions || []),
              `ElectriCalc comparison: ${nextSize} AWG trial against automatic ${recommended} AWG recommendation.`,
            ])),
            warnings,
            code_basis: Array.from(new Set([
              baseline.code_basis,
              drop.code_basis,
            ].filter(Boolean))).join(' | '),
          };
          renderSuccess(comparison, {preserveBaseline: true});
        } catch (error) {
          if (requestId === comparisonSequence) renderError(error);
        }
      };
      smaller.addEventListener('click', () => compare(sizes[currentIndex - 1]));
      larger.addEventListener('click', () => compare(sizes[currentIndex + 1]));
      reset.addEventListener('click', () => compare(recommended));
    };

    const renderSuccess = (data, options = {}) => {
      if (toolId === 'voltage-drop' && data?.status === 'ok' && !options.preserveBaseline) {
        voltageDropBaseline = data;
        comparisonSequence += 1;
      }
      const renderer = window.SmedleyElectricalResults;
      if (renderer && typeof renderer.renderResultCard === 'function') {
        result.innerHTML = renderer.renderResultCard(toolId, data);
      } else {
        result.innerHTML = `<pre>${esc(JSON.stringify(data, null, 2))}</pre>`;
      }
      renderConductorComparison(data);
    };

    const renderError = (error) => {
      const errPayload = {status: 'error', error: String(error.message || error)};
      const renderer = window.SmedleyElectricalResults;
      if (renderer && typeof renderer.renderResultCard === 'function') {
        result.innerHTML = renderer.renderResultCard(toolId, errPayload);
      } else {
        result.innerHTML = `<pre>${esc(JSON.stringify(errPayload, null, 2))}</pre>`;
      }
    };

    const validateExtra = (controls) => {
      const byName = Object.fromEntries(controls.map((control) => [control.name, control]));
      const errors = {};
      if (toolId === 'grounding') {
        const mode = String(byName.mode?.value || 'both');
        if ((mode === 'egc' || mode === 'both') && !String(byName.ocpd_amps?.value || '').trim()) {
          errors.ocpd_amps = 'OCPD amps (EGC) is required for this mode.';
        }
        if ((mode === 'gec' || mode === 'both')
            && !String(byName.service_conductor_size?.value || '').trim()) {
          errors.service_conductor_size = 'Service conductor (GEC) is required for this mode.';
        }
      }
      if (byName._fla_src && byName._fla_val
          && !String(byName._fla_val.value || '').trim()) {
        errors._fla_val = 'FLA / HP value is required.';
      }
      return errors;
    };

    const liveApi = window.SmedleyLiveTools;
    form.addEventListener('input', () => { comparisonSequence += 1; });
    form.addEventListener('change', () => { comparisonSequence += 1; });
    if (liveApi && typeof liveApi.wire === 'function') {
      live = liveApi.wire({
        form,
        result,
        run,
        collectParams,
        calculate,
        renderSuccess,
        renderError,
        validateExtra,
      });
      const firstEmpty = form.querySelector('input[required],textarea[required]');
      if (firstEmpty && typeof firstEmpty.focus === 'function') firstEmpty.focus();
      const initial = liveApi.validateForm(form, validateExtra);
      if (initial.valid) live.calculateNow();
    } else {
      // Calculate-only fallback if the live helper failed to load.
      run.textContent = 'CALCULATE';
      run.addEventListener('click', async (event) => {
        event.preventDefault();
        run.disabled = true;
        run.textContent = 'CALCULATING…';
        try {
          renderSuccess(await calculate(collectParams()));
        } catch (error) {
          renderError(error);
        } finally {
          run.disabled = false;
          run.textContent = 'CALCULATE';
        }
      });
    }
  }
  function makeRightRail(){
    const rail=el('aside','smedley-engineering-rail smedley-engineering-rail--right');rail.id='smedleyEngineeringRight';
    rail.innerHTML=`
      <section class="smedley-engineering-section"><h3>INGEST TO RAG</h3><p class="smedley-engineering-kicker">DROP TO LIBRARY FOLDER — WATCHER INDEXES</p><div class="smedley-engineering-inline"><span>FOLDER</span><button id="smedleyRefreshFolders" type="button">↺</button></div><select id="smedleyLibraryFolder"><option value="">LOADING…</option></select><div class="smedley-engineering-inline"><span>SUBFOLDER</span></div><select id="smedleyLibrarySubfolder" disabled><option value="">SELECT FOLDER FIRST</option></select><div class="smedley-engineering-inline"><span>LEVEL 3</span></div><select id="smedleyLibraryLevel3" disabled><option value="">SELECT SUBFOLDER FIRST</option></select><div class="smedley-engineering-inline"><span>LEVEL 4</span></div><select id="smedleyLibraryLevel4" disabled><option value="">SELECT LEVEL 3 FIRST</option></select><label class="smedley-engineering-drop">DROP FILE TO INGEST<input id="smedleyIngestFile" type="file" hidden></label><div id="smedleyIngestUploadStatus" class="smedley-engineering-note"></div></section>
      <section class="smedley-engineering-section"><h3 class="smedley-engineering-heading-row">INGEST STATUS <span id="smedleyWatcherDot">●</span></h3><div id="smedleyIngestJobs" class="smedley-engineering-ingest-job">⏸ <span>Waiting for watcher event…</span></div><div id="smedleyIngestIdentity" class="smedley-engineering-note"></div><div class="smedley-engineering-heartbeat"><i></i></div><div id="smedleyIngestQueue" class="smedley-ingest-queue"></div><div id="smedleyQuarantine" class="smedley-engineering-note"></div></section>
      <section class="smedley-engineering-section"><h3>NEW LIBRARY FOLDER</h3><p class="smedley-engineering-kicker" id="smedleyNewFolderParent">SELECT A FOLDER TO CREATE A SUBFOLDER</p><div class="smedley-engineering-new-folder"><input id="smedleyNewFolderName" type="text" placeholder="FOLDER NAME"><button id="smedleyCreateFolder" type="button">+</button></div><div id="smedleyFolderStatus" class="smedley-engineering-note"></div></section>
      <section class="smedley-engineering-section"><h3>CORPUS STATUS</h3><div id="smedleyCorpusVectors" class="smedley-engineering-corpus">—</div><div id="smedleyCorpusCollection" class="smedley-engineering-note"></div></section>
      <section class="smedley-engineering-section"><h3>LOW-LATENCY PATH</h3><div class="smedley-engineering-flow">EMBED → QDRANT → SMEDLEY</div><p class="smedley-engineering-help">One Smedley response with memory and continuity.</p></section>`;
    const folder=rail.querySelector('#smedleyLibraryFolder'),subfolder=rail.querySelector('#smedleyLibrarySubfolder'),level3=rail.querySelector('#smedleyLibraryLevel3'),level4=rail.querySelector('#smedleyLibraryLevel4'),upload=rail.querySelector('#smedleyIngestFile'),uploadStatus=rail.querySelector('#smedleyIngestUploadStatus');
    function selectedLibraryFolder(){const parts=[folder.value];if(subfolder.value)parts.push(subfolder.value);if(level3.value)parts.push(level3.value);if(level4.value)parts.push(level4.value);return parts.filter(Boolean).join('/');}
    function refreshNewFolderParent(){const parent=selectedLibraryFolder();const label=rail.querySelector('#smedleyNewFolderParent');if(label)label.textContent=parent?`CREATE IN ${parent.toUpperCase()}`:'CREATE A TOP-LEVEL LIBRARY FOLDER';}
    async function fillChildFolders(select,parent,emptyLabel){select.innerHTML='';select.disabled=true;if(!parent){select.innerHTML=`<option value="">${emptyLabel}</option>`;return;}try{const data=await proxyJson(`/library-folders?parent=${encodeURIComponent(parent)}`);const names=data.folders||[];const root=el('option');root.value='';root.textContent=`${parent.toUpperCase()} (ROOT)`;select.appendChild(root);names.forEach((name)=>{const option=el('option');option.value=name;option.textContent=String(name).toUpperCase();select.appendChild(option);});select.disabled=false;}catch(error){select.innerHTML='<option value="">FOLDER API OFFLINE</option>';}}
    async function refreshLevel4(){const parent=(folder.value&&subfolder.value&&level3.value)?`${folder.value}/${subfolder.value}/${level3.value}`:'';await fillChildFolders(level4,parent,'SELECT LEVEL 3 FIRST');}
    async function refreshLevel3(){const parent=(folder.value&&subfolder.value)?`${folder.value}/${subfolder.value}`:'';await fillChildFolders(level3,parent,'SELECT SUBFOLDER FIRST');await refreshLevel4();}
    async function refreshSubfolders(){const parent=folder.value;subfolder.innerHTML='';subfolder.disabled=true;if(!parent){subfolder.innerHTML='<option value="">SELECT FOLDER FIRST</option>';await refreshLevel3();return;}try{const data=await proxyJson(`/library-folders?parent=${encodeURIComponent(parent)}`);const names=data.folders||[];const root=el('option');root.value='';root.textContent=`${parent.toUpperCase()} (ROOT)`;subfolder.appendChild(root);names.forEach((name)=>{const option=el('option');option.value=name;option.textContent=String(name).toUpperCase();subfolder.appendChild(option);});subfolder.disabled=false;}catch(error){subfolder.innerHTML='<option value="">SUBFOLDER API OFFLINE</option>';}await refreshLevel3();}
    async function refreshFolders(){try{const data=await proxyJson('/library-folders');folder.innerHTML='';(data.folders||[]).forEach((name)=>{const option=el('option');option.value=name;option.textContent=String(name).toUpperCase();folder.appendChild(option);});if(!folder.options.length)folder.innerHTML='<option value="">NO FOLDERS FOUND</option>';await refreshSubfolders();}catch(error){folder.innerHTML='<option value="">FOLDER API OFFLINE</option>';subfolder.innerHTML='<option value="">SUBFOLDER API OFFLINE</option>';subfolder.disabled=true;level3.innerHTML='<option value="">SELECT SUBFOLDER FIRST</option>';level3.disabled=true;level4.innerHTML='<option value="">SELECT LEVEL 3 FIRST</option>';level4.disabled=true;}}
    let __ingestPoll=null;
    function ingestPollMs(status){const red=status&&(status.indicator==='red'||status.status==='active'||status.indicator_state==='ACTIVE');return red?1000:4000;}
    function isActionableIngestCard(row){
      const phase=String(row&&row.phase||'');
      return phase==='failed'||phase==='quarantined';
    }
    function renderQueue(status){
      const box=rail.querySelector('#smedleyIngestQueue');
      const rows=(status&&Array.isArray(status.queue)?status.queue:[]).filter(isActionableIngestCard);
      if(!box) return;
      if(!rows.length){box.innerHTML='<div class="smedley-ingest-empty">No ingest events yet</div>';return;}
      box.innerHTML=rows.slice(0,12).map((row)=>{
        const phase=esc(row.phase||'—');
        const name=esc(row.pub_id||row.basename||'—');
        const folderName=esc(row.folder||row.source||'');
        const when=esc((row.updated_at||'').replace('T',' ').replace('Z',''));
        const chunks=(row.chunks!=null||row.vectors!=null)?esc(String(row.chunks??'—')+' ch / '+(row.vectors??'—')+' vec'):'';
        const reason=row.reason?`<div class="smedley-ingest-reason">${esc(row.reason)}</div>`:'';
        const retry=(row.phase==='quarantined'||row.phase==='failed')?`<button type="button" class="smedley-ingest-retry" data-path="${esc(row.path||'')}">RETRY</button>`:'';
        return `<div class="smedley-ingest-row phase-${phase}"><div class="smedley-ingest-name">${name}</div><div class="smedley-ingest-meta">${phase} · ${folderName}</div><div class="smedley-ingest-meta">${when}${chunks?' · '+chunks:''}</div>${reason}${retry}</div>`;
      }).join('');
      box.querySelectorAll('.smedley-ingest-retry').forEach((btn)=>btn.addEventListener('click',async()=>{
        const path=btn.getAttribute('data-path'); if(!path) return;
        btn.disabled=true; btn.textContent='QUEUED';
        try{await proxyJson('/ingest-retry',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});}
        catch(error){btn.textContent='FAIL';}
        refreshStatus();
      }));
    }
    async function refreshStatus(){try{const health=await proxyJson('/health');const status=await proxyJson('/ingest-status').catch(()=>null);const count=health.vector_count??health.vectors??health.qdrant_vectors??'—';rail.querySelector('#smedleyCorpusVectors').textContent=`${count} VECTORS`;rail.querySelector('#smedleyCorpusCollection').textContent=health.collection||health.qdrant_collection||'jarvis_kb';const jobs=rail.querySelector('#smedleyIngestJobs');const dot=rail.querySelector('#smedleyWatcherDot');const ident=rail.querySelector('#smedleyIngestIdentity');const stale=!status||!status.heartbeat||((Date.now()/1000)-Number(status.heartbeat)>90);const red=!!(status&&(status.indicator==='red'||status.status==='active'||status.indicator_state==='ACTIVE'||status.indicator_state==='ALARM'||stale));const file=status&&(status.last_file||'');const phase=status&&(status.current_phase||status.indicator_state||'');const reason=status&&status.last_error;jobs.className='smedley-engineering-ingest-job'+(red?' live-red':' live-green');jobs.innerHTML=red?`● <span>${esc(status&&status.indicator_state||'ACTIVE')} · ${esc(file||phase||'processing')}</span>`:`● <span>${esc(phase==='indexed'?'INDEXED':(status&&status.indicator_state)||'RUNNING')}</span>`;dot.className=red?'live-red':'ok';ident.textContent=file?`${file}${phase?' · '+phase:''}${reason?' · '+reason:''}`:'';renderQueue(status);const q=status&&(status.quarantine_count??status.quarantined);rail.querySelector('#smedleyQuarantine').textContent=q?`${q} quarantined — listed in queue, not hidden by idle`:'';if(__ingestPoll) clearInterval(__ingestPoll);__ingestPoll=setInterval(refreshStatus,ingestPollMs(status));}catch(error){rail.querySelector('#smedleyCorpusVectors').textContent='CORPUS OFFLINE';}}
    rail.querySelector('#smedleyRefreshFolders').addEventListener('click',refreshFolders);
    folder.addEventListener('change',async()=>{await refreshSubfolders();refreshNewFolderParent();});
    subfolder.addEventListener('change',async()=>{await refreshLevel3();refreshNewFolderParent();});
    level3.addEventListener('change',async()=>{await refreshLevel4();refreshNewFolderParent();});
    level4.addEventListener('change',refreshNewFolderParent);
    upload.addEventListener('change',async()=>{const file=upload.files[0];if(!file)return;const dest=selectedLibraryFolder();if(!dest){uploadStatus.textContent='Select a RAG Pool library folder first.';upload.value='';return;}const body=new FormData();body.append('file',file);uploadStatus.textContent=`Uploading ${file.name} → ${dest}…`;try{const response=await fetch(`${RAG_PROXY}/ingest-upload?folder=${encodeURIComponent(dest)}`,{method:'POST',body});if(!response.ok)throw new Error(`HTTP ${response.status}`);const payload=await response.json().catch(()=>({}));uploadStatus.textContent=`Queued ${payload.filename||file.name} in ${payload.destination||('Library/'+dest)}`;}catch(error){uploadStatus.textContent=`Ingest upload failed: ${error.message||error}`;}upload.value='';refreshStatus();});
    rail.querySelector('#smedleyCreateFolder').addEventListener('click',async()=>{const input=rail.querySelector('#smedleyNewFolderName'),leaf=input.value.trim(),parent=selectedLibraryFolder(),name=[parent,leaf].filter(Boolean).join('/');if(!leaf)return;try{await proxyJson('/library-folders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});rail.querySelector('#smedleyFolderStatus').textContent=`Created ${name}`;input.value='';await refreshFolders();folder.value=parent.split('/')[0]||'';await refreshSubfolders();refreshNewFolderParent();}catch(error){rail.querySelector('#smedleyFolderStatus').textContent=`Create failed: ${error.message||error}`;}});
    refreshFolders();refreshNewFolderParent();refreshStatus();return rail;
  }

  let __docRouteBusy=false;
  function isDocumentLinkRequest(text){
    // Natural-language asks to find/pull/open/provide/link engineering documents.
    const msg=String(text||'').trim();
    if(!msg || msg.length>4000) return false;
    if(msg.startsWith('/')) return false;
    if(msg.includes('<retrieved_library_context>')) return false;
    const noun=/\b(?:documents?|docs?|specs?(?:ification)?s?|manuals?|datasheets?|pdfs?|drawings?|prints?|procedures?|standards?|wiring|schematics?)\b/i;
    const verb=/\b(?:pull|get|fetch|find|locate|open|show|send|give|provide|bring|grab|retrieve|look\s*up|lookup|search\s+for|need|want)\b/i;
    const linkAsk=/\b(?:(?:give|send|provide|get|need|want|show)\s+(?:me\s+)?(?:a\s+|the\s+)?(?:link|url|href|preview)|(?:link|url)\s+to)\b/i;
    const docnum=/\b\d{2}-?\d{3}\b/;
    const hwPart=/\b(?:MU\s*\/\s*MC|MC\s*\/\s*MU|MU|MC)[- ]?[A-Z]{2,6}\d{2,}[A-Z]?\b/i;
    const abPart=/\b(?:1756|1769|1794|5094)[- ]?[A-Z0-9]{2,}\b/i;
    const fileExt=/\b[\w./\\ -]+\.(?:pdf|docx?|xlsx?|pptx?|txt|md)\b/i;
    if(verb.test(msg) && noun.test(msg)) return true;
    if(/\b(?:need|want)\b/i.test(msg) && noun.test(msg)) return true;
    if(linkAsk.test(msg) && (noun.test(msg) || docnum.test(msg))) return true;
    if(verb.test(msg) && (docnum.test(msg) || fileExt.test(msg))) return true;
    if(docnum.test(msg) && /\b(?:document|doc|spec|pdf|link|url|preview|pull|find|open)\b/i.test(msg)) return true;
    if(hwPart.test(msg)) return true;
    if(linkAsk.test(msg)) return true;
    return false;
  }
  function isEngineeringFactRequest(text){
    const msg=String(text||'').trim();
    if(!msg || msg.length>1200 || msg.startsWith('/')) return false;
    if(/\bask\s+jarvis\b/i.test(msg)) return false;
    const chassis=/(?:controllogix|allen[- ]?bradley|rockwell|1756).{0,100}(?:power\s+suppl(?:y|ies)|psu|chassis|watt(?:age)?s?|redundan(?:t|cy)|slots?)|(?:power\s+suppl(?:y|ies)|psu|chassis|watt(?:age)?s?|redundan(?:t|cy)|slots?).{0,100}(?:controllogix|allen[- ]?bradley|rockwell|1756)|(?:which\s+power\s+suppl(?:y|ies)|chassis\s+(?:power|sizing|selection)|1756-P[AB]\w*)/i;
    if(chassis.test(msg)) return true;
    if(/^\s*\d{1,2}\s*-?\s*slots?\s*[.?]?\s*$/i.test(msg)) return true;
    const part=/\b(?:(?:MU|MC)[- ]?[A-Z]{2,6}\d{2,}[A-Z]?|(?:1756|1769|1794|5094)[- ]?[A-Z0-9]{2,})\b/i;
    const fact=/\b(?:fuse|fusing|fused|amp(?:ere)?s?|rating|rated|voltage|volts?|current|channel|compatible|compatibility|match(?:es|ing)?|ifm|interface\s+modules?|pre-?wired|cables?|terminals?|catalog|internal\s+fus|power\s+suppl(?:y|ies)|psu|chassis|watt(?:age)?s?|redundan(?:t|cy)|slots?)\w*\b/i;
    const ask=/\b(?:what|which|where|how|is|are|need)\b|\?/i;
    return part.test(msg) && fact.test(msg) && ask.test(msg);
  }
  let __smedleyAckUntil=0;
  function speakSmedleyNow(text, opts){
    const spoken=String(text||'').trim();
    if(!spoken) return Promise.resolve();
    const holdMs=Math.max(0, Number((opts&&opts.holdMs)||0));
    if(holdMs) __smedleyAckUntil=Date.now()+holdMs;
    return proxyJson('/speak',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:spoken})}).catch((err)=>{
      console.warn('smedley speak failed', err);
    });
  }
  function whenAckClear(){
    const wait=Math.max(0, __smedleyAckUntil-Date.now());
    return wait?new Promise((resolve)=>setTimeout(resolve, wait)):Promise.resolve();
  }

  let __smedleyAckArmedUntil=0;
  function maybeAckDocumentIntent(){
    const composer=document.getElementById('msg');
    const q=(composer&&composer.value||'').trim();
    if(!q) return false;
    if(/\bask\s+jarvis\b/i.test(q)) return false;
    if(!(isDocumentLinkRequest(q) || isEngineeringFactRequest(q))) return false;
    const now=Date.now();
    if(now < __smedleyAckArmedUntil) return true; // already acked this submit
    __smedleyAckArmedUntil=now+1500;
    const note=document.getElementById('smedleyHeaderNote')||{textContent:''};
    note.textContent='Working on that now…';
    speakSmedleyNow('Working on that now.',{holdMs:2200});
    return true;
  }
  function installDocumentIntentRouting(){
    if(window.__smedleyDocIntentRouting) return;
    const original=typeof window.send==='function'?window.send:null;
    if(!original) return;
    window.__smedleyDocIntentRouting=true;
    window.send=function(){
      if(__docRouteBusy) return original.apply(this, arguments);
      maybeAckDocumentIntent();
      return original.apply(this, arguments);
    };
    // Capture-phase safety net: Enter / send button must still get immediate ack
    // even if some code path calls the unbound original send() binding.
    document.addEventListener('keydown', (e)=>{
      if(e.key!=='Enter' || e.shiftKey) return;
      const t=e.target;
      if(!t || t.id!=='msg') return;
      maybeAckDocumentIntent();
    }, true);
    document.addEventListener('click', (e)=>{
      const t=e.target && e.target.closest ? e.target.closest('#sendBtn, button#send, button[aria-label="Send"]') : null;
      if(!t) return;
      maybeAckDocumentIntent();
    }, true);
  }

  function retrieveFromComposer(note){
    const composer=document.getElementById('msg'),q=(composer&&composer.value||'').trim();
    if(!q){note.textContent='Type the engineering question in the Smedley message box first.';return;}
    if(__docRouteBusy)return;
    note.textContent='Working on that now…';
    __docRouteBusy=true;
    speakSmedleyNow('Working on that now.',{holdMs:2200});
    // Prefer the server document_route path (deterministic index hit + compact speak).
    try{
      composer.value=q;
      composer.dispatchEvent(new Event('input',{bubbles:true}));
      if(typeof window.send==='function'){
        // Temporarily clear busy so installDocumentIntentRouting / original send can run.
        __docRouteBusy=false;
        window.send();
        note.textContent='Document route submitted.';
        return;
      }
    }catch(err){
      console.warn('document route send failed; falling back', err);
    }
    // Retrieval must traverse the shared WebUI document route, which calls the
    // Jarvis n8n gateway.  Never fall back to a browser-to-RAG request here.
    __docRouteBusy=false;
    note.textContent='Document route unavailable. Retry the request from the Smedley message box.';
    return;
  }

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
        if(/^Switching to (?:Headset|Room)…$/.test(note.textContent||'')){
          note.textContent='';
        }
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
      // NOTE: voice-emitter ownership is decided solely by the per-message
      // ptt_owned_tts/tts_owner stamp (see selectSmedleyVoiceEmitter in
      // realtime_voice.js). A blanket window here keyed off "pedal busy for
      // any reason" previously silenced Austin on unrelated GUI/typed turns
      // (confirmed root cause, 2026-08-18) — do not reintroduce it.
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
        await proxyJson('/ptt/active-session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sid,instance:PTT_INSTANCE,gui_id:GUI_ID})});
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
          // Initial-load only: if Glass is on a dead SID but PTT already holds a
          // replacement completion SID, migrate once. Never replay old completion
          // when there is no current URL SID, and never redirect when current is valid.
          if(
            sid
            &&completionSid
            &&completionSid!==sid
            &&typeof loadSession==='function'
          ){
            let currentMissing=false;
            try{
              const data=await jsonRequest(`/api/session?session_id=${encodeURIComponent(sid)}&messages=0&resolve_model=0`);
              if(!(data&&data.session))currentMissing=true;
            }catch(error){
              const status=Number(error&&error.status);
              const msg=String(error&&error.message||error||'');
              currentMissing=status===404||/\b404\b|missing|not found/i.test(msg);
            }
            if(currentMissing){
              await loadSession(completionSid,{force:true,externalRefreshReason:'ptt-stale-session-recovery'});
              postedSession='';
            }
          }
          return;
        }
        if(
          completionSid
          &&completionTimestamp>lastCompletionTimestamp
          &&typeof loadSession==='function'
        ){
          lastCompletionTimestamp=completionTimestamp;
          const eventGui=String(status.gui_id||status.completion_instance||'');
          if(eventGui&&eventGui!==GUI_ID&&eventGui!==PTT_INSTANCE)return;
          if(status.completion_instance&&String(status.completion_instance)!==PTT_INSTANCE)return;
          // Ownership for voice arbitration comes from the loaded session's
          // own ptt_owned_tts/tts_owner message stamp, not a global timer.
          const loadSess=(typeof window.loadSession==='function')?window.loadSession:(typeof loadSession==='function'?loadSession:null);
          if(completionSid&&loadSess){
            await loadSess(completionSid,{force:true,externalRefreshReason:'ptt-completion',guiId:GUI_ID});
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

  function makeHeader(left,right){const header=el('div','smedley-engineering-header');header.innerHTML='<img class="smedley-engineering-ega" src="/extensions/smedley-engineering/ega.jpg" alt="EGA"><div class="smedley-engineering-heading"><div class="smedley-engineering-title">SMEDLEY BUTLER\'S RAG CALL</div><div class="smedley-engineering-subtitle">JARVIS INTELLIGENCE PLATFORM · SMEDLEY MEMORY · SMEDLEY</div></div><img class="smedley-engineering-ega" src="/extensions/smedley-engineering/ega.jpg" alt="EGA"><div class="smedley-engineering-status"><span id="smedleyRagBadge" class="smedley-engineering-badge">RAG</span><span id="smedleyToolsBadge" class="smedley-engineering-badge">TOOLS</span><button id="smedleyPtt" type="button" data-testid="smedley-ptt">● PTT</button><button id="smedleyAudioRoute" type="button" data-testid="smedley-audio-route">ROOM</button><span class="smedley-engineering-drawer-btns"><button type="button" data-drawer="left">Project</button><button type="button" data-drawer="right">Corpus</button></span></div><div id="smedleyHeaderNote" class="smedley-engineering-header-note"></div>';
    header.querySelectorAll('[data-drawer]').forEach((button)=>button.addEventListener('click',()=>{const target=button.dataset.drawer==='left'?left:right;target.classList.toggle('open');}));
    async function status(){const rag=header.querySelector('#smedleyRagBadge'),tools=header.querySelector('#smedleyToolsBadge');try{const value=await proxyJson('/health');rag.classList.toggle('ok',!!(value.api_alive&&value.lmstudio_reachable&&value.embed_model_loaded&&value.qdrant_reachable));rag.classList.toggle('down',!rag.classList.contains('ok'));}catch(_){rag.classList.add('down');rag.classList.remove('ok');}try{const value=await proxyJson('/tools/health');tools.classList.toggle('ok',value.status==='ok');tools.classList.toggle('down',value.status!=='ok');}catch(_){tools.classList.add('down');tools.classList.remove('ok');}}
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

  const BRANDING_EXCLUDE_SEL='script,style,textarea,input,select,option,pre,code,[contenteditable="true"],.messages,.messages-shell,#msgInner,.message,.msg-content,.composer-wrap,#msg,.model-select,#modelSelect,.model-picker,.smedley-engineering-rail,.smedley-engineering-header,.smedley-engineering-tools-dock';
  const BRANDING_ATTRS=['title','aria-label','placeholder','alt'];
  const BRANDING_SCAN_SEL=['.sidebar','.rightpanel','.layout','.session-list','.composer-footer','header','nav','main'];
  const SMEDLEY_DOC_TITLE='Smedley Engineering Workspace';
  let brandingLock=false;

  function brandVisibleText(value){
    if(typeof value!=='string'||!value||!/hermes/i.test(value))return value;
    return value.replace(/\bHERMES\b/g,'SMEDLEY').replace(/\bHermes\b/g,'Smedley').replace(/\bhermes\b/g,'smedley');
  }

  function isBrandingExcluded(node){
    if(!node)return true;
    if(node.nodeType===Node.TEXT_NODE)return isBrandingExcluded(node.parentElement);
    if(node.nodeType!==Node.ELEMENT_NODE)return true;
    return !!node.closest(BRANDING_EXCLUDE_SEL);
  }

  function withBrandingLock(fn){
    if(brandingLock)return;
    brandingLock=true;
    try{fn();}finally{brandingLock=false;}
  }

  function brandAttributes(element){
    if(!element||element.nodeType!==Node.ELEMENT_NODE||isBrandingExcluded(element))return;
    BRANDING_ATTRS.forEach((attr)=>{
      if(!element.hasAttribute(attr))return;
      const raw=element.getAttribute(attr);
      const next=brandVisibleText(raw);
      if(next!==raw)element.setAttribute(attr,next);
    });
  }

  function brandTextNodes(root){
    if(!root)return;
    const hits=[];
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,{acceptNode(node){
      if(!node.nodeValue||!/hermes/i.test(node.nodeValue))return NodeFilter.FILTER_REJECT;
      if(isBrandingExcluded(node))return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    }});
    while(walker.nextNode())hits.push(walker.currentNode);
    hits.forEach((node)=>{const next=brandVisibleText(node.nodeValue);if(next!==node.nodeValue)node.nodeValue=next;});
  }

  function brandSubtree(root){
    if(!root)return;
    if(root.nodeType===Node.ELEMENT_NODE){
      brandAttributes(root);
      brandTextNodes(root);
      return;
    }
    if(root.nodeType===Node.TEXT_NODE){
      brandTextNodes(root.parentElement||document.body);
      return;
    }
    root.childNodes.forEach(brandSubtree);
  }

  function brandingScanRoots(){
    const roots=[];
    BRANDING_SCAN_SEL.forEach((selector)=>{
      document.querySelectorAll(selector).forEach((node)=>roots.push(node));
    });
    if(!roots.length&&document.body)roots.push(document.body);
    return roots;
  }

  function installDocumentTitleBranding(){
    const branded=brandVisibleText(document.title);
    document.title=branded&&branded!==document.title?branded:(document.title&&/smedley/i.test(document.title)?document.title:SMEDLEY_DOC_TITLE);
  }

  function installComposerBranding(){
    const composer=document.getElementById('msg');
    if(!composer)return;
    const apply=()=>{
      if(composer.getAttribute('placeholder')!=='Message Smedley'){
        composer.setAttribute('placeholder','Message Smedley');
      }
    };
    apply();
    new MutationObserver(apply).observe(composer,{attributes:true,attributeFilter:['placeholder']});
  }

  function installSmedleyVoiceOutput(){
    const original=typeof window.autoReadLastAssistant==='function'?window.autoReadLastAssistant:null;
    let lastSpokenKey='';
    function voiceSafeText(raw){
      const value=String(raw||'').trim();
      if(!value)return '';
      // ui.js owns the canonical speech sanitizer.  This override sends audio
      // through Smedley, so it must sanitize before calling /speak as well.
      if(typeof window._stripForTTS==='function'){
        try{return String(window._stripForTTS(value)||'').trim();}catch(_){}
      }
      // Defensive fallback for load-order races: retain markdown labels, never
      // hand a raw sidecar URL or document-route chrome to normal voice.
      return value
        .replace(/(^|\n)[ \t]*Document links[^\n]*:?/gi,'$1')
        .replace(/\[([^\]]+)\]\((?:https?:\/\/|\/api\/extensions\/)[^)]+\)/gi,'$1')
        .replace(/https?:\/\/\S+/gi,'')
        .replace(/\/api\/extensions\/smedley-engineering\/sidecar\/\S+/gi,'')
        .replace(/\b(?:sidecar preview|card title|lan_url)\s*:?\s*[^\n]*/gi,'')
        .replace(/\s{2,}/g,' ').trim();
    }
    function _fallbackLastAssistantPttOwned(){
      try{
        const msgs=(typeof S!=='undefined'&&Array.isArray(S.messages))?S.messages:[];
        for(let i=msgs.length-1;i>=0;i--){
          const m=msgs[i];
          if(!m||m.role!=='assistant')continue;
          return !!(m.ptt_owned_tts||m.tts_owner==='pedal_austin');
        }
      }catch(_){}
      return false;
    }
    window.autoReadLastAssistant=function(){
      // Load-order fallback (realtime_voice.js not yet loaded) checks the
      // same per-message ptt_owned_tts/tts_owner stamp directly — never a
      // global busy-heartbeat window, which silenced unrelated GUI turns.
      const emitter=(typeof window.selectSmedleyVoiceEmitter==='function')
        ? window.selectSmedleyVoiceEmitter({realtimeActive:!!window.__smedleyRealtimeVoiceActive})
        : (_fallbackLastAssistantPttOwned() ? 'none' : 'austin');
      if(emitter==='none') return;
      if(emitter!=='austin') return;
      // Prefer compact spoken_text / spoken_reply — never narrate full RAG body.
      let spoken='';
      let fromServerSpoken=false;
      try{
        if(window.__smedleyDocSpokenReply){
          spoken=String(window.__smedleyDocSpokenReply||'').trim();
          window.__smedleyDocSpokenReply='';
        }
      }catch(_){}
      try{
        const msgs=(typeof S!=='undefined'&&Array.isArray(S.messages))?S.messages:[];
        for(let i=msgs.length-1;i>=0;i--){
          const m=msgs[i];
          if(!m||m.role!=='assistant') continue;
          if(m.document_route||m.active_document_review||m.engineering_rag_answer||m.spoken_reply||m.spoken_text){
            spoken=String(m.spoken_text||m.spoken_reply||'').trim();
            fromServerSpoken=!!spoken;
          }
          break;
        }
      }catch(_){}
      const rows=document.querySelectorAll('.msg-row[data-role="assistant"], .assistant-segment[data-raw-text]');
      const last=rows.length?rows[rows.length-1]:null;
      const text=String(last&&last.dataset&&last.dataset.rawText||'').trim();
      // Never TTS the operator markdown body when a document_route turn is present.
      let isDocRoute=false;
      try{
        const msgs=(typeof S!=='undefined'&&Array.isArray(S.messages))?S.messages:[];
        for(let i=msgs.length-1;i>=0;i--){
          const m=msgs[i];
          if(!m||m.role!=='assistant') continue;
          isDocRoute=!!(m.document_route||m.active_document_review||m.engineering_rag_answer||m.spoken_reply);
          break;
        }
      }catch(_){}
      if(!spoken && !isDocRoute) spoken=voiceSafeText(text);
      if(!spoken && isDocRoute) spoken='The manual is on screen.';
      // Server spoken_text is already complete and <=400. Do not ellipsis-cut the closer.
      if(!fromServerSpoken){
        if(spoken.length>420){
          const cut=spoken.slice(0,417);
          const sp=cut.lastIndexOf(' ');
          spoken=(sp>280?cut.slice(0,sp):cut).trim();
        }
      }
      if(spoken){
        // Strip residual markdown / link chrome before TTS.
        spoken=spoken
          .replace(/\[([^\]]+)\]\([^)]+\)/g,'$1')
          .replace(/[*_`#]+/g,' ')
          .replace(/https?:\/\/\S+/g,'')
          .replace(/\/api\/extensions\/\S+/g,'')
          .replace(/\s{2,}/g,' ')
          .trim();
        if(!fromServerSpoken && spoken.length>400){
          const cut=spoken.slice(0,397);
          const sp=cut.lastIndexOf(' ');
          spoken=(sp>280?cut.slice(0,sp):cut).trim();
        }
        const asstId=(()=>{try{
          const msgs=(typeof S!=='undefined'&&Array.isArray(S.messages))?S.messages:[];
          for(let i=msgs.length-1;i>=0;i--){
            const m=msgs[i];
            if(m&&m.role==='assistant') return String(m.id||m.timestamp||spoken);
          }
        }catch(_){} return spoken;})();
        const key=`${currentHermesSessionId()}|${asstId}|${spoken}`;
        if(key!==lastSpokenKey){
          lastSpokenKey=key;
          whenAckClear().then(()=>proxyJson('/speak',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:spoken})})).catch(()=>{
            lastSpokenKey='';
            const note=document.getElementById('smedleyHeaderNote');
            if(note)note.textContent='Smedley voice unavailable — Austin did not play; no substitute voice.';
          });
        }
      }
      return;
    };
  }

  // Smedley remains the host surface, but a response produced by the explicit
  // Jarvis route must be visibly attributed to Jarvis.  The shared renderer
  // only has one global assistant display name, so annotate the completed turn
  // from its persisted message metadata rather than changing every Smedley
  // response label.
  function labelJarvisResponses(root){
    try{
      const messages=(typeof S!=='undefined'&&Array.isArray(S.messages))?S.messages:[];
      const scope=root&&root.querySelectorAll?root:document;
      scope.querySelectorAll('.assistant-segment[data-msg-idx]').forEach((segment)=>{
        const idx=Number(segment.dataset.msgIdx);
        const message=Number.isFinite(idx)?messages[idx]:null;
        const visible=String(segment.dataset.rawText||segment.textContent||'');
        const isJarvis=!!(message&&(
          String(message.assistant_identity||'').toLowerCase()==='jarvis'
          ||message.jarvis_response===true||message.ask_jarvis_hard_bind
        ))
          ||/^\s*(?:\*\*)?Jarvis\s*:/i.test(visible);
        if(!isJarvis)return;
        const turn=segment.closest('.assistant-turn');
        const role=turn&&turn.querySelector('.msg-role.assistant');
        if(!role)return;
        const name=role.querySelector('.msg-role-name');
        const icon=role.querySelector('.role-icon.assistant');
        if(name)name.textContent='Jarvis';
        if(icon)icon.textContent='J';
        if(turn)turn.dataset.responseAgent='jarvis';
      });
    }catch(_){}
  }

  function installBrandingObserver(){
    installDocumentTitleBranding();
    withBrandingLock(()=>{brandingScanRoots().forEach(brandSubtree);labelJarvisResponses(document);});
    const observer=new MutationObserver((mutations)=>{
      withBrandingLock(()=>{
        mutations.forEach((mutation)=>{
          if(mutation.type==='characterData'){
            const node=mutation.target;
            if(node&&/hermes/i.test(node.nodeValue||'')&&!isBrandingExcluded(node)){
              const next=brandVisibleText(node.nodeValue);
              if(next!==node.nodeValue)node.nodeValue=next;
            }
            return;
          }
          if(mutation.type==='childList'){
            mutation.addedNodes.forEach(brandSubtree);
            labelJarvisResponses(document);
            return;
          }
          if(mutation.type==='attributes'&&BRANDING_ATTRS.includes(mutation.attributeName||'')){
            brandAttributes(mutation.target);
          }
        });
      });
    });
    observer.observe(document.documentElement,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:BRANDING_ATTRS});
  }

  function devVersionBase(value){
    return String(value||'').trim().replace(/-dirty(?:-[0-9a-f]+)?$/i,'');
  }

  function suppressDirtyHashOnlyRefreshWarning(){
    const banner=document.getElementById('staleClientBanner');
    const versions=document.getElementById('staleClientVersions');
    if(!banner||!versions)return;
    const text=String(versions.textContent||'');
    const match=text.match(/^Running:\s*(.+?)\s*(?:→|->)\s*Server:\s*(.+?)\s*$/i);
    if(!match)return;
    const client=match[1].trim(),server=match[2].trim();
    if(client===server)return;
    if(!/-dirty(?:-[0-9a-f]+)?$/i.test(client)||!/-dirty(?:-[0-9a-f]+)?$/i.test(server))return;
    if(!devVersionBase(client)||devVersionBase(client)!==devVersionBase(server))return;
    banner.style.display='none';
    banner.dataset.smedleySuppressedDirtySkew='true';
  }

  function installDirtyHashRefreshGuard(){
    suppressDirtyHashOnlyRefreshWarning();
    const banner=document.getElementById('staleClientBanner');
    if(!banner)return;
    new MutationObserver(suppressDirtyHashOnlyRefreshWarning).observe(
      banner,{attributes:true,attributeFilter:['style'],childList:true,subtree:true,characterData:true}
    );
  }

  const DIAG_FLAG_KEY=`hermes-gui-debug:${GUI_ID}`;
  function diagnosticsEnabled(){
    try{
      const params=new URLSearchParams(location.search||'');
      if(params.get('hermes_gui_debug')==='1'||params.get('debug')==='1')return true;
    }catch(_){}
    try{return localStorage.getItem(DIAG_FLAG_KEY)==='1';}catch(_){}
    return false;
  }
  function setDiagnosticsEnabled(on){
    try{if(on)localStorage.setItem(DIAG_FLAG_KEY,'1');else localStorage.removeItem(DIAG_FLAG_KEY);}catch(_){}
  }
  function collectGuiDiagnosticsText(){
    const sid=(typeof currentHermesSessionId==='function'&&currentHermesSessionId())||'(none)';
    return `guiId=${GUI_ID} profile=smedley channel=${RAG_PROXY}/ptt/status backend=${location.origin} sessionId=${sid}`;
  }
  function stampGuiIdentity(){
    document.body.dataset.guiId=GUI_ID;
    document.documentElement.dataset.guiId=GUI_ID;
    document.body.dataset.profileId='smedley';
    document.documentElement.dataset.profileId='smedley';
    document.body.dataset.guiDiagnostics=collectGuiDiagnosticsText();
  }
  function ensureGuiDiagnosticsOverlay(){
    let node=document.getElementById('smedleyGuiDiagnostics');
    if(node)return node;
    node=document.createElement('details');
    node.id='smedleyGuiDiagnostics';
    node.className='smedley-gui-diagnostics';
    node.style.cssText='position:fixed;left:8px;bottom:max(12px, env(safe-area-inset-bottom, 0px));z-index:20;max-width:min(42vw,380px);max-height:28vh;overflow:auto;pointer-events:auto;';
    const summary=document.createElement('summary');
    summary.textContent='Diagnostics';
    summary.style.cssText='cursor:pointer;list-style:none;padding:4px 8px;border:1px solid #3a4657;border-radius:6px;background:rgba(13,17,23,.72);color:#8aa4c0;font:11px/1.2 ui-monospace,monospace;';
    const body=document.createElement('pre');
    body.id='smedleyGuiDiagnosticsBody';
    body.style.cssText='margin:4px 0 0;padding:6px 8px;border:1px solid #3a4657;border-radius:6px;background:rgba(13,17,23,.92);color:#9ecbff;font:11px/1.35 ui-monospace,monospace;white-space:pre-wrap;';
    node.appendChild(summary);node.appendChild(body);
    node.addEventListener('toggle',()=>{
      setDiagnosticsEnabled(node.open);
      if(!node.open)node.remove();
      else refreshGuiDiagnostics();
    });
    document.body.appendChild(node);
    return node;
  }
  function refreshGuiDiagnostics(){
    stampGuiIdentity();
    if(!diagnosticsEnabled()){
      const stale=document.getElementById('smedleyGuiDiagnostics');
      if(stale)stale.remove();
      return;
    }
    const node=ensureGuiDiagnosticsOverlay();
    const body=document.getElementById('smedleyGuiDiagnosticsBody');
    if(body)body.textContent=collectGuiDiagnosticsText();
    node.hidden=false;node.open=true;
  }
  function installGuiDiagnostics(){
    stampGuiIdentity();
    if(!diagnosticsEnabled()){
      const stale=document.getElementById('smedleyGuiDiagnostics');
      if(stale)stale.remove();
      return;
    }
    refreshGuiDiagnostics();
  }
  function installDiagnosticsHotkey(){
    if(window.__smedleyDiagHotkey)return;
    window.__smedleyDiagHotkey=true;
    let clicks=0,timer=null;
    document.addEventListener('click',(event)=>{
      if(!event.altKey)return;
      const target=event.target;
      if(!(target instanceof Element))return;
      if(!target.closest('.smedley-engineering-title,.smedley-engineering-heading'))return;
      clicks+=1;clearTimeout(timer);timer=setTimeout(()=>{clicks=0;},900);
      if(clicks<3)return;clicks=0;
      setDiagnosticsEnabled(!diagnosticsEnabled());
      installGuiDiagnostics();
    },true);
  }
  function init(){installBrandingObserver();installGuiDiagnostics();installDirtyHashRefreshGuard();const layout=document.querySelector('.layout');const main=document.querySelector('main.main');const mainChat=document.getElementById('mainChat');const rightPanel=document.querySelector('.rightpanel');if(!layout||!main||!mainChat)return;installComposerBranding();installSmedleyVoiceOutput();installCorpusLinkFix();installDocumentIntentRouting();warmModelsOnOpen();const left=makeLeftRail(),right=makeRightRail();layout.insertBefore(left,main);layout.insertBefore(right,rightPanel||null);mainChat.classList.add('smedley-engineering-iwo');mainChat.insertBefore(makeHeader(left,right),mainChat.firstChild);mainChat.appendChild(makeToolsDock());installOperatorChip();const msgInner=document.getElementById('msgInner');if(msgInner){removeHermesCenterPlaceholders();new MutationObserver(removeHermesCenterPlaceholders).observe(msgInner,{childList:true,subtree:true});}const sync=()=>{const shown=getComputedStyle(mainChat).display!=='none';left.hidden=!shown;right.hidden=!shown;if(!shown){left.classList.remove('open');right.classList.remove('open');}};new MutationObserver(sync).observe(mainChat,{attributes:true,attributeFilter:['class','style','hidden']});sync();}
  // Biggy uses this exact calculator runtime through its Tools rail.  Its own
  // cockpit owns the surrounding layout, so expose the real tool entry points
  // but do not build Smedley's rails, panes, or composer a second time.
  window.SmedleyEngineeringTools=Object.freeze({
    tools:TOOLS.map(([id,label,group])=>Object.freeze({id,label,group})),
    open(toolId){
      const tool=TOOLS.find(([id])=>id===String(toolId||''));
      if(!tool)throw new Error(`Unknown Smedley engineering tool: ${toolId}`);
      return openTool(tool);
    },
  });
  if(!TOOLS_ONLY_EMBED){
    if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
  }
})();
