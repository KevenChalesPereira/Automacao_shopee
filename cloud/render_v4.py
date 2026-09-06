#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import html
import json
import math
import random
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


def create_missing_product(product, target):
    img = Image.new("RGBA", (900,1040), (0,0,0,0))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle((65,160,835,875), radius=75, fill=(248,248,251,248))
    name = str(product.get("nome_limpo") or "Produto")
    lines = "\n".join(textwrap.wrap(name.upper(), width=18, break_long_words=False))
    f = fit_font(d, lines, 650, 64)
    d.multiline_text((450,485), lines, anchor="mm", align="center", font=f, fill=(22,23,30), spacing=12)
    d.text((450,760), "IMAGEM NÃO DISPONÍVEL", anchor="mm", font=font(28), fill=(110,110,125))
    img.save(target)


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


def make_visual_assets(work, product):
    points = list(product.get("pontos_visuais") or [])[:3]
    while len(points)<3: points.append("CONFIRA")
    make_card(work/'hook.png', product.get('hook_visual') or 'OLHA ESSE ACHADO', (920,250), (15,16,24,225), (255,255,255,255), radius=44, accent=(255,91,55,255), font_size=54)
    make_card(work/'badge1.png', points[0], (420,108), (255,91,55,245), (255,255,255,255), radius=32, font_size=40)
    make_card(work/'badge2.png', points[1], (420,108), (248,248,251,245), (20,21,28,255), radius=32, font_size=40)
    make_card(work/'badge3.png', points[2], (420,108), (27,29,42,242), (255,255,255,255), radius=32, font_size=40)
    make_card(work/'cta.png', 'CONFIRA NA SHOPEE', (900,176), (255,91,55,248), (255,255,255,255), radius=48, font_size=58)


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
        n=3 if remain>=3 else remain
        # keep very long words from making a 3-word chunk too wide
        if n==3 and sum(len(x) for x in words[i:i+3])>23:
            n=2
        chunks.append(words[i:i+n])
        i+=n
    return chunks


def make_tiktok_ass(srt, ass_path):
    cues=parse_srt(srt)
    header="""[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nScaledBorderAndShadow: yes\nWrapStyle: 2\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Pop,DejaVu Sans,74,&H00FFFFFF,&H0066E0FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,7,2,2,45,45,300,1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"""
    events=[]
    for start,end,text in cues:
        words=[w for w in re.split(r'\s+',text.strip()) if w]
        if not words: continue
        chunks=chunk_words(words)
        dur=max(0.30,end-start)
        total_words=sum(len(c) for c in chunks)
        cursor=start
        for ci,c in enumerate(chunks):
            share=dur*(len(c)/total_words)
            cstart=cursor
            cend=end if ci==len(chunks)-1 else min(end,cursor+share)
            if cend-cstart<0.28:
                cend=min(end,cstart+0.28)
            cursor=cend
            # highlight final word, keeping the rest white
            safe=[ass_escape(w.upper()) for w in c]
            if len(safe)==1:
                content=r'{\c&H0066E0FF&}'+safe[0]
            else:
                content=' '.join(safe[:-1]) + r' {\c&H0066E0FF&}' + safe[-1]
            fx=(r'{\an2\pos(540,1515)\fscx78\fscy78\alpha&H35&'
                r'\t(0,110,\fscx108\fscy108\alpha&H00&)'
                r'\t(110,220,\fscx100\fscy100)\fad(25,55)}')
            events.append(f"Dialogue: 0,{ass_time(cstart)},{ass_time(cend)},Pop,,0,0,0,,{fx}{content}")
    ass_path.write_text(header+'\n'.join(events)+'\n',encoding='utf-8')


