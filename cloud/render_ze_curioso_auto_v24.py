#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H = 1080, 1920
FPS = 30
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
DEFAULT_VOICE = "pt-BR-AntonioNeural"


def run(cmd):
    print("[>] " + " ".join(str(x) for x in cmd), flush=True)
    r = subprocess.run([str(x) for x in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
    if r.returncode:
        print(r.stderr[-9000:], flush=True)
        raise RuntimeError(f"Comando falhou: {cmd[0]}")
    return r


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def font(size, bold=True):
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size)
    except Exception:
        return ImageFont.load_default()


def wrap(text, max_chars):
    words = clean(text).split()
    lines, cur = [], []
    for word in words:
        trial = " ".join(cur + [word])
        if len(trial) <= max_chars:
            cur.append(word)
        else:
            if cur:
                lines.append(" ".join(cur))
            cur = [word]
    if cur:
        lines.append(" ".join(cur))
    return "\n".join(lines)


def ffprobe_duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path])
    try:
        return max(1.0, float(r.stdout.strip()))
    except Exception:
        return 25.0


def ass_time(sec):
    cs = int(round(sec * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def make_ass(scenes, durations, path):
    header = """[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Caption,DejaVu Sans,50,&H00FFFFFF,&H000000FF,&H00101010,&H9A000000,-1,0,0,0,100,100,0,0,3,3,0,2,70,70,210,1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"""
    lines = [header]
    t = 0.0
    for scene, dur in zip(scenes, durations):
        text = clean(scene.get("texto") or scene.get("titulo"))
        text = text.replace("{", "(").replace("}", ")")
        lines.append(f"Dialogue: 0,{ass_time(t)},{ass_time(t+dur)},Caption,,0,0,0,,{text}\n")
        t += dur
    path.write_text("".join(lines), encoding="utf-8")


def cover(path):
    im = Image.open(path).convert("RGB")
    return ImageOps.fit(im, (W, H), method=Image.Resampling.LANCZOS).convert("RGBA")


def shade_background(img):
    shade = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(shade, "RGBA")
    # contraste para headline e legenda sem matar o background de IA
    d.rectangle((0, 0, W, 370), fill=(0, 0, 0, 90))
    d.rectangle((0, 1420, W, H), fill=(0, 0, 0, 72))
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow, "RGBA")
    gd.ellipse((650, 1030, 1220, 1760), fill=(255, 171, 55, 35))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    return Image.alpha_composite(Image.alpha_composite(img, shade), glow)


def draw_mascot(base, x, y, scale=1.0, expression="smile"):
    """Mascote com rosto reconhecível. Mantido vetorial para ser leve e consistente."""
    layer = Image.new("RGBA", base.size, (0,0,0,0))
    d = ImageDraw.Draw(layer, "RGBA")
    s = scale
    skin = (224, 154, 103, 255)
    dark = (46, 29, 24, 255)
    white = (248, 246, 239, 255)

    # sombra
    d.ellipse((x-int(155*s), y+int(320*s), x+int(165*s), y+int(380*s)), fill=(0,0,0,70))
    # torso
    d.rounded_rectangle((x-int(145*s), y+int(75*s), x+int(145*s), y+int(345*s)), radius=int(70*s), fill=white, outline=(18,20,28,110), width=max(2,int(4*s)))
    # gola
    d.polygon([(x-int(92*s),y+int(105*s)),(x-int(30*s),y+int(155*s)),(x-int(5*s),y+int(105*s))], fill=(225,225,220,255))
    d.polygon([(x+int(92*s),y+int(105*s)),(x+int(30*s),y+int(155*s)),(x+int(5*s),y+int(105*s))], fill=(225,225,220,255))
    # gravata
    d.polygon([(x,y+int(135*s)),(x-int(24*s),y+int(180*s)),(x-int(13*s),y+int(290*s)),(x,y+int(330*s)),(x+int(13*s),y+int(290*s)),(x+int(24*s),y+int(180*s))], fill=(205,42,49,255))
    # pescoço e rosto
    d.rectangle((x-int(34*s),y+int(25*s),x+int(34*s),y+int(105*s)), fill=skin)
    d.ellipse((x-int(116*s),y-int(180*s),x+int(116*s),y+int(72*s)), fill=skin, outline=(105,58,38,180), width=max(2,int(4*s)))
    # orelhas
    d.ellipse((x-int(135*s),y-int(80*s),x-int(92*s),y-int(20*s)), fill=skin)
    d.ellipse((x+int(92*s),y-int(80*s),x+int(135*s),y-int(20*s)), fill=skin)
    # cabelo
    d.arc((x-int(108*s),y-int(185*s),x+int(108*s),y-int(35*s)), 180, 355, fill=dark, width=max(8,int(22*s)))
    d.arc((x-int(95*s),y-int(170*s),x+int(35*s),y-int(50*s)), 205, 330, fill=dark, width=max(6,int(16*s)))
    # olhos brancos + íris/pupila
    for ex in (-48, 48):
        d.ellipse((x+int((ex-25)*s), y-int(72*s), x+int((ex+25)*s), y-int(20*s)), fill=(255,255,255,255), outline=(76,48,36,200), width=max(1,int(2*s)))
        d.ellipse((x+int((ex-9)*s), y-int(60*s), x+int((ex+9)*s), y-int(38*s)), fill=(105,62,30,255))
        d.ellipse((x+int((ex-4)*s), y-int(56*s), x+int((ex+4)*s), y-int(40*s)), fill=(18,18,22,255))
        d.ellipse((x+int((ex-1)*s), y-int(54*s), x+int((ex+2)*s), y-int(50*s)), fill=(255,255,255,240))
    # sobrancelhas
    d.line((x-int(78*s),y-int(92*s),x-int(28*s),y-int(100*s)), fill=dark, width=max(2,int(7*s)))
    d.line((x+int(28*s),y-int(100*s),x+int(78*s),y-int(92*s)), fill=dark, width=max(2,int(7*s)))
    # nariz
    d.line((x,y-int(28*s),x-int(7*s),y+int(8*s),x+int(8*s),y+int(12*s)), fill=(138,82,58,220), width=max(2,int(4*s)))
    # bigode
    d.arc((x-int(64*s),y-int(2*s),x-int(2*s),y+int(45*s)),200,340,fill=dark,width=max(2,int(5*s)))
    d.arc((x+int(2*s),y-int(2*s),x+int(64*s),y+int(45*s)),200,340,fill=dark,width=max(2,int(5*s)))
    # boca
    if expression == "surprised":
        d.ellipse((x-int(20*s),y+int(32*s),x+int(20*s),y+int(70*s)), fill=(92,38,38,255))
    else:
        d.arc((x-int(55*s),y+int(20*s),x+int(55*s),y+int(80*s)),15,165,fill=(102,43,43,255),width=max(2,int(5*s)))
        d.line((x-int(25*s),y+int(55*s),x+int(25*s),y+int(55*s)), fill=(255,245,235,220), width=max(2,int(3*s)))
    # chapéu de palha com faixa vermelha
    d.ellipse((x-int(150*s),y-int(195*s),x+int(150*s),y-int(128*s)), fill=(201,151,76,255), outline=(80,52,24,220), width=max(2,int(4*s)))
    d.rounded_rectangle((x-int(95*s),y-int(260*s),x+int(95*s),y-int(145*s)), radius=max(8,int(32*s)), fill=(218,167,88,255), outline=(80,52,24,220), width=max(2,int(4*s)))
    d.rectangle((x-int(95*s),y-int(174*s),x+int(95*s),y-int(151*s)), fill=(175,40,43,255))
    # braços gesticulando
    d.line((x-int(118*s),y+int(170*s),x-int(220*s),y+int(115*s)), fill=skin, width=max(12,int(30*s)))
    d.ellipse((x-int(237*s),y+int(95*s),x-int(202*s),y+int(130*s)), fill=skin)
    d.line((x+int(118*s),y+int(170*s),x+int(220*s),y+int(105*s)), fill=skin, width=max(12,int(30*s)))
    d.ellipse((x+int(202*s),y+int(88*s),x+int(240*s),y+int(126*s)), fill=skin)
    base.alpha_composite(layer)


def draw_scene(job, scene, index, total, job_dir, destination):
    bg = job_dir / f"scene_{index+1:02d}.jpg"
    if not bg.is_file():
        raise RuntimeError(f"Background IA ausente: {bg.name}. A versão Auto não usa fundo manual/procedural.")

    img = shade_background(cover(bg))
    d = ImageDraw.Draw(img, "RGBA")

    # identidade discreta
    d.rounded_rectangle((48,50,318,116), radius=25, fill=(7,9,16,185))
    d.text((70,83), "ZÉ CURIOSO", anchor="lm", font=font(30), fill=(255,224,137,255))
    # barra de progresso
    d.rounded_rectangle((355,72,1020,88), radius=8, fill=(255,255,255,55))
    p = int(355 + (1020-355) * ((index+1)/total))
    d.rounded_rectangle((355,72,p,88), radius=8, fill=(255,181,56,255))

    headline = wrap(clean(scene.get("titulo")).upper(), 24)
    d.multiline_text((58,185), headline, font=font(67), fill=(255,255,255,255), spacing=8, stroke_width=4, stroke_fill=(0,0,0,150))

    # Zé aparece em hook, vínculo/revelação e fechamento
    show_ze = index in {0, 3, total-1}
    if show_ze:
        expr = "surprised" if index == 0 else "smile"
        draw_mascot(img, 795, 1325, 0.78 if index == 0 else 0.70, expr)
        bubbles = ["OXENTE...", "RAPAZ...", "MAS PERA AÍ...", "AGORA OLHA ISSO...", "CURIOSO, NÉ?"]
        label = bubbles[min(index, len(bubbles)-1)]
        d = ImageDraw.Draw(img, "RGBA")
        d.rounded_rectangle((52,1325,440,1428), radius=34, fill=(255,177,62,235))
        d.text((246,1377), label, anchor="mm", font=font(31), fill=(32,25,20,255))

    if index == total - 1:
        d = ImageDraw.Draw(img, "RGBA")
        d.rounded_rectangle((70,1635,1010,1765), radius=42, fill=(230,72,43,235))
        d.text((540,1683), "SEGUE O ZÉ CURIOSO", anchor="mm", font=font(43), fill=(255,255,255,255))
        d.text((540,1730), "mais curiosidades rápidas todo dia", anchor="mm", font=font(27, False), fill=(255,241,225,255))

    img.convert("RGB").save(destination, quality=94)


def synthesize(script, voice, destination):
    run(["edge-tts", "--voice", voice, "--text", script, "--write-media", destination])


def build_video(job, job_dir, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_work_auto"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    scenes = [x for x in (job.get("cenas") or []) if isinstance(x, dict)][:5]
    if len(scenes) != 5:
        raise RuntimeError("A versão Auto espera exatamente 5 cenas.")

    script = clean(job.get("roteiro"))
    voice = clean(job.get("voz")) or DEFAULT_VOICE
    audio = work / "narracao.mp3"
    synthesize(script, voice, audio)
    audio_seconds = ffprobe_duration(audio)

    base = max(4.0, audio_seconds / len(scenes))
    durations = [base] * len(scenes)

    clips = []
    for i, scene in enumerate(scenes):
        png = work / f"scene_{i+1:02d}.png"
        draw_scene(job, scene, i, len(scenes), job_dir, png)
        mp4 = work / f"scene_{i+1:02d}.mp4"
        frames = int(math.ceil(durations[i] * FPS))
        # Ken Burns discreto no background composto
        if i % 2 == 0:
            zoom = "min(zoom+0.00045,1.045)"
        else:
            zoom = "if(lte(zoom,1.0),1.04,max(1.0,zoom-0.00042))"
        run(["ffmpeg","-y","-loop","1","-i",png,"-vf",f"zoompan=z='{zoom}':d={frames}:s=1080x1920:fps={FPS},format=yuv420p","-t",f"{durations[i]:.3f}","-an","-c:v","libx264","-preset","veryfast","-crf","20",mp4])
        clips.append(mp4)

    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{p.resolve()}'\n" for p in clips), encoding="utf-8")
    visual = work / "visual.mp4"
    run(["ffmpeg","-y","-f","concat","-safe","0","-i",concat,"-c","copy",visual])

    ass = out_dir / "legendas_ze_curioso.ass"
    make_ass(scenes, durations, ass)
    final = out_dir / "anuncio_final.mp4"
    run(["ffmpeg","-y","-i",visual,"-i",audio,"-vf",f"ass={ass.as_posix()}","-map","0:v:0","-map","1:a:0","-c:v","libx264","-preset","veryfast","-crf","20","-c:a","aac","-b:a","160k","-shortest",final])

    shutil.copy2(work / "scene_01.png", out_dir / "capa_video.png")
    (out_dir / "roteiro_narracao.txt").write_text(script + "\n", encoding="utf-8")
    (out_dir / "curiosidade.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    diag = {
        "version": "ze-curioso-auto-v24",
        "render_mode": "ai_background_plus_mascot",
        "background_engine": "cloudflare_flux",
        "manual_background_required": False,
        "scene_count": len(scenes),
        "audio_duration_seconds": round(audio_seconds,2),
        "final_exists": final.is_file(),
        "final_bytes": final.stat().st_size if final.is_file() else 0,
    }
    (out_dir / "diagnostico_render.json").write_text(json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Zé Curioso Auto renderizado: {final}", flush=True)


def main():
    if len(sys.argv) < 3:
        raise SystemExit("Uso: render_ze_curioso_auto_v24.py <job_dir> <output_dir>")
    job_dir = Path(sys.argv[1]).resolve()
    out_dir = Path(sys.argv[2]).resolve()
    source = job_dir / "curiosidade.json"
    job = json.loads(source.read_text(encoding="utf-8"))
    build_video(job, job_dir, out_dir)


if __name__ == "__main__":
    main()
