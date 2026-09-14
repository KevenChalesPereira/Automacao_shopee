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
DEFAULT_VOICE = "supertonic:M4"
FALLBACK_VOICE = "pt-BR-AntonioNeural"
EDGE_VOICES = [
    "pt-BR-JulioNeural",
    "pt-BR-FabioNeural",
    "pt-BR-NicolauNeural",
    "pt-BR-AntonioNeural",
]
ROOT = Path(__file__).resolve().parents[1]
MASCOT = ROOT / "assets" / "ze_curioso" / "ze_main.png"

# Zé muda de lado apenas entre cenas.
SIDES = ["left", "left", "right", "right", "left"]

# Ritmo mais vivo sem virar locução de propaganda.
SUPER_SPEED = [1.11, 1.06, 1.02, 1.06, 1.10]
SUPER_PITCH = [1.035, 1.015, 0.995, 1.015, 1.030]
SUPER_GAIN = [1.10, 1.06, 1.03, 1.06, 1.09]

EDGE_STYLE = [
    ("+10%", "+4Hz"),
    ("+6%", "+2Hz"),
    ("+3%", "+0Hz"),
    ("+6%", "+2Hz"),
    ("+9%", "+4Hz"),
]


def run(cmd):
    print("[>] " + " ".join(str(x) for x in cmd), flush=True)
    r = subprocess.run(
        [str(x) for x in cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )
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
    r = run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ])
    try:
        return max(0.4, float(r.stdout.strip()))
    except Exception:
        return 5.0


def ffprobe_sample_rate(path):
    r = run([
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ])
    try:
        return int(r.stdout.strip())
    except Exception:
        return 24000


def performance_text(text, index):
    """Pontuação de performance só para o TTS; a legenda mantém o texto original."""
    text = clean(text)
    if index == 0:
        text = re.sub(
            r"^Se liga nessa,\s*curioso\s*:",
            "Se liga nessa, curioso!",
            text,
            flags=re.I,
        )
        if not re.search(r"[!?]$", text):
            text += "!"
    elif index == 4:
        text = text.replace(
            "Agora você sabe. Bora pra próxima com o Zé!",
            "Agora você sabe... Bora pra próxima com o Zé!",
        )
    return text


def caption_chunks(text):
    """Blocos curtos e irregulares: evita cara de slide e acompanha melhor a fala."""
    words = clean(text).split()
    chunks = []
    i = 0
    while i < len(words):
        remain = len(words) - i
        size = 2 if remain in (2, 4, 5) else 3
        if remain >= 7 and i % 2:
            size = 4
        size = min(size, remain)
        chunks.append(" ".join(words[i:i + size]))
        i += size
    return chunks


def bubble_geometry(index):
    side = SIDES[index % len(SIDES)]
    # Balão mais perto da cabeça/boca do Zé.
    if side == "left":
        return {
            "side": side,
            "mascot_x": -38,
            "bubble_center": (758, 1185),
        }
    return {
        "side": side,
        "mascot_x": 568,
        "bubble_center": (322, 1185),
    }


def cover(path):
    im = Image.open(path).convert("RGB")
    return ImageOps.fit(im, (W, H), method=Image.Resampling.LANCZOS).convert("RGBA")


def shade_background(img):
    # Vinheta mínima apenas no rodapé para destacar o personagem sem esconder o fundo.
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay, "RGBA")
    d.rectangle((0, 1620, W, H), fill=(0, 0, 0, 16))
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


STOPWORDS = {
    "a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "um", "uma",
    "que", "pra", "para", "por", "com", "se", "na", "no", "nas", "nos", "ele", "ela",
    "você", "isso", "essa", "esse", "mas", "ou", "ao", "até",
}


def hot_word_index(words):
    scored = []
    for i, word in enumerate(words):
        letters = re.sub(r"[^A-Za-zÀ-ÿ0-9]", "", word)
        score = len(letters)
        if letters.lower() in STOPWORDS:
            score -= 8
        scored.append((score, i))
    return max(scored, default=(0, 0))[1]


def text_width(draw, words, fnt):
    space = draw.textlength(" ", font=fnt)
    widths = [draw.textlength(w, font=fnt) for w in words]
    return sum(widths) + space * max(0, len(words) - 1), widths, space


