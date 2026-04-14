#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "src")

import matplotlib

matplotlib.use("Agg")

from cc_mapf.model import RenderConfig
from cc_mapf.render import render_paper_gallery
from cc_mapf.utils import load_json, load_yaml


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/render/render_paper_gallery.py <run_directory> [output_directory] [render_config_yaml]")
        return 1
    run_dir = Path(sys.argv[1])
    if not run_dir.exists():
        print(f"Error: Directory not found: {run_dir}")
        return 1
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    config = None
    if len(sys.argv) > 3:
        config = RenderConfig.from_dict(load_yaml(sys.argv[3]))
    else:
        payload = load_json(run_dir / "results.json")
        config = RenderConfig.from_dict(payload.get("render_config"))
    gallery_dir, manifest = render_paper_gallery(run_dir, output_dir=output_dir, config=config)
    print(f"Paper gallery created: {gallery_dir}")
    print(f"Manifest entries: {len(manifest.sources)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
