from __future__ import annotations

import difflib
import json
import shutil
import time
from pathlib import Path

import ze_postavel_woodfrog_voice_v6_retry as retry

v6 = retry.v6
cont = v6.cont
v4 = v6.v4

# Fonte única da verdade para a narração e para os balões.
# Remove definitivamente o fechamento antigo "Eu sou o Zé Curioso / E aqui...".
FINAL_BLOCKS = [
    {"scene": 1, "block": 1, "text": "Esse sapo congela no inverno."},
    {"scene": 1, "block": 2, "text": "Para de respirar."},
    {"scene": 1, "block": 3, "text": "E o coração simplesmente para de bater."},
    {"scene": 2, "block": 1, "text": "E o mais absurdo: meses depois..."},
    {"scene": 2, "block": 2, "text": "Ele descongela."},
    {"scene": 2, "block": 3, "text": "E sai andando como se nada tivesse acontecido. É o sapo-da-floresta."},
    {"scene": 3, "block": 1, "text": "Quando a temperatura cai, o fígado libera muita glicose."},
    {"scene": 3, "block": 2, "text": "Ela protege as células enquanto o gelo se forma ao redor delas."},
    {"scene": 4, "block": 1, "text": "Na primavera, ele descongela de dentro pra fora: primeiro o coração volta."},
    {"scene": 4, "block": 2, "text": "Depois o cérebro."},
    {"scene": 4, "block": 3, "text": "E, por fim, as pernas."},
    {"scene": 5, "block": 1, "text": "Parece ficção, mas é sobrevivência real."},
    {"scene": 5, "block": 2, "text": "A natureza consegue ser mais estranha que qualquer filme."},
    {"scene": 5, "block": 3, "text": "Zé Curioso: parece mentira, mas é real."},
]

FINAL_TEXT = " ".join(item["text"] for item in FINAL_BLOCKS)
cont.BLOCKS = FINAL_BLOCKS
cont.FULL_NARRATION = FINAL_TEXT
v6.FULL_SPEAK_TEXT = FINAL_TEXT

# Mantém a identidade aprovada, mas reforça continuidade e um pouco mais de calma.
v6.VOICE_CONTROL = (
    v6.VOICE_CONTROL
    + " Speak slightly slower than your default pace, with relaxed consonants and full word endings."
    + " Keep the SAME pitch center and SAME vocal effort from the first word through the final catchphrase."
    + " The final words are exactly: 'Zé Curioso: parece mentira, mas é real.' Do not add an introduction before them."
)

v6.CRITICAL.update({
    "meses", "descongela", "glicose", "gelo", "primavera",
    "curioso", "mentira", "real", "bater",
})


