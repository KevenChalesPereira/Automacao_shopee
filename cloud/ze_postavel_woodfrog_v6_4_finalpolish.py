from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import ze_postavel_woodfrog_v6_4_carrierfix as carrier

fs = carrier.fs
v64 = fs.v64
v4 = fs.v4
cont = fs.cont
card = v64.card
POST = cont.POST
AUDIO = cont.AUDIO
SCENES = cont.SCENES
VIDEO = cont.VIDEO
BUBBLE_FRAMES = cont.BUBBLE_FRAMES
FONT_BOLD = cont.FONT_BOLD
W, H = cont.W, cont.H

# Ajuste final do template:
# - mantém a voz/corpo calmos e o carrier phrase aprovado para o bordão;
# - acrescenta cauda real depois do bordão para não cortar a última sílaba;
# - usa timestamps reais de palavra do Faster-Whisper;
# - mostra janela deslizante de até 3 palavras (anterior/atual/próxima);
# - somente a palavra ativa recebe POP; balão e palavras vizinhas ficam estáticos;
# - mantém render single-pass, sem centenas de mini-MP4.
TAIL_SECONDS = 0.70
POP_IN_SECONDS = 0.055
POP_OVERSHOOT_SECONDS = 0.075
POP_START_SCALE = 0.86
POP_OVERSHOOT_SCALE = 1.08

_original_generate_signoff = carrier.generate_signoff_carrier
_original_qa_v64 = v64.qa_v64
_original_build_word_timing = v64.build_word_timing


def generate_signoff_with_tail():
    final, words, ratio, transcript, metrics = _original_generate_signoff()

    original_duration = v4.probe_duration(final)
    padded = AUDIO / "signoff_final_padded.wav"
    # Acrescenta silêncio DEPOIS da assinatura. Não corta nem altera a fala.
    v4.run([
        "ffmpeg", "-y",
        "-i", str(final),
        "-f", "lavfi", "-t", f"{TAIL_SECONDS:.3f}",
        "-i", "anullsrc=r=48000:cl=mono",
        "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[out]",
        "-map", "[out]",
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le",
        str(padded),
    ])
    shutil.move(str(padded), str(final))

    metrics = {
        **metrics,
        "tail_padding_seconds": TAIL_SECONDS,
        "duration_before_tail": round(original_duration, 3),
        "duration_after_tail": round(v4.probe_duration(final), 3),
    }

    qa_path = POST / "signoff_qa.json"
    if qa_path.exists():
        data = json.loads(qa_path.read_text(encoding="utf-8"))
        data["selected"] = metrics
        data["final_tail_seconds"] = TAIL_SECONDS
        qa_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return final, words, ratio, transcript, metrics


def _window_indices(timing: list[dict], active_index: int) -> list[int]:
    """Anterior/atual/próxima sem atravessar o limite do bloco/frase."""
    current = timing[active_index]
    out: list[int] = []
    if active_index > 0:
        prev = timing[active_index - 1]
        if prev["scene"] == current["scene"] and prev["block"] == current["block"]:
            out.append(active_index - 1)
    out.append(active_index)
    if active_index + 1 < len(timing):
        nxt = timing[active_index + 1]
        if nxt["scene"] == current["scene"] and nxt["block"] == current["block"]:
            out.append(active_index + 1)
    return out


