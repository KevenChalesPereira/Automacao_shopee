#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

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
        ((15, 24, 52), (46, 91, 155), (255, 161, 67)),
        ((35, 16, 52), (111, 43, 139), (246, 119, 78)),
        ((14, 49, 45), (28, 104, 89), (239, 177, 74)),
        ((52, 28, 18), (130, 70, 35), (250, 182, 68)),
        ((20, 32, 66), (53, 100, 170), (119, 75, 177)),
    ]
    top, mid, accent = palettes[index % len(palettes)]
    img = Image.new("RGB", (W, H), top)
    px = img.load()
    for y in range(H):
        q = y / max(1, H - 1)
        if q < 0.65:
            z = q / 0.65
            color = tuple(int(top[i] * (1-z) + mid[i] * z) for i in range(3))
        else:
            z = (q - 0.65) / 0.35
            color = tuple(int(mid[i] * (1-z) + accent[i] * z) for i in range(3))
        for x in range(W):
            px[x, y] = color

    glows = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glows, "RGBA")
    gd.ellipse((-250, -180, 560, 650), fill=(255, 255, 255, 35))
    gd.ellipse((560, 260, 1380, 1120), fill=(255, 220, 130, 45))
    gd.ellipse((80, 1120, 1030, 2050), fill=(255, 255, 255, 24))
    glows = glows.filter(ImageFilter.GaussianBlur(110))
    return Image.alpha_composite(img.convert("RGBA"), glows)


def draw_hat(draw: ImageDraw.ImageDraw, cx: int, cy: int):
    draw.ellipse((cx-155, cy-30, cx+155, cy+48), fill=(191, 143, 72, 255), outline=(86, 58, 26, 255), width=5)
    draw.rounded_rectangle((cx-100, cy-105, cx+100, cy+24), radius=36, fill=(205, 157, 82, 255), outline=(86, 58, 26, 255), width=5)
    for x in range(cx-76, cx+78, 34):
        draw.ellipse((x-6, cy-57, x+6, cy-45), fill=(75, 49, 21, 220))


def draw_mascot(base: Image.Image, x: int, y: int, scale: float = 1.0):
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")
    cx = int(x)
    cy = int(y)
    s = scale

    # corpo / camisa branca
    d.rounded_rectangle(
        (cx-int(150*s), cy+int(120*s), cx+int(150*s), cy+int(450*s)),
        radius=int(70*s),
        fill=(245, 245, 240, 255),
        outline=(26, 28, 35, 120),
        width=max(2, int(5*s)),
    )
    # gravata vermelha
    d.polygon([
        (cx, cy+int(150*s)),
        (cx-int(32*s), cy+int(208*s)),
        (cx-int(18*s), cy+int(335*s)),
        (cx, cy+int(380*s)),
        (cx+int(18*s), cy+int(335*s)),
        (cx+int(32*s), cy+int(208*s)),
    ], fill=(202, 42, 48, 255))

    # pescoço + rosto
    skin = (196, 136, 92, 255)
    d.rectangle((cx-int(38*s), cy+int(60*s), cx+int(38*s), cy+int(145*s)), fill=skin)
    d.ellipse((cx-int(125*s), cy-int(145*s), cx+int(125*s), cy+int(115*s)), fill=skin, outline=(91, 53, 34, 180), width=max(2, int(4*s)))

    # cabelo, sobrancelhas, olhos
    d.arc((cx-int(110*s), cy-int(140*s), cx+int(110*s), cy-int(10*s)), 185, 355, fill=(48, 31, 25, 255), width=max(4, int(18*s)))
    d.line((cx-int(72*s), cy-int(44*s), cx-int(25*s), cy-int(50*s)), fill=(54, 35, 27, 255), width=max(2, int(6*s)))
    d.line((cx+int(25*s), cy-int(50*s), cx+int(72*s), cy-int(44*s)), fill=(54, 35, 27, 255), width=max(2, int(6*s)))
    d.ellipse((cx-int(62*s), cy-int(32*s), cx-int(40*s), cy-int(10*s)), fill=(25, 25, 30, 255))
    d.ellipse((cx+int(40*s), cy-int(32*s), cx+int(62*s), cy-int(10*s)), fill=(25, 25, 30, 255))
    # nariz / sorriso / bigode discreto
    d.line((cx, cy-int(2*s), cx-int(7*s), cy+int(36*s), cx+int(5*s), cy+int(42*s)), fill=(113, 67, 48, 220), width=max(2, int(4*s)))
    d.arc((cx-int(60*s), cy+int(30*s), cx+int(60*s), cy+int(105*s)), 18, 162, fill=(95, 45, 40, 255), width=max(2, int(5*s)))
    d.arc((cx-int(70*s), cy+int(15*s), cx-int(2*s), cy+int(70*s)), 210, 340, fill=(56, 36, 29, 200), width=max(2, int(4*s)))
    d.arc((cx+int(2*s), cy+int(15*s), cx+int(70*s), cy+int(70*s)), 200, 330, fill=(56, 36, 29, 200), width=max(2, int(4*s)))

    # chapéu
    temp = Image.new("RGBA", base.size, (0, 0, 0, 0))
    td = ImageDraw.Draw(temp, "RGBA")
    draw_hat(td, cx, cy-int(120*s))
    if s != 1.0:
        # draw_hat is used at the chosen location; scaling visual is already dominated by body size.
        pass
    layer = Image.alpha_composite(layer, temp)

    # braço apontando para conteúdo
    d = ImageDraw.Draw(layer, "RGBA")
    d.line((cx+int(115*s), cy+int(210*s), cx+int(250*s), cy+int(145*s)), fill=skin, width=max(12, int(34*s)))
    d.ellipse((cx+int(230*s), cy+int(118*s), cx+int(282*s), cy+int(170*s)), fill=skin)
    base.alpha_composite(layer)


