#!/usr/bin/env node

/* Local-only Google Messages bridge for Biggy.
 *
 * The bridge talks to a dedicated Chrome profile over a loopback-only Chrome
 * DevTools port.  Pairing credentials stay inside that profile; message bodies
 * arrive on stdin and are never placed in process arguments or logs.
 */

const CDP_BASE = String(process.env.BIGGY_GOOGLE_MESSAGES_CDP || 'http://127.0.0.1:9223').replace(/\/$/, '');

async function readInput() {
  let raw = '';
  for await (const chunk of process.stdin) raw += chunk;
  try {
    return JSON.parse(raw || '{}');
  } catch {
    throw new Error('bridge request is not valid JSON');
  }
}

function cleanError(error) {
  return String(error && error.message || error || 'Google Messages bridge failed')
    .replace(/[\r\n]+/g, ' ')
    .slice(0, 500);
}

async function pages() {
  let response;
  try {
    response = await fetch(`${CDP_BASE}/json/list`, { signal: AbortSignal.timeout(2500) });
  } catch {
    throw new Error('Google Messages browser is not running');
  }
  if (!response.ok) throw new Error('Google Messages browser did not answer');
  const result = await response.json();
  return Array.isArray(result) ? result : [];
}

async function messagesPages() {
  const list = await pages();
  const matches = list.filter((item) => item && item.type === 'page'
    && /^https:\/\/messages\.google\.com\/web\//.test(String(item.url || ''))
    && item.webSocketDebuggerUrl);
  if (!matches.length) throw new Error('Google Messages pairing window is not open');
  // A Chrome app restart can leave both a stale welcome tab and the paired
  // conversation tab alive. Never let the stale welcome target mask the
  // usable transport.
  return matches.sort((a, b) => {
    const rank = (item) => /\/web\/(?:welcome|authentication)(?:\/|$)/.test(String(item.url || '')) ? 1 : 0;
    return rank(a) - rank(b);
  });
}

class Cdp {
  constructor(url) {
    this.url = url;
    this.socket = null;
    this.nextId = 1;
    this.pending = new Map();
  }

