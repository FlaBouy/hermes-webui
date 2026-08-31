"""Static contract for Biggy's persistent Calendar rail action."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRAND = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
BRAND_CSS = (ROOT / "static" / "biggy-brand.css").read_text(encoding="utf-8")


def test_calendar_is_first_pa_data_surface_after_travel():
    assert "'Travel',\n    'Calendar',\n    'Mail',\n    'Weather'," in BRAND
    categories = BRAND[BRAND.index("const TRAVEL_CATEGORIES"):BRAND.index("function railCategoryKey")]
    assert "'Other'" not in categories


def test_calendar_uses_live_same_origin_source():
    assert "/api/biggy/pa/calendar" in BRAND
    assert 'data-biggy-operator-panel="calendar"' in BRAND
    assert "['phone', 'calendar', 'mail', 'tasks', 'notes', 'alerts']" in BRAND


def test_calendar_workspace_has_day_month_navigation_and_overlays():
    assert "calendarWorkspaceState" in BRAND
    assert "calendarRequestWindow" in BRAND
    assert "renderCalendarWorkspace" in BRAND
    assert "CALENDAR OVERLAYS" in BRAND
    assert "Add / manage Google calendars" in BRAND
    assert "operatorButton('Day'" in BRAND
    assert "operatorButton('Month'" in BRAND


def test_calendar_write_controls_are_guarded_and_visible():
    assert "Add to calendar" in BRAND
    assert "Save changes" in BRAND
    assert "Delete “${String(event.summary || 'this event')}” from your calendar?" in BRAND
    assert "/api/biggy/pa/calendar/create" in BRAND
    assert "/api/biggy/pa/calendar/update" in BRAND
    assert "/api/biggy/pa/calendar/delete" in BRAND


def test_calendar_month_fits_the_full_docked_panel_height():
    assert "flex:1 1 auto;min-height:0;max-height:none" in BRAND_CSS
    assert "min-height:64px" in BRAND_CSS


def test_calendar_overlays_default_all_listed_on_card_open():
    """On each Calendar open, every calendarList source is selected by default."""
    assert "function resetCalendarOverlayDefaults(dlg)" in BRAND
    assert "function syncCalendarOverlayDefaults(dlg, calendar)" in BRAND
    assert "function calendarSourceIds(calendar)" in BRAND
    assert "overlaysUserModified: false" in BRAND
    assert "if (key === 'calendar') resetCalendarOverlayDefaults(dlg);" in BRAND
    assert "state.overlaysUserModified = true;" in BRAND
    assert "if (syncCalendarOverlayDefaults(dlg, calendar))" in BRAND
    assert "calendar.calendar_sources" in BRAND
    # Session toggles still refresh the panel; reopen resets via setActiveCategory.
    assert "state.calendarIds = check.checked" in BRAND
    assert "Add / manage Google calendars" in BRAND


def test_calendar_conflicts_are_highlighted_from_structured_agent_evidence_until_card_close():
    assert "function setCalendarConflictEvidence(dlg, evidence)" in BRAND
    assert "function isCalendarConflictEvent(dlg, event)" in BRAND
    assert "m.calendar_evidence" in BRAND
    assert "is-calendar-conflict" in BRAND
    assert "SCHEDULE CONFLICT${conflict.count === 1 ? '' : 'S'} FOUND" in BRAND
    assert "if (collapsed) clearCalendarConflictHighlight(dlg);" in BRAND
    assert ".biggy-calendar-conflict-banner" in BRAND_CSS
    assert ".biggy-calendar-event.is-calendar-conflict" in BRAND_CSS
