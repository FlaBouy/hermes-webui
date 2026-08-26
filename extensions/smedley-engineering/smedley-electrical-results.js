(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.SmedleyElectricalResults = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const FIELD_LABELS = Object.freeze({
    amps: 'Load amps',
    voltage: 'System voltage (V)',
    length_ft: 'One-way length (ft)',
    conductor_awg: 'Conductor size',
    conductor_size: 'Conductor size',
    parallel_sets: 'Parallel sets',
    ambient_temp_c: 'Ambient temp (C)',
    num_conductors: 'Current-carrying conductors',
    ocpd_amps: 'OCPD amps',
    nameplate_fla: 'Nameplate FLA',
    hp: 'HP',
    drive_input_fla: 'Drive input FLA',
    _fla_val: 'FLA / HP value',
    material: 'Conductor material',
    temp_rating: 'Temp / terminal basis (C)',
    continuous_load: 'Continuous load',
  });

  const COMPLIANCE_WARNING =
    'Result does not establish compliance — required pass/fail or solution proof was not returned.';

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[c]));
  }

  function asList(value) {
    if (!value) return [];
    if (Array.isArray(value)) return value.map((item) => String(item)).filter(Boolean);
    return [String(value)].filter(Boolean);
  }

  function present(value) {
    return value !== undefined && value !== null && String(value).trim() !== '';
  }

  function firstPresent(...values) {
    for (const value of values) {
      if (present(value)) return value;
    }
    return undefined;
  }

  function awg(size) {
    return present(size) ? `${size} AWG` : '';
  }

  function displayValue(value, unit) {
    if (!present(value)) return '';
    return unit ? `${value} ${unit}` : String(value);
  }

  function valueRow(label, value, unit) {
    if (!present(value)) return null;
    return {label, value, unit: unit || '', display: displayValue(value, unit)};
  }

  function pushRow(rows, row) {
    if (row) rows.push(row);
  }

  function conductorSize(result, inputs) {
    return firstPresent(
      result.comparison_size,
      result.recommended_size,
      result.conductor_awg,
      result.conductor_size,
      result.selected_size,
      inputs && inputs.recommended_size,
      inputs && inputs.conductor_awg,
    );
  }

  function recommendationFor(toolId, payload) {
    const result = payload.result || {};
    const inputs = payload.inputs || {};
    switch (toolId) {
      case 'voltage-drop':
        return awg(conductorSize(result, inputs));
      case 'feeder-size':
        return awg(firstPresent(result.conductor_size, result.conductor_awg));
      case 'conductor-sets':
        return awg(firstPresent(result.selected_size, result.conductor_awg, result.conductor_size));
      case 'ocpd-size':
        return present(result.ocpd_size_A) ? `${result.ocpd_size_A} A` : '';
      case 'conduit-fill':
        return String(firstPresent(result.minimum_trade_size, result.trade_size) || '');
      case 'grounding': {
        const parts = [];
        if (result.egc && present(result.egc.size_copper)) {
          parts.push(`EGC ${awg(result.egc.size_copper)}`);
        }
        if (result.gec && present(result.gec.size_copper)) {
          parts.push(`GEC ${awg(result.gec.size_copper)}`);
        }
        return parts.join(' / ');
      }
      case 'cable-tray-fill':
        return present(result.minimum_standard_width_in)
          ? `${result.minimum_standard_width_in} in`
          : '';
      case 'motor-circuit':
        return awg(result.branch_conductor);
      case 'motor-starter':
        return present(result.starter_type) ? String(result.starter_type) : '';
      case 'mcc-bucket':
        return present(result.total_height_in) ? `${result.total_height_in} in` : '';
      case 'vfd-circuit': {
        const parts = [];
        if (result.input_side && present(result.input_side.input_conductor)) {
          parts.push(`Input ${awg(result.input_side.input_conductor)}`);
        }
        if (result.output_side && present(result.output_side.output_conductor)) {
          parts.push(`Output ${awg(result.output_side.output_conductor)}`);
        }
        return parts.join(' / ');
      }
      default:
        return '';
    }
  }

  function valuesFor(toolId, payload) {
    const result = payload.result || {};
    const rows = [];
    switch (toolId) {
      case 'voltage-drop':
        if (present(result.comparison_size)) {
          pushRow(rows, valueRow('Trial conductor', result.comparison_size, 'AWG'));
          pushRow(rows, valueRow('Baseline recommendation', result.baseline_recommended_size, 'AWG'));
          pushRow(rows, valueRow('Ampacity check', result.ampacity_pass_fail));
          pushRow(rows, valueRow('Voltage-drop check', result.voltage_drop_pass_fail));
        } else {
          pushRow(rows, valueRow('Recommended conductor', conductorSize(result, payload.inputs), 'AWG'));
        }
        pushRow(rows, valueRow('Minimum ampacity size', result.minimum_ampacity_size, 'AWG'));
        pushRow(rows, valueRow('Minimum voltage-drop size', result.minimum_voltage_drop_size, 'AWG'));
        pushRow(rows, valueRow('Governing constraint', result.governing_constraint));
        pushRow(rows, valueRow('Governing explanation', result.governing_explanation));
        pushRow(rows, valueRow('Parallel minimum', result.parallel_minimum_awg, 'AWG'));
        pushRow(rows, valueRow('Voltage drop', result.voltage_drop_volts, 'V'));
        pushRow(rows, valueRow('Voltage drop percent', result.voltage_drop_pct, '%'));
        pushRow(rows, valueRow('Receiving end voltage', result.receiving_end_voltage, 'V'));
        pushRow(rows, valueRow('Threshold', result.threshold_pct, '%'));
        pushRow(rows, valueRow('Design amps', result.design_amps, 'A'));
        pushRow(rows, valueRow('Derated ampacity', result.derated_ampacity_A, 'A'));
        break;
      case 'feeder-size':
        pushRow(rows, valueRow('Conductor', firstPresent(result.conductor_size, result.conductor_awg), 'AWG'));
        pushRow(rows, valueRow('Parallel sets', result.parallel_sets));
        pushRow(rows, valueRow('OCPD', result.ocpd_size_A, 'A'));
        pushRow(rows, valueRow('EGC', result.egc_size, 'AWG'));
        pushRow(rows, valueRow('Design amps', result.design_amps, 'A'));
        pushRow(rows, valueRow('Derated ampacity', result.derated_ampacity_A, 'A'));
        pushRow(rows, valueRow('Voltage drop', result.voltage_drop_volts, 'V'));
        pushRow(rows, valueRow('Voltage drop percent', result.voltage_drop_pct, '%'));
        break;
      case 'conductor-sets':
        pushRow(rows, valueRow('Conductor', firstPresent(result.selected_size, result.conductor_awg, result.conductor_size), 'AWG'));
        pushRow(rows, valueRow('Parallel sets', result.parallel_sets));
        pushRow(rows, valueRow('OCPD', result.ocpd_size_A, 'A'));
        pushRow(rows, valueRow('EGC', result.egc_size, 'AWG'));
        pushRow(rows, valueRow('Design amps', result.design_amps, 'A'));
        pushRow(rows, valueRow('Voltage drop percent', result.voltage_drop_pct, '%'));
        pushRow(rows, valueRow('Solution found', result.solution_found));
        break;
      case 'ocpd-size':
        pushRow(rows, valueRow('OCPD', result.ocpd_size_A, 'A'));
        pushRow(rows, valueRow('Calculated amps', firstPresent(result.calculated_amps, result.amps), 'A'));
        pushRow(rows, valueRow('Circuit type', result.circuit_type));
        break;
      case 'conduit-fill':
        pushRow(rows, valueRow('Minimum trade size', result.minimum_trade_size));
        pushRow(rows, valueRow('Checked trade size', result.trade_size));
        pushRow(rows, valueRow('Fill percent', result.fill_pct, '%'));
        pushRow(rows, valueRow('Fill limit', result.fill_limit_pct, '%'));
        pushRow(rows, valueRow('Pass / fail', result.pass_fail));
        pushRow(rows, valueRow('EGC', result.egc_size, 'AWG'));
        pushRow(rows, valueRow('Solution found', result.solution_found));
        break;
      case 'grounding':
        pushRow(rows, valueRow('EGC copper', result.egc && result.egc.size_copper, 'AWG'));
        pushRow(rows, valueRow('GEC copper', result.gec && result.gec.size_copper, 'AWG'));
        break;
      case 'cable-tray-fill':
        pushRow(rows, valueRow('Minimum width', result.minimum_standard_width_in, 'in'));
        pushRow(rows, valueRow('Required width', result.required_width_in, 'in'));
        pushRow(rows, valueRow('Capacity used', firstPresent(result.pct_capacity_used, result.fill_pct), '%'));
        pushRow(rows, valueRow('Controlling metric', result.controlling_metric));
        pushRow(rows, valueRow('Solution found', result.solution_found));
        break;
      case 'motor-circuit':
        pushRow(rows, valueRow('Branch conductor', result.branch_conductor, 'AWG'));
        pushRow(rows, valueRow('Branch OCPD', firstPresent(result.ocpd_size_A, result.branch_ocpd_size_A), 'A'));
        pushRow(rows, valueRow('OL setpoint max', result.ol_setpoint_max_A, 'A'));
        pushRow(rows, valueRow('EGC', result.egc_size, 'AWG'));
        pushRow(rows, valueRow('FLA', firstPresent(result.fla, result.nameplate_fla, result.nec_fla), 'A'));
        pushRow(rows, valueRow('Voltage drop percent', result.voltage_drop_pct, '%'));
        break;
      case 'motor-starter':
        pushRow(rows, valueRow('Starter', result.starter_type));
        pushRow(rows, valueRow('Module', result.module_cat));
        pushRow(rows, valueRow('Size / NEMA', firstPresent(result.nema_size_equiv, result.nema_size, result.size)));
        pushRow(rows, valueRow('OL setpoint', result.ol_setpoint_A, 'A'));
        pushRow(rows, valueRow('FLA', result.fla, 'A'));
        break;
      case 'mcc-bucket':
        pushRow(rows, valueRow('Bucket height', result.total_height_in, 'in'));
        pushRow(rows, valueRow('Section spaces', result.section_spaces_used));
        pushRow(rows, valueRow('Starter', result.starter_type));
        pushRow(rows, valueRow('NEMA size', result.nema_size));
        pushRow(rows, valueRow('CB size', result.cb_size_A, 'A'));
        pushRow(rows, valueRow('CPT VA', result.cpt_va_size, 'VA'));
        break;
      case 'vfd-circuit':
        pushRow(rows, valueRow('Input conductor', result.input_side && result.input_side.input_conductor, 'AWG'));
        pushRow(rows, valueRow('Output conductor', result.output_side && result.output_side.output_conductor, 'AWG'));
        pushRow(rows, valueRow(
          'Input OCPD',
          result.input_side && firstPresent(result.input_side.input_ocpd_size_A, result.input_side.input_ocpd_A),
          'A',
        ));
        pushRow(rows, valueRow('Output voltage drop', result.output_side && result.output_side.voltage_drop_pct, '%'));
        break;
      default:
        break;
    }
    return rows;
  }

  function vdPassFail(result) {
    if (!result || typeof result !== 'object') return undefined;
    if (present(result.vd_pass_fail)) return String(result.vd_pass_fail);
    if (result.output_side && present(result.output_side.vd_pass_fail)) {
      return String(result.output_side.vd_pass_fail);
    }
    return undefined;
  }

  function complianceProven(result, codeBasis) {
    if (!result || typeof result !== 'object') return false;
    if (result.pass_fail === 'PASS') return true;
    if (result.solution_found === true) return true;
    // Tool-specific voltage-drop proof (feeder/motor root, VFD nested output_side).
    // Requires a returned code basis — PASS alone is not enough.
    if (vdPassFail(result) === 'PASS' && present(codeBasis)) return true;
    return false;
  }

  function resolveState(payload, warnings, result) {
    if (String(payload.status || '').toLowerCase() === 'error' || present(payload.error)) {
      return 'FAIL';
    }
    if (result && result.solution_found === false) return 'FAIL';
    if (result && result.pass_fail === 'FAIL') return 'FAIL';
    if (vdPassFail(result) === 'FAIL') return 'FAIL';
    if (warnings.length) return 'WARN';
    if (complianceProven(result, payload.code_basis)) return 'PASS';
    return 'WARN';
  }

  function errorRecommendation(payload) {
    const field = String(payload.field || '').trim();
    if (field) {
      const label = FIELD_LABELS[field] || field;
      return `Correct ${label} and recalculate.`;
    }
    return 'Correct the highlighted inputs and recalculate.';
  }

  function resultModel(toolId, payload) {
    const data = payload && typeof payload === 'object' ? payload : {};
    const result = data.result && typeof data.result === 'object' ? data.result : {};
    const warnings = asList(data.warnings);
    const assumptions = asList(data.assumptions);
    const sources = asList(data.sources);
    const isError = String(data.status || '').toLowerCase() === 'error' || present(data.error);

    if (isError) {
      const errorText = present(data.error) ? String(data.error) : 'Calculation failed.';
      return {
        toolId,
        state: 'FAIL',
        recommendation: errorRecommendation(data),
        values: [],
        warnings: warnings.length ? warnings : [errorText],
        assumptions,
        codeBasis: present(data.code_basis) ? String(data.code_basis) : '',
        sources,
        raw: data,
      };
    }

    const codeBasis = present(data.code_basis) ? String(data.code_basis) : '';

    // Fail closed: no PASS without proof. If the API already returned warnings, keep those
    // as the operator-facing WARN content; only inject the compliance notice when silent.
    if (
      !warnings.length
      && !complianceProven(result, codeBasis)
      && result.solution_found !== false
      && result.pass_fail !== 'FAIL'
      && vdPassFail(result) !== 'FAIL'
    ) {
      warnings.push(COMPLIANCE_WARNING);
    }

    const state = resolveState(data, warnings, result);
    let recommendation = recommendationFor(toolId, data);
    if (!recommendation) {
      recommendation = state === 'FAIL'
        ? 'No compliant solution found.'
        : 'Review calculated values and design conditions.';
    }

    return {
      toolId,
      state,
      recommendation,
      values: valuesFor(toolId, data),
      warnings,
      assumptions,
      codeBasis,
      sources,
      raw: data,
    };
  }

  function listSection(title, items, className) {
    if (!items || !items.length) return '';
    return `<section class="${className}"><h4>${esc(title)}</h4><ul>${
      items.map((item) => `<li>${esc(item)}</li>`).join('')
    }</ul></section>`;
  }

  function renderResultCard(toolId, payload) {
    const model = resultModel(toolId, payload);
    const stateClass = String(model.state || 'WARN').toLowerCase();
    const values = model.values.length
      ? `<dl class="smedley-result-values">${model.values.map((row) => (
        `<div><dt>${esc(row.label)}</dt><dd>${esc(row.display)}</dd></div>`
      )).join('')}</dl>`
      : '';
    const sources = listSection('Sources', model.sources, 'smedley-result-sources');
    const code = model.codeBasis
      ? `<section class="smedley-result-code"><h4>Code / Source Basis</h4><p>${esc(model.codeBasis)}</p></section>`
      : '';
    const technical = `<details class="smedley-result-technical"><summary>Technical Details</summary><pre>${esc(JSON.stringify(model.raw, null, 2))}</pre></details>`;

    return [
      `<article class="smedley-result-card smedley-result-card--${esc(stateClass)}" data-tool="${esc(toolId)}">`,
      `<header class="smedley-result-header"><span class="smedley-result-state">${esc(model.state)}</span>`,
      `<strong class="smedley-result-recommendation">${esc(model.recommendation)}</strong></header>`,
      values,
      listSection('Warnings', model.warnings, 'smedley-result-warnings'),
      listSection('Assumptions', model.assumptions, 'smedley-result-assumptions'),
      code,
      sources,
      technical,
      '</article>',
    ].join('');
  }

  return Object.freeze({
    resultModel,
    renderResultCard,
    FIELD_LABELS,
  });
});