def draw_scene(job: dict, scene: dict, index: int, total: int, destination: Path):
    img = gradient_background(index)
    d = ImageDraw.Draw(img, "RGBA")

    brand_font = font(38)
    d.rounded_rectangle((58, 56, 410, 126), radius=28, fill=(10, 12, 20, 165))
    d.text((82, 89), "ZÉ CURIOSO", anchor="lm", font=brand_font, fill=(255, 239, 191, 255))

    # contador visual
    d.rounded_rectangle((886, 62, 1026, 122), radius=25, fill=(255, 255, 255, 42))
    d.text((956, 92), f"{index+1}/{total}", anchor="mm", font=font(28), fill=(255, 255, 255, 230))

    scene_title = clean(scene.get("titulo")) or clean(job.get("titulo")) or "CURIOSIDADE"
    title_text = wrap(scene_title.upper(), 22)
    d.multiline_text((70, 225), title_text, font=font(72), fill=(255, 255, 255, 255), spacing=12, stroke_width=2, stroke_fill=(0, 0, 0, 60))

    # painel do fato
    panel = (70, 530, 1010, 1115)
    d.rounded_rectangle(panel, radius=54, fill=(9, 13, 25, 170), outline=(255, 255, 255, 50), width=3)
    fact_text = wrap(clean(scene.get("texto")) or clean(job.get("hook")), 31)
    d.multiline_text((118, 615), fact_text, font=font(52, bold=False), fill=(250, 251, 255, 255), spacing=18)

    draw_mascot(img, 780, 1320, 0.82)

    # balão curto do Zé
    bubble = (80, 1260, 610, 1575)
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle(bubble, radius=48, fill=(255, 248, 225, 245))
    d.polygon([(590, 1460), (680, 1505), (592, 1390)], fill=(255, 248, 225, 245))
    phrases = ["Oxente...", "Rapaz...", "Mas pera aí...", "Agora olha isso...", "Curioso, né?"]
    d.multiline_text((125, 1368), wrap(phrases[index % len(phrases)], 18), font=font(48), fill=(35, 27, 25, 255), spacing=8)

    # faixa inferior
    footer = clean(job.get("cta")) or "Segue o Zé Curioso para mais curiosidades."
    d.rounded_rectangle((80, 1715, 1000, 1845), radius=42, fill=(5, 8, 16, 180))
    d.text((540, 1780), footer, anchor="mm", font=font(30), fill=(255, 255, 255, 238))

    img.convert("RGB").save(destination, quality=95)


