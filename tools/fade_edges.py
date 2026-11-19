#!/usr/bin/env python3
"""Fade the bottom and the shoulders of a cut-out portrait into the page.

ID photos are cropped at the chest and at both shoulders. Cut out as they are,
they leave a hard bottom edge and vertical edges at the sides, which read as a
box again. This fades the bottom part away and, lower down, the left and right
edges, leaving the head untouched.

    python3 tools/fade_edges.py person_cut.png person_fade.png
"""

from __future__ import annotations

import argparse

import numpy as np
from PIL import Image


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="cut-out PNG with transparency")
    ap.add_argument("output", help="output PNG")
    ap.add_argument("--bottom", type=float, default=0.45, help="share of the subject's height faded at the bottom (default 0.45)")
    ap.add_argument("--power", type=float, default=1.8, help="curve of the bottom fade; higher fades sooner (default 1.8)")
    ap.add_argument("--sides", type=float, default=0.22, help="share of the width faded at each side (default 0.22)")
    ap.add_argument("--from", dest="side_from", type=float, default=0.35, help="height share where the side fade starts (default 0.35)")
    ap.add_argument("--full", type=float, default=0.70, help="height share where the side fade reaches full strength (default 0.70)")
    ap.add_argument("--crop", action="store_true", help="crop away empty rows above the subject")
    args = ap.parse_args()

    img = Image.open(args.input).convert("RGBA")
    a = np.array(img).astype(float)
    alpha = a[:, :, 3]
    h, w = alpha.shape
    ys, _ = np.where(alpha > 10)
    if ys.size == 0:
        raise SystemExit("the image has no visible subject")
    top = int(ys.min())

    start = int(h - args.bottom * (h - top))
    ramp = np.ones(h)
    if h > start:
        t = (np.arange(start, h) - start) / (h - start)
        ramp[start:] = (1 - t) ** args.power

    xs = np.arange(w)
    side = np.clip(np.minimum(xs, w - 1 - xs) / max(1.0, args.sides * w), 0, 1) ** 1.4
    rows = np.arange(h)[:, None] / h
    weight = np.clip((rows - args.side_from) / max(1e-6, args.full - args.side_from), 0, 1)
    mult = (1 - weight * (1 - side[None, :])) * ramp[:, None]

    a[:, :, 3] = alpha * mult
    out = Image.fromarray(np.clip(a, 0, 255).astype("uint8"))
    if args.crop:
        out = out.crop((0, max(0, top - 10), w, h))
    out.save(args.output)
    print(f"saved {args.output} {out.size[0]}x{out.size[1]}")


if __name__ == "__main__":
    main()
