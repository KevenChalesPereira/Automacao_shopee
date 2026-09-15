#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Zé Curioso resilient mobile entrypoint V2.

Adds a stricter factual edit pass and a more polished scene-aware procedural
fallback while preserving Cloudflare Workers AI as the preferred provider.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import ze_curioso_mobile_cloud as legacy
import ze_curioso_mobile_cloud_stable as stable

W, H = 1080, 1920
_original_polish = legacy.polish_result


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def safer_polish(api_key: str, topic: str, result: dict) -> dict:
    first = _original_polish(api_key, topic, result)
    candidate = json.dumps(first, ensure_ascii=False)
    prompt = f"""
Você é o revisor factual final do canal Zé Curioso. Devolva SOMENTE JSON válido.
Tema/pergunta: {topic}

JSON já editado:
{candidate}

REGRAS OBRIGATÓRIAS:
- mantenha exatamente 5 cenas e os mesmos campos;
- 55 a 78 palavras no roteiro total, contando os bordões;
- preserve exatamente "{legacy.OPENING}" no começo da primeira fala;
- preserve exatamente "{legacy.CLOSING}" no fim da quinta fala;
- responda diretamente ao tema com fatos amplamente estabelecidos;
- remova qualquer afirmação especulativa apresentada como certeza;
- NÃO invente redundância biológica: jamais diga que um órgão compensa a falha de outro sem evidência sólida;
- NÃO invente números, estudos, causas evolutivas, taxas, diagnósticos ou consequências médicas;
- se uma formulação for controversa ou simplificada demais, troque por uma versão prudente e correta;
- não repita o mesmo fato só para preencher a quinta cena; use um fechamento útil e factual;
- cada background_prompt deve ilustrar literalmente a fala, sem pessoas, mascote ou texto;
- roteiro deve ser exatamente a concatenação das 5 falas.
""".strip()
    try:
        data = legacy.groq_json(api_key, prompt, temperature=0.10)
        text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        checked = legacy.core.extract_json_object(text)
        scenes = checked.get("cenas") if isinstance(checked, dict) else None
        if isinstance(scenes, list) and len(scenes) == 5:
            print("[OK] Revisão factual final aplicada.", flush=True)
            return checked
    except Exception as exc:
        print(f"[!] Revisão factual extra falhou; mantendo versão anterior: {exc}", flush=True)
    return first


def _mix(a, b, t):
    return tuple(int(a[i] * (1-t) + b[i] * t) for i in range(3))


def _heart_points(cx: int, cy: int, size: int):
    pts = []
    for i in range(96):
        t = 2 * math.pi * i / 96
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2*t) - 2 * math.cos(3*t) - math.cos(4*t)
        pts.append((cx + int(x * size / 32), cy - int(y * size / 32)))
    return pts


def _vertical_gradient(top, bottom):
    im = Image.new("RGB", (W, H), top)
    d = ImageDraw.Draw(im)
    for y in range(0, H, 4):
        c = _mix(top, bottom, y / H)
        d.rectangle((0, y, W, min(H, y+4)), fill=c)
    return im.convert("RGBA")


def _ocean_texture(base: Image.Image, rng: random.Random):
    # Dim, blurred caustic shafts: atmosphere without the giant white bars from V1.
    rays = Image.new("RGBA", (W, H), (0,0,0,0))
    rd = ImageDraw.Draw(rays)
    for _ in range(7):
        x = rng.randint(-250, W+150)
        width = rng.randint(45, 100)
        drift = rng.randint(100, 260)
        rd.polygon([(x,0),(x+width,0),(x+width+drift,1280),(x+drift,1280)], fill=(180,240,245,rng.randint(10,22)))
    rays = rays.filter(ImageFilter.GaussianBlur(28))
    base.alpha_composite(rays)

    d = ImageDraw.Draw(base)
    # Seabed and distant rock silhouettes.
    d.polygon([(0,1460),(150,1410),(300,1485),(480,1435),(650,1490),(820,1420),(1080,1475),(1080,H),(0,H)], fill=(4,56,67,150))
    for _ in range(26):
        r = rng.randint(4,18)
        x = rng.randint(45,W-45)
        y = rng.randint(90,1370)
        d.ellipse((x-r,y-r,x+r,y+r), outline=(210,248,250,rng.randint(55,120)), width=2)


