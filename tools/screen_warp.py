#!/usr/bin/env python3
"""Put a screen image onto a device photo whose display is chroma-key green.

The green area's four corners are found from the photo, the screen image is
warped onto them with a perspective transform at `--scale` times the photo's
resolution, green spill at the edge is removed, and a faint glare is added.
Pass `--alpha` (a cut-out of the same photo, same size) to keep the device's
transparent background in the output.

    python3 tools/screen_warp.py laptop_green.png screen.png out.png --alpha laptop_cut.png
"""

from __future__ import annotations

import argparse
import math

import numpy as np
from PIL import Image, ImageFilter


def green_mask(rgb: np.ndarray, margin: int) -> np.ndarray:
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    return (g - np.maximum(r, b)) > margin


def find_quad(mask: np.ndarray) -> list[tuple[float, float]]:
    ys, xs = np.where(mask)
    if xs.size == 0:
        raise SystemExit("no green screen found: check the photo or lower --margin")
    s, d = xs + ys, xs - ys
    tl = (xs[s.argmin()], ys[s.argmin()])
    br = (xs[s.argmax()], ys[s.argmax()])
    tr = (xs[d.argmax()], ys[d.argmax()])
    bl = (xs[d.argmin()], ys[d.argmin()])
    return [tuple(map(float, p)) for p in (tl, tr, br, bl)]


def grow(quad: list[tuple[float, float]], px: float) -> list[tuple[float, float]]:
    cx = sum(p[0] for p in quad) / 4
    cy = sum(p[1] for p in quad) / 4
    out = []
    for x, y in quad:
        vx, vy = x - cx, y - cy
        n = math.hypot(vx, vy) or 1.0
        out.append((x + vx / n * px, y + vy / n * px))
    return out


def perspective_coeffs(dst: list[tuple[float, float]], w: int, h: int) -> tuple[float, ...]:
    """Coefficients PIL wants: output pixel (x, y) -> input pixel (u, v)."""
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    a, b = [], []
    for (x, y), (u, v) in zip(dst, src):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    return tuple(np.linalg.solve(np.array(a, float), np.array(b, float)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo", help="device photo with a chroma-key green display")
    ap.add_argument("screen", help="the screen image to put on the display")
    ap.add_argument("output", help="output PNG")
    ap.add_argument("--alpha", help="cut-out of the same photo (same size); its alpha is kept")
    ap.add_argument("--scale", type=float, default=2.0, help="work at this multiple of the photo size (default 2)")
    ap.add_argument("--grow", type=float, default=4.0, help="push the corners out by this many photo pixels (default 4)")
    ap.add_argument("--margin", type=int, default=40, help="how much G must exceed R and B to count as screen (default 40)")
    ap.add_argument("--glare", type=float, default=10.0, help="peak glare added to the screen, 0-255 (default 10)")
    ap.add_argument("--dim", type=float, default=0.975, help="screen brightness multiplier (default 0.975)")
    args = ap.parse_args()

    photo = Image.open(args.photo).convert("RGB")
    w0, h0 = photo.size
    quad = grow(find_quad(green_mask(np.array(photo).astype(int), args.margin)), args.grow)

    size = (round(w0 * args.scale), round(h0 * args.scale))
    big = photo.resize(size, Image.LANCZOS)
    quad = [(x * args.scale, y * args.scale) for x, y in quad]

    screen = Image.open(args.screen).convert("RGB")
    warped = screen.transform(size, Image.PERSPECTIVE, perspective_coeffs(quad, *screen.size), Image.BICUBIC)

    arr = np.array(warped).astype(float) * args.dim
    hh, ww = arr.shape[:2]
    yy, xx = np.mgrid[0:hh, 0:ww]
    glare = np.clip(1 - ((xx - ww * 0.62) + (yy - hh * 0.18) * 1.4) / (ww * 0.55), 0, 1) * args.glare
    warped = Image.fromarray(np.clip(arr + glare[:, :, None], 0, 255).astype("uint8"))

    o = np.array(big).astype(int)
    soft = np.clip((o[:, :, 1] - np.maximum(o[:, :, 0], o[:, :, 2]) - args.margin) / 80.0, 0, 1)
    mask = Image.fromarray((soft * 255).astype("uint8")).filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    out = Image.composite(warped, big, mask)

    a = np.array(out).astype(int)
    spill = (a[:, :, 1] - np.maximum(a[:, :, 0], a[:, :, 2])) > 18
    a[:, :, 1][spill] = np.maximum(a[:, :, 0], a[:, :, 2])[spill] + 6
    out = Image.fromarray(np.clip(a, 0, 255).astype("uint8")).convert("RGBA")

    if args.alpha:
        cut = Image.open(args.alpha).convert("RGBA").resize(size, Image.LANCZOS)
        out.putalpha(cut.split()[3])
        bbox = out.getbbox()
        if bbox:
            out = out.crop(bbox)
    out.save(args.output)
    print(f"saved {args.output} {out.size[0]}x{out.size[1]}  corners {[(round(x), round(y)) for x, y in quad]}")


if __name__ == "__main__":
    main()
