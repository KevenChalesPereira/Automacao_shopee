from __future__ import annotations

import json
import shutil
from pathlib import Path

import ze_postavel_woodfrog_v6_4_simplebubble as sb

fs = sb.fs
v62 = fs.v62
v6 = fs.v6
v4 = sb.v4
cont = sb.cont
AUDIO = sb.AUDIO
POST = sb.POST

# Fingerprint da tomada aprovada no run 35155786249 (attempt 3).
TARGET_WPM = 174.42
TARGET_F0_JITTER = 0.01739
TARGET_PITCH_DRIFT = 0.04559
TARGET_STABILITY = 0.78423
TARGET_MEDIANS = [145.90, 139.13, 134.45]

_original_body_generator = v62.generate_final_single_take
_original_signoff_generator = sb._base_generate_signoff


def _voice_match(row: dict) -> float:
    meds = [float(x) for x in row.get("pitch_section_medians_hz", [])[:3]]
    if len(meds) != 3:
        return 0.0
    med_err = sum(abs(a - b) for a, b in zip(meds, TARGET_MEDIANS)) / 3.0
    wpm = float(row.get("source_wpm", TARGET_WPM))
    jitter = float(row.get("f0_jitter", 1.0))
    drift = float(row.get("pitch_section_drift", 1.0))
    stability = float(row.get("stability_score", 0.0))
    return (
        max(0.0, 1.0 - med_err / 35.0) * 0.45
        + max(0.0, 1.0 - abs(wpm - TARGET_WPM) / 30.0) * 0.20
        + max(0.0, 1.0 - abs(drift - TARGET_PITCH_DRIFT) / 0.12) * 0.15
        + max(0.0, 1.0 - abs(jitter - TARGET_F0_JITTER) / 0.03) * 0.10
        + max(0.0, min(1.0, stability)) * 0.10
    )


def generate_body_voice_locked():
    # Deixa o gerador original produzir as 6 opções, mas não aceita automaticamente
    # a maior pontuação textual. Reabre as candidatas e escolhe a que mais se parece
    # com a voz aprovada do run 35155786249.
    _original_body_generator()
    meta_path = POST / "voice_consistency.json"
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    rows = data.get("candidates", [])

    eligible = []
    for row in rows:
        if float(row.get("asr_ratio", 0.0)) < 0.97:
            continue
        if float(row.get("sequence_ratio", 0.0)) < 0.96:
            continue
        if row.get("missing_critical"):
            continue
        if not 160.0 <= float(row.get("source_wpm", 0.0)) <= 195.0:
            continue
        if float(row.get("f0_jitter", 9.0)) > 0.040:
            continue
        if float(row.get("pitch_section_drift", 9.0)) > 0.12:
            continue
        if float(row.get("stability_score", 0.0)) < 0.70:
            continue
        enriched = dict(row)
        enriched["voice_match_score"] = round(_voice_match(row), 5)
        eligible.append(enriched)

    if not eligible:
        raise RuntimeError("Nenhuma tomada ficou perto o bastante da voz aprovada")

    best = max(eligible, key=lambda r: (float(r["voice_match_score"]), float(r.get("asr_ratio", 0.0))))
    raw = AUDIO / str(best["path"])
    if not raw.exists():
        raise RuntimeError(f"Candidata escolhida não existe: {raw}")

    model = v4.WhisperModel("small", device="cpu", compute_type="int8")
    words, transcript = v4.transcribe(model, raw)
    expected = v4.words_from_text(v62.FINAL_TEXT)
    actual = [w["norm"] for w in words]
    _, ratio = v4.align_tokens(expected, actual)

    first = float(words[0]["start"])
    last = float(words[-1]["end"])
    trim_start = max(0.0, first - 0.08)
    trim_end = min(v4.probe_duration(raw), last + 0.18)
    trim_duration = max(0.5, trim_end - trim_start)

    source_wpm = float(best["source_wpm"])
    tempo = 1.0
    if source_wpm > 185.0:
        tempo = max(0.86, min(1.0, 178.0 / source_wpm))

    final_audio = AUDIO / "narration_continuous.wav"
    filters = []
    if tempo < 0.999:
        filters.append(f"atempo={tempo:.6f}")
    filters.append("loudnorm=I=-16:TP=-2:LRA=8")
    v4.run([
        "ffmpeg", "-y", "-ss", f"{trim_start:.4f}", "-t", f"{trim_duration:.4f}",
        "-i", str(raw), "-af", ",".join(filters),
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(final_audio),
    ])

    shifted = [
        {
            **w,
            "start": max(0.0, (float(w["start"]) - trim_start) / tempo),
            "end": max(0.0, (float(w["end"]) - trim_start) / tempo),
        }
        for w in words
    ]

    selected = {
        **best,
        "playback_tempo": round(tempo, 6),
        "wpm": round(source_wpm * tempo, 2),
        "accepted_file": final_audio.name,
        "voice_lock": "approved fingerprint from run 35155786249 / attempt 3",
        "target_pitch_medians_hz": TARGET_MEDIANS,
        "target_wpm": TARGET_WPM,
    }
    # QA herdado da V6 lê v6.SELECTED_METRICS; portanto ele precisa apontar
    # para a MESMA tomada que realmente foi reprocessada acima.
    v6.SELECTED_METRICS = selected
    data["selected"] = selected
    data["voice_lock_enabled"] = True
    meta_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (POST / "asr_transcript.txt").write_text(transcript, encoding="utf-8")
    (POST / "alignment_words.json").write_text(json.dumps(shifted, ensure_ascii=False, indent=2), encoding="utf-8")
    print("VOICE_LOCK_SELECTED", json.dumps(selected, ensure_ascii=False), flush=True)
    return final_audio, shifted, ratio, transcript


