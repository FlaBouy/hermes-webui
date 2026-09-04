#!/usr/bin/env python3
"""Build the standalone cockpit-pet reviewer ZIP from tracked source files."""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
FILES = {
    ROOT / "static" / "argus-cockpit-pet-poc.html": "argus-cockpit-pet-poc.html",
    ROOT / "static" / "argus-cockpit-pet-poc.js": "argus-cockpit-pet-poc.js",
    ROOT / "static" / "argus-orb-template.png": "argus-orb-template.png",
    ROOT / "docs" / "argus-cockpit-pet-poc-share-readme.md": "README.md",
    ROOT / "docs" / "argus-cockpit-pet-poc-feedback.md": "FEEDBACK.md",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.output, "w", compression=ZIP_DEFLATED) as archive:
        for source, packaged_name in FILES.items():
            if not source.is_file():
                raise FileNotFoundError(source)
            archive.write(source, f"argus-cockpit-pet-poc/{packaged_name}")
    print(args.output)


if __name__ == "__main__":
    main()
