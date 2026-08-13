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
  const BUILD_ID = '20260811-1225-route-voice-fix';
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
          return String(m.tts_voice_id || 'dzRy05hNK3bab9ViJ0oU').trim();
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

  async function speakOnSmedley(text, opts) {
    opts = opts || {};
    const clean = stripForSmedleySpeak(text);
    if (!clean) return false;
    try {
      const body = { text: clean.slice(0, 800) };
      let voiceId = opts.voice_id ? String(opts.voice_id).trim() : '';
      // Exact override: speechSynthesis sink and other no-opts callers were
      // posting /speak with no voice_id → Austin. Ask Jarvis turns must carry
      // James Michael through this single Smedley-sink choke point.
      if (!voiceId) voiceId = resolveAskJarvisVoiceId();
      if (voiceId && /^[A-Za-z0-9_-]{8,64}$/.test(voiceId)) body.voice_id = voiceId;
      // Existing Smedley RAG sidecar: ElevenLabs → room soundbar/speakers or headset.
      await proxyJson('/speak', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      return true;
    } catch (_) {
      return false;
    }
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
    if (mobile) return; // phones/tablets keep local Biggy Voice / browser TTS

    // Desktop/remote GUIs: never play Biggy on the viewing machine.
    // Spoken output is Smedley room (soundbar/speakers) or headset via pedal TTS.
    try {
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
          // Ask Jarvis hard-bind: spoken_text only + James Michael voice override.
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
            // Server already queued James Michael (and Austin ack) — no client duplicate.
            if (jarvisMsg._tts_final_server_queued || jarvisMsg._tts_ack_server_queued) {
              if (jarvisMsg._tts_final_server_queued) return;
            }
            const spoken = String(jarvisMsg.spoken_text || jarvisMsg.spoken_reply || '').trim();
            if (spoken) {
              // Final only: James Michael. Never speak Austin ack from client.
              if (String(jarvisMsg.tts_voice_profile || '') === 'biggy_austin_ack') return;
              const voiceId = jarvisMsg.tts_voice_id || 'dzRy05hNK3bab9ViJ0oU';
              speakOnSmedley(spoken, { voice_id: voiceId });
              return;
            }
            return;
          }
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
    if (note && !note.textContent) {
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
      if (!target.closest('.biggy-brand-title, .biggy-brand-heading, #biggyIdentity')) return;
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
    let routePending = false;

    function applyAudioRouteStatus(status) {
      const active = String(status.active_route || 'room').toLowerCase();
      const desired = String(status.desired_route || active).toLowerCase();
      const switching = !!status.route_switching || routePending;
      const headsetAvailable = !!status.headset_available;
      const shown = (switching ? desired : active) === 'headset' ? 'HEADSET' : 'ROOM';
      routeBtn.textContent = shown;
      routeBtn.classList.remove('ok', 'active', 'down');
      if (!status.pedal_alive) {
        routeBtn.classList.add('down');
      } else if (switching) {
        routeBtn.classList.add('active');
        if (note) note.textContent = `Switching to ${desired === 'headset' ? 'Headset' : 'Room'}…`;
      } else if (desired === 'headset' && !headsetAvailable) {
        routeBtn.classList.add('down');
        if (note) note.textContent = 'Headset is not connected to Smedley.';
      } else {
        routeBtn.classList.add('ok');
        if (note && /^Switching to (?:Headset|Room)…$/.test(note.textContent || '')) {
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
      const target = active === 'headset' ? 'room' : 'headset';
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
      applyAudioRouteStatus(status);
    }

    async function syncActiveSession() {
      const sid = currentHermesSessionId();
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

    async function pollPttStatus() {
      await syncActiveSession();
      try {
        const status = await proxyJson('/ptt/status');
        applyPttStatus(status);
        const completionTs = Number(status.completion_timestamp || 0);
        if (!completionBaselineEstablished) {
          lastCompletionTimestamp = completionTs;
          completionBaselineEstablished = true;
          if (acceptPttCompletion(status)) {
            const completionSid = String(status.completion_session_id || '');
            const loadSess = (typeof window.loadSession === 'function')
              ? window.loadSession
              : (typeof loadSession === 'function' ? loadSession : null);
            const cur = currentHermesSessionId();
            if (loadSess && completionSid !== cur) {
              try {
                await loadSess(completionSid, {
                  force: true,
                  externalRefreshReason: 'ptt-baseline-sync',
                  guiId: GUI_ID,
                });
                postedSession = '';
                persistGuiSessionId(completionSid);
              } catch (_) {}
            } else if (loadSess && completionSid === cur) {
              try {
                await loadSess(completionSid, {
                  force: true,
                  externalRefreshReason: 'ptt-baseline-refresh',
                  guiId: GUI_ID,
                });
              } catch (_) {}
            }
          }
          return;
        }
        if (completionTs > lastCompletionTimestamp) {
          lastCompletionTimestamp = completionTs;
          if (!acceptPttCompletion(status)) return;
          const completionSid = String(status.completion_session_id || '');
          const loadSess = (typeof window.loadSession === 'function')
            ? window.loadSession
            : (typeof loadSession === 'function' ? loadSession : null);
          if (!loadSess) return;
          try {
            await loadSess(completionSid, {
              force: true,
              externalRefreshReason: 'ptt-completion',
              guiId: GUI_ID,
            });
            postedSession = '';
            persistGuiSessionId(completionSid);
          } catch (_) {}
        }
      } catch (_) {
        ptt.classList.remove('ok', 'active');
        ptt.classList.add('down');
        routeBtn.classList.remove('ok', 'active');
        routeBtn.classList.add('down');
      }
    }

    pollPttStatus();
    setInterval(() => { pollPttStatus().catch(() => {}); }, 1500);
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

  function makeHeader() {
    const header = el('div', 'biggy-brand-header');
    header.innerHTML =
      `<div class="biggy-brand-cluster">` +
      `<img class="biggy-brand-ega" src="/static/ega.jpg" alt="EGA">` +
      `<div class="biggy-brand-heading">` +
      `<div class="biggy-brand-title">BIGGY</div>` +
      `<div class="biggy-brand-subtitle" id="biggyBrandSubtitle">${esc(ROLE)}</div>` +
      `</div>` +
      `<img class="biggy-brand-ega" src="/static/ega.jpg" alt="EGA">` +
      `</div>` +
      `<div class="biggy-brand-controls">` +
      `<button id="biggyPtt" type="button" data-testid="biggy-ptt" title="Foot-pedal PTT status">● PTT</button>` +
      `<button id="biggyAudioRoute" type="button" data-testid="biggy-audio-route" title="Toggle headset / room audio">ROOM</button>` +
      `<button id="biggyOpenSmedley" type="button" data-testid="biggy-open-smedley" title="Open Smedley GUI (RAG + electrical tools)">SMEDLEY</button>` +
      `<div id="biggyHeaderNote" class="biggy-brand-header-note"></div>` +
      `</div>` +
      `<div class="biggy-brand-status" aria-label="Biggy identity">` +
      `<div class="biggy-brand-meta" id="biggyBrandMeta">PROFILE biggy</div>` +
      `</div>`;
    return header;
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
    'Travel',
    'Lodging',
    'Meals',
    'Entertainment',
    'Fuel',
    'Other',
  ];

  function railCategoryKey(label) {
    return String(label || '').trim().toLowerCase();
  }

  function mapRecCategoryToRail(category) {
    const c = String(category || '').trim().toLowerCase();
    if (!c || c === 'travel') return 'travel';
    if (c === 'lodging' || c === 'hotel') return 'lodging';
    if (c === 'meals' || c === 'meal' || c === 'restaurant' || c === 'steakhouse' || c === 'dining') {
      return 'meals';
    }
    if (c === 'entertainment' || c === 'event' || c === 'shows') return 'entertainment';
    if (c === 'fuel' || c === 'gas') return 'fuel';
    return 'other';
  }

  function ensureTravelMapDialog() {
    // Persistent category rail + docked open panel in unused landing space.
    // Never shrinks conversation viewport; never displaces brand header/composer.
    let dlg = document.getElementById('biggyTravelMapDialog');
    if (dlg) return dlg;
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
    dlg.setAttribute('data-open-panel-scale', '1.5');
    dlg.style.setProperty('--biggy-travel-dock-width', '540px'); // 360 * 1.5
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
      `<div class="biggy-travel-empty-cat" id="biggyTravelEmptyCat" hidden>No options loaded for this category yet.</div>` +
      `</div>` +
      `</div>`;
    mainChat.appendChild(dlg);

    const setCollapsed = (collapsed) => {
      dlg.classList.toggle('is-collapsed', !!collapsed);
      const collapseBtn = dlg.querySelector('#biggyTravelDockCollapse');
      if (collapseBtn) collapseBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      if (!collapsed) {
        try { if (mapInstance) mapInstance.resize(); } catch (_) {}
      }
    };
    dlg.__biggySetCollapsed = setCollapsed;

    const setActiveCategory = (category, { open = true } = {}) => {
      const key = mapRecCategoryToRail(category);
      dlg.setAttribute('data-active-category', key);
      dlg.querySelectorAll('.biggy-category-rail-btn').forEach((btn) => {
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
      const empty = dlg.querySelector('#biggyTravelEmptyCat');
      const showTravel = key === 'travel';
      if (mapCanvas) mapCanvas.hidden = !showTravel;
      if (mapActions) mapActions.hidden = !showTravel;
      if (mapNote) mapNote.hidden = !showTravel;
      if (lodging) {
        lodging.hidden = showTravel || lodging.getAttribute('data-has-cards') !== '1';
      }
      if (empty) {
        empty.hidden = showTravel || (lodging && lodging.getAttribute('data-has-cards') === '1');
      }
      if (open) {
        dlg.hidden = false;
        setCollapsed(false);
      }
    };
    dlg.__biggySetActiveCategory = setActiveCategory;

    dlg.querySelectorAll('.biggy-category-rail-btn').forEach((btn) => {
      btn.addEventListener('click', (ev) => {
        ev.preventDefault();
        const key = btn.getAttribute('data-category') || 'travel';
        if (!dlg.classList.contains('is-collapsed') && dlg.getAttribute('data-active-category') === key) {
          setCollapsed(true);
          return;
        }
        setActiveCategory(key, { open: true });
      });
    });

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
        startW = panel ? panel.getBoundingClientRect().width : 540;
        handle.setPointerCapture(ev.pointerId);
        ev.preventDefault();
      });
      handle.addEventListener('pointermove', (ev) => {
        if (!dragging) return;
        const dx = startX - ev.clientX;
        const next = Math.max(400, Math.min(780, startW + dx));
        dlg.style.setProperty('--biggy-travel-dock-width', next + 'px');
        try { if (mapInstance) mapInstance.resize(); } catch (_) {}
      });
      handle.addEventListener('pointerup', () => { dragging = false; });
      handle.addEventListener('pointercancel', () => { dragging = false; });
    }
    setActiveCategory('travel', { open: false });
    return dlg;
  }

  function hideTravelMap() {
    const dlg = document.getElementById('biggyTravelMapDialog');
    if (dlg) {
      // Keep persistent rail; only collapse the open panel.
      if (typeof dlg.__biggySetCollapsed === 'function') dlg.__biggySetCollapsed(true);
      else dlg.classList.add('is-collapsed');
    }
    try {
      if (mapInstance) {
        mapInstance.remove();
        mapInstance = null;
      }
    } catch (_) {}
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

  async function renderMapViewModel(mvm) {
    if (!mvm || typeof mvm !== 'object') return false;
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
    if (mvm.schema !== 'jarvis.map_view_model.v1' || mvm.emitted_by !== '3 AI Agent') {
      return false; // refuse non-Agent models
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

    let cfg;
    try {
      cfg = await fetchMapboxToken();
    } catch (_) {
      cfg = { available: false, reason: 'CONFIG_FETCH_FAILED' };
    }
    if (!cfg.available || !cfg.token) {
      if (note) {
        note.textContent =
          'Mapbox unavailable (' +
          String(cfg.reason || 'token') +
          '). Config var: ' +
          String(cfg.token_env || 'BIGGY_MAPBOX_PUBLIC_TOKEN');
      }
      return false;
    }
    try {
      const mapboxgl = await loadMapboxAssets();
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
      await new Promise((resolve) => {
        mapInstance.on('load', () => {
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
      if (note) note.textContent = 'Display only · Agent map_view_model · not a decision-maker';
      return true;
    } catch (err) {
      if (note) note.textContent = 'Mapbox render failed: ' + String(err && err.message || err);
      return false;
    }
  }

  window.__biggyRenderMapViewModel = renderMapViewModel;

  function safeLodgingHref(url) {
    const s = String(url || '').trim();
    if (!/^https:\/\//i.test(s)) return null;
    if (/^(https:\/\/)(localhost|127\.|0\.0\.0\.0|10\.|192\.168\.|172\.(1[6-9]|2\d|3[0-1])\.|\[::1\])/i.test(s)) {
      return null;
    }
    if (/[<>"']|javascript:/i.test(s)) return null;
    return s;
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

  function renderRecommendationViewModel(rvm) {
    if (!rvm || typeof rvm !== 'object') return { rendered: false, count: 0, category: null };
    const okSchema =
      (rvm.schema === 'jarvis.recommendation_view_model.v1' ||
        rvm.schema === 'jarvis.lodging_view_model.v1') &&
      rvm.emitted_by === '3 AI Agent';
    if (!okSchema) return { rendered: false, count: 0, category: null };
    const category = String(rvm.category || (rvm.schema === 'jarvis.lodging_view_model.v1' ? 'lodging' : '') || '');
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
      const href = safeLodgingHref(opt.url);
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

  async function handoffTravelVisualsFromMessages(messages, correlationId) {
    try {
      const list = Array.isArray(messages) ? messages : (typeof S !== 'undefined' && S && S.messages) || [];
      for (let i = list.length - 1; i >= 0; i--) {
        const m = list[i];
        if (!m || m.role !== 'assistant') continue;
        if (m.ask_jarvis_pending) continue;
        const corr = String(correlationId || m._correlation_id || window.__askJarvisActiveCorrelation || '');
        if (corr) window.__askJarvisActiveCorrelation = corr;
        const mvm = m.map_view_model;
        const rvm = m.recommendation_view_model;
        const lvm = m.lodging_view_model;
        // Prefer recommendation_view_model; never fall back to lodging when category != lodging.
        let mapOk = false;
        let recInfo = { rendered: false, count: 0, category: null };
        if (mvm && typeof mvm === 'object') {
          mapOk = !!(await renderMapViewModel(mvm));
        }
        if (rvm && typeof rvm === 'object') {
          recInfo = renderRecommendationViewModel(rvm) || recInfo;
        } else if (lvm && typeof lvm === 'object') {
          // Only render lodging alias when no non-lodging recommendation is present.
          recInfo = renderLodgingViewModel(lvm) || recInfo;
        }
        if ((mvm && typeof mvm === 'object') || (rvm && typeof rvm === 'object') || (lvm && typeof lvm === 'object')) {
          const dlg = document.getElementById('biggyTravelMapDialog');
          postRenderAck({
            correlation_id: corr,
            map_rendered: !!mapOk,
            recommendations_rendered: !!recInfo.rendered,
            recommendation_card_count: recInfo.count || 0,
            category: recInfo.category || null,
            layout_slot: 'docked_landing_panel',
            overlay_dialog: false,
            displaces_conversation: false,
            panel_visible: !!(dlg && !dlg.hidden),
            panel_collapsed: !!(dlg && dlg.classList.contains('is-collapsed')),
            dialog_visible: false,
          });
          return true;
        }
      }
    } catch (_) {}
    return false;
  }

  window.__biggyHandoffTravelVisualsFromMessages = handoffTravelVisualsFromMessages;

  function scanMessagesForMapModel() {
    handoffTravelVisualsFromMessages();
  }

  function applyShell() {
    const mainChat = document.getElementById('mainChat');
    if (!mainChat) return false;
    document.body.classList.add(BODY_CLASS);
    mainChat.classList.add(IWO_CLASS);
    document.querySelectorAll('.biggy-brand-header').forEach((node) => node.remove());
    pttInstalled = false;
    const header = makeHeader();
    mainChat.insertBefore(header, mainChat.firstChild);
    installPttBridge(header);
    installSmedleyButton(header);
    purgeOwnerAckArtifacts();
    installBiggyVoiceLabels();
    installSmedleyAudioPolicy();
    installGreetingAck();
    installDocumentTitle();
    installComposerBranding();
    forceChromeLabels();
    removeCaduceus();
    updateIdentityChip();
    ensureTravelMapDialog();
    setTimeout(scanMessagesForMapModel, 400);
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
    await ensureGuiSession();
    refreshGuiDiagnostics();
    await refreshIdentity();
    if (identityTimer) clearInterval(identityTimer);
    identityTimer = setInterval(() => {
      refreshIdentity().catch(() => {});
      ensureGuiSession().then(() => refreshGuiDiagnostics()).catch(() => {});
    }, 15000);
    if (diagTimer) clearInterval(diagTimer);
    diagTimer = setInterval(() => refreshGuiDiagnostics(), 3000);
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