def _draw_heart(draw: ImageDraw.ImageDraw, cx, cy, size, alpha=235):
    draw.polygon(_heart_points(cx, cy, size), fill=(247,72,92,alpha))
    draw.line(_heart_points(cx, cy, size), fill=(255,184,189,alpha), width=max(2,size//18), joint="curve")


def _octopus_layer(rng: random.Random, scene_kind: str):
    layer = Image.new("RGBA", (W,H), (0,0,0,0))
    d = ImageDraw.Draw(layer)
    cx = 540 + rng.randint(-35,35)
    cy = 710 + rng.randint(-30,45)
    if scene_kind == "swim":
        cx += 45
        cy -= 20
    body = (174,66,137,238)
    edge = (240,151,209,225)
    sucker = (249,190,221,155)

    # Organic mantle; no cartoon mouth, keeping the host Zé as the character.
    d.ellipse((cx-190,cy-245,cx+190,cy+210), fill=body, outline=edge, width=8)
    d.ellipse((cx-82,cy-75,cx-35,cy-28), fill=(242,231,239,225))
    d.ellipse((cx+35,cy-75,cx+82,cy-28), fill=(242,231,239,225))
    d.ellipse((cx-62,cy-58,cx-43,cy-39), fill=(25,30,42,230))
    d.ellipse((cx+43,cy-58,cx+62,cy-39), fill=(25,30,42,230))

    # Eight sinuous tentacles with small suckers.
    starts = [-145,-105,-65,-25,25,65,105,145]
    for i, sx in enumerate(starts):
        pts=[]
        phase = rng.random()*math.pi
        for j in range(22):
            yy = cy+155 + j*36
            xx = cx+sx + math.sin(j*0.42+phase)*(35+j*2.5) + (i-3.5)*j*1.8
            pts.append((int(xx),int(yy)))
        d.line(pts, fill=body, width=44, joint="curve")
        d.line(pts, fill=edge, width=4, joint="curve")
        for px,py in pts[5::4]:
            d.ellipse((px-5,py-5,px+5,py+5), fill=sucker)

    if scene_kind == "three":
        for dx,dy in [(-70,35),(70,35),(0,105)]:
            _draw_heart(d,cx+dx,cy+dy,62)
    elif scene_kind == "gills":
        _draw_heart(d,cx-82,cy+72,64)
        _draw_heart(d,cx+82,cy+72,64)
        # Feathery gill cues and short circulation paths.
        for side in (-1,1):
            gx = cx + side*145
            for k in range(6):
                y = cy + 5 + k*24
                d.line((gx,y,gx+side*(48+k*4),y-18), fill=(119,226,236,205), width=6)
            d.line((cx+side*76,cy+80,gx,cy+65), fill=(103,217,231,180), width=9)
    elif scene_kind == "systemic":
        _draw_heart(d,cx,cy+100,78)
        for ex,ey in [(cx,cy-155),(cx-125,cy+5),(cx+125,cy+5),(cx-120,cy+180),(cx+120,cy+180)]:
            d.line((cx,cy+95,ex,ey), fill=(241,105,124,165), width=8)
    elif scene_kind == "swim":
        for j in range(6):
            y = cy+350+j*60
            d.arc((95,y-45,390,y+45), 190, 350, fill=(184,241,247,130), width=8)
    else:
        _draw_heart(d,cx,cy+90,72)
    return layer


def _scene_kind(prompt: str):
    low = prompt.lower()
    # Use narration-specific clues before the global topic phrase.
    if any(k in low for k in ("brânquia", "branquia", "gill")):
        return "gills"
    if any(k in low for k in ("coração central", "coracao central", "systemic", "cérebro", "cerebro", "tecidos")):
        return "systemic"
    if any(k in low for k in ("quando nada", "swim", "nadando", "nadar", "frequência", "frequencia", "energia")):
        return "swim"
    if any(k in low for k in ("três corações", "tres coracoes", "three hearts")):
        return "three"
    return "general"


def improved_procedural_background(prompt: str, destination: Path):
    normalized = _clean(prompt)
    seed = int.from_bytes(__import__('hashlib').sha256(normalized.encode('utf-8')).digest()[:8], 'big')
    rng = random.Random(seed)
    low = normalized.lower()
    ocean = any(k in low for k in ("polvo","octopus","ocean","oceano","underwater","mar ","subaqu"))

    if ocean:
        palettes = [((4,24,48),(16,119,128)),((5,31,60),(20,105,126)),((9,28,55),(18,126,119))]
        top,bottom = palettes[seed % len(palettes)]
        base = _vertical_gradient(top,bottom)
        _ocean_texture(base,rng)
        kind = _scene_kind(normalized)
        base.alpha_composite(_octopus_layer(rng,kind))
    else:
        palettes = [((19,22,48),(65,84,120)),((28,25,48),(117,66,98)),((13,38,47),(47,114,103))]
        top,bottom = palettes[seed % len(palettes)]
        base = _vertical_gradient(top,bottom)
        layer = Image.new("RGBA",(W,H),(0,0,0,0))
        d=ImageDraw.Draw(layer)
        for _ in range(11):
            x,y=rng.randint(150,W-150),rng.randint(180,H-520)
            rx,ry=rng.randint(80,260),rng.randint(70,220)
            d.ellipse((x-rx,y-ry,x+rx,y+ry),fill=(230,170,105,rng.randint(12,35)))
        layer=layer.filter(ImageFilter.GaussianBlur(38))
        base.alpha_composite(layer)

    # Subtle vignette; bottom stays calm for Zé and the speech bubble.
    vignette=Image.new("RGBA",(W,H),(0,0,0,0))
    vd=ImageDraw.Draw(vignette)
    vd.rectangle((0,H-430,W,H),fill=(0,0,0,28))
    vignette=vignette.filter(ImageFilter.GaussianBlur(70))
    base.alpha_composite(vignette)
    destination.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(destination,"JPEG",quality=92,optimize=True)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--tema',required=True)
    ap.add_argument('--out-dir',required=True)
    args=ap.parse_args()

    legacy.polish_result = safer_polish
    stable.procedural_background = improved_procedural_background
    stable.build_job(_clean(args.tema),Path(args.out_dir))


if __name__=='__main__':
    main()
