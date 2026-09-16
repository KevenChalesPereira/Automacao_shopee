from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path

from faster_whisper import WhisperModel

import ze_postavel_woodfrog_final as base
import ze_postavel_woodfrog_card_sync as card
import ze_postavel_woodfrog_continuous_bubble as bubble

POST = base.POST
ASSETS = base.ASSETS
AUDIO = base.AUDIO
SCENES = base.SCENES
VIDEO = base.VIDEO

SCENE_DISPLAY_TEXTS = [
    " ".join(block["text"] for block in blocks)
    for blocks in card.SCENE_BLOCKS
]

# Texto falado mantém as mesmas palavras, mas usa pontuação que ajuda o VoxCPM2 a articular melhor.
SCENE_SPEAK_TEXTS = [
    "Esse sapo congela no inverno. Para de respirar. E o coração simplesmente... para de bater.",
    "E o mais absurdo: meses depois... ele descongela. E sai andando como se nada tivesse acontecido. É o sapo da floresta.",
    "Quando a temperatura cai, o fígado libera muita glicose. Ela protege as células enquanto o gelo se forma ao redor delas.",
    "Na primavera, ele descongela de dentro pra fora: primeiro o coração volta. Depois o cérebro. E, por fim, as pernas.",
    "Parece ficção, mas é sobrevivência real. A natureza consegue ser mais estranha que qualquer filme. Eu sou o Zé Curioso. E aqui... parece mentira, mas é real.",
]

CRITICAL_TOKENS = [
    {"sapo", "congela", "respirar", "coracao", "bater"},
    {"meses", "descongela", "andando", "floresta"},
    {"figado", "glicose", "celulas", "gelo"},
    {"primavera", "coracao", "cerebro", "pernas"},
    {"sobrevivencia", "natureza", "ze", "curioso", "mentira", "real"},
]

VOICE_CONTROL = (
    base.VOICE_CONTROL
    + " Speak this scene as one continuous natural take. Prioritize clean articulation over speed."
    + " Keep the exact reference timbre, but avoid raspiness, hoarseness, vocal fry, clicks, slurring and swallowed syllables."
    + " Make every content word intelligible in Brazilian Portuguese. Do not merge separate words."
    + " Finish sentences cleanly; never trail off or distort the final word."
    + " Target about 150 to 160 words per minute."
)

ALIASES = {
    "pra": "para",
}


def run(args: list[str]) -> None:
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def probe_duration(path: Path) -> float:
    return float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path)
    ], text=True).strip())


def norm_word(value: str) -> str:
    value = unicodedata.normalize("NFD", value.lower())
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = "".join(ch for ch in value if ch.isalnum())
    return ALIASES.get(value, value)


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
            sub = 0 if expected[i - 1] == actual[j - 1] else 1
            dp[i][j], back[i][j] = min(
                (dp[i - 1][j - 1] + sub, "M"),
                (dp[i - 1][j] + 1, "D"),
                (dp[i][j - 1] + 1, "I"),
                key=lambda x: x[0],
            )
    mapping: list[int | None] = [None] * n
    exact = 0
    i, j = n, m
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


def transcribe(model: WhisperModel, audio: Path) -> tuple[list[dict], str]:
    segments, _ = model.transcribe(
        str(audio), language="pt", beam_size=5, word_timestamps=True,
        vad_filter=False, condition_on_previous_text=True,
    )
    words: list[dict] = []
    transcript: list[str] = []
    for seg in segments:
        if seg.text.strip():
            transcript.append(seg.text.strip())
        for word in seg.words or []:
            token = norm_word(word.word)
            if not token:
                continue
            words.append({
                "word": word.word.strip(),
                "norm": token,
                "start": float(word.start),
                "end": float(word.end),
                "probability": float(getattr(word, "probability", 0.0) or 0.0),
            })
    return words, " ".join(transcript)


def scene_score(scene_idx: int, words: list[dict]) -> tuple[float, bool, list[str], list[int | None]]:
    expected = words_from_text(SCENE_DISPLAY_TEXTS[scene_idx - 1])
    actual = [w["norm"] for w in words]
    mapping, ratio = align_tokens(expected, actual)
    actual_set = set(actual)
    missing_critical = sorted(CRITICAL_TOKENS[scene_idx - 1] - actual_set)
    return ratio, not missing_critical, missing_critical, mapping