def render(product, background, product_png, audio, captions_ass, work):
    total=audio_duration(audio)
    end_cta=max(7.0,total-4.6)
    bg_local=work/'background.jpg'
    Image.open(background).convert('RGB').resize((W,H),Image.Resampling.LANCZOS).save(bg_local,quality=94)
    make_visual_assets(work,product)

    # Product stays fixed-size; motion happens only in overlay expressions.
    # This avoids temporal variables in scale(), the fragile point in V3.
    fc=f"""[0:v]scale=1080:1920,zoompan=z='min(zoom+0.00020,1.07)':x='iw/2-(iw/zoom/2)+10*sin(on/38)':y='ih/2-(ih/zoom/2)+8*cos(on/47)':d=1:s=1080x1920:fps=30,eq=brightness=-0.04:saturation=1.10[bg];
[1:v]format=rgba,scale=780:-1[p];
[bg][p]overlay=x='(W-w)/2+12*sin(t*1.25)':y='420+18*sin(t*1.05)':eval=frame[v1];
[2:v]format=rgba[hook];[v1][hook]overlay=x='(W-w)/2':y='if(lt(t,0.34),-h+(t/0.34)*(120+h),120)':enable='between(t,0,4.4)':eval=frame[v2];
[3:v]format=rgba[b1];[v2][b1]overlay=x='if(lt(t,6.4),-w+(t-6.0)/0.4*(80+w),80)':y=1160:enable='between(t,6.0,10.6)':eval=frame[v3];
[4:v]format=rgba[b2];[v3][b2]overlay=x='if(lt(t,9.6),W-(t-9.2)/0.4*(W-580),580)':y=1280:enable='between(t,9.2,13.8)':eval=frame[v4];
[5:v]format=rgba[b3];[v4][b3]overlay=x='if(lt(t,12.8),-w+(t-12.4)/0.4*(80+w),80)':y=360:enable='between(t,12.4,17.2)':eval=frame[v5];
[6:v]format=rgba[cta];[v5][cta]overlay=x='(W-w)/2':y='if(lt(t,{end_cta+0.35:.3f}),-h+(t-{end_cta:.3f})/0.35*(125+h),125)':enable='gte(t,{end_cta:.3f})':eval=frame[v6];
[v6]ass=captions.ass[v]""".replace('\n','')

    output=work/'anuncio_final.mp4'
    cmd=['ffmpeg','-y']
    for img in [bg_local,product_png,work/'hook.png',work/'badge1.png',work/'badge2.png',work/'badge3.png',work/'cta.png']:
        cmd += ['-loop','1','-framerate','30','-i',str(img)]
    cmd += ['-i',str(audio),'-filter_complex',fc,'-map','[v]','-map','7:a:0','-t',f'{total:.3f}','-r','30','-c:v','libx264','-preset','veryfast','-crf','22','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-movflags','+faststart',str(output)]
    run(cmd,cwd=work)
    return output


def main():
    if len(sys.argv)!=3:
        raise SystemExit('Uso: render_v4.py JOB_DIR OUTPUT_DIR')
    job_dir=Path(sys.argv[1]).resolve(); output_dir=Path(sys.argv[2]).resolve()
    output_dir.mkdir(parents=True,exist_ok=True)
    work=output_dir/'_work'; work.mkdir(parents=True,exist_ok=True)
    product=json.loads((job_dir/'produto.json').read_text(encoding='utf-8'))
    roteiro=work/'roteiro.txt'; roteiro.write_text(product['roteiro_comercial'],encoding='utf-8')
    audio=work/'narracao.mp3'; srt=work/'subtitles.srt'
    run(['edge-tts','--file',str(roteiro),'--voice',VOICE,'--rate=+10%','--write-media',str(audio),'--write-subtitles',str(srt)])
    ass=work/'captions.ass'; make_tiktok_ass(srt,ass)
    background=job_dir/'background.jpg'
    if not background.is_file():
        background=work/'procedural.jpg'; create_procedural_background(background)
    product_png=prepare_product(job_dir,work)
    if not product_png:
        product_png=work/'product.png'; create_missing_product(product,product_png)
    final=render(product,background,product_png,audio,ass,work)
    shutil.copy2(final,output_dir/'anuncio_final.mp4')
    shutil.copy2(job_dir/'produto.json',output_dir/'produto.json')
    shutil.copy2(ass,output_dir/'legendas_tiktok.ass')
    (output_dir/'copie_e_cole_na_live.txt').write_text(
        f"🔥 ACHADO NA SHOPEE\n\n{product.get('nome_limpo','Produto')}\n\n🛒 Confira preço, avaliações, cupons, frete e condições atuais no anúncio.\n\n"+' '.join(product.get('tags_engajamento') or [])+'\n',
        encoding='utf-8')
    print('[OK] Render V4 concluído.',flush=True)

if __name__=='__main__':
    main()
