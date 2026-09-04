import json
from pathlib import Path

import pytest

from api import biggy_pets


ROOT = Path(__file__).resolve().parents[1]


def make_pet(root, name="bones", **changes):
    folder = root / name
    folder.mkdir()
    manifest = {"id": name, "displayName": name.title(), "spriteVersionNumber": 2,
                "spritesheetPath": "spritesheet.webp"}
    manifest.update(changes)
    (folder / "pet.json").write_text(json.dumps(manifest))
    (folder / "spritesheet.webp").write_bytes(b"RIFFtestWEBPtest")
    return folder


def test_catalog_multiple_and_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("BIGGY_PETS_DIR", str(tmp_path))
    assert biggy_pets.catalog()["pets"] == []
    make_pet(tmp_path)
    make_pet(tmp_path, "second")
    pets = biggy_pets.catalog()["pets"]
    assert [p["id"] for p in pets] == ["bones", "second"]
    assert pets[0]["spriteUrl"].startswith("/api/biggy/pets/bones/sprite?v=")
    assert str(tmp_path) not in json.dumps(pets)
    assert biggy_pets.sprite("bones")[0] == b"RIFFtestWEBPtest"


@pytest.mark.parametrize("changes", [
    {"spritesheetPath": "../secret.webp"}, {"spritesheetPath": "/secret.webp"},
    {"spriteVersionNumber": 999}, {"id": "different"},
    {"spritesheetPath": "active.svg"},
])
def test_invalid_manifest_excluded(tmp_path, monkeypatch, changes):
    monkeypatch.setenv("BIGGY_PETS_DIR", str(tmp_path))
    make_pet(tmp_path, **changes)
    result = biggy_pets.catalog()
    assert result["pets"] == []
    assert result["unavailable"] == 1
    with pytest.raises(ValueError):
        biggy_pets.sprite("bones")


def test_symlinks_and_traversal_rejected(tmp_path, monkeypatch):
    root = tmp_path / "pets"
    root.mkdir()
    monkeypatch.setenv("BIGGY_PETS_DIR", str(root))
    outside = make_pet(tmp_path)
    (root / "bones").symlink_to(outside, target_is_directory=True)
    assert biggy_pets.catalog()["pets"] == []
    for name in ("bones", "../bones", "%2e%2e", "a/b"):
        with pytest.raises(ValueError):
            biggy_pets.sprite(name)
    folder = make_pet(root, "second")
    (folder / "spritesheet.webp").unlink()
    (folder / "spritesheet.webp").symlink_to(outside / "spritesheet.webp")
    with pytest.raises(ValueError):
        biggy_pets.sprite("second")


def test_replacement_invalidates_url_and_removed_sprite_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("BIGGY_PETS_DIR", str(tmp_path))
    folder = make_pet(tmp_path)
    before = biggy_pets.catalog()["pets"][0]["spriteUrl"]
    (folder / "spritesheet.webp").write_bytes(b"RIFFnew WEBPbody")
    assert biggy_pets.catalog()["pets"][0]["spriteUrl"] != before
    (folder / "spritesheet.webp").unlink()
    with pytest.raises(ValueError):
        biggy_pets.sprite("bones")


def test_strip_layout_and_anchor(tmp_path, monkeypatch):
    monkeypatch.setenv("BIGGY_PETS_DIR", str(tmp_path))
    make_pet(tmp_path, "biggy", spriteVersionNumber=None, format="strip-v1", frames=6,
             frameWidth=362, frameHeight=724, frameDurations=[280,110,110,140,140,320],
             defaultAnchor="dialog-right")
    item = biggy_pets.catalog()["pets"][0]
    assert (item["columns"], item["rows"], item["frameWidth"], item["frameHeight"]) == (6,1,362,724)
    assert item["frameDurations"] == [280,110,110,140,140,320]
    assert item["defaultAnchor"] == "dialog-right"


@pytest.mark.parametrize("changes", [{"frames": 0}, {"frameWidth": -1},
    {"frameDurations": [1]}, {"frameDurations": [160]}, {"frameHeight": True}])
def test_invalid_strip_layout(tmp_path, monkeypatch, changes):
    monkeypatch.setenv("BIGGY_PETS_DIR", str(tmp_path))
    fields = dict(spriteVersionNumber=None, format="strip-v1", frames=6,
                  frameWidth=362, frameHeight=724, frameDurations=[160]*6)
    fields.update(changes)
    make_pet(tmp_path, "biggy", **fields)
    assert biggy_pets.catalog()["pets"] == []


def test_pet_loader_uses_parent_asset_version_for_cache_busting():
    brand = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
    assert "document.currentScript?.src" in brand
    assert "const BUILD_ID = BRAND_ASSET_VERSION || 'biggy-runtime';" in brand
    assert "20260903-review-tool-handoff-57" not in brand
    assert "biggy-pets.js?v=${BUILD_ID}" in brand
    assert "biggy-pets.css?v=${BUILD_ID}" in brand
