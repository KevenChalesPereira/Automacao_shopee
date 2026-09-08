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

VOICE = "pt-BR-AntonioNeural"
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


def create_procedural_background(path, product=None):
    random.seed(41)
    theme = str((product or {}).get('visual_theme') or 'marketplace').lower()

    palettes = {
        'footwear': ((18,22,18), (76,52,34), (210,137,58)),
        'wellness': ((226,244,221), (164,215,166), (242,220,167)),
        'tech': ((7,12,28), (19,70,130), (126,55,201)),
        'marketplace': ((16,32,66), (37,98,164), (255,97,55)),
    }
    top, mid, accent = palettes.get(theme, palettes['marketplace'])

    img = Image.new('RGB', (W,H), top)
    px = img.load()
    for y in range(H):
        q = y / max(1,H-1)
        if q < .58:
            z = q/.58
            c = tuple(int(top[i]*(1-z)+mid[i]*z) for i in range(3))
        else:
            z = (q-.58)/.42
            c = tuple(int(mid[i]*(1-z)+accent[i]*z*.55+top[i]*z*.45) for i in range(3))
        for x in range(W):
            px[x,y] = c

    glows = Image.new('RGBA', (W,H), (0,0,0,0))
    gd = ImageDraw.Draw(glows, 'RGBA')
    if theme == 'wellness':
        gd.ellipse((-220,-160,560,650), fill=(255,255,220,120))
        gd.ellipse((570,120,1320,940), fill=(110,210,150,85))
        gd.ellipse((120,900,1000,1800), fill=(255,221,150,70))
    elif theme == 'footwear':
        gd.ellipse((-300,-220,650,780), fill=(220,155,72,85))
        gd.ellipse((500,260,1450,1260), fill=(70,92,55,95))
        gd.ellipse((80,1180,1040,2050), fill=(210,88,42,70))
    else:
        gd.ellipse((-420,-300,650,800), fill=(38,135,255,125))
        gd.ellipse((520,280,1500,1370), fill=(163,62,255,100))
        gd.ellipse((160,1120,1040,2030), fill=(255,89,48,75))
    glows = glows.filter(ImageFilter.GaussianBlur(150))
    img = Image.alpha_composite(img.convert('RGBA'), glows)

    deco = Image.new('RGBA', (W,H), (0,0,0,0))
    dd = ImageDraw.Draw(deco, 'RGBA')
    for _ in range(58):
        x = random.randrange(35, W-35); y = random.randrange(170, H-160)
        rr = random.choice([1,1,2,2,3]); a = random.randrange(25,95)
        dd.ellipse((x-rr,y-rr,x+rr,y+rr), fill=(255,255,255,a))
    dd.ellipse((130,1180,950,1455), fill=(0,0,0,80))
    dd.ellipse((215,1200,865,1405), outline=(255,255,255,72), width=4)
    if theme == 'footwear':
        dd.rectangle((0,1430,W,H), fill=(10,12,11,45))
        for x in range(0,W,120):
            dd.line((x,1480,x+280,H), fill=(255,255,255,12), width=2)
    img = Image.alpha_composite(img, deco)
    img.convert('RGB').save(path, quality=94)

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
        # Validação simples: evita quebrar o workflow caso HTML tenha sido salvo com extensão .jpg.
        with Image.open(source) as probe:
            probe.verify()
    except Exception as exc:
        print(f"[!] Arquivo de produto não é uma imagem válida: {exc}. Usarei fallback.", flush=True)
        return None
    try:
        if try_border_cutout(source, target):
            print("[OK] Produto recortado pelo fundo da imagem.", flush=True)
            return target
    except Exception as exc:
        print(f"[!] Recorte automático não aplicado: {exc}", flush=True)
    try:
        product_card(source, target)
        print("[OK] Produto preservado em card premium.", flush=True)
        return target
    except Exception as exc:
        print(f"[!] Não consegui preparar a imagem do produto: {exc}. Usarei fallback.", flush=True)
        return None


