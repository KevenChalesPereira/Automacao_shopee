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
    result = subprocess.run(
        [str(x) for x in cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout[-3000:], flush=True)
        if result.stderr:
            print(result.stderr[-12000:], flush=True)
        raise RuntimeError(f"Comando falhou: {cmd[0]}")
    return result


def ffprobe_duration(path: Path) -> float:
    result = run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ])
    try:
        return max(1.0, float(result.stdout.strip()))
    except Exception:
        return 20.0


def font(size: int, bold: bool = True):
    path = FONT_BOLD if bold else FONT_REGULAR
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def wrap(text: str, width: int) -> str:
    words = clean(text).split()
    lines = []
    current = []
    for word in words:
        trial = " ".join(current + [word])
        if len(trial) <= width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


def gradient_background(index: int) -> Image.Image:
    palettes = [
        ((12, 19, 40), (26, 75, 132), (237, 112, 54)),
        ((20, 16, 42), (74, 40, 118), (235, 101, 75)),
        ((10, 41, 43), (25, 98, 91), (226, 154, 55)),
        ((44, 24, 17), (112, 57, 28), (230, 124, 49)),
        ((16, 26, 54), (39, 85, 148), (111, 67, 169)),
    ]
    top, mid, accent = palettes[index % len(palettes)]
    img = Image.new("RGB", (W, H), top)
    px = img.load()
    for y in range(H):
        q = y / max(1, H - 1)
        if q < 0.72:
            z = q / 0.72
            color = tuple(int(top[i] * (1-z) + mid[i] * z) for i in range(3))
        else:
            z = (q - 0.72) / 0.28
            color = tuple(int(mid[i] * (1-z) + accent[i] * z) for i in range(3))
        for x in range(W):
            px[x, y] = color
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow, "RGBA")
    gd.ellipse((-380, -260, 580, 720), fill=(255, 255, 255, 28))
    gd.ellipse((620, 200, 1450, 1130), fill=(255, 194, 105, 38))
    glow = glow.filter(ImageFilter.GaussianBlur(145))
    return Image.alpha_composite(img.convert("RGBA"), glow)


def draw_hat(draw: ImageDraw.ImageDraw, cx: int, cy: int, s: float):
    draw.ellipse(
        (cx-int(155*s), cy-int(30*s), cx+int(155*s), cy+int(48*s)),
        fill=(191, 143, 72, 255), outline=(86, 58, 26, 255), width=max(2, int(5*s))
    )
    draw.rounded_rectangle(
        (cx-int(100*s), cy-int(105*s), cx+int(100*s), cy+int(24*s)),
        radius=max(8, int(36*s)),
        fill=(205, 157, 82, 255), outline=(86, 58, 26, 255), width=max(2, int(5*s))
    )


