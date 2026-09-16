from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path

from faster_whisper import WhisperModel
from PIL import Image, ImageDraw, ImageFont

import ze_postavel_woodfrog_final as base
import ze_postavel_woodfrog_card_sync as card

POST = base.POST
ASSETS = base.ASSETS
AUDIO = base.AUDIO
SCENES = base.SCENES
VIDEO = base.VIDEO
W, H = base.W, base.H
FONT_BOLD = base.FONT_BOLD
BUBBLE_FRAMES = POST / "bubble_frames"

BLOCKS: list[dict] = []
for scene_idx, scene_blocks in enumerate(card.SCENE_BLOCKS, 1):
    for block_idx, block in enumerate(scene_blocks, 1):
        BLOCKS.append({
            "scene": scene_idx,
            "block": block_idx,
            "text": block["text"],
        })

# Uma única tomada de voz. Nada de colar microáudios.
FULL_NARRATION = " ".join(item["text"] for item in BLOCKS)

VOICE_CONTROL = (
    base.VOICE_CONTROL
    + " Generate this as ONE continuous take from beginning to end. Keep timbre, volume, pace and microphone distance consistent."
    + " Do not reset the voice between sentences. Use natural connected speech and clean sentence endings."
    + " Avoid raspiness, vocal fry, hoarseness, clicks, abrupt cuts or breathy glitches."
    + " For the final channel signature, stay calm, clean and confident with a small natural smile."
)


def run_quiet(args: list[str]) -> None:
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def probe_duration(path: Path) -> float:
    return float(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            text=True,
        ).strip()
    )


def norm_word(value: str) -> str:
    value = unicodedata.normalize("NFD", value.lower())
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return "".join(ch for ch in value if ch.isalnum())


def words_from_text(text: str) -> list[str]:
    return [w for w in (norm_word(x) for x in re.findall(r"[\wÀ-ÿ'-]+", text, flags=re.UNICODE)) if w]