def generate_final_single_take() -> tuple[Path, list[dict], float, str]:
    client = cont.base.Client("openbmb/VoxCPM-Demo", verbose=False)
    ref = cont.base.handle_file(str(cont.ASSETS / "voice_ref.mp3"))
    model = v4.WhisperModel("small", device="cpu", compute_type="int8")
    expected = v4.words_from_text(FINAL_TEXT)
    valid: list[dict] = []
    all_rows: list[dict] = []

    for attempt in range(1, 7):
        print(f"FINAL_SINGLE_TAKE_ATTEMPT {attempt}", flush=True)
        result = client.predict(
            FINAL_TEXT,
            v6.VOICE_CONTROL,
            ref,
            False,
            "",
            2.0,
            True,
            False,
            api_name="/generate",
        )
        src = Path(cont.base.extract_path(result))
        if not src.exists() or src.stat().st_size < 12000:
            print("REJECT_EMPTY", attempt, flush=True)
            time.sleep(2)
            continue

        raw = cont.AUDIO / f"single_take_candidate_{attempt:02d}.wav"
        v4.run([
            "ffmpeg", "-y", "-i", str(src), "-ar", "48000", "-ac", "1",
            "-c:a", "pcm_s16le", str(raw),
        ])
        duration = v4.probe_duration(raw)
        if not 24.0 <= duration <= 52.0:
            print("REJECT_DURATION", attempt, round(duration, 3), flush=True)
            continue

        words, transcript = v4.transcribe(model, raw)
        if not words:
            continue
        actual = [w["norm"] for w in words]
        mapping, exact_ratio = v4.align_tokens(expected, actual)
        sequence_ratio = difflib.SequenceMatcher(None, expected, actual).ratio()
        actual_set = set(actual)
        missing = sorted(v6.CRITICAL - actual_set)
        span = max(0.5, words[-1]["end"] - words[0]["start"])
        source_wpm = len(expected) * 60.0 / span
        stab = v6.stability_metrics(raw)

        # O VoxCPM tende a acelerar roteiros longos. Aceitamos a tomada limpa e
        # fazemos, se necessário, UM único ajuste global de tempo sem mudar pitch.
        pace_penalty = abs(source_wpm - 180.0) / 70.0
        score = (
            exact_ratio * 5.5
            + sequence_ratio * 2.5
            + stab["stability_score"] * 2.5
            - pace_penalty
            - len(missing) * 0.7
        )
        row = {
            "attempt": attempt,
            "path": raw.name,
            "duration": round(duration, 3),
            "asr_ratio": round(exact_ratio, 4),
            "sequence_ratio": round(sequence_ratio, 4),
            "missing_critical": missing,
            "source_wpm": round(source_wpm, 2),
            "score": round(score, 5),
            **stab,
            "transcript": transcript,
        }
        all_rows.append(row)
        print("FINAL_SINGLE_TAKE_QA", json.dumps(row, ensure_ascii=False), flush=True)

        if (
            exact_ratio >= 0.92
            and sequence_ratio >= 0.92
            and not missing
            and 145.0 <= source_wpm <= 215.0
            and stab["f0_jitter"] <= 0.060
            and stab["pitch_section_drift"] <= 0.20
        ):
            valid.append({
                "score": score,
                "raw": raw,
                "words": words,
                "ratio": exact_ratio,
                "transcript": transcript,
                "source_wpm": source_wpm,
                "metrics": row,
            })
        time.sleep(2)

    v6.ALL_CANDIDATES = all_rows
    if not valid:
        (cont.POST / "voice_consistency.json").write_text(
            json.dumps({"selected": None, "candidates": all_rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        raise RuntimeError("Nenhuma tomada final passou em texto + estabilidade")

    best = max(valid, key=lambda x: x["score"])
    raw = best["raw"]
    first = best["words"][0]["start"]
    last = best["words"][-1]["end"]
    trim_start = max(0.0, first - 0.08)
    raw_duration = v4.probe_duration(raw)
    trim_end = min(raw_duration, last + 0.18)
    trim_duration = max(0.5, trim_end - trim_start)

    # Se veio rápida, desacelera a tomada INTEIRA de uma vez. atempo preserva pitch;
    # portanto não há emenda nem reinício de entonação entre cenas.
    tempo = 1.0
    if best["source_wpm"] > 185.0:
        tempo = max(0.86, min(1.0, 178.0 / best["source_wpm"]))
    final_wpm = best["source_wpm"] * tempo

    final_audio = cont.AUDIO / "narration_continuous.wav"
    filters = []
    if tempo < 0.999:
        filters.append(f"atempo={tempo:.6f}")
    filters.append("loudnorm=I=-16:TP=-2:LRA=8")
    v4.run([
        "ffmpeg", "-y", "-ss", f"{trim_start:.4f}", "-t", f"{trim_duration:.4f}",
        "-i", str(raw), "-af", ",".join(filters),
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(final_audio),
    ])

    shifted_words = [
        {
            **w,
            "start": max(0.0, (w["start"] - trim_start) / tempo),
            "end": max(0.0, (w["end"] - trim_start) / tempo),
        }
        for w in best["words"]
    ]

    selected = {
        **best["metrics"],
        "source_wpm": round(best["source_wpm"], 2),
        "playback_tempo": round(tempo, 6),
        "wpm": round(final_wpm, 2),
        "accepted_file": final_audio.name,
        "script_locked": FINAL_TEXT,
        "audio_edits": "single global tempo adjustment + single global loudness normalization; no scene cuts",
    }
    v6.SELECTED_METRICS = selected
    (cont.POST / "voice_consistency.json").write_text(
        json.dumps({"selected": selected, "candidates": all_rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (cont.POST / "asr_transcript.txt").write_text(best["transcript"], encoding="utf-8")
    (cont.POST / "alignment_words.json").write_text(
        json.dumps(shifted_words, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return final_audio, shifted_words, best["ratio"], best["transcript"]


if __name__ == "__main__":
    cont.words_from_text = v4.words_from_text
    cont.align_tokens = v4.align_tokens
    cont.generate_continuous_narration = generate_final_single_take
    cont._qa_original = cont.qa_and_copy
    cont.qa_and_copy = v6.qa_final
    cont.main()