def generate_scene_take(scene_idx: int, client, ref, model: WhisperModel) -> dict:
    text = SCENE_SPEAK_TEXTS[scene_idx - 1]
    best = None
    for attempt in range(1, 6):
        print(f"SCENE_{scene_idx:02d}_TTS_ATTEMPT {attempt}", flush=True)
        result = client.predict(
            text, VOICE_CONTROL, ref, False, "", 2.0, True, False, api_name="/generate"
        )
        src = Path(base.extract_path(result))
        if not src.exists() or src.stat().st_size < 8000:
            time.sleep(3)
            continue

        raw = AUDIO / f"scene_{scene_idx:02d}_candidate_{attempt:02d}.wav"
        run(["ffmpeg", "-y", "-i", str(src), "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(raw)])
        duration = probe_duration(raw)
        if not 2.0 <= duration <= 14.0:
            print("REJECT_DURATION", scene_idx, round(duration, 3), flush=True)
            continue

        words, transcript = transcribe(model, raw)
        if not words:
            continue
        ratio, critical_ok, missing, mapping = scene_score(scene_idx, words)
        score = ratio + (0.10 if critical_ok else -0.30)
        print(
            "SCENE_QA", scene_idx, "ratio", round(ratio, 4),
            "critical_ok", critical_ok, "missing", missing,
            "transcript", transcript,
            flush=True,
        )
        candidate = {
            "score": score,
            "ratio": ratio,
            "critical_ok": critical_ok,
            "missing_critical": missing,
            "raw": raw,
            "words": words,
            "mapping": mapping,
            "transcript": transcript,
            "duration": duration,
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate
        # Threshold deliberately strict: the previous V3 at 0.8922 sounded wrong.
        if ratio >= 0.94 and critical_ok:
            break
        time.sleep(3)

    if best is None or best["ratio"] < 0.92 or not best["critical_ok"]:
        raise RuntimeError(
            f"Cena {scene_idx} rejeitada pelo QA de voz. "
            f"best_ratio={best['ratio'] if best else None} missing={best['missing_critical'] if best else None}"
        )

    # Trim only long dead air around the accepted take, then normalize loudness and add tiny fades.
    first = best["words"][0]["start"]
    last = best["words"][-1]["end"]
    trim_start = max(0.0, first - 0.08)
    trim_end = min(best["duration"], last + 0.18)
    trimmed_duration = max(0.5, trim_end - trim_start)
    out = AUDIO / f"scene_{scene_idx:02d}_accepted.wav"
    fade_out_start = max(0.0, trimmed_duration - 0.012)
    af = (
        "loudnorm=I=-16:TP=-2:LRA=7,"
        "afade=t=in:st=0:d=0.010,"
        f"afade=t=out:st={fade_out_start:.4f}:d=0.012"
    )
    run([
        "ffmpeg", "-y", "-ss", f"{trim_start:.4f}", "-t", f"{trimmed_duration:.4f}",
        "-i", str(best["raw"]), "-af", af,
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(out),
    ])

    # Word times are stable under trim/normalization; shift them to accepted-file time.
    shifted_words = []
    for w in best["words"]:
        shifted_words.append({
            **w,
            "start": max(0.0, w["start"] - trim_start),
            "end": max(0.0, w["end"] - trim_start),
        })
    best["accepted"] = out
    best["words"] = shifted_words
    best["accepted_duration"] = probe_duration(out)
    return best


def make_silence() -> Path:
    out = AUDIO / "scene_transition_100ms.wav"
    run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
        "-t", "0.10", "-c:a", "pcm_s16le", str(out),
    ])
    return out


def concat_scenes(results: list[dict]) -> tuple[Path, list[float]]:
    silence = make_silence()
    listing = AUDIO / "scene_audio_concat.txt"
    offsets: list[float] = []
    cursor = 0.0
    lines: list[str] = []
    for idx, result in enumerate(results):
        offsets.append(cursor)
        lines.append(f"file '{result['accepted'].resolve()}'")
        cursor += probe_duration(result["accepted"])
        if idx < len(results) - 1:
            lines.append(f"file '{silence.resolve()}'")
            cursor += 0.10
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = AUDIO / "narration_scene_clean.wav"
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(out),
    ])
    return out, offsets


def build_bubble_timing(results: list[dict], offsets: list[float]) -> tuple[list[dict], float]:
    timing: list[dict] = []
    ratios: list[float] = []
    for scene_idx, (result, offset) in enumerate(zip(results, offsets), 1):
        expected: list[str] = []
        ranges: list[tuple[int, int]] = []
        for block in card.SCENE_BLOCKS[scene_idx - 1]:
            start = len(expected)
            expected.extend(words_from_text(block["text"]))
            ranges.append((start, len(expected)))
        mapping, ratio = align_tokens(expected, [w["norm"] for w in result["words"]])
        ratios.append(ratio)
        for block_idx, (block, (a, b)) in enumerate(zip(card.SCENE_BLOCKS[scene_idx - 1], ranges), 1):
            ids = [mapping[i] for i in range(a, b) if mapping[i] is not None]
            if not ids:
                raise RuntimeError(f"Sem alinhamento para balão {scene_idx}.{block_idx}")
            first, last = min(ids), max(ids)
            start = offset + max(0.0, result["words"][first]["start"] - 0.04)
            end = offset + result["words"][last]["end"] + 0.06
            timing.append({
                "scene": scene_idx,
                "block": block_idx,
                "text": block["text"],
                "start": round(start, 3),
                "end": round(end, 3),
                "seconds": round(end - start, 3),
                "first_asr_word": result["words"][first]["word"],
                "last_asr_word": result["words"][last]["word"],
                "sync_method": "scene-level clean TTS + Whisper word alignment",
                "caption_location": "Ze speech bubble only",
            })
    for i in range(len(timing) - 1):
        if timing[i]["end"] > timing[i + 1]["start"]:
            cut = (timing[i]["end"] + timing[i + 1]["start"]) / 2
            timing[i]["end"] = round(cut, 3)
            timing[i + 1]["start"] = round(cut, 3)
            timing[i]["seconds"] = round(timing[i]["end"] - timing[i]["start"], 3)
            timing[i + 1]["seconds"] = round(timing[i + 1]["end"] - timing[i + 1]["start"], 3)
    return timing, sum(ratios) / len(ratios)


