from __future__ import annotations

import json
import math
import shutil
import time
import wave
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

import ze_postavel_woodfrog_scene_voice_bubble_v4 as v4

POST = v4.POST
ASSETS = v4.ASSETS
AUDIO = v4.AUDIO
SCENES = v4.SCENES

# Same words/content as V4. Only punctuation/emphasis changes to guide delivery.
SCENE_SPEAK_TEXTS = [
    "Esse sapo CONGELA no inverno! Para de respirar. E o coração, simplesmente... para de bater.",
    "E o mais absurdo? Meses depois... ele descongela! E sai andando como se nada tivesse acontecido. É o sapo da floresta.",
    "Quando a temperatura cai... o fígado libera MUITA glicose. Ela protege as células, enquanto o gelo se forma ao redor delas.",
    "Na primavera, ele descongela de dentro pra fora! Primeiro, o coração volta. Depois, o cérebro. E, por fim... as pernas.",
    "Parece ficção... mas é sobrevivência REAL! A natureza consegue ser mais estranha que qualquer filme. Eu sou o Zé Curioso. E aqui... parece mentira, mas é real!",
]

SCENE_STYLE = [
    "Start curious and alert, then build genuine disbelief. Give clear conversational emphasis to 'congela' and 'para de bater'.",
    "Sound honestly amazed, with a slight smile in the voice. Lift the energy on 'meses depois' and 'ele descongela', then land the final identification clearly.",
    "Switch to an engaging 'here is the secret' explanation. Keep warmth and curiosity; make 'muita glicose' feel like the reveal, not like a lecture.",
    "Build the sequence step by step with forward momentum. Give each stage a small melodic lift so the list never sounds flat.",
    "Deliver a satisfying payoff: surprised first, then warm and confident. Brighten naturally on 'Zé Curioso' and finish the catchphrase with a clear smile, not an announcer voice.",
]

VOICE_CONTROL = (
    v4.base.VOICE_CONTROL
    + " Speak each scene as one continuous natural take, like an energetic creator talking to one friend."
    + " Keep the exact reference timbre and clean articulation, but DO NOT sound flat, tired, sleepy or emotionally neutral."
    + " Use natural pitch movement, small pace changes, conversational emphasis and decisive sentence endings."
    + " Energy target is about 6.5 out of 10: lively and curious, never shouting, never theatrical, never radio-announcer style."
    + " Avoid raspiness, hoarseness, vocal fry, clicks, slurring and swallowed syllables."
    + " Target about 160 to 170 words per minute."
)


def audio_energy_metrics(path: Path) -> dict:
    with wave.open(str(path), "rb") as wf:
        rate = wf.getframerate()
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())
    if width != 2:
        return {"energy_range_db": 0.0, "energy_std_db": 0.0}
    data = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    data /= 32768.0
    frame = max(1, int(rate * 0.030))
    hop = max(1, int(rate * 0.015))
    vals = []
    for start in range(0, max(1, len(data) - frame + 1), hop):
        x = data[start:start + frame]
        if len(x) < frame // 2:
            continue
        rms = float(np.sqrt(np.mean(x * x) + 1e-12))
        vals.append(20.0 * math.log10(rms + 1e-9))
    if len(vals) < 8:
        return {"energy_range_db": 0.0, "energy_std_db": 0.0}
    arr = np.asarray(vals, dtype=np.float32)
    floor = max(-46.0, float(np.percentile(arr, 25)))
    active = arr[arr >= floor]
    if len(active) < 8:
        active = arr
    return {
        "energy_range_db": float(np.percentile(active, 90) - np.percentile(active, 10)),
        "energy_std_db": float(np.std(active)),
    }


def prosody_metrics(path: Path, words: list[dict], duration: float) -> dict:
    energy = audio_energy_metrics(path)
    word_durations = np.asarray([
        max(0.01, float(w["end"]) - float(w["start"])) for w in words
    ], dtype=np.float32)
    gaps = np.asarray([
        max(0.0, float(words[i]["start"]) - float(words[i - 1]["end"]))
        for i in range(1, len(words))
    ], dtype=np.float32)
    wpm = len(words) * 60.0 / max(duration, 0.1)
    duration_cv = float(np.std(word_durations) / max(float(np.mean(word_durations)), 1e-6)) if len(word_durations) else 0.0
    gap_p90 = float(np.percentile(gaps, 90)) if len(gaps) else 0.0

    energy_score = min(1.0, max(0.0, (energy["energy_range_db"] - 4.0) / 10.0))
    pace_score = math.exp(-((wpm - 165.0) / 24.0) ** 2)
    timing_score = min(1.0, duration_cv / 0.48) * 0.65 + min(1.0, gap_p90 / 0.20) * 0.35
    lively = 0.50 * energy_score + 0.30 * pace_score + 0.20 * timing_score
    return {
        **energy,
        "words_per_minute": round(wpm, 2),
        "word_duration_cv": round(duration_cv, 4),
        "pause_p90_s": round(gap_p90, 4),
        "liveliness_score": round(float(lively), 4),
    }


