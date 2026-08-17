from api.ask_jarvis_route import (
    is_ask_jarvis_command,
    require_jarvis_voice_id,
    resolve_ask_jarvis_objective,
    JARVIS_VOICE_CONFIGURATION_UNAVAILABLE,
)

OWNER = (
    "I need to schedule a trip to GP Brewton next Tuesday. Ask Jarvis to map a "
    "route and check my schedule for conflicts. Also have him check availability "
    "at the Brewton Days Inn for one night."
)

SESSION = [
    {"role": "user", "content": OWNER, "_ask_jarvis": True},
    {
        "role": "assistant",
        "content": "Assuming departure from Lynn Haven…",
        "ask_jarvis_hard_bind": True,
        "ask_jarvis_pending": False,
    },
]


def test_explicit_ask_jarvis_binds():
    assert is_ask_jarvis_command(OWNER)
    assert resolve_ask_jarvis_objective(OWNER, []) == OWNER


def test_clarification_hard_binds_with_prior():
    follow = "I already told you GP Brewton in Brewton Alabama"
    assert not is_ask_jarvis_command(follow)
    bound = resolve_ask_jarvis_objective(follow, SESSION)
    assert bound is not None
    assert "Ask Jarvis to map a route" in bound
    assert "Owner clarification:" in bound
    assert "Brewton Alabama" in bound
    assert is_ask_jarvis_command(bound)


def test_unrelated_turn_does_not_bind():
    assert resolve_ask_jarvis_objective("What time is it?", SESSION) is None
    assert resolve_ask_jarvis_objective("never mind", SESSION) is None


def test_no_prior_jarvis_does_not_bind():
    follow = "I already told you GP Brewton in Brewton Alabama"
    assert resolve_ask_jarvis_objective(follow, []) is None


def test_jarvis_voice_fail_closed_without_explicit_id():
    vid, err = require_jarvis_voice_id(None)
    assert vid is None
    assert err == JARVIS_VOICE_CONFIGURATION_UNAVAILABLE
    vid, err = require_jarvis_voice_id("Bj9UqZbhQsanLzgalpEG")
    assert vid is None
    assert err == JARVIS_VOICE_CONFIGURATION_UNAVAILABLE
    vid, err = require_jarvis_voice_id("dzRy05hNK3bab9ViJ0oU")
    assert vid == "dzRy05hNK3bab9ViJ0oU"
    assert err is None
