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
DEFAULT_VOICE = "pt-BR-AntonioNeural"
ROOT = Path(__file__).resolve().parents[1]
MASCOT = ROOT / "assets" / "ze_curioso" / "ze_main.png"

# Zé troca de lado só algumas vezes; não se move dentro da cena.
SIDES = ["left", "left", "right", "right", "left"]


def run(cmd):
    print("[>] " + " ".join(str(x) for x in cmd), flush=True)
    r = subprocess.run([str(x) for x in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
    if r.returncode:
        print(r.stderr[-9000:], flush=True)
        raise RuntimeError(f"Comando falhou: {cmd[0]}")
    return r


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


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


def split_caption(text, max_words=4):
    words = clean(text).split()
    return [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]


def bubble_geometry(index):
    side = SIDES[index % len(SIDES)]
    if side == "left":
        return {
            "side": side,
            "mascot_x": -30,
            "bubble": (430, 1040, 1020, 1250),
            "text_pos": (725, 1145),
            "tail": [(450, 1185), (344, 1240), (435, 1125)],
        }
    return {
        "side": side,
        "mascot_x": 565,
        "bubble": (60, 1040, 650, 1250),
        "text_pos": (355, 1145),
        "tail": [(630, 1185), (738, 1240), (645, 1125)],
    }


def escape_ass(text):
    return clean(text).replace("{", "(").replace("}", ")")


def highlight_chunk(chunk):
    words = escape_ass(chunk).split()
    if not words:
        return ""
    # Destaca a palavra visualmente mais forte sem depender de IA extra.
    candidates = [(len(re.sub(r"[^A-Za-zÀ-ÿ0-9]", "", w)), i) for i, w in enumerate(words)]
    _, hot = max(candidates, default=(0, 0))
    out = []
    for i, word in enumerate(words):
        if i == hot:
            out.append(r"{\c&H0000D7FF&}" + word + r"{\c&H00FFFFFF&}")
        else:
            out.append(word)
    # 4 palavras normalmente cabem em 1–2 linhas; quebra no meio para leitura rápida.
    if len(out) >= 4:
        return " ".join(out[:2]) + r"\N" + " ".join(out[2:])
    if len(out) == 3:
        return " ".join(out[:2]) + r"\N" + out[2]
    return " ".join(out)


def make_ass(scenes, durations, path):
    header = """[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Bubble,DejaVu Sans,47,&H00FFFFFF,&H0000D7FF,&H00101010,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,5,0,0,0,1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"""
    lines = [header]
    t = 0.0
    for scene_index, (scene, dur) in enumerate(zip(scenes, durations)):
        chunks = split_caption(scene.get("texto") or scene.get("titulo"), 4)
        if not chunks:
            t += dur
            continue
        weights = [max(1, len(c.split())) for c in chunks]
        total = sum(weights)
        local = t
        x, y = bubble_geometry(scene_index)["text_pos"]
        for idx, (chunk, weight) in enumerate(zip(chunks, weights)):
            seg = dur * weight / total
            end = t + dur if idx == len(chunks) - 1 else local + seg
            text = highlight_chunk(chunk)
            # Pop curto estilo TikTok; texto troca rápido dentro do mesmo balão.
            tags = rf"{{\an5\pos({x},{y})\fscx82\fscy82\t(0,120,\fscx100\fscy100)\fad(45,45)}}"
            lines.append(f"Dialogue: 0,{ass_time(local)},{ass_time(end)},Bubble,,0,0,0,,{tags}{text}\n")
            local = end
        t += dur
    path.write_text("".join(lines), encoding="utf-8")


def cover(path):
    im = Image.open(path).convert("RGB")
    return ImageOps.fit(im, (W, H), method=Image.Resampling.LANCZOS).convert("RGBA")


def shade_background(img):
    # Só um leve degradê inferior: o background precisa continuar aparecendo.
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay, "RGBA")
    d.rectangle((0, 1510, W, H), fill=(0, 0, 0, 30))
    return Image.alpha_composite(img, overlay)


def paste_mascot(base, index):
    if not MASCOT.is_file():
        raise RuntimeError(f"Mascote final ausente: {MASCOT}")

    geom = bubble_geometry(index)
    ze = Image.open(MASCOT).convert("RGBA")
    target_h = 630
    target_w = max(1, round(ze.width * target_h / ze.height))
    ze = ze.resize((target_w, target_h), Image.Resampling.LANCZOS)

    if geom["side"] == "right":
        ze = ImageOps.mirror(ze)
    x = geom["mascot_x"]
    y = H - target_h - 70

    alpha = ze.getchannel("A")
    shadow_alpha = alpha.filter(ImageFilter.GaussianBlur(14))
    shadow = Image.new("RGBA", ze.size, (0, 0, 0, 92))
    shadow.putalpha(shadow_alpha)
    base.alpha_composite(shadow, (x + 12, y + 16))
    base.alpha_composite(ze, (x, y))


def draw_speech_bubble(img, index):
    geom = bubble_geometry(index)
    d = ImageDraw.Draw(img, "RGBA")
    x1, y1, x2, y2 = geom["bubble"]

    # Balão menor, escuro/translúcido, para não esconder o background.
    d.rounded_rectangle((x1 + 8, y1 + 10, x2 + 8, y2 + 10), radius=38, fill=(0, 0, 0, 70))
    d.rounded_rectangle((x1, y1, x2, y2), radius=38, fill=(18, 18, 18, 205), outline=(255, 255, 255, 215), width=3)
    d.polygon(geom["tail"], fill=(18, 18, 18, 205))
    d.line(geom["tail"], fill=(255, 255, 255, 215), width=3, joint="curve")

    # Três pontinhos pequenos lembrando 💬 sem ocupar espaço.
    dot_y = y1 + 28
    dot_start = x1 + 34 if geom["side"] == "left" else x2 - 82
    for i in range(3):
        cx = dot_start + i * 20
        d.ellipse((cx - 4, dot_y - 4, cx + 4, dot_y + 4), fill=(255, 215, 0, 230))


def draw_scene(scene, index, job_dir, destination):
    bg = job_dir / f"scene_{index+1:02d}.jpg"
    if not bg.is_file():
        raise RuntimeError(f"Background IA ausente: {bg.name}")

    img = shade_background(cover(bg))
    paste_mascot(img, index)
    draw_speech_bubble(img, index)
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
        draw_scene(scene, i, job_dir, frame)
        mp4 = work / f"scene_{i+1:02d}.mp4"
        # Sem zoompan: Zé e balão ficam parados; só mudam de posição entre cenas.
        run([
            "ffmpeg", "-y", "-loop", "1", "-i", frame,
            "-vf", f"fps={FPS},format=yuv420p",
            "-t", f"{durations[i]:.3f}", "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", mp4
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
        "version": "ze-curioso-mobile-tiktok-bubble-v3",
        "render_mode": "static_ai_background_plus_repositioned_mascot_plus_dynamic_speech_bubble",
        "background_engine": "cloudflare_flux",
        "mascot_asset": str(MASCOT.relative_to(ROOT)),
        "speech_bubble": True,
        "caption_style": "4-word-tiktok-pop-with-highlight",
        "mascot_motion": "none-within-scene",
        "mascot_reposition": SIDES,
        "manual_background_required": False,
        "scene_count": len(scenes),
        "audio_duration_seconds": round(audio_seconds, 2),
        "final_exists": final.is_file(),
        "final_bytes": final.stat().st_size if final.is_file() else 0,
    }
    (out_dir / "diagnostico_render.json").write_text(json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Zé Curioso TikTok bubble v3 renderizado: {final}", flush=True)


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