def generate_scene_take(scene_idx: int, client, ref, model: WhisperModel) -> dict:
    text = SCENE_SPEAK_TEXTS[scene_idx - 1]
    prompt = VOICE_CONTROL + " " + SCENE_STYLE[scene_idx - 1]
    candidates: list[dict] = []
    fallback = None

    # Do not stop at the first intelligible take. Compare several good takes and keep the liveliest one.
    for attempt in range(1, 6):
        print(f"SCENE_{scene_idx:02d}_V5_ATTEMPT {attempt}", flush=True)
        try:
            result = client.predict(
                text, prompt, ref, False, "", 2.0, True, False, api_name="/generate"
            )
        except Exception as exc:
            msg = str(exc).lower()
            if "queue is full" in msg or "429" in msg or "busy" in msg:
                time.sleep(min(12 + attempt * 3, 30))
                continue
            raise

        src = Path(v4.base.extract_path(result))
        if not src.exists() or src.stat().st_size < 8000:
            continue

        raw = AUDIO / f"scene_{scene_idx:02d}_v5_candidate_{attempt:02d}.wav"
        v4.run(["ffmpeg", "-y", "-i", str(src), "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(raw)])
        duration = v4.probe_duration(raw)
        if not 2.0 <= duration <= 14.0:
            continue

        words, transcript = v4.transcribe(model, raw)
        if not words:
            continue
        ratio, critical_ok, missing, mapping = v4.scene_score(scene_idx, words)
        prosody = prosody_metrics(raw, words, duration)
        candidate = {
            "ratio": ratio,
            "critical_ok": critical_ok,
            "missing_critical": missing,
            "raw": raw,
            "words": words,
            "mapping": mapping,
            "transcript": transcript,
            "duration": duration,
            "prosody": prosody,
        }
        candidate["score"] = ratio + (0.10 if critical_ok else -0.30) + 0.16 * prosody["liveliness_score"]
        print(
            "SCENE_V5_QA", scene_idx,
            "ratio", round(ratio, 4),
            "critical_ok", critical_ok,
            "liveliness", prosody["liveliness_score"],
            "wpm", prosody["words_per_minute"],
            "energy_range_db", round(prosody["energy_range_db"], 2),
            "transcript", transcript,
            flush=True,
        )
        if fallback is None or candidate["score"] > fallback["score"]:
            fallback = candidate
        if ratio >= 0.94 and critical_ok:
            candidates.append(candidate)
        if len(candidates) >= 3:
            break
        time.sleep(2)

    if not candidates:
        raise RuntimeError(
            f"Cena {scene_idx} sem take V5 aceitável. "
            f"best_ratio={fallback['ratio'] if fallback else None} "
            f"missing={fallback['missing_critical'] if fallback else None}"
        )

    best = max(candidates, key=lambda c: (c["prosody"]["liveliness_score"], c["ratio"]))
    print(
        "SCENE_V5_SELECTED", scene_idx,
        "candidate", best["raw"].name,
        "ratio", round(best["ratio"], 4),
        "liveliness", best["prosody"]["liveliness_score"],
        flush=True,
    )

    first = best["words"][0]["start"]
    last = best["words"][-1]["end"]
    trim_start = max(0.0, first - 0.08)
    trim_end = min(best["duration"], last + 0.18)
    trimmed_duration = max(0.5, trim_end - trim_start)
    out = AUDIO / f"scene_{scene_idx:02d}_accepted.wav"
    fade_out_start = max(0.0, trimmed_duration - 0.012)
    af = (
        "loudnorm=I=-16:TP=-2:LRA=8,"
        "afade=t=in:st=0:d=0.010,"
        f"afade=t=out:st={fade_out_start:.4f}:d=0.012"
    )
    v4.run([
        "ffmpeg", "-y", "-ss", f"{trim_start:.4f}", "-t", f"{trimmed_duration:.4f}",
        "-i", str(best["raw"]), "-af", af,
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(out),
    ])

    best["words"] = [
        {
            **w,
            "start": max(0.0, w["start"] - trim_start),
            "end": max(0.0, w["end"] - trim_start),
        }
        for w in best["words"]
    ]
    best["accepted"] = out
    best["accepted_duration"] = v4.probe_duration(out)
    return best


def final_qa_v5(results: list[dict], timing: list[dict], alignment_ratio: float, narration: Path) -> None:
    v4.final_qa(results, timing, alignment_ratio, narration)
    qa_path = POST / "qa.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    qa["revision"] = "card-v5-final-lively-voice-bubble-only"
    qa["voice_delivery"] = "lively conversational creator; selected among multiple intelligible takes"
    qa["voice_target_wpm"] = "160-170"
    qa["flat_delivery_guard"] = True
    qa["candidate_selection"] = "ASR correctness first; then highest measured liveliness among valid takes"
    qa["scene_prosody"] = [
        {"scene": i, **r["prosody"]} for i, r in enumerate(results, 1)
    ]
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")

    copy_path = POST / "copy_postagem.txt"
    if copy_path.exists():
        text = copy_path.read_text(encoding="utf-8")
        text += "\nVoz final V5: entre tomadas corretamente pronunciadas, o pipeline escolhe a de interpretação mais viva e conversacional.\n"
        copy_path.write_text(text, encoding="utf-8")


def main() -> None:
    v4.base.prepare_dirs()
    v4.base.rebuild_mascot()
    v4.base.download_voice_reference()
    v4.base.download_frog_photos()
    v4.card.build_scenes_card()
    (POST / "roteiro.txt").write_text(" ".join(v4.SCENE_DISPLAY_TEXTS), encoding="utf-8")

    client = v4.base.Client("openbmb/VoxCPM-Demo", verbose=False)
    ref = v4.base.handle_file(str(ASSETS / "voice_ref.mp3"))
    model = WhisperModel("small", device="cpu", compute_type="int8")

    results = [generate_scene_take(i, client, ref, model) for i in range(1, 6)]
    narration, offsets = v4.concat_scenes(results)
    timing, alignment_ratio = v4.build_bubble_timing(results, offsets)
    v4.bubble.render_video(timing, narration)
    shutil.copy2(SCENES / "scene_01.jpg", POST / "capa_sapo_congela_final.jpg")
    final_qa_v5(results, timing, alignment_ratio, narration)
    print("FINAL_V5_LIVELY_VOICE_OK", POST / "ze_curioso_sapo_congela_final.mp4", flush=True)


if __name__ == "__main__":
    main()
