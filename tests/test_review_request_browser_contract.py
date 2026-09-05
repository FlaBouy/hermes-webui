"""Execute the actual review Send callback with a failed network response.

This is a JS interaction test, not a physical-display or browser layout claim.
"""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_network_retry_keeps_identity_and_restores_draft():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    script = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync('static/biggy-brand.js', 'utf8');
const marker = "dialog.querySelector('#biggyProjectDialogSend').addEventListener('click', ";
const start = source.indexOf(marker) + marker.length;
const end = source.indexOf("    pane.querySelectorAll('[data-biggy-location-target]')", start);
assert(start >= marker.length && end > start);
const callbackSource = source.slice(start, end).trim().slice(0, -2);
const input = {value: 'What discrepancy is that?'}, button = {}, html = [];
const list = {querySelector: () => null, insertAdjacentHTML: (_, text) => html.push(text)};
const storage = new Map(), requests = [];
const context = {
  crypto: {randomUUID: () => 'request-' + requests.length},
  sessionStorage: {getItem: k => storage.get(k), setItem: (k,v) => storage.set(k,v)},
  dialog: {hidden: false, querySelector: s => s.endsWith('Input') ? input : s.endsWith('Send') ? button : list},
  dialogProject: {project_id: 'project-a'}, dialogSpeechId: '',
  reviewDictation: {cancel() {}}, reviewSpeechGate: {arm() {}, reset() {}},
  esc: s => s, renderDialog: () => {},
  window: {api: async (_, opts) => {
    requests.push(JSON.parse(opts.body));
    if (requests.length === 1) throw new Error('Network response lost');
    return {ok: true};
  }},
};
const callback = vm.runInNewContext('(' + callbackSource + ')', context);
(async () => {
  await callback();
  assert.equal(input.value, 'What discrepancy is that?');
  assert(html.some(text => text.includes('Reply not confirmed')));
  assert(!html.some(text => text.includes('Message was not sent')));
  await callback();
  assert.equal(requests.length, 2);
  assert.equal(requests[0].request_id, requests[1].request_id);
  assert.equal(requests[0].project_id, 'project-a');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
