"""Behavioral tests for Smedley live electrical recalculation helper."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIVE_JS = ROOT / "extensions" / "smedley-engineering" / "smedley-live-tools.v0.2.5.js"
ENGINEERING_JS = ROOT / "extensions" / "smedley-engineering" / "smedley-engineering.v0.2.5.js"
MANIFEST = ROOT / "extensions" / "smedley-engineering" / "manifest.json"
NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")


MINIMAL_DOM = r"""
class TokenList {
  constructor(el) { this._el = el; this._set = new Set(); }
  _sync() { this._el.className = Array.from(this._set).join(' '); }
  add(...tokens) { tokens.forEach((t) => this._set.add(t)); this._sync(); }
  remove(...tokens) { tokens.forEach((t) => this._set.delete(t)); this._sync(); }
  contains(token) { return this._set.has(token); }
  toggle(token, force) {
    if (force === true) this.add(token);
    else if (force === false) this.remove(token);
    else if (this.contains(token)) this.remove(token); else this.add(token);
  }
}

class Element {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.attributes = Object.create(null);
    this.className = '';
    this.classList = new TokenList(this);
    this.style = {};
    this._listeners = Object.create(null);
    this.value = '';
    this.name = '';
    this.type = '';
    this.required = false;
    this.min = '';
    this.max = '';
    this.step = '';
    this.disabled = false;
    this.textContent = '';
    this._innerHTML = '';
    this.parentElement = null;
    this.rows = 0;
    this.inputMode = '';
  }
  get innerHTML() { return this._innerHTML; }
  set innerHTML(value) {
    this._innerHTML = String(value ?? '');
    this.textContent = this._innerHTML.replace(/<[^>]+>/g, '');
  }
  appendChild(child) {
    child.parentElement = this;
    this.children.push(child);
    return child;
  }
  remove() {
    if (!this.parentElement) return;
    this.parentElement.children = this.parentElement.children.filter((c) => c !== this);
    this.parentElement = null;
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  getAttribute(name) { return this.attributes[name] ?? null; }
  closest(selector) {
    let node = this;
    while (node) {
      if (selector === 'label' && node.tagName === 'LABEL') return node;
      node = node.parentElement;
    }
    return null;
  }
  matches(selector) {
    if (selector === 'input,select,textarea') {
      return ['INPUT', 'SELECT', 'TEXTAREA'].includes(this.tagName);
    }
    if (selector === 'span') return this.tagName === 'SPAN';
    if (selector.startsWith('.')) return this.classList.contains(selector.slice(1));
    return this.tagName === selector.toUpperCase();
  }
  querySelector(selector) {
    const all = this.querySelectorAll(selector);
    return all[0] || null;
  }
  querySelectorAll(selector) {
    const out = [];
    const walk = (node) => {
      for (const child of node.children) {
        if (child.matches(selector)) out.push(child);
        walk(child);
      }
    };
    walk(this);
    return out;
  }
  addEventListener(type, fn) {
    (this._listeners[type] ||= []).push(fn);
  }
  removeEventListener(type, fn) {
    this._listeners[type] = (this._listeners[type] || []).filter((x) => x !== fn);
  }
  dispatchEvent(event) {
    const type = event.type;
    let node = this;
    while (node) {
      for (const fn of node._listeners[type] || []) fn(event);
      node = node.parentElement;
    }
  }
}

const document = {
  createElement(tag) { return new Element(tag); },
};
globalThis.document = document;

function labelControl(name, opts = {}) {
  const label = document.createElement('label');
  const span = document.createElement('span');
  span.textContent = opts.label || name;
  label.appendChild(span);
  const tag = opts.tag || 'input';
  const control = document.createElement(tag);
  control.name = name;
  control.type = opts.type || (
    tag === 'textarea' ? 'textarea' : tag === 'select' ? 'select' : 'number'
  );
  control.value = opts.value == null ? '' : String(opts.value);
  control.required = !!opts.required;
  if (opts.min != null) control.min = String(opts.min);
  if (opts.max != null) control.max = String(opts.max);
  if (opts.step != null) control.step = String(opts.step);
  label.appendChild(control);
  return {label, control};
}