def draw_centered_words(draw, words, y, fnt, hot, width):
    total, widths, space = text_width(draw, words, fnt)
    x = width / 2 - total / 2
    for i, (word, ww) in enumerate(zip(words, widths)):
        is_hot = i == hot
        fill = (255, 177, 0, 255) if is_hot else (24, 24, 24, 255)
        stroke = 2 if is_hot else 1
        draw.text(
            (x, y),
            word,
            font=fnt,
            fill=fill,
            stroke_width=stroke,
            stroke_fill=(255, 255, 255, 235),
        )
        x += ww + space


def make_bubble_png(text, side, destination):
    # Sticker mais compacto, assimétrico e orgânico.
    bw, bh = 550, 258
    mask = Image.new("L", (bw, bh), 0)
    m = ImageDraw.Draw(mask)

    m.ellipse((20, 26, 530, 218), fill=255)
    m.ellipse((55, 15, 180, 118), fill=255)
    m.ellipse((365, 14, 500, 122), fill=255)
    m.ellipse((155, 4, 392, 112), fill=255)

    if side == "left":
        m.polygon([(84, 192), (18, 247), (126, 212)], fill=255)
    else:
        m.polygon([(466, 192), (532, 247), (424, 212)], fill=255)

    shadow_mask = mask.filter(ImageFilter.GaussianBlur(10))
    outline_mask = mask.filter(ImageFilter.MaxFilter(11))

    bubble = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))

    shadow = Image.new("RGBA", (bw, bh), (0, 0, 0, 66))
    shadow.putalpha(shadow_mask)
    bubble.alpha_composite(shadow, (3, 7))

    outline = Image.new("RGBA", (bw, bh), (20, 20, 20, 245))
    outline.putalpha(outline_mask)
    bubble.alpha_composite(outline)

    white = Image.new("RGBA", (bw, bh), (255, 255, 255, 246))
    white.putalpha(mask)
    bubble.alpha_composite(white)

    d = ImageDraw.Draw(bubble, "RGBA")

    # Pequenos traços de energia dão cara de sticker sem ocupar o vídeo.
    accent_x = 470 if side == "left" else 78
    direction = 1 if side == "left" else -1
    d.line(
        (accent_x, 34, accent_x + 23 * direction, 8),
        fill=(255, 177, 0, 245),
        width=7,
    )
    d.line(
        (accent_x + 20 * direction, 51, accent_x + 50 * direction, 43),
        fill=(57, 151, 255, 235),
        width=6,
    )

    words = clean(text).split()
    hot = hot_word_index(words)
    joined = " ".join(words)
    fnt = font(52 if len(joined) <= 21 else 46)

    if len(words) <= 2:
        draw_centered_words(d, words, 101, fnt, hot, bw)
    else:
        cut = 2 if len(words) <= 3 else math.ceil(len(words) / 2)
        top = words[:cut]
        bottom = words[cut:]
        draw_centered_words(d, top, 67, fnt, hot if hot < cut else -1, bw)
        draw_centered_words(
            d, bottom, 127, fnt, hot - cut if hot >= cut else -1, bw
        )

    bubble.save(destination)


def shape_supertonic_audio(source, destination, index):
    """Dá leve variação de pitch/energia preservando a duração."""
    sr = ffprobe_sample_rate(source)
    pitch = SUPER_PITCH[index]
    tempo_comp = 1.0 / pitch
    gain = SUPER_GAIN[index]

    filt = (
        f"asetrate={sr}*{pitch:.5f},"
        f"aresample={sr},"
        f"atempo={tempo_comp:.5f},"
        f"volume={gain:.3f},"
        "alimiter=limit=0.95"
    )
    run([
        "ffmpeg", "-y", "-i", source,
        "-af", filt,
        "-c:a", "pcm_s16le",
        destination,
    ])


