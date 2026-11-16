#!/usr/bin/env python3
"""어두운 배경 위의 밝은 피사체를 투명 PNG로 분리합니다.

글자를 피사체 뒤에 두는 합성(docs/06-photo-and-depth.md)에 쓰는 컷아웃을
포토샵 없이 만드는 스크립트입니다. Pillow 만 사용합니다.

동작 순서
  1. 픽셀 밝기를 max(R, G, B) 로 구하고 작업 배율로 줄여 살짝 흐립니다.
  2. 임계값으로 밝은 곳과 어두운 곳을 나눕니다.
  3. 배경 씨앗에서 이어진 어두운 영역을 배경으로 칠합니다.
  4. 피사체 씨앗에서 이어진 밝은 영역을 피사체로 칠합니다.
  5. 피사체에 붙어 있고 배경과 이어지지 않은 어두운 구멍을 피사체에 넣습니다.
  6. 피사체 가장자리 근처에서는 밝기에 비례한 반투명 알파를 줍니다.
  7. 알파를 원본 크기로 되돌리고 약하게 흐려 저장합니다.

예시
  python3 cutout.py photo.png subject.png --seed 1610,900 --seed 1610,1150 \\
      --preview check.png
"""

import argparse
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

BACKGROUND = 128
SUBJECT = 200


def point(text):
    try:
        x, y = text.split(",")
        return int(x), int(y)
    except ValueError:
        raise argparse.ArgumentTypeError("x,y 형식으로 적습니다. 예: 1610,900")


def value_range(text):
    try:
        lo, hi = text.split(",")
        lo, hi = int(lo), int(hi)
    except ValueError:
        raise argparse.ArgumentTypeError("낮은값,높은값 형식으로 적습니다. 예: 62,128")
    if not 0 <= lo < hi <= 255:
        raise argparse.ArgumentTypeError("0 <= 낮은값 < 높은값 <= 255 여야 합니다.")
    return lo, hi


def odd(text):
    n = int(text)
    if n < 1 or n % 2 == 0:
        raise argparse.ArgumentTypeError("1 이상의 홀수여야 합니다.")
    return n


def hex_color(text):
    t = text.lstrip("#")
    if len(t) != 6:
        raise argparse.ArgumentTypeError("#RRGGBB 형식으로 적습니다.")
    return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))


def parse_args():
    ap = argparse.ArgumentParser(
        description="어두운 배경 위의 밝은 피사체를 투명 PNG 로 분리합니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="좌표는 모두 원본 이미지 기준 픽셀입니다 (왼쪽 위가 0,0).",
    )
    ap.add_argument("input", help="원본 사진 경로")
    ap.add_argument("output", help="저장할 투명 PNG 경로")
    ap.add_argument(
        "--seed", type=point, action="append", required=True, metavar="X,Y",
        help="피사체의 밝은 부분 위 한 점. 떨어진 덩어리마다 하나씩 여러 번 지정합니다.",
    )
    ap.add_argument(
        "--bg-seed", type=point, action="append", metavar="X,Y",
        help="배경의 어두운 부분 위 한 점. 생략하면 위쪽 세 점과 좌우 가운데를 씁니다.",
    )
    ap.add_argument(
        "--threshold", type=int, default=76,
        help="밝은 곳과 어두운 곳을 나누는 밝기 (0~255, 기본 76). "
             "배경 일부가 딸려 오면 올리고, 피사체가 깎이면 내립니다.",
    )
    ap.add_argument(
        "--soft", type=value_range, default=(62, 128), metavar="LO,HI",
        help="가장자리 반투명 구간 (기본 62,128). LO 이하는 투명, HI 이상은 불투명입니다.",
    )
    ap.add_argument(
        "--scale", type=float, default=0.5,
        help="영역을 찾을 때 쓰는 작업 배율 (기본 0.5). 작을수록 빠르고 잡음에 강합니다.",
    )
    ap.add_argument(
        "--edge", type=odd, default=7,
        help="반투명 가장자리를 허용할 범위 (작업 배율 기준 픽셀, 홀수, 기본 7).",
    )
    ap.add_argument(
        "--hole", type=odd, default=9,
        help="피사체에 넣을 어두운 구멍을 찾는 범위 (작업 배율 기준 픽셀, 홀수, 기본 9).",
    )
    ap.add_argument(
        "--feather", type=float, default=1.1,
        help="최종 알파를 흐리는 반경 (원본 기준 픽셀, 기본 1.1).",
    )
    ap.add_argument("--preview", help="단색 배경에 얹은 확인용 이미지를 저장할 경로")
    ap.add_argument(
        "--preview-bg", type=hex_color, default=(255, 0, 200), metavar="#RRGGBB",
        help="확인용 이미지의 배경색 (기본 #FF00C8). 사진에 없는 색이어야 헤일로가 보입니다.",
    )
    return ap.parse_args()


