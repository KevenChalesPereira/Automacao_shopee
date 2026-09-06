#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import html
import json
import math
import random
import wave
from array import array
import re
import shutil
import subprocess
import sys
import textwrap
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

VOICE = "pt-BR-FranciscaNeural"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
W, H = 1080, 1920


def run(cmd, cwd=None):
    print("[>] " + " ".join(str(x) for x in cmd), flush=True)
    result = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )
    if result.returncode != 0:
        print(result.stdout[-3000:], flush=True)
        print(result.stderr[-12000:], flush=True)
        raise RuntimeError(f"Comando falhou: {cmd[0]}")
    return result


def audio_duration(audio):
    result = run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio),
    ])
    try:
        return max(8.0, float(result.stdout.strip()))
    except Exception:
        return 30.0


def font(size, bold=True):
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size)
    except Exception:
        return ImageFont.load_default()


def fit_font(draw, text, max_width, start_size, min_size=28):
    size = start_size
    while size > min_size:
        f = font(size)
        box = draw.multiline_textbbox((0, 0), text, font=f, spacing=8, align="center")
        if box[2] - box[0] <= max_width:
            return f
        size -= 2
    return font(min_size)


def create_procedural_background(path):
    random.seed(41)
    img = Image.new("RGB", (W, H), (8, 10, 20))

    glows = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glows, "RGBA")
    gd.ellipse((-420, -300, 650, 800), fill=(38, 135, 255, 150))
    gd.ellipse((520, 280, 1500, 1370), fill=(163, 62, 255, 115))
    gd.ellipse((160, 1120, 1040, 2030), fill=(255, 89, 48, 75))
    glows = glows.filter(ImageFilter.GaussianBlur(155))
    img = Image.alpha_composite(img.convert("RGBA"), glows)

    deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco, "RGBA")
    for _ in range(75):
        x = random.randrange(35, W - 35)
        y = random.randrange(220, H - 170)
        r = random.choice([1, 1, 2, 2, 3])
        a = random.randrange(35, 120)
        dd.ellipse((x-r, y-r, x+r, y+r), fill=(255, 255, 255, a))
    # pedestal / halo
    dd.ellipse((170, 1190, 910, 1435), fill=(0, 0, 0, 95))
    dd.ellipse((230, 1200, 850, 1390), outline=(123, 172, 255, 100), width=5)
    dd.arc((160, 310, 920, 1070), 195, 340, fill=(255,255,255,50), width=3)
    img = Image.alpha_composite(img, deco)
    img.convert("RGB").save(path, quality=94)