def prepare_presenter(job_dir, work):
    source = None
    for ext in ('png','jpg','jpeg','webp'):
        p = job_dir / f'presenter.{ext}'
        if p.is_file():
            source = p
            break
    target = work / 'presenter.png'
    if not source:
        Image.new('RGBA', (520, 900), (0,0,0,0)).save(target)
        return target
    try:
        if try_border_cutout(source, target):
            img = Image.open(target).convert('RGBA')
        else:
            img = Image.open(source).convert('RGBA')
    except Exception:
        img = Image.open(source).convert('RGBA')
    img.thumbnail((520, 920), Image.Resampling.LANCZOS)
    canvas = Image.new('RGBA', (520, 920), (0,0,0,0))
    x = (canvas.width - img.width)//2
    y = canvas.height - img.height
    shadow = Image.new('RGBA', canvas.size, (0,0,0,0))
    sh = Image.new('RGBA', img.size, (0,0,0,120))
    if 'A' in img.getbands():
        sh.putalpha(img.getchannel('A').filter(ImageFilter.GaussianBlur(18)))
    shadow.alpha_composite(sh, (x+8, y+16))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(img, (x,y))
    canvas.save(target)
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

    if any(k in low for k in ('coturno','bota militar','bota tática','bota tatica','bota','tático','tatico')):
        # Coturno estilizado para fallback procedural.
        body = Image.new('RGBA',(520,760),(0,0,0,0)); bd=ImageDraw.Draw(body,'RGBA')
        bd.rounded_rectangle((120,85,320,600),radius=55,fill=(25,26,31,255),outline=(82,84,95,255),width=4)
        bd.rounded_rectangle((128,430,388,645),radius=72,fill=(18,18,22,255),outline=(95,98,110,220),width=4)
        bd.polygon([(120,500),(360,500),(395,635),(110,635)],fill=(20,21,26,255))
        for y in range(160,450,48):
            bd.ellipse((210,y,228,y+18),fill=(70,72,80,255)); bd.ellipse((257,y,275,y+18),fill=(70,72,80,255))
            bd.line((228,y+9,257,y+9),fill=(108,110,118,255),width=4)
        sole = [(120,605),(380,605),(420,648),(388,690),(160,708),(105,668)]
        bd.polygon(sole,fill=(35,36,42,255))
        body = body.rotate(-8,resample=Image.Resampling.BICUBIC,expand=True)
        img.alpha_composite(body,(165,190))
    elif 'palmilha' in low or 'insole' in low:
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

    hook_text = str(product.get('hook_visual') or 'OLHA ISSO').upper()

    # V21: hook pequeno, sem ocupar o topo inteiro.
    hook = Image.new('RGBA', (820, 132), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hook, 'RGBA')
    hd.rounded_rectangle((6, 6, 814, 118), radius=34, fill=(8, 10, 17, 212), outline=(255,255,255,24), width=2)
    wrap = '\n'.join(textwrap.wrap(hook_text, width=30, break_long_words=False))
    f = fit_font(hd, wrap, 730, 42, 26)
    hd.multiline_text((410, 61), wrap, anchor='mm', align='center', font=f, fill=(255,255,255,255), spacing=2)
    hook.save(work / 'hook.png')

    # Mantém input compatível com o filtro, mas sem card branco gigante.
    board = Image.new('RGBA', (8, 8), (0, 0, 0, 0))
    board.save(work / 'board.png')

    # Features em chips discretos, um por vez.
    for idx, pt in enumerate(points[:3], start=1):
        pill = Image.new('RGBA', (650, 92), (0,0,0,0))
        pd = ImageDraw.Draw(pill, 'RGBA')
        pd.rounded_rectangle((4,4,646,82), radius=28, fill=(7,10,17,196), outline=(255,255,255,25), width=2)
        pd.ellipse((20,22,58,60), fill=(255,94,45,245))
        pd.text((39,41), str(idx), anchor='mm', font=font(21), fill=(255,255,255,255))
        pf = _fit_single_line(pd, str(pt).upper(), 530, 34, 21)
        pd.text((78,43), str(pt).upper(), anchor='lm', font=pf, fill=(255,255,255,245))
        pill.save(work / f'pill{idx}.png')

    # CTA final curto; sem referência fixa à Shopee porque o destino agora pode ser TikTok Shop/link externo.
    cta = Image.new('RGBA', (780, 128), (0, 0, 0, 0))
    cd = ImageDraw.Draw(cta, 'RGBA')
    cd.rounded_rectangle((6,6,774,112), radius=36, fill=(255, 92, 45, 248))
    cta_main = str(product.get('cta_main') or 'CONFIRA O PRODUTO').upper()
    cf = _fit_single_line(cd, cta_main, 660, 44, 28)
    cd.text((390, 59), cta_main, anchor='mm', font=cf, fill=(255,255,255,255))
    cta.save(work / 'cta.png')

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
    header="""[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nScaledBorderAndShadow: yes\nWrapStyle: 2\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Pop,DejaVu Sans,64,&H00FFFFFF,&H00335CFF,&H00000000,&H8A000000,-1,0,0,0,100,100,0,0,1,9,3,2,42,42,280,1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"""
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
                        r'{\c&H00335CFF&\fscx114\fscy114}'
                        + word +
                        r'{\c&H00FFFFFF&\fscx100\fscy100}'
                    )
                else:
                    rendered.append(word)

            content=' '.join(rendered)

            # Small alternating vertical position keeps the captions alive without looking chaotic.
            ypos = 1220 if toggle % 2 == 0 else 1260
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



def _fit_single_line(draw, text, max_width, start=64, minimum=28):
    size = start
    while size >= minimum:
        f = font(size)
        box = draw.textbbox((0,0), text, font=f)
        if box[2]-box[0] <= max_width:
            return f
        size -= 2
    return font(minimum)


