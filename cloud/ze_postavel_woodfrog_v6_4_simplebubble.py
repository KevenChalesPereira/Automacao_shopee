from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import ze_postavel_woodfrog_v6_4_finalpolish as fp

carrier = fp.carrier
fs = fp.fs
v64 = fp.v64
v4 = fp.v4
cont = fp.cont
card = fp.card
POST = fp.POST
AUDIO = fp.AUDIO
SCENES = fp.SCENES
VIDEO = fp.VIDEO
BUBBLE_FRAMES = fp.BUBBLE_FRAMES
FONT_BOLD = fp.FONT_BOLD
W, H = fp.W, fp.H

# Versão simplificada aprovada em conversa:
# - mantém grupos fixos de até 3 palavras no balão;
# - somente destaca a palavra que está sendo falada (sem POP na palavra);
# - o balão inteiro dá UM único POP quando o grupo entra e depois fica estático;
# - restaura o bordão anterior, que começa naturalmente com "Eu sou...";
# - mantém Faster-Whisper + render single-pass.
PREVIOUS_SIGNOFF = "Eu sou o Zé Curioso. E aqui... parece mentira, mas é real."
TAIL_SECONDS = 0.70
BUBBLE_POP_IN = 0.060
BUBBLE_POP_OVER = 0.080
BUBBLE_START_SCALE = 0.88
BUBBLE_OVER_SCALE = 1.06

_base_generate_signoff = fs.generate_signoff
_original_qa_v64 = fp._original_qa_v64
_original_build_word_timing = fp._original_build_word_timing


def _restore_previous_signoff_text() -> None:
    fs.SIGNOFF_SPEAK = PREVIOUS_SIGNOFF
    fs.SIGNOFF_DISPLAY = PREVIOUS_SIGNOFF
    fs.SIGNOFF_BLOCK["text"] = PREVIOUS_SIGNOFF
    # SIGNOFF_BLOCK aponta para o último item da mesma lista, mas mantemos explícito.
    fs.v62.FINAL_BLOCKS[-1]["text"] = PREVIOUS_SIGNOFF
    cont.BLOCKS = fs.v62.FINAL_BLOCKS


def generate_previous_signoff_with_tail():
    _restore_previous_signoff_text()
    final, words, ratio, transcript, metrics = _base_generate_signoff()

    original_duration = v4.probe_duration(final)
    padded = AUDIO / "signoff_final_padded.wav"
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
        "signoff_text": PREVIOUS_SIGNOFF,
        "signoff_style": "previous catchphrase restored; no carrier phrase",
        "tail_padding_seconds": TAIL_SECONDS,
        "duration_before_tail": round(original_duration, 3),
        "duration_after_tail": round(v4.probe_duration(final), 3),
    }
    qa_path = POST / "signoff_qa.json"
    if qa_path.exists():
        data = json.loads(qa_path.read_text(encoding="utf-8"))
        data["selected"] = metrics
        data["final_tail_seconds"] = TAIL_SECONDS
        data["expected_signoff"] = PREVIOUS_SIGNOFF
        qa_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return final, words, ratio, transcript, metrics


def _block_bounds(timing: list[dict], index: int) -> tuple[int, int]:
    current = timing[index]
    scene = current["scene"]
    block = current["block"]
    start = index
    while start > 0 and timing[start - 1]["scene"] == scene and timing[start - 1]["block"] == block:
        start -= 1
    end = index + 1
    while end < len(timing) and timing[end]["scene"] == scene and timing[end]["block"] == block:
        end += 1
    return start, end


