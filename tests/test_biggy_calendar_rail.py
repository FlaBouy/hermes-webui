"""Static contract for Biggy's persistent Calendar rail action."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRAND = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")


def test_calendar_is_first_pa_data_surface_after_travel():
    assert "'Travel',\n    'Calendar',\n    'Mail',\n    'Weather'," in BRAND
    categories = BRAND[BRAND.index("const TRAVEL_CATEGORIES"):BRAND.index("function railCategoryKey")]
    assert "'Other'" not in categories


def test_calendar_uses_live_same_origin_source():
    assert "/api/biggy/pa/calendar" in BRAND
    assert 'data-biggy-operator-panel="calendar"' in BRAND
    assert "['calendar', 'mail', 'tasks', 'notes', 'alerts']" in BRAND


def test_calendar_write_controls_are_guarded_and_visible():
    assert "Add to calendar" in BRAND
    assert "Save changes" in BRAND
    assert "Delete “${String(event.summary || 'this event')}” from your calendar?" in BRAND
    assert "/api/biggy/pa/calendar/create" in BRAND
    assert "/api/biggy/pa/calendar/update" in BRAND
    assert "/api/biggy/pa/calendar/delete" in BRAND