def _cover_background(background, size):
    bg = Image.open(background).convert('RGB')
    tw,th = size
    scale = max(tw/bg.width, th/bg.height)
    nw,nh = int(bg.width*scale), int(bg.height*scale)
    bg = bg.resize((nw,nh), Image.Resampling.LANCZOS)
    x=(nw-tw)//2; y=(nh-th)//2
    return bg.crop((x,y,x+tw,y+th)).convert('RGBA')


def _hero_product(product_png, max_size):
    prod = Image.open(product_png).convert('RGBA')
    prod.thumbnail(max_size, Image.Resampling.LANCZOS)
    return prod


def _paste_product_with_shadow(canvas, prod, x, y, blur=28):
    shadow = Image.new('RGBA', canvas.size, (0,0,0,0))
    alpha = prod.getchannel('A').filter(ImageFilter.GaussianBlur(blur))
    sh = Image.new('RGBA', prod.size, (0,0,0,150)); sh.putalpha(alpha)
    shadow.alpha_composite(sh, (x+12,y+28))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(prod, (x,y))


def make_marketing_banners(product, background, product_png, output_dir):
    title = str(product.get('titulo_curto') or product.get('nome_limpo') or 'ACHADO SHOPEE').upper()
    hook = str(product.get('hook_visual') or 'OLHA ESSE ACHADO NA SHOPEE').upper()
    pts = list(product.get('pontos_visuais') or [])[:3]
    while len(pts) < 3:
        pts.append('CONFIRA')

    story = _cover_background(background, (1080, 1920))
    d = ImageDraw.Draw(story, 'RGBA')
    d.rounded_rectangle((70, 70, 1010, 290), radius=44, fill=(7, 10, 20, 225))
    d.polygon([(470, 290), (610, 290), (540, 334)], fill=(7, 10, 20, 225))
    hw = '\n'.join(textwrap.wrap(hook, width=27, break_long_words=False))
    hf = fit_font(d, hw, 840, 58, 32)
    d.multiline_text((540, 162), hw, anchor='mm', align='center', font=hf, fill=(255,255,255,255), spacing=4)
    prod = _hero_product(product_png, (920, 980))
    px = (1080 - prod.width) // 2
    py = 320
    _paste_product_with_shadow(story, prod, px, py, 30)
    sticker = Image.new('RGBA', (240, 240), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sticker, 'RGBA')
    cx = cy = 120
    burst = []
    for i in range(18):
        ang = math.pi * 2 * i / 18.0
        rr = 102 if i % 2 == 0 else 72
        burst.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    sd.polygon(burst, fill=(255, 99, 50, 248), outline=(255, 245, 235, 255))
    badge_text = str(product.get('badge_text') or 'ACHADO DO DIA').upper()
    badge_lines = badge_text.split()
    if len(badge_lines) >= 3:
        top_line = ' '.join(badge_lines[:2])
        bottom_line = ' '.join(badge_lines[2:])
    elif len(badge_lines) == 2:
        top_line, bottom_line = badge_lines
    else:
        top_line, bottom_line = 'TOP', badge_text
    sd.text((120, 110), top_line, anchor='mm', font=font(23), fill=(255,255,255,255))
    sd.text((120, 145), bottom_line, anchor='mm', font=font(27), fill=(255,245,235,255))
    sticker = sticker.rotate(-12, resample=Image.Resampling.BICUBIC, expand=True)
    story.alpha_composite(sticker, (95, 332))
    panel_y = 1515
    d = ImageDraw.Draw(story, 'RGBA')
    d.rounded_rectangle((70, panel_y, 1010, 1858), radius=56, fill=(247,244,239,245))
    tf = _fit_single_line(d, title, 800, 56, 30)
    d.text((540, panel_y + 82), title, anchor='mm', font=tf, fill=(20,22,28,255))
    y = panel_y + 142
    for pt in pts:
        d.ellipse((140, y - 14, 176, y + 22), fill=(39,146,83,255))
        d.text((158, y + 4), '✓', anchor='mm', font=font(25), fill=(255,255,255,255))
        pf = _fit_single_line(d, str(pt).upper(), 670, 39, 24)
        d.text((210, y + 4), str(pt).upper(), anchor='lm', font=pf, fill=(30,32,38,255))
        y += 62
    d.rounded_rectangle((160, 1750, 920, 1842), radius=36, fill=(255,92,45,255))
    cta_main = str(product.get('cta_main') or 'CONFIRA NA SHOPEE').upper()
    d.text((540, 1796), cta_main, anchor='mm', font=font(42), fill=(255,255,255,255))
    story_path = output_dir / 'banner_story.png'
    story.convert('RGB').save(story_path, quality=94)

    feed = _cover_background(background, (1080, 1350))
    d = ImageDraw.Draw(feed, 'RGBA')
    d.rounded_rectangle((60, 56, 1020, 220), radius=40, fill=(7, 10, 20, 220))
    hw = '\n'.join(textwrap.wrap(hook, width=28, break_long_words=False))
    hf = fit_font(d, hw, 860, 48, 28)
    d.multiline_text((540, 132), hw, anchor='mm', align='center', font=hf, fill=(255,255,255,255), spacing=2)
    prod = _hero_product(product_png, (780, 600))
    px = (1080 - prod.width) // 2
    py = 262
    _paste_product_with_shadow(feed, prod, px, py, 24)
    d.rounded_rectangle((70, 890, 1010, 1280), radius=50, fill=(247,244,239,245))
    tf = _fit_single_line(d, title, 800, 54, 28)
    d.text((540, 960), title, anchor='mm', font=tf, fill=(20,22,28,255))
    y = 1035
    for pt in pts:
        d.ellipse((130, y - 11, 166, y + 25), fill=(39,146,83,255))
        d.text((148, y + 6), '✓', anchor='mm', font=font(24), fill='white')
        d.text((198, y + 6), str(pt).upper(), anchor='lm', font=_fit_single_line(d, str(pt).upper(), 660, 36, 22), fill=(30,32,36,255))
        y += 68
    d.rounded_rectangle((225, 1200, 855, 1274), radius=28, fill=(255,92,45,255))
    cta_small = str(product.get('cta_small') or 'TOQUE E VEJA').upper()
    d.text((540, 1238), cta_small, anchor='mm', font=font(34), fill='white')
    feed_path = output_dir / 'banner_feed.png'
    feed.convert('RGB').save(feed_path, quality=94)

    cover = _cover_background(background, (1080, 1920))
    d = ImageDraw.Draw(cover, 'RGBA')
    d.rounded_rectangle((75, 88, 1005, 298), radius=44, fill=(7, 10, 20, 220))
    ch = '\n'.join(textwrap.wrap(hook, width=27, break_long_words=False))
    cf = fit_font(d, ch, 830, 58, 34)
    d.multiline_text((540, 178), ch, anchor='mm', align='center', font=cf, fill='white', spacing=3)
    prod = _hero_product(product_png, (920, 1040))
    px = (1080 - prod.width) // 2
    py = 350
    _paste_product_with_shadow(cover, prod, px, py, 28)
    d.rounded_rectangle((120, 1618, 960, 1762), radius=46, fill=(255,92,45,252))
    badge_text = str(product.get('badge_text') or 'ACHADO DO DIA').upper()
    d.text((540, 1692), badge_text, anchor='mm', font=font(48), fill='white')
    cover_path = output_dir / 'capa_video.png'
    cover.convert('RGB').save(cover_path, quality=94)
    return story_path, feed_path, cover_path

