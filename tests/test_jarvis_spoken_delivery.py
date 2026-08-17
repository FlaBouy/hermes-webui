"""Jarvis spoken-delivery identity and production handoff grammar."""

import pytest

from api.ask_jarvis_route import (
    JARVIS_VOICE_CONFIGURATION_UNAVAILABLE,
    configured_jarvis_voice_id,
    is_ask_jarvis_command,
    is_jarvis_addressed,
    is_jarvis_greeting,
    jarvis_greeting_reply,
    jarvis_handoff_rest,
    require_jarvis_voice_id,
)
from api.smedley_document_route import compact_fta_connection_spoken


OBJECTIVE = "I need a wiring schematic for a Honeywell MU-TDOD53 FTA connection"


@pytest.mark.parametrize(
    "utterance,rest",
    [
        (f"Tell Jarvis {OBJECTIVE}", OBJECTIVE),
        (f"Ask Jarvis {OBJECTIVE}", OBJECTIVE),
        (f"Let Jarvis know that {OBJECTIVE}", OBJECTIVE),
        (f"Tell Jarvis that {OBJECTIVE}", OBJECTIVE),
        (f"Ask Jarvis to {OBJECTIVE}", OBJECTIVE),
        (f"Jarvis, {OBJECTIVE}", OBJECTIVE),
        (f"Hey Smedley, Tell Jarvis {OBJECTIVE}", OBJECTIVE),
        (f"hey smedley. ask jarvis to {OBJECTIVE}", OBJECTIVE),
        (f"Hey Smedley, Jarvis, {OBJECTIVE}", OBJECTIVE),
    ],
)
def test_jarvis_handoff_grammar_preserves_rest_and_identity(utterance, rest):
    assert is_jarvis_addressed(utterance)
    assert jarvis_handoff_rest(utterance) == rest


def test_tell_biggy_is_not_jarvis_addressed():
    assert not is_jarvis_addressed(f"Tell Biggy {OBJECTIVE}")
    assert jarvis_handoff_rest(f"Tell Biggy {OBJECTIVE}") is None


def test_live_hey_smedley_tell_jarvis_mutdod53():
    msg = (
        "Hey Smedley, Tell Jarvis I need a wiring schematic for a "
        "Honeywell MU-TDOD53 FTA connection"
    )
    assert is_jarvis_addressed(msg)
    rest = jarvis_handoff_rest(msg)
    assert rest is not None
    assert "MU-TDOD53" in rest
    assert rest.lower().startswith("i need a wiring schematic")


def test_ask_jarvis_colon_still_hard_binds():
    assert is_ask_jarvis_command("Ask Jarvis: what is the weather")
    assert is_jarvis_addressed("Ask Jarvis: what is the weather")


def test_good_morning_jarvis_greeting():
    msg = "Good morning Jarvis."
    assert is_jarvis_greeting(msg)
    assert is_jarvis_addressed(msg)
    assert jarvis_greeting_reply(msg) == "Good morning, Rick."
    assert not is_ask_jarvis_command(msg)


def test_good_morning_biggy_is_not_jarvis_addressed():
    assert not is_jarvis_addressed("Good morning Biggy.")
    assert not is_jarvis_greeting("Good morning Biggy.")


def test_require_jarvis_voice_fail_closed_without_id():
    ok, err = require_jarvis_voice_id("")
    assert ok is None
    assert err == JARVIS_VOICE_CONFIGURATION_UNAVAILABLE
    ok2, err2 = require_jarvis_voice_id("Bj9UqZbhQsanLzgalpEG")
    assert ok2 is None
    assert err2 == JARVIS_VOICE_CONFIGURATION_UNAVAILABLE


def test_configured_jarvis_voice_id_is_explicit():
    assert configured_jarvis_voice_id() == "dzRy05hNK3bab9ViJ0oU"
    ok, err = require_jarvis_voice_id(configured_jarvis_voice_id())
    assert err is None
    assert ok == "dzRy05hNK3bab9ViJ0oU"


def test_compact_fta_spoken_omits_pdf_audit():
    spoken = compact_fta_connection_spoken("MU-TDOD53", "5-13", "196")
    assert spoken == "MU-TDOD53. I found Figure 5-13, printed page 196. The diagram is open."
    assert "PDF" not in spoken
    assert "216" not in spoken