  async open() {
    this.socket = new WebSocket(this.url);
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Google Messages browser connection timed out')), 3000);
      this.socket.addEventListener('open', () => { clearTimeout(timeout); resolve(); }, { once: true });
      this.socket.addEventListener('error', () => { clearTimeout(timeout); reject(new Error('Google Messages browser connection failed')); }, { once: true });
    });
    this.socket.addEventListener('message', (event) => {
      let message;
      try { message = JSON.parse(String(event.data || '')); } catch { return; }
      if (!message.id || !this.pending.has(message.id)) return;
      const { resolve, reject, timer } = this.pending.get(message.id);
      this.pending.delete(message.id);
      clearTimeout(timer);
      if (message.error) reject(new Error(String(message.error.message || 'Chrome command failed')));
      else resolve(message.result || {});
    });
    this.socket.addEventListener('close', () => {
      for (const { reject, timer } of this.pending.values()) {
        clearTimeout(timer);
        reject(new Error('Google Messages browser connection closed'));
      }
      this.pending.clear();
    });
    await this.call('Runtime.enable');
  }

  call(method, params = {}, timeoutMs = 8000) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return Promise.reject(new Error('Google Messages browser is disconnected'));
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Google Messages ${method} timed out`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression, { awaitPromise = false, timeoutMs = 10000 } = {}) {
    const result = await this.call('Runtime.evaluate', {
      expression,
      awaitPromise,
      returnByValue: true,
      userGesture: true,
    }, timeoutMs);
    if (result.exceptionDetails) throw new Error(String(result.exceptionDetails.text || 'Google Messages page script failed'));
    return result.result ? result.result.value : undefined;
  }

  close() {
    try { this.socket && this.socket.close(); } catch {}
  }
}

const statusExpression = `(() => {
  const body = String(document.body && document.body.innerText || '');
  const path = String(location.pathname || '');
  const signedOut = /\\b(?:welcome to google messages|pair with qr code|sign in)\\b/i.test(body)
    || /\\/(?:welcome|authentication)(?:\\/|$)/.test(path);
  const disconnected = /trying to (?:reach|connect to) your phone|you are signed out|unable to connect/i.test(body);
  const composer = document.querySelector('textarea[aria-label*="message" i], [contenteditable="true"][aria-label*="message" i]');
  const conversationUi = document.querySelector('[aria-label*="start chat" i], [aria-label*="new conversation" i], mw-main-nav, mws-conversations-list');
  return {
    ready: Boolean(!signedOut && !disconnected && (composer || conversationUi)),
    paired: Boolean(!signedOut),
    connected: Boolean(!signedOut && !disconnected),
    page: path,
    detail: signedOut ? 'Pair the dedicated Google Messages window with the Galaxy phone.'
      : (disconnected ? 'Google Messages cannot currently reach the Galaxy phone.' : 'Google Messages is connected.'),
  };
})()`;

async function status(cdp) {
  const value = await cdp.evaluate(statusExpression);
  return value && typeof value === 'object' ? value : { ready: false, paired: false, connected: false, detail: 'Google Messages status is unavailable.' };
}

async function waitFor(cdp, expression, timeoutMs = 8000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await cdp.evaluate(expression)) return true;
    await new Promise((resolve) => setTimeout(resolve, 180));
  }
  return false;
}

async function pressEnter(cdp) {
  await cdp.call('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 36 });
  await cdp.call('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 36 });
}

async function send(cdp, request) {
  const current = await status(cdp);
  if (!current.ready) throw new Error(current.detail || 'Google Messages is not ready');
  const to = String(request.to || '');
  const body = String(request.body || '');
  if (!to || !body) throw new Error('recipient and message body are required');

  const opened = await cdp.evaluate(`(() => {
    const visible = (el) => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
    const text = (el) => String(el.getAttribute('aria-label') || el.title || el.innerText || '').trim();
    const buttons = [...document.querySelectorAll('button, [role="button"]')].filter(visible);
    const button = buttons.find((el) => /^(?:start chat|new conversation|new message|start a conversation)$/i.test(text(el)))
      || buttons.find((el) => /start chat|new conversation|new message/i.test(text(el)));
    if (!button) return false;
    button.click();
    return true;
  })()`);
  if (!opened) throw new Error('Google Messages Start chat control was not found');

  const recipientReady = await waitFor(cdp, `(() => {
    const candidates = [...document.querySelectorAll('input, textarea, [contenteditable="true"]')];
    const input = candidates.find((el) => /name|phone|recipient|email/i.test(String(el.getAttribute('placeholder') || el.getAttribute('aria-label') || '')));
    if (!input) return false;
    input.focus();
    if ('value' in input) input.value = '';
    else input.textContent = '';
    return true;
  })()`);
  if (!recipientReady) throw new Error('Google Messages recipient field was not found');
  await cdp.call('Input.insertText', { text: to });
  await new Promise((resolve) => setTimeout(resolve, 700));

  const selected = await cdp.evaluate(`(() => {
    const digits = ${JSON.stringify(to.replace(/\D/g, ''))};
    const visible = (el) => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
    const rows = [...document.querySelectorAll('[role="option"], [role="listitem"], mws-contact-row, mw-contact-row')].filter(visible);
    const exact = rows.find((el) => String(el.innerText || '').replace(/\\D/g, '').includes(digits));
    if (!exact) return false;
    exact.click();
    return true;
  })()`);
  if (!selected) await pressEnter(cdp);

  const composerReady = await waitFor(cdp, `(() => {
    const candidates = [...document.querySelectorAll('textarea, [contenteditable="true"], input')];
    const composer = candidates.find((el) => /text message|message/i.test(String(el.getAttribute('aria-label') || el.getAttribute('placeholder') || '')))
      || candidates.find((el) => el.getAttribute('contenteditable') === 'true');
    if (!composer) return false;
    composer.focus();
    if ('value' in composer) composer.value = '';
    else composer.textContent = '';
    return true;
  })()`, 10000);
  if (!composerReady) throw new Error('Google Messages composer was not found');
  await cdp.call('Input.insertText', { text: body });
  await new Promise((resolve) => setTimeout(resolve, 250));

  const sent = await cdp.evaluate(`(() => {
    const visible = (el) => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
    const text = (el) => String(el.getAttribute('aria-label') || el.title || el.innerText || '').trim();
    const buttons = [...document.querySelectorAll('button, [role="button"]')].filter(visible);
    const button = buttons.find((el) => /^send(?: message)?$/i.test(text(el)))
      || buttons.find((el) => /send(?: sms)?/i.test(text(el)));
    if (!button || button.disabled || button.getAttribute('aria-disabled') === 'true') return false;
    button.click();
    return true;
  })()`);
  if (!sent) throw new Error('Google Messages Send control was not available');
  return { ok: true, status: 'submitted' };
}

async function main() {
  const request = await readInput();
  const targets = await messagesPages();
  let bestStatus = null;
  for (const page of targets) {
    const cdp = new Cdp(page.webSocketDebuggerUrl);
    try {
      await cdp.open();
      const current = await status(cdp);
      if (!bestStatus || current.ready || (!bestStatus.paired && current.paired)) bestStatus = current;
      if (request.action === 'status' && current.ready) return { ok: true, ...current };
      if (request.action === 'send' && current.ready) return await send(cdp, request);
    } catch {
      // One stale target must not hide a second healthy Messages tab.
    } finally {
      cdp.close();
    }
  }
  if (request.action === 'status') return { ok: true, ...(bestStatus || {
    ready: false, paired: false, connected: false,
    detail: 'Google Messages pairing window is unavailable.',
  }) };
  if (request.action === 'send') throw new Error((bestStatus && bestStatus.detail) || 'Google Messages is not ready');
  throw new Error('unsupported Google Messages bridge action');
}

try {
  process.stdout.write(JSON.stringify(await main()));
} catch (error) {
  process.stdout.write(JSON.stringify({ ok: false, error: cleanError(error) }));
  process.exitCode = 1;
}
