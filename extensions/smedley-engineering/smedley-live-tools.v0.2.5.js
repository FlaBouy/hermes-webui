(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.SmedleyLiveTools = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const DEFAULT_DEBOUNCE_MS = 300;

  // Numeric fields that must be strictly > 0 when present.
  const POSITIVE_FIELDS = new Set([
    'voltage',
    'amps',
    'length_ft',
    '_fla_val',
    'ocpd_amps',
    'tray_depth_in',
    'service_factor',
    'drive_input_fla',
    'check_width_in',
  ]);

  // Integer counts that must be >= 1 when present.
  const INTEGER_MIN_ONE_FIELDS = new Set([
    'parallel_sets',
    'num_conductors',
    'num_current_carrying',
  ]);

  function controlsFor(form) {
    return Array.from(form.querySelectorAll('input,select,textarea'));
  }

  function clearFieldError(control) {
    control.removeAttribute('aria-invalid');
    const wrapper = control.closest('label');
    if (!wrapper) return;
    wrapper.classList.remove('smedley-engineering-field-invalid');
    const error = wrapper.querySelector('.smedley-engineering-field-error');
    if (error) error.remove();
  }

  function showFieldError(control, message) {
    clearFieldError(control);
    control.setAttribute('aria-invalid', 'true');
    const wrapper = control.closest('label');
    if (!wrapper) return;
    wrapper.classList.add('smedley-engineering-field-invalid');
    const error = document.createElement('small');
    error.className = 'smedley-engineering-field-error';
    error.textContent = message;
    wrapper.appendChild(error);
  }

  function fieldLabel(control) {
    const caption = control.closest('label')?.querySelector('span');
    return (caption?.textContent || control.name || 'This field').trim();
  }

  function validateCables(raw, label) {
    let cables;
    try {
      cables = JSON.parse(raw);
    } catch (_) {
      return `${label} must be valid JSON.`;
    }
    if (!Array.isArray(cables) || !cables.length) {
      return `${label} must contain at least one cable.`;
    }
    for (let i = 0; i < cables.length; i += 1) {
      const cable = cables[i];
      if (!cable || typeof cable !== 'object' || Array.isArray(cable)) {
        return `${label}[${i}] must be an object.`;
      }
      const count = Number(cable.count);
      if (!Number.isInteger(count) || count < 1) {
        return `${label}[${i}].count must be an integer >= 1.`;
      }
      const hasDesignation = String(cable.cable_designation || '').trim();
      const hasOd = cable.od_in != null && cable.od_in !== '';
      const hasArea = cable.area_sqin != null && cable.area_sqin !== '';
      if (!hasDesignation && !(hasOd && hasArea)) {
        return `${label}[${i}] needs cable_designation or od_in + area_sqin.`;
      }
    }
    return '';
  }

  function validateControl(control) {
    const label = fieldLabel(control);
    const name = control.name || '';
    const raw = String(control.value ?? '').trim();
    if (control.required && !raw) return `${label} is required.`;
    if (!raw) return '';

    if (name === 'cables') return validateCables(raw, label);

    if (control.type === 'number' || name === 'power_factor' || POSITIVE_FIELDS.has(name)
        || INTEGER_MIN_ONE_FIELDS.has(name)) {
      const value = Number(raw);
      if (!Number.isFinite(value)) return `${label} must be a number.`;

      if (name === 'power_factor') {
        if (value <= 0 || value > 1) {
          return `${label} must be greater than 0 and at most 1.`;
        }
      }

      if (POSITIVE_FIELDS.has(name) && value <= 0) {
        return `${label} must be greater than 0.`;
      }

      if (INTEGER_MIN_ONE_FIELDS.has(name)) {
        if (!Number.isInteger(value) || value < 1) {
          return `${label} must be an integer >= 1.`;
        }
      }

      if (control.min !== '' && value < Number(control.min)) {
        return `${label} must be at least ${control.min}.`;
      }
      if (control.max !== '' && value > Number(control.max)) {
        return `${label} must be no more than ${control.max}.`;
      }
      if (control.step && control.step !== 'any' && Number(control.step) >= 1
          && !Number.isInteger(value)) {
        return `${label} must be a whole number.`;
      }
    }
    return '';
  }

  function validateForm(form, validateExtra) {
    const controls = controlsFor(form);
    const errors = {};
    controls.forEach((control) => {
      clearFieldError(control);
      const message = validateControl(control);
      if (message) errors[control.name] = message;
    });
    if (typeof validateExtra === 'function') {
      const extra = validateExtra(controls, errors) || {};
      Object.entries(extra).forEach(([name, message]) => {
        if (message) errors[name] = message;
      });
    }
    Object.entries(errors).forEach(([name, message]) => {
      const control = controls.find((candidate) => candidate.name === name);
      if (control) showFieldError(control, message);
    });
    return {valid: !Object.keys(errors).length, errors};
  }

  function wire(options) {
    const {
      form,
      result,
      run,
      collectParams,
      calculate,
      renderSuccess,
      renderError,
      validateExtra,
      debounceMs = DEFAULT_DEBOUNCE_MS,
    } = options;

    let timer = null;
    let requestVersion = 0;
    let disposed = false;

    const setRunState = (busy) => {
      run.disabled = busy;
      run.textContent = busy ? 'CALCULATING…' : 'RECALCULATE';
    };

    const invalidate = (message) => {
      requestVersion += 1;
      if (timer !== null) clearTimeout(timer);
      timer = null;
      setRunState(false);
      result.classList.remove('is-pending');
      result.innerHTML = `<div class="smedley-engineering-result-empty">${message}</div>`;
    };

    const execute = async () => {
      timer = null;
      const validation = validateForm(form, validateExtra);
      if (!validation.valid) {
        invalidate('Complete the highlighted fields to calculate.');
        return false;
      }
      let params;
      try {
        params = collectParams();
      } catch (error) {
        invalidate(error?.message || 'Correct the highlighted fields to calculate.');
        return false;
      }
      const version = ++requestVersion;
      setRunState(true);
      result.classList.add('is-pending');
      result.innerHTML = '<div class="smedley-engineering-result-empty">Recalculating…</div>';
      try {
        const data = await calculate(params);
        if (disposed || version !== requestVersion) return false;
        renderSuccess(data);
        return true;
      } catch (error) {
        if (disposed || version !== requestVersion) return false;
        renderError(error);
        return false;
      } finally {
        if (!disposed && version === requestVersion) {
          result.classList.remove('is-pending');
          setRunState(false);
        }
      }
    };

    const schedule = () => {
      const validation = validateForm(form, validateExtra);
      if (!validation.valid) {
        invalidate('Complete the highlighted fields to calculate.');
        return;
      }
      // Bump version so any in-flight reply is stale before the debounce fires.
      requestVersion += 1;
      if (timer !== null) clearTimeout(timer);
      // Keep last valid card during debounce; incomplete paths already invalidated.
      result.classList.add('is-pending');
      timer = setTimeout(execute, debounceMs);
    };

    const onInput = () => schedule();
    const onKeydown = (event) => {
      const textarea = event.target?.tagName === 'TEXTAREA';
      if (event.key !== 'Enter' || (textarea && !event.ctrlKey && !event.metaKey)) return;
      event.preventDefault();
      if (timer !== null) clearTimeout(timer);
      execute();
    };
    const onRun = (event) => {
      event.preventDefault();
      if (timer !== null) clearTimeout(timer);
      execute();
    };

    form.addEventListener('input', onInput);
    form.addEventListener('change', onInput);
    form.addEventListener('keydown', onKeydown);
    run.addEventListener('click', onRun);
    setRunState(false);

    return {
      calculateNow: execute,
      dispose() {
        disposed = true;
        requestVersion += 1;
        if (timer !== null) clearTimeout(timer);
        form.removeEventListener('input', onInput);
        form.removeEventListener('change', onInput);
        form.removeEventListener('keydown', onKeydown);
        run.removeEventListener('click', onRun);
      },
    };
  }

  return Object.freeze({
    wire,
    validateForm,
    validateControl,
    DEFAULT_DEBOUNCE_MS,
    POSITIVE_FIELDS,
    INTEGER_MIN_ONE_FIELDS,
  });
});
