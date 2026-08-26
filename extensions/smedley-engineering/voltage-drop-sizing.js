(() => {
  'use strict';

  const CONDUCTORS = Object.freeze([
    '14', '12', '10', '8', '6', '4', '3', '2', '1',
    '1/0', '2/0', '3/0', '4/0',
    '250', '300', '350', '400', '500', '600', '750', '1000',
  ]);

  // NEC 310.10(H)(1): ordinary parallel phase conductors 1/0 AWG and larger.
  // This UI has no exception workflow — fail closed to 1/0 when parallel_sets > 1.
  const PARALLEL_MIN_AWG = '1/0';
  const PARALLEL_MIN_CODE_BASIS =
    'NEC NFPA 70, 2014 Ed. -- 310.10(H)(1): ordinary parallel conductors shall be 1/0 AWG or larger; no exception workflow in this calculator (fail closed to 1/0 AWG when parallel_sets > 1).';

  const REQUIRED = Object.freeze([
    'voltage', 'phase', 'amps', 'length_ft', 'material', 'temp_rating',
    'circuit_type', 'continuous_load', 'conduit_type', 'parallel_sets',
    'ambient_temp_c', 'num_conductors',
  ]);

  function errorResult(message) {
    return {
      status: 'error',
      tool: 'voltage-drop',
      error: String(message || 'Voltage drop sizing failed.'),
      result: null,
      assumptions: [],
      warnings: [],
      code_basis: '',
      sources: [],
    };
  }

  function present(value) {
    return value !== undefined && value !== null && String(value).trim() !== '';
  }

  function normalizeMaterial(value) {
    return String(value || '').trim().toLowerCase();
  }

  function sizeIndex(size) {
    const key = String(size || '').trim();
    return CONDUCTORS.indexOf(key);
  }

  function largerSize(a, b) {
    const ia = sizeIndex(a);
    const ib = sizeIndex(b);
    if (ia < 0 || ib < 0) return null;
    return ia >= ib ? a : b;
  }

  function parallelMinimumAwg(parallelSets) {
    return Number(parallelSets) > 1 ? PARALLEL_MIN_AWG : null;
  }

  function conductorsFrom(minSize) {
    if (!minSize) return CONDUCTORS.slice();
    const idx = sizeIndex(minSize);
    if (idx < 0) return CONDUCTORS.slice();
    return CONDUCTORS.slice(idx);
  }

  function applyParallelMinimum(size, parallelSets) {
    const floor = parallelMinimumAwg(parallelSets);
    if (!floor) {
      return {size, floor: null, raised: false, raw: size};
    }
    const raisedSize = largerSize(size, floor);
    return {
      size: raisedSize,
      floor,
      raised: raisedSize !== size,
      raw: size,
    };
  }

  function mergeUnique(lists) {
    const out = [];
    const seen = new Set();
    lists.flat().forEach((item) => {
      const text = String(item || '').trim();
      if (!text || seen.has(text)) return;
      seen.add(text);
      out.push(text);
    });
    return out;
  }

  function validateInput(input) {
    const missing = REQUIRED.filter((key) => !present(input?.[key]));
    if (missing.length) {
      return errorResult(
        `Missing required design conditions: ${missing.join(', ')}.`,
      );
    }
    const material = normalizeMaterial(input.material);
    if (material !== 'copper') {
      return errorResult(
        'Unsupported conductor material. Copper conductors only for this calculator (NEC Ch.9 Table 9 / Table 310.16 copper basis).',
      );
    }
    const numericKeys = [
      'voltage', 'phase', 'amps', 'length_ft', 'temp_rating',
      'parallel_sets', 'ambient_temp_c', 'num_conductors',
    ];
    for (const key of numericKeys) {
      const value = Number(input[key]);
      if (!Number.isFinite(value)) {
        return errorResult(`Invalid design condition: ${key} must be numeric.`);
      }
    }
    if (Number(input.voltage) <= 0 || Number(input.amps) <= 0 || Number(input.length_ft) <= 0) {
      return errorResult('voltage, amps, and length_ft must be greater than zero.');
    }
    if (![1, 3].includes(Number(input.phase))) {
      return errorResult('phase must be 1 or 3.');
    }
    if (![60, 75, 90].includes(Number(input.temp_rating))) {
      return errorResult('temp_rating must be 60, 75, or 90.');
    }
    if (Number(input.parallel_sets) < 1) {
      return errorResult('parallel_sets must be >= 1.');
    }
    if (Number(input.num_conductors) < 1) {
      return errorResult('num_conductors must be >= 1.');
    }
    const circuit = String(input.circuit_type || '').trim().toLowerCase();
    if (!['feeder', 'branch'].includes(circuit)) {
      return errorResult("circuit_type must be 'feeder' or 'branch'.");
    }
    return null;
  }

  function feederParams(input) {
    const params = {
      voltage: Number(input.voltage),
      phase: Number(input.phase),
      amps: Number(input.amps),
      length_ft: Number(input.length_ft),
      conduit_type: String(input.conduit_type).trim().toLowerCase(),
      circuit_type: String(input.circuit_type).trim().toLowerCase(),
      continuous_load: Boolean(input.continuous_load === true || input.continuous_load === 'true'),
      temp_rating: Number(input.temp_rating),
      parallel_sets: Number(input.parallel_sets),
      ambient_temp_c: Number(input.ambient_temp_c),
      num_conductors: Number(input.num_conductors),
    };
    if (present(input.power_factor)) params.power_factor = Number(input.power_factor);
    return params;
  }

  function voltageDropParams(input, conductorAwg) {
    const params = {
      voltage: Number(input.voltage),
      phase: Number(input.phase),
      amps: Number(input.amps),
      length_ft: Number(input.length_ft),
      conductor_awg: String(conductorAwg),
      conduit_type: String(input.conduit_type).trim().toLowerCase(),
      circuit_type: String(input.circuit_type).trim().toLowerCase(),
      parallel_sets: Number(input.parallel_sets),
    };
    if (present(input.power_factor)) params.power_factor = Number(input.power_factor);
    return params;
  }

  function passesVoltageDrop(payload) {
    if (!payload || payload.status !== 'ok' || !payload.result) return false;
    if (payload.result.pass_fail === 'PASS') return true;
    if (payload.result.pass_fail === 'FAIL') return false;
    const pct = Number(payload.result.voltage_drop_pct);
    const threshold = Number(payload.result.threshold_pct);
    return Number.isFinite(pct) && Number.isFinite(threshold) && pct <= threshold;
  }

  async function findMinimumVoltageDropSize(input, request) {
    const floor = parallelMinimumAwg(input.parallel_sets);
    const candidates = conductorsFrom(floor);
    for (const size of candidates) {
      const payload = await request('/tools/voltage-drop', voltageDropParams(input, size));
      if (!payload || payload.status !== 'ok') {
        return {
          size: null,
          payload: null,
          error: payload?.error || `Voltage-drop lookup failed for ${size} AWG.`,
        };
      }
      if (passesVoltageDrop(payload)) {
        return {size, payload, floor};
      }
    }
    return {
      size: null,
      payload: null,
      floor,
      error: floor
        ? `No supported copper conductor at or above parallel minimum ${floor} AWG meets the voltage-drop threshold.`
        : 'No supported copper conductor meets the voltage-drop threshold.',
    };
  }

  function governingFor(ampacitySize, voltageDropSize) {
    const ia = sizeIndex(ampacitySize);
    const iv = sizeIndex(voltageDropSize);
    if (ia === iv) {
      return {
        governing_constraint: 'both',
        governing_explanation:
          `Ampacity/code size and voltage-drop size both require ${ampacitySize} AWG.`,
      };
    }
    if (ia > iv) {
      return {
        governing_constraint: 'ampacity',
        governing_explanation:
          `Ampacity/code size ${ampacitySize} AWG governs over voltage-drop minimum ${voltageDropSize} AWG.`,
      };
    }
    return {
      governing_constraint: 'voltage_drop',
      governing_explanation:
        `Voltage drop requires ${voltageDropSize} AWG, which is larger than ampacity/code size ${ampacitySize} AWG.`,
    };
  }

  async function calculate(input, request) {
    if (typeof request !== 'function') {
      return errorResult('Voltage drop sizing request adapter is missing.');
    }
    const invalid = validateInput(input || {});
    if (invalid) return invalid;

    const feeder = await request('/tools/feeder-size', feederParams(input));
    if (!feeder || feeder.status !== 'ok' || !feeder.result?.conductor_size) {
      return errorResult(feeder?.error || 'Ampacity/code sizing failed.');
    }
    const rawAmpacitySize = String(feeder.result.conductor_size).trim();
    if (sizeIndex(rawAmpacitySize) < 0) {
      return errorResult(`Unsupported ampacity conductor size returned: ${rawAmpacitySize}.`);
    }

    const parallelAmpacity = applyParallelMinimum(rawAmpacitySize, input.parallel_sets);
    if (!parallelAmpacity.size) {
      return errorResult('Unable to apply parallel-conductor minimum to ampacity size.');
    }
    const ampacitySize = parallelAmpacity.size;

    const vdMin = await findMinimumVoltageDropSize(input, request);
    if (!vdMin.size) {
      return errorResult(vdMin.error);
    }
    // Defense in depth: never accept a VD candidate below the parallel floor.
    const parallelVd = applyParallelMinimum(vdMin.size, input.parallel_sets);
    if (!parallelVd.size) {
      return errorResult('Unable to apply parallel-conductor minimum to voltage-drop size.');
    }

    const recommended = largerSize(ampacitySize, parallelVd.size);
    if (!recommended) {
      return errorResult('Unable to compare ampacity and voltage-drop conductor sizes.');
    }
    if (parallelMinimumAwg(input.parallel_sets)
        && sizeIndex(recommended) < sizeIndex(PARALLEL_MIN_AWG)) {
      return errorResult(
        `Parallel conductors cannot be smaller than ${PARALLEL_MIN_AWG} AWG (NEC 310.10(H)(1)).`,
      );
    }

    const finalDrop = await request('/tools/voltage-drop', voltageDropParams(input, recommended));
    if (!finalDrop || finalDrop.status !== 'ok' || !finalDrop.result) {
      return errorResult(finalDrop?.error || `Final voltage-drop check failed for ${recommended} AWG.`);
    }

    const governing = governingFor(ampacitySize, parallelVd.size);
    const parallelAssumptions = [];
    if (parallelAmpacity.floor) {
      if (parallelAmpacity.raised) {
        parallelAssumptions.push(
          `NEC parallel-conductor minimum applied to ampacity/code sizing: /tools/feeder-size returned ${parallelAmpacity.raw} AWG; raised to ${parallelAmpacity.floor} AWG per NEC 310.10(H)(1). Ordinary parallel feeders only — no exception workflow in this calculator (fail closed).`,
        );
      } else {
        parallelAssumptions.push(
          `NEC parallel-conductor minimum observed for ampacity/code sizing: ${parallelAmpacity.floor} AWG per NEC 310.10(H)(1). Ordinary parallel feeders only — no exception workflow in this calculator (fail closed).`,
        );
      }
      parallelAssumptions.push(
        `Voltage-drop candidate sweep starts at ${parallelAmpacity.floor} AWG when parallel_sets > 1; smaller parallel conductors are never presented as compliant.`,
      );
    }
    const assumptions = mergeUnique([
      feeder.assumptions || [],
      vdMin.payload?.assumptions || [],
      finalDrop.assumptions || [],
      parallelAssumptions,
      [
        'Automatic conductor sizing: minimum ampacity/code size from /tools/feeder-size (with parallel 1/0 AWG floor when parallel_sets > 1); minimum voltage-drop size from /tools/voltage-drop sweep (same floor); final recommendation is the larger size.',
      ],
    ]);
    const warnings = mergeUnique([
      feeder.warnings || [],
      vdMin.payload?.warnings || [],
      finalDrop.warnings || [],
    ]);
    const codeBasis = mergeUnique([
      feeder.code_basis ? [feeder.code_basis] : [],
      finalDrop.code_basis ? [finalDrop.code_basis] : [],
      parallelAmpacity.floor ? [PARALLEL_MIN_CODE_BASIS] : [],
    ]).join(' | ');

    return {
      status: 'ok',
      tool: 'voltage-drop',
      inputs: {
        ...feederParams(input),
        material: 'copper',
        recommended_size: recommended,
      },
      result: {
        ...finalDrop.result,
        conductor_awg: recommended,
        recommended_size: recommended,
        minimum_ampacity_size: ampacitySize,
        minimum_voltage_drop_size: parallelVd.size,
        feeder_ampacity_size: rawAmpacitySize,
        parallel_minimum_awg: parallelAmpacity.floor,
        governing_constraint: governing.governing_constraint,
        governing_explanation: governing.governing_explanation,
        design_amps: feeder.result.design_amps,
        derated_ampacity_A: feeder.result.derated_ampacity_A,
        combined_cf: feeder.result.combined_cf,
        temp_rating: feeder.result.temp_rating,
      },
      assumptions,
      warnings,
      code_basis: codeBasis,
      sources: mergeUnique([feeder.sources || [], finalDrop.sources || []]),
    };
  }

  window.SmedleyVoltageDropSizing = Object.freeze({
    calculate,
    CONDUCTORS,
    PARALLEL_MIN_AWG,
  });
})();
