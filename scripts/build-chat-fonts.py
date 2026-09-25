"""One-off dev tool: subset Liberation Sans/Mono into scripts/fonts/ for the agent chat.

Needs fontTools and brotli (pip install fonttools brotli). The workflow never runs this; it only
reads the committed woff2 files and metrics.json, so the chat renders without extra dependencies.
Liberation fonts are SIL Open Font License 1.1 and metric-compatible with Arial and Courier New,
so the measured line wraps also hold if a viewer's browser falls back to those faces.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

OUT = Path(__file__).resolve().parent / "fonts"
FACES = {
    "sans-regular": "LiberationSans-Regular.ttf",
    "sans-bold": "LiberationSans-Bold.ttf",
    "mono-regular": "LiberationMono-Regular.ttf",
}
# Printable ASCII, Latin-1 letters and the typographic marks the chat uses.
CHARS = "".join(map(chr, range(32, 127))) + "".join(map(chr, range(0xA0, 0x100))) + "‘’“”–—…•·›→✓"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("/usr/share/fonts/truetype/liberation"))
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    metrics = {}
    for name, filename in FACES.items():
        font = TTFont(args.source / filename)
        cmap, hmtx = font.getBestCmap(), font["hmtx"].metrics
        upm = font["head"].unitsPerEm
        metrics[name] = {c: round(hmtx[cmap[ord(c)]][0] / upm, 5) for c in CHARS if ord(c) in cmap}
        options = subset.Options()
        options.flavor = "woff2"
        options.layout_features = ["kern"]
        options.hinting = False
        options.name_IDs = [0, 1, 2, 13, 14]  # keep copyright and license names
        subsetter = subset.Subsetter(options)
        subsetter.populate(text=CHARS)
        subsetter.subset(font)
        font.flavor = "woff2"
        font.save(OUT / f"{name}.woff2")
    (OUT / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
