"""Regression: opaque full-circumference Orb freeze mask under ARGUS rings."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRAND = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
BRAND_CSS = (ROOT / "static" / "biggy-brand.css").read_text(encoding="utf-8")


def _reactor_markup() -> str:
    return BRAND[BRAND.index("function makeReactorDock"):BRAND.index("function installSmedleyButton")]


def _mask_rule() -> str:
    start = BRAND_CSS.index("#j-orb .biggy-orb-mask{")
    end = BRAND_CSS.index("}", start) + 1
    return BRAND_CSS[start:end]


def _orb_svg_rule() -> str:
    start = BRAND_CSS.index("#j-orb svg{")
    end = BRAND_CSS.index("}", start) + 1
    return BRAND_CSS[start:end]


def test_orb_mask_exists_in_reactor_dom():
    markup = _reactor_markup()
    assert 'id="j-orb-mask"' in markup
    assert 'data-testid="biggy-orb-mask"' in markup
    assert "biggy-orb-mask" in markup
    assert "biggy-orb-freeze-overlay" in markup
    assert 'data-biggy-layer="orb-mask"' in markup


def test_orb_mask_is_beneath_orb_svg_art():
    markup = _reactor_markup()
    mask_at = markup.index('id="j-orb-mask"')
    svg_at = markup.index('<svg viewBox="0 0 200 200"')
    assert mask_at < svg_at
    assert "z-index:0" in _mask_rule()
    assert "z-index:1" in _orb_svg_rule()
    assert "position:relative" in _orb_svg_rule()


def test_orb_mask_has_truly_opaque_background():
    rule = _mask_rule()
    assert "background:#04050a" in rule
    assert "rgba(" not in rule
    assert "transparent" not in rule
    assert "opacity:" not in rule
    # Same void as the galaxy canvas so the freeze reads as solid backdrop.
    assert "background:#04050a" in BRAND_CSS[BRAND_CSS.index(".biggy-v6-world{"):]


def test_orb_mask_covers_full_circular_204px_circumference():
    rule = _mask_rule()
    assert "width:204px" in rule
    assert "height:204px" in rule
    assert "border-radius:50%" in rule
    assert "inset:0" in rule
    orb_rule = BRAND_CSS[BRAND_CSS.index("#j-orb{"):BRAND_CSS.index("#j-orb .biggy-orb-mask{")]
    assert "width:204px;height:204px" in orb_rule


def test_orb_mask_stacking_stays_in_reactor_above_galaxy():
    layers = BRAND_CSS[BRAND_CSS.index("#mainChat.biggy-brand-iwo{"):BRAND_CSS.index("#mainChat.biggy-brand-iwo .messages-shell")]
    assert "--biggy-layer-galaxy:0" in layers
    assert "--biggy-layer-reactor:10" in layers
    reactor = BRAND_CSS[BRAND_CSS.index(".biggy-argus-reactor{"):BRAND_CSS.index("#j-orb{")]
    assert "z-index:var(--biggy-layer-reactor, 10)" in reactor
    markup = _reactor_markup()
    # Mask lives inside #j-orb (reactor), not over chip/state/fleet controls.
    assert markup.index('id="j-orb"') < markup.index('id="j-orb-mask"')
    assert markup.index("</svg>") < markup.index('id="j-state"')
    assert "pointer-events:none" in _mask_rule()
