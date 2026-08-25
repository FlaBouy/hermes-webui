(() => {
  'use strict';
  if (window.__biggyBrandLoaded) return;
  window.__biggyBrandLoaded = true;

  const DOC_TITLE = 'Biggy — Local Fleet Coordinator';
  const ROLE = 'Local Fleet Coordinator';
  const BRAND = 'Biggy';
  const PLACEHOLDER = 'Message Biggy…';
  const IWO_CLASS = 'biggy-brand-iwo';
  const BODY_CLASS = 'biggy-brand';
  const PTT_PROXY = '/api/extensions/biggy-brand/sidecar';
  const GUI_ID = 'biggy';
  const PROFILE_ID = 'biggy';
  const PTT_INSTANCE = 'biggy';
  const BUILD_ID = '20260825-cockpit-rail-1';
  const ARGUS_SYNC_STORAGE_KEY = 'biggy:argus-speech-sync:v1';
  const V6_HEALTH_PATH = '/api/biggy/v6/health';
  const V6_CHAT_PATH = '/api/biggy/v6/chat';
  const V6_WORLD_PATH = '/api/biggy/v6/world';
  const V6_WORLD_TREE_PATH = '/api/biggy/v6/world/tree';
  const V6_WORLD_STATUS_PATH = '/api/biggy/v6/world/status';
  const V6_WORLD_RETRY_PATH = '/api/biggy/v6/world/retry';
  const V6_WORLD_DISPOSITION_PATH = '/api/biggy/v6/world/disposition';
  const ORB_STATES = Object.freeze([
    'offline', 'online', 'thinking', 'speaking', 'tool-running', 'error',
  ]);
  const SESSION_STORAGE_KEY = `hermes-gui-session:${GUI_ID}`;
  const DIAG_FLAG_KEY = `hermes-gui-debug:${GUI_ID}`;
  try {
    Object.defineProperty(window, '__HERMES_GUI_ID__', {
      value: GUI_ID,
      writable: false,
      configurable: false,
    });
  } catch (_) {
    window.__HERMES_GUI_ID__ = GUI_ID;
  }
  try {
    Object.defineProperty(window, '__HERMES_PROFILE_ID__', {
      value: PROFILE_ID,
      writable: false,
      configurable: false,
    });
  } catch (_) {
    window.__HERMES_PROFILE_ID__ = PROFILE_ID;
  }
  window.__BIGGY_BUILD_ID__ = BUILD_ID;

  const state = {
    profile: PROFILE_ID,
    model: '',
    provider: '',
    providerLabel: '',
    ready: false,
    sessionId: '',
  };
  let identityTimer = null;
  let diagTimer = null;
  let ragWorldTimer = null;
  let conversationLaneTimer = null;
  let conversationLaneRenderQueued = false;
  let completionMessages = [];
  let completionMessagesSessionId = '';
  let ragTraceObserverInstalled = false;
  let ragTraceStatusListenerInstalled = false;
  let ragWorldReady = false;
  let pendingRagTrace = null;
  let started = false;
  let pttInstalled = false;
  let sessionEnsurePromise = null;

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  function el(tag, className, html) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (html !== undefined) node.innerHTML = html;
    return node;
  }

  function providerLabel(id) {
    const raw = String(id || '').trim();
    if (!raw) return '';
    const key = raw.toLowerCase();
    if (key === 'lmstudio' || key === 'lm-studio' || key === 'lm_studio') return 'LM Studio';
    if (key === 'openai') return 'OpenAI';
    if (key === 'anthropic') return 'Anthropic';
    if (key === 'custom' || key.startsWith('custom:')) return 'Custom';
    return raw;
  }

  function brandVisibleText(value) {
    if (typeof value !== 'string' || !value) return value;
    // Shared static defaults say "Smedley Voice"; Biggy must rewrite voice chrome only.
    // Do NOT globally rewrite the word Smedley (host/RAG references stay valid).
    let next = value
      .replace(/Smedley Voice/g, 'Biggy Voice')
      .replace(/Exit Smedley Voice/g, 'Exit Biggy Voice')
      .replace(/Connecting Smedley Voice/g, 'Connecting Biggy Voice')
      .replace(/Disconnect Smedley Voice/g, 'Disconnect Biggy Voice')
      .replace(/Stop Smedley Voice/g, 'Stop Biggy Voice')
      .replace(/Smedley Voice ·/g, 'Biggy Voice ·')
      .replace(/GPT Voice/g, 'Biggy Voice');
    if (/hermes/i.test(next)) {
      next = next
        .replace(/\bHERMES\b/g, 'BIGGY')
        .replace(/\bHermes\b/g, 'Biggy')
        .replace(/\bhermes\b/g, 'biggy');
    }
    return next;
  }

  function rewriteGptVoiceInLocales() {
    try {
      if (typeof LOCALES !== 'object' || !LOCALES) return;
      Object.keys(LOCALES).forEach((lang) => {
        const bag = LOCALES[lang];
        if (!bag || typeof bag !== 'object') return;
        Object.keys(bag).forEach((key) => {
          const val = bag[key];
          if (typeof val !== 'string' || !/(GPT Voice|Smedley Voice)/i.test(val)) return;
          bag[key] = brandVisibleText(val);
        });
      });
    } catch (_) {}
    try {
      if (typeof applyLocaleToDOM === 'function') applyLocaleToDOM();
    } catch (_) {}
  }

  function rewriteGptVoiceInDom(root) {
    const scope = root || document;
    const ATTRS = ['data-tooltip', 'title', 'aria-label', 'placeholder', 'alt'];
    const nodes = scope.querySelectorAll
      ? scope.querySelectorAll('#btnGptVoice, #gptVoiceLabel, #gptVoiceBar, #btnGptVoiceStop, #btnGptVoiceTalk, [data-i18n*="gpt_voice"], [data-i18n-title*="gpt_voice"], [data-tooltip*="GPT Voice"], [aria-label*="GPT Voice"], [data-tooltip*="Smedley Voice"], [aria-label*="Smedley Voice"]')
      : [];
    nodes.forEach((node) => {
      ATTRS.forEach((attr) => {
        if (!node.hasAttribute || !node.hasAttribute(attr)) return;
        const cur = node.getAttribute(attr);
        const next = brandVisibleText(cur);
        if (next !== cur) node.setAttribute(attr, next);
      });
      if (node.childNodes && node.childNodes.length === 1 && node.firstChild.nodeType === Node.TEXT_NODE) {
        const cur = node.textContent;
        const next = brandVisibleText(cur);
        if (next !== cur) node.textContent = next;
      }
    });
    // Catch settings copy and any leftover text nodes under voice chrome.
    [
      'gptVoiceLabel',
      'btnGptVoice',
      'btnGptVoiceStop',
      'settings_label_gpt_realtime_voice',
    ].forEach((id) => {
      const node = document.getElementById(id);
      if (!node || typeof node.textContent !== 'string') return;
      const next = brandVisibleText(node.textContent);
      if (next !== node.textContent) node.textContent = next;
    });
    document.querySelectorAll('[data-i18n="settings_label_gpt_realtime_voice"], [data-i18n="settings_desc_gpt_realtime_voice"]').forEach((node) => {
      const next = brandVisibleText(node.textContent || '');
      if (next && next !== node.textContent) node.textContent = next;
    });
  }

  function installBiggyVoiceLabels() {
    rewriteGptVoiceInLocales();
    rewriteGptVoiceInDom(document);
    if (window.__biggyVoiceLabelTimer) return;
    // realtime_voice.js rewrites labels on state changes; keep Biggy naming sticky.
    window.__biggyVoiceLabelTimer = setInterval(() => {
      rewriteGptVoiceInDom(document);
    }, 1500);
  }

  function smedleyWebUiUrl() {
    try {
      const url = new URL(window.location.href);
      url.port = '8787';
      url.pathname = '/';
      url.search = '';
      url.hash = '';
      return url.toString();
    } catch (_) {
      return 'http://127.0.0.1:8787/';
    }
  }

  function openSmedleyGui() {
    const target = smedleyWebUiUrl();
    window.open(target, 'smedley-webui', 'noopener,noreferrer');
  }

  function isPhoneOrTabletClient() {
    try {
      const ua = String(navigator.userAgent || '');
      if (/iPhone|iPod|Android.+Mobile|Windows Phone|Mobile.+Safari/i.test(ua)) return true;
      if (/iPad|Android(?!.+Mobile)|Tablet|Kindle|Silk/i.test(ua)) return true;
      // iPadOS 13+ reports as Mac; treat touch Macs with coarse pointer as tablets.
      if (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1) return true;
      if (window.matchMedia && window.matchMedia('(pointer: coarse)').matches && window.matchMedia('(max-width: 1100px)').matches) {
        return true;
      }
    } catch (_) {}
    return false;
  }

  function stripGlassLabelsForSpeech(text) {
    let clean = String(text || '');
    // Glass / board chrome — never voice pills, lane names, or card title prefixes.
    const labelRes = [
      /\bOwner\s*ACK\b\s*:?/gi,
      /\bOwnerACK\b\s*:?/gi,
      /\bOPEN BIGGY TO DISPOSE\b/gi,
      /\bOpen Biggy to (?:APPROVE|REJECT|DISPOSE)\b/gi,
      /\b(?:please\s+)?(?:APPROVE|REJECT)\b(?=\s*[.!?,]|$)/gi,
      /\bCLOSE\s*\/\s*ACK\b/gi,
      /\bCLOSE STALE\b/gi,
      /\bCANCEL SCHEDULED\b/gi,
      /\b(?:BIGGY|HERMES|CURSOR|CLAUDE|GPT|VAL|FLEET)\s+(?:pill|lane|card|label|badge|source)\b/gi,
      /\b(?:pill|lane|card|label|badge)\s+(?:BIGGY|HERMES|CURSOR|CLAUDE|GPT|VAL|FLEET)\b/gi,
      /\bsource[_ ](?:pill|system|host)\b/gi,
      /\b(?:on|in|the)\s+Attention\b/gi,
      /\bAttention\s+(?:pane|column|lane)\b/gi,
      /\b(?:Scheduled|Archived|Complete)\s+(?:pane|column|lane|card)\b/gi,
      /\bACK-[A-Za-z0-9._-]+\b/g,
      /\bt_[0-9a-f]{8}\b/gi,
      /(?:^|[\s"'(])(?:OwnerACK|Cursor(?:\/[A-Za-z0-9._-]+)?|Hermes(?:\/[A-Za-z0-9._-]+)?|Claude)\s*[:\/—-]+\s*/gi,
    ];
    for (let i = 0; i < 3; i += 1) {
      for (const re of labelRes) clean = clean.replace(re, ' ');
    }
    clean = clean.replace(/(?:^|[\s,;:])(?:BIGGY|HERMES|CURSOR|CLAUDE|GPT|VAL|FLEET|UNKNOWN)(?=\s|[.,!?;:]|$)\s*/g, ' ');
    for (let i = 0; i < 4; i += 1) {
      const next = clean.replace(/\b(?:with|a|an|the|says?|needs?|for|to|on|in|of|and|or)\s*[.!?]*\s*$/i, '').trim();
      if (next === clean.trim()) break;
      clean = next;
    }
    return clean.replace(/\s+/g, ' ').replace(/\s+([.!?])/g, '$1').trim();
  }

  function stripForSmedleySpeak(raw) {
    let clean = String(raw || '');
    if (typeof window._stripForTTS === 'function') {
      try { clean = String(window._stripForTTS(clean) || ''); } catch (_) {}
    } else {
      // Fallback mirrors ui.js voice-safe document sanitizer when TTS helper
      // is unavailable (load order / non-chat surfaces): answer prose only.
      clean = clean
        .replace(/(^|\n)[ \t]*Document links(?:\s+for\s+[“"][^”"]*[”"])?(?:\s*\(sidecar preview\))?\s*:?[ \t]*(?=\n|$)/gi, '$1')
        .replace(/\bDocument links(?:\s+for\s+[“"][^”"]*[”"])?(?:\s*\(sidecar preview\))?\s*:?/gi, ' ')
        .replace(/\(\s*score\s*=\s*[-+]?\d*\.?\d+\s*\)/gi, ' ')
        .replace(/\b(?:sidecar preview|lan_url|card title|source pill|owner\s*ack)\b\s*:?/gi, ' ');
      for (let i = 0; i < 8; i += 1) {
        const next = clean.replace(/\{[^{}]*\}/g, (body) => (
          /"(?:matches|collection|lan_url|snippet|source|score|url|markdown)"\s*:/i.test(body) ? ' ' : body
        ));
        if (next === clean) break;
        clean = next;
      }
      clean = clean
        .replace(/\b(?:matches|collection|snippet|source|topk|library_only|snippet_chars)\b\s*[:=]\s*/gi, ' ');
      if (/"matches"\s*:/i.test(clean) || /\b(?:matches|collection)\b\s*[:=]/i.test(clean)) {
        clean = '';
      } else {
        clean = clean
          .replace(/```[\s\S]*?```/g, ' ')
          .replace(/`([^`]*)`/g, '$1')
          .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
          .replace(/\[[^\]]*\]\([^)]*\)/g, ' ')
          .replace(/https?:\/\/[^\s<>\]\)"']+/gi, ' ')
          .replace(/\/api\/extensions\/smedley-engineering\/sidecar\/(?:preview|doc)\/[^\s<>\]\)"']*/gi, ' ')
          .replace(/\b[\w./\\-]+\.(?:pdf|docx?|xlsx?|pptx?|txt|md)\b/gi, ' ')
          .replace(/#{1,6}\s/g, '')
          .replace(/[*_~]+/g, '')
          .replace(/(^|\n)[ \t]*[-*•]\s+/g, '$1')
          .replace(/\n{2,}/g, '. ')
          .replace(/\n/g, ' ');
        clean = clean.replace(/\s+/g, ' ').replace(/\s+([,.;:!?])/g, '$1').trim();
      }
    }
    return stripGlassLabelsForSpeech(clean);
  }

  function resolveAskJarvisVoiceId() {
    // Last Ask Jarvis hard-bind turn only — do not change Biggy default Austin.
    try {
      const msgs = (typeof S !== 'undefined' && Array.isArray(S.messages)) ? S.messages : [];
      for (let i = msgs.length - 1; i >= 0; i--) {
        const m = msgs[i];
        if (m && m.role === 'assistant' && m.ask_jarvis_hard_bind) {
          return String(m.tts_voice_id || 'rvugSNzdY0NcpG2PKe4B').trim();
        }
        if (m && m.role === 'assistant') break;
      }
      const rows = document.querySelectorAll('.assistant-segment[data-raw-text]');
      const last = rows.length ? rows[rows.length - 1] : null;
      const fromDom = last && last.dataset ? String(last.dataset.ttsVoiceId || '').trim() : '';
      if (fromDom) return fromDom;
    } catch (_) {}
    return '';
  }

  function splitSmedleySpeech(text, maxChars) {
    const limit = Math.max(200, Number(maxChars) || 760);
    let remaining = String(text || '').replace(/\s+/g, ' ').trim();
    const chunks = [];
    while (remaining.length > limit) {
      const windowText = remaining.slice(0, limit + 1);
      const candidates = [
        windowText.lastIndexOf('. '),
        windowText.lastIndexOf('! '),
        windowText.lastIndexOf('? '),
        windowText.lastIndexOf('; '),
        windowText.lastIndexOf(': '),
        windowText.lastIndexOf(', '),
        windowText.lastIndexOf(' '),
      ];
      let cut = Math.max.apply(null, candidates);
      // Prefer a natural boundary, but never let one long sentence exceed the
      // speech service's 800-character contract.
      if (cut < Math.floor(limit * .55)) cut = limit;
      else cut += 1;
      const chunk = remaining.slice(0, cut).trim();
      if (chunk) chunks.push(chunk);
      remaining = remaining.slice(cut).trim();
    }
    if (remaining) chunks.push(remaining);
    return chunks;
  }

  let smedleySpeechTail = Promise.resolve();

  async function speakOnSmedley(text, opts) {
    opts = opts || {};
    const clean = stripForSmedleySpeak(text);
    if (!clean) return false;
    let voiceId = opts.voice_id ? String(opts.voice_id).trim() : '';
    // Exact override: speechSynthesis sink and other no-opts callers were
    // posting /speak with no voice_id → Austin. Ask Argus turns must carry
    // Alistar through this single Smedley-sink choke point.
    if (!voiceId) voiceId = resolveAskJarvisVoiceId();
    if (!/^[A-Za-z0-9_-]{8,64}$/.test(voiceId)) voiceId = '';
    const chunks = splitSmedleySpeech(clean, 760);
    const dispatch = async () => {
      try {
        for (const chunk of chunks) {
          const body = { text: chunk, wait: true };
          if (voiceId) body.voice_id = voiceId;
          // wait=true makes each chunk finish playback before the next begins;
          // this prevents both the former 800-character cutoff and overlap.
          await proxyJson('/speak', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          });
        }
        return true;
      } catch (_) {
        return false;
      }
    };
    const queued = smedleySpeechTail.catch(() => false).then(dispatch);
    smedleySpeechTail = queued;
    return queued;
  }

  function isGreetingPrompt(text) {
    return /^\s*good\s+(morning|afternoon)\s*,?\s*biggy\b/i.test(String(text || '').trim());
  }

  function installGreetingAck() {
    if (window.__biggyGreetingAckPatched) return;
    window.__biggyGreetingAckPatched = true;
    const fire = (raw) => {
      try {
        if (!isGreetingPrompt(raw)) return;
        // Immediate ack while Hermes/prefill catches up.
        speakOnSmedley('Just a sec, Rick...');
      } catch (_) {}
    };
    // Capture send from common Hermes/Biggy composers.
    document.addEventListener('keydown', (ev) => {
      try {
        if (ev.key !== 'Enter' || ev.shiftKey) return;
        const t = ev.target;
        if (!t) return;
        const tag = (t.tagName || '').toLowerCase();
        if (tag !== 'textarea' && tag !== 'input' && !t.isContentEditable) return;
        const val = t.isContentEditable ? (t.textContent || '') : (t.value || '');
        fire(val);
      } catch (_) {}
    }, true);
    document.addEventListener('click', (ev) => {
      try {
        const btn = ev.target && ev.target.closest
          ? ev.target.closest('button[type="submit"], button.send, .send-button, [data-testid="send"], #send-button')
          : null;
        if (!btn) return;
        const box = document.querySelector('textarea, [contenteditable="true"], .composer textarea, #prompt');
        if (!box) return;
        const val = box.isContentEditable ? (box.textContent || '') : (box.value || '');
        fire(val);
      } catch (_) {}
    }, true);
  }

  function installSmedleyAudioPolicy() {
    const mobile = isPhoneOrTabletClient();
    window.__biggyAudioSink = mobile ? 'local' : 'smedley';
    document.body.dataset.biggyAudioSink = window.__biggyAudioSink;

    // Desktop/remote GUIs: never play Biggy on the viewing machine.
    // Spoken output is Smedley room (soundbar/speakers) or headset via pedal TTS.
    // Tablets retain their local voice controls, but still install the Argus
    // guard below so browser auto-read cannot replace Alistar with Austin.
    if (!mobile) try {
      if (window.speechSynthesis && !window.__biggySpeechSynthPatched) {
        const synth = window.speechSynthesis;
        const origSpeak = synth.speak.bind(synth);
        synth.speak = function biggySinkSpeak(utter) {
          try {
            const text = utter && typeof utter.text === 'string' ? utter.text : '';
            if (text) speakOnSmedley(text);
            if (utter && typeof utter.onend === 'function') {
              setTimeout(() => { try { utter.onend(); } catch (_) {} }, 0);
            }
          } catch (_) {}
          try { synth.cancel(); } catch (_) {}
        };
        window.__biggySpeechSynthPatched = true;
        window.__biggySpeechSynthOrigSpeak = origSpeak;
      }
    } catch (_) {}

    // Keep the Biggy Voice button visible. Desktop browser TTS / auto-read
    // still sinks to Smedley room/headset via /speak; WebRTC Biggy Voice remains
    // available for hold-to-talk when the operator wants it.

    // Route hands-free / auto-read assistant replies to Smedley speakers.
    // Retry until autoRead exists — first shell paint can outrun ui.js define.
    const installAutoReadSink = function () {
      if (typeof window.autoReadLastAssistant !== 'function') return false;
      if (window.__biggyAutoReadJarvisVoice === true) return true;
      const prior = window.autoReadLastAssistant;
      window.autoReadLastAssistant = function biggyAutoReadToSmedley() {
        try {
          // Ask Argus hard-bind: spoken_text only + Alistar voice override.
          const msgs = (typeof S !== 'undefined' && Array.isArray(S.messages)) ? S.messages : [];
          let jarvisMsg = null;
          for (let i = msgs.length - 1; i >= 0; i--) {
            if (msgs[i] && msgs[i].role === 'assistant' && msgs[i].ask_jarvis_hard_bind) {
              jarvisMsg = msgs[i];
              break;
            }
            if (msgs[i] && msgs[i].role === 'assistant') break;
          }
          if (jarvisMsg) {
            // Pending working bubble has no spoken_text; never invent/speak it.
            if (jarvisMsg.ask_jarvis_pending) return;
            // A hard-bound final is always server-owned Alistar speech.  This
            // includes tablets: auto-read otherwise uses the browser's Austin
            // selection and can read the long display answer instead.
            return;
          }
          // Preserve the tablet's normal local auto-read behavior for ordinary
          // Biggy responses; only hard-bound Argus finals are server-owned.
          if (mobile) return prior.apply(this, arguments);
          const rows = document.querySelectorAll('.msg-row[data-role="assistant"], .assistant-segment[data-raw-text]');
          const last = rows.length ? rows[rows.length - 1] : null;
          const raw = last && (last.dataset.rawText || last.textContent) || '';
          if (raw.trim()) {
            const voiceId = last && last.dataset ? (last.dataset.ttsVoiceId || '') : '';
            speakOnSmedley(raw, voiceId ? { voice_id: voiceId } : {});
            return;
          }
        } catch (_) {}
        // Fall through only if we couldn't extract text.
        try { return prior.apply(this, arguments); } catch (_) {}
      };
      window.__biggyAutoReadJarvisVoice = true;
      window.__biggyAutoReadPatched = true;
      return true;
    };
    if (!installAutoReadSink()) {
      let tries = 0;
      const timer = setInterval(function () {
        tries += 1;
        if (installAutoReadSink() || tries >= 20) clearInterval(timer);
      }, 250);
    }

    const note = document.getElementById('biggyHeaderNote');
    if (!mobile && note && !note.textContent) {
      note.textContent = 'Audio → Smedley room/headset';
      setTimeout(() => {
        if (note.textContent === 'Audio → Smedley room/headset') note.textContent = '';
      }, 5000);
    }
  }

  function isBiggyInstance() {
    if (state.ready && state.profile === 'biggy') return true;
    try {
      if (typeof S !== 'undefined' && S && String(S.activeProfile || '').toLowerCase() === 'biggy') {
        return true;
      }
    } catch (_) {}
    return state.profile === 'biggy';
  }

  function installDocumentTitle() {
    document.title = DOC_TITLE;
    const apple = document.querySelector('meta[name="apple-mobile-web-app-title"]');
    if (apple) apple.setAttribute('content', BRAND);
  }

  function installComposerBranding() {
    const composer = document.getElementById('msg');
    if (!composer) return;
    if (composer.getAttribute('placeholder') !== PLACEHOLDER) {
      composer.setAttribute('placeholder', PLACEHOLDER);
    }
  }

  const FLEET_STATUS_PATH = '/api/biggy/fleet/status';
  let fleetStatusTimer = 0;

  function fleetButtonTitle(machine) {
    const state = String(machine.state || 'offline').toUpperCase();
    const worker = machine.worker_state ? ` · worker ${machine.worker_state}` : '';
    const action = machine.kind === 'rdp' ? 'Open remote desktop'
      : machine.kind === 'hermes' ? 'Open Smedley Hermes GUI'
      : 'Open TrueNAS login';
    return `${machine.id} · ${state}${worker} · ${action}`;
  }

  function launchFleetMachine(machine) {
    if (!machine) return;
    if (machine.kind === 'hermes') {
      openSmedleyGui();
      return;
    }
    const target = String(machine.launch_url || '');
    if (!target) return;
    if (machine.kind === 'web') {
      window.open(target, 'biggy-plato-truenas', 'noopener,noreferrer');
      return;
    }
    // Windows App registers the rdp: protocol on Smedley. Assigning the URL
    // from a direct user click preserves browser gesture authority.
    window.location.href = target;
  }

  function resetBiggyWorkspace() {
    clearRagTrace();
    markGalaxyFilterSelection('', 0);

    const dlg = document.getElementById('biggyTravelMapDialog');
    if (dlg) {
      if (typeof dlg.__biggySetCollapsed === 'function') dlg.__biggySetCollapsed(true);
      dlg.removeAttribute('data-rec-category');
      dlg.removeAttribute('data-active-category');
      dlg.classList.remove('has-lodging');
      const cards = dlg.querySelector('#biggyTravelLodgingCards');
      const rec = dlg.querySelector('#biggyTravelLodging');
      const actions = dlg.querySelector('#biggyTravelMapActions');
      const note = dlg.querySelector('#biggyTravelMapNote');
      const empty = dlg.querySelector('#biggyTravelEmptyCat');
      if (cards) cards.innerHTML = '';
      if (rec) {
        rec.hidden = true;
        rec.removeAttribute('data-rec-category');
        rec.setAttribute('data-has-cards', '0');
      }
      if (actions) {
        actions.innerHTML = '';
        actions.removeAttribute('data-action-category');
      }
      if (note) note.textContent = '';
      if (empty) empty.hidden = true;
      dlg.querySelectorAll('.biggy-category-rail-btn').forEach((button) => {
        button.classList.remove('is-active');
        button.setAttribute('aria-pressed', 'false');
      });
    }

    Object.keys(recommendationModelsByCategory).forEach((key) => {
      delete recommendationModelsByCategory[key];
    });
    lastMapModelKey = '';
    // Home must also resume the iframe if a route map was in the middle of
    // initializing.  Removing Mapbox alone leaves the Galaxy's renderer in
    // its paused state.
    releaseTravelMap();
  }

  function makeHomeControl() {
    const home = el('button', 'biggy-fleet-machine biggy-fleet-home is-online');
    home.type = 'button';
    home.dataset.machine = 'HOME';
    home.title = 'Reset galaxy and clear PA cards';
    home.setAttribute('aria-label', home.title);
    home.innerHTML = '<span class="biggy-fleet-state" aria-hidden="true"></span><span>HOME</span>';
    home.addEventListener('click', (event) => {
      event.preventDefault();
      resetBiggyWorkspace();
    });
    return home;
  }

  function makeSpeechSyncControl() {
    const sync = el('span', 'biggy-fleet-sync-wrap');
    sync.innerHTML =
      '<button id="argusSpeechSyncToggle" class="biggy-fleet-machine biggy-fleet-sync is-online" type="button" '
      + 'aria-expanded="false" aria-controls="argusSpeechSyncPanel" title="Tune A.R.G.U.S. speech pulse timing">'
      + '<span class="biggy-fleet-state" aria-hidden="true"></span><span>SYNC</span></button>'
      + '<div id="argusSpeechSyncPanel" class="biggy-argus-sync-panel" hidden>'
      + '<label>GAIN <input id="argusSpeechSyncGain" type="range" min="0.5" max="2" step="0.05">'
      + '<output id="argusSpeechSyncGainOut">100%</output></label>'
      + '<label>LEAD <input id="argusSpeechSyncLead" type="range" min="-250" max="300" step="10">'
      + '<output id="argusSpeechSyncLeadOut">+80 ms</output></label></div>';
    installArgusSpeechSyncTuner(sync);
    return sync;
  }

  function renderFleetStrip(strip, payload) {
    if (!strip || !payload || !Array.isArray(payload.machines)) return;
    const machines = payload.machines;
    strip.innerHTML = '<span class="biggy-fleet-strip-label">FLEET</span>';
    machines.forEach((machine) => {
      const button = el('button', `biggy-fleet-machine is-${machine.state || 'offline'}`);
      button.type = 'button';
      button.dataset.machine = machine.id;
      button.dataset.kind = machine.kind;
      button.title = fleetButtonTitle(machine);
      button.setAttribute('aria-label', button.title);
      button.innerHTML = `<span class="biggy-fleet-state" aria-hidden="true"></span><span>${machine.label}</span>`;
      button.addEventListener('click', (event) => {
        event.preventDefault();
        launchFleetMachine(machine);
      });
      strip.appendChild(button);
    });
  }

  async function refreshFleetStrip(strip) {
    if (!strip || !strip.isConnected || document.hidden) return;
    try {
      const response = await fetch(FLEET_STATUS_PATH, { credentials: 'same-origin', cache: 'no-store' });
      if (!response.ok) throw new Error(`fleet status ${response.status}`);
      renderFleetStrip(strip, await response.json());
    } catch (_) {
      strip.querySelectorAll('.biggy-fleet-machine').forEach((button) => {
        button.classList.remove('is-online', 'is-busy', 'is-error');
        button.classList.add('is-offline');
      });
    }
  }

  function installFleetStrip() {
    const composer = document.getElementById('composerWrap');
    if (!composer) return null;
    document.querySelectorAll('.biggy-fleet-strip').forEach((node) => node.remove());
    const strip = el('nav', 'biggy-fleet-strip');
    strip.id = 'biggyFleetStrip';
    strip.setAttribute('aria-label', 'Fleet machine status and launch controls');
    strip.setAttribute('data-testid', 'biggy-fleet-strip');
    composer.appendChild(strip);
    refreshFleetStrip(strip).catch(() => {});
    if (fleetStatusTimer) window.clearInterval(fleetStatusTimer);
    fleetStatusTimer = window.setInterval(() => refreshFleetStrip(strip).catch(() => {}), 15000);
    return strip;
  }

  function installCockpitStrip(header) {
    const controls = header && header.querySelector('.biggy-brand-controls');
    const mainChat = document.getElementById('mainChat');
    if (!controls || !mainChat) return null;
    document.querySelectorAll('.biggy-cockpit-strip').forEach((node) => node.remove());

    const strip = el('nav', 'biggy-cockpit-strip');
    strip.id = 'biggyCockpitStrip';
    strip.setAttribute('aria-label', 'Biggy cockpit controls');
    strip.setAttribute('data-testid', 'biggy-cockpit-strip');
    strip.innerHTML = '<span class="biggy-fleet-strip-label">COCKPIT</span>';
    strip.appendChild(makeHomeControl());
    strip.appendChild(makeSpeechSyncControl());

    const filter = el('button', 'biggy-fleet-machine biggy-cockpit-filter is-online');
    filter.type = 'button';
    filter.title = 'Filter the galaxy by RAG directory';
    filter.setAttribute('aria-label', filter.title);
    filter.innerHTML = '<span class="biggy-fleet-state" aria-hidden="true"></span><span>FILTER</span>';
    filter.addEventListener('click', (event) => {
      event.preventDefault();
      const railFilter = document.getElementById('biggyCatRail-filter');
      if (railFilter) railFilter.click();
    });
    strip.appendChild(filter);

    const ptt = controls.querySelector('#biggyPtt');
    const route = controls.querySelector('#biggyAudioRoute');
    [ptt, route].forEach((button) => {
      if (!button) return;
      button.classList.add('biggy-fleet-machine', 'biggy-cockpit-action');
      strip.appendChild(button);
    });
    if (ptt) ptt.textContent = 'PTT';
    controls.remove();
    mainChat.appendChild(strip);
    return strip;
  }

  function forceChromeLabels() {
    const title = document.getElementById('appTitlebarTitle');
    if (title && title.textContent.trim() !== BRAND) title.textContent = BRAND;

    const profileLabel = document.getElementById('profileChipLabel');
    if (profileLabel && profileLabel.textContent.trim().toLowerCase() === 'default') {
      profileLabel.textContent = 'biggy';
    }
    const titleProfile = document.getElementById('titlebarProfileLabel');
    if (titleProfile && titleProfile.textContent.trim().toLowerCase() === 'default') {
      titleProfile.textContent = 'biggy';
    }

    try {
      window._botName = BRAND;
      if (typeof S !== 'undefined' && S) {
        if (!S.activeProfile || S.activeProfile === 'default') {
          S.activeProfile = 'biggy';
          S.activeProfileIsDefault = false;
        }
      }
    } catch (_) {}

    const onboardingTitle = document.getElementById('onboardingTitle');
    if (onboardingTitle) {
      const next = brandVisibleText(onboardingTitle.textContent || '');
      if (next && next !== onboardingTitle.textContent) onboardingTitle.textContent = 'Welcome to Biggy';
      else if (/hermes/i.test(onboardingTitle.textContent || '')) onboardingTitle.textContent = 'Welcome to Biggy';
    }
    const onboardingLead = document.getElementById('onboardingLead');
    if (onboardingLead && /hermes/i.test(onboardingLead.textContent || '')) {
      onboardingLead.textContent =
        'A quick guided setup will check your Biggy install, choose a workspace and model, and optionally protect the app with a password.';
    }

    [
      'appTitlebarTitle',
      'offlineAutorefresh',
      'agentHealthTitle',
    ].forEach((id) => {
      const node = document.getElementById(id);
      if (!node || !node.firstChild || node.firstChild.nodeType !== Node.TEXT_NODE) {
        if (node && typeof node.textContent === 'string' && /hermes/i.test(node.textContent)) {
          node.textContent = brandVisibleText(node.textContent);
        }
        return;
      }
      const next = brandVisibleText(node.textContent);
      if (next !== node.textContent) node.textContent = next;
    });
  }

  // Biggy is the coordinator surface.  Replies supplied by the explicit
  // Ask-Jarvis route must retain their own author label instead of inheriting
  // Biggy's global assistant name from the shared renderer.
  function labelJarvisResponses(root) {
    try {
      const messages = (typeof S !== 'undefined' && Array.isArray(S.messages)) ? S.messages : [];
      const scope = root && root.querySelectorAll ? root : document;
      scope.querySelectorAll('.assistant-segment[data-msg-idx]').forEach((segment) => {
        const idx = Number(segment.dataset.msgIdx);
        const message = Number.isFinite(idx) ? messages[idx] : null;
        const visible = String(segment.dataset.rawText || segment.textContent || '');
        const isJarvis = !!(message && (
          String(message.assistant_identity || '').toLowerCase() === 'jarvis'
          || message.ask_jarvis_hard_bind || message.jarvis_response
        ))
          || /^\s*(?:\*\*)?(?:A\.R\.G\.U\.S\.|Argus|Jarvis)\s*:/i.test(visible);
        if (!isJarvis) return;
        const turn = segment.closest('.assistant-turn');
        const role = turn && turn.querySelector('.msg-role.assistant');
        if (!role) return;
        const name = role.querySelector('.msg-role-name');
        const icon = role.querySelector('.role-icon.assistant');
        if (name) name.textContent = 'A.R.G.U.S.';
        if (icon) icon.textContent = 'J';
        if (turn) turn.dataset.responseAgent = 'jarvis';
      });
    } catch (_) {}
  }

  function installJarvisResponseLabels() {
    if (window.__biggyJarvisResponseLabelsInstalled) return;
    window.__biggyJarvisResponseLabelsInstalled = true;
    const root = document.getElementById('msgInner');
    if (!root) return;
    labelJarvisResponses(root);
    new MutationObserver(() => labelJarvisResponses(root)).observe(root, {
      childList: true,
      subtree: true,
    });
  }

  function removeCaduceus() {
    document.querySelectorAll('#emptyState .empty-logo').forEach((node) => node.remove());
  }

  function updateIdentityChip() {
    const meta = document.getElementById('biggyBrandMeta');
    const sub = document.getElementById('biggyBrandSubtitle');
    if (!meta && !sub) return;
    const model = state.model || '—';
    const provider = state.providerLabel || providerLabel(state.provider) || '—';
    const profile = state.profile || 'biggy';
    if (sub) sub.textContent = ROLE;
    if (meta) {
      meta.innerHTML =
        `<div><span>PROFILE</span> ${esc(profile)}</div>` +
        `<div><span>PROVIDER</span> ${esc(provider)}</div>` +
        `<div><span>MODEL</span> ${esc(model)}</div>`;
    }
  }

  function syncModelFromDom() {
    const sel = document.getElementById('modelSelect');
    if (!sel || !sel.value) return;
    if (!state.model || state.model === 'Unknown' || /claude|gpt-4|gpt-5|sonnet|opus/i.test(state.model)) {
      if (sel.value && !/unknown/i.test(sel.value)) state.model = sel.value;
    }
    const opt = sel.selectedOptions && sel.selectedOptions[0];
    const dataProvider = opt && (opt.getAttribute('data-provider') || opt.dataset.provider);
    if (dataProvider && (!state.provider || state.provider === 'Unknown')) {
      state.provider = dataProvider;
      state.providerLabel = providerLabel(dataProvider);
    }
  }

  async function jsonGet(path) {
    if (typeof window.api === 'function') return window.api(path);
    const response = await fetch(path, { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  async function proxyJson(path, options = {}) {
    const url = `${PTT_PROXY}${path}`;
    if (typeof window.api === 'function' && url.startsWith('/api/')) {
      return window.api(url, options);
    }
    const response = await fetch(url, { ...options, cache: 'no-store' });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${(await response.text()).slice(0, 300)}`);
    }
    return response.json();
  }

  function isValidSessionId(value) {
    return typeof value === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/.test(value);
  }

  function readPersistedGuiSessionId() {
    try {
      const stored = localStorage.getItem(SESSION_STORAGE_KEY);
      if (isValidSessionId(stored)) return stored;
    } catch (_) {}
    return '';
  }

  function persistGuiSessionId(sid) {
    if (!isValidSessionId(sid)) return;
    state.sessionId = sid;
    try {
      localStorage.setItem(SESSION_STORAGE_KEY, sid);
    } catch (_) {}
    // Never write the shared Hermes key — Biggy/Smedley must not cross-contaminate.
    document.body.dataset.sessionId = sid;
    document.documentElement.dataset.sessionId = sid;
  }

  function currentHermesSessionId() {
    try {
      const activeRow = document.querySelector('.session-item.active[data-sid]');
      const activeSid = activeRow && activeRow.dataset && activeRow.dataset.sid;
      if (isValidSessionId(activeSid)) return activeSid;
    } catch (_) {}
    try {
      if (typeof S !== 'undefined' && S && S.session && S.session.session_id) {
        const sid = String(S.session.session_id);
        if (isValidSessionId(sid)) return sid;
      }
    } catch (_) {}
    if (isValidSessionId(state.sessionId)) return state.sessionId;
    return readPersistedGuiSessionId();
  }

  function diagnosticsEnabled() {
    try {
      const params = new URLSearchParams(location.search || '');
      if (params.get('hermes_gui_debug') === '1' || params.get('debug') === '1') return true;
    } catch (_) {}
    try {
      return localStorage.getItem(DIAG_FLAG_KEY) === '1';
    } catch (_) {}
    return false;
  }

  function setDiagnosticsEnabled(on) {
    try {
      if (on) localStorage.setItem(DIAG_FLAG_KEY, '1');
      else localStorage.removeItem(DIAG_FLAG_KEY);
    } catch (_) {}
  }

  function pttIdentityPayload(extra) {
    const sid = currentHermesSessionId();
    const correlationId = `gui-${GUI_ID}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    return Object.assign({
      session_id: sid,
      gui_id: GUI_ID,
      profile_id: PROFILE_ID,
      correlation_id: correlationId,
      instance: PTT_INSTANCE,
    }, extra || {});
  }

  function acceptPttCompletion(status) {
    const eventGui = String(status.completion_gui_id || status.gui_id || status.completion_instance || '').trim().toLowerCase();
    const completionSid = String(status.completion_session_id || '').trim();
    const completionInstance = String(status.completion_instance || '').trim().toLowerCase();
    if (!eventGui || (eventGui !== GUI_ID && eventGui !== PTT_INSTANCE)) return false;
    if (completionInstance && completionInstance !== PTT_INSTANCE && completionInstance !== GUI_ID) return false;
    if (!isValidSessionId(completionSid)) return false;
    return true;
  }

  async function ensureGuiSession() {
    if (sessionEnsurePromise) return sessionEnsurePromise;
    sessionEnsurePromise = (async () => {
      let sid = currentHermesSessionId();
      if (isValidSessionId(sid)) {
        persistGuiSessionId(sid);
        return sid;
      }
      const persisted = readPersistedGuiSessionId();
      if (persisted) {
        const loadSess = (typeof window.loadSession === 'function')
          ? window.loadSession
          : (typeof loadSession === 'function' ? loadSession : null);
        if (loadSess) {
          try {
            await loadSess(persisted, {
              force: true,
              externalRefreshReason: 'gui-session-restore',
              guiId: GUI_ID,
            });
          } catch (_) {}
          sid = currentHermesSessionId();
          if (isValidSessionId(sid)) {
            persistGuiSessionId(sid);
            return sid;
          }
        }
      }
      const mint = (typeof window.newSession === 'function')
        ? window.newSession
        : (typeof newSession === 'function' ? newSession : null);
      if (mint) {
        try {
          await mint(false, { worktree: false });
        } catch (_) {}
        sid = currentHermesSessionId();
        if (isValidSessionId(sid)) {
          persistGuiSessionId(sid);
          return sid;
        }
      }
      try {
        const created = typeof window.api === 'function'
          ? await window.api('/api/session/new', {
              method: 'POST',
              body: JSON.stringify({ profile: PROFILE_ID, worktree: false }),
            })
          : await fetch('/api/session/new', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              cache: 'no-store',
              body: JSON.stringify({ profile: PROFILE_ID, worktree: false }),
            }).then(async (r) => {
              if (!r.ok) throw new Error(`HTTP ${r.status}`);
              return r.json();
            });
        const createdSid = created && (created.session_id || (created.session && created.session.session_id));
        if (isValidSessionId(createdSid)) {
          const loadSess = (typeof window.loadSession === 'function')
            ? window.loadSession
            : (typeof loadSession === 'function' ? loadSession : null);
          if (loadSess) {
            try {
              await loadSess(createdSid, {
                force: true,
                externalRefreshReason: 'gui-session-mint',
                guiId: GUI_ID,
              });
            } catch (_) {}
          }
          persistGuiSessionId(createdSid);
          return createdSid;
        }
      } catch (_) {}
      return '';
    })();
    try {
      return await sessionEnsurePromise;
    } finally {
      sessionEnsurePromise = null;
    }
  }

  function collectGuiDiagnosticsText() {
    const sid = currentHermesSessionId() || '(none)';
    const backend = location.origin;
    const channel = PTT_PROXY + '/ptt/status';
    const cssHref = (() => {
      try {
        const sheet = [...document.styleSheets].map((s) => s.href).find((h) => h && h.includes('biggy-brand.css'));
        return sheet ? sheet.split('/').pop() : 'biggy-brand.css?missing';
      } catch (_) {
        return 'biggy-brand.css?unknown';
      }
    })();
    if (isValidSessionId(sid)) persistGuiSessionId(sid);
    return (
      `guiId=${GUI_ID} build=${BUILD_ID} profile=${state.profile || PROFILE_ID} profileId=${PROFILE_ID} ` +
      `css=${cssHref} channel=${channel} backend=${backend} sessionId=${sid}`
    );
  }

  function stampGuiIdentity() {
    document.body.dataset.guiId = GUI_ID;
    document.body.dataset.profileId = PROFILE_ID;
    document.documentElement.dataset.guiId = GUI_ID;
    document.documentElement.dataset.profileId = PROFILE_ID;
    document.body.dataset.biggyBuildId = BUILD_ID;
    // Keep machine-readable diagnostics without a visible overlay.
    document.body.dataset.guiDiagnostics = collectGuiDiagnosticsText();
  }

  function ensureGuiDiagnosticsOverlay() {
    let wrap = document.getElementById('biggyGuiDiagnostics');
    if (wrap) return wrap;
    wrap = el('details', 'biggy-gui-diagnostics');
    wrap.id = 'biggyGuiDiagnostics';
    // Keep above background chrome but below composer/tool panels (z-index < typical drawers).
    wrap.style.cssText = 'position:fixed;left:8px;bottom:max(12px, env(safe-area-inset-bottom, 0px));z-index:20;max-width:min(42vw,380px);max-height:28vh;overflow:auto;pointer-events:auto;';
    const summary = el('summary', 'biggy-gui-diagnostics-summary', 'Diagnostics');
    summary.style.cssText = 'cursor:pointer;list-style:none;padding:4px 8px;border:1px solid #3a4657;border-radius:6px;background:rgba(13,17,23,.72);color:#8aa4c0;font:11px/1.2 ui-monospace,monospace;';
    const body = el('pre', 'biggy-gui-diagnostics-body');
    body.id = 'biggyGuiDiagnosticsBody';
    body.style.cssText = 'margin:4px 0 0;padding:6px 8px;border:1px solid #3a4657;border-radius:6px;background:rgba(13,17,23,.92);color:#9ecbff;font:11px/1.35 ui-monospace,monospace;white-space:pre-wrap;';
    wrap.appendChild(summary);
    wrap.appendChild(body);
    wrap.addEventListener('toggle', () => {
      setDiagnosticsEnabled(wrap.open);
      if (!wrap.open) {
        wrap.remove();
      } else {
        refreshGuiDiagnostics();
      }
    });
    document.body.appendChild(wrap);
    return wrap;
  }

  function installGuiDiagnostics() {
    stampGuiIdentity();
    // Production default: no overlay DOM at all.
    if (!diagnosticsEnabled()) {
      const stale = document.getElementById('biggyGuiDiagnostics');
      if (stale) stale.remove();
      return;
    }
    const wrap = ensureGuiDiagnosticsOverlay();
    wrap.hidden = false;
    wrap.open = true;
    refreshGuiDiagnostics();
  }

  function refreshGuiDiagnostics() {
    stampGuiIdentity();
    if (!diagnosticsEnabled()) {
      const stale = document.getElementById('biggyGuiDiagnostics');
      if (stale) stale.remove();
      return;
    }
    const wrap = ensureGuiDiagnosticsOverlay();
    const body = document.getElementById('biggyGuiDiagnosticsBody');
    if (!wrap || !body) return;
    body.textContent = collectGuiDiagnosticsText();
  }

  function installDiagnosticsHotkey() {
    if (window.__biggyDiagHotkey) return;
    window.__biggyDiagHotkey = true;
    let clicks = 0;
    let timer = null;
    document.addEventListener('click', (event) => {
      if (!event.altKey) return;
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (!target.closest('.biggy-jarvis-transplant, #biggyIdentity')) return;
      clicks += 1;
      clearTimeout(timer);
      timer = setTimeout(() => { clicks = 0; }, 900);
      if (clicks < 3) return;
      clicks = 0;
      const next = !diagnosticsEnabled();
      setDiagnosticsEnabled(next);
      installGuiDiagnostics();
    }, true);
  }

  function installPttBridge(header) {
    if (pttInstalled || !header) return;
    const ptt = header.querySelector('#biggyPtt');
    const routeBtn = header.querySelector('#biggyAudioRoute');
    const note = header.querySelector('#biggyHeaderNote');
    if (!ptt || !routeBtn) return;
    pttInstalled = true;

    const SESSION_REPOST_INTERVAL_MS = 10000;
    let postedSession = '';
    let lastSessionPostAt = 0;
    let lastCompletionTimestamp = 0;
    let completionBaselineEstablished = false;
    let progressHydrationPromise = null;
    let lastProgressHydrationAt = 0;
    let routePending = false;
    let pttPollInFlight = false;
    let speechMeterPollInFlight = false;
    let speechMeterKnownGeneration = '';

    function applyAudioRouteStatus(status) {
      const active = String(status.active_route || 'room').toLowerCase();
      const desired = String(status.desired_route || active).toLowerCase();
      const muted = !!status.output_muted;
      const switching = !!status.route_switching || routePending;
      const headsetAvailable = !!status.headset_available;
      const shownRoute = (switching ? desired : active) === 'headset' ? 'headset' : 'room';
      routeBtn.textContent = muted ? 'MUTE' : shownRoute.toUpperCase();
      routeBtn.title = muted
        ? `Audio muted; ${shownRoute} route retained. Click for Room.`
        : `Audio route: ${shownRoute}. Click for ${shownRoute === 'room' ? 'Headset' : 'Mute'}.`;
      routeBtn.classList.remove('ok', 'active', 'down', 'muted');
      if (!status.pedal_alive) {
        routeBtn.classList.add('down');
      } else if (muted) {
        routeBtn.classList.add('muted');
        if (note) note.textContent = 'Biggy and A.R.G.U.S. speech muted.';
      } else if (switching) {
        routeBtn.classList.add('active');
        if (note) note.textContent = `Switching to ${desired === 'headset' ? 'Headset' : 'Room'}…`;
      } else if (desired === 'headset' && !headsetAvailable) {
        routeBtn.classList.add('down');
        if (note) note.textContent = 'Headset is not connected to Smedley.';
      } else {
        routeBtn.classList.add('ok');
        if (note && /^(?:Switching to (?:Headset|Room)…|Biggy and A\.R\.G\.U\.S\. speech muted\.)$/.test(note.textContent || '')) {
          note.textContent = '';
        }
      }
    }

    routeBtn.addEventListener('click', async () => {
      if (routePending) return;
      let status;
      try {
        status = await proxyJson('/ptt/status');
      } catch (_) {
        if (note) note.textContent = 'PTT sidecar offline.';
        return;
      }
      const active = String(status.active_route || 'room').toLowerCase();
      const muted = !!status.output_muted;
      const target = muted ? 'room' : (active === 'headset' ? 'mute' : 'headset');
      if (target === 'headset' && !status.headset_available) {
        if (note) note.textContent = 'Headset is not connected to Smedley.';
        applyAudioRouteStatus(status);
        return;
      }
      routePending = true;
      applyAudioRouteStatus({ ...status, route_switching: true });
      try {
        await proxyJson('/ptt/audio-route', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ route: target }),
        });
      } catch (_) {
        if (note) note.textContent = 'Audio route request failed.';
      } finally {
        routePending = false;
      }
    });

    const PTT_INSTANCE = 'biggy';

    function applyPttStatus(status) {
      const pedalAlive = !!status.pedal_alive;
      const phase = String(status.phase || 'idle');
      const phaseInstance = String(status.ptt_instance || '');
      const ours = !phaseInstance || phaseInstance === PTT_INSTANCE;
      const busy = pedalAlive && ours && ['listening', 'processing', 'speaking'].includes(phase);
      ptt.classList.remove('ok', 'active', 'down');
      if (!pedalAlive) ptt.classList.add('down');
      else if (busy) ptt.classList.add('active');
      else ptt.classList.add('ok');
      // Speech may be owned by the server-side Alistar queue even when the
      // physical pedal sidecar is not reporting alive.  The orb follows the
      // authoritative speaking phase, not pedal connectivity.
      if (ours && phase === 'speaking') {
        setJarvisOrbState('speaking', 'Alistar voice active');
      } else if (ours && phase === 'processing') {
        stopArgusSpeechPulse();
        setJarvisOrbState('thinking', 'gathering information');
      } else if (argusSpeechPulseSignature) {
        stopArgusSpeechPulse();
        if (!jarvisOrbFlight) pollJarvisV6Health().catch(() => {});
      }
      applyAudioRouteStatus(status);
    }

    async function pollArgusSpeechMeter() {
      if (speechMeterPollInFlight) return;
      speechMeterPollInFlight = true;
      try {
        const suffix = speechMeterKnownGeneration
          ? `?generation=${encodeURIComponent(speechMeterKnownGeneration)}`
          : '';
        const meter = await proxyJson(`/ptt/speech-meter${suffix}`);
        if (meter && meter.active) {
          const generation = String(meter.generation || '');
          if (Array.isArray(meter.envelope) && meter.envelope.length) {
            startArgusSpeechPulse(meter);
            speechMeterKnownGeneration = generation;
          }
          setJarvisOrbState('speaking', 'Alistar voice active');
        } else {
          speechMeterKnownGeneration = '';
          if (argusSpeechPulseSignature) {
            stopArgusSpeechPulse();
            if (!jarvisOrbFlight) pollJarvisV6Health().catch(() => {});
          }
        }
      } catch (_) {
        // A transient status miss must not jerk the orb out of a real utterance.
        // The audio-duration guard in renderArgusSpeechFrame still guarantees
        // cleanup if the sidecar disappears during playback.
      } finally {
        speechMeterPollInFlight = false;
      }
    }

    async function syncActiveSession(fallbackSid) {
      const sid = currentHermesSessionId() || (isValidSessionId(fallbackSid) ? fallbackSid : '');
      if (!sid) return;
      const now = Date.now();
      const sessionChanged = sid !== postedSession;
      const heartbeatStale = (now - lastSessionPostAt) >= SESSION_REPOST_INTERVAL_MS;
      if (!sessionChanged && !heartbeatStale) return;
      try {
        await proxyJson('/ptt/active-session', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(pttIdentityPayload({ session_id: sid })),
        });
        postedSession = sid;
        lastSessionPostAt = now;
        persistGuiSessionId(sid);
      } catch (_) {}
    }

    async function hydratePttSessionMessages(sessionId, reason, { includeVisuals = false } = {}) {
      const sid = String(sessionId || '').trim();
      if (!isValidSessionId(sid)) return false;
      try {
        const url = `/api/session?session_id=${encodeURIComponent(sid)}`
          + '&messages=1&msg_limit=24&resolve_model=0';
        const response = await fetch(url, {
          credentials: 'same-origin',
          cache: 'no-store',
          headers: { 'X-Biggy-Completion-Reason': String(reason || 'ptt-completion') },
        });
        if (!response.ok) throw new Error(`completion hydration HTTP ${response.status}`);
        const payload = await response.json();
        const session = payload && payload.session;
        const messages = session && Array.isArray(session.messages) ? session.messages : null;
        if (!messages) throw new Error('completion hydration returned no messages');
        completionMessages = messages;
        completionMessagesSessionId = sid;
        persistGuiSessionId(sid);
        // Pedal turns arrive through /api/chat and never execute messages.js's
        // direct response hook.  Apply the completed turn once at this shared
        // session boundary, before transcript/card reconciliation.
        const latestAssistant = includeVisuals
          ? [...messages].reverse().find((message) => message
              && message.role === 'assistant' && !message.ask_jarvis_pending)
          : null;
        renderArgusConversationLane();
        // Text is the first visible final-state owner. Let the browser paint
        // it before the camera starts its retrieval focus transition.
        if (latestAssistant && isGalaxyTraceEligibleMessage(latestAssistant)
            && galaxyTraceCitation(latestAssistant)) {
          requestAnimationFrame(() => requestAnimationFrame(() => {
            window.__biggyHandleDocumentResult(latestAssistant);
          }));
        }
        if (includeVisuals && typeof window.__biggyHandoffTravelVisualsFromMessages === 'function') {
          await window.__biggyHandoffTravelVisualsFromMessages(messages);
        }
        return true;
      } catch (error) {
        try { console.warn('[biggy] PTT session hydration will retry', error); } catch (_) {}
        return false;
      }
    }

    async function refreshPttProgress(status) {
      const phase = String(status.phase || '').toLowerCase();
      if (phase !== 'processing' && phase !== 'speaking') return false;
      const sid = String(
        status.linked_session_id || status.session_id || currentHermesSessionId() || ''
      ).trim();
      if (!isValidSessionId(sid)) return false;
      const now = Date.now();
      if (progressHydrationPromise || (now - lastProgressHydrationAt) < 1200) return false;
      lastProgressHydrationAt = now;
      progressHydrationPromise = hydratePttSessionMessages(
        sid,
        `ptt-${phase}-progress`,
        { includeVisuals: false },
      );
      try {
        return await progressHydrationPromise;
      } finally {
        progressHydrationPromise = null;
      }
    }

    async function refreshCompletedPttTurn(status, reason) {
      const completionSid = String(status.completion_session_id || '');
      if (!acceptPttCompletion(status)) return false;
      try {
        const hydrated = await hydratePttSessionMessages(
          completionSid,
          reason,
          { includeVisuals: true },
        );
        if (!hydrated) return false;
        postedSession = '';
        await syncActiveSession(completionSid);
        return true;
      } catch (error) {
        try { console.warn('[biggy] PTT completion refresh will retry', error); } catch (_) {}
        return false;
      }
    }

    async function pollPttStatus() {
      // A status tick can trigger session hydration while a turn is active.
      // Never queue a second complete poll behind a slow tablet/network hop:
      // stale concurrent polls were able to multiply work for the one active
      // turn and starve the renderer after the first ask.
      if (pttPollInFlight) return;
      pttPollInFlight = true;
      try {
        const status = await proxyJson('/ptt/status');
        applyPttStatus(status);
        await syncActiveSession(status.linked_session_id || status.session_id || status.completion_session_id);
        await refreshPttProgress(status);
        const completionTs = Number(status.completion_timestamp || 0);
        if (!completionBaselineEstablished) {
          completionBaselineEstablished = true;
          const recentCompletion = completionTs > 0 && ((Date.now() / 1000) - completionTs) <= 90;
          if (recentCompletion && acceptPttCompletion(status)) {
            const refreshed = await refreshCompletedPttTurn(status, 'ptt-baseline-refresh');
            if (!refreshed) return;
          }
          lastCompletionTimestamp = completionTs;
          return;
        }
        if (completionTs > lastCompletionTimestamp) {
          if (!acceptPttCompletion(status)) return;
          const refreshed = await refreshCompletedPttTurn(status, 'ptt-completion');
          // Do not consume the event until the visible session and cards have
          // hydrated. A transient load failure must retry on the next poll.
          if (refreshed) lastCompletionTimestamp = completionTs;
        }
      } catch (_) {
        ptt.classList.remove('ok', 'active');
        ptt.classList.add('down');
        routeBtn.classList.remove('ok', 'active');
        routeBtn.classList.add('down');
      } finally {
        pttPollInFlight = false;
      }
    }

    pollPttStatus();
    pollArgusSpeechMeter();
    setInterval(() => { pollPttStatus().catch(() => {}); }, 1500);
    // The speech meter is tiny and local. An 80 ms cadence removes the
    // quarter-second visual discovery lag without coupling it to galaxy work.
    setInterval(() => { pollArgusSpeechMeter().catch(() => {}); }, 80);
  }

  async function refreshIdentity() {
    try {
      const profiles = await jsonGet('/api/profiles');
      if (profiles && profiles.active) state.profile = String(profiles.active).trim() || 'biggy';
      const active = Array.isArray(profiles && profiles.profiles)
        ? profiles.profiles.find((p) => p && p.is_active) || profiles.profiles[0]
        : null;
      if (active) {
        if (active.model) state.model = String(active.model);
        if (active.provider) {
          state.provider = String(active.provider);
          state.providerLabel = providerLabel(active.provider);
        }
      }
      if (profiles && profiles.single_profile_mode) state.ready = true;
    } catch (_) {}

    try {
      const onboard = await jsonGet('/api/onboarding/status');
      const system = onboard && onboard.system ? onboard.system : {};
      if (system.current_model) state.model = String(system.current_model);
      if (system.current_provider) {
        state.provider = String(system.current_provider);
        state.providerLabel = providerLabel(system.current_provider);
      }
      state.ready = true;
    } catch (_) {}

    try {
      const settings = await jsonGet('/api/settings');
      if (settings && settings.default_model_provider && !state.provider) {
        state.provider = String(settings.default_model_provider);
        state.providerLabel = providerLabel(settings.default_model_provider);
      }
      window._botName = BRAND;
    } catch (_) {
      window._botName = BRAND;
    }

    try {
      if (state.model) window._defaultModel = state.model;
      if (state.provider) window._activeProvider = state.provider;
      if (typeof S !== 'undefined' && S && state.profile === 'biggy') {
        S.activeProfile = 'biggy';
        S.activeProfileIsDefault = false;
      }
    } catch (_) {}

    syncModelFromDom();
    updateIdentityChip();
    forceChromeLabels();
    installJarvisResponseLabels();
    installComposerBranding();
    installBiggyVoiceLabels();
    installGuiDiagnostics();
    removeCaduceus();
  }

  // Biggy is the coordinator GUI — Owner-ACK dispose UI is disabled here.
  // Dispose stays on Smedley (or a dedicated Owner surface) when needed.
  const FEATURES = Object.freeze({
    approvalsEnabled: false,
    diagnosticsEnabledDefault: false,
    guiId: GUI_ID,
    profileId: PROFILE_ID,
    // Later Ask Jarvis voice path routes here. This slice does not replace Austin.
    askJarvisV6Voice: Object.freeze({
      enabled: false,
      route: 'austin',
      note: 'Voice seam only — Austin remains the Biggy default.',
    }),
  });
  try {
    Object.defineProperty(window, '__BIGGY_FEATURES__', {
      value: FEATURES,
      writable: false,
      configurable: false,
    });
  } catch (_) {
    window.__BIGGY_FEATURES__ = FEATURES;
  }

  function purgeOwnerAckArtifacts() {
    // Fail closed: strip any leftover dispose panel from a prior Biggy build.
    document.querySelectorAll(
      '#biggyOwnerAckPanel, .biggy-owner-ack-panel, [data-testid="biggy-owner-ack"], [data-approval-widget]'
    ).forEach((node) => node.remove());
  }

  let jarvisOrbFlight = false;
  let jarvisHealthTimer = null;
  let jarvisOrbState = 'offline';

  // Mirrors V6's own STATE_STYLE table (3d.html) — label, css color, pulse —
  // extended with offline/tool-running/error, which the standalone V6 orb
  // never needs to represent (it's only ever reachable when V6 is up).
  const REACTOR_STATE_STYLE = Object.freeze({
    offline: ['OFFLINE', '#ff6b6b', 0],
    online: ['ONLINE', '#34d399', 0],
    thinking: ['THINKING', '#ffd06a', 1],
    speaking: ['SPEAKING', '#7dffd9', 1],
    'tool-running': ['TOOL RUNNING', '#caa6ff', 1],
    error: ['ERROR', '#ff6b6b', 1],
  });
  // Maps bridge states onto V6's own is-listen/is-think/is-speak orb
  // classes (colour-only, no pulsing — same rule V6 itself follows) plus
  // two additions (is-offline/is-error) for states V6's own orb never has
  // to render.
  const REACTOR_ORB_CLASS = Object.freeze({
    offline: 'is-offline',
    online: '',
    thinking: 'is-think',
    speaking: 'is-speak',
    'tool-running': 'is-think',
    error: 'is-error',
  });

  function setJarvisOrbState(state, detail) {
    const next = ORB_STATES.includes(state) ? state : 'error';
    jarvisOrbState = next;
    const frame = document.getElementById('biggyV6World');
    if (frame && frame.contentWindow) {
      try {
        frame.contentWindow.postMessage(
          { type: 'biggy-argus-state', state: next },
          window.location.origin,
        );
      } catch (_) {}
    }
    const orb = document.getElementById('j-orb');
    if (!orb) return;
    orb.className = REACTOR_ORB_CLASS[next] || '';
    const label = detail ? `${next}: ${detail}` : next;
    orb.setAttribute('title', `A.R.G.U.S. ${label}`);
    orb.setAttribute('aria-label', `A.R.G.U.S. ${label}`);
    const st = document.getElementById('j-state');
    const stTxt = document.getElementById('j-state-txt');
    if (st && stTxt) {
      const [text, color, pulse] = REACTOR_STATE_STYLE[next];
      stTxt.textContent = text;
      st.style.color = color;
      st.classList.toggle('pulse', !!pulse);
    }
  }

  let argusSpeechPulseFrame = null;
  let argusSpeechPulseSignature = '';
  let argusSpeechPulseEnvelope = [];
  let argusSpeechPulseStartedAt = 0;
  let argusSpeechPulseSampleMs = 40;
  let argusSpeechPulseGain = 1;
  let argusSpeechPulseLeadMs = 80;

  function loadArgusSpeechSyncSettings() {
    try {
      const saved = JSON.parse(localStorage.getItem(ARGUS_SYNC_STORAGE_KEY) || '{}');
      const gain = Number(saved.gain);
      const leadMs = Number(saved.lead_ms);
      if (Number.isFinite(gain)) argusSpeechPulseGain = Math.max(.5, Math.min(2, gain));
      if (Number.isFinite(leadMs)) argusSpeechPulseLeadMs = Math.max(-250, Math.min(300, leadMs));
    } catch (_) {}
  }

  function saveArgusSpeechSyncSettings() {
    try {
      localStorage.setItem(ARGUS_SYNC_STORAGE_KEY, JSON.stringify({
        gain: argusSpeechPulseGain,
        lead_ms: argusSpeechPulseLeadMs,
      }));
    } catch (_) {}
  }

  function stopArgusSpeechPulse() {
    if (argusSpeechPulseFrame) cancelAnimationFrame(argusSpeechPulseFrame);
    argusSpeechPulseFrame = null;
    argusSpeechPulseSignature = '';
    argusSpeechPulseEnvelope = [];
    argusSpeechPulseStartedAt = 0;
    argusSpeechPulseSampleMs = 40;
    const orb = document.getElementById('j-orb');
    if (orb) {
      orb.style.setProperty('--beat', '0');
      orb.style.setProperty('--orb-scale', '1');
    }
  }

  function renderArgusSpeechFrame() {
    const orb = document.getElementById('j-orb');
    if (!orb || !argusSpeechPulseSignature) return;
    const elapsed = Date.now() - argusSpeechPulseStartedAt + argusSpeechPulseLeadMs;
    const index = Math.floor(Math.max(0, elapsed) / argusSpeechPulseSampleMs);
    if (index >= argusSpeechPulseEnvelope.length) {
      stopArgusSpeechPulse();
      if (!jarvisOrbFlight) pollJarvisV6Health().catch(() => {});
      return;
    }
    const measured = Number(argusSpeechPulseEnvelope[index] || 0);
    const rawLevel = Math.max(0, Number.isFinite(measured) ? measured : 0);
    const level = Math.max(0, Math.min(1, rawLevel * argusSpeechPulseGain));
    // The real RMS envelope controls a restrained core glow and 0–2.8% scale.
    // This reads as speech energy without turning the reactor into a bounce.
    orb.style.setProperty('--beat', String(level * .82));
    orb.style.setProperty('--orb-scale', String(1 + (level * .028)));
    argusSpeechPulseFrame = requestAnimationFrame(renderArgusSpeechFrame);
  }

  function startArgusSpeechPulse(meter) {
    const generation = String((meter && meter.generation) || '').trim();
    const envelope = Array.isArray(meter && meter.envelope) ? meter.envelope : [];
    if (!generation || !envelope.length) return;
    if (argusSpeechPulseFrame && generation === argusSpeechPulseSignature) return;
    stopArgusSpeechPulse();
    argusSpeechPulseSignature = generation;
    argusSpeechPulseEnvelope = envelope.map((value) => Number(value) || 0);
    argusSpeechPulseStartedAt = Number(meter.started_at || 0) * 1000;
    argusSpeechPulseSampleMs = Math.max(20, Math.min(200, Number(meter.sample_ms || 40)));
    argusSpeechPulseFrame = requestAnimationFrame(renderArgusSpeechFrame);
  }

  function installArgusSpeechSyncTuner(dock) {
    if (!dock) return;
    loadArgusSpeechSyncSettings();
    const toggle = dock.querySelector('#argusSpeechSyncToggle');
    const panel = dock.querySelector('#argusSpeechSyncPanel');
    const gain = dock.querySelector('#argusSpeechSyncGain');
    const lead = dock.querySelector('#argusSpeechSyncLead');
    const gainOut = dock.querySelector('#argusSpeechSyncGainOut');
    const leadOut = dock.querySelector('#argusSpeechSyncLeadOut');
    if (!toggle || !panel || !gain || !lead || !gainOut || !leadOut) return;
    if (toggle.dataset.bound === '1') return;
    toggle.dataset.bound = '1';

    const render = () => {
      gain.value = String(argusSpeechPulseGain);
      lead.value = String(argusSpeechPulseLeadMs);
      gainOut.textContent = `${Math.round(argusSpeechPulseGain * 100)}%`;
      leadOut.textContent = `${argusSpeechPulseLeadMs >= 0 ? '+' : ''}${Math.round(argusSpeechPulseLeadMs)} ms`;
    };
    render();
    toggle.addEventListener('click', () => {
      const open = panel.hidden;
      panel.hidden = !open;
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    gain.addEventListener('input', () => {
      argusSpeechPulseGain = Math.max(.5, Math.min(2, Number(gain.value) || 1));
      saveArgusSpeechSyncSettings();
      render();
    });
    lead.addEventListener('input', () => {
      argusSpeechPulseLeadMs = Math.max(-250, Math.min(300, Number(lead.value) || 0));
      saveArgusSpeechSyncSettings();
      render();
    });
  }

  function formatReactorModel(model) {
    const raw = String(model || '').trim();
    if (!raw) return '';
    return raw.split('/').pop() || raw;
  }

  function setReactorModelChip(model) {
    const chip = document.getElementById('j-brain-chip');
    if (!chip) return;
    const short = formatReactorModel(model);
    chip.textContent = short ? `\u25c6 ${short}` : '\u2014';
    chip.title = model ? String(model) : '';
  }

  function buildReactorHud() {
    const NS = 'http://www.w3.org/2000/svg';
    const C = 100;
    const ticks = document.getElementById('hud-ticks');
    const dots = document.getElementById('hud-dots');
    const spokes = document.getElementById('hud-spokes');
    if (!ticks || ticks.childNodes.length) return;
    const line = (g, a, r1, r2) => {
      const rad = (a * Math.PI) / 180;
      const l = document.createElementNS(NS, 'line');
      l.setAttribute('x1', (C + r1 * Math.cos(rad)).toFixed(2));
      l.setAttribute('y1', (C + r1 * Math.sin(rad)).toFixed(2));
      l.setAttribute('x2', (C + r2 * Math.cos(rad)).toFixed(2));
      l.setAttribute('y2', (C + r2 * Math.sin(rad)).toFixed(2));
      g.appendChild(l);
    };
    for (let i = 0; i < 72; i += 1) line(ticks, i * 5, i % 6 === 0 ? 84 : 89, 96);
    for (let i = 0; i < 12; i += 1) line(spokes, i * 30, 13, 22);
    for (let i = 0; i < 5; i += 1) {
      const rad = ((-66 + i * 20) * Math.PI) / 180;
      const d = document.createElementNS(NS, 'circle');
      d.setAttribute('cx', (C + 74 * Math.cos(rad)).toFixed(2));
      d.setAttribute('cy', (C + 74 * Math.sin(rad)).toFixed(2));
      d.setAttribute('r', '1.7');
      d.setAttribute('class', 'dot');
      dots.appendChild(d);
    }
  }

  function collectBiggyContext() {
    const ctx = {
      project_id: '',
      display_name: '',
      workspace_name: '',
      synopsis: '',
    };
    try {
      const pid = (typeof _activeProject !== 'undefined') ? _activeProject : '';
      const none = (typeof NO_PROJECT_FILTER !== 'undefined') ? NO_PROJECT_FILTER : '__none__';
      if (pid && pid !== none) {
        ctx.project_id = String(pid);
        const projects = (typeof _allProjects !== 'undefined' && Array.isArray(_allProjects))
          ? _allProjects : [];
        const hit = projects.find((p) => p && p.project_id === pid);
        if (hit && hit.name) ctx.display_name = String(hit.name);
      }
    } catch (_) {}
    try {
      const wsNode = document.getElementById('workspaceName')
        || document.getElementById('titlebarWorkspace')
        || document.querySelector('.workspace-name, .ws-name');
      if (wsNode && wsNode.textContent) ctx.workspace_name = String(wsNode.textContent).trim();
      if (!ctx.workspace_name && typeof S !== 'undefined' && S && S.session) {
        ctx.workspace_name = String(S.session.cwd || S.session.workspace || '').trim();
      }
      if (!ctx.workspace_name) ctx.workspace_name = 'biggy';
    } catch (_) {}
    try {
      const syn = document.querySelector('[data-testid="project-synopsis"], .project-synopsis, #projectSynopsis');
      if (syn && syn.textContent) ctx.synopsis = String(syn.textContent).trim().slice(0, 500);
    } catch (_) {}
    return ctx;
  }

  async function jsonPost(path, body) {
    const options = {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    };
    if (typeof window.api === 'function') return window.api(path, options);
    const response = await fetch(path, { ...options, cache: 'no-store' });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${(await response.text()).slice(0, 300)}`);
    }
    return response.json();
  }

  function appendJarvisV6Turn(question, answer, ok, errorText) {
    const userLine = String(question || '').trim();
    const reply = ok
      ? String(answer || '').trim()
      : (`**A.R.G.U.S. unavailable:** ${String(errorText || 'request failed')}`);
    try {
      if (typeof S !== 'undefined' && S && Array.isArray(S.messages)) {
        S.messages.push({ role: 'user', content: userLine, jarvis_v6: true });
        S.messages.push({
          role: 'assistant',
          content: reply,
          assistant_identity: 'jarvis',
          jarvis_response: true,
          jarvis_v6: true,
        });
        if (typeof renderMessages === 'function') renderMessages();
        labelJarvisResponses(document);
        return;
      }
    } catch (_) {}
    const note = document.getElementById('biggyHeaderNote');
    if (note) note.textContent = reply.slice(0, 180);
  }

  async function pollJarvisV6Health() {
    if (jarvisOrbFlight || argusSpeechPulseSignature) return;
    try {
      const data = await jsonGet(V6_HEALTH_PATH);
      const state = String((data && data.state) || (data && data.online ? 'online' : 'offline'));
      const detail = data && (data.model || data.error) ? String(data.model || data.error) : '';
      setJarvisOrbState(ORB_STATES.includes(state) ? state : 'error', detail);
      setReactorModelChip(data && data.model);
    } catch (err) {
      setJarvisOrbState('error', String(err && err.message || err));
      setReactorModelChip('');
    }
  }

  async function askJarvisV6(raw) {
    const question = String(raw || '').trim();
    const note = document.getElementById('biggyHeaderNote');
    if (!question) {
      if (note) note.textContent = 'Type a question, then Ask Argus.';
      return;
    }
    jarvisOrbFlight = true;
    setJarvisOrbState('thinking', 'request in flight');
    if (note) note.textContent = 'A.R.G.U.S. thinking…';
    try {
      const data = await jsonPost(V6_CHAT_PATH, {
        message: question,
        session: `biggy-v6-${currentHermesSessionId() || 'local'}`,
        context: collectBiggyContext(),
      });
      if (data && data.ok) {
        setJarvisOrbState('online', 'reply received');
        appendJarvisV6Turn(question, data.answer, true);
        if (note) note.textContent = '';
      } else {
        const state = String((data && data.state) || 'error');
        setJarvisOrbState(state === 'offline' ? 'offline' : 'error', data && data.error);
        appendJarvisV6Turn(question, '', false, (data && data.error) || 'A.R.G.U.S. request failed');
        if (note) note.textContent = String((data && data.error) || 'A.R.G.U.S. error');
      }
    } catch (err) {
      setJarvisOrbState('error', String(err && err.message || err));
      appendJarvisV6Turn(question, '', false, err && err.message || err);
      if (note) note.textContent = String(err && err.message || err);
    } finally {
      jarvisOrbFlight = false;
    }
  }

  function installJarvisV6Bridge(header) {
    if (!header || header.dataset.jarvisV6Bound === '1') return;
    header.dataset.jarvisV6Bound = '1';
    const prompt = header.querySelector('#biggyAskJarvisPrompt');
    const btn = header.querySelector('#biggyAskJarvis');
    const submit = () => {
      const typed = prompt && prompt.value ? String(prompt.value) : '';
      const composer = document.getElementById('msg');
      const fallback = composer && !composer.isContentEditable
        ? String(composer.value || '')
        : String((composer && composer.textContent) || '');
      const question = typed.trim() || fallback.trim();
      if (prompt) prompt.value = '';
      askJarvisV6(question);
    };
    if (btn) {
      btn.addEventListener('click', (ev) => {
        ev.preventDefault();
        submit();
      });
    }
    if (prompt) {
      prompt.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' && !ev.shiftKey) {
          ev.preventDefault();
          ev.stopPropagation();
          submit();
        }
      });
    }
    pollJarvisV6Health();
    if (jarvisHealthTimer) clearInterval(jarvisHealthTimer);
    jarvisHealthTimer = setInterval(() => { pollJarvisV6Health().catch(() => {}); }, 5000);
  }

  // Jarvis V6 3D graph/galaxy — replaces the static Iwo background image.
  // Loaded from Biggy's own same-origin, fixed, read-only proxy route
  // (never a direct browser request to the standalone V6 service port);
  // see api/jarvis_v6_world.py. Falls back to a clean placeholder if WebGL
  // is unsupported or the embedded scene fails to initialize (e.g. no
  // network access to the Three.js CDN the V6 viewer's importmap points at).
  function hasWebGLSupport() {
    try {
      const canvas = document.createElement('canvas');
      return !!(window.WebGLRenderingContext
        && (canvas.getContext('webgl') || canvas.getContext('experimental-webgl')));
    } catch (_) {
      return false;
    }
  }

  function showV6WorldFallback(fallback, reasonText) {
    if (!fallback) return;
    const reason = fallback.querySelector('#biggyV6WorldFallbackReason');
    if (reason) reason.textContent = reasonText;
    fallback.classList.add('is-active');
  }

  function postRagTrace(trace) {
    const frame = document.getElementById('biggyV6World');
    if (!ragWorldReady) {
      pendingRagTrace = trace;
      return;
    }
    try {
      if (frame && frame.contentWindow) {
        frame.contentWindow.postMessage({ type: 'biggy-rag-trace', trace }, window.location.origin);
      }
    } catch (_) {}
  }

  function clearRagTrace() {
    pendingRagTrace = null;
    const frame = document.getElementById('biggyV6World');
    // The receipt is display state, not durable session state.  Remove it
    // immediately so Home cannot leave stale evidence attached to the frame
    // while the iframe processes the clear request.
    if (frame) frame.removeAttribute('data-rag-trace');
    if (!ragWorldReady || !frame || !frame.contentWindow) return;
    try {
      frame.contentWindow.postMessage({ type: 'biggy-rag-trace-clear' }, window.location.origin);
    } catch (_) {}
  }

  function traceFromRagPayload(payload) {
    if (!payload || typeof payload !== 'object') return;
    const receipt = payload.retrieval_receipt && typeof payload.retrieval_receipt === 'object'
      ? payload.retrieval_receipt : null;
    const active = payload.active_document && typeof payload.active_document === 'object'
      ? payload.active_document : null;
    const source = String((receipt && receipt.source) || (active && active.source) || '').trim();
    const pdfPage = Number((receipt && (receipt.pdf_page || receipt.page_hint))
      || (active && active.page_hint) || 0);
    const printedPage = Number((receipt && receipt.printed_page) || 0);
    // A green route is earned only by a concrete retrieval receipt.  A red
    // segment needs a concrete file path as well; we never invent one for a
    // no-match answer because that would falsely accuse a document branch.
    if (receipt && source) {
      postRagTrace({
        state: payload.error ? 'failed' : 'complete',
        source,
        pdfPage: Number.isFinite(pdfPage) && pdfPage > 0 ? pdfPage : null,
        printedPage: Number.isFinite(printedPage) && printedPage > 0 ? printedPage : null,
      });
    } else if (payload.document_route && payload.error && source) {
      postRagTrace({
        state: 'failed', source,
        pdfPage: Number.isFinite(pdfPage) && pdfPage > 0 ? pdfPage : null,
        printedPage: Number.isFinite(printedPage) && printedPage > 0 ? printedPage : null,
      });
    }
  }

  function isGalaxyTraceEligibleMessage(message) {
    if (!message || message.role !== 'assistant' || message.ask_jarvis_pending) return false;
    const identity = String(message.assistant_identity || '').toLowerCase();
    const isArgus = identity === 'argus' || identity === 'jarvis'
      || message.ask_jarvis_hard_bind || message.jarvis_response || message.jarvis_v6;
    if (!isArgus) return false;
    // Travel and other action cards can legitimately carry agent evidence for
    // their own response.  They are not corpus-navigation results, so they
    // must never refocus or recolor the RAG galaxy.
    return ![
      message.map_view_model,
      message.recommendation_view_model,
      message.trip_plan_view_model,
      message.lodging_view_model,
      message.visual_action_view_model,
    ].some((model) => model && typeof model === 'object');
  }

  function galaxyTraceCitation(message) {
    const evidence = message && message.rag_evidence && typeof message.rag_evidence === 'object'
      ? message.rag_evidence : null;
    const citations = evidence && Array.isArray(evidence.citations) ? evidence.citations : [];
    const citation = citations.find((item) => item && typeof item === 'object' && item.source);
    if (citation) return citation;
    // Deterministic document routing stores its concrete retrieval receipt
    // separately from general PA evidence.  It is equally traceable and, most
    // importantly, belongs to this exact session correlation.
    const receipt = message && message.retrieval_receipt;
    if (receipt && typeof receipt === 'object' && receipt.source) return receipt;
    const active = message && message.active_document;
    return active && typeof active === 'object' && active.source ? active : null;
  }

  function installRagTraceObserver() {
    if (ragTraceObserverInstalled || typeof window.fetch !== 'function') return;
    ragTraceObserverInstalled = true;
    const nativeFetch = window.fetch.bind(window);
    // Biggy's native `/api/chat/start` endpoint owns its streaming/session
    // lifecycle.  Do not clone, parse, or otherwise observe it here: doing so
    // puts visual tracing on the synchronous path of the primary composer.
    // The V6 bridge response is a small JSON contract, which is the only
    // response this observer is allowed to inspect.
    const isTraceableRequest = (request) => request.includes(V6_CHAT_PATH);
    window.fetch = async (...args) => {
      const request = String(args[0] && (args[0].url || args[0]) || '');
      const traceable = isTraceableRequest(request);
      if (traceable) clearRagTrace();
      const response = await nativeFetch(...args);
      try {
        if (traceable) {
          response.clone().json().then(traceFromRagPayload).catch(() => {});
        }
      } catch (_) {}
      return response;
    };
    if (!ragTraceStatusListenerInstalled) {
      ragTraceStatusListenerInstalled = true;
      window.addEventListener('message', (event) => {
        if (event.origin !== window.location.origin) return;
        const data = event.data || {};
        const frame = document.getElementById('biggyV6World');
        if (data.type === 'biggy-rag-world-ready') {
          ragWorldReady = true;
          if (pendingRagTrace && frame && frame.contentWindow) {
            const trace = pendingRagTrace;
            pendingRagTrace = null;
            frame.contentWindow.postMessage(
              { type: 'biggy-rag-trace', trace },
              window.location.origin,
            );
          }
          return;
        }
        if (data.type === 'biggy-rag-trace-applied' && frame) {
          frame.dataset.ragTrace = JSON.stringify(data.trace || {});
        }
        if (data.type === 'biggy-rag-trace-cleared' && frame) {
          frame.removeAttribute('data-rag-trace');
        }
        if (data.type === 'biggy-galaxy-filter-focused') {
          markGalaxyFilterSelection(String(data.path || ''), Number(data.nodes || 0));
        }
        if (data.type === 'biggy-galaxy-filter-restored') {
          markGalaxyFilterSelection('', 0);
        }
      });
    }
  }

  function ensureArgusRagOverview(mainChat) {
    const host = mainChat || document.getElementById('mainChat');
    if (!host) return null;
    let hud = host.querySelector('#biggyArgusRagOverview');
    if (hud) return hud;
    hud = el('section', 'biggy-argus-rag-overview');
    hud.id = 'biggyArgusRagOverview';
    hud.dataset.biggyLayer = 'workspace';
    hud.setAttribute('data-testid', 'biggy-argus-rag-overview');
    hud.setAttribute('aria-label', 'ARGUS RAG overview');
    hud.innerHTML = '<div class="biggy-argus-rag-title">A.R.G.U.S.</div>'
      + '<div class="biggy-argus-rag-subtitle">AUGMENTED RETRIEVAL &amp; GROUNDED UNDERSTANDING SYSTEM</div>'
      + '<div class="biggy-argus-rag-section">SYSTEM STATUS</div>'
      + '<div class="biggy-argus-rag-state is-offline">● AWAITING INGEST STATUS</div>';
    host.appendChild(hud);
    return hud;
  }

  function ensureArgusConversationLane(mainChat) {
    const host = mainChat || document.getElementById('mainChat');
    if (!host) return null;
    let lane = host.querySelector('#biggyArgusConversationLane');
    if (lane) return lane;
    lane = el('section', 'biggy-argus-conversation-lane');
    lane.id = 'biggyArgusConversationLane';
    lane.dataset.biggyLayer = 'conversation';
    lane.setAttribute('data-testid', 'biggy-argus-conversation-lane');
    lane.setAttribute('aria-label', 'Biggy and ARGUS conversation');
    lane.hidden = true;
    lane.innerHTML = '<div class="biggy-argus-conversation-heading">CONVERSATION // LIVE</div>'
      + '<div class="biggy-argus-conversation-turns" aria-live="polite"></div>';
    host.appendChild(lane);
    syncArgusConversationLaneBoundary(lane, host);
    return lane;
  }

  function syncArgusConversationLaneBoundary(lane, host) {
    lane = lane || document.getElementById('biggyArgusConversationLane');
    host = host || document.getElementById('mainChat');
    const composer = document.getElementById('composerWrap');
    if (!lane || !host || !composer) return;
    const hostRect = host.getBoundingClientRect();
    const composerRect = composer.getBoundingClientRect();
    const overlapBoundary = Math.max(132, Math.round(hostRect.bottom - composerRect.top + 18));
    lane.style.setProperty('--biggy-conversation-bottom', overlapBoundary + 'px');
  }

  function argusConversationText(message) {
    let value = message && message.content;
    if (Array.isArray(value)) {
      value = value.map((part) => {
        if (typeof part === 'string') return part;
        return part && typeof part === 'object' ? (part.text || part.content || '') : '';
      }).join('\n');
    } else if (value && typeof value === 'object') {
      value = value.text || value.content || '';
    }
    return String(value || '')
      .replace(/```[\s\S]*?```/g, '[technical detail available in transcript]')
      .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1')
      .replace(/^#{1,6}\s+/gm, '')
      .replace(/[*_~`]+/g, '')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
  }

  function argusConversationIdentity(message) {
    if (!message || message.role === 'user') return { key: 'operator', label: 'PROMPT' };
    const identity = String(message.assistant_identity || '').toLowerCase();
    const isArgus = identity === 'argus' || identity === 'jarvis'
      || message.ask_jarvis_hard_bind || message.jarvis_response || message.jarvis_v6;
    return isArgus ? { key: 'argus', label: 'A.R.G.U.S.' } : { key: 'biggy', label: 'BIGGY' };
  }

  function renderArgusConversationLane() {
    const lane = ensureArgusConversationLane();
    if (!lane) return;
    const activeSid = currentHermesSessionId();
    const source = (
      completionMessagesSessionId
      && (completionMessagesSessionId === activeSid || completionMessagesSessionId === state.sessionId)
      && Array.isArray(completionMessages)
    )
      ? completionMessages
      : ((typeof S !== 'undefined' && S && Array.isArray(S.messages)) ? S.messages : []);
    const visible = source.filter((message) => message
      && (message.role === 'user' || message.role === 'assistant')
      && !message.tool_only && !message._hidden);
    // Rendering the conversation is presentation-only. Visual ownership is
    // applied at the direct-response or PTT-session completion boundary, not
    // repeatedly from this timer-driven transcript decorator.
    const turns = visible.slice(-8).flatMap((message, index) => {
      const identity = argusConversationIdentity(message);
      const pending = !!(message.ask_jarvis_pending || message._live);
      const raw = argusConversationText(message);
      const text = pending && !raw ? 'Tracing the retrieval path…' : raw;
      const result = [];
      const ackText = String(message && message._ack_spoken_text || '').trim();
      if (message.role === 'assistant' && message.ask_jarvis_hard_bind && ackText) {
        result.push({ identity: { key: 'biggy', label: 'BIGGY' }, pending: false, text: ackText.slice(0, 1400), index: `${index}-ack` });
      }
      result.push({ identity, pending, text: text.slice(0, 1400), index });
      return result;
    }).filter((turn) => turn.text);
    const signature = JSON.stringify(turns.map((turn) => [turn.identity.key, turn.pending, turn.text]));
    if (lane.dataset.signature === signature) return;
    lane.dataset.signature = signature;
    // Measuring the composer forces a complete layout pass. Do it only when
    // the visible transcript actually changed, never on the background
    // heartbeat while the 3D canvas is rendering.
    syncArgusConversationLaneBoundary(lane);
    lane.hidden = turns.length === 0;
    const body = lane.querySelector('.biggy-argus-conversation-turns');
    if (!body) return;
    body.innerHTML = turns.map((turn) => `<article class="biggy-argus-dialog is-${turn.identity.key}${turn.pending ? ' is-pending' : ''}">`
      + `<div class="biggy-argus-dialog-role">${esc(turn.identity.label)}${turn.pending ? ' // WORKING' : ''}</div>`
      + `<div class="biggy-argus-dialog-copy">${esc(turn.text).replace(/\n/g, '<br>')}</div>`
      + '</article>').join('');
    body.scrollTop = body.scrollHeight;
  }

  window.__biggyRenderArgusConversationLaneNow = renderArgusConversationLane;

  function installArgusConversationLane(mainChat) {
    const lane = ensureArgusConversationLane(mainChat);
    syncArgusConversationLaneBoundary(lane, mainChat);
    renderArgusConversationLane();
    if (conversationLaneTimer) clearInterval(conversationLaneTimer);
    // Hermes owns the live transcript. This is merely a low-frequency safety
    // reconciliation for alternate clients/PTT, deliberately not a 500 ms
    // render loop competing with the galaxy on a tablet.
    conversationLaneTimer = setInterval(() => {
      if (conversationLaneRenderQueued) return;
      conversationLaneRenderQueued = true;
      requestAnimationFrame(() => {
        conversationLaneRenderQueued = false;
        renderArgusConversationLane();
      });
    }, 2500);
  }

  function ensureArgusIngestDialog(mainChat) {
    const host = mainChat || document.getElementById('mainChat');
    if (!host) return null;
    let dialog = host.querySelector('#biggyArgusIngestDialog');
    if (dialog) return dialog;
    dialog = el('section', 'biggy-argus-ingest-dialog');
    dialog.id = 'biggyArgusIngestDialog';
    dialog.dataset.biggyLayer = 'workspace';
    dialog.hidden = true;
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'false');
    dialog.setAttribute('aria-label', 'ARGUS ingestion exception');
    host.appendChild(dialog);
    return dialog;
  }

  function closeArgusIngestDialog() {
    const dialog = document.getElementById('biggyArgusIngestDialog');
    if (dialog) dialog.hidden = true;
  }

  function openArgusIngestDialog(row) {
    const dialog = ensureArgusIngestDialog();
    if (!dialog || !row) return;
    const source = String(row.source || '');
    const file = String(row.file || source || 'unknown file');
    const phase = String(row.phase || row.state || 'ingestion issue');
    const reason = String(row.reason || phase);
    dialog.dataset.source = source;
    dialog.hidden = false;
    dialog.innerHTML = '<div class="biggy-argus-ingest-dialog-kicker">ARGUS // INGEST ACTION</div>'
      + `<strong>${esc(file)}</strong><small>${esc(source)}</small>`
      + `<p>${esc(reason)}</p><div class="biggy-argus-ingest-dialog-actions">`
      + '<button type="button" data-argus-ingest-disposition="keep">KEEP ON RADAR</button>'
      + '<button type="button" data-argus-ingest-disposition="resolve">RESOLVE</button>'
      + '<button type="button" data-argus-ingest-disposition="retry">RE-INGEST</button></div>';
    dialog.querySelector('[data-argus-ingest-disposition="keep"]').addEventListener('click', closeArgusIngestDialog);
    dialog.querySelector('[data-argus-ingest-disposition="resolve"]').addEventListener('click', async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      button.textContent = 'RESOLVING…';
      try {
        const response = await fetch(V6_WORLD_DISPOSITION_PATH, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, action: 'resolve' }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload.ok) throw new Error(payload.error || 'disposition unavailable');
        dialog.innerHTML = '<div class="biggy-argus-ingest-dialog-kicker">ARGUS // ISSUE RESOLVED</div>'
          + `<strong>${esc(file)}</strong><p>The operator disposition is recorded. The row will age out normally.</p>`
          + '<div class="biggy-argus-ingest-dialog-actions"><button type="button" data-argus-ingest-disposition="keep">CLOSE</button></div>';
        dialog.querySelector('[data-argus-ingest-disposition="keep"]').addEventListener('click', closeArgusIngestDialog);
        pollRagWorldState().catch(() => {});
      } catch (error) {
        button.disabled = false;
        button.textContent = 'RESOLVE';
        dialog.querySelector('p').textContent = `Unable to resolve: ${String(error.message || error)}`;
      }
    });
    dialog.querySelector('[data-argus-ingest-disposition="retry"]').addEventListener('click', async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      button.textContent = 'QUEUING…';
      try {
        const response = await fetch(V6_WORLD_RETRY_PATH, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload.ok) throw new Error(payload.error || 'retry unavailable');
        dialog.innerHTML = '<div class="biggy-argus-ingest-dialog-kicker">ARGUS // RE-INGEST QUEUED</div>'
          + `<strong>${esc(file)}</strong><p>The watcher now owns this file again.</p>`
          + '<div class="biggy-argus-ingest-dialog-actions"><button type="button" data-argus-ingest-disposition="keep">CLOSE</button></div>';
        dialog.querySelector('[data-argus-ingest-disposition="keep"]').addEventListener('click', closeArgusIngestDialog);
        pollRagWorldState().catch(() => {});
      } catch (error) {
        button.disabled = false;
        button.textContent = 'RE-INGEST';
        dialog.querySelector('p').textContent = `Unable to queue: ${String(error.message || error)}`;
      }
    });
  }

  function renderArgusRagOverview(status) {
    const hud = ensureArgusRagOverview();
    if (!hud) return;
    const data = status && typeof status === 'object' ? status : {};
    const state = String(data.state || 'offline').toLowerCase();
    const phase = String(data.phase || '').trim();
    const ingesting = state === 'active' || /^(detected|queued|indexing|extracting|embedding|active)$/i.test(phase);
    const reconnecting = state === 'monitor_offline' || phase === 'reconnecting';
    const issue = !data.ok || state === 'error' || /^(failed|quarantined)$/i.test(phase);
    const stateClass = issue ? 'is-issue' : ((ingesting || reconnecting) ? 'is-ingesting' : 'is-ready');
    const stateText = issue ? 'INGEST STATUS UNAVAILABLE'
      : (reconnecting ? 'INGEST MONITOR RECONNECTING'
        : (ingesting ? `INGESTING${phase ? ` // ${phase.toUpperCase()}` : ''}` : 'INGEST READY'));
    const metric = (value) => Number.isFinite(Number(value)) ? Number(value).toLocaleString() : '—';
    const latency = Number.isFinite(Number(data.latency_ms)) ? `${Math.round(Number(data.latency_ms))} ms` : '—';
    const currentSource = String(data.last_file || '').replace(/\\/g, '/').replace(/^.*?\/Library\//, '').replace(/^\/+/, '');
    const currentFile = currentSource.split('/').filter(Boolean).pop() || '';
    const currentRow = ingesting && currentFile ? {
      state: 'ingesting', file: currentFile, source: currentSource,
      phase: phase || 'ingesting', reason: '', current: true,
    } : null;
    const recent = Array.isArray(data.recent) ? data.recent.slice() : [];
    // Only remove last_file when it is separately represented by the active
    // ingestion row. In ready state last_file is historical evidence and must
    // remain, otherwise a five-row backend radar renders as four.
    const remaining = currentRow
      ? recent.filter((row) => String(row && row.source || '') !== currentSource)
      : recent;
    const failures = remaining.filter((row) => String(row && row.state || '').toLowerCase() === 'issue');
    const completed = remaining.filter((row) => String(row && row.state || '').toLowerCase() !== 'issue');
    // This is intentional operator ordering, not chronological ordering:
    // current work, then trouble, then the most recent healthy evidence.
    const cards = (currentRow ? [currentRow] : []).concat(failures, completed).slice(0, 5);
    const radar = cards.length ? cards.map((row) => {
      const rowState = String(row && row.state || 'complete').toLowerCase();
      const rowPhase = String(row && row.phase || '').toLowerCase();
      const file = String(row && row.file || row && row.source || 'unknown file');
      const detail = rowState === 'issue'
        ? String(row && (row.reason || row.phase) || 'issue')
        : (rowState === 'ingesting' ? String(row && row.phase || 'ingesting')
          : (rowPhase === 'resolved' ? 'resolved' : 'indexed'));
      const actionable = rowState === 'issue' || /^(detected|failed|quarantined|quarantine|error)$/i.test(rowPhase);
      if (actionable) {
        const encoded = encodeURIComponent(JSON.stringify({ file, source: String(row && row.source || ''), reason: String(row && row.reason || ''), phase: String(row && row.phase || '') }));
        return `<li class="is-${esc(rowState)}"><button type="button" data-argus-ingest-action="${encoded}" title="Single-click for ingestion actions"><i>◆</i><b>${esc(file)}</b><small>${esc(detail)} · ACTION</small></button></li>`;
      }
      return `<li class="is-${esc(rowState)}"><i>◆</i><b>${esc(file)}</b><small>${esc(detail)}</small></li>`;
    }).join('') : '<li class="is-empty"><small>NO RECENT LEDGER EVENTS</small></li>';
    hud.innerHTML = '<div class="biggy-argus-rag-title">A.R.G.U.S.</div>'
      + '<div class="biggy-argus-rag-subtitle">AUGMENTED RETRIEVAL &amp; GROUNDED UNDERSTANDING SYSTEM</div>'
      + '<div class="biggy-argus-rag-section">SYSTEM STATUS</div>'
      + `<div class="biggy-argus-rag-state ${stateClass}">● ${esc(stateText)}</div>`
      + '<dl class="biggy-argus-rag-metrics">'
      + `<div><dt>NODE COUNT</dt><dd>${metric(data.node_count)}</dd></div>`
      + `<div><dt>LINK COUNT</dt><dd>${metric(data.link_count)}</dd></div>`
      + `<div><dt>LATENCY</dt><dd>${latency}</dd></div>`
      + `<div><dt>STORE COUNT</dt><dd>${metric(data.store_count)}</dd></div>`
      + '</dl>'
      + '<div class="biggy-argus-rag-radar-label">INGEST RADAR // LAST 5</div>'
      + `<ol class="biggy-argus-rag-radar">${radar}</ol>`;
    hud.querySelectorAll('[data-argus-ingest-action]').forEach((button) => {
      button.addEventListener('pointerdown', (event) => event.stopPropagation());
      button.addEventListener('dblclick', (event) => {
        event.preventDefault();
        event.stopPropagation();
      });
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        try { openArgusIngestDialog(JSON.parse(decodeURIComponent(button.dataset.argusIngestAction))); } catch (_) {}
      });
    });
  }

  let ragWorldStatusFailures = 0;
  let lastGoodRagWorldStatus = null;

  function noteRagWorldStatusFailure() {
    ragWorldStatusFailures += 1;
    // The ingest API and the browser do not always restart in lock-step. A
    // single missed poll must not replace known-good operator truth with a
    // red status card. Only declare the feed unavailable after three misses.
    if (ragWorldStatusFailures >= 3 || !lastGoodRagWorldStatus) {
      renderArgusRagOverview({ ok: false, state: 'offline' });
    }
  }

  async function pollRagWorldState() {
    try {
      const response = await fetch(V6_WORLD_STATUS_PATH, { cache: 'no-store' });
      if (!response.ok) {
        noteRagWorldStatusFailure();
        return;
      }
      const status = await response.json();
      ragWorldStatusFailures = 0;
      lastGoodRagWorldStatus = status;
      renderArgusRagOverview(status);
      const phase = String(status && status.phase || '').toLowerCase();
      const state = String(status && status.state || '').toLowerCase();
      const file = String(status && status.last_file || '').trim();
      if (file && (state === 'error' || phase === 'failed' || phase === 'quarantined')) {
        postRagTrace({ state: 'failed', source: file, reason: status.last_error || phase });
      }
    } catch (_) {
      noteRagWorldStatusFailure();
    }
  }

  function installBiggyV6World(mainChat) {
    if (!mainChat) return;
    ragWorldReady = false;
    pendingRagTrace = null;
    mainChat.querySelectorAll('.biggy-v6-world, .biggy-v6-world-fallback')
      .forEach((node) => node.remove());

    const fallback = el('div', 'biggy-v6-world-fallback');
    fallback.dataset.biggyLayer = 'galaxy-fallback';
    fallback.setAttribute('data-testid', 'biggy-v6-world-fallback');
    fallback.innerHTML = '<div class="msg">3D world unavailable'
      + '<small id="biggyV6WorldFallbackReason">\u2014</small></div>';
    mainChat.appendChild(fallback);

    if (!hasWebGLSupport()) {
      showV6WorldFallback(fallback, 'WebGL not supported in this browser');
      return;
    }

    const iframe = el('iframe', 'biggy-v6-world');
    iframe.dataset.biggyLayer = 'galaxy';
    iframe.id = 'biggyV6World';
    iframe.setAttribute('data-testid', 'biggy-v6-world');
    iframe.setAttribute('title', 'A.R.G.U.S. \u2014 3D memory graph');
    iframe.setAttribute('referrerpolicy', 'no-referrer');
    iframe.src = `${V6_WORLD_PATH}?v=${encodeURIComponent(BUILD_ID)}`;
    // Chrome's own fullscreen (F11 / browser wrapper) resizes the top-level
    // page, but ForceGraph3D retains the dimensions captured when it was
    // constructed. Reconcile only on a real outer-window resize and only if
    // the iframe's measured dimensions changed. This is intentionally not a
    // ResizeObserver or animation loop: it cannot continuously re-render a
    // static display and drive the TD fans.
    let lastGalaxySize = '';
    let galaxyResizeTimer = null;
    const syncGalaxyCanvasSize = () => {
      galaxyResizeTimer = null;
      if (document.getElementById('biggyV6World') !== iframe) return;
      try {
        const rect = iframe.getBoundingClientRect();
        const width = Math.max(1, Math.round(rect.width));
        const height = Math.max(1, Math.round(rect.height));
        const size = `${width}x${height}`;
        if (size === lastGalaxySize) return;
        const inner = iframe.contentWindow;
        const graph = inner && inner.__os && inner.__os.Graph;
        if (!graph) return;
        graph.width(width).height(height);
        lastGalaxySize = size;
      } catch (_) {}
    };
    const scheduleGalaxyCanvasSize = () => {
      if (galaxyResizeTimer !== null) clearTimeout(galaxyResizeTimer);
      galaxyResizeTimer = setTimeout(syncGalaxyCanvasSize, 120);
    };
    window.addEventListener('resize', scheduleGalaxyCanvasSize);
    iframe.addEventListener('error', () => {
      showV6WorldFallback(fallback, 'local V6 viewer unreachable');
      iframe.remove();
    });
    iframe.addEventListener('load', () => {
      // The proxy injects Biggy's chrome reset before this document paints.
      // Do not mutate the iframe after load: that was the visible native-V6
      // flash between Hermes boot and the finished Biggy shell.
      // The graph module exposes window.__os only after it finishes
      // building the ForceGraph3D scene; if that never appears (WebGL
      // context creation failed inside the frame, or the Three.js CDN
      // import couldn't be reached), surface the fallback instead of a
      // silently blank canvas.
      // Module imports and a 1,100+ node first layout can legitimately take
      // more than four seconds after a cold browser start. Poll readiness for
      // a bounded window instead of painting a false failure over a graph
      // that is still initializing.
      const readyStartedAt = Date.now();
      const checkGalaxyReady = () => {
        if (document.getElementById('biggyV6World') !== iframe) return;
        let booted = false;
        try {
          booted = !!(iframe.contentWindow
            && iframe.contentWindow.__os
            && iframe.contentWindow.__biggyRagTraceReady);
        } catch (_) {
          booted = false;
        }
        if (booted) {
          fallback.classList.remove('is-active');
          try {
            iframe.contentWindow.postMessage(
              { type: 'biggy-argus-state', state: jarvisOrbState },
              window.location.origin,
            );
          } catch (_) {}
          scheduleGalaxyCanvasSize();
          return;
        }
        if (Date.now() - readyStartedAt >= 20000) {
          showV6WorldFallback(fallback, 'graph failed to initialize (check network access)');
          return;
        }
        setTimeout(checkGalaxyReady, 250);
      };
      setTimeout(checkGalaxyReady, 250);
      scheduleGalaxyCanvasSize();
      setTimeout(scheduleGalaxyCanvasSize, 700);
      // The ingest watcher is authoritative for a path that failed before it
      // could be retrieved.  Polling it here paints only that known bad edge.
      pollRagWorldState().catch(() => {});
    });
    mainChat.appendChild(iframe);
  }

  function makeHeader() {
    const header = el('div', 'biggy-brand-header');
    header.dataset.biggyLayer = 'header';
    header.innerHTML =
      `<div class="biggy-brand-controls">` +
      `<button id="biggyPtt" type="button" data-testid="biggy-ptt" title="Foot-pedal PTT status">● PTT</button>` +
      `<button id="biggyAudioRoute" type="button" data-testid="biggy-audio-route" title="Cycle Room / Headset / Mute audio">ROOM</button>` +
      `</div>` +
      `<div class="biggy-brand-status" aria-label="A.R.G.U.S. model">` +
      `<div id="j-brain"><span id="j-brain-chip" data-testid="biggy-jarvis-model">—</span></div>` +
      `</div>`;
    return header;
  }

  // Jarvis V6 reactor — a verbatim transplant of the real V6 presence unit
  // from brain-jarvis/viewer/3d.html (#j-orb / #j-state / #j-brain-chip),
  // native 204x204, unmodified markup/classes/ids. Only the outer wrapper's
  // positioning differs (centered over the header/workspace seam here
  // instead of viewport-right-docked as in the standalone V6 page); see the
  // matching CSS block in biggy-brand.css for the ported (but unscaled)
  // styling. This is inserted as a sibling of the header so it can overlap
  // the header/workspace boundary without being clipped by the header box.
  function makeReactorDock() {
    const dock = el('div', 'biggy-jarvis-transplant');
    dock.id = 'biggyJarvisTransplant';
    dock.dataset.biggyLayer = 'reactor';
    dock.setAttribute('data-testid', 'biggy-reactor-dock');
    dock.innerHTML =
      `<div id="j-orb" data-testid="biggy-jarvis-orb" role="status" aria-live="polite" aria-label="A.R.G.U.S. offline">` +
      `<svg viewBox="0 0 200 200" aria-hidden="true">` +
      `<defs><radialGradient id="hudCore" cx="50%" cy="45%" r="62%">` +
      `<stop offset="0%" stop-color="#0e413c"/><stop offset="70%" stop-color="#0b302d"/>` +
      `<stop offset="100%" stop-color="#082825"/>` +
      `</radialGradient></defs>` +
      `<g class="hud-pulse glow">` +
      `<g class="rot rot-a"><g id="hud-ticks" class="s-hud" stroke-width="0.9"></g></g>` +
      `<circle class="rot rot-b s-hud" cx="100" cy="100" r="86" stroke-width="3.4" stroke-dasharray="48 30" stroke-linecap="round"/>` +
      `<circle class="s-hud2" cx="100" cy="100" r="79" stroke-width="1" opacity="0.45"/>` +
      `<circle class="rot rot-c s-accent" cx="100" cy="100" r="70" stroke-width="4.2" stroke-dasharray="122 318" stroke-linecap="round"/>` +
      `<circle class="rot rot-d s-hud" cx="100" cy="100" r="55" stroke-width="1.2" stroke-dasharray="2 6" opacity="0.7"/>` +
      `<circle class="s-hud2" cx="100" cy="100" r="40" stroke-width="1" opacity="0.4"/>` +
      `<g class="rot rot-core s-hud2" id="hud-spokes" stroke-width="0.9" opacity="0.5"></g>` +
      `<g class="rot rot-radar"><line class="s-hud" x1="100" y1="100" x2="100" y2="53" stroke-width="1.6" opacity="0.6"/></g>` +
      `<g id="hud-dots"></g>` +
      `<circle class="core-glow" cx="100" cy="100" r="37"/>` +
      `<circle class="core-disc" cx="100" cy="100" r="32"/>` +
      `<circle class="core-lobe" cx="100" cy="100" r="32"/>` +
      `<circle class="core-rim" cx="100" cy="100" r="32" stroke-width="1.2"/>` +
      `<text class="hud-label" x="101.5" y="103.5" text-anchor="middle">A.R.G.U.S.</text>` +
      `</g>` +
      `</svg>` +
      `</div>` +
      `<div id="j-state" data-testid="biggy-jarvis-state"><span class="dot"></span><span id="j-state-txt">OFFLINE</span></div>`;
    return dock;
  }

  function installSmedleyButton(header) {
    const btn = header && header.querySelector('#biggyOpenSmedley');
    if (!btn || btn.dataset.bound === '1') return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', (event) => {
      event.preventDefault();
      openSmedleyGui();
    });
  }

  // ── Mapbox travel display (Agent map_view_model only) ─────────────────────
  const MAPBOX_CSS = 'https://cdn.jsdelivr.net/npm/mapbox-gl@3.9.4/dist/mapbox-gl.css';
  const MAPBOX_JS = 'https://cdn.jsdelivr.net/npm/mapbox-gl@3.9.4/dist/mapbox-gl.js';
  const MAP_CONFIG_URL = '/api/biggy/mapbox-public-config';
  let mapboxLoadPromise = null;
  let mapInstance = null;
  let lastMapModelKey = '';
  let mapRenderPromise = null;

  function setGalaxyRenderPaused(paused) {
    const frame = document.getElementById('biggyV6World');
    if (!frame || !frame.contentWindow) return;
    try {
      frame.contentWindow.postMessage(
        { type: paused ? 'biggy-world-pause' : 'biggy-world-resume' },
        window.location.origin,
      );
    } catch (_) {}
  }

  function releaseTravelMap() {
    try {
      if (mapInstance) mapInstance.remove();
    } catch (_) {}
    mapInstance = null;
    setGalaxyRenderPaused(false);
  }

  function loadMapboxAssets() {
    if (window.mapboxgl) return Promise.resolve(window.mapboxgl);
    if (mapboxLoadPromise) return mapboxLoadPromise;
    mapboxLoadPromise = new Promise((resolve, reject) => {
      try {
        if (!document.querySelector('link[data-biggy-mapbox]')) {
          const link = document.createElement('link');
          link.rel = 'stylesheet';
          link.href = MAPBOX_CSS;
          link.setAttribute('data-biggy-mapbox', '1');
          document.head.appendChild(link);
        }
        const existing = document.querySelector('script[data-biggy-mapbox]');
        if (existing) {
          existing.addEventListener('load', () => resolve(window.mapboxgl));
          existing.addEventListener('error', () => reject(new Error('mapbox_script_failed')));
          if (window.mapboxgl) resolve(window.mapboxgl);
          return;
        }
        const script = document.createElement('script');
        script.src = MAPBOX_JS;
        script.async = true;
        script.setAttribute('data-biggy-mapbox', '1');
        script.onload = () => resolve(window.mapboxgl);
        script.onerror = () => reject(new Error('mapbox_script_failed'));
        document.head.appendChild(script);
      } catch (err) {
        reject(err);
      }
    });
    return mapboxLoadPromise;
  }

  const TRAVEL_CATEGORIES = [
    'Filter',
    'Phone',
    'Travel',
    'Calendar',
    'Mail',
    'Weather',
    'Lodging',
    'Meals',
    'Entertainment',
    'Fuel',
    'Tasks',
    'Notes',
    'Alerts',
  ];
  const BIGGY_DEFAULT_WEATHER_ZIP = '32444';
  const BIGGY_WEATHER_ZIP_KEY = 'biggy.weather.zip';

  function savedWeatherZip() {
    try {
      const value = String(window.localStorage.getItem(BIGGY_WEATHER_ZIP_KEY) || '').trim();
      return /^\d{5}$/.test(value) ? value : BIGGY_DEFAULT_WEATHER_ZIP;
    } catch (_) {
      return BIGGY_DEFAULT_WEATHER_ZIP;
    }
  }

  function extractWeatherZip(value) {
    const match = String(value || '').match(/(?:^|\D)(\d{5})(?::US)?(?:\D|$)/i);
    return match ? match[1] : '';
  }

  function weatherTemperature(value) {
    if (value === null || value === undefined || value === '') return '—';
    const number = Number(value);
    return Number.isFinite(number) ? `${Math.round(number)}°` : '—';
  }

  function hasWeatherNumber(value) {
    return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  }

  function renderWeatherPanel(dlg, weather) {
    const state = dlg && dlg.querySelector('#biggyWeatherState');
    if (!state) return;
    const currentBox = state.querySelector('#biggyWeatherCurrent');
    const forecastBox = state.querySelector('#biggyWeatherForecast');
    const status = state.querySelector('#biggyWeatherStatus');
    const zipInput = state.querySelector('#biggyWeatherZip');
    const payload = weather && typeof weather === 'object' ? weather : {};
    const zipCode = extractWeatherZip(payload.zip) || (zipInput && inputWeatherZip(zipInput)) || BIGGY_DEFAULT_WEATHER_ZIP;
    if (zipInput) zipInput.value = zipCode;
    if (currentBox) {
      currentBox.replaceChildren();
      const current = payload.current && typeof payload.current === 'object' ? payload.current : {};
      const temp = document.createElement('div');
      temp.className = 'biggy-weather-current-temp';
      temp.textContent = weatherTemperature(current.temp_f);
      const copy = document.createElement('div');
      copy.className = 'biggy-weather-current-copy';
      const place = document.createElement('strong');
      place.textContent = String(payload.location || zipCode);
      const conditions = document.createElement('span');
      const detail = [
        String(current.summary || '').trim(),
        hasWeatherNumber(current.humidity_percent) ? `Humidity ${Math.round(Number(current.humidity_percent))}%` : '',
        hasWeatherNumber(current.wind_mph) ? `Wind ${Math.round(Number(current.wind_mph))} mph` : '',
      ].filter(Boolean).join(' · ');
      conditions.textContent = detail || 'Current observation pending';
      copy.append(place, conditions);
      currentBox.append(temp, copy);
    }
    if (forecastBox) {
      forecastBox.replaceChildren();
      const rows = Array.isArray(payload.forecast) ? payload.forecast.slice(0, 7) : [];
      rows.forEach((row) => {
        const card = document.createElement('article');
        card.className = 'biggy-weather-day';
        const day = document.createElement('strong');
        day.textContent = String(row.day || row.date || 'Forecast');
        const temps = document.createElement('div');
        temps.className = 'biggy-weather-day-temps';
        temps.textContent = `${weatherTemperature(row.high_f)} / ${weatherTemperature(row.low_f)}`;
        const summary = document.createElement('span');
        summary.textContent = String(row.summary || 'Forecast available');
        const precip = document.createElement('small');
        precip.textContent = hasWeatherNumber(row.precip_percent) ? `${Math.round(Number(row.precip_percent))}% precipitation` : '';
        card.append(day, temps, summary, precip);
        forecastBox.appendChild(card);
      });
      if (!rows.length) {
        const unavailable = document.createElement('div');
        unavailable.className = 'biggy-weather-unavailable';
        unavailable.textContent = String(payload.error || 'Live forecast is temporarily unavailable. Retry or enter another ZIP.');
        forecastBox.appendChild(unavailable);
      }
    }
    if (status) {
      status.className = `biggy-weather-status${payload.stale || !payload.ok ? ' is-warning' : ''}`;
      status.textContent = String(payload.warning || payload.error || `${payload.source || 'Weather service'}${payload.updated ? ` · updated ${payload.updated}` : ''}`);
    }
  }

  function inputWeatherZip(input) {
    return extractWeatherZip(input && input.value);
  }

  async function refreshWeatherPanel(dlg, requestedZip, { persist = true } = {}) {
    const state = dlg && dlg.querySelector('#biggyWeatherState');
    if (!state) return false;
    const input = state.querySelector('#biggyWeatherZip');
    const zipCode = extractWeatherZip(requestedZip) || inputWeatherZip(input) || savedWeatherZip();
    if (input) input.value = zipCode;
    if (persist) {
      try { window.localStorage.setItem(BIGGY_WEATHER_ZIP_KEY, zipCode); } catch (_) {}
    }
    const status = state.querySelector('#biggyWeatherStatus');
    if (status) {
      status.className = 'biggy-weather-status is-loading';
      status.textContent = `Loading the 5–7 day forecast for ${zipCode}…`;
    }
    try {
      const weather = await operatorFetch(`/api/biggy/pa/weather?zip=${encodeURIComponent(zipCode)}`);
      renderWeatherPanel(dlg, weather);
      return !!weather.ok;
    } catch (error) {
      renderWeatherPanel(dlg, { ok: false, zip: zipCode, error: String(error && error.message || 'Weather refresh failed.') });
      return false;
    }
  }

  function renderArgusWeatherBriefing(dlg, briefing) {
    if (!briefing || typeof briefing !== 'object') return false;
    const periods = briefing.forecast && Array.isArray(briefing.forecast.periods)
      ? briefing.forecast.periods.slice(0, 7)
      : [];
    if (!periods.length) return false;
    const currents = briefing.currents && typeof briefing.currents === 'object' ? briefing.currents : {};
    const explicitZip = extractWeatherZip(briefing.location_echo);
    const source = briefing.source && typeof briefing.source === 'object' ? briefing.source : {};
    renderWeatherPanel(dlg, {
      ok: true,
      zip: explicitZip || savedWeatherZip(),
      location: String(currents.location || briefing.location_label || briefing.location_echo || explicitZip || 'Weather forecast'),
      source: source.provider === 'weather_underground_twc' ? 'Weather Underground / The Weather Company' : String(source.provider || 'A.R.G.U.S. weather briefing'),
      updated: String(currents.observed_at || ''),
      current: {
        temp_f: currents.temp_f,
        summary: String(currents.summary || ''),
        humidity_percent: currents.humidity_percent,
        wind_mph: currents.wind_mph,
      },
      forecast: periods.map((period) => ({
        day: period.day,
        date: period.date,
        high_f: period.high_f,
        low_f: period.low_f,
        precip_percent: period.precip_percent,
        summary: period.summary,
      })),
      stale: false,
      warning: '',
    });
    if (explicitZip) {
      try { window.localStorage.setItem(BIGGY_WEATHER_ZIP_KEY, explicitZip); } catch (_) {}
    }
    return true;
  }

  function railCategoryKey(label) {
    return String(label || '').trim().toLowerCase();
  }

  let galaxyFilterTreePromise = null;
  let galaxyFilterSelectedPath = '';
  let galaxyFilterSelectedCount = 0;

  function galaxyWorldFrame() {
    return document.getElementById('biggyV6World');
  }

  function postGalaxyFilterFocus(path) {
    const frame = galaxyWorldFrame();
    if (!ragWorldReady || !frame || !frame.contentWindow) return false;
    frame.contentWindow.postMessage({
      type: 'biggy-galaxy-filter-focus',
      path: String(path || ''),
    }, window.location.origin);
    return true;
  }

  function openGalaxyFilterDocument(path) {
    const rel = String(path || '').trim();
    if (!rel) return;
    window.open(`/api/biggy/rag-file?path=${encodeURIComponent(rel)}`, '_blank', 'noopener');
  }

  function markGalaxyFilterSelection(path, nodeCount) {
    galaxyFilterSelectedPath = String(path || '');
    galaxyFilterSelectedCount = galaxyFilterSelectedPath ? Math.max(0, Number(nodeCount || 0)) : 0;
    const dlg = document.getElementById('biggyTravelMapDialog');
    if (!dlg) return;
    const stateEl = dlg.querySelector('#biggyGalaxyFilterStatus');
    if (stateEl) {
      stateEl.textContent = galaxyFilterSelectedPath
        ? `${galaxyFilterSelectedPath} · ${galaxyFilterSelectedCount} nodes`
        : 'Full galaxy · centered on BIGGY PROMPT';
    }
    dlg.querySelectorAll('[data-biggy-filter-path]').forEach((button) => {
      button.classList.toggle(
        'is-selected',
        button.getAttribute('data-biggy-filter-path') === galaxyFilterSelectedPath,
      );
    });
  }

  function appendGalaxyFilterRows(container, branch, depth = 0) {
    const children = branch && Array.isArray(branch.children) ? branch.children : [];
    children.forEach((item) => {
      const path = String(item && item.path || '');
      const kind = String(item && item.kind || 'folder');
      const entry = document.createElement('div');
      entry.className = `biggy-galaxy-filter-entry is-${kind}`;
      entry.setAttribute('role', 'treeitem');
      entry.setAttribute('aria-level', String(depth + 1));
      const line = document.createElement('div');
      line.className = 'biggy-galaxy-filter-line';
      line.style.paddingLeft = `${depth * 14}px`;
      let childGroup = null;
      if (kind === 'folder') {
        const expanded = depth === 0 || !!(
          galaxyFilterSelectedPath &&
          (galaxyFilterSelectedPath === path || galaxyFilterSelectedPath.startsWith(`${path}/`))
        );
        const toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'biggy-galaxy-filter-toggle';
        toggle.setAttribute('aria-label', `${expanded ? 'Collapse' : 'Expand'} ${path}`);
        toggle.setAttribute('aria-expanded', String(expanded));
        toggle.textContent = expanded ? '▾' : '▸';
        childGroup = document.createElement('div');
        childGroup.className = 'biggy-galaxy-filter-children';
        childGroup.setAttribute('role', 'group');
        childGroup.hidden = !expanded;
        toggle.addEventListener('click', (event) => {
          event.preventDefault();
          event.stopPropagation();
          const nextExpanded = childGroup.hidden;
          childGroup.hidden = !nextExpanded;
          toggle.setAttribute('aria-expanded', String(nextExpanded));
          toggle.setAttribute('aria-label', `${nextExpanded ? 'Collapse' : 'Expand'} ${path}`);
          toggle.textContent = nextExpanded ? '▾' : '▸';
        });
        line.appendChild(toggle);
      } else {
        const spacer = document.createElement('span');
        spacer.className = 'biggy-galaxy-filter-toggle-spacer';
        spacer.setAttribute('aria-hidden', 'true');
        line.appendChild(spacer);
      }
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `biggy-galaxy-filter-row is-${kind}`;
      button.setAttribute('data-biggy-filter-path', path);
      button.setAttribute('data-biggy-filter-kind', kind);
      button.title = kind === 'folder' ? `Focus galaxy on ${path}` : `Open ${path}`;
      const marker = document.createElement('span');
      marker.className = 'biggy-galaxy-filter-marker';
      marker.textContent = kind === 'folder' ? '◆' : '·';
      const label = document.createElement('span');
      label.className = 'biggy-galaxy-filter-label';
      label.textContent = String(item && item.name || path);
      button.append(marker, label);
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (kind === 'document') {
          openGalaxyFilterDocument(path);
          return;
        }
        if (!postGalaxyFilterFocus(path)) {
          const status = document.getElementById('biggyGalaxyFilterStatus');
          if (status) status.textContent = 'Galaxy is still starting. Try the folder again in a moment.';
        }
      });
      line.appendChild(button);
      entry.appendChild(line);
      if (kind === 'folder' && childGroup) {
        appendGalaxyFilterRows(childGroup, item, depth + 1);
        entry.appendChild(childGroup);
      }
      container.appendChild(entry);
    });
  }

  function renderGalaxyFilterPanel(dlg, payload) {
    const tree = dlg && dlg.querySelector('#biggyGalaxyFilterTree');
    const status = dlg && dlg.querySelector('#biggyGalaxyFilterStatus');
    if (!tree || !status) return;
    tree.replaceChildren();
    const root = payload && payload.root;
    if (!root || !Array.isArray(root.children)) {
      status.textContent = 'Directory tree unavailable.';
      return;
    }
    appendGalaxyFilterRows(tree, root, 0);
    status.textContent = galaxyFilterSelectedPath
      ? galaxyFilterSelectedPath
      : `Full galaxy · ${Number(payload.node_count || 0).toLocaleString()} browsable nodes`;
    markGalaxyFilterSelection(galaxyFilterSelectedPath, galaxyFilterSelectedCount);
  }

  async function refreshGalaxyFilterPanel(dlg) {
    const status = dlg && dlg.querySelector('#biggyGalaxyFilterStatus');
    if (status) status.textContent = 'Loading bounded RAG directory tree…';
    if (!galaxyFilterTreePromise) {
      galaxyFilterTreePromise = fetch(V6_WORLD_TREE_PATH, {
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { Accept: 'application/json' },
      }).then(async (response) => {
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(String(payload.error || `HTTP ${response.status}`));
        return payload;
      }).catch((error) => {
        galaxyFilterTreePromise = null;
        throw error;
      });
    }
    try {
      renderGalaxyFilterPanel(dlg, await galaxyFilterTreePromise);
    } catch (error) {
      if (status) status.textContent = `Directory tree unavailable: ${String(error && error.message || 'unknown error')}`;
    } finally {
      galaxyFilterTreePromise = null;
    }
  }

  function mapRecCategoryToRail(category) {
    const c = String(category || '').trim().toLowerCase();
    if (c === 'filter') return 'filter';
    if (c === 'phone' || c === 'sms' || c === 'text' || c === 'call') return 'phone';
    if (!c || c === 'travel') return 'travel';
    if (c === 'weather' || c === 'radar') return 'weather';
    if (c === 'lodging' || c === 'hotel') return 'lodging';
    if (c === 'meals' || c === 'meal' || c === 'restaurant' || c === 'steakhouse' || c === 'dining') {
      return 'meals';
    }
    if (c === 'entertainment' || c === 'event' || c === 'shows') return 'entertainment';
    if (c === 'fuel' || c === 'gas') return 'fuel';
    if (c === 'mail' || c === 'email' || c === 'inbox') return 'mail';
    if (c === 'task' || c === 'tasks' || c === 'todo') return 'tasks';
    if (c === 'note' || c === 'notes') return 'notes';
    if (c === 'alert' || c === 'alerts' || c === 'status') return 'alerts';
    if (c === 'calendar' || c === 'schedule') return 'calendar';
    return 'travel';
  }

  function operatorPanel(dlg, key) {
    return dlg ? dlg.querySelector(`[data-biggy-operator-panel="${key}"]`) : null;
  }

  function clearOperatorPanel(panel) {
    if (panel) panel.replaceChildren();
  }

  function operatorHeading(text) {
    const heading = document.createElement('div');
    heading.className = 'biggy-operator-panel-title';
    heading.textContent = text;
    return heading;
  }

  function operatorMessage(panel, text, state) {
    clearOperatorPanel(panel);
    const message = document.createElement('p');
    message.className = `biggy-operator-message ${state ? `is-${state}` : ''}`;
    message.textContent = text;
    panel.appendChild(message);
  }

  async function operatorFetch(url, options = {}) {
    const method = String(options.method || 'GET').toUpperCase();
    const fetchOptions = { credentials: 'same-origin', method };
    if (method !== 'GET' && options.body !== undefined) {
      fetchOptions.headers = { 'Content-Type': 'application/json' };
      fetchOptions.body = JSON.stringify(options.body);
    }
    const response = await fetch(url, fetchOptions);
    let payload = {};
    try { payload = await response.json(); } catch (_) {}
    if (!response.ok) throw new Error(String((payload && payload.error) || `HTTP ${response.status}`));
    return payload && typeof payload === 'object' ? payload : {};
  }

  function appendOperatorRow(panel, primary, secondary, state) {
    const row = document.createElement('div');
    row.className = `biggy-operator-row ${state ? `is-${state}` : ''}`;
    const title = document.createElement('div');
    title.className = 'biggy-operator-row-title';
    title.textContent = primary;
    row.appendChild(title);
    if (secondary) {
      const detail = document.createElement('div');
      detail.className = 'biggy-operator-row-detail';
      detail.textContent = secondary;
      row.appendChild(detail);
    }
    panel.appendChild(row);
    return row;
  }

  function operatorButton(label, tone = '') {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `biggy-operator-btn${tone ? ` is-${tone}` : ''}`;
    button.textContent = label;
    return button;
  }

  function operatorField(label, name, type = 'text', value = '') {
    const wrapper = document.createElement('label');
    wrapper.className = 'biggy-operator-field';
    const caption = document.createElement('span');
    caption.textContent = label;
    const input = type === 'textarea' ? document.createElement('textarea') : document.createElement('input');
    input.name = name;
    if (type !== 'textarea') input.type = type;
    if (type === 'email') input.multiple = true;
    input.value = value || '';
    if (['to', 'subject', 'summary', 'start', 'end'].includes(name)) input.required = true;
    wrapper.append(caption, input);
    return wrapper;
  }

  function operatorFormStatus(form, text, state = '') {
    let status = form.querySelector('.biggy-operator-form-status');
    if (!status) {
      status = document.createElement('div');
      status.className = 'biggy-operator-form-status';
      form.appendChild(status);
    }
    status.className = `biggy-operator-form-status${state ? ` is-${state}` : ''}`;
    status.textContent = text || '';
  }

  function phoneNumberValue(form) {
    return String(new FormData(form).get('to') || '').trim();
  }

  function setPhoneDestination(forms, number) {
    forms.forEach((form) => {
      const input = form && form.querySelector('[name="to"]');
      if (input) input.value = String(number || '');
    });
  }

  function openPhoneContactCard(panel, label, contacts, forms) {
    const primaryView = Array.from(panel.childNodes);
    panel.replaceChildren();

    const card = document.createElement('section');
    card.className = 'biggy-phone-contact-card';
    card.setAttribute('aria-label', `${label} contacts`);
    const chrome = document.createElement('div');
    chrome.className = 'biggy-phone-contact-card-chrome';
    const title = operatorHeading(`${label} contacts`);
    const close = operatorButton('‹ Back to Phone');
    close.classList.add('biggy-phone-contact-card-close');
    close.setAttribute('aria-label', `Close ${label} contacts and return to Phone`);
    const restorePhone = () => panel.replaceChildren(...primaryView);
    close.addEventListener('click', restorePhone);
    chrome.append(title, close);
    card.appendChild(chrome);

    const list = document.createElement('div');
    list.className = 'biggy-phone-contact-card-list';
    if (!contacts.length) {
      const empty = document.createElement('div');
      empty.className = 'biggy-operator-form-status is-muted';
      empty.textContent = `No ${label} contacts configured.`;
      list.appendChild(empty);
    } else {
      contacts.forEach((contact) => {
        const choice = operatorButton(String(contact.name || contact.number || 'Contact'));
        choice.type = 'button';
        choice.title = String(contact.number || '');
        choice.addEventListener('click', () => {
          setPhoneDestination(forms, contact.number);
          restorePhone();
          const target = forms[0] && forms[0].querySelector('[name="to"]');
          if (target) target.focus();
        });
        list.appendChild(choice);
      });
    }
    card.appendChild(list);
    panel.appendChild(card);
  }

  function renderPhoneContacts(panel, phone, forms) {
    panel.appendChild(operatorHeading('Contacts'));
    const groups = phone.contacts && typeof phone.contacts === 'object' ? phone.contacts : {};
    const wrap = document.createElement('div');
    wrap.className = 'biggy-operator-form biggy-phone-contacts';
    const actions = document.createElement('div');
    actions.className = 'biggy-operator-actions biggy-phone-contact-launchers';

    ['EGS', 'Personal'].forEach((label) => {
      const contacts = Array.isArray(groups[label]) ? groups[label] : [];
      const button = operatorButton(label.toUpperCase(), label === 'EGS' ? 'primary' : '');
      button.type = 'button';
      button.setAttribute('aria-label', `Open ${label} contacts`);
      button.addEventListener('click', () => openPhoneContactCard(panel, label, contacts, forms));
      actions.appendChild(button);
    });
    wrap.appendChild(actions);
    panel.appendChild(wrap);
  }

  function renderPhoneHistory(panel, items) {
    panel.appendChild(operatorHeading('Recent calls and messages'));
    if (!items.length) {
      appendOperatorRow(panel, 'No recent phone activity.', 'Calls and texts will appear here after Twilio is connected.', 'muted');
      return;
    }
    items.slice(0, 20).forEach((item) => {
      const kind = String(item.kind || '').toUpperCase();
      const direction = String(item.direction || '').replace(/-/g, ' ').toUpperCase();
      const peer = String(item.direction || '').startsWith('inbound') ? item.from : item.to;
      const detail = item.kind === 'sms'
        ? String(item.body || '').slice(0, 180)
        : `${String(item.status || '')}${item.duration ? ` · ${item.duration}s` : ''}`;
      appendOperatorRow(panel, `${kind} · ${direction} · ${String(peer || 'unknown')}`, `${String(item.date || '')}${detail ? ` · ${detail}` : ''}`, 'ready');
    });
  }

  async function renderPhoneWorkspace(panel, dlg, phone) {
    clearOperatorPanel(panel);
    panel.appendChild(operatorHeading('Galaxy S25 Ultra'));
    const state = String(phone.state || 'disconnected');
    appendOperatorRow(
      panel,
      `${String(phone.device_label || 'Galaxy S25 Ultra')} · ${String(phone.carrier || 'Verizon')}`,
      phone.connected ? 'Twilio voice and SMS are ready.' : 'Twilio is not connected. Calls and texts remain disabled.',
      phone.connected ? 'ready' : 'warning',
    );
    if (!phone.connected) {
      const missing = Array.isArray(phone.missing) ? phone.missing.join(', ') : '';
      appendOperatorRow(panel, 'Phone setup required.', missing || `Add the profile-local configuration at ${String(phone.config_path_hint || '~/.hermes/profiles/biggy/biggy-phone.json')}.`, 'warning');
    }

    const sms = document.createElement('form');
    sms.className = 'biggy-operator-form biggy-phone-sms-form';
    sms.appendChild(operatorHeading('Text message'));
    sms.appendChild(operatorField('Mobile number', 'to', 'tel'));
    sms.appendChild(operatorField('Message', 'body', 'textarea'));
    const smsActions = document.createElement('div');
    smsActions.className = 'biggy-operator-actions';
    const send = operatorButton('Review and send', 'primary');
    send.type = 'submit';
    send.disabled = !phone.sms_ready;
    smsActions.appendChild(send);
    sms.appendChild(smsActions);
    sms.addEventListener('submit', async (event) => {
      event.preventDefault();
      const data = new FormData(sms);
      const to = phoneNumberValue(sms);
      const body = String(data.get('body') || '').trim();
      if (!to || !body) return operatorFormStatus(sms, 'A mobile number and message are required.', 'warning');
      if (!window.confirm(`Send this text to ${to}?\n\n${body}`)) return;
      send.disabled = true;
      operatorFormStatus(sms, 'Sending text…', 'loading');
      try {
        await operatorFetch('/api/biggy/phone/sms/send', { method: 'POST', body: { to, body, confirmed: true } });
        sms.reset();
        operatorFormStatus(sms, 'Text queued through Twilio.', 'ready');
        window.setTimeout(() => refreshOperatorPanel(dlg, 'phone'), 900);
      } catch (error) {
        operatorFormStatus(sms, String(error && error.message || 'Text failed.'), 'warning');
        send.disabled = !phone.sms_ready;
      }
    });
    panel.appendChild(sms);

    const call = document.createElement('form');
    call.className = 'biggy-operator-form biggy-phone-call-form';
    call.appendChild(operatorHeading('Voice call'));
    call.appendChild(operatorField('Mobile number', 'to', 'tel'));
    const callActions = document.createElement('div');
    callActions.className = 'biggy-operator-actions';
    const dial = operatorButton('Review and call', 'primary');
    dial.type = 'submit';
    dial.disabled = !phone.voice_ready;
    callActions.appendChild(dial);
    call.appendChild(callActions);
    if (phone.connected && !phone.voice_ready) operatorFormStatus(call, 'Voice requires an HTTPS TwiML URL in the local phone profile.', 'warning');
    call.addEventListener('submit', async (event) => {
      event.preventDefault();
      const to = phoneNumberValue(call);
      if (!to) return operatorFormStatus(call, 'A mobile number is required.', 'warning');
      if (!window.confirm(`Call ${to} through Biggy Phone?`)) return;
      dial.disabled = true;
      operatorFormStatus(call, 'Starting call…', 'loading');
      try {
        await operatorFetch('/api/biggy/phone/call/start', { method: 'POST', body: { to, confirmed: true } });
        operatorFormStatus(call, 'Call queued through Twilio.', 'ready');
        window.setTimeout(() => refreshOperatorPanel(dlg, 'phone'), 900);
      } catch (error) {
        operatorFormStatus(call, String(error && error.message || 'Call failed.'), 'warning');
        dial.disabled = !phone.voice_ready;
      }
    });
    panel.appendChild(call);

    renderPhoneContacts(panel, phone, [sms, call]);

    if (phone.history_ready) {
      try {
        const history = await operatorFetch('/api/biggy/phone/history?limit=20');
        if (dlg.getAttribute('data-active-category') !== 'phone') return;
        renderPhoneHistory(panel, Array.isArray(history.items) ? history.items : []);
      } catch (error) {
        appendOperatorRow(panel, 'Phone history unavailable.', String(error && error.message || 'Unable to load recent calls and messages.'), 'warning');
      }
    } else {
      renderPhoneHistory(panel, []);
    }
  }

  function localDateTimeValue(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const pad = (number) => String(number).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function calendarLocalDate(value) {
    const text = String(value || '');
    if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return new Date(`${text}T00:00:00`);
    return new Date(text);
  }

  function calendarDateKey(value) {
    const date = value instanceof Date ? value : calendarLocalDate(value);
    if (Number.isNaN(date.getTime())) return '';
    const pad = (number) => String(number).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  }

  function calendarWorkspaceState(dlg) {
    if (!dlg.__biggyCalendarState) {
      dlg.__biggyCalendarState = {
        view: 'month',
        cursor: calendarDateKey(new Date()),
        calendarIds: ['primary'],
      };
    }
    return dlg.__biggyCalendarState;
  }

  function calendarRequestWindow(state) {
    const cursor = calendarLocalDate(state.cursor);
    cursor.setHours(0, 0, 0, 0);
    let start = new Date(cursor);
    let end = new Date(cursor);
    if (state.view === 'day') {
      end.setDate(end.getDate() + 1);
    } else {
      start = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
      start.setDate(start.getDate() - start.getDay());
      end = new Date(start);
      end.setDate(end.getDate() + 42);
    }
    return { start, end };
  }

  function calendarRequestUrl(state) {
    const range = calendarRequestWindow(state);
    const query = new URLSearchParams({ start: range.start.toISOString(), end: range.end.toISOString() });
    (state.calendarIds.length ? state.calendarIds : ['primary']).forEach((id) => query.append('calendar_id', id));
    return `/api/biggy/pa/calendar?${query.toString()}`;
  }

  function calendarPayload(form) {
    const data = new FormData(form);
    const start = new Date(String(data.get('start') || ''));
    const end = new Date(String(data.get('end') || ''));
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) throw new Error('Start and end times are required.');
    if (end <= start) throw new Error('End must be after start.');
    return {
      summary: String(data.get('summary') || '').trim(),
      start: start.toISOString(),
      end: end.toISOString(),
      location: String(data.get('location') || '').trim(),
      description: String(data.get('description') || '').trim(),
    };
  }

  function appendCalendarForm(panel, dlg, event = null, defaults = null) {
    const editing = !!(event && event.id);
    const seed = event || defaults || {};
    const form = document.createElement('form');
    form.className = 'biggy-operator-form biggy-calendar-form';
    form.appendChild(operatorHeading(editing ? 'Edit event' : 'Add event'));
    form.appendChild(operatorField('Title', 'summary', 'text', seed.summary));
    const times = document.createElement('div');
    times.className = 'biggy-operator-form-grid';
    times.appendChild(operatorField('Start', 'start', 'datetime-local', localDateTimeValue(seed.start)));
    times.appendChild(operatorField('End', 'end', 'datetime-local', localDateTimeValue(seed.end)));
    form.appendChild(times);
    form.appendChild(operatorField('Location', 'location', 'text', seed.location));
    form.appendChild(operatorField('Notes', 'description', 'textarea', seed.description));
    const actions = document.createElement('div');
    actions.className = 'biggy-operator-actions';
    const save = operatorButton(editing ? 'Save changes' : 'Add to calendar', 'primary');
    save.type = 'submit';
    actions.appendChild(save);
    const cancel = operatorButton('Cancel');
    cancel.addEventListener('click', () => refreshOperatorPanel(dlg, 'calendar'));
    actions.appendChild(cancel);
    form.appendChild(actions);
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      save.disabled = true;
      operatorFormStatus(form, editing ? 'Saving event…' : 'Creating event…', 'loading');
      try {
        const body = calendarPayload(form);
        if (editing) body.event_id = String(event.id);
        await operatorFetch(editing ? '/api/biggy/pa/calendar/update' : '/api/biggy/pa/calendar/create', { method: 'POST', body });
        await refreshOperatorPanel(dlg, 'calendar');
      } catch (error) {
        operatorFormStatus(form, String(error && error.message || 'Calendar action failed.'), 'warning');
        save.disabled = false;
      }
    });
    panel.appendChild(form);
  }

  function calendarEventLabel(event, includeDate = false) {
    const start = calendarLocalDate(event.start);
    if (Number.isNaN(start.getTime())) return String(event.summary || '(no title)');
    const isAllDay = /^\d{4}-\d{2}-\d{2}$/.test(String(event.start || ''));
    const time = isAllDay ? 'ALL DAY' : start.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    const date = includeDate ? `${start.toLocaleDateString([], { month: 'short', day: 'numeric' })} · ` : '';
    return `${date}${time} · ${String(event.summary || '(no title)')}`;
  }

  function calendarEventEditor(panel, dlg, event, writeReady) {
    if (!writeReady || !event.editable || !event.id) return;
    clearOperatorPanel(panel);
    panel.appendChild(operatorHeading('Calendar'));
    appendCalendarForm(panel, dlg, event);
    const actions = document.createElement('div');
    actions.className = 'biggy-operator-actions';
    const remove = operatorButton('Delete event', 'danger');
    actions.appendChild(remove);
    panel.appendChild(actions);
    remove.addEventListener('click', async () => {
      if (!window.confirm(`Delete “${String(event.summary || 'this event')}” from your calendar?`)) return;
      remove.disabled = true;
      try {
        await operatorFetch('/api/biggy/pa/calendar/delete', { method: 'POST', body: { event_id: event.id, confirmed: true } });
        await refreshOperatorPanel(dlg, 'calendar');
      } catch (error) {
        operatorMessage(panel, String(error && error.message || 'Delete failed.'), 'warning');
      }
    });
  }

  function renderCalendarWorkspace(panel, dlg, calendar) {
    const state = calendarWorkspaceState(dlg);
    clearOperatorPanel(panel);
    panel.classList.add('biggy-calendar-workspace');
    panel.appendChild(operatorHeading('Google Calendar'));

    if (!calendar.connected) {
      appendOperatorRow(panel, 'Biggy local Google authorization is required.', calendar.oauth_ready ? 'OAuth client is ready for account approval.' : 'Biggy needs its profile-scoped Google OAuth connection.', 'warning');
      return;
    }

    const toolbar = document.createElement('div');
    toolbar.className = 'biggy-calendar-toolbar';
    const previous = operatorButton('‹');
    previous.setAttribute('aria-label', 'Previous calendar period');
    const today = operatorButton('Today');
    const next = operatorButton('›');
    next.setAttribute('aria-label', 'Next calendar period');
    const picker = document.createElement('input');
    picker.className = 'biggy-calendar-picker';
    picker.type = state.view === 'day' ? 'date' : 'month';
    picker.value = state.view === 'day' ? state.cursor : state.cursor.slice(0, 7);
    const dayView = operatorButton('Day', state.view === 'day' ? 'primary' : '');
    const monthView = operatorButton('Month', state.view === 'month' ? 'primary' : '');
    const add = operatorButton('Add event', 'primary');
    toolbar.append(previous, today, next, picker, dayView, monthView, add);
    panel.appendChild(toolbar);

    const shift = (amount) => {
      const cursor = calendarLocalDate(state.cursor);
      if (state.view === 'day') cursor.setDate(cursor.getDate() + amount);
      else cursor.setMonth(cursor.getMonth() + amount, 1);
      state.cursor = calendarDateKey(cursor);
      refreshOperatorPanel(dlg, 'calendar');
    };
    previous.addEventListener('click', () => shift(-1));
    next.addEventListener('click', () => shift(1));
    today.addEventListener('click', () => { state.cursor = calendarDateKey(new Date()); refreshOperatorPanel(dlg, 'calendar'); });
    picker.addEventListener('change', () => {
      state.cursor = state.view === 'day' ? picker.value : `${picker.value}-01`;
      refreshOperatorPanel(dlg, 'calendar');
    });
    dayView.addEventListener('click', () => { state.view = 'day'; refreshOperatorPanel(dlg, 'calendar'); });
    monthView.addEventListener('click', () => { state.view = 'month'; refreshOperatorPanel(dlg, 'calendar'); });
    add.addEventListener('click', () => {
      const start = calendarLocalDate(state.cursor);
      start.setHours(9, 0, 0, 0);
      const end = new Date(start);
      end.setHours(10, 0, 0, 0);
      clearOperatorPanel(panel);
      panel.appendChild(operatorHeading('Calendar'));
      appendCalendarForm(panel, dlg, null, { start: start.toISOString(), end: end.toISOString() });
    });

    if (!calendar.write_ready) appendOperatorRow(panel, 'Calendar is currently read-only.', 'Reconnect Google once to enable event creation, editing, and deletion.', 'warning');
    if (calendar.error) appendOperatorRow(panel, 'Calendar refresh failed.', String(calendar.error), 'warning');

    const sourceBar = document.createElement('div');
    sourceBar.className = 'biggy-calendar-sources';
    const sourceTitle = document.createElement('span');
    sourceTitle.className = 'biggy-calendar-sources-title';
    sourceTitle.textContent = 'CALENDAR OVERLAYS';
    sourceBar.appendChild(sourceTitle);
    const sources = Array.isArray(calendar.calendar_sources) ? calendar.calendar_sources : [];
    sources.forEach((source) => {
      const label = document.createElement('label');
      label.className = 'biggy-calendar-source';
      const check = document.createElement('input');
      check.type = 'checkbox';
      check.checked = state.calendarIds.includes(String(source.id));
      check.disabled = !!source.primary;
      const swatch = document.createElement('span');
      swatch.className = 'biggy-calendar-source-swatch';
      swatch.style.backgroundColor = String(source.background_color || '#34d399');
      const name = document.createElement('span');
      name.textContent = String(source.summary || source.id || 'Calendar');
      label.append(check, swatch, name);
      sourceBar.appendChild(label);
      check.addEventListener('change', () => {
        const id = String(source.id || '');
        state.calendarIds = check.checked ? Array.from(new Set([...state.calendarIds, id])) : state.calendarIds.filter((item) => item !== id);
        refreshOperatorPanel(dlg, 'calendar');
      });
    });
    const manage = document.createElement('a');
    manage.className = 'biggy-calendar-manage';
    manage.href = 'https://calendar.google.com/calendar/u/0/r/settings/addbyurl';
    manage.target = '_blank';
    manage.rel = 'noopener noreferrer';
    manage.textContent = 'Add / manage Google calendars ↗';
    sourceBar.appendChild(manage);
    panel.appendChild(sourceBar);
    if (calendar.overlay_error) {
      const warning = document.createElement('div');
      warning.className = 'biggy-calendar-overlay-warning';
      warning.textContent = String(calendar.overlay_error);
      panel.appendChild(warning);
    }

    const events = Array.isArray(calendar.events) ? calendar.events : [];
    if (state.view === 'day') {
      const day = document.createElement('section');
      day.className = 'biggy-calendar-day';
      const heading = document.createElement('div');
      heading.className = 'biggy-calendar-date-heading';
      heading.textContent = calendarLocalDate(state.cursor).toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
      day.appendChild(heading);
      const selected = events.filter((event) => calendarDateKey(event.start) === state.cursor);
      if (!selected.length) appendOperatorRow(day, 'No events scheduled.', 'This day is clear.', 'ready');
      selected.forEach((event) => {
        const row = appendOperatorRow(day, calendarEventLabel(event), `${String(event.calendar_summary || '')}${event.location ? ` · ${event.location}` : ''}`, 'ready');
        if (event.editable && calendar.write_ready) {
          row.classList.add('is-actionable');
          row.addEventListener('click', () => calendarEventEditor(panel, dlg, event, calendar.write_ready));
        }
      });
      panel.appendChild(day);
      return;
    }

    const range = calendarRequestWindow(state);
    const grid = document.createElement('div');
    grid.className = 'biggy-calendar-month';
    ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].forEach((name) => {
      const weekday = document.createElement('div');
      weekday.className = 'biggy-calendar-weekday';
      weekday.textContent = name;
      grid.appendChild(weekday);
    });
    for (let offset = 0; offset < 42; offset += 1) {
      const date = new Date(range.start);
      date.setDate(date.getDate() + offset);
      const key = calendarDateKey(date);
      const cell = document.createElement('div');
      cell.className = 'biggy-calendar-cell';
      if (date.getMonth() !== calendarLocalDate(state.cursor).getMonth()) cell.classList.add('is-adjacent');
      if (key === calendarDateKey(new Date())) cell.classList.add('is-today');
      const number = document.createElement('button');
      number.type = 'button';
      number.className = 'biggy-calendar-day-number';
      number.textContent = String(date.getDate());
      number.addEventListener('click', () => { state.cursor = key; state.view = 'day'; refreshOperatorPanel(dlg, 'calendar'); });
      cell.appendChild(number);
      events.filter((event) => calendarDateKey(event.start) === key).slice(0, 4).forEach((event) => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'biggy-calendar-event';
        chip.textContent = calendarEventLabel(event);
        chip.title = `${String(event.summary || '')}${event.location ? ` · ${event.location}` : ''}`;
        chip.style.borderLeftColor = String(event.calendar_color || '#34d399');
        chip.addEventListener('click', () => {
          if (event.editable && calendar.write_ready) calendarEventEditor(panel, dlg, event, calendar.write_ready);
          else if (event.url) window.open(event.url, '_blank', 'noopener');
        });
        cell.appendChild(chip);
      });
      grid.appendChild(cell);
    }
    panel.appendChild(grid);
  }

  function appendMailComposer(panel, dlg) {
    const form = document.createElement('form');
    form.className = 'biggy-operator-form biggy-mail-form';
    form.appendChild(operatorHeading('New draft'));
    form.appendChild(operatorField('To', 'to', 'email'));
    form.appendChild(operatorField('Cc', 'cc', 'text'));
    form.appendChild(operatorField('Subject', 'subject'));
    form.appendChild(operatorField('Message', 'body', 'textarea'));
    const actions = document.createElement('div');
    actions.className = 'biggy-operator-actions';
    const create = operatorButton('Create draft', 'primary');
    create.type = 'submit';
    actions.appendChild(create);
    form.appendChild(actions);
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const data = new FormData(form);
      create.disabled = true;
      operatorFormStatus(form, 'Creating Gmail draft…', 'loading');
      try {
        const result = await operatorFetch('/api/biggy/pa/mail/draft', {
          method: 'POST',
          body: {
            to: String(data.get('to') || '').trim(),
            cc: String(data.get('cc') || '').trim(),
            subject: String(data.get('subject') || '').trim(),
            body: String(data.get('body') || '').trim(),
          },
        });
        renderMailDraftReview(panel, dlg, result.draft || {});
      } catch (error) {
        operatorFormStatus(form, String(error && error.message || 'Draft creation failed.'), 'warning');
        create.disabled = false;
      }
    });
    panel.appendChild(form);
  }

  function renderMailDraftReview(panel, dlg, draft) {
    clearOperatorPanel(panel);
    panel.appendChild(operatorHeading('Review Gmail draft'));
    appendOperatorRow(panel, String(draft.subject || '(no subject)'), `To: ${String(draft.to || '')}${draft.cc ? ` · Cc: ${draft.cc}` : ''}`, 'warning');
    const body = document.createElement('pre');
    body.className = 'biggy-operator-draft-body';
    body.textContent = String(draft.body || '');
    panel.appendChild(body);
    const note = document.createElement('p');
    note.className = 'biggy-operator-confirm-note';
    note.textContent = 'Nothing has been sent. Review the recipient, subject, and message before confirming.';
    panel.appendChild(note);
    const actions = document.createElement('div');
    actions.className = 'biggy-operator-actions';
    const send = operatorButton('Send email', 'danger');
    const discard = operatorButton('Discard draft');
    const back = operatorButton('Keep draft and return');
    actions.append(send, discard, back);
    panel.appendChild(actions);
    back.addEventListener('click', () => refreshOperatorPanel(dlg, 'mail'));
    send.addEventListener('click', async () => {
      if (!window.confirm(`Send this email to ${String(draft.to || 'the listed recipient')}?`)) return;
      send.disabled = true;
      try {
        await operatorFetch('/api/biggy/pa/mail/send', { method: 'POST', body: { draft_id: draft.id, confirmed: true } });
        operatorMessage(panel, 'Email sent.', 'ready');
      } catch (error) {
        operatorMessage(panel, String(error && error.message || 'Email send failed.'), 'warning');
      }
    });
    discard.addEventListener('click', async () => {
      if (!window.confirm('Discard this Gmail draft?')) return;
      discard.disabled = true;
      try {
        await operatorFetch('/api/biggy/pa/mail/discard', { method: 'POST', body: { draft_id: draft.id, confirmed: true } });
        await refreshOperatorPanel(dlg, 'mail');
      } catch (error) {
        operatorMessage(panel, String(error && error.message || 'Draft discard failed.'), 'warning');
      }
    });
  }

  function notesPanelIsCurrent(dlg) {
    return dlg && dlg.getAttribute('data-active-category') === 'notes';
  }

  function appendNotesResult(panel, dlg, note) {
    const row = appendOperatorRow(
      panel,
      String(note && note.title || 'Untitled note'),
      String(note && (note.snippet || note.updated_time) || ''),
      'ready',
    );
    row.classList.add('is-actionable');
    row.setAttribute('role', 'button');
    row.setAttribute('tabindex', '0');
    row.setAttribute('aria-label', `Open note ${String(note && note.title || 'Untitled note')}`);
    const open = async () => {
      if (row.classList.contains('is-loading')) return;
      row.classList.add('is-loading');
      try {
        const id = encodeURIComponent(String(note && note.id || ''));
        const result = await operatorFetch(`/api/notes/item?source=obsidian&id=${id}`);
        if (!notesPanelIsCurrent(dlg)) return;
        renderNotesEditor(panel, dlg, result.note || result);
      } catch (error) {
        row.classList.remove('is-loading');
        const detail = row.querySelector('.biggy-operator-row-detail');
        if (detail) detail.textContent = String(error && error.message || 'Unable to open note.');
        row.classList.add('is-warning');
      }
    };
    row.addEventListener('click', open);
    row.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      open();
    });
    return row;
  }

  function renderNotesEditor(panel, dlg, note = null) {
    if (!notesPanelIsCurrent(dlg)) return;
    clearOperatorPanel(panel);
    const editing = !!(note && note.id);
    panel.appendChild(operatorHeading(editing ? 'Edit note' : 'New note'));
    const form = document.createElement('form');
    form.className = 'biggy-operator-form biggy-notes-editor';
    form.setAttribute('data-testid', 'biggy-notes-editor');
    form.appendChild(operatorField('Title', 'title', 'text', note && note.title));
    form.appendChild(operatorField('Note', 'body', 'textarea', note && note.body));
    const actions = document.createElement('div');
    actions.className = 'biggy-operator-actions';
    const save = operatorButton('Save note', 'primary');
    save.type = 'submit';
    const back = operatorButton('Back to notes');
    actions.append(save, back);
    if (editing) {
      const remove = operatorButton('Delete note', 'danger');
      actions.appendChild(remove);
      remove.addEventListener('click', async () => {
        if (!window.confirm(`Delete “${String(note.title || 'this note')}”?`)) return;
        remove.disabled = true;
        operatorFormStatus(form, 'Deleting note…', 'loading');
        try {
          await operatorFetch('/api/notes/delete', {
            method: 'POST',
            body: { source: 'obsidian', id: String(note.id), confirmed: true },
          });
          await refreshOperatorPanel(dlg, 'notes');
        } catch (error) {
          remove.disabled = false;
          operatorFormStatus(form, String(error && error.message || 'Delete failed.'), 'warning');
        }
      });
    }
    form.appendChild(actions);
    back.addEventListener('click', () => refreshOperatorPanel(dlg, 'notes'));
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const data = new FormData(form);
      save.disabled = true;
      operatorFormStatus(form, editing ? 'Saving note…' : 'Creating note…', 'loading');
      try {
        const body = {
          source: 'obsidian',
          title: String(data.get('title') || '').trim(),
          body: String(data.get('body') || ''),
        };
        if (editing) body.id = String(note.id);
        const result = await operatorFetch(editing ? '/api/notes/update' : '/api/notes/create', { method: 'POST', body });
        if (!notesPanelIsCurrent(dlg)) return;
        renderNotesEditor(panel, dlg, result.note || result);
        const refreshed = panel.querySelector('.biggy-notes-editor');
        if (refreshed) operatorFormStatus(refreshed, 'Note saved.', 'ready');
      } catch (error) {
        save.disabled = false;
        operatorFormStatus(form, String(error && error.message || 'Save failed.'), 'warning');
      }
    });
    panel.appendChild(form);
  }

  function renderNotesWorkspace(panel, dlg, notes) {
    clearOperatorPanel(panel);
    panel.appendChild(operatorHeading('Notes'));
    if (!notes.enabled) {
      appendOperatorRow(panel, 'Notes source is not connected.', 'Enable the approved PLATO Obsidian vault to use this workspace.', 'warning');
      return;
    }
    const sources = Array.isArray(notes.sources) ? notes.sources : [];
    const obsidian = sources.find((source) => String(source.name || '').toLowerCase() === 'obsidian');
    if (!obsidian) {
      appendOperatorRow(panel, 'Obsidian vault is not connected.', String(notes.obsidian_error || 'Notes remain in the approved PLATO vault; no alternate source will be used.'), 'warning');
      return;
    }
    appendOperatorRow(panel, 'Obsidian vault ready.', `${String(obsidian.vault_name || 'Biggy Notes')} on PLATO is available.`, 'ready');
    const homeActions = document.createElement('div');
    homeActions.className = 'biggy-operator-actions biggy-notes-home-actions';
    const create = operatorButton('New note', 'primary');
    create.setAttribute('data-testid', 'biggy-notes-new');
    homeActions.appendChild(create);
    panel.appendChild(homeActions);
    create.addEventListener('click', () => renderNotesEditor(panel, dlg));

    const search = document.createElement('form');
    search.className = 'biggy-operator-form biggy-notes-search';
    search.setAttribute('data-testid', 'biggy-notes-search');
    search.appendChild(operatorHeading('Search notes'));
    search.appendChild(operatorField('Keywords', 'query', 'search'));
    const searchActions = document.createElement('div');
    searchActions.className = 'biggy-operator-actions';
    const submit = operatorButton('Search', 'primary');
    submit.type = 'submit';
    searchActions.appendChild(submit);
    search.appendChild(searchActions);
    panel.appendChild(search);

    const results = document.createElement('div');
    results.className = 'biggy-notes-results';
    results.setAttribute('data-testid', 'biggy-notes-results');
    panel.appendChild(results);
    search.addEventListener('submit', async (event) => {
      event.preventDefault();
      const query = String(new FormData(search).get('query') || '').trim();
      if (!query) {
        operatorFormStatus(search, 'Enter one or more search terms.', 'warning');
        return;
      }
      submit.disabled = true;
      operatorFormStatus(search, 'Searching Obsidian…', 'loading');
      results.replaceChildren();
      try {
        const found = await operatorFetch(`/api/notes/search?source=obsidian&q=${encodeURIComponent(query)}`);
        if (!notesPanelIsCurrent(dlg)) return;
        operatorFormStatus(search, '', '');
        results.appendChild(operatorHeading('Search results'));
        const items = Array.isArray(found.results) ? found.results : [];
        if (!items.length) appendOperatorRow(results, 'No matching notes.', 'Try another title or phrase.', 'muted');
        items.slice(0, 30).forEach((item) => appendNotesResult(results, dlg, item));
      } catch (error) {
        operatorFormStatus(search, String(error && error.message || 'Search failed.'), 'warning');
      } finally {
        submit.disabled = false;
      }
    });

    results.appendChild(operatorHeading('Recent notes'));
    const recent = Array.isArray(notes.recent_ai_notes) ? notes.recent_ai_notes.slice(0, 10) : [];
    if (!recent.length) appendOperatorRow(results, 'No recent notes returned.', 'Create a note or search the Obsidian vault.', 'muted');
    recent.forEach((note) => appendNotesResult(results, dlg, note));
  }

  async function refreshOperatorPanel(dlg, key) {
    const panel = operatorPanel(dlg, key);
    if (!panel) return;
    const current = () => dlg.getAttribute('data-active-category') === key;
    operatorMessage(panel, 'Loading local status…', 'loading');
    try {
      if (key === 'mail') {
        const mail = await operatorFetch('/api/biggy/pa/mail');
        if (!current()) return;
        clearOperatorPanel(panel);
        panel.appendChild(operatorHeading('Mail'));
        if (!mail.connected) {
          appendOperatorRow(panel, 'Biggy local Google authorization is required.', mail.oauth_ready ? 'OAuth client is ready for account approval.' : 'Codex plugins are connected; Biggy still needs its own profile-scoped OAuth client.', 'warning');
          return;
        }
        if (mail.write_ready) {
          appendMailComposer(panel, dlg);
        } else {
          appendOperatorRow(panel, 'Mail is currently read-only.', 'Reconnect Google once to enable Gmail drafts and confirmed sending.', 'warning');
        }
        if (mail.error) appendOperatorRow(panel, 'Mail refresh failed.', String(mail.error), 'warning');
        const drafts = Array.isArray(mail.drafts) ? mail.drafts : [];
        if (drafts.length) {
          panel.appendChild(operatorHeading('Saved drafts'));
          drafts.slice(0, 5).forEach((draft) => appendOperatorRow(panel, String(draft.subject || '(no subject)'), `DRAFT · To: ${String(draft.to || '')}${draft.snippet ? ` · ${draft.snippet}` : ''}`, 'warning'));
        }
        panel.appendChild(operatorHeading('Recent inbox'));
        const messages = Array.isArray(mail.messages) ? mail.messages : [];
        if (!messages.length && !mail.error) appendOperatorRow(panel, 'Inbox clear.', 'No recent inbox messages returned.', 'ready');
        messages.slice(0, 10).forEach((message) => appendOperatorRow(panel, String(message.subject || '(no subject)'), `${message.unread ? 'UNREAD · ' : ''}${String(message.from || '')}${message.date ? ` · ${message.date}` : ''}`, message.unread ? 'warning' : 'ready'));
        return;
      }
      if (key === 'phone') {
        const phone = await operatorFetch('/api/biggy/phone/status');
        if (!current()) return;
        await renderPhoneWorkspace(panel, dlg, phone);
        return;
      }
      if (key === 'calendar') {
        const state = calendarWorkspaceState(dlg);
        const calendar = await operatorFetch(calendarRequestUrl(state));
        if (!current()) return;
        renderCalendarWorkspace(panel, dlg, calendar);
        return;
      }
      if (key === 'tasks') {
        const board = await operatorFetch('/api/kanban/board?board=fleet-coordination');
        if (!current()) return;
        clearOperatorPanel(panel);
        panel.appendChild(operatorHeading('Fleet coordination'));
        const columns = Array.isArray(board.columns) ? board.columns : [];
        const active = columns.filter((column) => !['done', 'archived'].includes(String(column.name || '').toLowerCase()));
        let shown = 0;
        active.forEach((column) => {
          (Array.isArray(column.tasks) ? column.tasks : []).slice(0, 4).forEach((task) => {
            shown += 1;
            appendOperatorRow(
              panel,
              String(task.title || 'Untitled task'),
              `${String(column.name || 'ready').toUpperCase()}${task.assignee ? ` · ${task.assignee}` : ''}`,
              String(column.name || '').toLowerCase() === 'blocked' ? 'warning' : 'ready',
            );
          });
        });
        if (!shown) appendOperatorRow(panel, 'No open fleet tasks.', 'The coordination board is clear.', 'ready');
        return;
      }
      if (key === 'notes') {
        const notes = await operatorFetch('/api/notes/sources');
        if (!current()) return;
        renderNotesWorkspace(panel, dlg, notes);
        return;
      }
      if (key === 'alerts') {
        const [ingest, fleet] = await Promise.all([
          operatorFetch('/api/biggy/v6/world/status'),
          operatorFetch('/api/biggy/fleet/status'),
        ]);
        if (!current()) return;
        clearOperatorPanel(panel);
        panel.appendChild(operatorHeading('Operational alerts'));
        const ingestState = String(ingest.state || 'unknown').replace(/_/g, ' ');
        const issue = String(ingest.last_error || '').trim();
        appendOperatorRow(
          panel,
          `ARGUS ingest: ${ingestState}`,
          issue || `Latency ${Math.round(Number(ingest.latency_ms || 0))} ms`,
          issue || ingestState === 'error' ? 'warning' : 'ready',
        );
        const machines = Array.isArray(fleet.machines) ? fleet.machines : [];
        machines.forEach((machine) => {
          const state = String(machine.state || 'unknown');
          appendOperatorRow(panel, `${machine.label || machine.id}: ${state}`, String(machine.detail || machine.worker_state || ''), state === 'error' || state === 'offline' ? 'warning' : 'ready');
        });
        return;
      }
    } catch (error) {
      if (current()) operatorMessage(panel, `Unable to load this local status: ${String(error && error.message || 'unknown error')}`, 'warning');
    }
  }

  function ensureTravelMapDialog() {
    // Persistent category rail + docked open panel in unused landing space.
    // Never shrinks conversation viewport; never displaces brand header/composer.
    let dlg = document.getElementById('biggyTravelMapDialog');
    if (dlg) {
      mountTravelRailInWorkspace(dlg);
      return dlg;
    }
    const mainChat = document.getElementById('mainChat');
    if (!mainChat) return null;
    const legacy = document.getElementById('biggyTravelCenterPanelSlot');
    if (legacy && legacy.parentNode) legacy.parentNode.removeChild(legacy);

    dlg = el('aside', 'biggy-travel-dock is-collapsed');
    dlg.id = 'biggyTravelMapDialog';
    dlg.setAttribute('data-testid', 'biggy-travel-map');
    dlg.setAttribute('data-layout-slot', 'docked_landing_panel');
    dlg.setAttribute('data-displaces-conversation', 'false');
    dlg.setAttribute('aria-label', 'Travel category rail');
    dlg.setAttribute('data-open-panel-scale', 'workspace');
    dlg.style.setProperty('--biggy-travel-dock-width', 'min(38vw, 720px)');
    // Rail stays visible; panel opens on category select / travel content.
    dlg.hidden = false;
    const railBtns = TRAVEL_CATEGORIES.map((label) => {
      const key = railCategoryKey(label);
      return (
        `<button type="button" class="biggy-category-rail-btn" data-category="${key}"` +
        ` id="biggyCatRail-${key}" title="${label}" aria-pressed="false">${label}</button>`
      );
    }).join('');
    dlg.innerHTML =
      `<nav class="biggy-category-rail" id="biggyCategoryRail" aria-label="Travel categories">${railBtns}</nav>` +
      `<div class="biggy-travel-panel" id="biggyTravelPanel">` +
      `<div class="biggy-travel-dock-resize" id="biggyTravelDockResize" title="Resize" aria-hidden="true"></div>` +
      `<div class="biggy-travel-map-chrome">` +
      `<button type="button" id="biggyTravelDockCollapse" class="biggy-travel-dock-collapse" title="Collapse panel" aria-expanded="false">⟩</button>` +
      `<div class="biggy-travel-map-title" id="biggyTravelPanelTitle">Travel</div>` +
      `<div class="biggy-travel-map-meta" id="biggyTravelMapMeta"></div>` +
      `<button type="button" id="biggyTravelMapClose" class="biggy-travel-map-close" title="Close panel">×</button>` +
      `</div>` +
      `<div class="biggy-travel-dock-body" id="biggyTravelDockBody">` +
      `<div id="biggyTravelMapCanvas" class="biggy-travel-map-canvas" role="img" aria-label="Route map"></div>` +
      `<div class="biggy-travel-map-actions" id="biggyTravelMapActions"></div>` +
      `<div class="biggy-travel-lodging" id="biggyTravelLodging" hidden>` +
      `<div class="biggy-travel-lodging-title" id="biggyTravelRecTitle">Options</div>` +
      `<div class="biggy-travel-lodging-cards" id="biggyTravelLodgingCards"></div>` +
      `<div class="biggy-travel-lodging-note" id="biggyTravelLodgingNote"></div>` +
      `</div>` +
      `<div class="biggy-travel-map-note" id="biggyTravelMapNote"></div>` +
      `<section class="biggy-weather-state" id="biggyWeatherState" hidden>` +
      `<form class="biggy-weather-zip-form" id="biggyWeatherZipForm">` +
      `<label for="biggyWeatherZip">Weather ZIP</label>` +
      `<input id="biggyWeatherZip" name="zip" inputmode="numeric" autocomplete="postal-code" maxlength="5" pattern="[0-9]{5}" value="${savedWeatherZip()}" aria-label="Weather ZIP code">` +
      `<button type="submit">Load forecast</button>` +
      `<a class="biggy-weather-radar-link" id="biggyWeatherRadarLink" href="myradar://open" data-testid="biggy-weather-myradar-primary" title="Open MyRadar on this device">Open MyRadar</a>` +
      `</form>` +
      `<div class="biggy-weather-current" id="biggyWeatherCurrent"></div>` +
      `<div class="biggy-weather-forecast" id="biggyWeatherForecast"></div>` +
      `<div class="biggy-weather-status" id="biggyWeatherStatus">Forecast has not been loaded yet.</div>` +
      `</section>` +
      `<section class="biggy-galaxy-filter-state" id="biggyGalaxyFilterState" hidden>` +
      `<div class="biggy-galaxy-filter-status" id="biggyGalaxyFilterStatus">Full galaxy · centered on BIGGY PROMPT</div>` +
      `<div class="biggy-galaxy-filter-tree" id="biggyGalaxyFilterTree" role="tree" aria-label="RAG directory tree"></div>` +
      `</section>` +
      `<div class="biggy-operator-state" id="biggyOperatorState" hidden>` +
      `<div class="biggy-operator-panel" data-biggy-operator-panel="phone" hidden></div>` +
      `<div class="biggy-operator-panel" data-biggy-operator-panel="calendar" hidden></div>` +
      `<div class="biggy-operator-panel" data-biggy-operator-panel="mail" hidden></div>` +
      `<div class="biggy-operator-panel" data-biggy-operator-panel="tasks" hidden></div>` +
      `<div class="biggy-operator-panel" data-biggy-operator-panel="notes" hidden></div>` +
      `<div class="biggy-operator-panel" data-biggy-operator-panel="alerts" hidden></div>` +
      `</div>` +
      `<div class="biggy-travel-empty-cat" id="biggyTravelEmptyCat" hidden>No options loaded for this category yet.</div>` +
      `</div>` +
      `</div>`;
    mainChat.appendChild(dlg);
    mountTravelRailInWorkspace(dlg);

    const setCollapsed = (collapsed) => {
      dlg.classList.toggle('is-collapsed', !!collapsed);
      const collapseBtn = dlg.querySelector('#biggyTravelDockCollapse');
      if (collapseBtn) collapseBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      if (!collapsed) {
        try { if (mapInstance) mapInstance.resize(); } catch (_) {}
      }
    };
    dlg.__biggySetCollapsed = setCollapsed;
    const categoryButtons = () => {
      const rail = document.getElementById('biggyCategoryRail');
      return rail ? rail.querySelectorAll('.biggy-category-rail-btn[data-category]') : [];
    };

    const setActiveCategory = (category, { open = true } = {}) => {
      const key = mapRecCategoryToRail(category);
      dlg.setAttribute('data-active-category', key);
      categoryButtons().forEach((btn) => {
        const on = btn.getAttribute('data-category') === key;
        btn.classList.toggle('is-active', on);
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
      const titleEl = dlg.querySelector('#biggyTravelPanelTitle');
      if (titleEl) {
        titleEl.textContent = TRAVEL_CATEGORIES.find((x) => railCategoryKey(x) === key) || 'Travel';
      }
      const mapCanvas = dlg.querySelector('#biggyTravelMapCanvas');
      const mapActions = dlg.querySelector('#biggyTravelMapActions');
      const mapNote = dlg.querySelector('#biggyTravelMapNote');
      const lodging = dlg.querySelector('#biggyTravelLodging');
      const operatorState = dlg.querySelector('#biggyOperatorState');
      const weatherState = dlg.querySelector('#biggyWeatherState');
      const filterState = dlg.querySelector('#biggyGalaxyFilterState');
      const empty = dlg.querySelector('#biggyTravelEmptyCat');
      const showTravel = key === 'travel';
      const showWeather = key === 'weather';
      const showFilter = key === 'filter';
      const showOperator = ['phone', 'calendar', 'mail', 'tasks', 'notes', 'alerts'].includes(key);
      const recommendationKey = lodging
        ? mapRecCategoryToRail(lodging.getAttribute('data-rec-category') || '')
        : '';
      const showRecommendation = !!(
        lodging && !showTravel && !showWeather && !showFilter && key === recommendationKey &&
        lodging.getAttribute('data-has-cards') === '1'
      );
      if (mapCanvas) mapCanvas.hidden = !showTravel;
      if (mapActions) mapActions.hidden = !showTravel;
      if (mapNote) mapNote.hidden = !showTravel;
      if (weatherState) weatherState.hidden = !showWeather;
      if (filterState) filterState.hidden = !showFilter;
      if (lodging) {
        lodging.hidden = !showRecommendation;
      }
      if (operatorState) {
        operatorState.hidden = !showOperator;
        operatorState.querySelectorAll('[data-biggy-operator-panel]').forEach((panel) => {
          panel.hidden = panel.getAttribute('data-biggy-operator-panel') !== key;
        });
      }
      if (empty) {
        empty.hidden = showTravel || showWeather || showFilter || showRecommendation || showOperator;
      }
      if (open) {
        dlg.hidden = false;
        setCollapsed(false);
      }
    };
    dlg.__biggySetActiveCategory = setActiveCategory;

    categoryButtons().forEach((btn) => {
      btn.addEventListener('click', (ev) => {
        ev.preventDefault();
        const key = btn.getAttribute('data-category') || 'travel';
        if (!dlg.classList.contains('is-collapsed') && dlg.getAttribute('data-active-category') === key) {
          setCollapsed(true);
          return;
        }
        const cachedRecommendation = recommendationModelsByCategory[key];
        if (cachedRecommendation && key !== 'travel' && key !== 'weather' && key !== 'filter') {
          renderRecommendationViewModel(cachedRecommendation);
          return;
        }
        setActiveCategory(key, { open: true });
        if (key === 'filter') refreshGalaxyFilterPanel(dlg);
        if (key === 'weather') refreshWeatherPanel(dlg, savedWeatherZip());
        if (['phone', 'calendar', 'mail', 'tasks', 'notes', 'alerts'].includes(key)) refreshOperatorPanel(dlg, key);
      });
    });

    const weatherForm = dlg.querySelector('#biggyWeatherZipForm');
    if (weatherForm) {
      weatherForm.addEventListener('submit', (ev) => {
        ev.preventDefault();
        const input = weatherForm.querySelector('#biggyWeatherZip');
        const zipCode = input && String(input.value || '').trim();
        if (!/^\d{5}$/.test(zipCode)) {
          renderWeatherPanel(dlg, { ok: false, zip: zipCode || BIGGY_DEFAULT_WEATHER_ZIP, error: 'Enter a five-digit ZIP code.' });
          return;
        }
        refreshWeatherPanel(dlg, zipCode);
      });
    }

    const closeBtn = dlg.querySelector('#biggyTravelMapClose');
    if (closeBtn) {
      closeBtn.addEventListener('click', (ev) => {
        ev.preventDefault();
        setCollapsed(true);
      });
    }
    const collapseBtn = dlg.querySelector('#biggyTravelDockCollapse');
    if (collapseBtn) {
      collapseBtn.addEventListener('click', (ev) => {
        ev.preventDefault();
        setCollapsed(true);
      });
    }
    const handle = dlg.querySelector('#biggyTravelDockResize');
    if (handle) {
      let dragging = false;
      let startX = 0;
      let startW = 0;
      handle.addEventListener('pointerdown', (ev) => {
        if (dlg.classList.contains('is-collapsed')) return;
        dragging = true;
        startX = ev.clientX;
        const panel = dlg.querySelector('#biggyTravelPanel');
        startW = panel ? panel.getBoundingClientRect().width : 720;
        handle.setPointerCapture(ev.pointerId);
        ev.preventDefault();
      });
      handle.addEventListener('pointermove', (ev) => {
        if (!dragging) return;
        const dx = startX - ev.clientX;
        const next = Math.max(480, Math.min(860, startW + dx));
        dlg.style.setProperty('--biggy-travel-dock-width', next + 'px');
        try { if (mapInstance) mapInstance.resize(); } catch (_) {}
      });
      handle.addEventListener('pointerup', () => { dragging = false; });
      handle.addEventListener('pointercancel', () => { dragging = false; });
    }
    setActiveCategory('travel', { open: false });
    return dlg;
  }

  // Categories are Biggy-level navigation.  Keep this rail exposed as the top
  // layer of the collapsed right sidebar, mirroring Hermes's left navigation;
  // category content itself continues to open only on demand.
  function mountTravelRailInWorkspace(dlg) {
    const rail = dlg && dlg.querySelector('#biggyCategoryRail');
    const mainChat = document.getElementById('mainChat');
    if (!rail || !mainChat) return;
    if (rail.parentElement !== mainChat) mainChat.appendChild(rail);
    const filter = rail.querySelector('[data-category="filter"]');
    if (filter) filter.hidden = true;
  }

  function hideTravelMap() {
    const dlg = document.getElementById('biggyTravelMapDialog');
    if (dlg) {
      // Keep persistent rail; only collapse the open panel.
      if (typeof dlg.__biggySetCollapsed === 'function') dlg.__biggySetCollapsed(true);
      else dlg.classList.add('is-collapsed');
    }
    releaseTravelMap();
  }

  // Incremented whenever a non-travel result takes visual ownership.  Mapbox
  // initialization is asynchronous; without this generation check an older
  // travel request can finish later and reopen its panel over a RAG result.
  let travelVisualEpoch = 0;

  function invalidateTravelVisuals() {
    travelVisualEpoch += 1;
    lastMapModelKey = '';
    hideTravelMap();
    return travelVisualEpoch;
  }

  function modelKey(mvm) {
    try {
      const o = mvm && mvm.origin;
      const d = mvm && mvm.destination;
      return [o && o.lat, o && o.lon, d && d.lat, d && d.lon, mvm && mvm.route && (mvm.route.distance_mi != null ? mvm.route.distance_mi : mvm.route.distance_km)].join('|');
    } catch (_) {
      return String(Date.now());
    }
  }

  async function fetchMapboxToken() {
    const resp = await fetch(MAP_CONFIG_URL, { credentials: 'same-origin' });
    if (!resp.ok) return { available: false, reason: 'HTTP_' + resp.status };
    const cfg = await resp.json();
    return cfg && typeof cfg === 'object' ? cfg : { available: false, reason: 'BAD_CONFIG' };
  }

  async function renderMapViewModelOnce(mvm) {
    if (!mvm || typeof mvm !== 'object') return false;
    const renderEpoch = travelVisualEpoch;
    if (mvm.available === false) {
      const dlg = ensureTravelMapDialog();
      if (!dlg) return;
      dlg.hidden = false;
      if (typeof dlg.__biggySetActiveCategory === 'function') {
        dlg.__biggySetActiveCategory('travel', { open: true });
      }
      const note = dlg.querySelector('#biggyTravelMapNote');
      if (note) note.textContent = 'Map unavailable: ' + String(mvm.reason || 'no route model');
      return false;
    }
    if (mvm.schema !== 'jarvis.map_view_model.v1' ||
        (mvm.emitted_by !== '3 AI Agent' && mvm.emitted_by !== 'Jarvis II PA Tool')) {
      return false; // refuse untrusted map models
    }
    const dlg = ensureTravelMapDialog();
    if (!dlg) return false;
    dlg.hidden = false;
    if (typeof dlg.__biggySetActiveCategory === 'function') {
      dlg.__biggySetActiveCategory('travel', { open: true });
    } else if (typeof dlg.__biggySetCollapsed === 'function') {
      dlg.__biggySetCollapsed(false);
    }
    const meta = dlg.querySelector('#biggyTravelMapMeta');
    const note = dlg.querySelector('#biggyTravelMapNote');
    const actions = dlg.querySelector('#biggyTravelMapActions');
    const canvas = dlg.querySelector('#biggyTravelMapCanvas');
    const o = mvm.origin || {};
    const d = mvm.destination || {};
    if (meta) {
      meta.textContent =
        String(o.label || 'Origin').slice(0, 48) +
        ' → ' +
        String(d.label || 'Destination').slice(0, 48) +
        (function () {
          const r = mvm.route || {};
          let mi = r.distance_mi;
          if (mi == null && r.distance_km != null) mi = Math.round(Number(r.distance_km) * 0.621371 * 10) / 10;
          if (mi == null && r.distance_m != null) mi = Math.round((Number(r.distance_m) / 1609.344) * 10) / 10;
          return mi != null ? ` · ${mi} mi / ${r.duration_min} min` : '';
        })();
    }
    if (actions) {
      actions.innerHTML = '';
      actions.setAttribute('data-action-category', 'travel');
      const nav = mvm.navigation || {};
      // Optional buttons from model only — public O/D params; no auto-launch.
      if (nav.waze_url) {
        const a = document.createElement('a');
        a.className = 'biggy-travel-nav-btn';
        a.href = String(nav.waze_url);
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.textContent = 'Send to Waze';
        a.setAttribute('data-testid', 'biggy-nav-waze');
        actions.appendChild(a);
      }
      if (nav.google_maps_url) {
        const a = document.createElement('a');
        a.className = 'biggy-travel-nav-btn';
        a.href = String(nav.google_maps_url);
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.textContent = 'Open in Google Maps';
        a.setAttribute('data-testid', 'biggy-nav-gmaps');
        actions.appendChild(a);
      }
    }
    const key = modelKey(mvm);
    if (key === lastMapModelKey && mapInstance) {
      if (note) note.textContent = 'Display only · Agent map_view_model';
      return true;
    }
    lastMapModelKey = key;
    setGalaxyRenderPaused(true);

    let cfg;
    try {
      cfg = await fetchMapboxToken();
    } catch (_) {
      cfg = { available: false, reason: 'CONFIG_FETCH_FAILED' };
    }
    if (renderEpoch !== travelVisualEpoch) return false;
    if (!cfg.available || !cfg.token) {
      if (note) {
        note.textContent =
          'Mapbox unavailable (' +
          String(cfg.reason || 'token') +
          '). Config var: ' +
          String(cfg.token_env || 'BIGGY_MAPBOX_PUBLIC_TOKEN');
      }
      setGalaxyRenderPaused(false);
      return false;
    }
    try {
      const mapboxgl = await loadMapboxAssets();
      if (renderEpoch !== travelVisualEpoch) return false;
      if (!mapboxgl) throw new Error('mapboxgl_missing');
      mapboxgl.accessToken = cfg.token;
      if (mapInstance) {
        try { mapInstance.remove(); } catch (_) {}
        mapInstance = null;
      }
      if (canvas) canvas.innerHTML = '';
      mapInstance = new mapboxgl.Map({
        container: canvas,
        style: 'mapbox://styles/mapbox/streets-v12',
        center: [Number(o.lon) || 0, Number(o.lat) || 0],
        zoom: 11,
        attributionControl: true,
      });
      mapInstance.addControl(new mapboxgl.NavigationControl({ showCompass: false }), 'top-right');
      await new Promise((resolve, reject) => {
        const timeout = window.setTimeout(() => reject(new Error('mapbox_load_timeout')), 12000);
        mapInstance.once('error', (event) => {
          window.clearTimeout(timeout);
          reject(new Error(String(event && event.error && event.error.message || 'mapbox_load_error')));
        });
        mapInstance.once('load', () => {
          window.clearTimeout(timeout);
          try {
            const geom = mvm.route && mvm.route.geometry;
            if (geom && geom.type === 'LineString' && Array.isArray(geom.coordinates)) {
              mapInstance.addSource('route', {
                type: 'geojson',
                data: { type: 'Feature', properties: {}, geometry: geom },
              });
              mapInstance.addLayer({
                id: 'route-line',
                type: 'line',
                source: 'route',
                layout: { 'line-join': 'round', 'line-cap': 'round' },
                paint: { 'line-color': '#2f6fed', 'line-width': 5 },
              });
              const bounds = new mapboxgl.LngLatBounds();
              geom.coordinates.forEach((c) => bounds.extend(c));
              if (o.lon != null && o.lat != null) bounds.extend([o.lon, o.lat]);
              if (d.lon != null && d.lat != null) bounds.extend([d.lon, d.lat]);
              mapInstance.fitBounds(bounds, { padding: 48, maxZoom: 14 });
            }
            if (o.lon != null && o.lat != null) {
              new mapboxgl.Marker({ color: '#1a7f37' })
                .setLngLat([o.lon, o.lat])
                .setPopup(new mapboxgl.Popup().setText(String(o.label || 'Origin')))
                .addTo(mapInstance);
            }
            if (d.lon != null && d.lat != null) {
              new mapboxgl.Marker({ color: '#cf222e' })
                .setLngLat([d.lon, d.lat])
                .setPopup(new mapboxgl.Popup().setText(String(d.label || 'Destination')))
                .addTo(mapInstance);
            }
            resolve(true);
          } catch (_) {
            resolve(false);
          }
        });
      });
      if (renderEpoch !== travelVisualEpoch) {
        releaseTravelMap();
        return false;
      }
      if (note) note.textContent = 'Display only · Agent map_view_model · not a decision-maker';
      // Mapbox and Three.js compete during WebGL initialization only. Resume
      // the galaxy as soon as the map is ready, even while its panel is open.
      setGalaxyRenderPaused(false);
      return true;
    } catch (err) {
      releaseTravelMap();
      if (note) note.textContent = 'Mapbox render failed: ' + String(err && err.message || err);
      return false;
    }
  }

  function renderMapViewModel(mvm) {
    if (mapRenderPromise) return mapRenderPromise;
    mapRenderPromise = renderMapViewModelOnce(mvm).finally(() => {
      mapRenderPromise = null;
    });
    return mapRenderPromise;
  }

  window.__biggyRenderMapViewModel = renderMapViewModel;

  // The response that produced a document result owns this transition.  Apply
  // its receipt directly instead of waiting for a later session scan that can
  // race stale travel hydration or select an older assistant turn.
  window.__biggyHandleDocumentResult = function handleDocumentResult(payload) {
    invalidateTravelVisuals();
    clearRagTrace();
    const citation = galaxyTraceCitation(payload);
    const tracePayload = payload && (payload.retrieval_receipt || payload.active_document)
      ? payload
      : { ...(payload || {}), retrieval_receipt: citation };
    traceFromRagPayload(tracePayload);
  };

  function safeLodgingHref(url) {
    const s = String(url || '').trim();
    if (!/^https:\/\//i.test(s)) return null;
    if (/^(https:\/\/)(localhost|127\.|0\.0\.0\.0|10\.|192\.168\.|172\.(1[6-9]|2\d|3[0-1])\.|\[::1\])/i.test(s)) {
      return null;
    }
    if (/[<>"']|javascript:/i.test(s)) return null;
    return s;
  }

  function safeRecommendationHref(opt) {
    if (!opt || typeof opt !== 'object') return null;
    const address = String(opt.address || '').trim();
    if (address) {
      return 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(address);
    }
    const safe = safeLodgingHref(opt.url || opt.directions_url);
    if (!safe) return null;
    try {
      const parsed = new URL(safe);
      if (!/(^|\.)google\.[a-z.]+$/i.test(parsed.hostname)) return safe;
      const key = parsed.searchParams.has('query') ? 'query'
        : (parsed.searchParams.has('destination') ? 'destination' : '');
      if (!key) return safe;
      const raw = String(parsed.searchParams.get(key) || '').trim();
      const match = raw.match(/^(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)$/);
      if (!match) return safe;
      const first = Number(match[1]);
      const second = Number(match[2]);
      // Mapbox payloads historically emitted longitude,latitude. Only swap
      // when the first value cannot be a latitude and the second can, which
      // avoids guessing for valid latitude,longitude coordinates.
      if (Math.abs(first) > 90 && Math.abs(first) <= 180 && Math.abs(second) <= 90) {
        parsed.searchParams.set(key, `${second},${first}`);
        return parsed.toString();
      }
    } catch (_) {}
    return safe;
  }

  function ensureTravelRecommendationSection(dlg) {
    if (!dlg) return null;
    let section = dlg.querySelector('#biggyTravelLodging') || dlg.querySelector('#biggyTravelRecommendations');
    if (section) return section;
    // Migrate in place — never destroy an existing map canvas/dialog.
    section = el('div', 'biggy-travel-lodging');
    section.id = 'biggyTravelRecommendations';
    section.hidden = true;
    section.innerHTML =
      `<div class="biggy-travel-lodging-title" id="biggyTravelRecTitle">Recommendations</div>` +
      `<div class="biggy-travel-lodging-cards" id="biggyTravelLodgingCards"></div>` +
      `<div class="biggy-travel-lodging-note" id="biggyTravelLodgingNote"></div>`;
    const note = dlg.querySelector('#biggyTravelMapNote');
    if (note && note.parentNode === dlg) dlg.insertBefore(section, note);
    else dlg.appendChild(section);
    return section;
  }

  function postRenderAck(payload) {
    try {
      const corr = String((payload && payload.correlation_id) || window.__askJarvisActiveCorrelation || '');
      if (!corr) return;
      const body = Object.assign({}, payload || {}, {
        schema: 'jarvis.ask_jarvis_render_ack.v1',
        correlation_id: corr,
        client: 'biggy_owner_webui',
      });
      window.__askJarvisLastRenderAck = body;
      fetch('/api/biggy/ask-jarvis-render-ack', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).catch(function () {});
    } catch (_) {}
  }
  window.__biggyPostAskJarvisRenderAck = postRenderAck;

  const recommendationModelsByCategory = Object.create(null);

  function renderRecommendationViewModel(rvm) {
    if (!rvm || typeof rvm !== 'object') return { rendered: false, count: 0, category: null };
    const okSchema =
      (rvm.schema === 'jarvis.recommendation_view_model.v1' ||
        rvm.schema === 'jarvis.lodging_view_model.v1') &&
      (rvm.emitted_by === '3 AI Agent' || rvm.emitted_by === 'Jarvis II PA Tool');
    if (!okSchema) return { rendered: false, count: 0, category: null };
    const category = String(rvm.category || (rvm.schema === 'jarvis.lodging_view_model.v1' ? 'lodging' : '') || '');
    if (category) recommendationModelsByCategory[mapRecCategoryToRail(category)] = rvm;
    const title =
      String(rvm.title || '').trim() ||
      (category === 'steakhouse'
        ? 'Steak houses'
        : category === 'lodging'
          ? 'Lodging options'
          : category === 'restaurant'
            ? 'Restaurants'
            : 'Recommendations');
    const dlg = ensureTravelMapDialog();
    if (!dlg) return { rendered: false, count: 0, category };
    const section = ensureTravelRecommendationSection(dlg);
    if (!section) return { rendered: false, count: 0, category };
    const cards = section.querySelector('#biggyTravelLodgingCards');
    const note = section.querySelector('#biggyTravelLodgingNote');
    const titleEl = section.querySelector('#biggyTravelRecTitle') || section.querySelector('.biggy-travel-lodging-title');
    if (!cards) return { rendered: false, count: 0, category };
    if (titleEl) titleEl.textContent = title;
    dlg.hidden = false;
    dlg.classList.add('has-lodging');
    dlg.setAttribute('data-rec-category', category || '');
    const railKey = mapRecCategoryToRail(category || 'lodging');
    section.setAttribute('data-rec-category', railKey);
    if (rvm.available === false) {
      section.hidden = false;
      section.setAttribute('data-has-cards', '0');
      cards.innerHTML = '';
      if (note) {
        note.textContent =
          title + ' unavailable: ' + String(rvm.reason || 'no reliable public options');
      }
      if (typeof dlg.__biggySetActiveCategory === 'function') {
        dlg.__biggySetActiveCategory(railKey, { open: true });
      }
      return { rendered: false, count: 0, category };
    }
    const options = Array.isArray(rvm.options) ? rvm.options : [];
    cards.innerHTML = '';
    let rendered = 0;
    options.slice(0, 5).forEach((opt) => {
      if (!opt || typeof opt !== 'object') return;
      const href = safeRecommendationHref(opt);
      if (!href) return;
      // Never show lodging-titled cards under a non-lodging category.
      if (category && category !== 'lodging') {
        const nm = String(opt.name || '');
        if (/\b(hotel|motel|lodging|inn)\b/i.test(nm) && !/\b(steak|grill|restaurant|dining)\b/i.test(nm)) {
          return;
        }
      }
      const card = el('a', 'biggy-lodging-card');
      card.href = href;
      card.target = '_blank';
      card.rel = 'noopener noreferrer';
      card.setAttribute('data-testid', 'biggy-recommendation-card');
      card.setAttribute('data-rec-category', category || '');
      const name = el('div', 'biggy-lodging-card-name');
      name.textContent = String(opt.name || title.slice(0, -1) || 'Option').slice(0, 96);
      const cue = el('div', 'biggy-lodging-card-cue');
      cue.textContent = String(opt.cue || 'Public listing').slice(0, 140);
      const src = el('div', 'biggy-lodging-card-source');
      src.textContent = String(opt.source_host || 'public source').slice(0, 80);
      card.appendChild(name);
      card.appendChild(cue);
      card.appendChild(src);
      cards.appendChild(card);
      rendered += 1;
    });
    section.hidden = rendered === 0;
    section.setAttribute('data-has-cards', rendered > 0 ? '1' : '0');
    if (note) {
      note.textContent =
        rendered > 0
          ? 'Display only · Agent recommendation_view_model · no booking/rates'
          : 'No safe public links to show';
    }
    if (typeof dlg.__biggySetActiveCategory === 'function') {
      // Prefer recommendation category after cards land; Travel remains on the rail.
      dlg.__biggySetActiveCategory(railKey, { open: true });
    } else if (typeof dlg.__biggySetCollapsed === 'function') {
      dlg.__biggySetCollapsed(false);
    }
    return { rendered: rendered > 0, count: rendered, category };
  }

  function renderLodgingViewModel(lvm) {
    // Back-compat: lodging schema only when category is lodging.
    if (!lvm || typeof lvm !== 'object') return { rendered: false, count: 0, category: 'lodging' };
    if (lvm.schema === 'jarvis.recommendation_view_model.v1') {
      return renderRecommendationViewModel(lvm);
    }
    const aliased = Object.assign({}, lvm, {
      category: 'lodging',
      title: 'Lodging options',
    });
    return renderRecommendationViewModel(aliased);
  }

  window.__biggyRenderLodgingViewModel = renderLodgingViewModel;
  window.__biggyRenderRecommendationViewModel = renderRecommendationViewModel;
  function cacheTripPlanViewModels(tvm) {
    if (!tvm || typeof tvm !== 'object' || tvm.schema !== 'jarvis.trip_plan_view_model.v1' ||
        tvm.emitted_by !== 'Jarvis II PA Tool') return [];
    const models = Array.isArray(tvm.categories) ? tvm.categories : [];
    models.forEach((model) => {
      if (model && typeof model === 'object' && model.category) {
        recommendationModelsByCategory[mapRecCategoryToRail(model.category)] = model;
      }
    });
    return models;
  }

  window.__biggyRenderTripPlanViewModel = function renderTripPlanViewModel(tvm) {
    const models = cacheTripPlanViewModels(tvm);
    if (!models.length) return { rendered: false, count: 0, category: null };
    const first = models.find((model) => model && model.category === 'lodging') || models.find((model) => model && model.available) || models[0];
    return first ? renderRecommendationViewModel(first) : { rendered: false, count: 0, category: null };
  };

  function safeJarvisVisualActionHref(value) {
    // The browser resolves this custom protocol on the workstation displaying
    // Biggy.  Thus a TD browser opens TD's MyRadar, while Smedley opens its own.
    // Never turn arbitrary model text into a custom-protocol launch link.
    const href = String(value || '').trim();
    if (href === 'myradar://open' || href === 'myradar://primary') return href;
    // Normalize the retired PA contract so cached/session view models cannot
    // put the dead `radar://` scheme back onto the weather card.
    if (href === 'radar://open') return 'myradar://open';
    if (href === 'radar://primary') return 'myradar://primary';
    return '';
  }

  function renderVisualActionViewModel(vm) {
    if (!vm || typeof vm !== 'object') return false;
    if (vm.schema !== 'jarvis.visual_action_view_model.v1' || vm.emitted_by !== 'Jarvis II PA Tool') {
      return false;
    }
    if (mapRecCategoryToRail(vm.category) !== 'weather') return false;
    const actionsIn = Array.isArray(vm.actions) ? vm.actions : [];
    const actions = actionsIn
      .map((item) => ({ label: String(item && item.label || '').trim(), href: safeJarvisVisualActionHref(item && item.href) }))
      .filter((item) => item.label && item.href);
    if (!actions.length) return false;

    const dlg = ensureTravelMapDialog();
    if (!dlg) return false;
    const weatherZip = extractWeatherZip(vm.location_echo || vm.location || vm.zip || vm.postal_code);
    refreshWeatherPanel(dlg, weatherZip || savedWeatherZip(), { persist: !!weatherZip });
    const radarLink = dlg.querySelector('#biggyWeatherRadarLink');
    if (radarLink && actions[0]) radarLink.href = actions[0].href;
    const actionBox = dlg.querySelector('#biggyTravelMapActions');
    const note = dlg.querySelector('#biggyTravelMapNote');
    if (!actionBox) return false;
    actionBox.innerHTML = '';
    actionBox.setAttribute('data-action-category', 'weather');
    actions.forEach((item) => {
      const a = document.createElement('a');
      a.className = 'biggy-travel-nav-btn';
      a.href = item.href;
      a.textContent = item.label;
      a.setAttribute('data-testid', item.href === 'myradar://primary' ? 'biggy-weather-myradar-primary' : 'biggy-weather-myradar-secondary');
      a.setAttribute('title', 'Opens MyRadar on this device after you click');
      actionBox.appendChild(a);
    });
    if (note) {
      note.textContent = String(vm.notice || 'Local MyRadar action · opens only after you click it.');
    }
    if (typeof dlg.__biggySetActiveCategory === 'function') {
      dlg.__biggySetActiveCategory('weather', { open: true });
    } else if (typeof dlg.__biggySetCollapsed === 'function') {
      dlg.__biggySetCollapsed(false);
    }
    return true;
  }

  window.__biggyRenderVisualActionViewModel = renderVisualActionViewModel;

  async function handoffTravelVisualsFromMessages(messages, correlationId) {
    const list = Array.isArray(messages) ? messages : (typeof S !== 'undefined' && S && S.messages) || [];
    for (let i = list.length - 1; i >= 0; i--) {
      const m = list[i];
      if (!m || m.role !== 'assistant' || m.ask_jarvis_pending) continue;
      const corr = String(correlationId || m._correlation_id || window.__askJarvisActiveCorrelation || '');
      if (corr) window.__askJarvisActiveCorrelation = corr;
      const mvm = m.map_view_model;
      const rvm = m.recommendation_view_model;
      const tpm = m.trip_plan_view_model;
      const lvm = m.lodging_view_model;
      const avm = m.visual_action_view_model;
      const weatherBriefing = m.weather_briefing;
      const hasVisual = [mvm, rvm, tpm, lvm, avm, weatherBriefing].some((vm) => vm && typeof vm === 'object');
      // Only the latest completed assistant turn is eligible.  Do not walk
      // back through history: a RAG result must never resurrect travel cards.
      if (!hasVisual) {
        // A completed corpus/document response owns the right-hand workspace
        // even when retrieval failed and produced no citation.  Close and
        // invalidate any older travel generation so an asynchronous Mapbox
        // completion cannot reopen the prior trip over this RAG turn.
        if (isGalaxyTraceEligibleMessage(m) || m.document_route
            || m.active_document_review || m.engineering_rag_answer
            || m.jarvis_ii_generic_rag_vnext) {
          invalidateTravelVisuals();
        }
        return false;
      }

      // A travel/action response owns the dock, never the corpus graph.  An
      // earlier document trace must be cleared before the new cards render.
      clearRagTrace();

      let recInfo = { rendered: false, count: 0, category: null };
      let visualActionOk = false;
      try {
        // A trip package owns every category on the right rail.  Cache all of
        // them even when the response also carries a preferred recommendation
        // model; otherwise only Lodging survives hydration and the remaining
        // category buttons incorrectly appear empty.
        const tripModels = tpm && typeof tpm === 'object' ? cacheTripPlanViewModels(tpm) : [];
        if (rvm && typeof rvm === 'object') {
          recInfo = renderRecommendationViewModel(rvm) || recInfo;
        } else if (tripModels.length) {
          recInfo = window.__biggyRenderTripPlanViewModel(tpm) || recInfo;
        } else if (lvm && typeof lvm === 'object') {
          recInfo = renderLodgingViewModel(lvm) || recInfo;
        }
        if (avm && typeof avm === 'object') {
          visualActionOk = renderVisualActionViewModel(avm);
        }
        if (weatherBriefing && typeof weatherBriefing === 'object') {
          const dlg = ensureTravelMapDialog();
          const explicitZip = extractWeatherZip(weatherBriefing.location_echo);
          const zipOverride = explicitZip
            || extractWeatherZip(weatherBriefing.currents && weatherBriefing.currents.location)
            || savedWeatherZip();
          if (!renderArgusWeatherBriefing(dlg, weatherBriefing)) {
            refreshWeatherPanel(dlg, zipOverride, { persist: !!explicitZip });
          }
          if (dlg && typeof dlg.__biggySetActiveCategory === 'function') {
            dlg.__biggySetActiveCategory('weather', { open: true });
          }
          visualActionOk = true;
        }
      } catch (error) {
        console.error('[biggy] recommendation card hydration failed', error);
      }

      const sendAck = (mapOk) => {
        const dlg = document.getElementById('biggyTravelMapDialog');
        postRenderAck({
          correlation_id: corr,
          map_rendered: !!mapOk,
          recommendations_rendered: !!recInfo.rendered,
          recommendation_card_count: recInfo.count || 0,
          category: recInfo.category || (visualActionOk ? 'weather' : null),
          visual_actions_rendered: visualActionOk,
          layout_slot: 'docked_landing_panel',
          overlay_dialog: false,
          displaces_conversation: false,
          panel_visible: !!(dlg && !dlg.hidden),
          panel_collapsed: !!(dlg && dlg.classList.contains('is-collapsed')),
          dialog_visible: false,
        });
      };

      if (mvm && typeof mvm === 'object') {
        // Mapbox/WebGL may take seconds to initialize.  Start it after the card
        // DOM and category cache exist, but do not make completion hydration,
        // PTT release, or the visible cards wait for the map promise.
        Promise.resolve(renderMapViewModel(mvm)).then((mapOk) => {
          sendAck(!!mapOk);
        }).catch((error) => {
          console.error('[biggy] map card hydration failed', error);
          sendAck(false);
        });
      } else {
        sendAck(false);
      }
      return true;
    }
    return false;
  }

  window.__biggyHandoffTravelVisualsFromMessages = handoffTravelVisualsFromMessages;

  async function scanMessagesForMapModel() {
    // One boot-time restore for the latest completed turn. Live turns are
    // owned by their direct-response/PTT completion boundaries.
    const list = (typeof S !== 'undefined' && S && Array.isArray(S.messages)) ? S.messages : [];
    const latestAssistant = [...list].reverse().find((message) => message
      && message.role === 'assistant' && !message.ask_jarvis_pending);
    if (latestAssistant && isGalaxyTraceEligibleMessage(latestAssistant)
        && galaxyTraceCitation(latestAssistant)) {
      window.__biggyHandleDocumentResult(latestAssistant);
      return;
    }
    await handoffTravelVisualsFromMessages(list);
    const dlg = document.getElementById('biggyTravelMapDialog');
    if (dlg && typeof dlg.__biggySetCollapsed === 'function') {
      dlg.__biggySetCollapsed(true);
    }
  }

  function applyShell() {
    const mainChat = document.getElementById('mainChat');
    if (!mainChat) return false;
    document.body.classList.add(BODY_CLASS);
    mainChat.classList.add(IWO_CLASS);
    document.querySelectorAll('.biggy-brand-header').forEach((node) => node.remove());
    document.querySelectorAll('.biggy-jarvis-transplant').forEach((node) => node.remove());
    document.querySelectorAll('.biggy-composer-controls').forEach((node) => node.remove());
    document.querySelectorAll('.biggy-fleet-strip').forEach((node) => node.remove());
    document.querySelectorAll('.biggy-cockpit-strip').forEach((node) => node.remove());
    document.querySelectorAll('.biggy-right-cockpit-controls').forEach((node) => node.remove());
    mainChat.querySelectorAll('.biggy-argus-rag-overview').forEach((node) => node.remove());
    mainChat.querySelectorAll('.biggy-argus-conversation-lane').forEach((node) => node.remove());
    pttInstalled = false;
    installBiggyV6World(mainChat);
    ensureArgusRagOverview(mainChat);
    installArgusConversationLane(mainChat);
    const header = makeHeader();
    mainChat.insertBefore(header, mainChat.firstChild);
    const reactorDock = makeReactorDock();
    const modelStatus = header.querySelector('.biggy-brand-status');
    if (modelStatus) reactorDock.appendChild(modelStatus);
    const composer = document.getElementById('composerWrap');
    if (composer) composer.appendChild(reactorDock);
    else header.insertAdjacentElement('afterend', reactorDock);
    buildReactorHud();
    installPttBridge(header);
    installCockpitStrip(header);
    installJarvisV6Bridge(header);
    installRagTraceObserver();
    purgeOwnerAckArtifacts();
    installBiggyVoiceLabels();
    installSmedleyAudioPolicy();
    installGreetingAck();
    installDocumentTitle();
    installComposerBranding();
    installFleetStrip();
    forceChromeLabels();
    installJarvisResponseLabels();
    removeCaduceus();
    updateIdentityChip();
    ensureTravelMapDialog();
    // Do not replay saved response cards into a fresh cockpit. New assistant
    // results invoke the handoff directly; the landing page stays collapsed.
    return true;
  }

  async function tryStart() {
    if (started) return;
    await refreshIdentity();
    if (!isBiggyInstance()) return;
    if (!applyShell()) {
      setTimeout(() => { tryStart().catch(() => {}); }, 100);
      return;
    }
    started = true;
    installGuiDiagnostics();
    installDiagnosticsHotkey();
    // The ARGUS landing is intentionally sessionless. Native Hermes creates
    // or loads a conversation only after explicit operator action; restoring
    // Biggy's private session key here caused a second, competing boot.
    refreshGuiDiagnostics();
    await refreshIdentity();
    if (identityTimer) clearInterval(identityTimer);
    identityTimer = setInterval(() => {
      refreshIdentity().catch(() => {});
      refreshGuiDiagnostics();
    }, 15000);
    if (diagTimer) clearInterval(diagTimer);
    diagTimer = setInterval(() => refreshGuiDiagnostics(), 3000);
    if (ragWorldTimer) clearInterval(ragWorldTimer);
    ragWorldTimer = setInterval(() => { pollRagWorldState().catch(() => {}); }, 5000);
  }

  function start() {
    tryStart().catch(() => {});
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();