def synthesize_supertonic(scenes, requested_voice, work):
    voice_name = "M4"
    if requested_voice.startswith("supertonic:"):
        voice_name = requested_voice.split(":", 1)[1].strip() or "M4"

    print(f"[>] Tentando Supertonic 3 voz {voice_name}...", flush=True)

    try:
        from supertonic import TTS

        tts = TTS(auto_download=True)
        style = tts.get_voice_style(voice_name=voice_name)

        audio_files = []
        for i, scene in enumerate(scenes):
            raw = work / f"audio_scene_{i+1:02d}_raw.wav"
            dest = work / f"audio_scene_{i+1:02d}.wav"

            wav, _ = tts.synthesize(
                text=performance_text(scene.get("texto"), i),
                voice_style=style,
                total_steps=12,
                speed=SUPER_SPEED[i],
                max_chunk_length=300,
                silence_duration=0.06,
                lang="pt",
                verbose=False,
            )
            tts.save_audio(wav, str(raw))

            if not raw.is_file() or raw.stat().st_size < 1000:
                raise RuntimeError(f"Supertonic não gerou {raw.name}")

            shape_supertonic_audio(raw, dest, i)
            audio_files.append(dest)

        durations = [ffprobe_duration(p) for p in audio_files]

        concat = work / "audio_concat_supertonic.txt"
        concat.write_text(
            "".join(f"file '{p.resolve()}'\n" for p in audio_files),
            encoding="utf-8",
        )

        narration = work / "narracao.wav"
        run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", concat,
            "-af", "loudnorm=I=-16:LRA=7:TP=-1.5",
            "-c:a", "pcm_s16le",
            narration,
        ])

        print(f"[OK] Supertonic expressivo ativo: {voice_name}", flush=True)
        return f"supertonic:{voice_name}", narration, durations

    except Exception as exc:
        print(f"[!] Supertonic falhou; fallback Edge: {exc}", flush=True)
        return None


def synth_edge_one(text, voice, rate, pitch, destination):
    cmd = [
        "edge-tts",
        "--voice", voice,
        f"--rate={rate}",
        f"--pitch={pitch}",
        "--text", text,
        "--write-media", str(destination),
    ]
    print(f"[>] Edge TTS {voice} rate={rate} pitch={pitch}", flush=True)
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )


def synthesize_edge(scenes, work):
    selected = None
    audio_files = []

    for voice in EDGE_VOICES:
        test = work / "edge_test.mp3"
        rate, pitch = EDGE_STYLE[0]
        r = synth_edge_one(
            performance_text(scenes[0].get("texto"), 0),
            voice,
            rate,
            pitch,
            test,
        )
        if r.returncode == 0 and test.is_file() and test.stat().st_size > 1000:
            selected = voice
            test.unlink(missing_ok=True)
            break
        test.unlink(missing_ok=True)

    if not selected:
        selected = FALLBACK_VOICE

    for i, scene in enumerate(scenes):
        rate, pitch = EDGE_STYLE[i]
        dest = work / f"audio_scene_{i+1:02d}.mp3"
        r = synth_edge_one(
            performance_text(scene.get("texto"), i),
            selected,
            rate,
            pitch,
            dest,
        )
        if r.returncode != 0:
            raise RuntimeError(f"Edge TTS falhou na cena {i+1}.")
        audio_files.append(dest)

    durations = [ffprobe_duration(p) for p in audio_files]

    concat = work / "audio_concat_edge.txt"
    concat.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in audio_files),
        encoding="utf-8",
    )

    narration = work / "narracao.mp3"
    run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat,
        "-af", "loudnorm=I=-16:LRA=7:TP=-1.5",
        "-c:a", "libmp3lame", "-q:a", "2",
        narration,
    ])
    return selected, narration, durations


def synthesize_scenes(scenes, requested_voice, work):
    result = synthesize_supertonic(scenes, requested_voice, work)
    if result:
        return result
    return synthesize_edge(scenes, work)


def chunk_durations(text, scene_duration):
    chunks = caption_chunks(text)
    if not chunks:
        return []

    # Duração ponderada por caracteres dá sincronização mais natural que só nº de palavras.
    weights = [max(2, len(re.sub(r"\s+", "", chunk))) for chunk in chunks]
    total = sum(weights)

    pairs = []
    for chunk, weight in zip(chunks, weights):
        pairs.append((chunk, scene_duration * weight / total))
    return pairs


