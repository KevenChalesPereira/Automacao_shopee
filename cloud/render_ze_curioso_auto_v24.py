#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H = 1080, 1920
FPS = 30
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
DEFAULT_VOICE = "pt-BR-JulioNeural"
FALLBACK_VOICE = "pt-BR-AntonioNeural"
VOICE_CANDIDATES = [
    "pt-BR-JulioNeural",
    "pt-BR-FabioNeural",
    "pt-BR-NicolauNeural",
    "pt-BR-AntonioNeural",
]
ROOT = Path(__file__).resolve().parents[1]
MASCOT = ROOT / "assets" / "ze_curioso" / "ze_main.png"

# Zé só muda de lado entre cenas; nunca desliza no meio da fala.
SIDES = ["left", "left", "right", "right", "left"]
VOICE_STYLE = [
    ("+6%", "+3Hz"),
    ("+3%", "+1Hz"),
    ("+2%", "+0Hz"),
    ("+3%", "+1Hz"),
    ("+5%", "+2Hz"),
]


def run(cmd):
    print("[>] " + " ".join(str(x) for x in cmd), flush=True)
    r = subprocess.run([str(x) for x in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
    if r.returncode:
        print(r.stderr[-9000:], flush=True)
        raise RuntimeError(f"Comando falhou: {cmd[0]}")
    return r


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def font(size):
    try:
        return ImageFont.truetype(FONT_BOLD, size)
    except Exception:
        return ImageFont.load_default()


def ffprobe_duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path])
    try:
        return max(0.4, float(r.stdout.strip()))
    except Exception:
        return 5.0


def split_caption(text, max_words=3):
    words = clean(text).split()
    return [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]


def bubble_geometry(index):
    side = SIDES[index % len(SIDES)]
    if side == "left":
        return {
            "side": side,
            "mascot_x": -34,
            "bubble_center": (770, 1160),
        }
    return {
        "side": side,
        "mascot_x": 565,
        "bubble_center": (310, 1160),
    }


def cover(path):
    im = Image.open(path).convert("RGB")
    return ImageOps.fit(im, (W, H), method=Image.Resampling.LANCZOS).convert("RGBA")


def shade_background(img):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay, "RGBA")
    d.rectangle((0, 1600, W, H), fill=(0, 0, 0, 18))
    return Image.alpha_composite(img, overlay)


def paste_mascot(base, index):
    if not MASCOT.is_file():
        raise RuntimeError(f"Mascote final ausente: {MASCOT}")

    geom = bubble_geometry(index)
    ze = Image.open(MASCOT).convert("RGBA")
    target_h = 620
    target_w = max(1, round(ze.width * target_h / ze.height))
    ze = ze.resize((target_w, target_h), Image.Resampling.LANCZOS)

    if geom["side"] == "right":
        ze = ImageOps.mirror(ze)
    x = geom["mascot_x"]
    y = H - target_h - 62

    alpha = ze.getchannel("A")
    shadow_alpha = alpha.filter(ImageFilter.GaussianBlur(12))
    shadow = Image.new("RGBA", ze.size, (0, 0, 0, 82))
    shadow.putalpha(shadow_alpha)
    base.alpha_composite(shadow, (x + 10, y + 14))
    base.alpha_composite(ze, (x, y))


def draw_base_scene(index, job_dir, destination):
    bg = job_dir / f"scene_{index+1:02d}.jpg"
    if not bg.is_file():
        raise RuntimeError(f"Background IA ausente: {bg.name}")
    img = shade_background(cover(bg))
    paste_mascot(img, index)
    img.save(destination)


def hot_word_index(words):
    scored = []
    for i, word in enumerate(words):
        letters = re.sub(r"[^A-Za-zÀ-ÿ0-9]", "", word)
        scored.append((len(letters), i))
    return max(scored, default=(0, 0))[1]


def draw_centered_words(draw, words, y, fnt, hot, y_offset=0):
    space = draw.textlength(" ", font=fnt)
    widths = [draw.textlength(w, font=fnt) for w in words]
    total = sum(widths) + space * max(0, len(words) - 1)
    x = 300 - total / 2
    for i, (word, ww) in enumerate(zip(words, widths)):
        fill = (255, 183, 0, 255) if i == hot else (25, 25, 25, 255)
        draw.text((x, y + y_offset), word, font=fnt, fill=fill, stroke_width=1, stroke_fill=(255, 255, 255, 220))
        x += ww + space