def _job_media_files(job_dir, prefix):
    files = []
    for pattern in (f"{prefix}*.mp4", f"{prefix}*.mov", f"{prefix}*.webm", f"{prefix}*.m4v", f"{prefix}*.jpg", f"{prefix}*.jpeg", f"{prefix}*.png", f"{prefix}*.webp"):
        files.extend(job_dir.glob(pattern))
    return sorted({p.resolve() for p in files if p.is_file()})


def create_motion_background(source, duration, output_path):
    run([
        'ffmpeg','-y','-loop','1','-t',f'{duration:.3f}','-i',str(source),
        '-vf',
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,zoompan=z='min(zoom+0.00028,1.085)':x='iw/2-(iw/zoom/2)+9*sin(on/42)':y='ih/2-(ih/zoom/2)+7*cos(on/53)':d=1:s=1080x1920:fps=30,setsar=1",
        '-an','-r','30','-c:v','libx264','-preset','veryfast','-crf','24','-pix_fmt','yuv420p',str(output_path)
    ])
    return output_path


def create_image_segment(source, duration, output_path):
    run([
        'ffmpeg','-y','-loop','1','-t',f'{duration:.3f}','-i',str(source),
        '-vf',
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,zoompan=z='min(zoom+0.00055,1.10)':x='iw/2-(iw/zoom/2)+8*sin(on/37)':y='ih/2-(ih/zoom/2)+6*cos(on/44)':d=1:s=1080x1920:fps=30,setsar=1,eq=saturation=1.08:contrast=1.02",
        '-an','-r','30','-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p',str(output_path)
    ])
    return output_path


def create_video_segment(source, duration, output_path):
    run([
        'ffmpeg','-y','-stream_loop','-1','-i',str(source),'-t',f'{duration:.3f}',
        '-vf',
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,setsar=1,eq=saturation=1.08:contrast=1.03",
        '-an','-r','30','-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p',str(output_path)
    ])
    return output_path


