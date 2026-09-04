/* Local sprite companion: no model, microphone, or external service calls. */
(() => {
  'use strict';
  if (window.BiggyPets) return;
  const KEY = 'biggy:pets:v1';
  const clampSize = value => Math.min(448, Math.max(64, Number(value) || 128));
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (_) {}
  const validPosition = value => value && Number.isFinite(value.x) && Number.isFinite(value.y)
    && value.x >= 0 && value.x <= 1 && value.y >= 0 && value.y <= 1;
  const state = { id: typeof saved.id === 'string' ? saved.id : '', enabled: saved.enabled === true,
    size: clampSize(saved.size), position: validPosition(saved.position) ? saved.position : null,
    positions: saved.positions && typeof saved.positions === 'object' ? saved.positions : {},
    sizes: saved.sizes && typeof saved.sizes === 'object' ? saved.sizes : {},
    animations: saved.animations && typeof saved.animations === 'object' ? saved.animations : {} };
  if (state.position && !Object.hasOwn(state.positions, state.id)) state.positions[state.id] = state.position;
  if (!Object.hasOwn(state.sizes, state.id)) state.sizes[state.id] = clampSize(state.size * (state.id === 'biggy' ? 2 : 1));
  state.size = clampSize(state.sizes[state.id]);
  let drag = null;
  let root, button, panel, select, toggle, range, output, status, stage, resetPosition, visibilityObserver;
  let speed, speedOutput, pause, pauseOutput, random;
  let pets = [], timer = 0, frame = 0, loaded = false, request = 0, loading = false, destroyed = false, observer;
  let catalogRequest = 0, catalogAbort;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const node = (tag, attrs = {}, text = '') => {
    const result = document.createElement(tag);
    Object.entries(attrs).forEach(([key, value]) => result.setAttribute(key, value));
    result.textContent = text;
    return result;
  };
  const persist = () => { state.positions[state.id] = state.position; state.sizes[state.id] = state.size; try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (_) {} };
  const selected = () => pets.find(pet => pet.id === state.id);
  function animationSettings() {
    const value = state.animations[state.id] || {};
    const coffee = state.id === 'biggy';
    return { speed: Math.max(25, Math.min(150, Number(value.speed) || (coffee ? 50 : 100))),
      pause: Math.max(0, Math.min(20, Number.isFinite(value.pause) ? value.pause : (coffee ? 8 : 0))),
      random: typeof value.random === 'boolean' ? value.random : coffee };
  }
  const petWidth = () => state.size * (selected()?.frameWidth || 192) / (selected()?.frameHeight || 208);
  function choose(id) {
    state.id = id;
    state.position = validPosition(state.positions[id]) ? state.positions[id] : null;
    state.size = clampSize(state.sizes[id] || (id === 'biggy' ? 256 : 128));
  }
  function stop() { clearTimeout(timer); timer = 0; }
  function animate() {
    stop();
    if (!loaded || !state.enabled || document.hidden || reduced.matches) return;
    const pet = selected();
    if (!pet) return;
    const settings = animationSettings();
    const delay = () => pet.frameDurations[frame] * 100 / settings.speed + (frame === 0
      ? settings.pause * 1000 * (settings.random ? 0.5 + Math.random() : 1) : 0);
    const tick = () => {
      frame = (frame + 1) % pet.idleFrames;
      stage.style.backgroundPosition = `${pet.columns > 1 ? frame / (pet.columns - 1) * 100 : 0}% 0%`;
      timer = setTimeout(tick, delay());
    };
    timer = setTimeout(tick, delay());
  }
  function position() {
    if (!root || !stage) return;
    const bounds = (document.getElementById('msg') || document.getElementById('composerBox') || button).getBoundingClientRect();
    const width = petWidth();
    stage.style.width = `${width}px`;
    stage.style.height = `${state.size}px`;
    const maxX = Math.max(8, innerWidth - width - 8);
    const maxY = Math.max(8, innerHeight - state.size - 8);
    const lane = document.getElementById('biggyArgusConversationLane');
    const laneBox = lane?.getBoundingClientRect();
    const dialog = selected()?.defaultAnchor === 'dialog-right';
    const visibleLane = dialog && laneBox?.width && laneBox?.height && getComputedStyle(lane).visibility !== 'hidden';
    const x = state.position ? 8 + state.position.x * (maxX - 8) : dialog ? (visibleLane ? laneBox.right : bounds.right) + 12 : bounds.left + 12;
    const y = state.position ? 8 + state.position.y * (maxY - 8) : (visibleLane ? laneBox.bottom : bounds.top - 8) - state.size;
    stage.style.left = `${Math.max(8, Math.min(maxX, x))}px`;
    stage.style.top = `${Math.max(8, Math.min(maxY, y))}px`;
    stage.style.bottom = 'auto';
    panel.style.right = '56px';
    panel.style.bottom = '12px';
    if (!panel.hidden && !drag) {
      const popup = panel.getBoundingClientRect();
      const petBox = stage.getBoundingClientRect();
      if (petBox.right <= popup.left || petBox.left >= popup.right || petBox.bottom <= popup.top || petBox.top >= popup.bottom) return;
      // Keep the live resize preview visible without painting over its controls.
      if (popup.right + width + 20 <= innerWidth) stage.style.left = `${popup.right + 12}px`;
      else if (popup.left >= width + 20) stage.style.left = `${popup.left - width - 12}px`;
      else stage.style.top = `${Math.max(8, popup.top - state.size - 10)}px`;
    }
  }
  function rememberPosition(x, y) {
    const width = petWidth();
    state.position = {
      x: Math.max(0, Math.min(1, (x - 8) / Math.max(1, innerWidth - width - 16))),
      y: Math.max(0, Math.min(1, (y - 8) / Math.max(1, innerHeight - state.size - 16))),
    };
  }
  function endDrag(cancel = false) {
    if (!drag) return;
    const current = drag;
    drag = null;
    if (cancel) state.position = current.previous;
    if (stage.hasPointerCapture(current.id)) stage.releasePointerCapture(current.id);
    stage.classList.remove('is-dragging');
    persist();
    position();
  }
  function startDrag(event) {
    if (event.button !== 0 || !event.isPrimary) return;
    const rect = stage.getBoundingClientRect();
    drag = { id: event.pointerId, dx: event.clientX - rect.left, dy: event.clientY - rect.top, previous: state.position };
    rememberPosition(rect.left, rect.top);
    setOpen(false);
    stage.setPointerCapture(event.pointerId);
    stage.classList.add('is-dragging');
    stage.focus({ preventScroll: true });
    event.preventDefault();
  }
  function moveDrag(event) {
    if (!drag || event.pointerId !== drag.id) return;
    rememberPosition(event.clientX - drag.dx, event.clientY - drag.dy);
    position();
    event.preventDefault();
  }
  function moveWithKeys(event) {
    if (event.key === 'Escape' && drag) { endDrag(true); event.preventDefault(); return; }
    const directions = { ArrowLeft: [-1,0], ArrowRight: [1,0], ArrowUp: [0,-1], ArrowDown: [0,1] };
    const step = directions[event.key];
    if (!step) return;
    const rect = stage.getBoundingClientRect(), pixels = event.shiftKey ? 24 : 8;
    rememberPosition(rect.left + step[0]*pixels, rect.top + step[1]*pixels);
    persist();
    position();
    event.preventDefault();
    event.stopPropagation();
  }
  function render() {
    if (!root) return;
    const pet = selected();
    button.classList.toggle('is-active', state.enabled && loaded);
    button.setAttribute('aria-label', `Pet controls${pet ? ': ' + pet.displayName : ''}${state.enabled && loaded ? ', on' : ', off'}`);
    toggle.textContent = state.enabled ? 'Turn off' : 'Turn on';
    toggle.setAttribute('aria-pressed', String(state.enabled));
    toggle.disabled = !pet || loading;
    range.value = String(state.size);
    output.textContent = `${state.size}px`;
    const settings = animationSettings();
    speed.value = String(settings.speed);
    speedOutput.textContent = `${settings.speed}%`;
    pause.value = String(settings.pause);
    pauseOutput.textContent = `${settings.pause}s`;
    random.checked = settings.random;
    stage.hidden = !state.enabled || !loaded;
    stage.setAttribute('aria-label', pet ? pet.displayName : 'Pet');
    resetPosition.textContent = pet?.defaultAnchor === 'dialog-right' ? 'Place right of dialog' : 'Place above Message Biggy';
    position();
    animate();
  }
  async function loadSprite() {
    const serial = ++request;
    loaded = false;
    frame = 0;
    stop();
    stage.style.backgroundImage = 'none';
    render();
    const pet = selected();
    if (!pet) return;
    const img = new Image();
    img.src = pet.spriteUrl;
    try {
      await img.decode();
      if (destroyed || serial !== request) return;
      if (img.naturalWidth !== pet.columns * pet.frameWidth || img.naturalHeight !== pet.rows * pet.frameHeight) throw new Error('grid');
      stage.style.backgroundImage = `url("${pet.spriteUrl}")`;
      stage.style.backgroundSize = `${pet.columns * 100}% ${pet.rows * 100}%`;
      stage.style.backgroundPosition = '0% 0%';
      loaded = true;
      status.textContent = 'Local idle preview. No voice or AI calls.';
    } catch (_) {
      if (destroyed || serial !== request) return;
      state.enabled = false;
      persist();
      status.textContent = 'Sprite unavailable or dimensions do not match its manifest.';
    }
    render();
  }
  async function refresh() {
    if (loading) return;
    const serial = ++catalogRequest;
    const controller = new AbortController();
    catalogAbort = controller;
    const timeout = setTimeout(() => controller.abort(), 5000);
    loading = true;
    status.textContent = 'Loading local pets…';
    render();
    try {
      const response = await fetch('/api/biggy/pets', { cache: 'no-store', signal: controller.signal });
      if (!response.ok) throw new Error('catalog');
      const payload = await response.json();
      if (destroyed || serial !== catalogRequest) return;
      pets = (Array.isArray(payload.pets) ? payload.pets : []).filter(pet =>
        /^[a-z0-9][a-z0-9_-]{0,63}$/.test(pet.id)
        && Number.isInteger(pet.columns) && pet.columns >= 1 && pet.columns <= 32
        && Number.isInteger(pet.rows) && pet.rows >= 1 && pet.rows <= 11
        && Number.isInteger(pet.idleFrames) && pet.idleFrames >= 1 && pet.idleFrames <= pet.columns
        && [pet.frameWidth,pet.frameHeight].every(n => Number.isInteger(n) && n >= 1 && n <= 2048)
        && Array.isArray(pet.frameDurations) && pet.frameDurations.length === pet.idleFrames
        && pet.frameDurations.every(n => Number.isInteger(n) && n >= 40 && n <= 10000)
        && new RegExp(`^/api/biggy/pets/${pet.id}/sprite\\?v=[a-f0-9]+$`).test(pet.spriteUrl));
      select.replaceChildren();
      pets.forEach(pet => select.appendChild(node('option', { value: pet.id }, pet.displayName)));
      if (!selected()) {
        choose(pets[0]?.id || '');
        state.enabled = false; // Missing selected pet never silently enables its replacement.
      }
      select.value = state.id;
      select.disabled = !pets.length;
      if (!pets.length) {
        select.appendChild(node('option', {}, 'No compatible pets'));
        status.textContent = 'Add a compatible pet folder locally, then refresh.';
      }
      persist();
      await loadSprite();
    } catch (_) {
      if (destroyed || serial !== catalogRequest) return;
      loaded = false;
      state.enabled = false;
      persist();
      status.textContent = 'Local pets unavailable. Refresh to retry.';
    } finally {
      clearTimeout(timeout);
      if (serial === catalogRequest) {
        loading = false;
        if (!destroyed) render();
      }
    }
  }
  function setOpen(open) {
    panel.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    position();
    if (open) select.focus();
  }
  function outside(event) { if (root && !root.contains(event.target) && !panel.contains(event.target)) setOpen(false); }
  function keydown(event) {
    if (event.key === 'Escape' && panel && !panel.hidden) { setOpen(false); button.focus(); }
  }
  function mount(deck) {
    const rail = document.getElementById('biggyCategoryRail');
    if (!deck || !rail) return;
    if (root) { if (root.parentElement !== rail) rail.appendChild(root); position(); return; }
    destroyed = false;
    root = node('div', { id: 'biggyPets', class: 'biggy-pets' });
    button = node('button', { type: 'button', class: 'biggy-pets-button', 'aria-expanded': 'false', 'aria-controls': 'biggyPetPanel' }, 'PET');
    panel = node('section', { id: 'biggyPetPanel', class: 'biggy-pet-panel biggy-pets', 'aria-label': 'Pet controls' });
    panel.hidden = true;
    const label = node('label', { for: 'biggyPetSelect' }, 'SELECT PET');
    select = node('select', { id: 'biggyPetSelect' });
    const actions = node('div', { class: 'biggy-pet-actions' });
    toggle = node('button', { type: 'button', 'aria-pressed': 'false' }, 'Turn on');
    const reload = node('button', { type: 'button', 'aria-label': 'Refresh local pets' }, 'Refresh');
    resetPosition = node('button', { type: 'button', class: 'biggy-pet-reset' }, 'Place above Message Biggy');
    actions.append(toggle, reload);
    range = node('input', { id: 'biggyPetSize', type: 'range', min: '64', max: '448', step: '8', 'aria-label': 'Pet size' });
    output = node('output', { for: 'biggyPetSize' });
    speed = node('input', { id: 'biggyPetSpeed', type: 'range', min: '25', max: '150', step: '5', 'aria-label': 'Animation speed' });
    speedOutput = node('output', { for: 'biggyPetSpeed' });
    pause = node('input', { id: 'biggyPetPause', type: 'range', min: '0', max: '20', step: '1', 'aria-label': 'Pause between animations' });
    pauseOutput = node('output', { for: 'biggyPetPause' });
    random = node('input', { id: 'biggyPetRandom', type: 'checkbox' });
    const randomLabel = node('label', { for: 'biggyPetRandom', class: 'biggy-pet-random' });
    randomLabel.append(random, document.createTextNode(' Random timing'));
    status = node('p', { role: 'status' });
    panel.append(label, select, actions, node('label', { for: 'biggyPetSize' }, 'SIZE'), range, output, resetPosition,
      node('label', { for: 'biggyPetSpeed' }, 'ANIMATION SPEED'), speed, speedOutput,
      node('label', { for: 'biggyPetPause' }, 'PAUSE BETWEEN ANIMATIONS'), pause, pauseOutput, randomLabel,
      node('p', {}, 'Random timing varies the pause from half to 1½ times the selected seconds. Zero means continuous.'),
      node('p', {}, 'Drag your pet to move. Arrow keys fine-tune.'), status);
    root.append(button);
    rail.appendChild(root);
    document.body.appendChild(panel);
    stage = node('div', { class: 'biggy-pet-sprite', role: 'img', tabindex: '0',
      'aria-description': 'Drag to move. Use arrow keys to adjust position; Shift moves faster.', title: 'Drag to move pet' });
    stage.hidden = true;
    document.body.appendChild(stage);
    stage.addEventListener('pointerdown', startDrag);
    stage.addEventListener('pointermove', moveDrag);
    stage.addEventListener('pointerup', event => { if (drag?.id === event.pointerId) endDrag(); });
    stage.addEventListener('pointercancel', event => { if (drag?.id === event.pointerId) endDrag(true); });
    stage.addEventListener('lostpointercapture', event => { if (drag?.id === event.pointerId) endDrag(true); });
    stage.addEventListener('keydown', moveWithKeys);
    resetPosition.addEventListener('click', () => { state.position = null; persist(); position(); });
    button.addEventListener('click', () => setOpen(panel.hidden));
    select.addEventListener('change', () => { choose(select.value); persist(); loadSprite(); });
    toggle.addEventListener('click', () => { state.enabled = !state.enabled; persist(); render(); });
    reload.addEventListener('click', refresh);
    range.addEventListener('input', () => { state.size = clampSize(range.value); persist(); render(); });
    const updateAnimation = () => {
      state.animations[state.id] = { speed: Number(speed.value), pause: Number(pause.value), random: random.checked };
      persist(); render();
    };
    speed.addEventListener('input', updateAnimation);
    pause.addEventListener('input', updateAnimation);
    random.addEventListener('change', updateAnimation);
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', keydown);
    document.addEventListener('visibilitychange', animate);
    window.addEventListener('resize', position);
    reduced.addEventListener('change', animate);
    observer = new ResizeObserver(position);
    observer.observe(deck);
    const lane = document.getElementById('biggyArgusConversationLane');
    if (lane) observer.observe(lane);
    visibilityObserver = new MutationObserver(() => {
      if (!document.getElementById('mainChat')?.classList.contains('biggy-pa-rail-open')) setOpen(false);
      position();
    });
    const main = document.getElementById('mainChat');
    if (main) visibilityObserver.observe(main, { attributes: true, attributeFilter: ['class'] });
    refresh();
  }
  function unmount() {
    endDrag(true);
    destroyed = true;
    request += 1;
    catalogRequest += 1;
    catalogAbort?.abort();
    loading = false;
    stop();
    observer?.disconnect();
    visibilityObserver?.disconnect();
    document.removeEventListener('pointerdown', outside);
    document.removeEventListener('keydown', keydown);
    document.removeEventListener('visibilitychange', animate);
    window.removeEventListener('resize', position);
    reduced.removeEventListener('change', animate);
    root?.remove();
    panel?.remove();
    stage?.remove();
    root = null;
  }
  window.BiggyPets = { mount, unmount };
})();
