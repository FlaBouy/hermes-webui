import importlib
import os
import sys
from pathlib import Path


def test_profile_switch_clears_previous_profile_env_vars(monkeypatch, tmp_path):
    base = tmp_path / ".hermes"
    (base / "profiles" / "p1").mkdir(parents=True)
    (base / "profiles" / "p2").mkdir(parents=True)
    (base / "profiles" / "p1" / ".env").write_text(
        "OPENAI_API_KEY=secret-from-p1\nCUSTOM_TOKEN=token-from-p1\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("HERMES_BASE_HOME", str(base))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CUSTOM_TOKEN", raising=False)

    # Point the module's cached base-home at our temp base via monkeypatch
    # (auto-restored at teardown) instead of deleting + re-importing api.profiles.
    # The delitem+import_module approach swapped the module object and poisoned
    # dependent modules' cached references, breaking later tests under sharding.
    import api.profiles as profiles
    monkeypatch.setattr(profiles, "_DEFAULT_HERMES_HOME", base)

    profiles.init_profile_state()
    profiles.switch_profile("p1")
    assert os.environ.get("OPENAI_API_KEY") == "secret-from-p1"
    assert os.environ.get("CUSTOM_TOKEN") == "token-from-p1"

    profiles.switch_profile("p2")
    assert os.environ.get("OPENAI_API_KEY") is None
    assert os.environ.get("CUSTOM_TOKEN") is None
    assert profiles.get_active_profile_name() == "p2"


def test_profile_switch_replaces_overlapping_keys(monkeypatch, tmp_path):
    base = tmp_path / ".hermes"
    (base / "profiles" / "p1").mkdir(parents=True)
    (base / "profiles" / "p2").mkdir(parents=True)
    (base / "profiles" / "p1" / ".env").write_text(
        "OPENAI_API_KEY=secret-from-p1\nONLY_P1=one\n",
        encoding="utf-8",
    )
    (base / "profiles" / "p2" / ".env").write_text(
        "OPENAI_API_KEY=secret-from-p2\nONLY_P2=two\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("HERMES_BASE_HOME", str(base))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ONLY_P1", raising=False)
    monkeypatch.delenv("ONLY_P2", raising=False)

    # Point the module's cached base-home at our temp base via monkeypatch
    # (auto-restored at teardown) instead of deleting + re-importing api.profiles.
    # The delitem+import_module approach swapped the module object and poisoned
    # dependent modules' cached references, breaking later tests under sharding.
    import api.profiles as profiles
    monkeypatch.setattr(profiles, "_DEFAULT_HERMES_HOME", base)

    profiles.init_profile_state()
    profiles.switch_profile("p1")
    assert os.environ.get("OPENAI_API_KEY") == "secret-from-p1"
    assert os.environ.get("ONLY_P1") == "one"

    profiles.switch_profile("p2")
    assert os.environ.get("OPENAI_API_KEY") == "secret-from-p2"
    assert os.environ.get("ONLY_P1") is None
    assert os.environ.get("ONLY_P2") == "two"


def test_named_startup_profile_preserves_normal_profile_management(monkeypatch, tmp_path):
    base = tmp_path / ".hermes"
    (base / "profiles" / "biggy").mkdir(parents=True)

    monkeypatch.setenv("HERMES_BASE_HOME", str(base))
    monkeypatch.setenv("HERMES_WEBUI_STARTUP_PROFILE", "biggy")
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("HERMES_WEBUI_ISOLATED_PROFILE", raising=False)

    import api.profiles as profiles
    monkeypatch.setattr(profiles, "_DEFAULT_HERMES_HOME", base)
    monkeypatch.setattr(profiles, "_INITIAL_ISOLATED_PROFILE_OPT_IN", "")

    profiles.init_profile_state()

    assert profiles.get_active_profile_name() == "biggy"
    assert Path(os.environ["HERMES_HOME"]) == base / "profiles" / "biggy"


def test_update_profile_writes_capabilities_to_target_profile(monkeypatch, tmp_path):
    base = tmp_path / ".hermes"
    target = base / "profiles" / "comms"
    target.mkdir(parents=True)

    import api.profiles as profiles
    monkeypatch.setattr(profiles, "_DEFAULT_HERMES_HOME", base)
    monkeypatch.setattr(profiles, "_INITIAL_ISOLATED_PROFILE_OPT_IN", "")
    monkeypatch.setattr(
        profiles,
        "_validate_profile_model_selection",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        profiles,
        "list_profiles_api",
        lambda: [{"name": "comms", "path": str(target)}],
    )

    result = profiles.update_profile_api(
        "comms",
        base_url="https://api.example.test",
        api_key="profile-secret",
        default_model="coordinator-model",
        model_provider="test-provider",
        additional_secret={"name": "SOCIAL_API_KEY", "value": "social-secret"},
    )

    assert result["name"] == "comms"
    assert "profile-secret" in (target / ".env").read_text(encoding="utf-8")
    assert "SOCIAL_API_KEY=social-secret" in (target / ".env").read_text(encoding="utf-8")
    config = (target / "config.yaml").read_text(encoding="utf-8")
    assert "https://api.example.test" in config
    assert "coordinator-model" in config
