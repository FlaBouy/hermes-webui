"""Static contract for Biggy's operational right-rail panels."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRAND = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")


def test_operator_actions_are_present_in_the_persistent_right_rail():
    for label in ("Mail", "Tasks", "Notes", "Alerts"):
        assert f"'{label}'," in BRAND


def test_operator_panels_use_existing_same_origin_sources():
    assert "/api/biggy/pa/mail" in BRAND
    assert "/api/biggy/pa/calendar" in BRAND
    assert "/api/kanban/board?board=fleet-coordination" in BRAND
    assert "/api/notes/sources" in BRAND
    assert "/api/biggy/v6/world/status" in BRAND
    assert "/api/biggy/fleet/status" in BRAND


def test_mail_remains_honest_when_local_google_auth_is_absent():
    assert "Biggy local Google authorization is required." in BRAND
    assert "Codex plugins are connected" in BRAND


def test_mail_is_draft_first_with_explicit_send_confirmation():
    assert "Create draft" in BRAND
    assert "Nothing has been sent." in BRAND
    assert "window.confirm(`Send this email" in BRAND
    assert "/api/biggy/pa/mail/draft" in BRAND
    assert "/api/biggy/pa/mail/send" in BRAND
    assert "/api/biggy/pa/mail/discard" in BRAND


def test_operator_panels_do_not_take_map_or_galaxy_ownership():
    start = BRAND.index("async function refreshOperatorPanel")
    end = BRAND.index("function ensureTravelMapDialog", start)
    operator_block = BRAND[start:end]
    assert "setGalaxyRenderPaused" not in operator_block
    assert "renderMapViewModelOnce" not in operator_block


def test_notes_panel_is_a_local_obsidian_workspace_not_a_read_only_status_list():
    assert "/api/notes/search" in BRAND
    assert "/api/notes/item" in BRAND
    assert "/api/notes/create" in BRAND
    assert "/api/notes/update" in BRAND
    assert "/api/notes/delete" in BRAND
    assert "New note" in BRAND
    assert "Search notes" in BRAND
    assert "Save note" in BRAND
    assert "Delete “${String(note.title || 'this note')}”?" in BRAND
    assert "confirmed: true" in BRAND
    assert "source=obsidian" in BRAND
    assert "source: 'obsidian'" in BRAND
    assert "Obsidian vault ready." in BRAND