def _chunk_indices(timing: list[dict], active_index: int) -> list[int]:
    block_start, block_end = _block_bounds(timing, active_index)
    offset = active_index - block_start
    chunk_start = block_start + (offset // 3) * 3
    return list(range(chunk_start, min(chunk_start + 3, block_end)))


def _chunk_id(timing: list[dict], index: int) -> tuple[int, int, int]:
    chunk = _chunk_indices(timing, index)
    item = timing[index]
    return int(item["scene"]), int(item["block"]), int(chunk[0])


def build_simple_timing(words: list[dict]):
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

        chunk = _chunk_indices(timing, idx)
        item["window_word_indices"] = [int(timing[j]["word_index"]) for j in chunk]
        item["window_words"] = [str(timing[j]["display"]) for j in chunk]
        item["window_text"] = " ".join(item["window_words"])
        item["active_window_position"] = chunk.index(idx)
        item["chunk_start_index"] = int(chunk[0])
        item["chunk_end_index"] = int(chunk[-1])
        item["caption_location"] = "small Ze speech bubble only"
        item["animation"] = "bubble pops once on chunk entry; active spoken word highlight only"
        item["sync_method"] = "Faster-Whisper word timestamps; fixed groups of up to 3 words"

    payload = {
        "alignment_ratio": ratio,
        "words": timing,
        "window_mode": "fixed chunks of up to 3 words within each block",
        "window_size_max": 3,
        "active_word_highlight_only": True,
        "active_word_pop": False,
        "bubble_pop_once_per_chunk": True,
        "bubble_pop_profile": "88%-106%-100%",
        "word_timestamp_source": "Faster-Whisper",
        "max_start_drift_seconds": round(max(drifts) if drifts else 0.0, 4),
        "mean_start_drift_seconds": round(sum(drifts) / max(1, len(drifts)), 4),
        "final_audio_tail_seconds": TAIL_SECONDS,
        "signoff": PREVIOUS_SIGNOFF,
    }
    (POST / "word_bubble_timing.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return timing, ratio


def bubble_pop_scale(chunk_start: float, t: float) -> tuple[float, int]:
    elapsed = max(0.0, t - chunk_start)
    if elapsed < BUBBLE_POP_IN:
        return BUBBLE_START_SCALE, 1
    if elapsed < BUBBLE_POP_IN + BUBBLE_POP_OVER:
        return BUBBLE_OVER_SCALE, 2
    return 1.0, 3


def _draw_bubble_layer(
    timing: list[dict],
    chunk: list[int],
    active_index: int | None,
    side: str,
    accent: str,
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    box, tail = fp.bubble_geometry_static(side)

    d.polygon(tail, fill=(255, 255, 255, 248))
    d.rounded_rectangle(
        box,
        radius=34,
        fill=(255, 255, 255, 248),
        outline=accent,
        width=6,
    )

    labels = [str(timing[j]["display"]) for j in chunk]
    usable_width = (box[2] - box[0]) - 50
    _, base_size, widths, gap = fp._fit_window_font(d, labels, usable_width)
    total = sum(widths) + gap * max(0, len(widths) - 1)
    cursor = box[0] + ((box[2] - box[0]) - total) / 2.0
    centers: list[float] = []
    for width in widths:
        centers.append(cursor + width / 2.0)
        cursor += width + gap

    for slot, word_idx in enumerate(chunk):
        label = str(timing[word_idx]["display"])
        is_active = active_index == word_idx
        font = ImageFont.truetype(FONT_BOLD, base_size)
        tb = d.textbbox((0, 0), label, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        x = centers[slot] - tw / 2.0
        y = box[1] + ((box[3] - box[1]) - th) / 2.0 - tb[1]
        fill = accent if is_active else (82, 82, 82, 255)
        d.text((x, y), label, font=font, fill=fill)

    xs = [box[0], box[2]] + [p[0] for p in tail]
    ys = [box[1], box[3]] + [p[1] for p in tail]
    pad = 14
    bounds = (
        max(0, int(min(xs)) - pad),
        max(0, int(min(ys)) - pad),
        min(W, int(max(xs)) + pad),
        min(H, int(max(ys)) + pad),
    )
    return layer, bounds


def draw_simple_bubble(
    base_img: Image.Image,
    timing: list[dict],
    chunk: list[int],
    active_index: int | None,
    side: str,
    accent: str,
    bubble_scale: float,
) -> Image.Image:
    base = base_img.copy().convert("RGBA")
    layer, bounds = _draw_bubble_layer(timing, chunk, active_index, side, accent)
    crop = layer.crop(bounds)

    if abs(bubble_scale - 1.0) > 0.001:
        nw = max(2, int(round(crop.width * bubble_scale)))
        nh = max(2, int(round(crop.height * bubble_scale)))
        crop = crop.resize((nw, nh), Image.Resampling.LANCZOS)

    cx = (bounds[0] + bounds[2]) // 2
    cy = (bounds[1] + bounds[3]) // 2
    x = int(round(cx - crop.width / 2))
    y = int(round(cy - crop.height / 2))
    base.alpha_composite(crop, (x, y))
    return base


def render_simple_bubble_video(_block_timing: list[dict], audio: Path) -> None:
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
    plain_raw = {scene: img.convert("RGB").tobytes() for scene, img in scene_images.items()}

    scene_starts: dict[int, float] = {1: 0.0}
    for scene in range(2, 6):
        starts = [float(x["start"]) for x in timing if int(x["scene"]) == scene]
        if starts:
            scene_starts[scene] = min(starts)

    visual = VIDEO / "simple_bubble_visual.mp4"
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
        raise RuntimeError("FFmpeg não abriu stdin para render do balão simples")

    chunks: dict[tuple[int, int, int], dict] = {}
    for idx, item in enumerate(timing):
        cid = _chunk_id(timing, idx)
        if cid not in chunks:
            inds = _chunk_indices(timing, idx)
            chunks[cid] = {
                "indices": inds,
                "start": float(timing[inds[0]]["start"]),
                "end": float(timing[inds[-1]]["end"]),
                "scene": int(item["scene"]),
            }

    ordered_chunks = sorted(chunks.items(), key=lambda kv: kv[1]["start"])
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

            active_chunk_id = None
            chunk_info = None
            for cid, info in ordered_chunks:
                if info["start"] <= t <= info["end"]:
                    active_chunk_id = cid
                    chunk_info = info
                    break
                if info["start"] > t:
                    break

            if chunk_info is None:
                key = (scene, "plain")
            else:
                scene = int(chunk_info["scene"])
                inds = chunk_info["indices"]
                active_index: int | None = None
                for wi in inds:
                    if float(timing[wi]["start"]) <= t < float(timing[wi]["end"]):
                        active_index = wi
                        break
                scale, phase = bubble_pop_scale(float(chunk_info["start"]), t)
                key = (scene, active_chunk_id, active_index, phase)

            if key != last_key:
                if chunk_info is None:
                    current_raw = plain_raw[scene]
                else:
                    cfg = card.SCENE_CONFIG[scene - 1]
                    frame = draw_simple_bubble(
                        scene_images[scene], timing, chunk_info["indices"], active_index,
                        cfg["side"], cfg["accent"], scale,
                    )
                    current_raw = frame.convert("RGB").tobytes()
                    save_key = (active_chunk_id, active_index, phase)
                    if save_key not in saved_keys:
                        chunk_first = int(timing[chunk_info["indices"][0]]["word_index"])
                        active_word = 0 if active_index is None else int(timing[active_index]["word_index"])
                        frame.convert("RGB").save(
                            BUBBLE_FRAMES / f"chunk_{chunk_first:03d}_active_{active_word:03d}_phase_{phase}.jpg",
                            quality=92,
                        )
                        saved_keys.add(save_key)
                last_key = key

            if current_raw is None:
                current_raw = plain_raw[scene]
            proc.stdin.write(current_raw)
    except BrokenPipeError as exc:
        raise RuntimeError("FFmpeg encerrou durante o render contínuo do balão simples") from exc
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass

    return_code = proc.wait()
    if return_code != 0:
        raise RuntimeError(f"FFmpeg simple-bubble retornou código {return_code}")

    visual_duration = cont.probe_duration(visual)
    if abs(visual_duration - audio_duration) > 0.12:
        raise RuntimeError(
            f"Timeline simple-bubble fora da duração do áudio: video={visual_duration:.3f}s audio={audio_duration:.3f}s"
        )

    final = POST / "ze_curioso_sapo_congela_final.mp4"
    v4.run([
        "ffmpeg", "-y", "-i", str(visual), "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart", str(final),
    ])
    print(
        "SIMPLE_BUBBLE_SINGLE_PASS_OK",
        json.dumps({
            "audio_duration": round(audio_duration, 3),
            "visual_duration": round(visual_duration, 3),
            "frames": total_frames,
            "fps": fps,
            "word_alignment": round(word_ratio, 4),
            "window_size": 3,
            "active_word_highlight_only": True,
            "active_word_pop": False,
            "bubble_pop_once_per_chunk": True,
            "signoff": PREVIOUS_SIGNOFF,
        }, ensure_ascii=False),
        flush=True,
    )


def qa_simple(asr_ratio: float, alignment_ratio: float, timing: list[dict]) -> None:
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
    signoff_text = (POST / "asr_transcript.txt").read_text(encoding="utf-8") if (POST / "asr_transcript.txt").exists() else ""
    signoff_ok = "Zé Curioso" in signoff_text and "parece mentira" in signoff_text.lower() and "real" in signoff_text.lower()

    qa.update({
        "revision": "card-v6.4-SIMPLE-BUBBLE",
        "template_status": "FINAL CANDIDATE - simplified bubble",
        "bubble_mode": "fixed groups of up to 3 words",
        "bubble_animation": "whole bubble pops once on group entry; then stays at 100%",
        "active_word_style": "highlight only; no word scaling/pop",
        "active_word_pop": False,
        "bubble_pop_once_per_chunk": True,
        "word_timestamp_source": "Faster-Whisper word timestamps",
        "word_mean_start_drift_seconds": wt.get("mean_start_drift_seconds"),
        "word_max_start_drift_seconds": wt.get("max_start_drift_seconds"),
        "window_size_max": 3,
        "window_structure_valid": windows_ok,
        "external_captions": False,
        "final_audio_tail_seconds": TAIL_SECONDS,
        "final_cutoff_protection": True,
        "video_render_strategy": "single continuous rawvideo -> one H.264 encode",
        "signoff_expected": PREVIOUS_SIGNOFF,
        "signoff_asr_contains_brand": signoff_ok,
    })
    qa["passed"] = bool(qa.get("passed")) and windows_ok and signoff_ok and float(wt.get("alignment_ratio", 0.0)) >= 0.90
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    if not qa["passed"]:
        raise RuntimeError(f"QA balão simples falhou: {qa}")


def main() -> None:
    _restore_previous_signoff_text()
    carrier.generate_signoff_carrier = generate_previous_signoff_with_tail
    v64.build_word_timing = build_simple_timing
    v64.render_word_pop_video = render_simple_bubble_video
    v64.qa_v64 = qa_simple
    carrier.main()


if __name__ == "__main__":
    main()
