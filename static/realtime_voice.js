/* biggy-ptt-replace-gate-20260812-1245 */
/**
 * GPT Realtime Voice — browser audio I/O only.
 *
 * Hermes remains the conversation authority: spoken input becomes a normal
 * composer/send turn; Realtime speaks Hermes-approved reply text. Default off.
 */
(function () {
  'use strict';

  const STATE = {
    active: false,
    phase: 'idle', // idle | connecting | listening | processing | speaking | error
    pc: null,
    dc: null,
    media: null,
    audioEl: null,
    pendingSpeak: false,
    lastTranscript: '',
    suppressAutoResponse: true,
    micLive: false,
    talking: false,
    turnSubmitted: false,
    // Whether captured audio is still eligible to become a Hermes turn. This
    // outlives micLive: releasing push-to-talk mutes the mic immediately, but
    // the final transcription for that utterance still arrives afterwards.
    captureOpen: false,
    // Push-to-talk may receive several server-VAD segment transcripts while the
    // physical hold is still down. Accumulate them; submit only after release.
    pttParts: [],
  };

  // Playback and capture share the room, so the session is half-duplex: the
  // microphone is only live while listening. Without this the model hears its
  // own spoken reply, transcribes it, and drives an endless self-reply loop.
  const MIC_REARM_MS = 600;

  // How long after releasing Talk we still accept that utterance's transcript.
  const CAPTURE_GRACE_MS = 8000;

  // Hands-free server VAD: default OpenAI silence is 500ms, which cuts real
  // verbal prompts on natural pauses. Use a longer stop window.
  const HANDS_FREE_SILENCE_MS = 1800;

  // Watchdog: if the Hermes run ends without a speech hook firing, the session
  // would sit in "processing" forever with the mic gated. Poll the run state
  // and recover instead of stranding the operator.
  const RUN_WATCH_MS = 1500;
  const RUN_IDLE_TICKS = 3;

  // Push-to-talk is the default. Hands-free VAD stays behind an explicit
  // localStorage opt-in until echo handling is proven on real hardware.
  const HANDS_FREE_KEY = 'hermes-gpt-voice-handsfree';

  let _origAutoRead = null;
  let _micRearmTimer = null;
  let _captureGraceTimer = null;
  let _runWatchTimer = null;
  let _levelMeter = null;
  let _levelRaf = 0;
  let _rtcStatsTimer = null;
  const _TRACE = [];
  const TRACE_MAX = 250;
  STATE.lastRms = 0;
  STATE.peakRms = 0;
  STATE.framesAboveNoise = 0;
  STATE.outboundBytesDelta = 0;
  STATE._lastBytesSent = null;
  STATE.lastRtcOutbound = null;

  function _trace(kind, detail) {
    const row = Object.assign(
      {
        t: Date.now(),
        kind: String(kind || ''),
        phase: STATE.phase,
        talking: !!STATE.talking,
        micLive: !!STATE.micLive,
        captureOpen: !!STATE.captureOpen,
        turnSubmitted: !!STATE.turnSubmitted,
        handsFree: !!_handsFree(),
      },
      detail && typeof detail === 'object' ? detail : {}
    );
    _TRACE.push(row);
    while (_TRACE.length > TRACE_MAX) _TRACE.shift();
    try {
      window.__biggyVoiceTrace = _TRACE;
    } catch (_) {}
  }

  function _hermesRunActive() {
    try {
      return !!(window.S && (S.busy || S.activeStreamId));
    } catch (_) {
      return false;
    }
  }

  function _stopRunWatch() {
    if (_runWatchTimer) {
      clearInterval(_runWatchTimer);
      _runWatchTimer = null;
    }
  }

  function _startRunWatch() {
    _stopRunWatch();
    let idleTicks = 0;
    _runWatchTimer = setInterval(() => {
      if (!STATE.active || STATE.phase !== 'processing' || _hermesRunActive()) {
        idleTicks = 0;
        return;
      }
      idleTicks += 1;
      if (idleTicks >= RUN_IDLE_TICKS) {
        idleTicks = 0;
        _setPhase('listening');
      }
    }, RUN_WATCH_MS);
  }

  function _handsFree() {
    try {
      return localStorage.getItem(HANDS_FREE_KEY) === 'true';
    } catch (_) {
      return false;
    }
  }

  // Failure categories surfaced to the operator so a dead connection names the
  // layer that actually failed instead of a generic "error".
  const CATEGORY = {
    configuration: 'Configuration',
    permission: 'Microphone permission',
    session: 'Session creation',
    webrtc: 'WebRTC connection',
  };

  function _categoryError(category, message) {
    const err = new Error(message);
    err.category = CATEGORY[category] ? category : 'session';
    return err;
  }

  function _describeError(err) {
    const message = String(err && err.message ? err.message : err || 'Unknown error');
    const label = CATEGORY[err && err.category] || CATEGORY.session;
    return label + ': ' + message;
  }

  function _notify(message, type) {
    if (typeof showToast === 'function') {
      showToast(message, null, type || 'error');
      return;
    }
    if (typeof console !== 'undefined') console.error('[gpt-voice]', message);
  }

  function $(id) {
    return document.getElementById(id);
  }

  function _t(key, fallback) {
    try {
      if (typeof t === 'function') {
        const v = t(key);
        if (v && v !== key) return v;
      }
    } catch (_) {}
    return fallback;
  }

  async function _swapSenderTrack(track) {
    if (!track || !STATE.pc) return false;
    const sender =
      STATE.audioSender ||
      STATE.pc.getSenders().find((s) => s.track && s.track.kind === 'audio') ||
      STATE.pc.getSenders().find((s) => s.track == null);
    if (!sender) return false;
    STATE.audioSender = sender;
    // Never mute by track.enabled=false after addTrack — that left Realtime
    // receiving permanent silence while the UI still showed Talk held.
    try {
      track.enabled = true;
    } catch (_) {}
    try {
      await sender.replaceTrack(track);
      _trace('sender_replace', {
        trackId: track.id,
        label: track.label || '',
        readyState: track.readyState,
      });
      return true;
    } catch (err) {
      _trace('sender_replace_failed', {
        error: String(err && err.message ? err.message : err),
      });
      return false;
    }
  }

  function _setMicEnabled(on) {
    const next = !!on;
    if (STATE.micLive !== next) {
      _trace('mic_enable', {
        on: next,
        gate: STATE.micTrack && STATE.silentTrack ? 'replace' : 'legacy',
      });
    }
    STATE.micLive = next;
    // Physical-mic path: swap the RTC sender between the live getUserMedia
    // track and a silent WebAudio placeholder. Do not route mic through
    // MediaStreamDestination — that path accepted WebAudio inject while
    // real Fifine/getUserMedia stayed silent to OpenAI.
    if (STATE.micTrack && STATE.silentTrack) {
      const want = next ? STATE.micTrack : STATE.silentTrack;
      try {
        STATE.micTrack.enabled = true;
      } catch (_) {}
      try {
        STATE.silentTrack.enabled = true;
      } catch (_) {}
      STATE._swapChain = (STATE._swapChain || Promise.resolve())
        .catch(() => {})
        .then(() => _swapSenderTrack(want));
    } else if (STATE.media) {
      try {
        STATE.media.getAudioTracks().forEach((track) => {
          track.enabled = next;
        });
      } catch (_) {}
    }
    if (next) {
      _ensureLevelMeter();
      _sampleOutboundRtc('mic_on');
    }
  }

  function _stopLevelMeter() {
    if (_levelRaf) {
      try {
        cancelAnimationFrame(_levelRaf);
      } catch (_) {}
      _levelRaf = 0;
    }
    if (_rtcStatsTimer) {
      try {
        clearInterval(_rtcStatsTimer);
      } catch (_) {}
      _rtcStatsTimer = null;
    }
    _levelMeter = null;
  }

  async function _sampleOutboundRtc(reason) {
    if (!STATE.pc) return null;
    try {
      const stats = await STATE.pc.getStats();
      let outbound = null;
      let mediaSource = null;
      stats.forEach((r) => {
        if (r.type === 'outbound-rtp' && (!r.kind || r.kind === 'audio')) {
          outbound = {
            bytesSent: r.bytesSent,
            packetsSent: r.packetsSent,
            headerBytesSent: r.headerBytesSent,
            nackCount: r.nackCount,
            targetBitrate: r.targetBitrate,
          };
        }
        if (r.type === 'media-source' && (!r.kind || r.kind === 'audio')) {
          mediaSource = {
            audioLevel: r.audioLevel,
            totalAudioEnergy: r.totalAudioEnergy,
            totalSamplesDuration: r.totalSamplesDuration,
          };
        }
      });
      const deltaBytes =
        outbound && typeof STATE._lastBytesSent === 'number'
          ? outbound.bytesSent - STATE._lastBytesSent
          : null;
      if (outbound && typeof outbound.bytesSent === 'number') {
        STATE._lastBytesSent = outbound.bytesSent;
      }
      if (deltaBytes != null && deltaBytes > 0) {
        STATE.outboundBytesDelta = (STATE.outboundBytesDelta || 0) + deltaBytes;
      }
      const row = {
        reason: reason || 'sample',
        outbound: outbound,
        mediaSource: mediaSource,
        deltaBytes: deltaBytes,
        outboundBytesDelta: STATE.outboundBytesDelta || 0,
        lastRms: STATE.lastRms,
        peakRms: STATE.peakRms,
        framesAboveNoise: STATE.framesAboveNoise,
      };
      _trace('rtc_outbound', row);
      STATE.lastRtcOutbound = row;
      return row;
    } catch (err) {
      _trace('rtc_outbound_failed', {
        error: String(err && err.message ? err.message : err),
      });
      return null;
    }
  }

  function _startOutboundRtcWatch() {
    if (_rtcStatsTimer) return;
    _rtcStatsTimer = setInterval(() => {
      if (!STATE.active || !STATE.micLive) return;
      _sampleOutboundRtc('hold_tick');
    }, 500);
  }

  function _ensureLevelMeter() {
    if (_levelMeter) {
      _startOutboundRtcWatch();
      return;
    }
    const stream = STATE.rawMic || STATE.media;
    if (!stream) return;
    try {
      const ctx = STATE.audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      if (!STATE.audioCtx) STATE.audioCtx = ctx;
      if (ctx.state === 'suspended') {
        try {
          ctx.resume();
        } catch (_) {}
      }
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 2048;
      src.connect(analyser);
      const data = new Uint8Array(analyser.fftSize);
      _levelMeter = { analyser: analyser, data: data };
      const tick = () => {
        if (!_levelMeter || !STATE.active) return;
        try {
          _levelMeter.analyser.getByteTimeDomainData(_levelMeter.data);
          let sum = 0;
          for (let i = 0; i < _levelMeter.data.length; i++) {
            const v = (_levelMeter.data[i] - 128) / 128;
            sum += v * v;
          }
          const rms = Math.sqrt(sum / _levelMeter.data.length);
          STATE.lastRms = rms;
          if (STATE.micLive && rms > STATE.peakRms) STATE.peakRms = rms;
          if (STATE.micLive && rms > 0.02) STATE.framesAboveNoise += 1;
        } catch (_) {}
        _levelRaf = requestAnimationFrame(tick);
      };
      _levelRaf = requestAnimationFrame(tick);
      _startOutboundRtcWatch();
      _trace('level_meter_on');
    } catch (err) {
      _trace('level_meter_failed', { error: String(err && err.message ? err.message : err) });
    }
  }

  function _clearMicRearm() {
    if (_micRearmTimer) {
      clearTimeout(_micRearmTimer);
      _micRearmTimer = null;
    }
  }

  function _clearCaptureGrace() {
    if (_captureGraceTimer) {
      clearTimeout(_captureGraceTimer);
      _captureGraceTimer = null;
    }
  }

  function _openCapture() {
    _clearCaptureGrace();
    if (!STATE.captureOpen) _trace('capture_open');
    STATE.captureOpen = true;
  }

  function _closeCapture() {
    _clearCaptureGrace();
    if (STATE.captureOpen) _trace('capture_close');
    STATE.captureOpen = false;
  }

  function _applyMicGate(phase) {
    _clearMicRearm();
    // In push-to-talk the mic is armed only while the operator holds Talk, so
    // playback can never be captured. Hands-free arms on the listening phase.
    const wanted = STATE.active && phase === 'listening' && (_handsFree() || STATE.talking);
    if (!wanted) {
      _setMicEnabled(false);
      // Playback and Hermes processing invalidate anything still buffered;
      // only a push-to-talk release keeps its capture window open.
      if (phase === 'speaking' || phase === 'processing' || !STATE.active) _closeCapture();
      _trace('mic_gate_off', { phase: phase });
      return;
    }
    // CRITICAL: repeated _setPhase('listening') (speech_started, watchdogs,
    // response.done) must NOT pulse-mute an already-live capture window.
    // The prior 600ms re-arm on every listening entry cut real verbal prompts.
    if (STATE.micLive) {
      _openCapture();
      _trace('mic_gate_keep_live', { phase: phase });
      return;
    }
    // PTT while physically holding: arm immediately — no echo-tail delay.
    if (!_handsFree() && STATE.talking) {
      _setMicEnabled(true);
      _openCapture();
      _trace('mic_gate_ptt_immediate', { phase: phase });
      return;
    }
    // Hands-free / post-playback: brief re-arm so speaker decay does not
    // retrigger VAD, but only when transitioning from muted → live.
    _trace('mic_gate_rearm_scheduled', { delay_ms: MIC_REARM_MS, phase: phase });
    _micRearmTimer = setTimeout(() => {
      _micRearmTimer = null;
      if (STATE.active && STATE.phase === 'listening' && (_handsFree() || STATE.talking)) {
        _setMicEnabled(true);
        _openCapture();
        _trace('mic_gate_rearm_fired');
      }
    }, MIC_REARM_MS);
  }

  function _guiId() {
    try {
      const raw = String(window.__HERMES_GUI_ID__ || document.body?.dataset?.guiId || '').trim().toLowerCase();
      if (raw === 'biggy' || raw === 'smedley') return raw;
    } catch (_) {}
    return '';
  }

  function _voiceProductName() {
    const gui = _guiId();
    if (gui === 'biggy') return 'Biggy Voice';
    if (gui === 'smedley') return 'Smedley Voice';
    return 'Smedley Voice';
  }

  function _voiceCopy(fallback) {
    // Immutable per-GUI product name. Never inherit the other GUI's label from
    // shared i18n/static defaults or a "current profile" fallback.
    const product = _voiceProductName();
    return String(fallback || '')
      .replace(/Smedley Voice/g, product)
      .replace(/GPT Voice/g, product)
      .replace(/Biggy Voice/g, product);
  }

  function _setPhase(phase, detail) {
    const prev = STATE.phase;
    STATE.phase = phase;
    try { window.__smedleyRealtimeVoiceActive = !!STATE.active; } catch (_) {}
    // A fresh listening window is a new voice turn, so re-arm the one-shot
    // submission guard — but only when entering listening from a non-listening
    // phase. Re-entrant listening must not reset mid-utterance state.
    if (phase === 'listening' && prev !== 'listening') STATE.turnSubmitted = false;
    _trace('phase', { from: prev, to: phase, detail: detail || null });
    _applyMicGate(phase);
    const bar = $('gptVoiceBar');
    const label = $('gptVoiceLabel');
    const indicator = $('gptVoiceIndicator');
    const guard = $('gptVoiceGuard');
    const talkBtn = $('btnGptVoiceTalk');
    const btn = $('btnGptVoice');
    if (btn) {
      btn.classList.toggle('active', STATE.active);
      const tip = STATE.active
        ? _voiceCopy(_t('gpt_voice_toggle_active', 'Exit Smedley Voice'))
        : _voiceCopy(_t('gpt_voice_toggle', 'Smedley Voice'));
      btn.setAttribute('data-tooltip', tip);
      btn.setAttribute('title', tip);
      btn.setAttribute('aria-pressed', STATE.active ? 'true' : 'false');
      btn.dataset.guiId = _guiId() || '';
    }
    // An error is reported after the session has already torn down, so the
    // error phase must still render rather than hiding with the idle bar.
    if (!STATE.active && phase !== 'error') {
      if (bar) bar.style.display = 'none';
      return;
    }
    if (bar) {
      bar.style.display = '';
      bar.dataset.guiId = _guiId() || '';
    }

    // The mic is hard-muted while Hermes is thinking or speaking; say so, since
    // an operator who does not know that will talk into a dead microphone.
    const guarded = phase === 'processing' || phase === 'speaking';
    if (guard) guard.style.display = guarded ? '' : 'none';
    const stopBtn = $('btnGptVoiceStop');
    if (stopBtn) {
      // One control, two jobs: interrupt the turn in flight, or leave the
      // session once it is idle. Label it for whichever applies.
      stopBtn.textContent = guarded
        ? _t('gpt_voice_stop', 'Stop')
        : _t('gpt_voice_end', 'End');
      stopBtn.title = guarded
        ? _voiceCopy(_t('gpt_voice_stop_hint', 'Stop this response and keep Smedley Voice connected'))
        : _voiceCopy(_t('gpt_voice_end_hint', 'Disconnect Smedley Voice'));
    }
    if (talkBtn) {
      // Hands-free has no hold control; connecting has nothing to capture yet.
      talkBtn.style.display = _handsFree() ? 'none' : '';
      talkBtn.disabled = guarded || !STATE.active || phase === 'connecting';
      talkBtn.classList.toggle('talking', !!STATE.talking);
      talkBtn.textContent = STATE.talking
        ? _t('gpt_voice_release_to_send', 'Release to send')
        : _t('gpt_voice_hold_to_talk', 'Hold to talk');
    }

    const listeningLabel = _handsFree()
      ? _voiceCopy(_t('gpt_voice_listening', 'Smedley Voice · listening'))
      : STATE.talking
        ? _voiceCopy(_t('gpt_voice_capturing', 'Smedley Voice · capturing'))
        : _voiceCopy(_t('gpt_voice_ready_ptt', 'Smedley Voice · ready · hold Talk to speak'));
    const messages = {
      connecting: _voiceCopy(_t('gpt_voice_connecting', 'Connecting Smedley Voice…')),
      listening: listeningLabel,
      processing: _voiceCopy(_t('gpt_voice_processing', 'Smedley Voice · processing via Hermes')),
      speaking: _voiceCopy(_t('gpt_voice_speaking', 'Smedley Voice · speaking')),
      error: detail || _voiceCopy(_t('gpt_voice_error', 'Smedley Voice error')),
      idle: _voiceCopy(_t('gpt_voice_idle', 'Smedley Voice')),
    };
    if (label) {
      label.textContent = messages[phase] || messages.idle;
      label.dataset.guiId = _guiId() || '';
    }
    if (indicator) {
      indicator.dataset.phase = phase;
      indicator.className = 'voice-mode-indicator gpt-voice-indicator';
    }
  }

  function _webrtcSupported() {
    return !!(
      window.RTCPeerConnection &&
      navigator.mediaDevices &&
      typeof navigator.mediaDevices.getUserMedia === 'function'
    );
  }

  function _stripSpeechText(text) {
    if (typeof _stripForTTS === 'function') {
      try {
        return _stripForTTS(String(text || ''));
      } catch (_) {}
    }
    return String(text || '')
      .replace(/(^|\n)[ \t]*Document links(?:\s+for\s+[“"][^”"]*[”"])?(?:\s*\(sidecar preview\))?\s*:?[ \t]*(?=\n|$)/gi, '$1')
      .replace(/\bDocument links(?:\s+for\s+[“"][^”"]*[”"])?(?:\s*\(sidecar preview\))?\s*:?/gi, ' ')
      .replace(/\(\s*score\s*=\s*[-+]?\d*\.?\d+\s*\)/gi, ' ')
      .replace(/```[\s\S]*?```/g, ' ')
      .replace(/`[^`]*`/g, ' ')
      .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
      .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
      .replace(/https?:\/\/[^\s<>\]\)"']+/gi, ' ')
      .replace(/\/api\/extensions\/smedley-engineering\/sidecar\/(?:preview|doc)\/[^\s<>\]\)"']*/gi, ' ')
      .replace(/[#>*_~]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function _cleanupMedia() {
    _clearMicRearm();
    _closeCapture();
    _stopRunWatch();
    _stopLevelMeter();
    STATE.micLive = false;
    STATE.lastRms = 0;
    STATE.peakRms = 0;
    STATE.framesAboveNoise = 0;
    try {
      if (STATE.dc) STATE.dc.close();
    } catch (_) {}
    try {
      if (STATE.pc) STATE.pc.close();
    } catch (_) {}
    try {
      if (STATE.audioCtx && STATE.audioCtx.state !== 'closed') STATE.audioCtx.close();
    } catch (_) {}
    if (STATE.rawMic) {
      try {
        STATE.rawMic.getTracks().forEach((tr) => tr.stop());
      } catch (_) {}
    }
    if (STATE.media && STATE.media !== STATE.rawMic) {
      try {
        STATE.media.getTracks().forEach((tr) => tr.stop());
      } catch (_) {}
    }
    if (STATE.audioEl) {
      try {
        STATE.audioEl.srcObject = null;
        STATE.audioEl.remove();
      } catch (_) {}
    }
    STATE.pc = null;
    STATE.dc = null;
    STATE.media = null;
    STATE.rawMic = null;
    STATE.outbound = null;
    STATE.micGain = null;
    STATE.micTrack = null;
    STATE.silentTrack = null;
    STATE.audioSender = null;
    STATE.audioCtx = null;
    STATE.audioEl = null;
    STATE.pendingSpeak = false;
    STATE.lastTranscript = '';
    STATE.talking = false;
    STATE.turnSubmitted = false;
    STATE.outboundBytesDelta = 0;
    STATE._lastBytesSent = null;
    STATE.lastRtcOutbound = null;
  }

  function _stopPlayback() {
    // response.cancel is what actually silences Realtime: the audio element
    // renders a live WebRTC stream, so detaching it here would break the
    // session for the next reply.
    _cancelModelResponse();
    STATE.pendingSpeak = false;
    if (typeof stopSpeaking === 'function') {
      try {
        stopSpeaking();
      } catch (_) {}
    } else if (window.speechSynthesis) {
      try {
        window.speechSynthesis.cancel();
      } catch (_) {}
    }
  }

  function _sendEvent(payload) {
    if (!STATE.dc || STATE.dc.readyState !== 'open') return false;
    try {
      STATE.dc.send(JSON.stringify(payload));
      return true;
    } catch (_) {
      return false;
    }
  }

  function _cancelModelResponse() {
    _sendEvent({ type: 'response.cancel' });
  }

  function _speakHermesText(text) {
    if (typeof selectSmedleyVoiceEmitter === 'function' && selectSmedleyVoiceEmitter({}) === 'none') {
      if (STATE.active) _setPhase('listening');
      return;
    }
    const spoken = _stripSpeechText(text);
    if (!spoken) {
      // Nothing speakable (e.g. a code-only reply) still ends the turn.
      if (STATE.active) _setPhase('listening');
      return;
    }
    _closeCapture();
    _setPhase('speaking');
    STATE.pendingSpeak = true;
    // Prefer a one-shot response so Realtime does not treat this as a new Q&A turn.
    const ok = _sendEvent({
      type: 'response.create',
      response: {
        output_modalities: ['audio'],
        instructions:
          'Speak the following Hermes reply aloud verbatim, then stop. ' +
          'Do not answer questions or add commentary.\n\n' +
          spoken,
      },
    });
    if (!ok) {
      STATE.pendingSpeak = false;
      _setPhase('listening');
      _notify(
        _t('gpt_voice_speak_fallback', 'Smedley Voice not ready — reply was not spoken'),
        'warning'
      );
    }
  }

  function _submitTranscript(text) {
    const cleaned = String(text || '').trim();
    if (!cleaned) return;
    // One automatic submission per voice turn. Server VAD can emit several
    // transcription events for a single utterance, and each extra submission
    // would queue another Hermes run.
    if (STATE.turnSubmitted) return;
    // Physical hold still down: never auto-submit / never clear talking.
    // Mid-hold VAD completions were the "disconnect after a few seconds" bug.
    if (!_handsFree() && STATE.talking) {
      _trace('submit_blocked_while_talking', { chars: cleaned.length });
      return;
    }
    const msg = $('msg');
    if (!msg) return;
    STATE.turnSubmitted = true;
    STATE.talking = false;
    STATE.pttParts = [];
    _setMicEnabled(false);
    _closeCapture();
    _trace('submit_transcript', { chars: cleaned.length, preview: cleaned.slice(0, 80) });
    if (window._voiceModeActive) {
      try {
        if (typeof _stopVoiceMode === 'function') _stopVoiceMode();
      } catch (_) {}
    }
    msg.value = cleaned;
    msg.dispatchEvent(new Event('input', { bubbles: true }));
    _setPhase('processing');
    if (typeof send === 'function') {
      Promise.resolve(send()).catch((err) => {
        _setPhase('error', String(err && err.message ? err.message : err));
        setTimeout(() => {
          if (STATE.active) _setPhase('listening');
        }, 2000);
      });
    }
  }

  function _onServerEvent(raw) {
    let event;
    try {
      event = JSON.parse(raw);
    } catch (_) {
      return;
    }
    const type = event && event.type;
    if (!type) return;
    _trace('realtime_event', {
      type: type,
      dcState: STATE.dc ? STATE.dc.readyState : null,
      pcState: STATE.pc ? STATE.pc.connectionState : null,
      transcriptChars:
        type.indexOf('transcription') >= 0
          ? String((event && event.transcript) || '').length
          : undefined,
    });

    if (type === 'error') {
      const msg =
        (event.error && (event.error.message || event.error.code)) ||
        _t('gpt_voice_error', 'Smedley Voice error');
      _setPhase('error', String(msg));
      return;
    }

    if (type === 'session.updated' || type === 'session.created') {
      try {
        const input = event.session && event.session.audio && event.session.audio.input;
        const td = input && input.turn_detection;
        const tr = input && input.transcription;
        _trace('session_turn_detection', {
          turn_detection: td === null ? null : td || '(absent)',
          transcription: tr || '(absent)',
        });
      } catch (_) {}
      return;
    }

    if (type === 'input_audio_buffer.speech_started') {
      // Only a live mic represents the operator speaking; anything else is
      // leaked playback and must not cancel or restart the turn.
      if (!STATE.micLive) return;
      if (STATE.pendingSpeak) {
        _cancelModelResponse();
        STATE.pendingSpeak = false;
      }
      // Already listening with a live mic: do not re-enter phase (avoids
      // historical pulse-mute). Only promote from non-listening phases.
      if (STATE.phase !== 'listening') _setPhase('listening');
      return;
    }

    if (type === 'input_audio_buffer.speech_stopped') {
      _trace('speech_stopped');
      return;
    }

    if (type === 'input_audio_buffer.committed') {
      _trace('audio_buffer_committed');
      return;
    }

    if (type === 'response.created' && STATE.suppressAutoResponse && !STATE.pendingSpeak) {
      _cancelModelResponse();
      return;
    }

    if (
      type === 'conversation.item.input_audio_transcription.completed'
    ) {
      // Audio captured outside an open capture window is either our own
      // playback echoing back or speech that arrived mid-turn; either way it
      // must not become a Hermes turn.
      if (!STATE.captureOpen) return;
      if (STATE.phase === 'speaking' || STATE.phase === 'processing') return;
      const transcript = event.transcript || '';
      const cleaned = String(transcript || '').trim();
      if (!cleaned) return;
      STATE.lastTranscript = cleaned;
      // Hold-to-talk: keep capturing for the full physical press. Server VAD
      // may complete segments during a long hold; stash them and wait for
      // actual button/pedal release before submitting.
      if (!_handsFree()) {
        if (!Array.isArray(STATE.pttParts)) STATE.pttParts = [];
        STATE.pttParts.push(cleaned);
        STATE.lastTranscript = STATE.pttParts.join(' ').trim();
        _trace('ptt_part_stashed', {
          parts: STATE.pttParts.length,
          chars: STATE.lastTranscript.length,
          talking: STATE.talking,
        });
        if (STATE.talking) return;
        _submitTranscript(STATE.lastTranscript);
        return;
      }
      _submitTranscript(cleaned);
      return;
    }

    if (type === 'response.done' || type === 'response.output_audio.done') {
      if (STATE.pendingSpeak) {
        STATE.pendingSpeak = false;
        if (STATE.active) _setPhase('listening');
      }
    }
  }

  async function _connect() {
    // Order matters: browsers remove navigator.mediaDevices entirely on
    // insecure origins, so an unchecked capability probe misreports a plain
    // HTTP origin as an unsupported browser.
    if (!window.isSecureContext) {
      const base = _t(
        'gpt_voice_insecure_context',
        'Microphone capture needs a secure page (HTTPS or localhost)'
      );
      throw _categoryError(
        'configuration',
        base + ' — this page is ' + (location.origin || 'an insecure origin') + '.'
      );
    }
    if (!_webrtcSupported()) {
      throw _categoryError(
        'configuration',
        _t(
          'gpt_voice_unsupported',
          'WebRTC or microphone APIs are unavailable in this browser'
        )
      );
    }
    _setPhase('connecting');

    let tokenRes;
    try {
      tokenRes = await fetch(
        new URL('api/realtime/session', document.baseURI || location.href).href,
        { method: 'POST', credentials: 'include', headers: { Accept: 'application/json' } }
      );
    } catch (err) {
      throw _categoryError(
        'session',
        _t('gpt_voice_session_unreachable', 'Could not reach the Hermes session endpoint')
      );
    }
    let tokenData = null;
    try {
      tokenData = await tokenRes.json();
    } catch (_) {
      tokenData = null;
    }
    if (!tokenRes.ok) {
      const category =
        (tokenData && tokenData.category) || (tokenRes.status === 401 ? 'configuration' : 'session');
      throw _categoryError(
        category,
        (tokenData && tokenData.error) ||
          _t('gpt_voice_session_failed', 'Could not create Smedley Voice session') +
            ' (HTTP ' + tokenRes.status + ')'
      );
    }
    const ephemeral = tokenData && tokenData.value;
    if (!ephemeral) {
      throw _categoryError(
        'session',
        _t('gpt_voice_session_failed', 'Could not create Smedley Voice session')
      );
    }

    const pc = new RTCPeerConnection();
    STATE.pc = pc;
    const audioEl = document.createElement('audio');
    audioEl.autoplay = true;
    audioEl.setAttribute('playsinline', 'true');
    audioEl.style.display = 'none';
    document.body.appendChild(audioEl);
    STATE.audioEl = audioEl;
    pc.ontrack = (e) => {
      audioEl.srcObject = e.streams[0];
    };

    let media;
    try {
      media = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (err) {
      const name = (err && err.name) || '';
      if (name === 'NotFoundError' || name === 'OverconstrainedError') {
        throw _categoryError(
          'configuration',
          _t('gpt_voice_mic_missing', 'No microphone input device was found')
        );
      }
      throw _categoryError(
        'permission',
        name === 'NotAllowedError' || name === 'SecurityError'
          ? _t('gpt_voice_mic_denied', 'Microphone permission denied or unavailable')
          : _t('gpt_voice_mic_failed', 'Microphone could not be started') +
              (name ? ' (' + name + ')' : '')
      );
    }
    // Physical-mic outbound path:
    //   RTC sender starts on a silent WebAudio placeholder track.
    //   PTT hold → replaceTrack(raw getUserMedia track), always enabled.
    //   PTT release → replaceTrack(silent).
    // Do NOT send mic via MediaStreamDestination — WebAudio inject could
    // reach OpenAI while real getUserMedia through that graph stayed silent.
    STATE.rawMic = media;
    STATE.media = media;
    STATE.micTrack = media.getAudioTracks()[0] || null;
    if (STATE.micTrack) {
      try {
        STATE.micTrack.enabled = true;
      } catch (_) {}
    }
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      if (ctx.state === 'suspended') {
        try {
          await ctx.resume();
        } catch (_) {}
      }
      const dest = ctx.createMediaStreamDestination();
      // Keep the silent graph alive so the placeholder track stays live.
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      gain.gain.value = 0.0;
      osc.connect(gain);
      gain.connect(dest);
      osc.start();
      STATE.audioCtx = ctx;
      STATE.micGain = gain;
      STATE.silentTrack = dest.stream.getAudioTracks()[0] || null;
      STATE.outbound = dest.stream;
      if (STATE.silentTrack) STATE.silentTrack.enabled = true;
      _trace('audio_replace_gate_ready', {
        micTrack: STATE.micTrack ? STATE.micTrack.id : null,
        silentTrack: STATE.silentTrack ? STATE.silentTrack.id : null,
        micLabel: STATE.micTrack ? STATE.micTrack.label : '',
      });
    } catch (err) {
      _trace('audio_replace_gate_failed', {
        error: String(err && err.message ? err.message : err),
      });
      STATE.silentTrack = null;
    }
    const initial = STATE.silentTrack || STATE.micTrack;
    if (!initial) {
      throw _categoryError(
        'configuration',
        _t('gpt_voice_mic_missing', 'No microphone input device was found')
      );
    }
    STATE.audioSender = pc.addTrack(initial, STATE.silentTrack ? STATE.outbound : media);
    // Start gated off (silent placeholder on the wire).
    _setMicEnabled(false);

    const dc = pc.createDataChannel('oai-events');
    STATE.dc = dc;
    dc.addEventListener('message', (e) => _onServerEvent(e.data));
    dc.addEventListener('open', () => {
      _trace('datachannel_open');
      // partial session.update that blanked turn detection wiped
      // audio.input.transcription and produced commits with no transcripts.
      const transcription = { model: 'gpt-4o-mini-transcribe' };
      if (_handsFree()) {
        _sendEvent({
          type: 'session.update',
          session: {
            type: 'realtime',
            audio: {
              input: {
                transcription: transcription,
                turn_detection: {
                  type: 'server_vad',
                  create_response: false,
                  interrupt_response: true,
                  silence_duration_ms: HANDS_FREE_SILENCE_MS,
                  prefix_padding_ms: 300,
                },
              },
            },
          },
        });
        _trace('handsfree_vad_enabled', {
          silence_duration_ms: HANDS_FREE_SILENCE_MS,
          transcription: true,
        });
      } else {
        // PTT: keep server_vad + transcription, but use a long silence window
        // so mid-hold pauses do not end the utterance. Client still blocks
        // submit while talking and commits on physical release.
        _sendEvent({
          type: 'session.update',
          session: {
            type: 'realtime',
            audio: {
              input: {
                transcription: transcription,
                turn_detection: {
                  type: 'server_vad',
                  create_response: false,
                  interrupt_response: true,
                  silence_duration_ms: 10000,
                  prefix_padding_ms: 300,
                },
              },
            },
          },
        });
        _trace('ptt_vad_long_silence', {
          silence_duration_ms: 10000,
          transcription: true,
        });
      }
      if (STATE.active) _setPhase('listening');
    });

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    let sdpResponse;
    try {
      sdpResponse = await fetch('https://api.openai.com/v1/realtime/calls', {
        method: 'POST',
        body: offer.sdp,
        headers: {
          Authorization: 'Bearer ' + ephemeral,
          'Content-Type': 'application/sdp',
        },
      });
    } catch (err) {
      // A blocked cross-origin request surfaces here with no status, which in
      // practice means CSP connect-src or the network refused api.openai.com.
      throw _categoryError(
        'webrtc',
        _t(
          'gpt_voice_webrtc_blocked',
          'Browser could not reach api.openai.com (blocked by CSP, proxy, or network)'
        )
      );
    }
    if (!sdpResponse.ok) {
      const detail = await sdpResponse.text().catch(() => '');
      throw _categoryError(
        'webrtc',
        _t('gpt_voice_webrtc_failed', 'WebRTC connect failed') +
          ' (HTTP ' + sdpResponse.status + ')' +
          (detail ? ': ' + detail.slice(0, 160) : '')
      );
    }
    const answer = { type: 'answer', sdp: await sdpResponse.text() };
    await pc.setRemoteDescription(answer);

    // ICE can still fail after the SDP answer, so report it instead of
    // sitting silently in "connecting".
    pc.addEventListener('connectionstatechange', () => {
      if (pc !== STATE.pc || !STATE.active) return;
      _trace('pc_state', { connectionState: pc.connectionState });
      if (pc.connectionState === 'failed') {
        _reportFailure(
          _categoryError(
            'webrtc',
            _t('gpt_voice_ice_failed', 'Audio connection failed (ICE could not establish a path)')
          )
        );
      } else if (pc.connectionState === 'disconnected') {
        _setPhase('error', _t('gpt_voice_ice_lost', 'Smedley Voice · audio connection lost'));
      }
    });
  }

  function lastAssistantPttOwned() {
    try {
      const msgs = (typeof S !== 'undefined' && Array.isArray(S.messages)) ? S.messages : [];
      for (let i = msgs.length - 1; i >= 0; i--) {
        const m = msgs[i];
        if (!m || m.role !== 'assistant') continue;
        return !!(m.ptt_owned_tts || m.tts_owner === 'pedal_austin');
      }
    } catch (_) {}
    return false;
  }

  function smedleyPttOwnsCompletedTurn() {
    // Scope ownership to the actual displayed turn via its server-stamped
    // ptt_owned_tts/tts_owner marker only. A wall-clock window keyed off
    // "any LEFT-pedal busy heartbeat" (formerly __smedleyPttOwnsVoiceUntil)
    // silenced Austin for unrelated GUI/typed turns whenever the physical
    // pedal happened to be busy for any reason within the prior 20s —
    // confirmed root cause of a silent-voice incident on 2026-08-18.
    return lastAssistantPttOwned();
  }

  function selectSmedleyVoiceEmitter(opts) {
    // LEFT PTT owns Austin for that completed turn. Realtime/browser stay
    // available as features, but must not emit on the same turn.
    if (smedleyPttOwnsCompletedTurn()) return 'none';
    return 'austin';
  }
  try { window.selectSmedleyVoiceEmitter = selectSmedleyVoiceEmitter; } catch (_) {}

  function _hookHermesReplySpeech() {
    if (_origAutoRead) return;
    if (typeof autoReadLastAssistant !== 'function') return;
    _origAutoRead = autoReadLastAssistant;
    window.autoReadLastAssistant = function () {
      if (typeof _origAutoRead === 'function') {
        return _origAutoRead.apply(this, arguments);
      }
    };
  }

  function _unhookHermesReplySpeech() {
    if (_origAutoRead) {
      window.autoReadLastAssistant = _origAutoRead;
      _origAutoRead = null;
    }
  }

  function _reportFailure(err) {
    const message = _describeError(err);
    _cleanupMedia();
    STATE.active = false;
    _unhookHermesReplySpeech();
    _setPhase('error', message);
    _notify(message, 'error');
    const bar = $('gptVoiceBar');
    if (bar) {
      setTimeout(() => {
        if (!STATE.active) bar.style.display = 'none';
      }, 6000);
    }
  }

  function _biggyV6VoiceController() {
    const controller = window.__biggyV6VoiceController;
    return controller && typeof controller === 'object' ? controller : null;
  }

  function beginTalk() {
    const local = _biggyV6VoiceController();
    if (local && typeof local.beginTalk === 'function') {
      local.beginTalk();
      return;
    }
    if (!STATE.active || _handsFree()) return;
    if (STATE.phase === 'connecting' || STATE.phase === 'processing') return;
    // Holding Talk during playback is a deliberate barge-in.
    if (STATE.phase === 'speaking' || STATE.pendingSpeak) _stopPlayback();
    STATE.talking = true;
    STATE.turnSubmitted = false;
    STATE.pttParts = [];
    STATE.lastTranscript = '';
    STATE.peakRms = 0;
    STATE.framesAboveNoise = 0;
    STATE.outboundBytesDelta = 0;
    STATE._lastBytesSent = null;
    _trace('begin_talk');
    try {
      if (STATE.audioCtx && STATE.audioCtx.state === 'suspended') {
        STATE.audioCtx.resume();
      }
    } catch (_) {}
    // Drop any pre-hold audio so release commits only this press.
    try {
      _sendEvent({ type: 'input_audio_buffer.clear' });
    } catch (_) {}
    _setPhase('listening');
    _clearMicRearm();
    _setMicEnabled(true);
    _openCapture();
    _sampleOutboundRtc('begin_talk');
  }

  function endTalk() {
    const local = _biggyV6VoiceController();
    if (local && typeof local.endTalk === 'function') {
      local.endTalk();
      return;
    }
    if (!STATE.talking) return;
    STATE.talking = false;
    _sampleOutboundRtc('end_talk');
    _trace('end_talk', {
      parts: (STATE.pttParts || []).length,
      chars: (STATE.lastTranscript || '').length,
      peakRms: STATE.peakRms,
      framesAboveNoise: STATE.framesAboveNoise,
      outboundBytesDelta: STATE.outboundBytesDelta || 0,
      lastRtc: STATE.lastRtcOutbound || null,
    });
    // Swap sender back to silent immediately; keep captureOpen for transcript.
    _clearMicRearm();
    _setMicEnabled(false);
    try {
      _sendEvent({ type: 'input_audio_buffer.commit' });
      _trace('commit_sent', {
        peakRms: STATE.peakRms,
        framesAboveNoise: STATE.framesAboveNoise,
        outboundBytesDelta: STATE.outboundBytesDelta || 0,
      });
    } catch (_) {}
    _clearCaptureGrace();
    _captureGraceTimer = setTimeout(() => {
      _captureGraceTimer = null;
      if (
        STATE.captureOpen &&
        !STATE.turnSubmitted &&
        !_handsFree() &&
        STATE.lastTranscript
      ) {
        _submitTranscript(STATE.lastTranscript);
      } else if (
        STATE.captureOpen &&
        !STATE.turnSubmitted &&
        !_handsFree() &&
        STATE.framesAboveNoise < 3
      ) {
        _trace('end_talk_no_audio', {
          peakRms: STATE.peakRms,
          framesAboveNoise: STATE.framesAboveNoise,
          outboundBytesDelta: STATE.outboundBytesDelta || 0,
        });
        _notify(
          _voiceCopy(
            _t(
              'gpt_voice_no_audio',
              'No microphone audio was captured — check mic input and try again'
            )
          ),
          'warning'
        );
      }
      STATE.captureOpen = false;
    }, CAPTURE_GRACE_MS);
    _setPhase(STATE.phase);
  }

  async function startGptVoice() {
    const local = _biggyV6VoiceController();
    if (local && typeof local.start === 'function') {
      return local.start();
    }
    if (STATE.active) return;
    STATE.active = true;
    try { window.__smedleyRealtimeVoiceActive = true; } catch (_) {}
    _hookHermesReplySpeech();
    try {
      await _connect();
      _startRunWatch();
      _setPhase('listening');
    } catch (err) {
      _reportFailure(err);
    }
  }

  function stopGptVoice(options) {
    const local = _biggyV6VoiceController();
    if (local && typeof local.stop === 'function'
        && typeof local.isActive === 'function' && local.isActive()) {
      local.stop(options || {});
      return;
    }
    const cancelRun = !!(options && options.cancelRun);
    // Silence the speaker before tearing the transport down so Stop is
    // audibly immediate.
    _stopPlayback();
    STATE.active = false;
    try { window.__smedleyRealtimeVoiceActive = false; } catch (_) {}
    _cleanupMedia();
    _unhookHermesReplySpeech();
    _setPhase('idle');
    // An explicit Stop should also drop a Hermes run that this voice turn
    // started, otherwise its reply arrives after the operator stopped.
    if (cancelRun && typeof cancelStream === 'function') {
      try {
        cancelStream('gpt-voice-stop');
      } catch (_) {}
    }
  }

  async function toggleGptVoice() {
    const local = _biggyV6VoiceController();
    if (local && typeof local.toggle === 'function') return local.toggle();
    if (STATE.active) stopGptVoice();
    else await startGptVoice();
  }

  function applyGptVoiceButtonVisibility(enabled) {
    const btn = $('btnGptVoice');
    if (!btn) return;
    const hide = localStorage.getItem('hermes-hide-composer-gpt-voice') === '1';
    const show = !!enabled && !hide;
    btn.style.display = show ? '' : 'none';
    if (!show && STATE.active) stopGptVoice();
  }

  function _bindTalkControl() {
    const talkBtn = $('btnGptVoiceTalk');
    if (!talkBtn || talkBtn.dataset.bound === '1') return;
    talkBtn.dataset.bound = '1';
    const press = (e) => {
      e.preventDefault();
      // Capture the pointer so leaving the button bounds does not end talk.
      // Release must come from pointerup / lostpointercapture only.
      try {
        if (e.pointerId != null) talkBtn.setPointerCapture(e.pointerId);
      } catch (_) {}
      beginTalk();
    };
    const releaseFromPointer = (e) => {
      e.preventDefault();
      endTalk();
    };
    talkBtn.addEventListener('pointerdown', press);
    talkBtn.addEventListener('pointerup', releaseFromPointer);
    // Actual capture loss (OS/user released). Do not treat pointerleave or
    // pointercancel as release — those were unintended mid-hold disconnects.
    talkBtn.addEventListener('lostpointercapture', () => {
      if (STATE.talking) endTalk();
    });
    talkBtn.addEventListener('contextmenu', (e) => e.preventDefault());
  }

  function stopCurrentResponse() {
    const local = _biggyV6VoiceController();
    if (local && typeof local.stopResponse === 'function'
        && typeof local.isActive === 'function' && local.isActive()) {
      local.stopResponse();
      return;
    }
    _stopPlayback();
    if (typeof cancelStream === 'function') {
      try {
        cancelStream('gpt-voice-stop-response');
      } catch (_) {}
    }
    STATE.turnSubmitted = false;
    if (STATE.active) _setPhase('listening');
  }

  function _bindStopControl() {
    const stopBtn = $('btnGptVoiceStop');
    if (!stopBtn || stopBtn.dataset.bound === '1') return;
    stopBtn.dataset.bound = '1';
    stopBtn.addEventListener('click', (e) => {
      e.preventDefault();
      // Mid-turn this interrupts the response but keeps the session; when idle
      // it disconnects. Stop should not always mean "shut down voice".
      if (STATE.phase === 'processing' || STATE.phase === 'speaking') {
        stopCurrentResponse();
      } else {
        stopGptVoice({ cancelRun: true });
      }
    });
  }

  function initGptVoiceUi() {
    _bindTalkControl();
    _bindStopControl();
    const btn = $('btnGptVoice');
    if (!btn || btn.dataset.bound === '1') return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      toggleGptVoice();
    });
    const pref =
      localStorage.getItem('hermes-gpt-realtime-voice') === '1' ||
      localStorage.getItem('hermes-gpt-realtime-voice') === 'true';
    applyGptVoiceButtonVisibility(pref);
  }

  window.startGptVoice = startGptVoice;
  window.stopGptVoice = stopGptVoice;
  window.toggleGptVoice = toggleGptVoice;
  window.beginGptVoiceTalk = beginTalk;
  window.endGptVoiceTalk = endTalk;
  window.stopGptVoiceResponse = stopCurrentResponse;
  window.applyGptVoiceButtonVisibility = applyGptVoiceButtonVisibility;
  window._gptVoiceActive = function () {
    const local = _biggyV6VoiceController();
    return local && typeof local.isActive === 'function' ? !!local.isActive() : !!STATE.active;
  };
  window._gptVoicePhase = function () {
    return STATE.phase;
  };
  window._gptVoiceMicLive = function () {
    return !!STATE.micLive;
  };
  window._gptVoiceTalking = function () {
    return !!STATE.talking;
  };
  window._gptVoiceCaptureOpen = function () {
    return !!STATE.captureOpen;
  };
  /** Test/smoke only: arm hold-to-talk gates without a live WebRTC session. */
  window.__gptVoiceArmHoldForTest = function () {
    STATE.active = true;
    try { window.__smedleyRealtimeVoiceActive = true; } catch (_) {}
    STATE.phase = 'listening';
    STATE.talking = false;
    STATE.turnSubmitted = false;
    STATE.captureOpen = false;
    STATE.pttParts = [];
    return true;
  };
  window.__biggyVoiceClearTrace = function () {
    _TRACE.length = 0;
    try {
      window.__biggyVoiceTrace = _TRACE;
    } catch (_) {}
    return true;
  };
  window.__biggyVoiceDumpTrace = function () {
    return _TRACE.slice();
  };
  window.__biggyVoiceAudioStats = function () {
    const media = STATE.rawMic || STATE.media;
    const tracks = media
      ? media.getAudioTracks().map((tr) => ({
          id: tr.id,
          label: tr.label,
          enabled: tr.enabled,
          muted: tr.muted,
          readyState: tr.readyState,
          settings: typeof tr.getSettings === 'function' ? tr.getSettings() : null,
        }))
      : [];
    const sender =
      STATE.audioSender ||
      (STATE.pc
        ? STATE.pc.getSenders().find((s) => s.track && s.track.kind === 'audio')
        : null);
    return {
      micLive: !!STATE.micLive,
      talking: !!STATE.talking,
      captureOpen: !!STATE.captureOpen,
      gate: STATE.micTrack && STATE.silentTrack ? 'replace' : 'legacy',
      lastRms: STATE.lastRms,
      peakRms: STATE.peakRms,
      framesAboveNoise: STATE.framesAboveNoise,
      outboundBytesDelta: STATE.outboundBytesDelta || 0,
      lastRtcOutbound: STATE.lastRtcOutbound || null,
      lastTranscript: STATE.lastTranscript,
      pttParts: (STATE.pttParts || []).slice(),
      turnSubmitted: !!STATE.turnSubmitted,
      phase: STATE.phase,
      pcState: STATE.pc ? STATE.pc.connectionState : null,
      dcState: STATE.dc ? STATE.dc.readyState : null,
      micLabel: STATE.micTrack ? STATE.micTrack.label : '',
      tracks: tracks,
      senderTrack: sender && sender.track
        ? {
            id: sender.track.id,
            label: sender.track.label || '',
            enabled: sender.track.enabled,
            muted: sender.track.muted,
            readyState: sender.track.readyState,
            isMic: !!(STATE.micTrack && sender.track.id === STATE.micTrack.id),
            isSilent: !!(STATE.silentTrack && sender.track.id === STATE.silentTrack.id),
          }
        : null,
    };
  };
  /**
   * Diagnostic inject only — NOT physical-mic acceptance.
   * Temporarily replaceTrack with decoded WAV, then restore mic/silent gate.
   */
  window.__biggyVoiceInjectSpokenPrompt = async function (opts) {
    const o = opts || {};
    const pc = STATE.pc;
    if (!pc) return { ok: false, reason: 'no_pc' };
    const sender =
      STATE.audioSender ||
      pc.getSenders().find((s) => s.track && s.track.kind === 'audio');
    if (!sender) return { ok: false, reason: 'no_audio_sender' };
    if (!STATE.audioCtx) return { ok: false, reason: 'no_audio_ctx' };
    const ctx = STATE.audioCtx;
    try {
      if (ctx.state === 'suspended') await ctx.resume();
    } catch (_) {}
    const dest = ctx.createMediaStreamDestination();
    const gain = ctx.createGain();
    gain.gain.value = 0.9;
    gain.connect(dest);
    let mode = 'tone_replace';
    try {
      if (o.audioUrl) {
        const resp = await fetch(String(o.audioUrl), { credentials: 'include' });
        const buf = await resp.arrayBuffer();
        const audioBuf = await ctx.decodeAudioData(buf.slice(0));
        const src = ctx.createBufferSource();
        src.buffer = audioBuf;
        src.connect(gain);
        src.start();
        mode = 'wav_replace';
        const track = dest.stream.getAudioTracks()[0];
        track.enabled = true;
        await sender.replaceTrack(track);
        STATE.audioSender = sender;
        _setMicEnabled(true);
        _trace('spoken_inject_start', {
          mode: mode,
          duration_s: audioBuf.duration,
          note: 'diagnostic_only_not_acceptance',
        });
        await new Promise((r) => setTimeout(r, Math.ceil(audioBuf.duration * 1000) + 250));
        try {
          src.stop();
        } catch (_) {}
        _trace('spoken_inject_done', { mode: mode });
        // Restore physical gate track (mic if live, else silent).
        const restore = STATE.micLive && STATE.micTrack ? STATE.micTrack : STATE.silentTrack;
        if (restore) await sender.replaceTrack(restore);
        return {
          ok: true,
          mode: mode,
          duration_s: audioBuf.duration,
          acceptance: false,
          peakRms: STATE.peakRms,
          framesAboveNoise: STATE.framesAboveNoise,
          outboundBytesDelta: STATE.outboundBytesDelta || 0,
        };
      }
    } catch (err) {
      _trace('spoken_inject_wav_failed', {
        error: String(err && err.message ? err.message : err),
      });
    }
    return { ok: false, reason: 'inject_failed', acceptance: false };
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initGptVoiceUi);
  } else {
    initGptVoiceUi();
  }
})();