def build_three_word_timing(words: list[dict]):
    # Usa a sincronização original da V6.4: o início vem do timestamp real
    # Faster-Whisper (apenas 18 ms de antecipação visual), sem agenda artificial.
    timing, ratio = _original_build_word_timing(words)
    drifts: list[float] = []

    for idx, item in enumerate(timing):
        mapped = item.get("mapped_asr_index")
        if isinstance(mapped, int) and 0 <= mapped < len(words):
            spoken_start = float(words[mapped]["start"])
            spoken_end = float(words[mapped]["end"])
            drift = float(item["start"]) - spoken_start
            item["spoken_start"] = round(spoken_start, 4)
            item["spoken_end"] = round(spoken_end, 4)
            item["display_vs_speech_start_drift"] = round(drift, 4)
            drifts.append(abs(drift))
        else:
            item["spoken_start"] = None
            item["spoken_end"] = None
            item["display_vs_speech_start_drift"] = None

        win = _window_indices(timing, idx)
        item["window_word_indices"] = [int(timing[j]["word_index"]) for j in win]
        item["window_words"] = [str(timing[j]["display"]) for j in win]
        item["window_text"] = " ".join(item["window_words"])
        item["active_window_position"] = win.index(idx)
        item["caption_location"] = "small static Ze speech bubble only"
        item["animation"] = "active word only POP 86%-108%-100%; neighbors static"
        item["sync_method"] = "faster-whisper word timestamp; sliding 3-word window"

    payload = {
        "alignment_ratio": ratio,
        "words": timing,
        "window_mode": "previous/current/next within same block",
        "window_size_max": 3,
        "active_word_only": True,
        "pop_profile": "86%-108%-100%",
        "word_timestamp_source": "Faster-Whisper",
        "max_start_drift_seconds": round(max(drifts) if drifts else 0.0, 4),
        "mean_start_drift_seconds": round(sum(drifts) / max(1, len(drifts)), 4),
        "final_audio_tail_seconds": TAIL_SECONDS,
    }
    (POST / "word_bubble_timing.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return timing, ratio


def active_word_pop_scale(item: dict, t: float):
    dur = max(0.075, float(item["end"]) - float(item["start"]))
    d1 = min(POP_IN_SECONDS, max(0.034, dur * 0.22))
    d2 = min(POP_OVERSHOOT_SECONDS, max(0.034, dur * 0.28))
    if d1 + d2 > dur * 0.78:
        factor = (dur * 0.72) / max(0.001, d1 + d2)
        d1 *= factor
        d2 *= factor

    elapsed = max(0.0, t - float(item["start"]))
    if elapsed < d1:
        return POP_START_SCALE, 1
    if elapsed < d1 + d2:
        return POP_OVERSHOOT_SCALE, 2
    return 1.00, 3


def bubble_geometry_static(side: str):
    """Balão maior que o antigo de 1 palavra, mas ainda compacto e perto do Zé."""
    if side == "left":
        cx, cy = 760, 1375
        tail_tip = (392, 1432)
    else:
        cx, cy = 320, 1375
        tail_tip = (688, 1432)

    base_w, base_h = 620, 190
    x1, y1 = cx - base_w // 2, cy - base_h // 2
    x2, y2 = cx + base_w // 2, cy + base_h // 2
    if side == "left":
        tail = [(x1 + 34, cy + 16), tail_tip, (x1 + 70, cy + 52)]
    else:
        tail = [(x2 - 34, cy + 16), tail_tip, (x2 - 70, cy + 52)]
    return (x1, y1, x2, y2), tail


def _fit_window_font(draw: ImageDraw.ImageDraw, words: list[str], usable_width: int):
    gap = 16
    for size in (52, 50, 48, 46, 44, 42, 40, 38, 36, 34, 32, 30):
        font = ImageFont.truetype(FONT_BOLD, size)
        widths = []
        for word in words:
            tb = draw.textbbox((0, 0), word, font=font)
            widths.append(tb[2] - tb[0])
        total = sum(widths) + gap * max(0, len(words) - 1)
        if total <= usable_width:
            return font, size, widths, gap

    font = ImageFont.truetype(FONT_BOLD, 28)
    widths = []
    for word in words:
        tb = draw.textbbox((0, 0), word, font=font)
        widths.append(tb[2] - tb[0])
    return font, 28, widths, 12


def draw_three_word_bubble(
    base_img: Image.Image,
    timing: list[dict],
    active_index: int,
    side: str,
    accent: str,
    active_scale: float,
) -> Image.Image:
    """Desenha balão fixo; somente a palavra ativa muda de escala."""
    im = base_img.copy().convert("RGBA")
    d = ImageDraw.Draw(im)
    box, tail = bubble_geometry_static(side)

    d.polygon(tail, fill=(255, 255, 255, 248))
    d.rounded_rectangle(
        box,
        radius=34,
        fill=(255, 255, 255, 248),
        outline=accent,
        width=6,
    )

    win = _window_indices(timing, active_index)
    labels = [str(timing[j]["display"]) for j in win]
    usable_width = (box[2] - box[0]) - 50
    base_font, base_size, widths, gap = _fit_window_font(d, labels, usable_width)

    total = sum(widths) + gap * max(0, len(widths) - 1)
    cursor = box[0] + ((box[2] - box[0]) - total) / 2.0
    slot_centers: list[float] = []
    for width in widths:
        slot_centers.append(cursor + width / 2.0)
        cursor += width + gap

    for slot, word_idx in enumerate(win):
        label = str(timing[word_idx]["display"])
        is_active = word_idx == active_index
        scale = active_scale if is_active else 1.0
        font_size = max(26, int(round(base_size * scale)))
        font = ImageFont.truetype(FONT_BOLD, font_size)
        tb = d.textbbox((0, 0), label, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        x = slot_centers[slot] - tw / 2.0
        y = box[1] + ((box[3] - box[1]) - th) / 2.0 - tb[1]
        fill = (18, 18, 18, 255) if is_active else (78, 78, 78, 255)
        d.text((x, y), label, font=font, fill=fill)

    return im


def render_three_word_pop_video(_block_timing: list[dict], audio: Path) -> None:
    """Single-pass H.264 com janela de 3 palavras e POP apenas na ativa."""
    words = json.loads((POST / "alignment_words.json").read_text(encoding="utf-8"))
    timing, word_ratio = v64.build_word_timing(words)
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
        raise RuntimeError("FFmpeg não abriu stdin para render da janela de 3 palavras")

    word_ptr = 0
    last_key = None
    current_raw: bytes | None = None
    saved_keys: set[tuple] = set()

    try:
        for frame_index in range(total_frames):
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

            if active and item is not None:
                scene = int(item["scene"])
                scale, phase = v64._pop_scale(item, t)
                key = (scene, word_ptr, phase)
            else:
                key = (scene, -1, 0)

            if key != last_key:
                if active and item is not None:
                    cfg = card.SCENE_CONFIG[scene - 1]
                    frame = draw_three_word_bubble(
                        scene_images[scene],
                        timing,
                        word_ptr,
                        cfg["side"],
                        cfg["accent"],
                        scale,
                    )
                    current_raw = frame.convert("RGB").tobytes()
                    if key not in saved_keys:
                        fp = BUBBLE_FRAMES / f"window_{int(item['word_index']):03d}_{phase}.jpg"
                        frame.convert("RGB").save(fp, quality=92)
                        saved_keys.add(key)
                else:
                    current_raw = plain_raw[scene]
                last_key = key

            if current_raw is None:
                current_raw = plain_raw[scene]
            proc.stdin.write(current_raw)
    except BrokenPipeError as exc:
        raise RuntimeError("FFmpeg encerrou durante o render contínuo da janela de 3 palavras") from exc
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass

    return_code = proc.wait()
    if return_code != 0:
        raise RuntimeError(f"FFmpeg three-word-pop retornou código {return_code}")

    visual_duration = cont.probe_duration(visual)
    if abs(visual_duration - audio_duration) > 0.12:
        raise RuntimeError(
            f"Timeline three-word-pop fora da duração do áudio: video={visual_duration:.3f}s audio={audio_duration:.3f}s"
        )

    final = POST / "ze_curioso_sapo_congela_final.mp4"
    v4.run([
        "ffmpeg", "-y", "-i", str(visual), "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart", str(final),
    ])
    print(
        "THREE_WORD_POP_SINGLE_PASS_OK",
        json.dumps({
            "audio_duration": round(audio_duration, 3),
            "visual_duration": round(visual_duration, 3),
            "frames": total_frames,
            "fps": fps,
            "word_alignment": round(word_ratio, 4),
            "window_size": 3,
            "active_word_only": True,
        }),
        flush=True,
    )


def qa_three_word_window(asr_ratio: float, alignment_ratio: float, timing: list[dict]) -> None:
    _original_qa_v64(asr_ratio, alignment_ratio, timing)
    qa_path = POST / "qa.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    wt = json.loads((POST / "word_bubble_timing.json").read_text(encoding="utf-8"))
    rows = wt.get("words", [])

    windows_ok = bool(rows) and all(
        1 <= len(row.get("window_words", [])) <= 3
        and 0 <= int(row.get("active_window_position", -1)) < len(row.get("window_words", []))
        for row in rows
    )

    qa.update({
        "revision": "card-v6.4-THREE-WORD-WINDOW-active-pop",
        "template_status": "FINAL CANDIDATE - awaiting visual approval",
        "bubble_mode": "3-word sliding window: previous/current/next; 2 words at block edges",
        "bubble_size": "compact 620x190 static bubble near Ze",
        "bubble_animation": "ONLY active word POP 86%-108%-100%; bubble and neighbor words remain static",
        "word_timestamp_source": "Faster-Whisper word timestamps",
        "word_mean_start_drift_seconds": wt.get("mean_start_drift_seconds"),
        "word_max_start_drift_seconds": wt.get("max_start_drift_seconds"),
        "window_size_max": 3,
        "window_structure_valid": windows_ok,
        "active_word_only": True,
        "external_captions": False,
        "final_audio_tail_seconds": TAIL_SECONDS,
        "final_cutoff_protection": True,
        "video_render_strategy": "single continuous rawvideo -> one H.264 encode",
    })
    qa["passed"] = bool(qa.get("passed")) and windows_ok and float(wt.get("alignment_ratio", 0.0)) >= 0.90
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    if not qa["passed"]:
        raise RuntimeError(f"QA janela de 3 palavras falhou: {qa}")


def main() -> None:
    carrier.generate_signoff_carrier = generate_signoff_with_tail
    v64.build_word_timing = build_three_word_timing
    v64._pop_scale = active_word_pop_scale
    v64.render_word_pop_video = render_three_word_pop_video
    v64.qa_v64 = qa_three_word_window
    carrier.main()


if __name__ == "__main__":
    main()