def draw_mascot(base: Image.Image, x: int, y: int, scale: float = 1.0, mood: str = "curious"):
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")
    cx, cy, s = int(x), int(y), scale
    skin = (196, 136, 92, 255)

    d.rounded_rectangle(
        (cx-int(145*s), cy+int(120*s), cx+int(145*s), cy+int(430*s)),
        radius=max(20, int(68*s)),
        fill=(247, 245, 238, 255), outline=(20, 22, 28, 95), width=max(2, int(4*s))
    )
    d.polygon([
        (cx, cy+int(145*s)),
        (cx-int(30*s), cy+int(202*s)),
        (cx-int(16*s), cy+int(320*s)),
        (cx, cy+int(365*s)),
        (cx+int(16*s), cy+int(320*s)),
        (cx+int(30*s), cy+int(202*s)),
    ], fill=(198, 42, 48, 255))

    d.rectangle((cx-int(36*s), cy+int(55*s), cx+int(36*s), cy+int(140*s)), fill=skin)
    d.ellipse(
        (cx-int(122*s), cy-int(145*s), cx+int(122*s), cy+int(115*s)),
        fill=skin, outline=(91, 53, 34, 150), width=max(2, int(4*s))
    )

    brow_y = cy-int(46*s)
    if mood == "surprised":
        d.arc((cx-int(78*s), brow_y-int(30*s), cx-int(15*s), brow_y+int(10*s)), 185, 355, fill=(54,35,27,255), width=max(2,int(6*s)))
        d.arc((cx+int(15*s), brow_y-int(30*s), cx+int(78*s), brow_y+int(10*s)), 185, 355, fill=(54,35,27,255), width=max(2,int(6*s)))
    else:
        d.line((cx-int(72*s), brow_y, cx-int(24*s), brow_y-int(8*s)), fill=(54,35,27,255), width=max(2,int(6*s)))
        d.line((cx+int(24*s), brow_y-int(8*s), cx+int(72*s), brow_y), fill=(54,35,27,255), width=max(2,int(6*s)))

    eye_r = int(12*s)
    d.ellipse((cx-int(52*s)-eye_r, cy-int(23*s)-eye_r, cx-int(52*s)+eye_r, cy-int(23*s)+eye_r), fill=(24,24,28,255))
    d.ellipse((cx+int(52*s)-eye_r, cy-int(23*s)-eye_r, cx+int(52*s)+eye_r, cy-int(23*s)+eye_r), fill=(24,24,28,255))
    d.line((cx, cy, cx-int(6*s), cy+int(34*s), cx+int(6*s), cy+int(39*s)), fill=(112,67,48,210), width=max(2,int(4*s)))
    if mood == "surprised":
        d.ellipse((cx-int(22*s), cy+int(52*s), cx+int(22*s), cy+int(86*s)), fill=(92,42,38,230))
    else:
        d.arc((cx-int(58*s), cy+int(30*s), cx+int(58*s), cy+int(105*s)), 18, 162, fill=(95,45,40,255), width=max(2,int(5*s)))

    d.arc((cx-int(68*s), cy+int(14*s), cx-int(2*s), cy+int(70*s)), 210, 340, fill=(56,36,29,190), width=max(2,int(4*s)))
    d.arc((cx+int(2*s), cy+int(14*s), cx+int(68*s), cy+int(70*s)), 200, 330, fill=(56,36,29,190), width=max(2,int(4*s)))
    draw_hat(d, cx, cy-int(120*s), s)

    if mood == "point":
        d.line((cx+int(112*s), cy+int(210*s), cx+int(245*s), cy+int(140*s)), fill=skin, width=max(12,int(32*s)))
        d.ellipse((cx+int(225*s), cy+int(115*s), cx+int(274*s), cy+int(164*s)), fill=skin)
    else:
        d.line((cx-int(110*s), cy+int(220*s), cx-int(195*s), cy+int(145*s)), fill=skin, width=max(12,int(30*s)))
        d.line((cx+int(110*s), cy+int(220*s), cx+int(195*s), cy+int(145*s)), fill=skin, width=max(12,int(30*s)))

    base.alpha_composite(layer)


def find_scene_asset(job_dir: Path, index: int):
    for ext in ("jpg", "jpeg", "png", "webp"):
        p = job_dir / f"scene_{index+1:02d}.{ext}"
        if p.is_file():
            return p
    return None


def cover_image(source: Path) -> Image.Image:
    img = Image.open(source).convert("RGB")
    return ImageOps.fit(img, (W, H), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5)).convert("RGBA")


def draw_cat_visual(img: Image.Image, index: int):
    d = ImageDraw.Draw(img, "RGBA")
    glow = Image.new("RGBA", img.size, (0,0,0,0))
    gd = ImageDraw.Draw(glow, "RGBA")
    gd.ellipse((220, 520, 860, 1210), fill=(255, 201, 111, 52))
    glow = glow.filter(ImageFilter.GaussianBlur(80))
    img.alpha_composite(glow)
    body = (34, 35, 43, 245)
    d.ellipse((340, 740, 740, 1210), fill=body)
    d.ellipse((375, 560, 705, 880), fill=body)
    d.polygon([(400,620),(450,480),(500,650)], fill=body)
    d.polygon([(580,650),(635,480),(690,625)], fill=body)
    eye = (244, 210, 78, 255)
    d.ellipse((445,690,500,745), fill=eye)
    d.ellipse((580,690,635,745), fill=eye)
    d.ellipse((468,690,480,745), fill=(20,20,25,255))
    d.ellipse((603,690,615,745), fill=(20,20,25,255))
    d.arc((675,820,930,1180), 260, 80, fill=body, width=46)
    if index == 0:
        d.rounded_rectangle((150, 1280, 930, 1435), radius=42, fill=(255,255,255,35))
        d.text((540, 1358), "ELE TE SEGUE ATÉ LÁ?", anchor="mm", font=font(43), fill=(255,255,255,245))
    elif index == 2:
        d.rounded_rectangle((80, 520, 270, 1200), radius=15, fill=(226,216,194,180), outline=(255,255,255,80), width=3)
        d.ellipse((225,850,242,867), fill=(85,62,45,255))
    elif index == 3:
        d.polygon([(825,675),(790,620),(720,630),(690,690),(705,765),(825,875),(945,765),(960,690),(930,630),(860,620)], fill=(220,65,75,210))