def make_bubble_png(text, side, destination):
    # Canvas pequeno: o balão vira um sticker animado sobre o vídeo, não um slide.
    bw, bh = 600, 300
    mask = Image.new("L", (bw, bh), 0)
    m = ImageDraw.Draw(mask)
    m.ellipse((25, 28, 575, 238), fill=255)
    # Lóbulos discretos deixam a silhueta mais orgânica/comic.
    m.ellipse((70, 18, 210, 128), fill=255)
    m.ellipse((390, 18, 530, 128), fill=255)
    if side == "left":
        m.polygon([(98, 205), (18, 276), (145, 228)], fill=255)
    else:
        m.polygon([(502, 205), (582, 276), (455, 228)], fill=255)

    shadow_mask = mask.filter(ImageFilter.GaussianBlur(12))
    outline_mask = mask.filter(ImageFilter.MaxFilter(13))

    bubble = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (bw, bh), (0, 0, 0, 78))
    shadow.putalpha(shadow_mask)
    bubble.alpha_composite(shadow, (4, 8))

    outline = Image.new("RGBA", (bw, bh), (24, 24, 24, 255))
    outline.putalpha(outline_mask)
    bubble.alpha_composite(outline)

    white = Image.new("RGBA", (bw, bh), (255, 255, 255, 248))
    white.putalpha(mask)
    bubble.alpha_composite(white)

    d = ImageDraw.Draw(bubble, "RGBA")
    # Pequenos traços dão cara de sticker/TikTok sem poluir.
    accent_x = 505 if side == "left" else 82
    d.line((accent_x, 32, accent_x + (24 if side == "left" else -24), 8), fill=(255, 190, 0, 245), width=7)
    d.line((accent_x + (22 if side == "left" else -22), 50, accent_x + (55 if side == "left" else -55), 42), fill=(70, 150, 255, 235), width=6)

    words = clean(text).split()
    hot = hot_word_index(words)
    fnt = font(54 if len(" ".join(words)) <= 21 else 48)

    if len(words) <= 2:
        draw_centered_words(d, words, 112, fnt, hot)
    else:
        cut = 2 if len(words) >= 3 else 1
        top = words[:cut]
        bottom = words[cut:]
        top_hot = hot if hot < cut else -1
        bottom_hot = hot - cut if hot >= cut else -1
        draw_centered_words(d, top, 82, fnt, top_hot)
        draw_centered_words(d, bottom, 142, fnt, bottom_hot)

    bubble.save(destination)


def synth_one(text, voice, rate, pitch, destination):
    cmd = [
        "edge-tts", "--voice", voice,
        f"--rate={rate}", f"--pitch={pitch}",
        "--text", text, "--write-media", str(destination),
    ]
    print(f"[>] TTS {voice} rate={rate} pitch={pitch}", flush=True)
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")


def synthesize_scenes(scenes, requested_voice, work):
    candidates = []
    for voice in [requested_voice, *VOICE_CANDIDATES]:
        if voice and voice not in candidates:
            candidates.append(voice)

    first_text = clean(scenes[0].get("texto"))
    selected = None
    first_audio = work / "audio_scene_01.mp3"
    rate, pitch = VOICE_STYLE[0]
    for voice in candidates:
        r = synth_one(first_text, voice, rate, pitch, first_audio)
        if r.returncode == 0 and first_audio.is_file() and first_audio.stat().st_size > 1000:
            selected = voice
            print(f"[OK] Voz selecionada: {voice}", flush=True)
            break
        if first_audio.exists():
            first_audio.unlink()
        print(f"[!] Voz indisponível: {voice}", flush=True)

    if not selected:
        raise RuntimeError("Nenhuma voz pt-BR funcionou no Edge TTS.")

    audio_files = [first_audio]
    failed = False
    for i, scene in enumerate(scenes[1:], 1):
        rate, pitch = VOICE_STYLE[i]
        dest = work / f"audio_scene_{i+1:02d}.mp3"
        r = synth_one(clean(scene.get("texto")), selected, rate, pitch, dest)
        if r.returncode != 0 or not dest.is_file() or dest.stat().st_size < 1000:
            failed = True
            break
        audio_files.append(dest)

    if failed:
        # Mantém a mesma voz em todas as cenas caso uma voz alternativa oscile.
        print(f"[!] {selected} falhou no meio; regenerando tudo com {FALLBACK_VOICE}.", flush=True)
        for p in work.glob("audio_scene_*.mp3"):
            p.unlink(missing_ok=True)
        selected = FALLBACK_VOICE
        audio_files = []
        for i, scene in enumerate(scenes):
            rate, pitch = VOICE_STYLE[i]
            dest = work / f"audio_scene_{i+1:02d}.mp3"
            r = synth_one(clean(scene.get("texto")), selected, rate, pitch, dest)
            if r.returncode != 0:
                raise RuntimeError("Fallback de voz também falhou.")
            audio_files.append(dest)

    durations = [ffprobe_duration(p) for p in audio_files]
    concat = work / "audio_concat.txt"
    concat.write_text("".join(f"file '{p.resolve()}'\n" for p in audio_files), encoding="utf-8")
    narration = work / "narracao.mp3"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat, "-c:a", "libmp3lame", "-q:a", "2", narration])
    return selected, narration, durations