def make_chunk_clip(base_frame, bubble_png, center, duration, destination):
    cx, cy = center

    # Só o sticker mexe: fade + micro bounce de entrada, depois fica parado.
    filt = (
        "[1:v]format=rgba,"
        "fade=t=in:st=0:d=0.08:alpha=1[b];"
        f"[0:v][b]overlay="
        f"x='{cx}-overlay_w/2':"
        f"y='{cy}-overlay_h/2+6*exp(-7*t)*cos(24*t)':"
        "eval=frame:shortest=1,"
        "format=yuv420p[v]"
    )

    run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", base_frame,
        "-loop", "1", "-i", bubble_png,
        "-filter_complex", filt,
        "-map", "[v]",
        "-t", f"{duration:.3f}",
        "-r", str(FPS),
        "-an",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
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

    scenes = [
        x for x in (job.get("cenas") or [])
        if isinstance(x, dict)
    ][:5]

    if len(scenes) != 5:
        raise RuntimeError("A versão Auto espera exatamente 5 cenas.")

    requested_voice = clean(job.get("voz")) or DEFAULT_VOICE
    selected_voice, audio, scene_durations = synthesize_scenes(
        scenes, requested_voice, work
    )

    clips = []
    first_base = first_bubble = first_center = None

    for i, (scene, scene_duration) in enumerate(zip(scenes, scene_durations)):
        base_frame = work / f"base_scene_{i+1:02d}.png"
        draw_base_scene(i, job_dir, base_frame)

        geom = bubble_geometry(i)
        text = scene.get("texto") or scene.get("titulo")

        for j, (chunk, dur) in enumerate(
            chunk_durations(text, scene_duration),
            1,
        ):
            bubble_png = work / f"bubble_{i+1:02d}_{j:02d}.png"
            make_bubble_png(chunk, geom["side"], bubble_png)

            clip = work / f"clip_{i+1:02d}_{j:02d}.mp4"
            make_chunk_clip(
                base_frame,
                bubble_png,
                geom["bubble_center"],
                dur,
                clip,
            )
            clips.append(clip)

            if first_base is None:
                first_base = base_frame
                first_bubble = bubble_png
                first_center = geom["bubble_center"]

    concat = work / "video_concat.txt"
    concat.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in clips),
        encoding="utf-8",
    )

    visual = work / "visual.mp4"
    run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat,
        "-c", "copy",
        visual,
    ])

    final = out_dir / "anuncio_final.mp4"
    run([
        "ffmpeg", "-y",
        "-i", visual,
        "-i", audio,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "160k",
        "-shortest",
        final,
    ])

    if first_base and first_bubble and first_center:
        compose_cover(
            first_base,
            first_bubble,
            first_center,
            out_dir / "capa_video.png",
        )

    (out_dir / "legendas_ze_curioso.ass").write_text(
        "; captions baked into animated organic speech bubbles\n",
        encoding="utf-8",
    )

    script = clean(job.get("roteiro"))
    (out_dir / "roteiro_narracao.txt").write_text(
        script + "\n",
        encoding="utf-8",
    )

    (out_dir / "curiosidade.json").write_text(
        json.dumps(job, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    diag = {
        "version": "ze-curioso-mobile-expressive-v7",
        "render_mode": "static_ai_background_plus_repositioned_mascot_plus_dynamic_speech_sticker",
        "background_engine": "cloudflare_flux",
        "voice_requested": requested_voice,
        "voice_selected": selected_voice,
        "supertonic_speed": SUPER_SPEED,
        "supertonic_pitch": SUPER_PITCH,
        "speech_bubble": "compact-organic-white-sticker",
        "caption_style": "2-4-word-highlighted-tiktok-bubble",
        "bubble_motion": "fade-plus-subtle-microbounce-only",
        "mascot_motion": "none-within-scene",
        "mascot_reposition": SIDES,
        "manual_background_required": False,
        "scene_count": len(scenes),
        "audio_duration_seconds": round(sum(scene_durations), 2),
        "final_exists": final.is_file(),
        "final_bytes": final.stat().st_size if final.is_file() else 0,
    }

    (out_dir / "diagnostico_render.json").write_text(
        json.dumps(diag, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        f"[OK] Zé Curioso expressive v7 renderizado: {final}",
        flush=True,
    )


def main():
    if len(sys.argv) < 3:
        raise SystemExit(
            "Uso: render_ze_curioso_auto_v24.py <job_dir> <output_dir>"
        )

    job_dir = Path(sys.argv[1]).resolve()
    out_dir = Path(sys.argv[2]).resolve()

    source = job_dir / "curiosidade.json"
    job = json.loads(source.read_text(encoding="utf-8"))

    build_video(job, job_dir, out_dir)


if __name__ == "__main__":
    main()