def ass_time(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def make_ass(job: dict, scenes: list[dict], durations: list[float], path: Path):
    header = """[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Caption,DejaVu Sans,52,&H00FFFFFF,&H000000FF,&H00101010,&H88000000,-1,0,0,0,100,100,0,0,1,4,1,2,80,80,165,1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"""
    lines = [header]
    t = 0.0
    for scene, duration in zip(scenes, durations):
        text = clean(scene.get("texto")) or clean(scene.get("titulo"))
        text = text.replace("{", "(").replace("}", ")")
        lines.append(
            f"Dialogue: 0,{ass_time(t)},{ass_time(t+duration)},Caption,,0,0,0,,{text}\n"
        )
        t += duration
    path.write_text("".join(lines), encoding="utf-8")


def synthesize(script: str, voice: str, destination: Path):
    run([
        "edge-tts",
        "--voice", voice,
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

    scenes = job.get("cenas") or []
    scenes = [x for x in scenes if isinstance(x, dict)]
    if len(scenes) < 3:
        raise RuntimeError("O job precisa de pelo menos 3 cenas estruturadas.")
    scenes = scenes[:7]

    voice = clean(job.get("voz")) or DEFAULT_VOICE
    narration = work / "narracao.mp3"
    synthesize(script, voice, narration)
    audio_seconds = ffprobe_duration(narration)

    # Mantém cenas com tempo mínimo legível e aproxima o vídeo da narração.
    min_scene = 2.4
    base = max(min_scene, audio_seconds / len(scenes))
    durations = [base] * len(scenes)
    total_video = sum(durations)

    scene_videos = []
    for i, scene in enumerate(scenes):
        png = work / f"scene_{i+1:02d}.png"
        draw_scene(job, scene, i, len(scenes), png)
        mp4 = work / f"scene_{i+1:02d}.mp4"
        frames = max(1, int(math.ceil(durations[i] * FPS)))
        zoom = "min(zoom+0.00055,1.055)" if i % 2 == 0 else "if(lte(zoom,1.0),1.055,max(1.0,zoom-0.00055))"
        run([
            "ffmpeg", "-y", "-loop", "1", "-i", png,
            "-vf", f"zoompan=z='{zoom}':d={frames}:s=1080x1920:fps={FPS},format=yuv420p",
            "-t", f"{durations[i]:.3f}",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", mp4,
        ])
        scene_videos.append(mp4)

    concat_file = work / "concat.txt"
    concat_file.write_text("".join(f"file '{p.resolve()}'\n" for p in scene_videos), encoding="utf-8")
    visual = work / "visual.mp4"
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file,
        "-c", "copy", visual,
    ])

    ass = out_dir / "legendas_ze_curioso.ass"
    make_ass(job, scenes, durations, ass)

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

    # Capa: usa a primeira cena.
    shutil.copy2(work / "scene_01.png", out_dir / "capa_video.png")
    (out_dir / "roteiro_narracao.txt").write_text(script + "\n", encoding="utf-8")
    (out_dir / "curiosidade.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    diagnostics = {
        "version": "ze-curioso-v24",
        "tema": clean(job.get("tema")),
        "titulo": clean(job.get("titulo")),
        "voice": voice,
        "scene_count": len(scenes),
        "audio_duration_seconds": round(audio_seconds, 2),
        "planned_visual_seconds": round(total_video, 2),
        "final_exists": final.is_file(),
        "final_bytes": final.stat().st_size if final.is_file() else 0,
        "render_mode": "procedural_mascot_motion",
    }
    (out_dir / "diagnostico_render.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Zé Curioso V24 renderizado: {final}", flush=True)
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