def chunk_durations(text, scene_duration):
    chunks = split_caption(text, 3)
    if not chunks:
        return []
    weights = [max(1, len(chunk.split())) for chunk in chunks]
    total = sum(weights)
    durations = [scene_duration * w / total for w in weights]
    return list(zip(chunks, durations))


def make_chunk_clip(base_frame, bubble_png, center, duration, destination):
    cx, cy = center
    # O fundo e o Zé ficam imóveis; só o sticker de fala entra com fade + microbounce.
    filt = (
        "[1:v]format=rgba,fade=t=in:st=0:d=0.09:alpha=1[b];"
        f"[0:v][b]overlay=x='{cx}-overlay_w/2':"
        f"y='{cy}-overlay_h/2+8*exp(-6*t)*cos(22*t)':eval=frame:shortest=1,format=yuv420p[v]"
    )
    run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", base_frame,
        "-loop", "1", "-i", bubble_png,
        "-filter_complex", filt,
        "-map", "[v]",
        "-t", f"{duration:.3f}", "-r", str(FPS), "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        destination,
    ])


def compose_cover(base_frame, bubble_png, center, destination):
    base = Image.open(base_frame).convert("RGBA")
    bubble = Image.open(bubble_png).convert("RGBA")
    cx, cy = center
    x = round(cx - bubble.width / 2)
    y = round(cy - bubble.height / 2)
    base.alpha_composite(bubble, (x, y))
    base.convert("RGB").save(destination, quality=94)


def build_video(job, job_dir, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_work_auto"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    scenes = [x for x in (job.get("cenas") or []) if isinstance(x, dict)][:5]
    if len(scenes) != 5:
        raise RuntimeError("A versão Auto espera exatamente 5 cenas.")

    requested_voice = clean(job.get("voz")) or DEFAULT_VOICE
    selected_voice, audio, scene_durations = synthesize_scenes(scenes, requested_voice, work)

    clips = []
    first_base = None
    first_bubble = None
    first_center = None

    for i, (scene, scene_duration) in enumerate(zip(scenes, scene_durations)):
        base_frame = work / f"base_scene_{i+1:02d}.png"
        draw_base_scene(i, job_dir, base_frame)
        geom = bubble_geometry(i)
        pieces = chunk_durations(scene.get("texto") or scene.get("titulo"), scene_duration)
        for j, (chunk, dur) in enumerate(pieces, 1):
            bubble_png = work / f"bubble_{i+1:02d}_{j:02d}.png"
            make_bubble_png(chunk, geom["side"], bubble_png)
            clip = work / f"clip_{i+1:02d}_{j:02d}.mp4"
            make_chunk_clip(base_frame, bubble_png, geom["bubble_center"], dur, clip)
            clips.append(clip)
            if first_base is None:
                first_base = base_frame
                first_bubble = bubble_png
                first_center = geom["bubble_center"]

    concat = work / "video_concat.txt"
    concat.write_text("".join(f"file '{p.resolve()}'\n" for p in clips), encoding="utf-8")
    visual = work / "visual.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat, "-c", "copy", visual])

    final = out_dir / "anuncio_final.mp4"
    run([
        "ffmpeg", "-y", "-i", visual, "-i", audio,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", final,
    ])

    if first_base and first_bubble and first_center:
        compose_cover(first_base, first_bubble, first_center, out_dir / "capa_video.png")

    # Mantém o arquivo esperado pelo workflow; a legenda agora é desenhada dentro do sticker animado.
    ass = out_dir / "legendas_ze_curioso.ass"
    ass.write_text("; captions baked into animated organic speech bubbles\n", encoding="utf-8")

    script = clean(job.get("roteiro"))
    (out_dir / "roteiro_narracao.txt").write_text(script + "\n", encoding="utf-8")
    (out_dir / "curiosidade.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    diag = {
        "version": "ze-curioso-mobile-organic-bubble-v5",
        "render_mode": "static_ai_background_plus_repositioned_mascot_plus_animated_organic_speech_sticker",
        "background_engine": "cloudflare_flux",
        "voice_requested": requested_voice,
        "voice_selected": selected_voice,
        "voice_scene_styles": VOICE_STYLE,
        "speech_bubble": "organic-white-oval-sticker",
        "caption_style": "3-word-highlighted-pop-bubble",
        "bubble_motion": "fade-plus-microbounce-only",
        "mascot_motion": "none-within-scene",
        "mascot_reposition": SIDES,
        "manual_background_required": False,
        "scene_count": len(scenes),
        "audio_duration_seconds": round(sum(scene_durations), 2),
        "final_exists": final.is_file(),
        "final_bytes": final.stat().st_size if final.is_file() else 0,
    }
    (out_dir / "diagnostico_render.json").write_text(json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Zé Curioso organic bubble v5 renderizado: {final}", flush=True)


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
