#!/usr/bin/env python3
"""Place the official MCA neighborhood drawing on the street map.

The printed map is three separate north-up drawings, not a survey. Each panel
is cropped and stretched as a rectangle onto the streets named on its frame.
Interior streets will not all match — warping them onto OSM made the drawing
look worse. Districts should follow those named frame streets, not this raster.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "public" / "maps" / "mca-neighborhood.png"
OUT_DIR = ROOT / "public" / "maps"
META = ROOT / "public" / "data" / "overlays.json"

# Crops on the 3301×5101 PNG. Bounds are [[south, west], [north, east]].
PANELS = {
    "north": {
        # CP Blvd · Havana · 64th · 56th
        "crop": (1078, 302, 2036, 1288),
        "bounds": [[39.79840, -104.88449], [39.81299, -104.86609]],
    },
    "mid": {
        # Spruce · Dallas · 56th · I-70
        "crop": (328, 1308, 1558, 2786),
        "bounds": [[39.77720, -104.89734], [39.79840, -104.87547]],
    },
    "south": {
        # Quebec · Peoria · I-70 · Montview
        "crop": (58, 2830, 3102, 4700),
        "bounds": [[39.74743, -104.90339], [39.77595, -104.84689]],
    },
}


def white_to_alpha(im: Image.Image, thresh: int = 246) -> Image.Image:
    rgba = im.convert("RGBA")
    arr = np.array(rgba)
    white = (arr[:, :, 0] >= thresh) & (arr[:, :, 1] >= thresh) & (arr[:, :, 2] >= thresh)
    arr[white, 3] = 0
    return Image.fromarray(arr)


def mask_south_compass(im: Image.Image) -> Image.Image:
    arr = np.array(im)
    h, w = arr.shape[:2]
    arr[int(h * 0.78) :, int(w * 0.42) :, 3] = 0
    return Image.fromarray(arr)


def main() -> None:
    src = Image.open(SRC).convert("RGB")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    meta = {"source": "23_MCA_NEIGHBORHOODmap.pdf", "panels": []}

    for name, spec in PANELS.items():
        crop = src.crop(spec["crop"])
        overlay = white_to_alpha(crop)
        if name == "south":
            overlay = mask_south_compass(overlay)
        path = OUT_DIR / f"overlay-{name}.png"
        overlay.save(path, optimize=True)
        meta["panels"].append(
            {
                "id": name,
                "url": f"/maps/overlay-{name}.png",
                "bounds": spec["bounds"],
                "crop": list(spec["crop"]),
                "size": [overlay.width, overlay.height],
            }
        )
        print(f"{name:5s} {overlay.size} -> {path.name}")

    META.write_text(json.dumps(meta, indent=2) + "\n")
    print("wrote", META)


if __name__ == "__main__":
    main()
