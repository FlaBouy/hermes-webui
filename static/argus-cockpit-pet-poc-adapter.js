/* Isolated POC adapter. Production does not import this file. */
(() => {
  'use strict';
  if (window.ArgusCockpitPocAdapter) return;

  const ACTION_IDS = Object.freeze([
    'chat', 'tasks', 'kanban', 'skills', 'memory', 'spaces',
    'profiles', 'todos', 'insights', 'logs', 'settings', 'tools',
  ]);
  const ACTION_SET = new Set(ACTION_IDS);
  const STATE_IDS = Object.freeze([
    'online', 'listening', 'thinking', 'speaking', 'dispatch',
    'working', 'success', 'warning', 'error', 'sleep',
  ]);

  class ArgusCockpitPocAdapter {
    constructor({ orb, composer, response, statusOutput } = {}) {
      if (!orb || !composer) throw new TypeError('Orb and composer are required');
      this.orb = orb;
      this.composer = composer;
      this.response = response || null;
      this.statusOutput = statusOutput || null;
      this.activeAction = null;
      this.lastComposerControl = null;
      this.lastSubmissionLength = 0;
      this.connected = false;
      this._onAction = event => this.selectAction(event.detail?.action);
      this._onControl = event => {
        this.lastComposerControl = String(event.detail?.control || '');
        this.publish();
      };
      this._onSubmit = event => {
        this.lastSubmissionLength = String(event.detail?.text || '').length;
        this.publish();
      };
    }

    connect() {
      if (this.connected) return this;
      this.orb.addEventListener('argus-cockpit-action', this._onAction);
      this.composer.addEventListener('argus-cockpit-control', this._onControl);
      this.composer.addEventListener('argus-cockpit-submit', this._onSubmit);
      this.connected = true;
      this.publish();
      return this;
    }

    disconnect() {
      if (!this.connected) return this;
      this.orb.removeEventListener('argus-cockpit-action', this._onAction);
      this.composer.removeEventListener('argus-cockpit-control', this._onControl);
      this.composer.removeEventListener('argus-cockpit-submit', this._onSubmit);
      this.connected = false;
      return this;
    }

    selectAction(action) {
      const requested = String(action || '').toLowerCase();
      if (!ACTION_SET.has(requested)) return false;
      this.activeAction = this.activeAction === requested ? null : requested;
      this.orb.setActiveActions(this.activeAction ? [this.activeAction] : []);
      if (this.response && requested === 'chat') this.response.hidden = this.activeAction !== 'chat';
      this.publish();
      return true;
    }

    snapshot() {
      return Object.freeze({
        contractVersion: 1,
        actionCount: ACTION_IDS.length,
        actions: Object.freeze(ACTION_IDS.slice()),
        activeAction: this.activeAction,
        orbStatus: (this.orb.getAttribute('status') || 'online').toLowerCase(),
        composerState: (this.composer.dataset.state || 'online').toLowerCase(),
        lastComposerControl: this.lastComposerControl,
        lastSubmissionLength: this.lastSubmissionLength,
      });
    }

    verifyParity() {
      const root = this.orb.shadowRoot;
      const actionCoverage = ACTION_IDS.map(action => ({
        action,
        menuButtons: root?.querySelectorAll(`.menu-button[data-action="${action}"]`).length || 0,
        pathParts: root?.querySelectorAll(`[data-action="${action}"]`).length || 0,
      }));
      const stateButtons = Array.from(document.querySelectorAll('.states [data-state]'), button => button.dataset.state);
      const composerControls = this.composer.querySelectorAll('[data-composer-action]').length;
      const result = {
        actionCount: ACTION_IDS.length,
        stateCount: STATE_IDS.length,
        actionCoverage,
        stateButtons,
        composerControls,
        actionParity: actionCoverage.every(item => item.menuButtons === 1 && item.pathParts === 5),
        stateParity: STATE_IDS.every(state => stateButtons.includes(state)) && stateButtons.length === STATE_IDS.length,
        composerParity: composerControls === 6,
        productionWired: false,
      };
      result.passed = result.actionParity && result.stateParity && result.composerParity && !result.productionWired;
      return Object.freeze(result);
    }

    publish() {
      const snapshot = this.snapshot();
      const parity = this.verifyParity();
      if (this.statusOutput) {
        const prefix = parity.passed ? 'PARITY PASS · 12/12 · 10/10' : 'PARITY CHECK FAILED';
        this.statusOutput.textContent = snapshot.activeAction
          ? `${prefix} · ${snapshot.activeAction.toUpperCase()}`
          : prefix;
      }
      this.orb.dispatchEvent(new CustomEvent('argus-cockpit-contract-state', {
        bubbles: true, composed: true, detail: snapshot,
      }));
      return snapshot;
    }
  }

  Object.defineProperty(ArgusCockpitPocAdapter, 'actionIds', { value: ACTION_IDS });
  Object.defineProperty(ArgusCockpitPocAdapter, 'stateIds', { value: STATE_IDS });
  window.ArgusCockpitPocAdapter = ArgusCockpitPocAdapter;
})();