def final_qa(results: list[dict], timing: list[dict], alignment_ratio: float, narration: Path) -> None:
    final = POST / "ze_curioso_sapo_congela_final.mp4"
    info = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(final)
    ], text=True))
    v = next(s for s in info["streams"] if s.get("codec_type") == "video")
    a = next(s for s in info["streams"] if s.get("codec_type") == "audio")
    duration = float(info["format"]["duration"])
    scene_qa = []
    for i, result in enumerate(results, 1):
        scene_qa.append({
            "scene": i,
            "asr_ratio": round(result["ratio"], 4),
            "critical_ok": result["critical_ok"],
            "missing_critical": result["missing_critical"],
            "transcript": result["transcript"],
            "accepted_audio": result["accepted"].name,
        })
    qa = {
        "duration_seconds": duration,
        "width": v.get("width"),
        "height": v.get("height"),
        "video_codec": v.get("codec_name"),
        "audio_codec": a.get("codec_name"),
        "vertical_1080x1920_ok": v.get("width") == 1080 and v.get("height") == 1920,
        "h264_ok": v.get("codec_name") == "h264",
        "aac_ok": a.get("codec_name") == "aac",
        "audio_generation_mode": "5 scene-level continuous takes with strict per-scene ASR QA",
        "micro_phrase_splicing": False,
        "scene_transition_silence_ms": 100,
        "external_caption_track": False,
        "captions_location": "Ze speech bubble only",
        "bubble_sync": "Whisper word timestamps per accepted scene",
        "bubble_alignment_ratio": round(alignment_ratio, 4),
        "voice_reference": "VoxCPM2 take 02 original",
        "scene_qa": scene_qa,
        "revision": "card-v4-scene-voice-strict-qa-bubble-only",
    }
    qa["passed"] = all([
        qa["vertical_1080x1920_ok"], qa["h264_ok"], qa["aac_ok"],
        qa["bubble_alignment_ratio"] >= 0.92,
        all(x["asr_ratio"] >= 0.92 and x["critical_ok"] for x in scene_qa),
    ])
    (POST / "qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    (POST / "bubble_timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8")
    (POST / "asr_transcript.txt").write_text(
        "\n".join(f"Cena {i}: {r['transcript']}" for i, r in enumerate(results, 1)) + "\n",
        encoding="utf-8",
    )
    if not qa["passed"]:
        raise RuntimeError(f"QA V4 falhou: {qa}")

    (POST / "copy_postagem.txt").write_text(
        """TÍTULO/CAPA:\nO sapo que CONGELA e volta meses depois 🐸❄️\n\nLEGENDA:\nEsse sapo passa o inverno sem respirar e sem o coração bater — e depois descongela e volta à atividade. O segredo envolve uma carga enorme de glicose protegendo as células. 🐸❄️\n\n#curiosidades #natureza #animais #ciencia #zecurioso #shorts #tiktokbr\n\nVoz: VoxCPM2 — take 02 original aprovada do Zé Curioso.\nÁudio: 5 tomadas completas, uma por cena, com QA de fala antes da montagem.\nLegendas: somente no balão do Zé; não existe legenda externa.\n""",
        encoding="utf-8",
    )


def main() -> None:
    base.prepare_dirs()
    base.rebuild_mascot()
    base.download_voice_reference()
    base.download_frog_photos()
    card.build_scenes_card()
    (POST / "roteiro.txt").write_text(" ".join(SCENE_DISPLAY_TEXTS), encoding="utf-8")

    client = base.Client("openbmb/VoxCPM-Demo", verbose=False)
    ref = base.handle_file(str(ASSETS / "voice_ref.mp3"))
    # Small é mais confiável em português que base e o áudio é curto o bastante para CPU.
    model = WhisperModel("small", device="cpu", compute_type="int8")

    results = [generate_scene_take(i, client, ref, model) for i in range(1, 6)]
    narration, offsets = concat_scenes(results)
    timing, alignment_ratio = build_bubble_timing(results, offsets)
    bubble.render_video(timing, narration)
    shutil.copy2(SCENES / "scene_01.jpg", POST / "capa_sapo_congela_final.jpg")
    final_qa(results, timing, alignment_ratio, narration)
    print("FINAL_V4_SCENE_VOICE_BUBBLE_OK", POST / "ze_curioso_sapo_congela_final.mp4", flush=True)


if __name__ == "__main__":
    main()