def draw_generic_visual(img: Image.Image, job: dict, index: int):
    theme = f"{clean(job.get('tema'))} {clean(job.get('titulo'))}".lower()
    if any(k in theme for k in ("gato", "gata", "felino", "cat")):
        draw_cat_visual(img, index)
        return

    d = ImageDraw.Draw(img, "RGBA")
    glow = Image.new("RGBA", img.size, (0,0,0,0))
    gd = ImageDraw.Draw(glow, "RGBA")
    gd.ellipse((210, 520, 870, 1190), fill=(255, 208, 116, 50))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    img.alpha_composite(glow)
    d.ellipse((315, 620, 650, 955), outline=(255, 239, 190, 235), width=34)
    d.line((620, 925, 785, 1095), fill=(255, 239, 190, 235), width=42)
    d.text((480, 790), "?", anchor="mm", font=font(170), fill=(255,255,255,245))


def draw_brand(d):
    d.rounded_rectangle((55, 50, 330, 116), radius=26, fill=(8, 10, 18, 145))
    d.text((78, 83), "ZÉ CURIOSO", anchor="lm", font=font(31), fill=(255, 235, 176, 255))


def draw_scene(job: dict, scene: dict, index: int, total: int, job_dir: Path, destination: Path):
    asset = find_scene_asset(job_dir, index)
    if asset:
        img = cover_image(asset)
        shade = Image.new("RGBA", img.size, (0,0,0,0))
        sd = ImageDraw.Draw(shade, "RGBA")
        sd.rectangle((0,0,W,390), fill=(0,0,0,92))
        sd.rectangle((0,1500,W,H), fill=(0,0,0,92))
        img = Image.alpha_composite(img, shade)
    else:
        img = gradient_background(index)
        draw_generic_visual(img, job, index)

    d = ImageDraw.Draw(img, "RGBA")
    draw_brand(d)

    x0, x1 = 390, 1015
    d.rounded_rectangle((x0, 72, x1, 88), radius=8, fill=(255,255,255,32))
    progress = int(x0 + (x1-x0) * ((index+1)/total))
    d.rounded_rectangle((x0, 72, progress, 88), radius=8, fill=(255, 177, 72, 225))

    title = clean(scene.get("titulo")) or clean(job.get("titulo")) or "CURIOSIDADE"
    title = wrap(title.upper(), 22)
    d.multiline_text(
        (64, 170), title, font=font(66 if index == 0 else 58),
        fill=(255,255,255,255), spacing=10,
        stroke_width=3, stroke_fill=(0,0,0,88)
    )

    if index == 0:
        draw_mascot(img, 820, 1215, 0.62, "surprised")
        d.rounded_rectangle((58, 1285, 590, 1475), radius=44, fill=(255,248,225,238))
        hook = clean(job.get("hook")) or clean(scene.get("texto"))
        d.multiline_text((92, 1338), wrap(hook, 25), font=font(38, False), fill=(35,27,25,255), spacing=10)
        d.rounded_rectangle((70, 1510, 380, 1590), radius=28, fill=(234,104,49,242))
        d.text((225,1550), "OXENTE...", anchor="mm", font=font(35), fill=(255,255,255,255))
    elif index == 1:
        d.rounded_rectangle((70, 1280, 365, 1362), radius=28, fill=(255,177,72,232))
        d.text((217,1321), "RAPAZ...", anchor="mm", font=font(32), fill=(31,24,20,255))
    elif index == 2:
        d.rounded_rectangle((70, 1280, 500, 1362), radius=28, fill=(255,177,72,232))
        d.text((285,1321), "MAS PERA AÍ...", anchor="mm", font=font(31), fill=(31,24,20,255))
    elif index == 3:
        draw_mascot(img, 850, 1260, 0.50, "point")
        d.rounded_rectangle((70, 1275, 470, 1355), radius=28, fill=(255,177,72,232))
        d.text((270,1315), "AGORA OLHA ISSO...", anchor="mm", font=font(28), fill=(31,24,20,255))
    else:
        draw_mascot(img, 835, 1195, 0.50, "curious")
        cta = clean(job.get("cta")) or "Segue o Zé Curioso para mais curiosidades rápidas."
        d.rounded_rectangle((82, 1450, 998, 1585), radius=44, fill=(234,104,49,244))
        d.text((540, 1518), wrap(cta.upper(), 40), anchor="mm", font=font(29), fill=(255,255,255,255), align="center")

    img.convert("RGB").save(destination, quality=95)


