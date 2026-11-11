#!/usr/bin/env python3
"""Draw the six Demo District school logos into scripts/demo_logos/.

    python scripts/make_demo_logos.py

Original artwork for fictional schools: an evergreen for Cedar Ridge, a maple leaf for Maple
Valley, a peak for Summit View. Each high school gets a shield and its feeder middle school a
round badge in the same colors. Needs Pillow and the macOS fonts named below; the PNGs it
writes are committed, so this only has to be re-run to change the artwork.
scripts/seed_demo_logos.py puts them on the schools.
"""
import math
import os

from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_logos")
S = 3                                   # supersample, then shrink to 400 px
W = 400 * S
BOLD = "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf"
WHITE = (255, 255, 255, 255)

SCHOOLS = {            # stem: (emblem, primary, accent, emblem color)
    "Cedar Ridge": ("tree", (24, 84, 56), (229, 178, 60), (255, 255, 255)),
    "Maple Valley": ("leaf", (28, 44, 80), (222, 98, 44), (222, 98, 44)),
    "Summit View": ("peak", (30, 78, 160), (150, 200, 240), (255, 255, 255)),
}


def P(pts, cx, cy, r):
    return [(cx + x * r, cy + y * r) for x, y in pts]


def mirror(half):
    return half + [(-x, y) for x, y in reversed(half)]


def shield(inset):
    """Shield outline, `inset` px inside the full-size one."""
    l, r, t, mid, tip = 0.10 * W + inset, 0.90 * W - inset, 0.05 * W + inset, 0.50 * W, 0.965 * W - inset * 1.25
    pts = [(l, t), (r, t), (r, mid)]
    for i in range(1, 25):              # right flank curving to the point, then back up the left
        u = i / 24
        pts.append(((1 - u) ** 2 * r + 2 * u * (1 - u) * r + u * u * W / 2,
                    (1 - u) ** 2 * mid + 2 * u * (1 - u) * (0.80 * W) + u * u * tip))
    for i in range(23, -1, -1):
        u = i / 24
        pts.append(((1 - u) ** 2 * l + 2 * u * (1 - u) * l + u * u * W / 2,
                    (1 - u) ** 2 * mid + 2 * u * (1 - u) * (0.80 * W) + u * u * tip))
    return pts


def tree(d, cx, cy, r, fill, _accent):
    for top, bottom, half in ((-1.0, -0.30, 0.42), (-0.62, 0.18, 0.58), (-0.20, 0.66, 0.74)):
        d.polygon(P([(0, top), (half, bottom), (-half, bottom)], cx, cy, r), fill=fill)
    d.rectangle([cx - 0.10 * r, cy + 0.66 * r, cx + 0.10 * r, cy + 1.0 * r], fill=fill)


def leaf(d, cx, cy, r, fill, _accent, vein=(28, 44, 80, 255)):
    half = [(0, -1.0), (0.15, -0.68), (0.31, -0.77), (0.25, -0.26), (0.53, -0.50), (0.59, -0.34),
            (0.93, -0.40), (0.81, -0.12), (0.97, -0.02), (0.53, 0.36), (0.60, 0.54), (0.07, 0.46),
            (0.07, 1.0)]
    co, si = math.cos(math.radians(-16)), math.sin(math.radians(-16))

    def rot(pts):                       # tilt the whole leaf, as if it just landed
        return P([(x * co - y * si, x * si + y * co) for x, y in pts], cx, cy, r)

    d.polygon(rot(mirror(half)), fill=fill)
    w = max(2, int(0.035 * r))
    for tip in ((0, -0.78), (0.70, -0.26), (-0.70, -0.26), (0.42, 0.26), (-0.42, 0.26)):
        d.line(rot([(0, 0.42), tip]), fill=vein, width=w)


def peak(d, cx, cy, r, fill, accent, far=(96, 146, 214, 255)):
    d.ellipse([cx - 0.92 * r, cy - 0.98 * r, cx - 0.44 * r, cy - 0.50 * r], fill=fill)          # sun
    d.polygon(P([(-1.0, 0.85), (-0.40, -0.12), (0.12, 0.85)], cx, cy, r), fill=far)             # far peak
    d.polygon(P([(-0.52, 0.85), (0.22, -0.95), (1.0, 0.85)], cx, cy, r), fill=accent)           # near peak
    snow = [(0.22, -0.95), (0.47, -0.38), (0.33, -0.50), (0.21, -0.30), (0.09, -0.48), (-0.03, -0.34)]
    d.polygon(P(snow, cx, cy, r), fill=fill)


def text(d, s, cx, cy, size, fill, max_w):
    f = ImageFont.truetype(BOLD, size)
    while d.textlength(s, font=f) > max_w and size > 10:
        size -= 2
        f = ImageFont.truetype(BOLD, size)
    d.text((cx, cy), s, font=f, fill=fill, anchor="mm")


def logo(stem, level):
    emblem, primary, accent, ink = SCHOOLS[stem]
    primary, accent, ink = primary + (255,), accent + (255,), ink + (255,)
    im = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    inner = Image.new("L", (W, W), 0)   # the colored field: what the name ribbon is clipped to
    cx = W / 2
    if level == "High School":
        d.polygon(shield(0), fill=accent)
        d.polygon(shield(0.022 * W), fill=WHITE)
        d.polygon(shield(0.040 * W), fill=primary)
        ImageDraw.Draw(inner).polygon(shield(0.040 * W), fill=255)
        ey, er, by = 0.275 * W, 0.185 * W, 0.565 * W
        ly, lsize, name_w = 0.735 * W, 0.085 * W, 0.66 * W
    else:
        d.ellipse([0.03 * W, 0.03 * W, 0.97 * W, 0.97 * W], fill=accent)
        d.ellipse([0.052 * W, 0.052 * W, 0.948 * W, 0.948 * W], fill=WHITE)
        d.ellipse([0.070 * W, 0.070 * W, 0.930 * W, 0.930 * W], fill=primary)
        ImageDraw.Draw(inner).ellipse([0.070 * W, 0.070 * W, 0.930 * W, 0.930 * W], fill=255)
        ey, er, by = 0.300 * W, 0.190 * W, 0.600 * W
        ly, lsize, name_w = 0.775 * W, 0.080 * W, 0.70 * W
    globals()[emblem](d, cx, ey, er, ink, accent)
    bh = 0.085 * W
    ribbon = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ribbon)
    rd.rectangle([0, by - bh, W, by + bh], fill=WHITE)
    rd.rectangle([0, by - bh, W, by - bh + 0.012 * W], fill=accent)
    rd.rectangle([0, by + bh - 0.012 * W, W, by + bh], fill=accent)
    im.paste(ribbon, (0, 0), Image.composite(ribbon.getchannel("A"), Image.new("L", (W, W), 0), inner))
    text(d, stem.upper(), cx, by + 0.012 * W, int(0.150 * W), primary, name_w)
    text(d, level.upper(), cx, ly, int(lsize), WHITE, 0.50 * W)
    return im.resize((400, 400), Image.LANCZOS)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for stem in SCHOOLS:
        for level in ("High School", "Middle School"):
            name = f"{stem} {level}".lower().replace(" ", "-") + ".png"
            logo(stem, level).save(os.path.join(OUT, name), optimize=True)
            print("wrote", name)