function buildForm(fields) {
  const form = document.createElement('form');
  const controls = {};
  for (const field of fields) {
    const built = labelControl(field.name, field);
    form.appendChild(built.label);
    controls[field.name] = built.control;
  }
  const run = document.createElement('button');
  run.type = 'button';
  run.textContent = 'RECALCULATE';
  form.appendChild(run);
  const result = document.createElement('div');
  result.className = 'smedley-engineering-result';
  result.innerHTML = '<div class="smedley-engineering-result-empty">ready</div>';
  return {form, run, result, controls};
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
"""


def _run_node(body: str, *, timeout: int = 20) -> dict:
    script = textwrap.dedent(
        f"""
        const live = require({json.dumps(str(LIVE_JS))});
        {MINIMAL_DOM}
        (async () => {{
          {body}
        }})().catch((error) => {{
          console.error(error && error.stack ? error.stack : error);
          process.exit(1);
        }});
        """
    )
    completed = subprocess.run(
        [NODE, "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"node harness failed ({completed.returncode}): {completed.stderr}\n{completed.stdout}"
        )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert lines, f"no stdout from harness: stderr={completed.stderr}"
    return json.loads(lines[-1])


@requires_node
def test_live_helper_syntax_and_manifest_order():
    completed = subprocess.run(
        [NODE, "--check", str(LIVE_JS)], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr
    manifest = json.loads(MANIFEST.read_text())
    scripts = manifest["scripts"]
    assert "smedley-live-tools.v0.2.5.js" in scripts
    assert scripts.index("smedley-live-tools.v0.2.5.js") < scripts.index(
        "smedley-engineering.v0.2.5.js"
    )
    engineering = ENGINEERING_JS.read_text()
    assert "SmedleyLiveTools" in engineering
    assert "liveApi.wire" in engineering
    assert "RECALCULATE" in engineering
    assert "SmedleyVoltageDropSizing" in engineering
    assert "SmedleyElectricalResults" in engineering
    vd_fields = engineering.split("'voltage-drop':")[1].split("'feeder-size':")[0]
    assert "'conductor_awg'" not in vd_fields


@requires_node
def test_validate_form_rejects_incomplete_and_out_of_range_fields():
    payload = _run_node(
        """
        const {form, controls} = buildForm([
          {name:'amps', label:'Load amps', required:true, value:''},
          {name:'power_factor', label:'Power factor', value:'1.2', min:'0', max:'1'},
          {name:'parallel_sets', label:'Parallel sets', value:'0', min:'1', step:'1'},
          {name:'cables', label:'Cables JSON', tag:'textarea', required:true,
           value:'[{"cable_designation":"3C-10","count":0}]'},
        ]);
        const result = live.validateForm(form);
        process.stdout.write(JSON.stringify({
          valid: result.valid,
          errors: result.errors,
          ampsInvalid: controls.amps.getAttribute('aria-invalid'),
          pfInvalid: controls.power_factor.getAttribute('aria-invalid'),
          parallelInvalid: controls.parallel_sets.getAttribute('aria-invalid'),
          cablesInvalid: controls.cables.getAttribute('aria-invalid'),
          marked: form.querySelectorAll('.smedley-engineering-field-invalid').length,
        }));
        """
    )
    assert payload["valid"] is False
    assert "amps" in payload["errors"]
    assert "power_factor" in payload["errors"]
    assert "parallel_sets" in payload["errors"]
    assert "cables" in payload["errors"]
    assert payload["ampsInvalid"] == "true"
    assert payload["pfInvalid"] == "true"
    assert payload["parallelInvalid"] == "true"
    assert payload["cablesInvalid"] == "true"
    assert payload["marked"] == 4


@requires_node
def test_validate_form_accepts_valid_ranges_and_cable_json():
    payload = _run_node(
        """
        const {form} = buildForm([
          {name:'amps', label:'Load amps', required:true, value:'100'},
          {name:'power_factor', label:'Power factor', value:'0.85', min:'0', max:'1'},
          {name:'parallel_sets', label:'Parallel sets', value:'2', min:'1', step:'1'},
          {name:'cables', label:'Cables JSON', tag:'textarea', required:true,
           value:'[{"cable_designation":"3C-10","count":3}]'},
        ]);
        const result = live.validateForm(form);
        process.stdout.write(JSON.stringify(result));
        """
    )
    assert payload["valid"] is True
    assert payload["errors"] == {}


@requires_node
def test_grounding_mode_extra_requires_ocpd_only_for_egc_paths():
    payload = _run_node(
        """
        function groundingExtra(mode) {
          return (controls) => {
            const byName = Object.fromEntries(controls.map((c) => [c.name, c]));
            const errors = {};
            if ((mode === 'egc' || mode === 'both') && !String(byName.ocpd_amps.value || '').trim()) {
              errors.ocpd_amps = 'OCPD amps (EGC) is required for this mode.';
            }
            return errors;
          };
        }
        const fields = [
          {name:'mode', label:'Mode', tag:'select', value:'gec'},
          {name:'ocpd_amps', label:'OCPD amps (EGC)', value:''},
          {name:'service_conductor_size', label:'Service conductor (GEC)', tag:'select', value:'4/0'},
        ];
        const gec = buildForm(fields);
        gec.controls.mode.value = 'gec';
        const gecResult = live.validateForm(gec.form, groundingExtra('gec'));
        const both = buildForm(fields);
        both.controls.mode.value = 'both';
        const bothResult = live.validateForm(both.form, groundingExtra('both'));
        process.stdout.write(JSON.stringify({gecResult, bothResult}));
        """
    )
    assert payload["gecResult"]["valid"] is True
    assert payload["bothResult"]["valid"] is False
    assert "ocpd_amps" in payload["bothResult"]["errors"]


@requires_node
def test_incomplete_edit_invalidates_result_without_api_call():
    payload = _run_node(
        """
        const ui = buildForm([
          {name:'amps', label:'Load amps', required:true, value:'100'},
          {name:'length_ft', label:'One-way length (ft)', required:true, value:'250'},
        ]);
        let calls = 0;
        const liveWire = live.wire({
          form: ui.form,
          result: ui.result,
          run: ui.run,
          debounceMs: 40,
          collectParams: () => ({amps: Number(ui.controls.amps.value), length_ft: Number(ui.controls.length_ft.value)}),
          calculate: async (params) => { calls += 1; return {status:'ok', params}; },
          renderSuccess: (data) => { ui.result.innerHTML = '<div class="ok">' + data.params.amps + '</div>'; },
          renderError: (error) => { ui.result.innerHTML = '<div class="err">' + error.message + '</div>'; },
        });
        await liveWire.calculateNow();
        const afterOk = ui.result.innerHTML;
        ui.controls.amps.value = '';
        ui.controls.amps.dispatchEvent({type:'input', target: ui.controls.amps, preventDefault(){}});
        await sleep(80);
        process.stdout.write(JSON.stringify({
          afterOk,
          afterClear: ui.result.innerHTML,
          calls,
          ampsValue: ui.controls.amps.value,
          lengthValue: ui.controls.length_ft.value,
          ampsInvalid: ui.controls.amps.getAttribute('aria-invalid'),
          runLabel: ui.run.textContent,
        }));
        liveWire.dispose();
        """
    )
    assert "100" in payload["afterOk"]
    assert "Complete the highlighted fields" in payload["afterClear"]
    assert payload["calls"] == 1
    assert payload["ampsValue"] == ""
    assert payload["lengthValue"] == "250"
    assert payload["ampsInvalid"] == "true"
    assert payload["runLabel"] == "RECALCULATE"


@requires_node
def test_live_debounce_and_stale_async_never_overwrite_newer_input():
    payload = _run_node(
        """
        function assert(cond, msg) { if (!cond) throw new Error(msg); }
        const ui = buildForm([
          {name:'amps', label:'Load amps', required:true, value:'10'},
        ]);
        const deferred = [];
        let calls = 0;
        const liveWire = live.wire({
          form: ui.form,
          result: ui.result,
          run: ui.run,
          debounceMs: 30,
          collectParams: () => ({amps: Number(ui.controls.amps.value)}),
          calculate: (params) => new Promise((resolve) => {
            calls += 1;
            deferred.push({params, resolve});
          }),
          renderSuccess: (data) => { ui.result.innerHTML = '<div id="v">' + data.amps + '</div>'; },
          renderError: (error) => { ui.result.innerHTML = '<div id="e">' + error.message + '</div>'; },
        });
        ui.controls.amps.dispatchEvent({type:'input', target: ui.controls.amps, preventDefault(){}});
        await sleep(50);
        ui.controls.amps.value = '55';
        ui.controls.amps.dispatchEvent({type:'input', target: ui.controls.amps, preventDefault(){}});
        await sleep(50);
        assert(deferred.length === 2, 'expected two calculate calls, got ' + deferred.length);
        deferred[0].resolve({amps: deferred[0].params.amps});
        await sleep(10);
        const afterStale = ui.result.innerHTML;
        deferred[1].resolve({amps: deferred[1].params.amps});
        await sleep(10);
        process.stdout.write(JSON.stringify({
          calls,
          afterStale,
          final: ui.result.innerHTML,
          values: deferred.map((row) => row.params.amps),
        }));
        liveWire.dispose();
        """
    )
    assert payload["calls"] == 2
    assert payload["values"] == [10, 55]
    assert "55" in payload["final"]
    assert ">10<" not in payload["final"].replace(" ", "")
    assert "Recalculating" in payload["afterStale"] or "55" in payload["afterStale"]


@requires_node
def test_enter_and_recalculate_bypass_debounce():
    payload = _run_node(
        """
        const ui = buildForm([
          {name:'amps', label:'Load amps', required:true, value:'12'},
        ]);
        let calls = 0;
        const liveWire = live.wire({
          form: ui.form,
          result: ui.result,
          run: ui.run,
          debounceMs: 5000,
          collectParams: () => ({amps: Number(ui.controls.amps.value)}),
          calculate: async (params) => { calls += 1; return params; },
          renderSuccess: (data) => { ui.result.innerHTML = '<div>' + data.amps + '</div>'; },
          renderError: (error) => { ui.result.innerHTML = '<div>' + error.message + '</div>'; },
        });
        ui.form.dispatchEvent({
          type:'keydown', key:'Enter', target: ui.controls.amps, preventDefault(){ this._prevented = true; },
        });
        await sleep(20);
        const afterEnter = {calls, html: ui.result.innerHTML};
        ui.controls.amps.value = '99';
        ui.run.dispatchEvent({type:'click', preventDefault(){}});
        await sleep(20);
        process.stdout.write(JSON.stringify({
          afterEnter,
          afterClick: {calls, html: ui.result.innerHTML, label: ui.run.textContent},
        }));
        liveWire.dispose();
        """
    )
    assert payload["afterEnter"]["calls"] == 1
    assert "12" in payload["afterEnter"]["html"]
    assert payload["afterClick"]["calls"] == 2
    assert "99" in payload["afterClick"]["html"]
    assert payload["afterClick"]["label"] == "RECALCULATE"


@requires_node
def test_valid_form_schedules_live_calculate_for_all_tool_ids_shape():
    """Integration source pin: every tool id is wired through the shared openTool path."""
    source = ENGINEERING_JS.read_text()
    assert "const liveApi = window.SmedleyLiveTools" in source
    assert "liveApi.wire({" in source
    assert "renderResultCard" in source
    for tool_id in (
        "voltage-drop",
        "feeder-size",
        "conductor-sets",
        "ocpd-size",
        "conduit-fill",
        "grounding",
        "cable-tray-fill",
        "motor-circuit",
        "motor-starter",
        "mcc-bucket",
        "vfd-circuit",
    ):
        assert f"'{tool_id}'" in source
    optional_block = source.split("OPTIONAL_EMPTY_FIELDS")[1].split("]")[0]
    assert "'ocpd_amps'" in optional_block
    assert "FIELD_NUMBER_CONSTRAINTS" in source
    constraints = source.split("FIELD_NUMBER_CONSTRAINTS")[1].split("});")[0]
    assert "power_factor" in constraints
    assert "parallel_sets" in constraints
