from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import ze_postavel_woodfrog_voice_v6_3_calm as v63

v62 = v63.v62
v6 = v63.v6
cont = v63.cont
v4 = v63.v4
card = cont.card

POST = cont.POST
AUDIO = cont.AUDIO
SCENES = cont.SCENES
VIDEO = cont.VIDEO
BUBBLE_FRAMES = cont.BUBBLE_FRAMES
FONT_BOLD = cont.FONT_BOLD
W, H = cont.W, cont.H

# Mantém toda a leitura calma da V6.3. SOMENTE a assinatura ganha presença.
v6.VOICE_CONTROL = (
    v6.VOICE_CONTROL
    + " Keep the body of the narration calm, passive, ordinary and explanatory."
    + " ONLY the final channel signature may become slightly more present and memorable."
    + " On 'Zé Curioso', sound clear and confidently identified."
    + " On 'parece mentira', use a small natural lift of interest."
    + " On 'mas é real', land firmly with a natural downward cadence."
    + " The sign-off should have a little more energy than the sentence before it, but never sound shouted, theatrical, urgent, promotional or like an announcer."
)

WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9'-]+", re.UNICODE)


def expected_word_rows() -> list[dict]:
    rows: list[dict] = []
    for block in v62.FINAL_BLOCKS:
        for display in WORD_RE.findall(block["text"]):
            norm = v4.words_from_text(display)
            if not norm:
                continue
            rows.append({
                "scene": block["scene"],
                "block": block["block"],
                "display": display,
                "norm": norm[0],
            })
    return rows


