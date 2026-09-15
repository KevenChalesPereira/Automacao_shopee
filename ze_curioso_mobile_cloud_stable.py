#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Resilient entrypoint for Zé Curioso mobile generation.

Cloudflare Workers AI remains the preferred background provider. If it is
unavailable (including free-quota HTTP 429), this wrapper creates a brand-new
procedural 9:16 background from each scene prompt instead of reusing an old
image or failing the whole video.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import ze_curioso_mobile_cloud as legacy

W, H = 1080, 1920
_cloudflare_generate = legacy.generate_background
_background_provenance: list[dict] = []


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _palette(seed: int, ocean: bool = False):
    if ocean:
        palettes = [
            ((5, 28, 58), (7, 96, 137), (55, 190, 184)),
            ((4, 31, 67), (10, 111, 143), (82, 207, 190)),
            ((10, 25, 54), (19, 84, 132), (65, 171, 188)),
        ]
    else:
        palettes = [
            ((21, 18, 47), (72, 45, 115), (235, 123, 89)),
            ((15, 32, 52), (37, 91, 115), (241, 180, 81)),
            ((35, 22, 45), (114, 50, 78), (247, 164, 92)),
            ((18, 35, 42), (44, 104, 94), (224, 176, 89)),
        ]
    return palettes[seed % len(palettes)]


def _mix(a, b, t: float):
    return tuple(round(a[i] * (1 - t) + b[i] * t) for i in range(3))


def _gradient(base: Image.Image, top, mid, bottom):
    draw = ImageDraw.Draw(base)
    step = 4
    for y in range(0, H, step):
        p = y / max(1, H - 1)
        if p < 0.55:
            color = _mix(top, mid, p / 0.55)
        else:
            color = _mix(mid, bottom, (p - 0.55) / 0.45)
        draw.rectangle((0, y, W, min(H, y + step)), fill=color)


def _soft_glows(base: Image.Image, rng: random.Random, accent):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for _ in range(8):
        r = rng.randint(120, 360)
        x = rng.randint(-80, W + 80)
        y = rng.randint(80, H - 260)
        c = tuple(accent) + (rng.randint(16, 42),)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=c)
    layer = layer.filter(ImageFilter.GaussianBlur(90))
    base.alpha_composite(layer)


