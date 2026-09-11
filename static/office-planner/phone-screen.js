// The popup belongs to the top-level cockpit so planner iframe bounds cannot clip it.
export function openPhoneScreen(device, name) {
  if (!device) throw Error('Choose a connected phone first.');
  const host = window.parent;
  const doc = host.document;
  doc.getElementById('argus-phone-screen')?.dispatchEvent(new Event('phone-close'));
  const make = (tag, text = '') => { const node = doc.createElement(tag); node.textContent = text; return node; };
  const box = make('section');
  box.id = 'argus-phone-screen';
  box.setAttribute('role', 'dialog');
  box.setAttribute('aria-label', 'Visual phone control');
  box.style.cssText = 'position:fixed;z-index:100020;background:#071820;color:#edf6fa;border:1px solid #58a6ba;border-radius:14px;box-shadow:0 14px 50px #000b;display:flex;flex-direction:column;padding:10px;gap:7px;box-sizing:border-box;resize:both;overflow:hidden;min-width:0;min-height:0;font:13px system-ui';
  const reactor = doc.getElementById('biggyArgusReactor');
  const previousVisibility = reactor?.style.visibility || '';
  if (reactor) reactor.style.visibility = 'hidden';
  function bounds() {
    const orbHost = doc.getElementById('j-orb');
    // The Orb host includes transparent artwork padding above its visible ring.
    const orb = (orbHost?.shadowRoot?.querySelector('.profile') || orbHost)?.getBoundingClientRect();
    const rail = doc.querySelector('.biggy-top-rail-group')?.getBoundingClientRect();
    const top = Math.max(12, (rail?.bottom || 0) + 12);
    const composer = doc.getElementById('biggyPromptDeck')?.getBoundingClientRect();
    const bottom = Math.max(top, Math.min(host.innerHeight - 12, (composer?.top || host.innerHeight) - 12));
    return {top, bottom, orb};
  }
  const initial = bounds();
  const width = Math.min(370, host.innerWidth - 24);
  const height = initial.bottom - initial.top;
  box.style.width = width + 'px'; box.style.height = height + 'px';
  box.style.left = Math.max(12, Math.min(host.innerWidth - width - 12, (initial.orb ? initial.orb.left + initial.orb.width / 2 : host.innerWidth / 2) - width / 2)) + 'px';
  box.style.top = initial.bottom - height + 'px';
  const header = make('header'); header.style.cssText = 'display:flex;align-items:center;gap:8px;cursor:move;touch-action:none';
  const title = make('strong', name || 'Phone'); title.style.flex = '1';
  const status = make('div', 'Connecting to your phone…'); status.setAttribute('role', 'status'); status.style.cssText = 'font-size:12px;min-height:30px';
  const controls = make('div'); controls.style.cssText = 'display:flex;flex-wrap:wrap;gap:5px';
  const appControls = make('div'); appControls.style.cssText = 'display:flex;gap:5px';
  const apps = make('select'); apps.setAttribute('aria-label', 'Phone application'); apps.style.cssText = 'min-width:0;flex:1;background:#102b37;color:inherit';
  apps.append(new Option('Choose app', ''));
  const stage = make('div'); stage.style.cssText = 'display:flex;justify-content:center;align-items:center;flex:1;min-height:0;overflow:hidden;background:#000;border-radius:6px';
  const picture = make('img'); picture.alt = 'Current phone screen'; picture.draggable = false;
  picture.style.cssText = 'max-width:100%;max-height:100%;width:auto;height:auto;display:block;touch-action:none;user-select:none;cursor:crosshair';
  stage.append(picture);
  let busy = false, closed = false, frame = null, expires = 0, expiryTimer, pointer, drag;
  const abort = new AbortController();
  const actionButtons = [];
  function button(text, action, parent = controls) {
    const b = make('button', text); b.type = 'button'; b.style.cssText = 'background:#153440;color:inherit;border:1px solid #426775;border-radius:5px;padding:6px 8px;cursor:pointer';
    b.onclick = action; parent.append(b); return b;
  }
  function close() {
    if (closed) return;
    if (reactor) reactor.style.visibility = previousVisibility;
    closed = true; frame = null; clearTimeout(expiryTimer); abort.abort();
    host.removeEventListener('keydown', key); host.removeEventListener('resize', fit);
    window.removeEventListener('pagehide', close); observer.disconnect(); box.remove();
  }
  function key(event) { if (event.key === 'Escape') close(); }
  function fit() {
    const area = bounds();
    box.style.maxWidth = Math.max(0, host.innerWidth - 24) + 'px';
    box.style.maxHeight = Math.max(0, area.bottom - area.top) + 'px';
    const r = box.getBoundingClientRect();
    box.style.left = Math.max(12, Math.min(r.left, host.innerWidth - r.width - 12)) + 'px';
    box.style.top = Math.max(area.top, Math.min(r.top, area.bottom - r.height)) + 'px';
  }
  const observer = new host.ResizeObserver(fit);
  header.append(title); button('Close', close, header).setAttribute('aria-label', 'Close phone screen');
  async function request(body) {
    const response = await fetch('/api/biggy/pa/phone-device', {
      method: 'POST', cache: 'no-store', signal: AbortSignal.any([abort.signal, AbortSignal.timeout(60000)]),
      headers: {'Content-Type': 'application/json', 'X-Hermes-CSRF-Token': host.__HERMES_CONFIG__?.csrfToken || ''},
      body: JSON.stringify({device, visual: true, ...body}),
    });
    const data = await response.json(); if (!response.ok) throw Error(data.error || 'Phone action failed. Refresh before retrying.');
    return data;
  }
  async function show(data) {
    if (closed) return;
    if (typeof data.image !== 'string' || !data.image.startsWith('data:image/png;base64,')) throw Error('Phone screenshot unavailable.');
    picture.src = data.image; await picture.decode(); if (closed) return;
    frame = data.frame; expires = Date.now() + data.expires_in * 1000;
    clearTimeout(expiryTimer);
    expiryTimer = setTimeout(() => { frame = null; if (!closed) status.textContent = 'Screenshot paused. Refresh before tapping or swiping.'; }, data.expires_in * 1000);
    status.textContent = (data.notice ? data.notice + ' ' : '') + 'Tap the image to act on your phone; drag to swipe. Updated ' + new Date().toLocaleTimeString();
  }
  async function perform(body) {
    if (busy || closed) return;
    busy = true; frame = null; clearTimeout(expiryTimer); pointer = null;
    actionButtons.forEach(b => { b.disabled = true; });
    picture.style.opacity = '.55'; status.textContent = 'Updating phone screen…';
    try {
      const result = await request(body);
      if (closed) return;
      await show(result.image ? result : await request({action: 'screen'}));
    } catch (error) { if (!closed) status.textContent = error.message + ' Refresh the screen to continue.'; }
    finally { busy = false; if (!closed) { picture.style.opacity = '1'; actionButtons.forEach(b => { b.disabled = false; }); } }
  }
  for (const [label, action] of [['Refresh', 'screen'], ['Home', 'home'], ['Recents', 'recents']]) {
    actionButtons.push(button(label, () => perform({action})));
  }
  for (const [label, start, end] of [['←', .8, .2], ['→', .2, .8]]) {
    const b = button(label, () => {
      if (busy || !frame || Date.now() >= expires) {
        status.textContent = 'Refresh the screenshot before swiping.'; return;
      }
      perform({action: 'swipe', frame, x: start, y: .5, end_x: end, end_y: .5});
    });
    b.setAttribute('aria-label', label === '←' ? 'Swipe left' : 'Swipe right');
    b.title = label === '←' ? 'Swipe left · next Home screen' : 'Swipe right · previous Home screen';
    actionButtons.push(b);
  }
  actionButtons.push(button('Apps', async () => {
    if (busy || closed) return; busy = true;
    actionButtons.forEach(b => { b.disabled = true; });
    try {
      const data = await request({action: 'apps'}); if (closed) return;
      apps.replaceChildren(new Option('Choose app', ''));
      for (const item of data.apps) apps.append(new Option(item, item));
      status.textContent = 'Choose an installed app, then Open.';
    } catch (error) { if (!closed) status.textContent = error.message; }
    finally { busy = false; if (!closed) actionButtons.forEach(b => { b.disabled = false; }); }
  }));
  appControls.append(apps);
  actionButtons.push(button('Open', () => { if (apps.value) perform({action: 'launch', package: apps.value}); }, appControls));
  actionButtons.push(button('Close app', () => perform({action: 'close_app'}), appControls));
  function point(event) {
    const r = picture.getBoundingClientRect();
    return {x: Math.max(0, Math.min(1, (event.clientX - r.left) / r.width)), y: Math.max(0, Math.min(1, (event.clientY - r.top) / r.height))};
  }
  picture.onpointerdown = event => {
    if (event.button !== 0 || !event.isPrimary || busy || !frame || Date.now() >= expires) {
      if (!busy && !frame) status.textContent = 'Refresh the screenshot before tapping.'; return;
    }
    event.preventDefault(); picture.setPointerCapture(event.pointerId);
    pointer = {...point(event), id: event.pointerId, frame, clientX: event.clientX, clientY: event.clientY};
  };
  picture.onpointerup = event => {
    if (!pointer || pointer.id !== event.pointerId) return;
    const start = pointer; pointer = null;
    if (busy || frame !== start.frame || Date.now() >= expires) return;
    const end = point(event);
    const swipe = Math.hypot(event.clientX - start.clientX, event.clientY - start.clientY) > 12;
    perform({action: swipe ? 'swipe' : 'tap', frame: start.frame, x: start.x, y: start.y, ...(swipe ? {end_x: end.x, end_y: end.y} : {})});
  };
  picture.onpointercancel = () => { pointer = null; };
  header.onpointerdown = event => {
    if (event.target.closest('button') || event.button !== 0) return;
    const r = box.getBoundingClientRect(); drag = {x: event.clientX - r.left, y: event.clientY - r.top}; header.setPointerCapture(event.pointerId);
  };
  header.onpointermove = event => {
    if (!drag) return;
    box.style.left = Math.max(0, Math.min(host.innerWidth - box.offsetWidth, event.clientX - drag.x)) + 'px';
    const area = bounds();
    box.style.top = Math.max(area.top, Math.min(area.bottom - box.offsetHeight, event.clientY - drag.y)) + 'px';
  };
  header.onpointerup = header.onpointercancel = () => { drag = null; };
  box.addEventListener('phone-close', close); host.addEventListener('keydown', key); host.addEventListener('resize', fit);
  window.addEventListener('pagehide', close, {once: true});
  box.append(header, controls, appControls, status, stage); doc.body.append(box);
  observer.observe(box);
  for (const node of [doc.getElementById('biggyPromptDeck'), doc.querySelector('.biggy-top-rail-group')]) if (node) observer.observe(node);
  fit();
  perform({action: 'screen'});
}