def build_word_timing(words: list[dict]) -> tuple[list[dict], float]:
    expected_rows = expected_word_rows()
    expected = [x["norm"] for x in expected_rows]
    actual = [x["norm"] for x in words]
    mapping, ratio = v4.align_tokens(expected, actual)
    duration = cont.probe_duration(AUDIO / "narration_continuous.wav")

    starts: list[float | None] = [None] * len(expected_rows)
    ends: list[float | None] = [None] * len(expected_rows)
    for i, actual_idx in enumerate(mapping):
        if actual_idx is not None and 0 <= actual_idx < len(words):
            starts[i] = float(words[actual_idx]["start"])
            ends[i] = float(words[actual_idx]["end"])

    # Interpola raras palavras que o ASR não mapeou. O texto mostrado continua
    # sendo o roteiro aprovado; o tempo vem dos vizinhos reais do áudio.
    i = 0
    while i < len(expected_rows):
        if starts[i] is not None:
            i += 1
            continue
        a = i
        while i < len(expected_rows) and starts[i] is None:
            i += 1
        b = i
        left = ends[a - 1] if a > 0 and ends[a - 1] is not None else 0.0
        right = starts[b] if b < len(expected_rows) and starts[b] is not None else duration
        left = float(left)
        right = max(left + 0.08 * (b - a), float(right))
        step = (right - left) / max(1, b - a)
        for k in range(a, b):
            starts[k] = left + step * (k - a)
            ends[k] = left + step * (k - a + 1)

    timing: list[dict] = []
    for idx, row in enumerate(expected_rows):
        start = max(0.0, float(starts[idx] or 0.0) - 0.018)
        spoken_end = float(ends[idx] or start + 0.12)
        next_start = float(starts[idx + 1]) if idx + 1 < len(starts) and starts[idx + 1] is not None else duration
        # Em fala corrida a palavra fica até a próxima começar. Em pausa real,
        # o balão some logo depois do término da palavra.
        if next_start - spoken_end <= 0.18:
            end = max(spoken_end, next_start)
        else:
            end = min(next_start, spoken_end + 0.07)
        end = min(duration, max(start + 0.075, end))
        timing.append({
            **row,
            "word_index": idx + 1,
            "start": round(start, 4),
            "end": round(end, 4),
            "seconds": round(end - start, 4),
            "mapped_asr_index": mapping[idx],
            "sync_method": "single-take + faster-whisper word timestamp",
            "caption_location": "small Ze speech bubble only",
            "animation": "pop 82%-108%-100%",
        })

    (POST / "word_bubble_timing.json").write_text(
        json.dumps({"alignment_ratio": ratio, "words": timing}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return timing, ratio


def bubble_geometry(side: str, scale: float) -> tuple[tuple[int, int, int, int], list[tuple[int, int]]]:
    # Aproximadamente 55% da área do balão antigo. Uma palavra por vez.
    if side == "left":
        cx, cy = 760, 1375
        tail_tip = (392, 1432)
    else:
        cx, cy = 320, 1375
        tail_tip = (688, 1432)
    base_w, base_h = 430, 188
    w, h = int(base_w * scale), int(base_h * scale)
    x1, y1 = cx - w // 2, cy - h // 2
    x2, y2 = cx + w // 2, cy + h // 2
    if side == "left":
        tail = [(x1 + 24, cy + 18), tail_tip, (x1 + 54, cy + 48)]
    else:
        tail = [(x2 - 24, cy + 18), tail_tip, (x2 - 54, cy + 48)]
    return (x1, y1, x2, y2), tail


def draw_word_bubble(base_img: Image.Image, word: str, side: str, accent: str, scale: float) -> Image.Image:
    im = base_img.copy().convert("RGBA")
    d = ImageDraw.Draw(im)
    box, tail = bubble_geometry(side, scale)
    d.polygon(tail, fill=(255, 255, 255, 248))
    d.rounded_rectangle(
        box,
        radius=max(22, int(34 * scale)),
        fill=(255, 255, 255, 248),
        outline=accent,
        width=max(4, int(6 * scale)),
    )

    usable = max(120, (box[2] - box[0]) - 48)
    chosen = None
    for size in (58, 54, 50, 46, 42, 38, 34):
        font = ImageFont.truetype(FONT_BOLD, max(28, int(size * scale)))
        tb = d.textbbox((0, 0), word, font=font)
        if tb[2] - tb[0] <= usable:
            chosen = font
            break
    if chosen is None:
        chosen = ImageFont.truetype(FONT_BOLD, max(26, int(32 * scale)))
    tb = d.textbbox((0, 0), word, font=chosen)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    x = box[0] + ((box[2] - box[0]) - tw) // 2
    y = box[1] + ((box[3] - box[1]) - th) // 2 - tb[1]
    d.text((x, y), word, font=chosen, fill=(18, 18, 18, 255))
    return im


def emphasize_signoff(audio: Path, words: list[dict]) -> tuple[Path, list[dict]]:
    rows = expected_word_rows()
    expected = [x["norm"] for x in rows]
    mapping, _ = v4.align_tokens(expected, [w["norm"] for w in words])
    # Últimas 7 palavras: Zé Curioso parece mentira mas é real.
    ids = [mapping[i] for i in range(max(0, len(mapping) - 7), len(mapping)) if mapping[i] is not None]
    if not ids:
        return audio, words
    signoff_start = max(0.0, float(words[min(ids)]["start"]) - 0.04)
    boosted = AUDIO / "narration_continuous_v64.wav"
    # +~1 dB apenas na assinatura. Não corta nem cola áudio; reforça a intenção
    # prosódica pedida ao TTS sem alterar o corpo calmo da narração.
    v4.run([
        "ffmpeg", "-y", "-i", str(audio),
        "-af", f"volume=1.12:enable='gte(t,{signoff_start:.4f})'",
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(boosted),
    ])
    shutil.move(str(boosted), str(audio))
    return audio, words


def generate_v64() -> tuple[Path, list[dict], float, str]:
    audio, words, ratio, transcript = v62.generate_final_single_take()
    audio, words = emphasize_signoff(audio, words)
    return audio, words, ratio, transcript


def _pop_scale(item: dict, t: float) -> tuple[float, int]:
    dur = max(0.075, float(item["end"]) - float(item["start"]))
    # Em 30 fps, 40 ms + 50 ms garante visualmente cerca de três quadros de POP.
    d1 = min(0.040, max(0.034, dur * 0.22))
    d2 = min(0.050, max(0.034, dur * 0.28))
    if d1 + d2 > dur * 0.78:
        factor = (dur * 0.72) / max(0.001, d1 + d2)
        d1 *= factor
        d2 *= factor
    elapsed = max(0.0, t - float(item["start"]))
    if elapsed < d1:
        return 0.82, 1
    if elapsed < d1 + d2:
        return 1.08, 2
    return 1.00, 3


def render_word_pop_video(_block_timing: list[dict], audio: Path) -> None:
    """Renderiza a linha do tempo inteira em UMA passagem H.264.

    A versão anterior criava centenas de mini-MP4s e concatenava com stream-copy;
    timestamps de segmentos muito curtos colapsavam a duração. Aqui cada quadro
    de 30 fps é enviado diretamente para um único processo FFmpeg. O áudio
    continua sendo a tomada única original, sem cortes.
    """
    words = json.loads((POST / "alignment_words.json").read_text(encoding="utf-8"))
    timing, word_ratio = build_word_timing(words)
    if word_ratio < 0.90:
        raise RuntimeError(f"Word bubble alignment baixo: {word_ratio:.4f}")

    BUBBLE_FRAMES.mkdir(parents=True, exist_ok=True)
    audio_duration = cont.probe_duration(audio)
    fps = 30
    total_frames = int(math.ceil(audio_duration * fps))

    scene_images = {
        scene: Image.open(SCENES / f"scene_{scene:02d}.jpg").convert("RGBA")
        for scene in range(1, 6)
    }
    plain_raw = {
        scene: img.convert("RGB").tobytes()
        for scene, img in scene_images.items()
    }

    scene_starts: dict[int, float] = {1: 0.0}
    for scene in range(2, 6):
        starts = [float(x["start"]) for x in timing if int(x["scene"]) == scene]
        if starts:
            scene_starts[scene] = min(starts)

    visual = VIDEO / "word_pop_visual.mp4"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
        "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-g", str(fps), "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(visual),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    if proc.stdin is None:
        raise RuntimeError("FFmpeg não abriu stdin para render V6.4")

    word_ptr = 0
    last_key = None
    current_raw: bytes | None = None
    saved_keys: set[tuple] = set()

    try:
        for frame_index in range(total_frames):
            # Centro temporal do frame evita antecipar uma palavra por um quadro.
            t = min(audio_duration, (frame_index + 0.5) / fps)

            scene = 1
            for candidate_scene, start in sorted(scene_starts.items()):
                if t >= start:
                    scene = candidate_scene
                else:
                    break

            while word_ptr + 1 < len(timing) and t >= float(timing[word_ptr]["end"]):
                word_ptr += 1

            item = timing[word_ptr] if timing else None
            active = (
                item is not None
                and float(item["start"]) <= t < float(item["end"])
            )

            if active:
                scene = int(item["scene"])
                scale, phase = _pop_scale(item, t)
                key = (scene, int(item["word_index"]), phase)
            else:
                key = (scene, 0, 0)

            if key != last_key:
                if active and item is not None:
                    cfg = card.SCENE_CONFIG[scene - 1]
                    frame = draw_word_bubble(
                        scene_images[scene],
                        str(item["display"]),
                        cfg["side"],
                        cfg["accent"],
                        scale,
                    )
                    current_raw = frame.convert("RGB").tobytes()
                    if key not in saved_keys:
                        fp = BUBBLE_FRAMES / f"word_{int(item['word_index']):03d}_{phase}.jpg"
                        frame.convert("RGB").save(fp, quality=92)
                        saved_keys.add(key)
                else:
                    current_raw = plain_raw[scene]
                last_key = key

            if current_raw is None:
                current_raw = plain_raw[scene]
            proc.stdin.write(current_raw)
    except BrokenPipeError as exc:
        raise RuntimeError("FFmpeg encerrou durante o render contínuo do POP") from exc
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass

    return_code = proc.wait()
    if return_code != 0:
        raise RuntimeError(f"FFmpeg word-pop retornou código {return_code}")

    visual_duration = cont.probe_duration(visual)
    if abs(visual_duration - audio_duration) > 0.12:
        raise RuntimeError(
            f"Timeline word-pop fora da duração do áudio: video={visual_duration:.3f}s audio={audio_duration:.3f}s"
        )

    final = POST / "ze_curioso_sapo_congela_final.mp4"
    v4.run([
        "ffmpeg", "-y", "-i", str(visual), "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart", str(final),
    ])
    print(
        "WORD_POP_SINGLE_PASS_OK",
        json.dumps({
            "audio_duration": round(audio_duration, 3),
            "visual_duration": round(visual_duration, 3),
            "frames": total_frames,
            "fps": fps,
            "word_alignment": round(word_ratio, 4),
        }),
        flush=True,
    )


def qa_v64(asr_ratio: float, alignment_ratio: float, timing: list[dict]) -> None:
    v63.qa_v63(asr_ratio, alignment_ratio, timing)
    qa_path = POST / "qa.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    word_data = json.loads((POST / "word_bubble_timing.json").read_text(encoding="utf-8"))
    qa.update({
        "revision": "card-v6.4-LOCKED-word-pop-signoff-emphasis",
        "template_status": "LOCKED BASELINE",
        "bubble_mode": "one spoken word at a time",
        "bubble_size": "small",
        "bubble_animation": "POP 82%-108%-100% per spoken word",
        "word_alignment_ratio": round(float(word_data["alignment_ratio"]), 4),
        "external_captions": False,
        "signoff": "Zé Curioso: parece mentira, mas é real.",
        "signoff_direction": "slightly stronger identity/lift/firm landing; body remains calm explanatory",
        "signoff_post_gain": "1.12x (~+1 dB), continuous file, no splice",
        "video_render_strategy": "single continuous rawvideo -> one H.264 encode",
    })
    qa["passed"] = bool(qa.get("passed")) and float(word_data["alignment_ratio"]) >= 0.90
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    if not qa["passed"]:
        raise RuntimeError(f"QA V6.4 falhou: {qa}")


if __name__ == "__main__":
    cont.words_from_text = v4.words_from_text
    cont.align_tokens = v4.align_tokens
    cont.generate_continuous_narration = generate_v64
    cont.render_video = render_word_pop_video
    cont._qa_original = cont.qa_and_copy
    cont.qa_and_copy = qa_v64
    cont.main()
