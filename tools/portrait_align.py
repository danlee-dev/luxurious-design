#!/usr/bin/env python3
"""Line up cut-out portraits by the face: same face width, same face height.

Team photos are taken at different distances and crops. Scaled to the same
photo width, one head comes out bigger than the others, and the widest photo
still shows its cut shoulders after a bottom and side fade. This scales each
cut-out so its face box has the same width, puts every face at the same point
of one canvas, and fades the body inside an oval under the face, so the edges
of the original photo do not show. The head is never faded from above, and a
photo cropped short fades out before its own bottom edge.

Face boxes come from tools/faces.swift, or by hand as image:x,y,w (left, top
and width of the face box in that image's pixels):

    tools/faces a_cut.png b_cut.png c_cut.png > faces.txt
    python3 tools/portrait_align.py a_cut.png b_cut.png c_cut.png --faces faces.txt --sheet sheet.png
    python3 tools/portrait_align.py a_cut.png:221,289,283 b_cut.png:216,308,339
"""

from __future__ import annotations

import argparse
import os
import re
import sys

import numpy as np
from PIL import Image, ImageColor, ImageDraw

FACE_LINE = re.compile(r"^(?P<name>.+?) face x=(?P<x>-?[\d.]+) y=(?P<y>-?[\d.]+) w=(?P<w>[\d.]+)")
INLINE = re.compile(r"^(?P<path>.+):(?P<x>-?[\d.]+),(?P<y>-?[\d.]+),(?P<w>[\d.]+)$")


def read_faces(path: str) -> dict[str, tuple[float, float, float]]:
    """tools/faces output -> {file name: (x, y, w)}, keeping the widest face of each file."""
    if path == "-":
        text = sys.stdin.read()
    else:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    boxes: dict[str, tuple[float, float, float]] = {}
    counts: dict[str, int] = {}
    for line in text.splitlines():
        m = FACE_LINE.match(line.strip())
        if not m:
            continue
        name, box = m["name"], (float(m["x"]), float(m["y"]), float(m["w"]))
        counts[name] = counts.get(name, 0) + 1
        if name not in boxes or box[2] > boxes[name][2]:
            boxes[name] = box
    for name, n in counts.items():
        if n > 1:
            print(f"note: {name} has {n} faces; using the largest", file=sys.stderr)
    return boxes


def fade_mask(cw: int, ch: int, face: float, face_top: float, soft: float, bottom: float, bottom_edge: float) -> np.ndarray:
    """Multiplier for the alpha: an oval under the face, a bottom fade, the head kept whole."""
    yy, xx = np.mgrid[0:ch, 0:cw].astype(float)
    cx, cy = cw / 2, face_top + 0.62 * face  # just under the middle of the face box
    rx, ry = 0.97 * cw / 2, (ch - cy) + 0.04 * face  # stops short of the sides, reaches past the bottom
    nx, ny = (xx - cx) / rx, (yy - cy) / ry
    oval = np.clip((1 - np.sqrt(nx ** 2 + ny ** 2)) / soft, 0, 1) ** 1.3
    # never fade the head and hair from above; the soft edges keep a line out of long hair
    keep = np.clip((1 - np.abs(nx)) / 0.08, 0, 1) * np.clip((cy + 0.3 * face - yy) / (0.3 * face), 0, 1)
    low = np.clip((bottom_edge - yy) / bottom, 0, 1) ** 1.6
    return np.minimum(np.maximum(oval, keep), low)


