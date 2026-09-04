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
          .profile{fill:#01060b;opacity:.99}
          .solid,.dash{transform-box:view-box;transform-origin:596px 404px;will-change:transform}
          .solid{animation:cw 18s linear infinite}.dash{animation:ccw 26s linear infinite}
          .eye-glow,.confirmation-sweep{transform-box:view-box;transform-origin:596px 404px}
          .eye-glow{animation:eyeBreathe 5.6s ease-in-out infinite}
          .confirmation-sweep{fill:none;stroke:#5eead4;stroke-width:5;stroke-linecap:round;stroke-dasharray:0 830;opacity:0;pointer-events:none}
          .lamp{animation:lampIdle 5.6s ease-in-out infinite}
          .eye{transform-box:view-box;transform-origin:596px 404px;will-change:transform}
          .tie{fill:none;stroke:#27bce8;stroke-width:1.7;stroke-dasharray:3 5;opacity:.62;transition:stroke .18s ease,stroke-width .18s ease,opacity .18s ease,filter .18s ease}
          .node{fill:#061421;stroke:#33dfff;stroke-width:2;transition:fill .18s ease,stroke .18s ease,filter .18s ease}
          .tie.hover{stroke:#eafcff;stroke-width:2.1;opacity:.92;filter:drop-shadow(0 0 3px rgba(234,252,255,.45))}.node.hover{stroke:#eafcff;filter:drop-shadow(0 0 3px rgba(234,252,255,.55))}
          .tie.active{stroke:#fff;stroke-width:2.7;opacity:1;animation:tieFlow 1.8s linear infinite;filter:drop-shadow(0 0 4px rgba(255,255,255,.7))}.node.active{fill:#34d399;stroke:#fff;filter:drop-shadow(0 0 5px rgba(52,211,153,.9))}
          button{position:absolute;width:84px;height:27px;transform:translate(-50%,-50%);border:1px solid #303b48;border-radius:5px;background:rgba(8,15,23,.94);color:#aab5c3;font:800 10px/1 "SF Mono",ui-monospace,monospace;letter-spacing:.05em;cursor:pointer;z-index:2}
          button:hover,button:focus-visible{color:#eafcff;border-color:#35d9ff;outline:none;box-shadow:0 0 7px rgba(53,217,255,.18)}button.active{color:#69efcd;border-color:#34d399;background:#082018;box-shadow:0 0 10px rgba(52,211,153,.3)}
          .name{position:absolute;left:50%;bottom:37px;transform:translateX(-50%);color:#fff;font:900 17px/1 "SF Mono",ui-monospace,monospace;letter-spacing:.2em;text-shadow:0 0 8px rgba(112,225,255,.72)}
          .readout{position:absolute;left:50%;bottom:4px;transform:translateX(-50%);width:224px;padding:5px 10px;display:flex;justify-content:center;gap:12px;border:1px solid rgba(52,211,153,.42);border-radius:999px;background:rgba(5,16,14,.88);font-size:10px;font-weight:800;letter-spacing:.09em;color:#34d399;white-space:nowrap}
          .state::before{content:"";display:inline-block;width:7px;height:7px;margin-right:6px;border-radius:50%;background:currentColor;box-shadow:0 0 8px currentColor}.state{min-width:74px;text-align:center;transition:color .2s ease,text-shadow .2s ease}
          .entity[data-state="thinking"] .solid{animation-duration:7s}.entity[data-state="thinking"] .dash{animation-duration:10s}.entity[data-state="thinking"] .state{color:#f6bd43;text-shadow:0 0 7px rgba(246,189,67,.58)}
          .entity[data-state="thinking"] .eye-glow{animation-duration:2.8s}.entity[data-state="thinking"] .lamp{animation-duration:2.8s}
          .entity[data-state="speaking"] .eye-glow{animation:speechEye 1.35s ease-in-out infinite}.entity[data-state="speaking"] .lamp{animation:speechLamp 1.35s ease-in-out infinite}.entity[data-state="speaking"] .state{color:#67e8f9;text-shadow:0 0 7px rgba(103,232,249,.62)}
          .entity[data-state="working"] .solid{animation:stepCw 4.8s steps(12,end) infinite}.entity[data-state="working"] .dash{animation-duration:18s}.entity[data-state="working"] .state{color:#67e8f9;text-shadow:0 0 7px rgba(103,232,249,.62)}
          .entity[data-state="success"] .confirmation-sweep{animation:confirmSweep 1.05s ease-out 1}.entity[data-state="success"] .state{color:#5eead4;text-shadow:0 0 8px rgba(94,234,212,.72)}.entity[data-state="success"] .tie.active{stroke:#5eead4;animation:successPath .9s ease-out 1}.entity[data-state="success"] .node.active{fill:#5eead4}
          .entity[data-state="warning"] .state,.entity[data-state="warning"] .tie.active{color:#f6bd43;stroke:#f6bd43}.entity[data-state="warning"] .node.active{fill:#f6bd43;stroke:#fff}.entity[data-state="warning"] .eye-glow{stroke:#f59e0b;opacity:.82;animation:none;filter:drop-shadow(0 0 7px rgba(245,158,11,.6))}
          .entity[data-state="error"] .state,.entity[data-state="error"] .tie.active{color:#fb5353;stroke:#fb5353}.entity[data-state="error"] .node.active{fill:#fb5353;stroke:#fff}.entity[data-state="error"] .eye-glow{stroke:#fb3030;opacity:1;animation:none;filter:drop-shadow(0 0 9px rgba(251,48,48,.78))}
          @keyframes cw{to{transform:rotate(360deg)}}@keyframes ccw{to{transform:rotate(-360deg)}}@keyframes tieFlow{to{stroke-dashoffset:-32}}
          @keyframes stepCw{to{transform:rotate(360deg)}}@keyframes confirmSweep{0%{opacity:0;stroke-dasharray:0 830;transform:rotate(-90deg)}18%{opacity:1}72%{opacity:1;stroke-dasharray:830 0;transform:rotate(-90deg)}100%{opacity:0;stroke-dasharray:830 0;transform:rotate(-90deg)}}@keyframes successPath{0%{opacity:.35;stroke-dashoffset:32}45%{opacity:1}100%{opacity:1;stroke-dashoffset:-32}}
          @keyframes eyeBreathe{0%,100%{opacity:.34;filter:brightness(.78)}50%{opacity:.76;filter:brightness(1.13) drop-shadow(0 0 8px rgba(255,56,48,.62))}}
          @keyframes lampIdle{0%,100%{opacity:.22}50%{opacity:.58}}
          @keyframes speechEye{0%,100%{opacity:.42;transform:scale(.985);filter:brightness(.86)}18%{opacity:.9;transform:scale(1.025);filter:brightness(1.28) drop-shadow(0 0 10px rgba(255,56,48,.76))}42%{opacity:.56;transform:scale(.995);filter:brightness(.96)}63%{opacity:1;transform:scale(1.035);filter:brightness(1.38) drop-shadow(0 0 12px rgba(255,56,48,.82))}82%{opacity:.62;transform:scale(1);filter:brightness(1.02)}}
          @keyframes speechLamp{0%,100%{opacity:.22}18%{opacity:.72}42%{opacity:.36}63%{opacity:.92}82%{opacity:.44}}
          @media(prefers-reduced-motion:reduce){.solid,.dash,.eye-glow,.lamp,.tie.active,.confirmation-sweep{animation:none!important}}
        </style>
        <div class="entity" part="entity" data-state="idle">
          <svg viewBox="0 60 1200 720" role="img" aria-label="A.R.G.U.S. cockpit pet proof of concept">
            <defs>
              <radialGradient id="iris" cx="38%" cy="34%"><stop stop-color="#ffb1a3"/><stop offset=".16" stop-color="#ff5147"/><stop offset=".5" stop-color="#b5121c"/><stop offset=".82" stop-color="#4e050d"/><stop offset="1" stop-color="#170207"/></radialGradient>
              <radialGradient id="lens" cx="36%" cy="30%"><stop stop-color="#4b171b"/><stop offset=".48" stop-color="#13070b"/><stop offset="1" stop-color="#020509"/></radialGradient>
              <radialGradient id="mask"><stop stop-color="#01060b"/><stop offset=".72" stop-color="#020a12"/><stop offset="1" stop-color="#03101a"/></radialGradient>
              <linearGradient id="lensSheen" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#fff" stop-opacity=".42"/><stop offset=".4" stop-color="#fff" stop-opacity=".04"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
              <clipPath id="eyeAperture"><circle cx="596" cy="404" r="53"/></clipPath>
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
            <circle class="confirmation-sweep" cx="596" cy="404" r="132" pathLength="830"/>
            <circle cx="596" cy="404" r="68" fill="#01050a" opacity=".98"/>
            <circle class="eye-glow" cx="596" cy="404" r="61" fill="none" stroke="#e22b2d" stroke-width="3" opacity=".55" filter="url(#soft)"/>
            <circle cx="596" cy="404" r="55" fill="url(#lens)" stroke="#7e252b" stroke-width="2"/>
            <g clip-path="url(#eyeAperture)">
              <g id="eye" class="eye">
                <circle cx="596" cy="404" r="43" fill="url(#iris)" filter="url(#glow)"/>
                <circle cx="596" cy="404" r="34" fill="none" stroke="#ff786b" stroke-width="8" stroke-dasharray="2 9" opacity=".34"/>
                <circle cx="596" cy="404" r="25" fill="none" stroke="#5d060d" stroke-width="5" stroke-dasharray="1 7" opacity=".75"/>
                <ellipse cx="596" cy="404" rx="13" ry="24" fill="#050104"/>
                <ellipse cx="592" cy="399" rx="5" ry="11" fill="#220309" opacity=".78"/>
                <circle cx="584" cy="389" r="5" fill="#fff5f2" opacity=".88" filter="url(#glow)"/>
                <circle cx="603" cy="394" r="2.4" fill="#ffd1c9" opacity=".72"/>
              </g>
            </g>
            <path d="M 566 379 Q 596 357 625 379 Q 603 370 579 386 Z" fill="url(#lensSheen)" opacity=".55" pointer-events="none"/>
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
        const actionId = action.toLowerCase();
        path.setAttribute('class', 'tie'); path.dataset.action = actionId;
        path.setAttribute('d', `M ${edgeX} ${edgeY} L ${elbow} ${y} L ${x} ${y}`);
        const node = document.createElementNS(NS, 'circle');
        node.setAttribute('class', 'node'); node.dataset.action = actionId; node.setAttribute('cx', x); node.setAttribute('cy', y); node.setAttribute('r', 7);
        ties.append(path, node);
        const button = document.createElement('button');
        button.type = 'button'; button.dataset.action = actionId; button.textContent = action;
        button.style.left = `${x / 12}%`; button.style.top = `${(y - 60) / 7.2}%`;
        const paintHover = on => this.paintActionClass(actionId, 'hover', on);
        button.addEventListener('pointerenter', () => paintHover(true));
        button.addEventListener('pointerleave', () => paintHover(false));
        button.addEventListener('focus', () => paintHover(true));
        button.addEventListener('blur', () => paintHover(false));
        button.addEventListener('click', () => this.dispatchEvent(new CustomEvent('argus-cockpit-action', { bubbles: true, composed: true, detail: { action: button.dataset.action } })));
        buttons.appendChild(button);
      });
    }

    paintActionClass(action, className, on) {
      this.shadowRoot.querySelectorAll(`[data-action="${action}"]`).forEach(node => node.classList.toggle(className, on));
    }

    syncLabels() {
      if (!this.shadowRoot) return;
      const model = this.getAttribute('model') || 'GPT-OSS-120B';
      const status = (this.getAttribute('status') || 'ONLINE').toUpperCase();
      this.shadowRoot.querySelector('.model').textContent = `◆ ${model}`;
      this.shadowRoot.querySelector('.state').textContent = status;
      const visualStates = new Set(['THINKING', 'SPEAKING', 'WORKING', 'SUCCESS', 'WARNING', 'ERROR']);
      const visualState = visualStates.has(status) ? status.toLowerCase() : 'idle';
      this.shadowRoot.querySelector('.entity').dataset.state = visualState;
    }

    track(clientX, clientY) {
      if (this.getAttribute('tracking') === 'off') return this.centerEye();
      const rect = this._eyeNode.getBoundingClientRect();
      const dx = clientX - (rect.left + rect.width / 2), dy = clientY - (rect.top + rect.height / 2);
      const distance = Math.hypot(dx, dy) || 1, strength = Math.min(1, distance / 280);
      this._target.x = dx / distance * 11 * strength;
      this._target.y = dy / distance * 8 * strength;
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
      this.shadowRoot.querySelectorAll('[data-action]').forEach(node => node.classList.toggle('active', active.has(node.dataset.action)));
    }
  }

  customElements.define('argus-cockpit-pet', ArgusCockpitPet);
})();