def ass_time(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def make_ass(scenes: list[dict], durations: list[float], path: Path):
    header = """[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Caption,DejaVu Sans,48,&H00FFFFFF,&H000000FF,&H00101010,&H60000000,-1,0,0,0,100,100,0,0,3,3,0,2,72,72,120,1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"""
    lines = [header]
    t = 0.0
    for scene, duration in zip(scenes, durations):
        text = clean(scene.get("texto")) or clean(scene.get("titulo"))
        text = text.replace("{", "(").replace("}", ")")
        words = text.split()
        if len(words) > 8:
            mid = max(3, len(words)//2)
            text = " ".join(words[:mid]) + r"\N" + " ".join(words[mid:])
        margin_v = 255 if scene is scenes[-1] else 120
        lines.append(f"Dialogue: 0,{ass_time(t)},{ass_time(t+duration)},Caption,,0,0,{margin_v},,,{text}\n")
        t += duration
    path.write_text("".join(lines), encoding="utf-8")


def synthesize(script: str, voice: str, destination: Path):
    run([
        "edge-tts",
        "--voice", voice,
        "--rate=+10%",
        "--text", script,
        "--write-media", destination,
    ])


def build_video(job: dict, job_dir: Path, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_work_ze"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    script = clean(job.get("roteiro"))
    if len(script.split()) < 20:
        raise RuntimeError("Roteiro curto demais para o Zé Curioso V24.")

    scenes = [x for x in (job.get("cenas") or []) if isinstance(x, dict)]
    if len(scenes) != 5:
        raise RuntimeError("O Zé Curioso V24.1 exige exatamente 5 cenas.")

    voice = clean(job.get("voz")) or DEFAULT_VOICE
    narration = work / "narracao.mp3"
    synthesize(script, voice, narration)
    audio_seconds = ffprobe_duration(narration)

    base = max(2.8, audio_seconds / len(scenes))
    durations = [base] * len(scenes)
    total_video = sum(durations)

    scene_videos = []
    for i, scene in enumerate(scenes):
        png = work / f"scene_{i+1:02d}.png"
        draw_scene(job, scene, i, len(scenes), job_dir, png)
        mp4 = work / f"scene_{i+1:02d}.mp4"
        frames = max(1, int(math.ceil(durations[i] * FPS)))
        if i % 2 == 0:
            vf = f"zoompan=z='min(zoom+0.0008,1.065)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps={FPS}"
        else:
            vf = f"zoompan=z='1.055':x='min(iw-iw/zoom,({i+1})*on/8)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps={FPS}"
        run([
            "ffmpeg", "-y", "-loop", "1", "-i", png,
            "-vf", vf + ",format=yuv420p",
            "-t", f"{durations[i]:.3f}",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", mp4,
        ])
        scene_videos.append(mp4)

    concat_file = work / "concat.txt"
    concat_file.write_text("".join(f"file '{p.resolve()}'\n" for p in scene_videos), encoding="utf-8")
    visual = work / "visual.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", visual])

    ass = out_dir / "legendas_ze_curioso.ass"
    make_ass(scenes, durations, ass)

    final = out_dir / "anuncio_final.mp4"
    run([
        "ffmpeg", "-y",
        "-i", visual,
        "-i", narration,
        "-vf", f"ass={ass.as_posix()}",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k",
        "-shortest", final,
    ])

    shutil.copy2(work / "scene_01.png", out_dir / "capa_video.png")
    (out_dir / "roteiro_narracao.txt").write_text(script + "\n", encoding="utf-8")
    (out_dir / "curiosidade.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    diagnostics = {
        "version": "ze-curioso-v24.1",
        "tema": clean(job.get("tema")),
        "titulo": clean(job.get("titulo")),
        "voice": voice,
        "scene_count": len(scenes),
        "audio_duration_seconds": round(audio_seconds, 2),
        "planned_visual_seconds": round(total_video, 2),
        "final_exists": final.is_file(),
        "final_bytes": final.stat().st_size if final.is_file() else 0,
        "render_mode": "dynamic_topic_visuals_v24_1",
        "external_scene_assets": sum(1 for i in range(len(scenes)) if find_scene_asset(job_dir, i)),
        "mascot_strategy": "hook_mid_final",
        "cta_strategy": "final_scene_only",
    }
    (out_dir / "diagnostico_render.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Zé Curioso V24.1 renderizado: {final}", flush=True)
    return final


def main():
    if len(sys.argv) < 3:
        print("Uso: render_ze_curioso_v24.py <job_dir> <output_dir>", file=sys.stderr)
        raise SystemExit(2)

    job_dir = Path(sys.argv[1]).resolve()
    out_dir = Path(sys.argv[2]).resolve()
    source = job_dir / "curiosidade.json"
    if not source.is_file():
        raise RuntimeError(f"Arquivo ausente: {source}")
    job = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(job, dict):
        raise RuntimeError("curiosidade.json inválido.")
    build_video(job, job_dir, out_dir)


if __name__ == "__main__":
    main()