def align_tokens(expected: list[str], actual: list[str]) -> tuple[list[int | None], float]:
    n, m = len(expected), len(actual)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    back = [[""] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i
        back[i][0] = "D"
    for j in range(1, m + 1):
        dp[0][j] = j
        back[0][j] = "I"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            sub_cost = 0 if expected[i - 1] == actual[j - 1] else 1
            choices = [
                (dp[i - 1][j - 1] + sub_cost, "M"),
                (dp[i - 1][j] + 1, "D"),
                (dp[i][j - 1] + 1, "I"),
            ]
            dp[i][j], back[i][j] = min(choices, key=lambda x: x[0])

    mapping: list[int | None] = [None] * n
    i, j = n, m
    exact = 0
    while i > 0 or j > 0:
        op = back[i][j]
        if i > 0 and j > 0 and op == "M":
            mapping[i - 1] = j - 1
            if expected[i - 1] == actual[j - 1]:
                exact += 1
            i -= 1
            j -= 1
        elif i > 0 and (j == 0 or op == "D"):
            i -= 1
        else:
            j -= 1
    return mapping, exact / max(1, n)


def transcribe_words(model: WhisperModel, audio: Path) -> tuple[list[dict], str]:
    segments, info = model.transcribe(
        str(audio),
        language="pt",
        beam_size=5,
        word_timestamps=True,
        vad_filter=False,
        condition_on_previous_text=True,
    )
    out: list[dict] = []
    transcript: list[str] = []
    for seg in segments:
        transcript.append(seg.text.strip())
        for word in seg.words or []:
            token = norm_word(word.word)
            if not token:
                continue
            out.append({
                "word": word.word.strip(),
                "norm": token,
                "start": float(word.start),
                "end": float(word.end),
                "probability": float(getattr(word, "probability", 0.0) or 0.0),
            })
    return out, " ".join(x for x in transcript if x)


def generate_continuous_narration() -> tuple[Path, list[dict], float, str]:
    client = base.Client("openbmb/VoxCPM-Demo", verbose=False)
    ref = base.handle_file(str(ASSETS / "voice_ref.mp3"))
    whisper = WhisperModel("base", device="cpu", compute_type="int8")
    expected = words_from_text(FULL_NARRATION)
    best = None

    for attempt in range(1, 5):
        print(f"CONTINUOUS_TTS_ATTEMPT {attempt}", flush=True)
        result = client.predict(
            FULL_NARRATION, VOICE_CONTROL, ref, False, "", 2.0, True, False, api_name="/generate"
        )
        src = Path(base.extract_path(result))
        if not src.exists() or src.stat().st_size < 12000:
            time.sleep(4)
            continue

        candidate = AUDIO / f"narration_candidate_{attempt:02d}.wav"
        run_quiet([
            "ffmpeg", "-y", "-i", str(src),
            "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(candidate),
        ])
        duration = probe_duration(candidate)
        if not 24.0 <= duration <= 52.0:
            print("REJECT_DURATION", round(duration, 3), flush=True)
            continue

        words, transcript = transcribe_words(whisper, candidate)
        mapping, ratio = align_tokens(expected, [w["norm"] for w in words])
        print("ASR_EXACT_RATIO", round(ratio, 4), "WORDS", len(words), flush=True)
        score = ratio
        if best is None or score > best[0]:
            best = (score, candidate, words, mapping, transcript)
        # A leitura precisa estar muito próxima do roteiro; isso também barra takes embolados/bugados.
        if ratio >= 0.82:
            break
        time.sleep(5)

    if best is None or best[0] < 0.68:
        raise RuntimeError(f"Nenhuma tomada contínua passou no QA de inteligibilidade. Melhor score={best[0] if best else None}")

    score, candidate, words, mapping, transcript = best
    final_audio = AUDIO / "narration_continuous.wav"
    shutil.copy2(candidate, final_audio)
    (POST / "asr_transcript.txt").write_text(transcript, encoding="utf-8")
    (POST / "alignment_words.json").write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")
    return final_audio, words, score, transcript


def build_block_timing(words: list[dict]) -> tuple[list[dict], float]:
    expected: list[str] = []
    ranges: list[tuple[int, int]] = []
    for item in BLOCKS:
        start = len(expected)
        expected.extend(words_from_text(item["text"]))
        ranges.append((start, len(expected)))

    mapping, ratio = align_tokens(expected, [w["norm"] for w in words])
    duration = probe_duration(AUDIO / "narration_continuous.wav")
    timing: list[dict] = []

    for item, (a, b) in zip(BLOCKS, ranges):
        actual_ids = [mapping[i] for i in range(a, b) if mapping[i] is not None]
        if not actual_ids:
            raise RuntimeError(f"Sem alinhamento para bloco {item['scene']}.{item['block']}: {item['text']}")
        first, last = min(actual_ids), max(actual_ids)
        start = max(0.0, words[first]["start"] - 0.06)
        end = min(duration, words[last]["end"] + 0.08)
        timing.append({
            **item,
            "start": start,
            "end": end,
            "first_asr_word": words[first]["word"],
            "last_asr_word": words[last]["word"],
        })

    # Evita sobreposição de balões vizinhos: divide qualquer pequena colisão no meio.
    for i in range(len(timing) - 1):
        if timing[i]["end"] > timing[i + 1]["start"]:
            cut = (timing[i]["end"] + timing[i + 1]["start"]) / 2.0
            timing[i]["end"] = cut
            timing[i + 1]["start"] = cut

    for item in timing:
        item["start"] = round(item["start"], 3)
        item["end"] = round(item["end"], 3)
        item["seconds"] = round(item["end"] - item["start"], 3)
        item["sync_method"] = "single-continuous-audio + faster-whisper-word-alignment"
        item["caption_location"] = "Ze speech bubble only"

    return timing, ratio


def wrap_bubble_text(text: str, max_lines: int = 4) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    # Ajusta por largura real no balão. Fonte reduz automaticamente se precisar.
    max_px = 590
    for size in (46, 42, 38, 34):
        font = ImageFont.truetype(FONT_BOLD, size)
        lines: list[str] = []
        cur = ""
        for word in words:
            trial = word if not cur else cur + " " + word
            bbox = font.getbbox(trial)
            if bbox[2] - bbox[0] <= max_px:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        if len(lines) <= max_lines:
            return lines
    return lines[:max_lines]


def draw_caption_bubble(base_img: Image.Image, text: str, side: str, accent: str) -> Image.Image:
    lines = wrap_bubble_text(text)
    im = base_img.copy().convert("RGBA")
    d = ImageDraw.Draw(im)
    if side == "left":
        box = (315, 1200, 1030, 1545)
        tail = [(325, 1360), (275, 1420), (348, 1395)]
    else:
        box = (50, 1200, 765, 1545)
        tail = [(755, 1360), (810, 1420), (735, 1395)]
    d.rounded_rectangle(box, radius=44, fill=(255, 255, 255, 246), outline=accent, width=7)
    d.polygon(tail, fill=(255, 255, 255, 246))
    d.rounded_rectangle((box[0] + 22, box[1] + 17, box[0] + 132, box[1] + 58), radius=16, fill=(20, 20, 20, 232))
    d.text((box[0] + 43, box[1] + 24), "ZÉ", font=ImageFont.truetype(FONT_BOLD, 24), fill="white")

    font_size = 46 if len(lines) <= 2 else (40 if len(lines) == 3 else 35)
    font = ImageFont.truetype(FONT_BOLD, font_size)
    line_h = int(font_size * 1.23)
    text_area_top = box[1] + 76
    text_area_h = box[3] - text_area_top - 20
    yy = text_area_top + max(0, (text_area_h - len(lines) * line_h) // 2)
    for line in lines:
        tb = d.textbbox((0, 0), line, font=font)
        x = box[0] + ((box[2] - box[0]) - (tb[2] - tb[0])) // 2
        d.text((x, yy), line, font=font, fill=(18, 18, 18, 255))
        yy += line_h
    return im


def render_still_segment(image: Path, duration: float, out: Path, motion_idx: int) -> None:
    if duration <= 0.025:
        return
    z = "min(zoom+0.00018,1.018)" if motion_idx % 2 else "if(lte(zoom,1.0),1.018,max(1.0,zoom-0.00015))"
    vf = (
        f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        "d=1:s=1080x1920:fps=30,format=yuv420p"
    )
    run_quiet([
        "ffmpeg", "-y", "-loop", "1", "-i", str(image), "-t", f"{duration:.6f}",
        "-vf", vf, "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-g", "30", "-pix_fmt", "yuv420p", str(out),
    ])


def render_video(timing: list[dict], audio: Path) -> None:
    BUBBLE_FRAMES.mkdir(parents=True, exist_ok=True)
    pieces = VIDEO / "continuous_video_segments.txt"
    pieces.write_text("", encoding="utf-8")
    audio_duration = probe_duration(audio)
    cursor = 0.0
    segment_no = 0
    current_scene = 1

    def add_segment(frame_path: Path, duration: float) -> None:
        nonlocal segment_no
        if duration <= 0.025:
            return
        segment_no += 1
        out = VIDEO / f"visual_{segment_no:03d}.mp4"
        render_still_segment(frame_path, duration, out, segment_no)
        with pieces.open("a", encoding="utf-8") as f:
            f.write(f"file '{out.resolve()}'\n")

    for idx, item in enumerate(timing, 1):
        current_scene = item["scene"]
        scene_path = SCENES / f"scene_{current_scene:02d}.jpg"
        if item["start"] > cursor + 0.025:
            # Silêncio/pausa: mantém o Zé e o card, mas SEM texto fantasma.
            add_segment(scene_path, item["start"] - cursor)
            cursor = item["start"]

        cfg = card.SCENE_CONFIG[current_scene - 1]
        base_img = Image.open(scene_path).convert("RGBA")
        frame = draw_caption_bubble(base_img, item["text"], cfg["side"], cfg["accent"])
        frame_path = BUBBLE_FRAMES / f"caption_{idx:02d}_scene_{current_scene:02d}.jpg"
        frame.convert("RGB").save(frame_path, quality=95)
        add_segment(frame_path, item["end"] - item["start"])
        cursor = item["end"]

    if audio_duration > cursor + 0.025:
        add_segment(SCENES / f"scene_{current_scene:02d}.jpg", audio_duration - cursor)

    video_only = POST / "video_bubble_only_noaudio.mp4"
    run_quiet([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(pieces), "-c", "copy", str(video_only)
    ])

    final = POST / "ze_curioso_sapo_congela_final.mp4"
    # O áudio entra UMA vez, inteiro. Não existe corte ou concatenação de voz no vídeo final.
    run_quiet([
        "ffmpeg", "-y", "-i", str(video_only), "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-shortest", "-movflags", "+faststart", str(final),
    ])


def qa_and_copy(asr_ratio: float, alignment_ratio: float, timing: list[dict]) -> None:
    final = POST / "ze_curioso_sapo_congela_final.mp4"
    info = json.loads(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(final)], text=True
    ))
    duration = float(info["format"]["duration"])
    videos = [s for s in info["streams"] if s.get("codec_type") == "video"]
    audios = [s for s in info["streams"] if s.get("codec_type") == "audio"]
    if not videos or not audios:
        raise RuntimeError("QA: stream de vídeo ou áudio ausente")
    v, a = videos[0], audios[0]
    qa = {
        "duration_seconds": duration,
        "width": v.get("width"),
        "height": v.get("height"),
        "video_codec": v.get("codec_name"),
        "audio_codec": a.get("codec_name"),
        "duration_target_ok": 24.0 <= duration <= 52.0,
        "vertical_1080x1920_ok": v.get("width") == 1080 and v.get("height") == 1920,
        "h264_ok": v.get("codec_name") == "h264",
        "aac_ok": a.get("codec_name") == "aac",
        "continuous_audio_single_take": True,
        "microaudio_splicing": False,
        "external_caption_track": False,
        "captions_location": "Ze speech bubble only",
        "bubble_text_is_exact_narration": True,
        "bubble_sync": "faster-whisper word timestamps on the continuous narration",
        "tts_asr_exact_match_ratio": round(asr_ratio, 4),
        "alignment_exact_match_ratio": round(alignment_ratio, 4),
        "bubble_blocks": len(timing),
        "voice_reference": "VoxCPM2 take 02 original",
        "layout_revision": "card-v3-continuous-audio-bubble-captions",
    }
    qa["passed"] = all([
        qa["duration_target_ok"], qa["vertical_1080x1920_ok"], qa["h264_ok"], qa["aac_ok"],
        qa["tts_asr_exact_match_ratio"] >= 0.68,
    ])
    (POST / "qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    (POST / "bubble_timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8")
    if not qa["passed"]:
        raise RuntimeError(f"QA final falhou: {qa}")

    copy = """TÍTULO/CAPA:
O sapo que CONGELA e volta meses depois 🐸❄️

LEGENDA:
Esse sapo passa o inverno sem respirar e sem o coração bater — e depois descongela e volta à atividade. O segredo envolve uma carga enorme de glicose protegendo as células. 🐸❄️

#curiosidades #natureza #animais #ciencia #zecurioso #shorts #tiktokbr

Voz: VoxCPM2 — take 02 original aprovada do Zé Curioso.
Áudio: uma única tomada contínua, sem microáudios colados.
Legendas: exclusivamente dentro do balão do Zé, usando o texto exato da narração e sincronização por palavras.
"""
    (POST / "copy_postagem.txt").write_text(copy, encoding="utf-8")


def main() -> None:
    base.prepare_dirs()
    base.rebuild_mascot()
    base.download_voice_reference()
    base.download_frog_photos()
    card.build_scenes_card()
    (POST / "roteiro.txt").write_text(FULL_NARRATION, encoding="utf-8")
    audio, words, asr_ratio, _ = generate_continuous_narration()
    timing, alignment_ratio = build_block_timing(words)
    render_video(timing, audio)
    shutil.copy2(SCENES / "scene_01.jpg", POST / "capa_sapo_congela_final.jpg")
    qa_and_copy(asr_ratio, alignment_ratio, timing)
    print("FINAL_CONTINUOUS_BUBBLE_OK", POST / "ze_curioso_sapo_congela_final.mp4", flush=True)


if __name__ == "__main__":
    main()