def generate_stable_previous_signoff():
    # O bug ouvido no último vídeo veio daqui: a função antiga parava na primeira
    # leitura com texto perfeito, mesmo quando a entonação estava instável.
    candidates = []
    for round_index in range(1, 6):
        final, words, ratio, transcript, metrics = _original_signoff_generator()
        copy_path = AUDIO / f"signoff_voice_lock_{round_index:02d}.wav"
        shutil.copy2(final, copy_path)
        row = {
            **metrics,
            "round": round_index,
            "copy_path": copy_path.name,
            "ratio": float(ratio),
            "transcript": transcript,
            "words": words,
        }
        drift = float(row.get("pitch_section_drift", 9.0))
        jitter = float(row.get("f0_jitter", 9.0))
        stability = float(row.get("stability_score", 0.0))
        row["signoff_voice_score"] = round(stability - drift * 1.7 - jitter * 0.8, 5)
        candidates.append(row)
        if ratio >= 0.98 and drift <= 0.09 and jitter <= 0.035 and stability >= 0.68:
            break

    valid = [
        r for r in candidates
        if float(r["ratio"]) >= 0.90
        and float(r.get("pitch_section_drift", 9.0)) <= 0.15
        and float(r.get("f0_jitter", 9.0)) <= 0.040
        and float(r.get("stability_score", 0.0)) >= 0.60
    ]
    if not valid:
        raise RuntimeError("Bordão não atingiu estabilidade de voz aceitável")

    best = max(valid, key=lambda r: float(r["signoff_voice_score"]))
    chosen = AUDIO / best["copy_path"]
    final = AUDIO / "signoff_final.wav"
    shutil.copy2(chosen, final)

    qa_candidates = []
    for row in candidates:
        clean = {k: v for k, v in row.items() if k != "words"}
        qa_candidates.append(clean)
    selected = {k: v for k, v in best.items() if k != "words"}
    selected["voice_lock"] = "reject unstable first-perfect signoff; choose stable reading"
    (POST / "signoff_qa.json").write_text(
        json.dumps({"selected": selected, "candidates": qa_candidates}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("SIGNOFF_VOICE_LOCK_SELECTED", json.dumps(selected, ensure_ascii=False), flush=True)
    return final, best["words"], float(best["ratio"]), str(best["transcript"]), selected


def main() -> None:
    v62.generate_final_single_take = generate_body_voice_locked
    sb._base_generate_signoff = generate_stable_previous_signoff
    sb.main()


if __name__ == "__main__":
    main()
