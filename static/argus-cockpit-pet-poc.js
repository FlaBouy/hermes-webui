/* Isolated A.R.G.U.S. cockpit-pet POC. It is not imported by the production GUI. */
(() => {
  'use strict';
  if (customElements.get('argus-cockpit-pet')) return;

  const MODULES = [
    ['CHAT', 'left'], ['TASKS', 'left'], ['KANBAN', 'left'], ['SKILLS', 'left'], ['MEMORY', 'left'], ['SPACES', 'left'],
    ['PROFILES', 'right'], ['TODOS', 'right'], ['INSIGHTS', 'right'], ['LOGS', 'right'], ['SETTINGS', 'right'], ['TOOLS', 'right'],
  ];

  class ArgusCockpitPet extends HTMLElement {
    static get observedAttributes() { return ['model', 'status', 'tracking']; }

    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._target = { x: 0, y: 0 };
      this._eye = { x: 0, y: 0 };
      this._frame = 0;
      this._onPointerMove = event => this.track(event.clientX, event.clientY);
      this._onPointerLeave = () => this.centerEye();
      this._onBlur = () => this.centerEye();
      this.shadowRoot.innerHTML = `
        <style>
          :host{display:block;width:min(720px,96vw);aspect-ratio:1200/720;contain:layout style;user-select:none;color:#b9c4d2;font-family:"SF Mono",ui-monospace,monospace}
          *{box-sizing:border-box}.entity{position:relative;width:100%;height:100%;overflow:visible}
          svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible;filter:drop-shadow(0 0 14px rgba(22,188,237,.15))}
          .profile{fill:#01060b;opacity:.99}.solid{transform-origin:596px 404px;animation:cw 9.5s linear infinite}.dash{animation:dash 14s linear infinite}
          .pulse{transform-origin:596px 404px;animation:pulse 5.6s ease-in-out infinite}.lamp{animation:lamp 5.6s ease-in-out infinite}
          .eye{transform-box:view-box;transform-origin:596px 404px;will-change:transform}
          .tie{fill:none;stroke:#27bce8;stroke-width:1.7;stroke-dasharray:3 5;opacity:.62}.node{fill:#061421;stroke:#33dfff;stroke-width:2}
          button{position:absolute;width:84px;height:27px;transform:translate(-50%,-50%);border:1px solid #303b48;border-radius:5px;background:rgba(8,15,23,.94);color:#aab5c3;font:800 10px/1 "SF Mono",ui-monospace,monospace;letter-spacing:.05em;cursor:pointer;z-index:2}
          button:hover,button:focus-visible{color:#eafcff;border-color:#35d9ff;outline:none}button.active{color:#69efcd;border-color:#34d399;background:#082018;box-shadow:0 0 10px rgba(52,211,153,.3)}
          .name{position:absolute;left:50%;bottom:37px;transform:translateX(-50%);color:#fff;font:900 17px/1 "SF Mono",ui-monospace,monospace;letter-spacing:.2em;text-shadow:0 0 8px rgba(112,225,255,.72)}
          .readout{position:absolute;left:50%;bottom:4px;transform:translateX(-50%);width:224px;padding:5px 10px;display:flex;justify-content:center;gap:12px;border:1px solid rgba(52,211,153,.42);border-radius:999px;background:rgba(5,16,14,.88);font-size:10px;font-weight:800;letter-spacing:.09em;color:#34d399;white-space:nowrap}
          .state::before{content:"";display:inline-block;width:7px;height:7px;margin-right:6px;border-radius:50%;background:currentColor;box-shadow:0 0 8px currentColor}.state{min-width:74px;text-align:center}
          @keyframes cw{to{transform:rotate(360deg)}}@keyframes dash{to{stroke-dashoffset:190}}@keyframes pulse{0%,100%{opacity:.82;filter:brightness(.84)}50%{opacity:1;filter:brightness(1.22) drop-shadow(0 0 10px rgba(255,70,58,.8))}}@keyframes lamp{0%,100%{opacity:.25}50%{opacity:.9}}
          @media(prefers-reduced-motion:reduce){.solid,.dash,.pulse,.lamp{animation:none!important}}
        </style>
        <div class="entity" part="entity">
          <svg viewBox="0 60 1200 720" role="img" aria-label="A.R.G.U.S. cockpit pet proof of concept">
            <defs>
              <radialGradient id="sensor"><stop stop-color="#fff4f1"/><stop offset=".28" stop-color="#ff8d7c"/><stop offset=".68" stop-color="#dc2f28"/><stop offset="1" stop-color="#6f090d"/></radialGradient>
              <radialGradient id="mask"><stop stop-color="#01060b"/><stop offset=".72" stop-color="#020a12"/><stop offset="1" stop-color="#03101a"/></radialGradient>
              <filter id="glow" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
              <filter id="soft" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="12"/></filter>
              <mask id="lamps" maskUnits="userSpaceOnUse" x="320" y="120" width="560" height="560"><rect x="320" y="120" width="560" height="560" fill="black"/><circle cx="596" cy="404" r="255" fill="white"/><circle cx="596" cy="404" r="205" fill="black"/></mask>
            </defs>
            <circle class="profile" cx="596" cy="404" r="252" fill="url(#mask)"/>
            <image href="/static/argus-orb-template.png" x="238.5" y="159" width="723" height="482" preserveAspectRatio="xMidYMid meet"/>
            <image class="lamp" href="/static/argus-orb-template.png" x="238.5" y="159" width="723" height="482" preserveAspectRatio="xMidYMid meet" mask="url(#lamps)"/>
            <g class="solid" fill="none" stroke="#55ddff"><circle cx="596" cy="404" r="91" stroke-width="2.5" opacity=".82"/><circle cx="596" cy="313" r="4" fill="#c8f8ff" stroke="none" filter="url(#glow)"/></g>
            <circle class="dash" cx="596" cy="404" r="112" pathLength="703" fill="none" stroke="#30bfe9" stroke-width="2.5" stroke-dasharray="11 8" opacity=".78"/>
            <circle class="lamp" cx="596" cy="404" r="150" fill="none" stroke="#42dcff" stroke-width="8" opacity=".32" filter="url(#glow)"/>
            <circle cx="596" cy="404" r="68" fill="#020a11" opacity=".94"/>
            <g id="eye" class="eye pulse">
              <circle cx="596" cy="404" r="65" fill="none" stroke="#7f1014" stroke-width="7" opacity=".42" filter="url(#soft)"/>
              <circle cx="596" cy="404" r="59" fill="none" stroke="#d92f2b" stroke-width="5" opacity=".72" filter="url(#glow)"/>
              <circle cx="596" cy="404" r="53" fill="#b91f20" opacity=".9" filter="url(#glow)"/>
              <circle id="eye-bulb" cx="596" cy="404" r="41" fill="url(#sensor)" filter="url(#glow)"/>
            </g>
            <g id="ties"></g>
          </svg>
          <div id="buttons"></div>
          <div class="name">A.R.G.U.S.</div>
          <div class="readout"><span class="model"></span><span class="state"></span></div>
        </div>`;
      this._eyeNode = this.shadowRoot.getElementById('eye');
      this.buildMenu();
      this.syncLabels();
    }

    connectedCallback() {
      document.addEventListener('pointermove', this._onPointerMove, { passive: true });
      document.documentElement.addEventListener('mouseleave', this._onPointerLeave);
      window.addEventListener('blur', this._onBlur);
      this.animateEye();
    }

    disconnectedCallback() {
      document.removeEventListener('pointermove', this._onPointerMove);
      document.documentElement.removeEventListener('mouseleave', this._onPointerLeave);
      window.removeEventListener('blur', this._onBlur);
      cancelAnimationFrame(this._frame);
      this._frame = 0;
    }

    attributeChangedCallback() { this.syncLabels(); }

    buildMenu() {
      const NS = 'http://www.w3.org/2000/svg';
      const ties = this.shadowRoot.getElementById('ties');
      const buttons = this.shadowRoot.getElementById('buttons');
      MODULES.forEach(([action, side], index) => {
        const row = index % 6;
        const y = 250 + row * 60;
        const inward = [40, 20, 0, 0, 20, 40][row];
        const x = side === 'left' ? 250 + inward : 950 - inward;
        const elbow = side === 'left' ? 360 : 840;
        const dx = elbow - 596, dy = y - 404, length = Math.hypot(dx, dy) || 1;
        const edgeX = 596 + dx / length * 270, edgeY = 404 + dy / length * 270;
        const path = document.createElementNS(NS, 'path');
        path.setAttribute('class', 'tie');
        path.setAttribute('d', `M ${x} ${y} L ${elbow} ${y} L ${edgeX} ${edgeY}`);
        const node = document.createElementNS(NS, 'circle');
        node.setAttribute('class', 'node'); node.setAttribute('cx', x); node.setAttribute('cy', y); node.setAttribute('r', 7);
        ties.append(path, node);
        const button = document.createElement('button');
        button.type = 'button'; button.dataset.action = action.toLowerCase(); button.textContent = action;
        button.style.left = `${x / 12}%`; button.style.top = `${(y - 60) / 7.2}%`;
        button.addEventListener('click', () => this.dispatchEvent(new CustomEvent('argus-cockpit-action', { bubbles: true, composed: true, detail: { action: button.dataset.action } })));
        buttons.appendChild(button);
      });
    }

    syncLabels() {
      if (!this.shadowRoot) return;
      const model = this.getAttribute('model') || 'GPT-OSS-120B';
      const status = (this.getAttribute('status') || 'ONLINE').toUpperCase();
      this.shadowRoot.querySelector('.model').textContent = `◆ ${model}`;
      this.shadowRoot.querySelector('.state').textContent = status;
    }

    track(clientX, clientY) {
      if (this.getAttribute('tracking') === 'off') return this.centerEye();
      const rect = this._eyeNode.getBoundingClientRect();
      const dx = clientX - (rect.left + rect.width / 2), dy = clientY - (rect.top + rect.height / 2);
      const distance = Math.hypot(dx, dy) || 1, strength = Math.min(1, distance / 280);
      this._target.x = dx / distance * 14 * strength;
      this._target.y = dy / distance * 10 * strength;
    }

    centerEye() { this._target.x = 0; this._target.y = 0; }

    animateEye() {
      this._eye.x += (this._target.x - this._eye.x) * .18;
      this._eye.y += (this._target.y - this._eye.y) * .18;
      this._eyeNode.style.translate = `${this._eye.x.toFixed(2)}px ${this._eye.y.toFixed(2)}px`;
      this._frame = requestAnimationFrame(() => this.animateEye());
    }

    setActiveActions(actions = []) {
      const active = new Set(Array.from(actions, value => String(value).toLowerCase()));
      this.shadowRoot.querySelectorAll('button[data-action]').forEach(button => button.classList.toggle('active', active.has(button.dataset.action)));
    }
  }

  customElements.define('argus-cockpit-pet', ArgusCockpitPet);
})();
