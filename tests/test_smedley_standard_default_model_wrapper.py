"""Smedley must use the shared Hermes default-model wrapper contract.

Authoritative divergence (do not reintroduce):
  Documents/Codex/2026-07-16/i/work/hermes-webui-dynamic-model/static/panels.js
  and the 2026-07-16 retention hermes-core panels.js made profile switches
  follow the composer/localStorage selection ("dynamic model inheritance").

Shared Thunderdome / upstream contract:
  - Profile switch clears browser-persisted model state
  - Profile switch applies /api/profile/switch default_model (persistent)
  - Profile menu reports each profile's on-disk model, not the composer chip
  - set_hermes_default_model persists exact slash-form model ids such as
    qwen/qwen3.5-35b-a3b without wiping agent.reasoning_effort

A per-conversation model dropdown is not a persistent default.
"""
from __future__ import annotations

from pathlib import Path

import yaml

import api.config as config
from api.config import set_hermes_default_model


REPO = Path(__file__).resolve().parents[1]
PANELS_JS = (REPO / "static" / "panels.js").read_text(encoding="utf-8")
SESSIONS_JS = (REPO / "static" / "sessions.js").read_text(encoding="utf-8")

TARGET_DEFAULT = "qwen/qwen3.5-35b-a3b"


def _switch_to_profile_body() -> str:
    start = PANELS_JS.index("async function switchToProfile(name)")
    end = PANELS_JS.index("function openProfileCreate", start)
    return PANELS_JS[start:end]


def _render_profile_dropdown_body() -> str:
    start = PANELS_JS.index("function renderProfileDropdown(data)")
    end = PANELS_JS.index("function toggleProfileDropdown", start)
    return PANELS_JS[start:end]


def _session_profile_switch_body() -> str:
    start = SESSIONS_JS.index("async function _switchProfileForSessionLoad(profile)")
    end = SESSIONS_JS.index("async function loadSession(sid)", start)
    return SESSIONS_JS[start:end]


def test_profile_switch_applies_persistent_profile_default_not_composer_selection():
    body = _switch_to_profile_body()

    assert "_clearPersistedModelState" in body
    assert "if (data.default_model) window._defaultModel = data.default_model" in body
    assert "_applyModelToDropdown(data.default_model, sel, providerId)" in body
    assert "refreshProfileTransitionReasoningChip(data.default_model" in body

    # Reject the Smedley-only composer-follow regression.
    assert "_selectedModelBeforeProfileSwitch" not in body
    assert "const effectiveModel =" not in body
    assert "_writePersistedModelState" not in body


def test_profile_menu_reports_each_profile_persistent_model():
    body = _render_profile_dropdown_body()

    assert "p.model.split('/').pop()" in body
    assert "selectedModelState" not in body
    assert "effectiveProfileModel" not in body
    assert "Smedley's role profiles follow the model selected in the composer" not in body


def test_session_load_profile_switch_uses_same_persistent_default_contract():
    body = _session_profile_switch_body()

    assert "_clearPersistedModelState" in body
    assert "if(data.default_model) window._defaultModel=data.default_model" in body
    assert "refreshProfileTransitionReasoningChip(data.default_model" in body
    assert "_selectedModelBeforeProfileSwitch" not in body


def test_set_hermes_default_model_persists_exact_qwen_slash_id(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "\n".join(
            [
                "model:",
                "  provider: lmstudio",
                "  default: gpt-5.6-sol",
                "  base_url: http://127.0.0.1:1234/v1",
                "agent:",
                "  reasoning_effort: none",
                "  temperature: 0.4",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "_get_config_path", lambda: Path(str(config_file)))
    config.cfg["model"] = {
        "provider": "lmstudio",
        "default": "gpt-5.6-sol",
        "base_url": "http://127.0.0.1:1234/v1",
    }
    try:
        config._cfg_mtime = config_file.stat().st_mtime
    except OSError:
        config._cfg_mtime = 0.0

    monkeypatch.setattr(
        config,
        "resolve_model_provider",
        lambda model_id: (str(model_id).strip(), "lmstudio", "http://127.0.0.1:1234/v1"),
    )
    monkeypatch.setattr(config, "reload_config", lambda: None)
    monkeypatch.setattr(config, "invalidate_models_cache", lambda: None)

    result = set_hermes_default_model(TARGET_DEFAULT, provider="lmstudio")

    assert result["ok"] is True
    assert result["model"] == TARGET_DEFAULT
    assert result["provider"] == "lmstudio"

    saved = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert saved["model"]["default"] == TARGET_DEFAULT
    assert saved["model"]["provider"] == "lmstudio"
    # Persistent defaults must not clobber reasoning/thinking or temperature.
    assert saved["agent"]["reasoning_effort"] == "none"
    assert saved["agent"]["temperature"] == 0.4


def test_boot_and_composer_still_expose_model_and_reasoning_controls():
    boot = (REPO / "static" / "boot.js").read_text(encoding="utf-8")
    index = (REPO / "static" / "index.html").read_text(encoding="utf-8")

    assert "preferProfileDefaultOnFreshBoot:true" in boot
    assert "!window._defaultModel?savedState:null" in boot or "allowBootSavedModelOverride=!window._defaultModel" in boot
    assert 'id="modelSelect"' in index
    assert 'id="composerReasoningChip"' in index
    assert 'data-effort="none"' in index
    assert 'data-effort="medium"' in index