def _draw_bubbles(draw: ImageDraw.ImageDraw, rng: random.Random, count=24):
    for _ in range(count):
        r = rng.randint(5, 24)
        x = rng.randint(55, W - 55)
        y = rng.randint(100, H - 430)
        draw.ellipse((x-r, y-r, x+r, y+r), outline=(220, 250, 255, rng.randint(65, 150)), width=max(2, r // 5))


def _heart_points(cx: int, cy: int, s: int):
    pts = []
    for i in range(80):
        t = 2 * math.pi * i / 80
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2*t) - 2 * math.cos(3*t) - math.cos(4*t)
        pts.append((cx + int(x * s / 32), cy - int(y * s / 32)))
    return pts


def _draw_octopus(base: Image.Image, rng: random.Random, prompt_low: str):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx = 540 + rng.randint(-45, 45)
    cy = 760 + rng.randint(-70, 70)
    body = (193, 91, 151, 235)
    edge = (245, 185, 217, 235)
    # Eight curved-looking tentacles built from smooth point chains.
    for i in range(8):
        angle = (i - 3.5) * 0.31
        x0, y0 = cx + int(math.sin(angle) * 135), cy + 200
        direction = -1 if i % 2 else 1
        pts = []
        for j in range(9):
            yy = y0 + j * 58
            xx = x0 + int(math.sin(j * 0.8 + i) * (45 + j * 8)) + direction * j * 12
            pts.append((xx, yy))
        draw.line(pts, fill=body, width=max(24, 56 - i * 2), joint="curve")
        draw.line(pts, fill=edge, width=5, joint="curve")
    draw.ellipse((cx-180, cy-230, cx+180, cy+240), fill=body, outline=edge, width=8)
    # Small highlights keep the fallback illustration readable without text.
    draw.ellipse((cx-78, cy-55, cx-42, cy-19), fill=(250, 239, 246, 220))
    draw.ellipse((cx+42, cy-55, cx+78, cy-19), fill=(250, 239, 246, 220))
    if "cora" in prompt_low or "heart" in prompt_low:
        for dx, dy in [(-72, 35), (0, 78), (72, 35)]:
            draw.polygon(_heart_points(cx+dx, cy+dy, 58), fill=(249, 84, 107, 220))
    base.alpha_composite(layer)


def _draw_space(base: Image.Image, rng: random.Random):
    draw = ImageDraw.Draw(base)
    for _ in range(150):
        x, y = rng.randrange(W), rng.randrange(H - 300)
        r = rng.choice([1, 1, 1, 2, 3])
        a = rng.randint(90, 230)
        draw.ellipse((x-r, y-r, x+r, y+r), fill=(245, 245, 255, a))
    px, py, pr = rng.randint(300, 760), rng.randint(520, 1040), rng.randint(130, 240)
    draw.ellipse((px-pr, py-pr, px+pr, py+pr), fill=(198, 120, 100, 210), outline=(247, 207, 163, 210), width=7)


def _draw_abstract(base: Image.Image, rng: random.Random, accent):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for _ in range(9):
        x = rng.randint(160, W-160)
        y = rng.randint(260, H-520)
        rx = rng.randint(90, 280)
        ry = rng.randint(80, 240)
        draw.ellipse((x-rx, y-ry, x+rx, y+ry), fill=tuple(accent)+(rng.randint(20, 58),))
    layer = layer.filter(ImageFilter.GaussianBlur(24))
    base.alpha_composite(layer)


def procedural_background(prompt: str, destination: Path):
    normalized = _clean(prompt)
    digest = hashlib.sha256(normalized.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], "big")
    rng = random.Random(seed)
    low = normalized.lower()
    ocean = any(k in low for k in ("polvo", "octopus", "ocean", "oceano", "mar ", "underwater", "subaqu", "água", "agua"))
    space = any(k in low for k in ("space", "espaço", "espaco", "planet", "planeta", "galaxy", "galáxia", "galaxia"))
    top, mid, bottom = _palette(seed, ocean=ocean)

    base = Image.new("RGBA", (W, H), top + (255,))
    _gradient(base, top, mid, bottom)
    _soft_glows(base, rng, bottom)
    draw = ImageDraw.Draw(base)

    if ocean:
        # Soft light rays and bubbles create a fresh underwater scene.
        for x in range(-200, W+300, 260):
            draw.polygon([(x, 0), (x+90, 0), (x+420, 1450), (x+250, 1450)], fill=(210, 245, 255, 15))
        _draw_bubbles(draw, rng)
        if "polvo" in low or "octopus" in low:
            _draw_octopus(base, rng, low)
        else:
            _draw_abstract(base, rng, bottom)
    elif space:
        _draw_space(base, rng)
    else:
        _draw_abstract(base, rng, bottom)

    # Keep the lower corners less busy for the recurring Zé overlay.
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    sd.rectangle((0, H-500, W, H), fill=(0, 0, 0, 38))
    shade = shade.filter(ImageFilter.GaussianBlur(45))
    base.alpha_composite(shade)

    destination.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(destination, "JPEG", quality=91, optimize=True)


def stable_generate_background(prompt: str, destination: Path):
    try:
        _cloudflare_generate(prompt, destination)
        # Validate that a real image was produced before declaring success.
        with Image.open(destination) as im:
            im.verify()
        source = "cloudflare_ai"
        reason = None
        print(f"[OK] Background IA Cloudflare: {destination.name}", flush=True)
    except Exception as exc:
        reason = _clean(exc)[:320]
        print(f"[!] Cloudflare indisponível ({reason}); criando fallback NOVO para {destination.name}.", flush=True)
        procedural_background(prompt, destination)
        source = "procedural_fallback"
        print(f"[OK] Fallback novo gerado: {destination.name}", flush=True)

    _background_provenance.append({
        "arquivo": destination.name,
        "source": source,
        "prompt_sha256": hashlib.sha256(_clean(prompt).encode("utf-8")).hexdigest(),
        "fallback_reason": reason,
    })


def build_job(topic: str, out_dir: Path):
    _background_provenance.clear()
    legacy.generate_background = stable_generate_background
    legacy.build_job(topic, out_dir)

    job_path = out_dir / "curiosidade.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    fallback_used = any(item["source"] == "procedural_fallback" for item in _background_provenance)
    job["background_provenance"] = _background_provenance
    job["background_fallback_used"] = fallback_used
    job["visual_mode_runtime"] = (
        "mixed_cloudflare_ai_and_procedural_fallback" if fallback_used and any(item["source"] == "cloudflare_ai" for item in _background_provenance)
        else "procedural_fallback_fresh" if fallback_used
        else "cloudflare_ai"
    )
    job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "background_provenance.json").write_text(
        json.dumps({"tema": topic, "scenes": _background_provenance}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[OK] Proveniência visual: {job['visual_mode_runtime']}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tema", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    build_job(_clean(args.tema), Path(args.out_dir))


if __name__ == "__main__":
    main()