def corner_average(im, box_size=32):
    rgb = im.convert("RGB")
    w, h = rgb.size
    areas = [
        (0, 0, min(box_size,w), min(box_size,h)),
        (max(0,w-box_size), 0, w, min(box_size,h)),
        (0, max(0,h-box_size), min(box_size,w), h),
        (max(0,w-box_size), max(0,h-box_size), w, h),
    ]
    vals = []
    for box in areas:
        crop = rgb.crop(box)
        px = list(crop.getdata())
        if not px: continue
        vals.append(tuple(sum(p[i] for p in px)//len(px) for i in range(3)))
    return tuple(sum(v[i] for v in vals)//len(vals) for i in range(3)) if vals else (255,255,255)


def try_border_cutout(source, target):
    im = Image.open(source).convert("RGBA")
    im.thumbnail((920, 1050), Image.Resampling.LANCZOS)
    bg = corner_average(im)
    # Only attempt if corners are reasonably neutral/light/dark and similar.
    rgb = im.convert("RGB")
    w, h = rgb.size
    pix = rgb.load()
    alpha = Image.new("L", (w, h), 255)
    ap = alpha.load()

    def dist(p):
        return math.sqrt(sum((p[i]-bg[i])**2 for i in range(3)))

    q = deque()
    seen = bytearray(w*h)
    stride = w
    # seed every 3 px along border so connected background is found reliably
    for x in range(0, w, 3):
        q.append((x,0)); q.append((x,h-1))
    for y in range(0, h, 3):
        q.append((0,y)); q.append((w-1,y))

    threshold = 40.0
    removed = 0
    while q:
        x,y = q.popleft()
        idx = y*stride+x
        if seen[idx]: continue
        seen[idx] = 1
        if dist(pix[x,y]) > threshold:
            continue
        ap[x,y] = 0
        removed += 1
        if x>0: q.append((x-1,y))
        if x+1<w: q.append((x+1,y))
        if y>0: q.append((x,y-1))
        if y+1<h: q.append((x,y+1))

    ratio = removed / max(1, w*h)
    # If almost nothing or nearly everything vanished, use safer card mode.
    if ratio < 0.08 or ratio > 0.90:
        return False

    alpha = alpha.filter(ImageFilter.GaussianBlur(0.65))
    im.putalpha(alpha)
    bbox = im.getbbox()
    if not bbox:
        return False
    im = im.crop(bbox)
    im.thumbnail((790, 930), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (900, 1040), (0,0,0,0))
    x = (canvas.width-im.width)//2
    y = (canvas.height-im.height)//2
    # shadow made from the resulting alpha
    shadow = Image.new("RGBA", canvas.size, (0,0,0,0))
    sh = Image.new("RGBA", im.size, (0,0,0,150))
    sh.putalpha(im.getchannel("A").filter(ImageFilter.GaussianBlur(24)))
    shadow.alpha_composite(sh, (x+12, y+32))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(im, (x,y))
    canvas.save(target)
    return True


def product_card(source, target):
    src = Image.open(source).convert("RGB")
    src.thumbnail((760, 760), Image.Resampling.LANCZOS)
    card = Image.new("RGBA", (900, 1040), (0,0,0,0))
    shadow = Image.new("RGBA", card.size, (0,0,0,0))
    sd = ImageDraw.Draw(shadow, "RGBA")
    sd.rounded_rectangle((55,110,845,930), radius=78, fill=(0,0,0,135))
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    card.alpha_composite(shadow)
    d = ImageDraw.Draw(card, "RGBA")
    d.rounded_rectangle((55,85,845,905), radius=78, fill=(250,250,252,250), outline=(255,255,255,160), width=3)
    x = (900-src.width)//2
    y = 85 + (820-src.height)//2
    card.paste(src, (x,y))
    card.save(target)


def prepare_product(job_dir, work):
    source = None
    for ext in ("png","jpg","jpeg","webp"):
        p = job_dir / f"product.{ext}"
        if p.is_file():
            source = p; break
    if not source:
        return None
    target = work / "product.png"
    try:
        if try_border_cutout(source, target):
            print("[OK] Produto recortado pelo fundo da imagem.", flush=True)
            return target
    except Exception as exc:
        print(f"[!] Recorte automático não aplicado: {exc}", flush=True)
    product_card(source, target)
    print("[OK] Produto preservado em card premium.", flush=True)
    return target


def _gradient_fill(img, top, bottom):
    px=img.load(); w,h=img.size
    for y in range(h):
        q=y/max(1,h-1)
        c=tuple(int(top[i]*(1-q)+bottom[i]*q) for i in range(4))
        for x in range(w): px[x,y]=c


def stamp_illustrative(target):
    img=Image.open(target).convert('RGBA')
    d=ImageDraw.Draw(img,'RGBA')
    label='IMAGEM ILUSTRATIVA'
    f=font(24)
    box=d.textbbox((0,0),label,font=f)
    tw=box[2]-box[0]; th=box[3]-box[1]
    x=(img.width-tw)//2
    y=img.height-72
    d.rounded_rectangle((x-18,y-10,x+tw+18,y+th+10),radius=18,fill=(15,16,24,205))
    d.text((img.width//2,y+th//2),label,anchor='mm',font=f,fill=(255,255,255,235))
    img.save(target)


def create_missing_product(product, target):
    """Cria uma ilustração visual por categoria em vez de um cartão de erro."""
    name=str(product.get('nome_limpo') or 'Produto')
    low=name.lower()
    img=Image.new('RGBA',(900,1040),(0,0,0,0))
    glow=Image.new('RGBA',img.size,(0,0,0,0))
    gd=ImageDraw.Draw(glow,'RGBA')
    for r in range(330,30,-14):
        a=int(3+18*(1-r/330))
        gd.ellipse((450-r,500-r,450+r,500+r),fill=(115,92,255,a))
    glow=glow.filter(ImageFilter.GaussianBlur(28)); img.alpha_composite(glow)
    d=ImageDraw.Draw(img,'RGBA')

    if 'palmilha' in low or 'insole' in low:
        # Par de palmilhas gel estilizadas.
        def insole(cx,cy,angle=0):
            layer=Image.new('RGBA',(360,720),(0,0,0,0)); ld=ImageDraw.Draw(layer,'RGBA')
            ld.ellipse((88,30,270,260),fill=(83,191,255,245),outline=(225,249,255,245),width=8)
            ld.rounded_rectangle((105,155,255,655),radius=84,fill=(55,147,238,238),outline=(220,246,255,230),width=8)
            ld.ellipse((108,500,252,690),fill=(45,121,221,240),outline=(220,246,255,220),width=7)
            ld.ellipse((138,86,220,168),fill=(255,255,255,85))
            layer=layer.rotate(angle,resample=Image.Resampling.BICUBIC,expand=True)
            img.alpha_composite(layer,(int(cx-layer.width/2),int(cy-layer.height/2)))
        insole(340,525,-13); insole(565,500,13)
    elif any(k in low for k in ('fone','tws','earbud','bluetooth')):
        # Case + dois earbuds.
        d.rounded_rectangle((235,510,665,790),radius=115,fill=(245,247,252,248),outline=(255,255,255,255),width=8)
        d.rounded_rectangle((260,535,640,665),radius=70,fill=(225,229,239,255))
        for cx in (365,535):
            d.ellipse((cx-62,285,cx+62,415),fill=(249,250,253,255),outline=(205,210,225,255),width=6)
            d.rounded_rectangle((cx-27,390,cx+28,565),radius=24,fill=(245,247,252,255),outline=(205,210,225,255),width=5)
            d.ellipse((cx-22,323,cx+22,367),fill=(35,38,48,255))
    elif 'smartwatch' in low or 'relógio' in low or 'relogio' in low:
        d.rounded_rectangle((370,110,530,930),radius=70,fill=(38,42,55,245))
        d.rounded_rectangle((245,300,655,720),radius=95,fill=(15,17,24,255),outline=(220,225,240,230),width=8)
        d.rounded_rectangle((270,325,630,695),radius=78,fill=(40,75,135,255))
        d.ellipse((420,455,480,515),fill=(255,110,60,255))
    else:
        # Produto genérico premium: caixa/embalagem tridimensional estilizada.
        d.rounded_rectangle((205,250,695,805),radius=82,fill=(242,244,250,250),outline=(255,255,255,255),width=8)
        d.polygon([(205,365),(450,215),(695,365),(450,515)],fill=(221,226,242,255))
        d.polygon([(205,365),(450,515),(450,790),(205,650)],fill=(190,199,226,255))
        d.polygon([(695,365),(450,515),(450,790),(695,650)],fill=(155,169,214,255))

    # Nome discreto, apenas para contextualizar a ilustração procedural.
    lines='\n'.join(textwrap.wrap(name.upper(),width=22,break_long_words=False))
    f=fit_font(d,lines,690,42,28)
    d.multiline_text((450,900),lines,anchor='mm',align='center',font=f,fill=(245,246,250,235),spacing=8,stroke_width=3,stroke_fill=(15,16,24,180))
    img.save(target)
    stamp_illustrative(target)

def make_card(path, text, size, bg, fg, radius=38, accent=None, font_size=56, padding=30):
    w,h = size
    img = Image.new("RGBA", size, (0,0,0,0))
    shadow = Image.new("RGBA", size, (0,0,0,0))
    sd = ImageDraw.Draw(shadow, "RGBA")
    sd.rounded_rectangle((15,20,w-15,h-10), radius=radius, fill=(0,0,0,120))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    img.alpha_composite(shadow)
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle((8,8,w-8,h-18), radius=radius, fill=bg)
    if accent:
        d.rounded_rectangle((25,22,w-25,34), radius=8, fill=accent)
    wrapped = "\n".join(textwrap.wrap(str(text).upper(), width=max(12, int((w-padding*2)/(font_size*0.58))), break_long_words=False))
    f = fit_font(d, wrapped, w-padding*2, font_size, 30)
    d.multiline_text((w//2,h//2+3), wrapped, anchor="mm", align="center", font=f, fill=fg, spacing=7)
    img.save(path)


def create_glow_assets(work):
    # Soft hero flare behind the product.
    flare = Image.new("RGBA", (760,760), (0,0,0,0))
    fd = ImageDraw.Draw(flare, "RGBA")
    cx = cy = 380
    for r in range(330, 8, -10):
        strength = (1.0 - r / 330.0)
        a = int(2 + 15 * strength)
        fd.ellipse((cx-r, cy-r, cx+r, cy+r), fill=(255,132,74,a))
    flare = flare.filter(ImageFilter.GaussianBlur(34))
    flare.save(work/'hero_flare.png')

    # Diagonal light sweep used as a TV-commercial "shine".
    shine = Image.new("RGBA", (420,1920), (0,0,0,0))
    sd = ImageDraw.Draw(shine, "RGBA")
    for x in range(420):
        d = abs(x-210)/210
        alpha = int(max(0, 92*(1-d)**2))
        sd.polygon(
            [(x-120,0),(x+30,0),(x+330,1920),(x+180,1920)],
            fill=(255,255,255,alpha)
        )
    shine = shine.filter(ImageFilter.GaussianBlur(18))
    shine.save(work/'shine.png')


def make_visual_assets(work, product):
    points = list(product.get("pontos_visuais") or [])[:3]
    while len(points) < 3:
        points.append("CONFIRA")

    # Hook: cleaner and more "campaign line" than a UI card.
    make_card(
        work/'hook.png',
        product.get('hook_visual') or 'UM ACHADO QUE MERECE ATENÇÃO',
        (940,250),
        (12,14,24,225),
        (255,255,255,255),
        radius=42,
        accent=(255,104,55,255),
        font_size=50,
    )

    # Benefits are smaller, premium "supers".
    make_card(work/'badge1.png', points[0], (390,100), (255,104,55,245), (255,255,255,255), radius=30, font_size=36)
    make_card(work/'badge2.png', points[1], (390,100), (248,248,251,245), (20,21,28,255), radius=30, font_size=36)
    make_card(work/'badge3.png', points[2], (390,100), (28,30,42,244), (255,255,255,255), radius=30, font_size=36)

    # Two-line TV style closing card.
    cta = Image.new("RGBA", (930,250), (0,0,0,0))
    shadow = Image.new("RGBA", cta.size, (0,0,0,0))
    sd = ImageDraw.Draw(shadow, "RGBA")
    sd.rounded_rectangle((20,30,910,225), radius=50, fill=(0,0,0,125))
    shadow = shadow.filter(ImageFilter.GaussianBlur(20))
    cta.alpha_composite(shadow)
    d = ImageDraw.Draw(cta, "RGBA")
    d.rounded_rectangle((10,15,920,215), radius=50, fill=(255,92,45,248))
    d.text((465,86), "CONFIRA NA SHOPEE", anchor="mm", font=font(58), fill=(255,255,255,255))
    d.text(
        (465,158),
        "VEJA PREÇO • FRETE • AVALIAÇÕES",
        anchor="mm",
        font=font(28),
        fill=(255,245,240,245),
    )
    cta.save(work/'cta.png')
    create_glow_assets(work)

def srt_seconds(value):
    m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)", value.strip())
    if not m: return 0.0
    hh,mm,ss,ms = map(int,m.groups())
    return hh*3600+mm*60+ss+ms/1000


def parse_srt(path):
    text = path.read_text(encoding='utf-8', errors='replace').replace('\r\n','\n')
    cues=[]
    blocks=re.split(r"\n\s*\n", text.strip())
    for block in blocks:
        lines=[x.strip() for x in block.splitlines() if x.strip()]
        time_line=next((x for x in lines if '-->' in x), None)
        if not time_line: continue
        idx=lines.index(time_line)
        body=' '.join(lines[idx+1:])
        body=re.sub(r'<[^>]+>','',body)
        body=html.unescape(body).strip()
        if not body: continue
        a,b=[x.strip() for x in time_line.split('-->',1)]
        cues.append((srt_seconds(a),srt_seconds(b),body))
    return cues


def ass_time(sec):
    sec=max(0.0,sec)
    h=int(sec//3600); sec-=h*3600
    m=int(sec//60); sec-=m*60
    s=int(sec); cs=int(round((sec-s)*100))
    if cs>=100: s+=1; cs-=100
    if s>=60: m+=1; s-=60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_escape(text):
    return text.replace('\\','／').replace('{','(').replace('}',')').replace('\n',' ')


def chunk_words(words):
    chunks=[]
    i=0
    while i<len(words):
        remain=len(words)-i
        n=4 if remain>=4 else remain
        if n>=4 and sum(len(x) for x in words[i:i+n])>27:
            n=3
        if n>=3 and sum(len(x) for x in words[i:i+n])>23:
            n=2
        chunks.append(words[i:i+n])
        i+=n
    return chunks


def make_tiktok_ass(srt, ass_path):
    cues=parse_srt(srt)
    header="""[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nScaledBorderAndShadow: yes\nWrapStyle: 2\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Pop,DejaVu Sans,68,&H00FFFFFF,&H005ED6FF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,8,3,2,48,48,300,1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"""
    events=[]
    toggle=0

    for start,end,text in cues:
        words=[w for w in re.split(r'\s+',text.strip()) if w]
        if not words:
            continue

        chunks=chunk_words(words)
        dur=max(0.30,end-start)
        total_words=sum(len(c) for c in chunks)
        cursor=start

        for ci,c in enumerate(chunks):
            share=dur*(len(c)/total_words)
            cstart=cursor
            cend=end if ci==len(chunks)-1 else min(end,cursor+share)

            if cend-cstart<0.30:
                cend=min(end,cstart+0.30)

            cursor=cend
            safe=[ass_escape(w.upper()) for w in c]

            # Highlight one "power word". Longer words are preferred over articles/prepositions.
            candidates=[
                (idx, word) for idx,word in enumerate(safe)
                if len(re.sub(r'[^A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9]','',word)) >= 5
            ]
            hi = candidates[-1][0] if candidates else len(safe)-1

            rendered=[]
            for idx,word in enumerate(safe):
                if idx==hi:
                    rendered.append(
                        r'{\c&H005ED6FF&\fscx110\fscy110}'
                        + word +
                        r'{\c&H00FFFFFF&\fscx100\fscy100}'
                    )
                else:
                    rendered.append(word)

            content=' '.join(rendered)

            # Small alternating vertical position keeps the captions alive without looking chaotic.
            ypos = 1505 if toggle % 2 == 0 else 1540
            toggle += 1

            fx=(
                rf'{{\an2\pos(540,{ypos})'
                r'\fscx82\fscy82\alpha&H40&'
                r'\t(0,90,\fscx108\fscy108\alpha&H00&)'
                r'\t(90,180,\fscx100\fscy100)'
                r'\fad(20,45)}'
            )

            events.append(
                f"Dialogue: 0,{ass_time(cstart)},{ass_time(cend)},Pop,,0,0,0,,{fx}{content}"
            )

    ass_path.write_text(
        header+'\n'.join(events)+'\n',
        encoding='utf-8'
    )


def create_commercial_music(path, duration_s):
    """
    Original procedural music bed.
    No external song/audio is downloaded, so every render can stay self-contained.
    """
    sr = 22050
    total = int((duration_s + 0.35) * sr)
    data = array('h')

    # Warm pop-commercial progression: C - Am - F - G.
    chords = [
        (130.81, 164.81, 196.00),
        (110.00, 130.81, 164.81),
        (87.31, 110.00, 130.81),
        (98.00, 123.47, 146.83),
    ]
    beat_len = 60.0 / 102.0

    for i in range(total):
        t = i / sr
        chord_index = int(t / 4.0) % len(chords)
        freqs = chords[chord_index]

        # Pad with a tiny detune for width/energy.
        pad = 0.0
        for f in freqs:
            pad += math.sin(2*math.pi*f*t)
            pad += 0.35*math.sin(2*math.pi*(f*2.0)*t + 0.35)
        pad /= (len(freqs)*1.35)

        # Gentle pulse / kick for commercial rhythm.
        phase = t % beat_len
        kick = 0.0
        if phase < 0.16:
            kick = math.sin(2*math.pi*(72 - 110*phase)*phase) * math.exp(-phase*22)

        # Small shimmer on off-beats.
        off = (t + beat_len/2) % beat_len
        shimmer = 0.0
        if off < 0.08:
            shimmer = math.sin(2*math.pi*880*t) * math.exp(-off*38)

        # Intro impact.
        impact = 0.0
        if t < 0.55:
            impact = math.sin(2*math.pi*64*t) * math.exp(-t*8.5)

        fade_in = min(1.0, t/0.55)
        fade_out = min(1.0, max(0.0, duration_s-t)/1.2)
        env = fade_in * fade_out

        sample = env*(0.23*pad + 0.17*kick + 0.035*shimmer) + 0.24*impact
        sample = max(-0.95, min(0.95, sample))
        v = int(sample * 32767)
        data.append(v)
        data.append(v)

    with wave.open(str(path),'wb') as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sr)
        wav.writeframes(data.tobytes())



def make_banner(product, background, product_png, target):
    bg = Image.open(background).convert('RGBA').resize((W, H), Image.Resampling.LANCZOS)
    overlay = Image.new('RGBA', (W, H), (0,0,0,0))
    od = ImageDraw.Draw(overlay, 'RGBA')
    od.rounded_rectangle((70, 90, 1010, 340), radius=52, fill=(10, 12, 20, 165))
    od.rounded_rectangle((80, 1460, 1000, 1780), radius=46, fill=(8, 10, 16, 175))
    bg = Image.alpha_composite(bg, overlay)

    prod = Image.open(product_png).convert('RGBA')
    prod.thumbnail((900, 1020), Image.Resampling.LANCZOS)
    px = (W - prod.width) // 2
    py = 360
    shadow = Image.new('RGBA', (W, H), (0,0,0,0))
    sh = Image.new('RGBA', prod.size, (0,0,0,0))
    shd = ImageDraw.Draw(sh, 'RGBA')
    shd.rounded_rectangle((18, 26, prod.width-6, prod.height-2), radius=64, fill=(0,0,0,130))
    sh = sh.filter(ImageFilter.GaussianBlur(30))
    shadow.alpha_composite(sh, (px+12, py+28))
    bg = Image.alpha_composite(bg, shadow)
    bg.alpha_composite(prod, (px, py))

    d = ImageDraw.Draw(bg, 'RGBA')
    hook = str(product.get('hook_visual') or 'ACHADO DA SHOPEE').upper()
    name = str(product.get('nome_limpo') or 'Produto').upper()
    name = '\n'.join(textwrap.wrap(name, width=26, break_long_words=False))
    pts = list(product.get('pontos_visuais') or [])[:3]
    while len(pts) < 3:
        pts.append('CONFIRA')

    d.text((540, 175), hook, anchor='mm', font=font(56), fill=(255,255,255,255), stroke_width=3, stroke_fill=(0,0,0,190))
    d.multiline_text((540, 1540), name, anchor='mm', align='center', font=fit_font(d, name, 850, 52, 28), fill=(255,255,255,255), spacing=10, stroke_width=3, stroke_fill=(0,0,0,190))

    chip_y = 1670
    xs = [210, 540, 870]
    fills = [(255,104,55,245),(240,242,248,245),(28,30,42,245)]
    fgs = [(255,255,255,255),(20,21,28,255),(255,255,255,255)]
    for x, pt, fill, fg in zip(xs, pts, fills, fgs):
        box = (x-135, chip_y-34, x+135, chip_y+34)
        d.rounded_rectangle(box, radius=26, fill=fill)
        d.text((x, chip_y), str(pt).upper(), anchor='mm', font=font(28), fill=fg)

    d.rounded_rectangle((140, 1795, 940, 1885), radius=32, fill=(255,92,45,248))
    d.text((540, 1840), 'CONFIRA NA SHOPEE', anchor='mm', font=font(42), fill=(255,255,255,255))
    bg.convert('RGB').save(target, quality=94)

def render(product, background, product_png, audio, captions_ass, work):
    total=audio_duration(audio)
    end_cta=max(7.0,total-4.8)

    bg_local=work/'background.jpg'
    Image.open(background).convert('RGB').resize((W,H),Image.Resampling.LANCZOS).save(bg_local,quality=94)
    make_visual_assets(work,product)

    music=work/'commercial_music.wav'
    create_commercial_music(music,total)

    # Visual direction:
    # 1) product enters with a deliberate hero reveal;
    # 2) subtle flare behind it;
    # 3) three light sweeps punctuate the commercial;
    # 4) benefit supers enter on alternating sides;
    # 5) strong end card.
    fc=f"""[0:v]scale=1080:1920,zoompan=z='min(zoom+0.00024,1.075)':x='iw/2-(iw/zoom/2)+11*sin(on/37)':y='ih/2-(ih/zoom/2)+8*cos(on/46)':d=1:s=1080x1920:fps=30,eq=brightness=-0.045:saturation=1.13,vignette=PI/5[bg0];
[8:v]format=rgba,colorchannelmixer=aa=0.72[flare];
[bg0][flare]overlay=x='(W-w)/2+5*sin(t*0.8)':y='430+5*cos(t*0.75)':eval=frame[bg];
[1:v]format=rgba,scale=860:-1,fade=t=in:st=0:d=0.30:alpha=1[p];
[bg][p]overlay=x='(W-w)/2+12*sin(t*1.20)':y='if(lt(t,0.58),760-(t/0.58)*340,420+17*sin(t*1.05))':eval=frame[v1];

[7:v]format=rgba[shine];[shine]split=3[s1][s2][s3];
[v1][s1]overlay=x='-w+(t-0.75)/0.80*(W+w)':y=0:enable='between(t,0.75,1.55)':eval=frame[v1a];
[v1a][s2]overlay=x='-w+(t-8.0)/0.85*(W+w)':y=0:enable='between(t,8.0,8.85)':eval=frame[v1b];
[v1b][s3]overlay=x='-w+(t-15.0)/0.85*(W+w)':y=0:enable='between(t,15.0,15.85)':eval=frame[v1c];

[2:v]format=rgba[hook];[v1c][hook]overlay=x='(W-w)/2':y='if(lt(t,0.38),-h+(t/0.38)*(105+h),105)':enable='between(t,0,4.3)':eval=frame[v2];
[3:v]format=rgba[b1];[v2][b1]overlay=x='if(lt(t,6.0),-w+(t-5.55)/0.45*(92+w),92)':y=1170:enable='between(t,5.55,9.4)':eval=frame[v3];
[4:v]format=rgba[b2];[v3][b2]overlay=x='if(lt(t,9.15),W-(t-8.70)/0.45*(W-598),598)':y=1290:enable='between(t,8.70,12.6)':eval=frame[v4];
[5:v]format=rgba[b3];[v4][b3]overlay=x='if(lt(t,12.25),-w+(t-11.80)/0.45*(92+w),92)':y=370:enable='between(t,11.80,15.8)':eval=frame[v5];
[6:v]format=rgba[cta];[v5][cta]overlay=x='(W-w)/2':y='if(lt(t,{end_cta+0.38:.3f}),-h+(t-{end_cta:.3f})/0.38*(110+h),110)':enable='gte(t,{end_cta:.3f})':eval=frame[v6];
[v6]ass=captions.ass[v];

[9:a]volume=1.12[narr];
[10:a]volume=0.16[musicbed];
[narr][musicbed]amix=inputs=2:duration=first:dropout_transition=1.5,alimiter=limit=0.94[aout]
""".replace('\n','')

    output=work/'anuncio_final.mp4'
    cmd=['ffmpeg','-y']

    for img in [
        bg_local,
        product_png,
        work/'hook.png',
        work/'badge1.png',
        work/'badge2.png',
        work/'badge3.png',
        work/'cta.png',
        work/'shine.png',
        work/'hero_flare.png',
    ]:
        cmd += ['-loop','1','-framerate','30','-i',str(img)]

    cmd += [
        '-i',str(audio),
        '-i',str(music),
        '-filter_complex',fc,
        '-map','[v]',
        '-map','[aout]',
        '-t',f'{total:.3f}',
        '-r','30',
        '-c:v','libx264',
        '-preset','veryfast',
        '-crf','21',
        '-pix_fmt','yuv420p',
        '-c:a','aac',
        '-b:a','160k',
        '-movflags','+faststart',
        str(output),
    ]

    run(cmd,cwd=work)
    return output

def main():
    if len(sys.argv)!=3:
        raise SystemExit('Uso: render_v6.py JOB_DIR OUTPUT_DIR')
    job_dir=Path(sys.argv[1]).resolve(); output_dir=Path(sys.argv[2]).resolve()
    output_dir.mkdir(parents=True,exist_ok=True)
    work=output_dir/'_work'; work.mkdir(parents=True,exist_ok=True)
    product=json.loads((job_dir/'produto.json').read_text(encoding='utf-8'))
    roteiro=work/'roteiro.txt'; roteiro.write_text(product['roteiro_comercial'],encoding='utf-8')
    audio=work/'narracao.mp3'; srt=work/'subtitles.srt'
    voice = product.get('voice_id') or VOICE
    run(['edge-tts','--file',str(roteiro),'--voice',voice,'--rate=+2%','--write-media',str(audio),'--write-subtitles',str(srt)])
    ass=work/'captions.ass'; make_tiktok_ass(srt,ass)
    background=job_dir/'background.jpg'
    if not background.is_file():
        background=work/'procedural.jpg'; create_procedural_background(background)
    product_png=prepare_product(job_dir,work)
    if not product_png:
        product_png=work/'product.png'; create_missing_product(product,product_png)
    elif product.get('imagem_ilustrativa'):
        stamp_illustrative(product_png)
    banner = work/'banner_promocional.png'
    make_banner(product, background, product_png, banner)
    final=render(product,background,product_png,audio,ass,work)
    shutil.copy2(final,output_dir/'anuncio_final.mp4')
    shutil.copy2(banner,output_dir/'banner_promocional.png')
    shutil.copy2(job_dir/'produto.json',output_dir/'produto.json')
    shutil.copy2(ass,output_dir/'legendas_tiktok.ass')
    (output_dir/'copie_e_cole_na_live.txt').write_text(
        f"🔥 ACHADO NA SHOPEE\n\n{product.get('nome_limpo','Produto')}\n\n🛒 Confira preço, avaliações, cupons, frete e condições atuais no anúncio.\n\n"+' '.join(product.get('tags_engajamento') or [])+'\n',
        encoding='utf-8')
    print('[OK] Render V6 comercial concluído.',flush=True)

if __name__=='__main__':
    main()