def visible_edges(alpha: np.ndarray, rect: tuple[int, int, int, int], limit: float = 0.1) -> list[tuple[str, float]]:
    """Edges of the original photo that fall inside the canvas and still show."""
    ch, cw = alpha.shape
    x0, y0, x1, y1 = rect
    rows, cols = slice(max(0, y0), min(ch, y1)), slice(max(0, x0), min(cw, x1))
    lines = []
    if 0 < x0 < cw:
        lines.append(("left", alpha[rows, x0]))
    if 0 < x1 < cw:
        lines.append(("right", alpha[rows, x1 - 1]))
    if 0 < y0 < ch:
        lines.append(("top", alpha[y0, cols]))
    if 0 < y1 < ch:
        lines.append(("bottom", alpha[y1 - 1, cols]))
    found = [(side, float(v.max()) / 255) for side, v in lines if v.size]
    return [(side, peak) for side, peak in found if peak > limit]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+", help="cut-out PNGs, each optionally followed by :x,y,w of its face box")
    ap.add_argument("--faces", help="output of tools/faces for these images ('-' reads stdin)")
    ap.add_argument("--face-width", type=float, default=340, help="face width in the output, px (default 340)")
    ap.add_argument("--canvas", default="2.0,2.7", help="output width,height in face widths (default 2.0,2.7)")
    ap.add_argument("--face-top", type=float, default=0.7, help="room above the face box, in face widths (default 0.7)")
    ap.add_argument("--soft", type=float, default=0.28, help="width of the oval fade, share of the oval radius (default 0.28)")
    ap.add_argument("--bottom", type=float, default=0.55, help="height of the bottom fade, in face widths (default 0.55)")
    ap.add_argument("--same-bottom", action="store_true", help="end every body at the height of the shortest photo")
    ap.add_argument("--out-dir", help="where to save; default is next to each input")
    ap.add_argument("--suffix", default="_aligned", help="added to each output name (default _aligned)")
    ap.add_argument("--sheet", help="save a side-by-side check image with face guides here")
    ap.add_argument("--paper", default="#F4F3EF", help="background of the check image (default #F4F3EF)")
    args = ap.parse_args()

    face = args.face_width
    try:
        kw, kh = (float(v) for v in args.canvas.split(","))
    except ValueError:
        raise SystemExit("--canvas takes width,height in face widths, for example 2.0,2.7")
    cw, ch = round(kw * face), round(kh * face)
    face_top = args.face_top * face
    known = read_faces(args.faces) if args.faces else {}

    jobs = []
    for item in args.images:
        m = INLINE.match(item)
        if m and not os.path.exists(item):
            path, box = m["path"], (float(m["x"]), float(m["y"]), float(m["w"]))
        else:
            path, box = item, known.get(os.path.basename(item))
        if box is None:
            raise SystemExit(f"no face box for {path}: run tools/faces on it and pass --faces, or write {path}:x,y,w")
        if box[2] <= 0:
            raise SystemExit(f"face width must be positive for {path}")
        jobs.append((path, box))

    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)

    placed = []
    for path, (fx, fy, fw) in jobs:
        src = Image.open(path).convert("RGBA")
        s = face / fw
        big = src.resize((max(1, round(src.width * s)), max(1, round(src.height * s))), Image.LANCZOS)
        left, up = round((fx + fw / 2) * s - cw / 2), round(fy * s - face_top)
        canvas = big.crop((left, up, left + cw, up + ch))  # outside the photo stays transparent
        rect = (-left, -up, big.width - left, big.height - up)  # the photo's extent in canvas pixels
        placed.append((path, fw, s, canvas, rect))

    # the body fades out before the photo's own bottom edge, so a tight crop never shows a cut line
    ends = [min(ch, rect[3]) for *_, rect in placed]
    if args.same_bottom:
        ends = [min(ends)] * len(ends)

    outputs = []
    for (path, fw, s, canvas, rect), end in zip(placed, ends):
        a = np.array(canvas).astype(float)
        a[:, :, 3] *= fade_mask(cw, ch, face, face_top, args.soft, args.bottom * face, end)
        out = Image.fromarray(np.clip(np.rint(a), 0, 255).astype(np.uint8))

        stem = os.path.splitext(os.path.basename(path))[0]
        dest = os.path.join(args.out_dir or os.path.dirname(path) or ".", f"{stem}{args.suffix}.png")
        out.save(dest)
        outputs.append(out)
        print(f"saved {dest} {cw}x{ch}  face {fw:.0f}px x{s:.2f}  body ends at {end}px")
        if s > 2:
            print(f"warning: {stem} is enlarged {s:.1f}x and may look soft at 100%", file=sys.stderr)
        if end - args.bottom * face < face_top + face:
            print(f"warning: {stem}: the photo ends close under the face, so the fade reaches the chin; use a photo cropped lower", file=sys.stderr)
        for side, peak in visible_edges(np.array(out)[:, :, 3], rect):
            print(f"warning: {stem}: the photo's {side} edge shows (alpha {peak:.2f}); use a wider photo or a narrower --canvas", file=sys.stderr)

    if args.sheet:
        k, gap = 0.5, 24
        tw, th = round(cw * k), round(ch * k)
        sheet = Image.new("RGBA", (len(outputs) * (tw + gap) + gap, th + 2 * gap), ImageColor.getrgb(args.paper))
        for i, im in enumerate(outputs):
            sheet.alpha_composite(im.resize((tw, th), Image.LANCZOS), (gap + i * (tw + gap), gap))
        draw = ImageDraw.Draw(sheet)
        guide = (208, 52, 44, 255)
        for y in (face_top, face_top + face):  # top and bottom of the face box (Vision boxes are square)
            draw.line([(0, gap + round(y * k)), (sheet.width, gap + round(y * k))], fill=guide, width=1)
        for i in range(len(outputs)):
            x = gap + i * (tw + gap) + tw // 2
            draw.line([(x, gap), (x, gap + th)], fill=guide, width=1)
        sheet.convert("RGB").save(args.sheet)
        print(f"saved {args.sheet}")


if __name__ == "__main__":
    main()