def build_background_video(job_dir, fallback_background, duration, work):
    images = [p for p in _job_media_files(job_dir, 'media_image_') if p.suffix.lower() in {'.jpg','.jpeg','.png','.webp'}]
    videos = [p for p in _job_media_files(job_dir, 'media_video_') if p.suffix.lower() in {'.mp4','.mov','.webm','.m4v'}]
    bg_output = work / 'bg_support.mp4'

    if not images and not videos:
        return create_motion_background(fallback_background, duration, bg_output)

    # Vídeo real vira protagonista. Imagens entram como inserts curtos entre trechos de vídeo.
    if videos:
        assets=[]
        for vid in videos:
            assets.append(('video', vid, 5.8))
            if images:
                assets.append(('image', images[len(assets) % len(images)], 2.2))
            assets.append(('video', vid, 5.2))
        # garante que todas as imagens tenham chance de aparecer sem dominar o anúncio
        for img in images:
            assets.append(('image', img, 2.0))
    else:
        assets=[('image', p, 3.0) for p in images]

    seg_dir = work / 'segments'
    seg_dir.mkdir(parents=True, exist_ok=True)
    segments=[]
    elapsed=0.0
    idx=0
    limit=max(12, len(assets)*4)
    while elapsed < duration + 0.2 and idx < limit:
        kind, src, desired = assets[idx % len(assets)]
        remaining=duration-elapsed
        seg_dur=min(desired, max(1.6, remaining+0.12))
        out=seg_dir / f'segment_{idx:02d}.mp4'
        try:
            if kind == 'video':
                create_video_segment(src, seg_dur, out)
            else:
                create_image_segment(src, seg_dur, out)
            if out.is_file() and out.stat().st_size > 12_000:
                segments.append(out); elapsed += seg_dur
        except Exception:
            pass
        idx += 1

    if not segments:
        return create_motion_background(fallback_background, duration, bg_output)

    concat_list=work/'concat_segments.txt'
    concat_list.write_text(''.join([f"file '{p.as_posix()}'\n" for p in segments]), encoding='utf-8')
    try:
        run(['ffmpeg','-y','-f','concat','-safe','0','-i',str(concat_list),'-t',f'{duration:.3f}',
             '-an','-r','30','-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p',str(bg_output)])
        if bg_output.is_file() and bg_output.stat().st_size > 20_000:
            return bg_output
    except Exception:
        pass
    return create_motion_background(fallback_background, duration, bg_output)




def create_creator_intro(source, duration, output_path):
    """Converte o vídeo quadrado/landscape do creator em abertura vertical 9:16."""
    duration = max(1.0, float(duration))
    fc = (
        "[0:v]split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "gblur=sigma=34,eq=brightness=-0.12:saturation=0.88[blur];"
        "[fg]scale=1000:1180:force_original_aspect_ratio=decrease,setsar=1[front];"
        "[blur][front]overlay=x='(W-w)/2':y='240+(1180-h)/2',"
        "drawbox=x=0:y=0:w=iw:h=220:color=black@0.10:t=fill,"
        "drawbox=x=0:y=1550:w=iw:h=370:color=black@0.12:t=fill[v]"
    )
    run([
        'ffmpeg','-y','-stream_loop','-1','-i',str(source),'-t',f'{duration:.3f}',
        '-filter_complex',fc,'-map','[v]','-an','-r','30','-c:v','libx264','-preset','veryfast',
        '-crf','21','-pix_fmt','yuv420p',str(output_path)
    ])
    return output_path


def splice_creator_with_product(creator_intro, product_background, total, creator_duration, output_path):
    creator_duration = min(float(creator_duration), max(0.0, float(total)-0.4))
    if creator_duration <= 0.5:
        shutil.copy2(product_background, output_path)
        return output_path
    if total <= creator_duration + 0.2:
        run([
            'ffmpeg','-y','-i',str(creator_intro),'-t',f'{total:.3f}','-an','-r','30',
            '-c:v','libx264','-preset','veryfast','-crf','22','-pix_fmt','yuv420p',str(output_path)
        ])
        return output_path
    fc = (
        f"[0:v]trim=start=0:end={creator_duration:.3f},setpts=PTS-STARTPTS[v0];"
        f"[1:v]trim=start={creator_duration:.3f}:end={total:.3f},setpts=PTS-STARTPTS[v1];"
        "[v0][v1]concat=n=2:v=1:a=0[v]"
    )
    run([
        'ffmpeg','-y','-i',str(creator_intro),'-i',str(product_background),
        '-filter_complex',fc,'-map','[v]','-an','-r','30','-c:v','libx264','-preset','veryfast',
        '-crf','22','-pix_fmt','yuv420p',str(output_path)
    ])
    return output_path


