/* Shared in-GUI document windows. Modules may opt out with data-document-external. */
(() => {
  'use strict';
  // Allow a cache-busted import to replace a stale viewer that lacks presentation
  // support. Skip only when an already-capable viewer is installed.
  if (window.BiggyDocumentViewer && window.BiggyDocumentViewer.supportsPresentation) return;
  const viewers = new Set();
  let layer = 100000;
  const oldRoot = '/api/extensions/smedley-engineering/sidecar/';
  function documentURL(value) {
    let url;
    try { url = new URL(value, location.href); } catch (_) { return null; }
    if (url.origin !== location.origin) return null;
    if (url.pathname.startsWith(oldRoot)) url.pathname = '/api/biggy/rag/' + url.pathname.slice(oldRoot.length);
    const path = url.pathname;
    const evidenceOk = /^\/(?:biggy-workspace\/)?api\/v1\/evidence\/ev_[A-Za-z0-9]+\/(?:original(?:\.(?:png|jpe?g|webp))?|analysis(?:\.txt)?)$/.test(path);
    const presentationOk = /^\/api\/presentation\/file\/prv_[A-Za-z0-9_-]+$/.test(path);
    if (!evidenceOk && !presentationOk &&
        !/^\/api\/biggy\/rag\/(doc|preview)\//.test(path) &&
        !/^\/api\/biggy\/rag-file(?:-path\/|$)/.test(path) &&
        !path.startsWith('/api/jarvis-ii/rag-document/') &&
        !/\.(pdf|txt|docx?|rtf|xlsx?|pptx?|png|jpe?g|webp|gif|mp4|webm)(?:$)/i.test(path)) return null;
    return url.href;
  }
  if (!document.getElementById('biggy-document-viewer-style')) {
    const style = document.createElement('style');
    style.id = 'biggy-document-viewer-style';
    style.textContent = `
.biggy-document-window{position:fixed;display:flex;flex-direction:column;box-sizing:border-box;min-width:0;min-height:0;background:#182a39;color:#edf5fb;border:1px solid #62899f;border-radius:9px;box-shadow:0 12px 45px #0009;overflow:hidden;font:14px system-ui}
.biggy-document-header{display:flex;align-items:center;gap:12px;padding:8px 12px;min-height:36px;cursor:move;touch-action:none;background:#142230;flex-shrink:0}
.biggy-document-title{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin:0;font:600 14px system-ui}
.biggy-document-close{color:#fff;background:#29485b;border:1px solid #7196aa;border-radius:4px;min-height:32px;padding:4px 12px;cursor:pointer}
.biggy-document-frame{flex:1;width:100%;min-height:0;border:0;background:white}
.biggy-document-resize{position:absolute;bottom:0;right:0;width:24px;height:24px;background:#29485b;color:white;border:0;border-top-left-radius:5px;cursor:nwse-resize;touch-action:none;font-size:18px}
`;
    document.head.append(style);
  }
  function open(value, title, opener) {
    const url = documentURL(value);
    if (!url) return false;
    // Workspace iframes share the shell's viewer rather than clipping a popup
    // to their own calendar frame. A standalone embed gets the same component.
    try {
      if (parent !== window && parent.location.origin === location.origin && parent.BiggyDocumentViewer) {
        return parent.BiggyDocumentViewer.open(url, title, opener);
      }
    } catch (_) { /* An unrelated parent cannot receive document access. */ }
    const panel = document.createElement('section');
    panel.className = 'biggy-document-window';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Document viewer');
    panel.setAttribute('data-testid', 'biggy-document-viewer');
    const header = document.createElement('div'); header.className = 'biggy-document-header';
    header.tabIndex = 0; header.setAttribute('aria-label', 'Move document window');
    const heading = document.createElement('h2'); heading.className = 'biggy-document-title';
    try { heading.textContent = title || decodeURIComponent(new URL(url).pathname.split('/').pop()); }
    catch (_) { heading.textContent = title || 'Document'; }
    const close = document.createElement('button'); close.type = 'button'; close.className = 'biggy-document-close'; close.textContent = 'Close document';
    const frame = document.createElement('iframe'); frame.className = 'biggy-document-frame'; frame.title = heading.textContent; frame.referrerPolicy = 'same-origin';
    if(new URL(url).pathname.includes('/preview/')) frame.setAttribute('sandbox','allow-same-origin');
    const isPresentationVideo = /^\/api\/presentation\/file\//.test(new URL(url).pathname);
    let media = frame;
    if (isPresentationVideo) {
      media = document.createElement('video');
      media.className = 'biggy-document-frame';
      media.controls = true;
      media.playsInline = true;
      media.setAttribute('data-testid', 'biggy-presentation-video');
    }
    const resize = document.createElement('button'); resize.type = 'button'; resize.className = 'biggy-document-resize'; resize.textContent = '↘'; resize.setAttribute('aria-label','Resize document window');
    header.append(heading,close); panel.append(header,media,resize);
    const viewport = () => ({w:window.innerWidth,h:window.innerHeight});
    let box = {x:40+viewers.size*24,y:40+viewers.size*24,w:Math.min(1000,innerWidth-80),h:Math.min(760,innerHeight-80)};
    let drag = null;
    function layout() {
      const v=viewport(); box.w=Math.min(v.w,Math.max(Math.min(300,v.w),box.w)); box.h=Math.min(v.h,Math.max(Math.min(200,v.h),box.h));
      box.x=Math.max(0,Math.min(v.w-box.w,box.x)); box.y=Math.max(0,Math.min(v.h-box.h,box.y));
      Object.assign(panel.style,{left:box.x+'px',top:box.y+'px',width:box.w+'px',height:box.h+'px'});
    }
    function raise(){panel.style.zIndex=String(++layer);}
    function finish(){drag=null;media.style.pointerEvents='';}
    function start(event,mode){
      if(event.button!==0 || event.target.closest('.biggy-document-close'))return;
      raise();drag={mode,x:event.clientX,y:event.clientY,box:{...box},id:event.pointerId};
      event.currentTarget.setPointerCapture(event.pointerId);media.style.pointerEvents='none';event.preventDefault();
    }
    function move(event){if(!drag||drag.id!==event.pointerId)return; const dx=event.clientX-drag.x,dy=event.clientY-drag.y;
      box={...drag.box}; if(drag.mode==='move'){box.x+=dx;box.y+=dy;}else{box.w+=dx;box.h+=dy;}layout();}
    for(const [handle,mode] of [[header,'move'],[resize,'resize']]){
      handle.addEventListener('pointerdown',e=>start(e,mode));handle.addEventListener('pointermove',move);
      handle.addEventListener('pointerup',finish);handle.addEventListener('pointercancel',finish);handle.addEventListener('lostpointercapture',finish);
      handle.addEventListener('keydown',e=>{const delta={ArrowLeft:[-20,0],ArrowRight:[20,0],ArrowUp:[0,-20],ArrowDown:[0,20]}[e.key];if(!delta)return;
        e.preventDefault();if(mode==='move'){box.x+=delta[0];box.y+=delta[1];}else{box.w+=delta[0];box.h+=delta[1];}layout();});
    }
    function remove(){
      finish();window.removeEventListener('resize',layout);viewers.delete(panel);
      if (media.tagName === 'VIDEO') { try { media.pause(); media.removeAttribute('src'); media.load(); } catch (_) {} }
      else { media.src = 'about:blank'; }
      panel.remove();try{opener?.focus({preventScroll:true});}catch(_){}
    }
    close.addEventListener('click',remove);panel.addEventListener('keydown',e=>{if(e.key==='Escape'){e.stopPropagation();remove();}});
    panel.addEventListener('pointerdown',raise);window.addEventListener('resize',layout);
    (document.fullscreenElement||document.body).append(panel);viewers.add(panel);raise();layout();
    media.src = url;
    close.focus({preventScroll:true});
    return true;
  }
  window.BiggyDocumentViewer = { open, supportsPresentation: true };
  const watched = new WeakSet();
  function watch(doc) {
    if(watched.has(doc))return; watched.add(doc);
    doc.addEventListener('click', event => {
      const link=event.target.closest?.('a[href]');
      if(!link||link.hasAttribute('download')||link.hasAttribute('data-document-external'))return;
      if(open(link.href,link.dataset.documentTitle||'',link)){event.preventDefault();event.stopImmediatePropagation();}
    }, true);
    function watchFrame(frame){
      if(frame.classList.contains('biggy-document-frame'))return;
      try{if(frame.contentDocument)watch(frame.contentDocument);}catch(_){/* Cross-origin modules retain their explicit behavior. */}
    }
    doc.addEventListener('load',event=>{if(event.target.tagName==='IFRAME')watchFrame(event.target);},true);
    doc.querySelectorAll('iframe').forEach(watchFrame);
  }
  watch(document);
})();
