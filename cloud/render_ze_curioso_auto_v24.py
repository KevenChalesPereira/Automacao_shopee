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
ROOT = Path(__file__).resolve().parents[1]
MASCOT = ROOT / "assets" / "ze_curioso" / "ze_main.webp"


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
    return (chr(92) + "N").join(lines)


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
    header = """[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Caption,DejaVu Sans,58,&H00FFFFFF,&H000000FF,&H00101010,&H76000000,-1,0,0,0,100,100,0,0,1,5,1,2,78,78,185,1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"""
    lines = [header]
    t = 0.0
    for scene, dur in zip(scenes, durations):
        text = clean(scene.get("texto") or scene.get("titulo"))
        text = text.replace("{", "(").replace("}", ")")
        text = wrap(text, 31)
        lines.append(f"Dialogue: 0,{ass_time(t)},{ass_time(t+dur)},Caption,,0,0,0,,{text}\n")
        t += dur
    path.write_text("".join(lines), encoding="utf-8")


def cover(path):
    im = Image.open(path).convert("RGB")
    return ImageOps.fit(im, (W, H), method=Image.Resampling.LANCZOS).convert("RGBA")


def shade_background(img):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay, "RGBA")
    d.rectangle((0, 0, W, 300), fill=(0, 0, 0, 78))
    d.rectangle((0, 1370, W, H), fill=(0, 0, 0, 62))
    return Image.alpha_composite(img, overlay)


def paste_mascot(base, index, total):
    if not MASCOT.is_file():
        raise RuntimeError(f"Mascote final ausente: {MASCOT}")

    ze = Image.open(MASCOT).convert("RGBA")
    target_h = 820 if index == 0 else 760
    target_w = max(1, round(ze.width * target_h / ze.height))
    ze = ze.resize((target_w, target_h), Image.Resampling.LANCZOS)

    on_right = index % 2 == 0
    if on_right:
        x = W - target_w + 28
        ze = ImageOps.mirror(ze)
    else:
        x = -28
    y = H - target_h - 170

    alpha = ze.getchannel("A")
    shadow = Image.new("RGBA", ze.size, (0, 0, 0, 0))
    shadow.putalpha(alpha.filter(ImageFilter.GaussianBlur(18)))
    dark = Image.new("RGBA", ze.size, (0, 0, 0, 118))
    dark.putalpha(shadow.getchannel("A"))
    base.alpha_composite(dark, (x + 18, y + 24))
    base.alpha_composite(ze, (x, y))


def safe_title(scene, job, index):
    if index != 0:
        return ""
    title = clean(scene.get("titulo"))
    bad = {"hook", "gancho", "cena 1", "abertura", "introdução", "introducao"}
    if title.lower() in bad or len(title) < 4:
        title = clean(job.get("titulo"))
    return title


def draw_scene(job, scene, index, total, job_dir, destination):
    bg = job_dir / f"scene_{index+1:02d}.jpg"
    if not bg.is_file():
        raise RuntimeError(f"Background IA ausente: {bg.name}")

    img = shade_background(cover(bg))
    d = ImageDraw.Draw(img, "RGBA")

    headline = safe_title(scene, job, index)
    if headline:
        text = wrap(headline.upper(), 22).replace(chr(92) + "N", "\n")
        d.multiline_text(
            (540, 165), text, anchor="ma", align="center",
            font=font(66), fill=(255, 255, 255, 255), spacing=8,
            stroke_width=5, stroke_fill=(0, 0, 0, 180)
        )

    paste_mascot(img, index, total)

    if index == total - 1:
        d.rounded_rectangle((180, 1540, 900, 1635), radius=34, fill=(0, 0, 0, 165))
        d.text((540, 1587), "SEGUE O ZÉ CURIOSO", anchor="mm", font=font(39), fill=(255, 235, 165, 255))

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

    base = max(3.6, audio_seconds / len(scenes))
    durations = [base] * len(scenes)

    clips = []
    for i, scene in enumerate(scenes):
        frame = work / f"scene_{i+1:02d}.png"
        draw_scene(job, scene, i, len(scenes), job_dir, frame)
        mp4 = work / f"scene_{i+1:02d}.mp4"
        frames = int(math.ceil(durations[i] * FPS))
        zoom = "min(zoom+0.00045,1.045)" if i % 2 == 0 else "if(lte(zoom,1.0),1.04,max(1.0,zoom-0.00042))"
        run([
            "ffmpeg", "-y", "-loop", "1", "-i", frame,
            "-vf", f"zoompan=z='{zoom}':d={frames}:s=1080x1920:fps={FPS},format=yuv420p",
            "-t", f"{durations[i]:.3f}", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", mp4
        ])
        clips.append(mp4)

    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{p.resolve()}'\n" for p in clips), encoding="utf-8")
    visual = work / "visual.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat, "-c", "copy", visual])

    ass = out_dir / "legendas_ze_curioso.ass"
    make_ass(scenes, durations, ass)
    final = out_dir / "anuncio_final.mp4"
    run([
        "ffmpeg", "-y", "-i", visual, "-i", audio,
        "-vf", f"ass={ass.as_posix()}",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-shortest", final
    ])

    shutil.copy2(work / "scene_01.png", out_dir / "capa_video.png")
    (out_dir / "roteiro_narracao.txt").write_text(script + "\n", encoding="utf-8")
    (out_dir / "curiosidade.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    diag = {
        "version": "ze-curioso-mobile-final-mascot-v1",
        "render_mode": "ai_scene_plus_fixed_final_mascot",
        "background_engine": "cloudflare_flux",
        "mascot_asset": str(MASCOT.relative_to(ROOT)),
        "manual_background_required": False,
        "scene_count": len(scenes),
        "audio_duration_seconds": round(audio_seconds, 2),
        "final_exists": final.is_file(),
        "final_bytes": final.stat().st_size if final.is_file() else 0,
    }
    (out_dir / "diagnostico_render.json").write_text(json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Zé Curioso com mascote final renderizado: {final}", flush=True)


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