def main():
    args = parse_args()
    if not 0 < args.scale <= 1:
        sys.exit("--scale 은 0 초과 1 이하여야 합니다.")
    if not 0 <= args.threshold <= 255:
        sys.exit("--threshold 는 0~255 여야 합니다.")

    image = Image.open(args.input).convert("RGB")
    width, height = image.size
    small_w = max(1, round(width * args.scale))
    small_h = max(1, round(height * args.scale))

    def to_small(p):
        x = min(small_w - 1, max(0, int(p[0] * args.scale)))
        y = min(small_h - 1, max(0, int(p[1] * args.scale)))
        return x, y

    # 1. 밝기
    r, g, b = image.split()
    value = ImageChops.lighter(ImageChops.lighter(r, g), b)
    small = value.resize((small_w, small_h), Image.BILINEAR)
    small = small.filter(ImageFilter.GaussianBlur(1.0))

    # 2. 임계값
    threshold = args.threshold
    mask = small.point(lambda v: 255 if v >= threshold else 0)

    # 3. 배경
    bg_seeds = args.bg_seed or [
        (3, 3), (width // 2, 3), (width - 4, 3),
        (3, height // 2), (width - 4, height // 2),
    ]
    for seed in bg_seeds:
        s = to_small(seed)
        if mask.getpixel(s) == 0:
            ImageDraw.floodfill(mask, s, BACKGROUND)

    # 4. 피사체
    hits = 0
    for seed in args.seed:
        s = to_small(seed)
        v = mask.getpixel(s)
        if v == 255:
            ImageDraw.floodfill(mask, s, SUBJECT)
            hits += 1
        elif v == SUBJECT:
            hits += 1
        else:
            print(
                f"경고: 씨앗 {seed[0]},{seed[1]} 은 임계값보다 어둡습니다 "
                f"(밝기 {small.getpixel(s)}). 건너뜁니다.",
                file=sys.stderr,
            )
    if hits == 0:
        sys.exit("피사체 씨앗이 모두 어두운 곳에 있습니다. 좌표나 --threshold 를 확인합니다.")

    subject = mask.point(lambda v: 255 if v == SUBJECT else 0)

    # 5. 피사체에 붙은 어두운 구멍 (배경과 이어지지 않은 어두운 영역)
    near = subject.filter(ImageFilter.MaxFilter(args.hole))
    enclosed_dark = mask.point(lambda v: 255 if v == 0 else 0)
    holes = ImageChops.darker(enclosed_dark, near)
    core = ImageChops.lighter(subject, holes).resize((width, height), Image.BILINEAR)

    # 6. 가장자리 반투명
    lo, hi = args.soft
    soft = value.point(
        lambda v: 0 if v <= lo else (255 if v >= hi else int(255 * (v - lo) / (hi - lo)))
    )
    edge_region = subject.filter(ImageFilter.MaxFilter(args.edge))
    edge_region = edge_region.resize((width, height), Image.BILINEAR)
    alpha = ImageChops.lighter(core, ImageChops.darker(soft, edge_region))

    # 7. 저장
    if args.feather > 0:
        alpha = alpha.filter(ImageFilter.GaussianBlur(args.feather))
    result = image.copy()
    result.putalpha(alpha)
    result.save(args.output, optimize=True)

    covered = sum(alpha.histogram()[128:]) / (width * height)
    print(f"저장: {args.output} ({width}x{height}, 불투명 영역 {covered:.1%})")

    if args.preview:
        backdrop = Image.new("RGB", (width, height), args.preview_bg)
        backdrop.paste(result, (0, 0), result)
        backdrop.save(args.preview)
        print(f"확인용: {args.preview}")


if __name__ == "__main__":
    main()
