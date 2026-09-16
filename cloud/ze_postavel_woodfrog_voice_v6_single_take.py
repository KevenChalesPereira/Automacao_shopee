from __future__ import annotations

import json
import math
import shutil
import time
import wave
from pathlib import Path

import numpy as np

import ze_postavel_woodfrog_continuous_bubble as cont
import ze_postavel_woodfrog_scene_voice_bubble_v4 as v4

POST = cont.POST
ASSETS = cont.ASSETS
AUDIO = cont.AUDIO

# Mesmas palavras do vídeo aprovado; só a pontuação ajuda a interpretação.
FULL_SPEAK_TEXT = " ".join(v4.SCENE_SPEAK_TEXTS)

# Uma única instrução vale do primeiro ao último segundo. O objetivo é impedir
# que o modelo "reinicie" a emoção/tom a cada cena.
VOICE_CONTROL = (
    cont.base.VOICE_CONTROL
    + " Read the ENTIRE script as one uninterrupted conversational take from beginning to end."
    + " Keep one stable vocal identity, one stable pitch center, one stable speaking effort, and one stable microphone distance for the whole take."
    + " Do not restart your emotion or delivery after sentences or scene changes."
    + " Keep a naturally interested creator tone throughout: alive and warm, but controlled and consistent."
    + " Use only small natural emphasis on surprising words; never suddenly become flat, theatrical, louder, softer, darker or breathier."
    + " Absolutely avoid tremolo, wavering pitch, pitch flutter, shaky voice, vibrato, vocal fry, raspiness, hoarseness, breathy instability, clicks and swallowed syllables."
    + " Keep sentence endings firm and clean instead of trailing away."
    + " Target roughly 160 to 170 words per minute across the whole script."
)

# 'Zé' às vezes vira 'José' no Whisper mesmo quando o áudio está correto; não
# usamos esse token isolado como gate. 'Curioso' continua obrigatório.
CRITICAL = set().union(*v4.CRITICAL_TOKENS)
CRITICAL.discard("ze")
CRITICAL.add("descongela")

SELECTED_METRICS: dict = {}
ALL_CANDIDATES: list[dict] = []


def stability_metrics(path: Path) -> dict:
    """Mede microinstabilidade sem exigir voz artificialmente plana.

    O score combina jitter de F0 entre frames vizinhos, variação brusca de
    energia e deriva do centro de pitch entre começo/meio/fim. Ele serve para
    RANQUEAR tomadas inteiras; ASR e ritmo continuam sendo gates separados.
    """
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())
    if width != 2:
        raise RuntimeError(f"WAV inesperado: sampwidth={width}")
    x = np.frombuffer(frames, dtype=np.int16).astype(np.float64) / 32768.0
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)

    frame_n = max(960, int(sr * 0.040))
    hop = max(240, int(sr * 0.010))
    if len(x) < frame_n * 2:
        return {"f0_jitter": 1.0, "energy_jitter": 1.0, "pitch_section_drift": 1.0, "stability_score": 0.0, "voiced_frames": 0}

    rms_rows: list[tuple[int, float]] = []
    for pos in range(0, len(x) - frame_n, hop):
        fr = x[pos:pos + frame_n]
        rms_rows.append((pos, float(np.sqrt(np.mean(fr * fr) + 1e-12))))
    rms_values = np.array([r for _, r in rms_rows], dtype=np.float64)
    p90 = float(np.percentile(rms_values, 90))
    threshold = max(0.0025, p90 * 0.10)

    f0_rows: list[tuple[int, float, float]] = []
    window = np.hanning(frame_n)
    min_lag = max(1, int(sr / 300.0))
    max_lag = min(frame_n - 2, int(sr / 75.0))

    for pos, rms in rms_rows:
        if rms < threshold:
            continue
        fr = x[pos:pos + frame_n]
        fr = (fr - np.mean(fr)) * window
        energy = float(np.dot(fr, fr))
        if energy < 1e-8:
            continue
        corr = np.correlate(fr, fr, mode="full")[frame_n - 1:]
        search = corr[min_lag:max_lag + 1]
        if not len(search):
            continue
        lag = min_lag + int(np.argmax(search))
        quality = float(corr[lag] / max(corr[0], 1e-12))
        if quality < 0.30:
            continue
        f0 = float(sr / lag)
        if 75.0 <= f0 <= 300.0:
            f0_rows.append((pos, f0, rms))

    if len(f0_rows) < 20:
        return {"f0_jitter": 0.20, "energy_jitter": 0.50, "pitch_section_drift": 0.50, "stability_score": 0.10, "voiced_frames": len(f0_rows)}

    pitch_jumps: list[float] = []
    energy_jumps: list[float] = []
    for (p0, f0a, e0), (p1, f0b, e1) in zip(f0_rows, f0_rows[1:]):
        if p1 - p0 > hop * 2:
            continue
        pitch_jumps.append(abs(math.log(max(f0b, 1e-6) / max(f0a, 1e-6))))
        energy_jumps.append(abs(math.log(max(e1, 1e-6) / max(e0, 1e-6))))

    f0_jitter = float(np.median(pitch_jumps)) if pitch_jumps else 0.20
    energy_jitter = float(np.median(energy_jumps)) if energy_jumps else 0.50

    total = max(1, len(x) - frame_n)
    thirds: list[list[float]] = [[], [], []]
    for pos, f0, _ in f0_rows:
        thirds[min(2, int((pos / total) * 3))].append(f0)
    section_medians = [float(np.median(v)) for v in thirds if len(v) >= 3]
    global_median = float(np.median([f for _, f, _ in f0_rows]))
    pitch_drift = max((abs(v - global_median) / max(global_median, 1.0) for v in section_medians), default=0.0)

    # Score deliberadamente suave: queremos escolher a tomada mais estável,
    # não achatar a prosódia natural.
    penalty = 5.0 * f0_jitter + 0.55 * min(energy_jitter, 0.8) + 1.15 * pitch_drift
    stability = max(0.0, min(1.0, 1.0 - penalty))
    return {
        "f0_jitter": round(f0_jitter, 5),
        "energy_jitter": round(energy_jitter, 5),
        "pitch_section_drift": round(pitch_drift, 5),
        "stability_score": round(stability, 5),
        "voiced_frames": len(f0_rows),
        "pitch_section_medians_hz": [round(v, 2) for v in section_medians],
    }


