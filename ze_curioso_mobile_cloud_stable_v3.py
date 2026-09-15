#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Zé Curioso resilient mobile entrypoint V3.

V3 keeps Cloudflare AI as first choice, but replaces the octopus procedural
fallback with five deliberately different compositions. The goal is visual
storytelling, not five prompt variations of the same centered illustration.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import ze_curioso_mobile_cloud as legacy
import ze_curioso_mobile_cloud_stable as stable
import ze_curioso_mobile_cloud_stable_v2 as v2

W, H = 1080, 1920


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _mix(a, b, t):
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


def _gradient(top=(4, 24, 48), bottom=(10, 115, 128)):
    im = Image.new("RGBA", (W, H), top + (255,))
    d = ImageDraw.Draw(im)
    for y in range(0, H, 4):
        d.rectangle((0, y, W, min(H, y + 4)), fill=_mix(top, bottom, y / H) + (255,))
    return im


def _heart_points(cx: int, cy: int, size: int):
    pts = []
    for i in range(100):
        t = 2 * math.pi * i / 100
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2*t) - 2 * math.cos(3*t) - math.cos(4*t)
        pts.append((cx + int(x * size / 32), cy - int(y * size / 32)))
    return pts


def _heart(draw, cx, cy, size, alpha=238):
    pts = _heart_points(cx, cy, size)
    draw.polygon(pts, fill=(246, 72, 96, alpha))
    draw.line(pts + [pts[0]], fill=(255, 183, 192, alpha), width=max(3, size // 18), joint="curve")


def _ocean_atmosphere(base: Image.Image, rng: random.Random, seabed=True):
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for _ in range(8):
        r = rng.randint(120, 310)
        x = rng.randint(-80, W + 80)
        y = rng.randint(50, 1200)
        gd.ellipse((x-r, y-r, x+r, y+r), fill=(120, 235, 228, rng.randint(8, 22)))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(85)))
    d = ImageDraw.Draw(base)
    for _ in range(22):
        r = rng.randint(4, 14)
        x = rng.randint(40, W - 40)
        y = rng.randint(100, 1350)
        d.ellipse((x-r, y-r, x+r, y+r), outline=(210, 248, 250, rng.randint(45, 100)), width=2)
    if seabed:
        d.polygon([(0, 1510), (150, 1472), (330, 1518), (510, 1485), (710, 1525), (900, 1470), (1080, 1504), (1080, H), (0, H)], fill=(3, 50, 61, 205))
        for x, h in [(90, 105), (205, 65), (842, 90), (960, 130)]:
            d.line((x, 1510, x-20, 1510-h), fill=(23, 103, 91, 170), width=10)
            d.line((x, 1492, x+34, 1492-h//2), fill=(23, 103, 91, 150), width=7)


def _bezier(p0, p1, p2, steps=24):
    out = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        out.append((int(u*u*p0[0] + 2*u*t*p1[0] + t*t*p2[0]), int(u*u*p0[1] + 2*u*t*p1[1] + t*t*p2[1])))
    return out


def _octopus_clean(base: Image.Image, cx: int, cy: int, scale=1.0, direction=1, alpha=238, simple=False):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    body = (167, 68, 137, alpha)
    edge = (237, 151, 205, min(255, alpha + 8))
    s = scale
    mw, mh = int(150*s), int(205*s)
    d.ellipse((cx-mw, cy-mh, cx+mw, cy+int(145*s)), fill=body, outline=edge, width=max(4, int(7*s)))
    offsets = [-125, -90, -55, -20, 20, 55, 90, 125]
    for i, off in enumerate(offsets):
        x0 = cx + int(off*s)
        y0 = cy + int(115*s)
        fan = (i - 3.5) * 42 * s
        p0 = (x0, y0)
        p1 = (int(x0 + fan*0.55), int(y0 + 120*s))
        p2 = (int(x0 + fan), int(y0 + (245 if not simple else 190)*s))
        pts = _bezier(p0, p1, p2)
        d.line(pts, fill=body, width=max(12, int(31*s)), joint="curve")
        d.line(pts, fill=edge, width=max(2, int(3*s)), joint="curve")
    if not simple and s >= .7:
        eye_y = cy - int(38*s)
        eye_dx = int(57*s)
        er = max(7, int(16*s))
        for ex in (cx-eye_dx, cx+eye_dx):
            d.ellipse((ex-er, eye_y-er, ex+er, eye_y+er), fill=(242, 235, 242, alpha))
            pr = max(3, int(6*s))
            d.ellipse((ex-pr, eye_y-pr, ex+pr, eye_y+pr), fill=(29, 34, 48, alpha))
    if direction < 0:
        layer = layer.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    base.alpha_composite(layer)


def _scene_number(destination: Path) -> int:
    m = re.search(r"(\d+)", destination.stem)
    return max(1, min(5, int(m.group(1)))) if m else 1


def _scene_1(base, rng):
    _ocean_atmosphere(base, rng, seabed=True)
    _octopus_clean(base, 330, 760, .88)
    d = ImageDraw.Draw(base)
    for x, y, s in [(730, 560, 94), (850, 720, 84), (690, 865, 82)]:
        _heart(d, x, y, s)
        d.ellipse((x-s-20, y-s-18, x+s+20, y+s+18), outline=(151, 235, 234, 90), width=4)


def _scene_2(base, rng):
    _ocean_atmosphere(base, rng, seabed=False)
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(panel)
    d.ellipse((180, 330, 900, 1110), fill=(8, 59, 77, 185), outline=(126, 226, 232, 175), width=8)
    for side in (-1, 1):
        hx = 540 + side * 205
        _heart(d, hx, 730, 88)
        gx = 540 + side * 120
        for k in range(7):
            yy = 520 + k * 48
            endx = gx + side * (110 + k * 8)
            d.line((gx, yy, endx, yy - 30), fill=(121, 228, 236, 210), width=12)
            d.ellipse((endx-8, yy-38, endx+8, yy-22), fill=(190, 247, 248, 180))
        d.line((hx - side*35, 730, gx, 700), fill=(246, 104, 126, 170), width=12)
    d.ellipse((460, 625, 620, 835), fill=(170, 73, 139, 220), outline=(239, 153, 206, 220), width=7)
    base.alpha_composite(panel)


def _scene_3(base, rng):
    _ocean_atmosphere(base, rng, seabed=False)
    d = ImageDraw.Draw(base)
    d.ellipse((250, 330, 830, 1110), fill=(5, 49, 69, 170), outline=(101, 211, 224, 135), width=7)
    _heart(d, 540, 700, 115)
    nodes = [(540, 430), (340, 520), (740, 520), (330, 900), (750, 900), (540, 1010)]
    for nx, ny in nodes:
        d.line((540, 705, nx, ny), fill=(240, 105, 127, 155), width=11)
        d.ellipse((nx-28, ny-28, nx+28, ny+28), fill=(113, 224, 231, 210), outline=(208, 250, 251, 180), width=4)
    d.ellipse((445, 570, 635, 875), outline=(222, 151, 202, 85), width=6)


def _scene_4(base, rng):
    _ocean_atmosphere(base, rng, seabed=False)
    d = ImageDraw.Draw(base)
    for y, w in [(500, 360), (630, 430), (770, 330), (900, 390)]:
        d.arc((80, y-65, 80+w, y+65), 205, 340, fill=(169, 238, 242, 125), width=9)
    _octopus_clean(base, 760, 700, .62, simple=True)
    glow = Image.new("RGBA", (W, H), (0,0,0,0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((510, 350, 1040, 1080), fill=(64, 215, 213, 22))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(65)))


def _scene_5(base, rng):
    _ocean_atmosphere(base, rng, seabed=True)
    d = ImageDraw.Draw(base)
    for x, y, r in [(170, 390, 35), (870, 300, 22), (740, 1160, 28)]:
        d.ellipse((x-r, y-r, x+r, y+r), fill=(115, 227, 221, 20), outline=(179, 242, 240, 55), width=3)
    _octopus_clean(base, 710, 650, .30, alpha=190, simple=True)
    for x in (450, 540, 630):
        _heart(d, x, 1120, 38, alpha=135)


def _octopus_v3(prompt: str, destination: Path):
    normalized = _clean(prompt)
    seed = int.from_bytes(hashlib.sha256((normalized + destination.name).encode("utf-8")).digest()[:8], "big")
    rng = random.Random(seed)
    scene = _scene_number(destination)
    palettes = [
        ((4, 22, 45), (8, 108, 125)),
        ((4, 31, 54), (14, 118, 126)),
        ((5, 28, 54), (13, 101, 122)),
        ((3, 29, 51), (9, 122, 134)),
        ((5, 25, 48), (11, 104, 116)),
    ]
    base = _gradient(*palettes[scene - 1])
    [_scene_1, _scene_2, _scene_3, _scene_4, _scene_5][scene - 1](base, rng)
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    sd.rectangle((0, H-400, W, H), fill=(0, 0, 0, 40))
    base.alpha_composite(shade.filter(ImageFilter.GaussianBlur(55)))
    destination.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(destination, "JPEG", quality=93, optimize=True)


def procedural_background_v3(prompt: str, destination: Path):
    low = _clean(prompt).lower()
    if any(k in low for k in ("polvo", "octopus")):
        _octopus_v3(prompt, destination)
        print(f"[OK] V3 composição única da cena {_scene_number(destination)}/5: {destination.name}", flush=True)
        return
    v2.improved_procedural_background(prompt, destination)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tema", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    legacy.polish_result = v2.safer_polish
    stable.procedural_background = procedural_background_v3
    stable.build_job(_clean(args.tema), Path(args.out_dir))


if __name__ == "__main__":
    main()