def generate_creator_assets(job_dir, product, voice, work):
    info_path = work / 'creator_info.json'
    creator_video = work / 'creator_ai.mp4'
    creator_reference = work / 'creator_reference.png'
    script_text = str(product.get('creator_script_tts') or product.get('creator_script') or '').strip()
    if not product.get('creator_ai_enabled') or not script_text:
        info = {'ok': False, 'engine': 'disabled', 'error': 'creator desativado ou sem roteiro'}
        info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
        return None, info

    creator_script = work / 'creator_script.txt'
    creator_script.write_text(script_text, encoding='utf-8')
    creator_audio = work / 'creator_audio.mp3'
    creator_audio_short = work / 'creator_audio_short.wav'
    creator_seconds = float(product.get('creator_target_seconds') or 3.2)
    try:
        run([
            'edge-tts','--file',str(creator_script),'--voice',voice,'--rate=+16%','--pitch=+4Hz',
            '--write-media',str(creator_audio)
        ])
        # O creator fala somente o hook. Cortar o áudio reduz MUITO o custo do fallback CPU.
        run([
            'ffmpeg','-y','-i',str(creator_audio),'-t',f'{creator_seconds:.2f}',
            '-ar','16000','-ac','1','-c:a','pcm_s16le',str(creator_audio_short)
        ])
    except Exception as exc:
        info = {'ok': False, 'engine': 'tts_failed', 'error': str(exc)}
        info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
        return None, info

    presenter = None
    for ext in ('png','jpg','jpeg','webp'):
        candidate = job_dir / f'presenter.{ext}'
        if candidate.is_file():
            presenter = candidate
            break

    # Etapa 1: HF continua útil para criar a imagem de referência. Os Spaces de talking-head
    # públicos hoje pedem janelas de GPU acima do limite do ZeroGPU, então não dependemos deles.
    hf_script = Path(__file__).with_name('creator_hf.py')
    hf_cmd = [
        sys.executable, str(hf_script),
        '--audio', str(creator_audio_short),
        '--prompt', str(product.get('creator_visual_prompt') or 'photorealistic synthetic ecommerce creator, half body, front facing'),
        '--output', str(creator_video),
        '--reference-output', str(creator_reference),
        '--info-output', str(info_path),
    ]
    if presenter:
        hf_cmd += ['--image', str(presenter)]

    print('[>] Criando referência do Creator IA...', flush=True)
    hf_result = subprocess.run(hf_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace')
    print(hf_result.stdout[-12000:], flush=True)
    try:
        hf_info = json.loads(info_path.read_text(encoding='utf-8')) if info_path.is_file() else {}
    except Exception:
        hf_info = {}
    if creator_video.is_file() and creator_video.stat().st_size > 20_000:
        hf_info['ok'] = True
        return creator_video, hf_info

    if not creator_reference.is_file() or creator_reference.stat().st_size < 5000:
        hf_info.setdefault('ok', False)
        hf_info.setdefault('error', 'Não consegui criar a imagem de referência do creator.')
        info_path.write_text(json.dumps(hf_info, ensure_ascii=False, indent=2), encoding='utf-8')
        return None, hf_info

    # Etapa 2: fallback REAL, sem ZeroGPU: SadTalker rodando em CPU no próprio runner do GitHub.
    cpu_script = Path(__file__).with_name('creator_sadtalker_cpu.py')
    cpu_info_path = work / 'creator_cpu_info.json'
    cpu_cmd = [
        sys.executable, str(cpu_script),
        '--image', str(creator_reference),
        '--audio', str(creator_audio_short),
        '--output', str(creator_video),
        '--info-output', str(cpu_info_path),
    ]
    print('[>] ZeroGPU não gerou vídeo; tentando SadTalker em CPU no GitHub Actions...', flush=True)
    cpu_result = subprocess.run(cpu_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace')
    print(cpu_result.stdout[-16000:], flush=True)
    try:
        cpu_info = json.loads(cpu_info_path.read_text(encoding='utf-8')) if cpu_info_path.is_file() else {}
    except Exception:
        cpu_info = {}

    merged = {
        'ok': bool(creator_video.is_file() and creator_video.stat().st_size > 20_000),
        'engine': cpu_info.get('engine') if cpu_info.get('ok') else (hf_info.get('engine') or 'none'),
        'reference_source': hf_info.get('reference_source', ''),
        'hf_authenticated': hf_info.get('hf_authenticated', False),
        'zerogpu_attempts': hf_info.get('attempts', []),
        'cpu_fallback': cpu_info,
        'note': 'V21.1 usa ZeroGPU para a referência e SadTalker CPU no GitHub como fallback de vídeo.'
    }
    if not merged['ok']:
        merged['error'] = cpu_info.get('error') or hf_info.get('error') or f'creator CPU retornou código {cpu_result.returncode}'
    info_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding='utf-8')
    return (creator_video if merged['ok'] else None), merged


def render(job_dir, product, background, product_png, audio, captions_ass, work, creator_video=None, creator_seconds=3.2):
    total = audio_duration(audio)
    end_cta = max(5.0, total - 2.3)
    has_video = bool(product.get('quantidade_videos_apoio'))
    has_images = bool(product.get('quantidade_imagens_apoio'))
    has_creator = bool(creator_video and Path(creator_video).is_file())
    creator_seconds = min(float(creator_seconds or 4.0), max(1.0, total - 1.0)) if has_creator else 0.0

    if has_creator:
        # Creator primeiro; depois mídia real do produto. Evita colocar uma foto gigante em cima da pessoa.
        hook_enable = "between(t,0,0.01)"
        board_enable = "between(t,0,0.01)"
        if has_video:
            product_enable = f"gte(t,{end_cta:.3f})"
        else:
            product_enable = f"between(t,{creator_seconds+0.25:.3f},{min(end_cta-0.5,creator_seconds+2.8):.3f})+gte(t,{end_cta:.3f})"
        pill1_enable = f"between(t,{creator_seconds+0.35:.3f},{creator_seconds+1.45:.3f})"
        pill2_enable = f"between(t,{creator_seconds+2.05:.3f},{creator_seconds+3.15:.3f})"
        pill3_enable = f"between(t,{creator_seconds+3.75:.3f},{creator_seconds+4.85:.3f})"
    elif has_video:
        hook_enable = "between(t,0,1.55)"
        product_enable = f"gte(t,{end_cta:.3f})"
        board_enable = "between(t,0,0.01)"
        pill1_enable = "between(t,2.8,4.0)"
        pill2_enable = "between(t,5.8,7.0)"
        pill3_enable = "between(t,8.8,10.0)"
    elif has_images:
        hook_enable = "between(t,0,1.55)"
        product_enable = f"between(t,0,2.4)+gte(t,{end_cta:.3f})"
        board_enable = "between(t,0,0.01)"
        pill1_enable = "between(t,3.0,4.2)"
        pill2_enable = "between(t,5.2,6.4)"
        pill3_enable = "between(t,7.4,8.6)"
    else:
        hook_enable = "between(t,0,1.55)"
        product_enable = '1'
        board_enable = "between(t,0,0.01)"
        pill1_enable = "between(t,3.0,4.2)"
        pill2_enable = "between(t,5.2,6.4)"
        pill3_enable = "between(t,7.4,8.6)"

    bg_local = work / 'background.jpg'
    Image.open(background).convert('RGB').resize((W, H), Image.Resampling.LANCZOS).save(bg_local, quality=94)
    product_background = build_background_video(job_dir, bg_local, total, work)
    background_video = product_background
    if has_creator:
        creator_intro = work / 'creator_intro_vertical.mp4'
        creator_base = work / 'creator_product_base.mp4'
        create_creator_intro(creator_video, creator_seconds, creator_intro)
        splice_creator_with_product(creator_intro, product_background, total, creator_seconds, creator_base)
        background_video = creator_base
    make_visual_assets(work, product)

    music = work / 'commercial_music.wav'
    create_commercial_music(music, total)
    presenter_png = work / 'presenter.png'
    if not presenter_png.exists():
        Image.new('RGBA', (520,900), (0,0,0,0)).save(presenter_png)

    fc = f"""[0:v]scale=1080:1920,setsar=1,eq=brightness=-0.02:saturation=1.06,vignette=PI/5[bg0];
[6:v]format=rgba,colorchannelmixer=aa=0.36[flare];
[bg0][flare]overlay=x='(W-w)/2+3*sin(t*0.8)':y='480+5*cos(t*0.7)':eval=frame[bg];
[1:v]format=rgba,scale=800:-1,fade=t=in:st=0:d=0.24:alpha=1[p];
[bg][p]overlay=x='(W-w)/2+6*sin(t*1.0)':y='if(lt(t,0.48),930-(t/0.48)*560,360+5*sin(t*1.0))':enable='{product_enable}':eval=frame[v1];
[5:v]format=rgba[shine];[shine]split=2[s1][s2];
[v1][s1]overlay=x='-w+(t-0.68)/0.72*(W+w)':y=0:enable='between(t,0.68,1.40)':eval=frame[v1a];
[v1a][s2]overlay=x='-w+(t-{end_cta:.3f})/0.72*(W+w)':y=0:enable='between(t,{end_cta:.3f},{end_cta+0.72:.3f})':eval=frame[v1b];
[2:v]format=rgba[hook];[v1b][hook]overlay=x='(W-w)/2':y='if(lt(t,0.24),-h+(t/0.24)*(72+h),72)':enable='{hook_enable}':eval=frame[v2];
[3:v]format=rgba[board];[v2][board]overlay=x=0:y=0:enable='{board_enable}'[v3];
[8:v]format=rgba[pill1];[v3][pill1]overlay=x=54:y=260:enable='{pill1_enable}'[v4];
[9:v]format=rgba[pill2];[v4][pill2]overlay=x=54:y=260:enable='{pill2_enable}'[v5];
[10:v]format=rgba[pill3];[v5][pill3]overlay=x=54:y=260:enable='{pill3_enable}'[v6];
[4:v]format=rgba[cta];[v6][cta]overlay=x='(W-w)/2':y='if(lt(t,{end_cta+0.30:.3f}),H-(t-{end_cta:.3f})/0.30*(H-1320),1320)':enable='gte(t,{end_cta:.3f})'[v7];
[v7]ass=captions.ass[v];
[11:a]volume=1.12[narr];
[12:a]volume=0.12[musicbed];
[narr][musicbed]amix=inputs=2:duration=first:dropout_transition=1.4,alimiter=limit=0.94[aout]
""".replace('\n','')

    output = work / 'anuncio_final.mp4'
    cmd = ['ffmpeg', '-y', '-i', str(background_video)]
    for img in [product_png, work/'hook.png', work/'board.png', work/'cta.png', work/'shine.png', work/'hero_flare.png', presenter_png, work/'pill1.png', work/'pill2.png', work/'pill3.png']:
        cmd += ['-loop', '1', '-framerate', '30', '-i', str(img)]
    cmd += ['-i', str(audio), '-i', str(music), '-filter_complex', fc, '-map', '[v]', '-map', '[aout]', '-t', f'{total:.3f}', '-r', '30', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', str(output)]
    run(cmd, cwd=work)
    return output

def main():
    if len(sys.argv)!=3:
        raise SystemExit('Uso: render_v21_1.py JOB_DIR OUTPUT_DIR')
    job_dir=Path(sys.argv[1]).resolve(); output_dir=Path(sys.argv[2]).resolve()
    output_dir.mkdir(parents=True,exist_ok=True)
    work=output_dir/'_work'; work.mkdir(parents=True,exist_ok=True)
    product=json.loads((job_dir/'produto.json').read_text(encoding='utf-8'))
    roteiro=work/'roteiro.txt'; roteiro.write_text(product.get('roteiro_tts') or product['roteiro_comercial'],encoding='utf-8')
    audio=work/'narracao.mp3'; srt=work/'subtitles.srt'
    voice = product.get('voice_id') or 'pt-BR-AntonioNeural'
    run(['edge-tts','--file',str(roteiro),'--voice',voice,'--rate=+12%','--pitch=+4Hz','--write-media',str(audio),'--write-subtitles',str(srt)])
    ass=work/'captions.ass'; make_tiktok_ass(srt,ass)
    background=job_dir/'background.jpg'
    if not background.is_file():
        background=work/'procedural.jpg'; create_procedural_background(background, product)
    product_png=prepare_product(job_dir,work)
    if not product_png:
        product_png=work/'product.png'; create_missing_product(product,product_png)
    elif product.get('imagem_ilustrativa'):
        stamp_illustrative(product_png)
    make_marketing_banners(product, background, product_png, output_dir)
    if not (work/'presenter.png').exists():
        prepare_presenter(job_dir, work)

    creator_video, creator_info = generate_creator_assets(job_dir, product, voice, work)
    product['creator_status'] = 'ok' if creator_video else 'fallback_standard'
    product['creator_engine'] = creator_info.get('engine', 'none') if isinstance(creator_info, dict) else 'none'
    product['creator_info'] = creator_info
    creator_seconds = float(product.get('creator_target_seconds') or 4.0)
    final=render(job_dir,product,background,product_png,audio,ass,work,creator_video=creator_video,creator_seconds=creator_seconds)
    shutil.copy2(final,output_dir/'anuncio_final.mp4')
    (output_dir/'produto.json').write_text(json.dumps(product, ensure_ascii=False, indent=2), encoding='utf-8')
    if creator_video and Path(creator_video).is_file():
        shutil.copy2(creator_video, output_dir/'creator_ai.mp4')
    if (work/'creator_reference.png').is_file():
        shutil.copy2(work/'creator_reference.png', output_dir/'creator_reference.png')
    if (work/'creator_info.json').is_file():
        shutil.copy2(work/'creator_info.json', output_dir/'creator_info.json')
    shutil.copy2(ass,output_dir/'legendas_tiktok.ass')
    shutil.copy2(roteiro,output_dir/'roteiro_narracao.txt')
    if (job_dir/'produto.json').is_file():
        prod_src = job_dir/'produto.json'
        try:
            analysis = json.loads(prod_src.read_text(encoding='utf-8')).get('analise_produto')
            if analysis:
                (output_dir/'analise_produto.json').write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass
    (output_dir/'copie_e_cole_na_live.txt').write_text(
        (product.get('post_text_render') or product.get('post_text') or f"🔥 {product.get('titulo_curto','ACHADO')}\n\n🛒 Confira o anúncio e veja detalhes atualizados.\n\n" + ' '.join(product.get('tags_engajamento') or []) + '\n'),
        encoding='utf-8')
    diagnostic = {
        'version': '21.1',
        'creator_ok': bool(creator_video),
        'creator_engine': product.get('creator_engine','none'),
        'creator_info': creator_info,
        'product_media_images': int(product.get('quantidade_imagens_apoio') or 0),
        'product_media_videos': int(product.get('quantidade_videos_apoio') or 0),
        'render_mode': 'creator_then_product' if creator_video else ('raw_product_video' if int(product.get('quantidade_videos_apoio') or 0) else 'image_motion'),
        'final_exists': (output_dir/'anuncio_final.mp4').is_file(),
        'final_bytes': (output_dir/'anuncio_final.mp4').stat().st_size if (output_dir/'anuncio_final.mp4').is_file() else 0,
    }
    (output_dir/'diagnostico_render.json').write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding='utf-8')
    print('[OK] Render V21.1 TikTok-first concluído.',flush=True)

if __name__=='__main__':
    main()