def generate_single_take() -> tuple[Path, list[dict], float, str]:
    global SELECTED_METRICS, ALL_CANDIDATES

    client = cont.base.Client("openbmb/VoxCPM-Demo", verbose=False)
    ref = cont.base.handle_file(str(ASSETS / "voice_ref.mp3"))
    model = v4.WhisperModel("small", device="cpu", compute_type="int8")
    expected = v4.words_from_text(cont.FULL_NARRATION)
    valid: list[dict] = []
    all_rows: list[dict] = []

    for attempt in range(1, 6):
        print(f"SINGLE_TAKE_ATTEMPT {attempt}", flush=True)
        result = client.predict(
            FULL_SPEAK_TEXT, VOICE_CONTROL, ref, False, "", 2.0, True, False, api_name="/generate"
        )
        src = Path(cont.base.extract_path(result))
        if not src.exists() or src.stat().st_size < 12000:
            print("REJECT_EMPTY", attempt, flush=True)
            time.sleep(3)
            continue

        raw = AUDIO / f"single_take_candidate_{attempt:02d}.wav"
        v4.run(["ffmpeg", "-y", "-i", str(src), "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(raw)])
        duration = v4.probe_duration(raw)
        if not 24.0 <= duration <= 50.0:
            print("REJECT_DURATION", attempt, round(duration, 3), flush=True)
            continue

        words, transcript = v4.transcribe(model, raw)
        if not words:
            continue
        mapping, ratio = v4.align_tokens(expected, [w["norm"] for w in words])
        actual_set = {w["norm"] for w in words}
        missing = sorted(CRITICAL - actual_set)
        span = max(0.5, words[-1]["end"] - words[0]["start"])
        wpm = len(expected) * 60.0 / span
        stab = stability_metrics(raw)

        pace_penalty = abs(wpm - 165.0) / 55.0
        score = ratio * 5.0 + stab["stability_score"] * 2.2 - pace_penalty - len(missing) * 0.45
        row = {
            "attempt": attempt,
            "path": raw.name,
            "duration": round(duration, 3),
            "asr_ratio": round(ratio, 4),
            "missing_critical": missing,
            "wpm": round(wpm, 2),
            "score": round(score, 5),
            **stab,
            "transcript": transcript,
        }
        all_rows.append(row)
        print("SINGLE_TAKE_QA", json.dumps(row, ensure_ascii=False), flush=True)

        # Gates: fala correta, palavras críticas, ritmo saudável e nenhum sinal
        # extremo de tremor/deriva. Depois ranqueamos TODOS os takes válidos.
        if (
            ratio >= 0.90
            and not missing
            and 145.0 <= wpm <= 185.0
            and stab["f0_jitter"] <= 0.085
            and stab["pitch_section_drift"] <= 0.32
        ):
            valid.append({
                "score": score,
                "raw": raw,
                "words": words,
                "mapping": mapping,
                "ratio": ratio,
                "transcript": transcript,
                "wpm": wpm,
                "metrics": row,
            })
        time.sleep(2)

    ALL_CANDIDATES = all_rows
    if not valid:
        (POST / "voice_consistency.json").write_text(
            json.dumps({"selected": None, "candidates": all_rows}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        raise RuntimeError("Nenhuma tomada única passou simultaneamente em dicção, ritmo e estabilidade de voz")

    best = max(valid, key=lambda x: x["score"])
    raw = best["raw"]
    first = best["words"][0]["start"]
    last = best["words"][-1]["end"]
    trim_start = max(0.0, first - 0.08)
    raw_duration = v4.probe_duration(raw)
    trim_end = min(raw_duration, last + 0.18)
    trimmed_duration = max(0.5, trim_end - trim_start)

    final_audio = AUDIO / "narration_continuous.wav"
    # UMA normalização no arquivo inteiro. Não existe corte/fade entre cenas.
    v4.run([
        "ffmpeg", "-y", "-ss", f"{trim_start:.4f}", "-t", f"{trimmed_duration:.4f}",
        "-i", str(raw),
        "-af", "loudnorm=I=-16:TP=-2:LRA=8",
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(final_audio),
    ])

    shifted_words = [
        {**w, "start": max(0.0, w["start"] - trim_start), "end": max(0.0, w["end"] - trim_start)}
        for w in best["words"]
    ]
    SELECTED_METRICS = {**best["metrics"], "accepted_file": final_audio.name}
    (POST / "voice_consistency.json").write_text(
        json.dumps({"selected": SELECTED_METRICS, "candidates": all_rows}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (POST / "asr_transcript.txt").write_text(best["transcript"], encoding="utf-8")
    (POST / "alignment_words.json").write_text(json.dumps(shifted_words, ensure_ascii=False, indent=2), encoding="utf-8")
    return final_audio, shifted_words, best["ratio"], best["transcript"]


def qa_final(asr_ratio: float, alignment_ratio: float, timing: list[dict]) -> None:
    # Reaproveita toda a checagem técnica do renderer contínuo e endurece a
    # parte de voz para esta versão final.
    cont._qa_original(asr_ratio, alignment_ratio, timing)
    qa_path = POST / "qa.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    qa.update({
        "audio_generation_mode": "ONE uninterrupted full-script VoxCPM2 take",
        "scene_audio_concatenation": False,
        "scene_audio_fades": False,
        "voice_style_reset_between_scenes": False,
        "voice_selection": "best full take by ASR + pace + pitch/energy stability",
        "selected_voice_metrics": SELECTED_METRICS,
        "revision": "card-v6-single-take-stable-intonation",
    })
    qa["passed"] = bool(qa.get("passed")) and all([
        asr_ratio >= 0.90,
        alignment_ratio >= 0.90,
        145.0 <= float(SELECTED_METRICS.get("wpm", 0)) <= 185.0,
        float(SELECTED_METRICS.get("f0_jitter", 1)) <= 0.085,
        float(SELECTED_METRICS.get("pitch_section_drift", 1)) <= 0.32,
        not SELECTED_METRICS.get("missing_critical"),
    ])
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    if not qa["passed"]:
        raise RuntimeError(f"QA V6 single-take falhou: {qa}")

    copy_path = POST / "copy_postagem.txt"
    copy_path.write_text(
        copy_path.read_text(encoding="utf-8")
        + "\nV6 voz: tomada única do roteiro inteiro, escolhida por dicção, ritmo e estabilidade; sem reinício de entonação por cena.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    # Melhora o alinhamento do renderer contínuo: trata 'pra'/'para' como equivalentes.
    cont.words_from_text = v4.words_from_text
    cont.align_tokens = v4.align_tokens
    cont.generate_continuous_narration = generate_single_take
    cont._qa_original = cont.qa_and_copy
    cont.qa_and_copy = qa_final
    cont.main()
