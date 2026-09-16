from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import ze_postavel_woodfrog_v6_4_locked as v64

v62 = v64.v62
v6 = v64.v6
cont = v64.cont
v4 = v64.v4

BODY_BLOCKS = v62.FINAL_BLOCKS[:-1]
SIGNOFF_BLOCK = v62.FINAL_BLOCKS[-1]
BODY_TEXT = " ".join(x["text"] for x in BODY_BLOCKS)
SIGNOFF_SPEAK = "Zé Curioso. Parece mentira, mas é real."
SIGNOFF_DISPLAY = SIGNOFF_BLOCK["text"]
GAP_SECONDS = 0.12

# O corpo fica exatamente no estilo calmo aprovado. A assinatura é gerada curta,
# com a MESMA referência de voz, para garantir marca inteligível e presença.
BODY_CRITICAL = {
    "meses", "descongela", "glicose", "gelo", "primavera", "bater",
}
SIGNOFF_CRITICAL = {"ze", "curioso", "mentira", "real"}


def generate_signoff() -> tuple[Path, list[dict], float, str, dict]:
    client = cont.base.Client("openbmb/VoxCPM-Demo", verbose=False)
    ref = cont.base.handle_file(str(cont.ASSETS / "voice_ref.mp3"))
    model = v4.WhisperModel("small", device="cpu", compute_type="int8")
    expected = v4.words_from_text(SIGNOFF_SPEAK)
    candidates: list[dict] = []
    valid: list[dict] = []

    control = (
        "Use exactly the same speaker identity and timbre as the reference. "
        "This is a short channel signature after a calm explanatory narration. "
        "Say the two words 'Zé Curioso' literally, clearly and separately enough to be unmistakable. "
        "Do not say 'isso é curioso', 'é curioso' or 'José Curioso'. "
        "Give 'Zé Curioso' confident identification, then a short natural pause. "
        "Say 'parece mentira' with a small lift of curiosity, and land 'mas é real' firmly with a natural downward cadence. "
        "Slightly more presence than normal conversation, but never shout, advertise, sound urgent, theatrical or like a radio announcer."
    )

    for attempt in range(1, 9):
        print(f"SIGNOFF_ATTEMPT {attempt}", flush=True)
        result = client.predict(
            SIGNOFF_SPEAK,
            control,
            ref,
            False,
            "",
            2.0,
            True,
            False,
            api_name="/generate",
        )
        src = Path(cont.base.extract_path(result))
        if not src.exists() or src.stat().st_size < 5000:
            time.sleep(2)
            continue

        raw = cont.AUDIO / f"signoff_candidate_{attempt:02d}.wav"
        v4.run([
            "ffmpeg", "-y", "-i", str(src), "-ar", "48000", "-ac", "1",
            "-c:a", "pcm_s16le", str(raw),
        ])
        duration = v4.probe_duration(raw)
        if not 1.8 <= duration <= 7.5:
            continue

        words, transcript = v4.transcribe(model, raw)
        if not words:
            continue
        actual = [w["norm"] for w in words]
        mapping, ratio = v4.align_tokens(expected, actual)
        actual_set = set(actual)
        missing = sorted(SIGNOFF_CRITICAL - actual_set)
        stab = v6.stability_metrics(raw)
        row = {
            "attempt": attempt,
            "path": raw.name,
            "duration": round(duration, 3),
            "asr_ratio": round(ratio, 4),
            "missing_critical": missing,
            "transcript": transcript,
            **stab,
        }
        candidates.append(row)
        print("SIGNOFF_QA", json.dumps(row, ensure_ascii=False), flush=True)

        # O nome da marca precisa estar literalmente reconhecido.
        if ratio >= 0.86 and not missing:
            valid.append({"raw": raw, "words": words, "ratio": ratio, "transcript": transcript, "metrics": row})
            # Uma assinatura perfeita não precisa de mais tentativas.
            if ratio >= 0.98:
                break
        time.sleep(2)

    if not valid:
        (cont.POST / "signoff_qa.json").write_text(
            json.dumps({"selected": None, "candidates": candidates}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        raise RuntimeError("Nenhum bordão pronunciou 'Zé Curioso' claramente")

    best = max(valid, key=lambda x: (x["ratio"], x["metrics"]["stability_score"]))
    raw = best["raw"]
    first = best["words"][0]["start"]
    last = best["words"][-1]["end"]
    trim_start = max(0.0, first - 0.06)
    trim_duration = max(0.4, min(v4.probe_duration(raw), last + 0.16) - trim_start)
    final = cont.AUDIO / "signoff_final.wav"
    # Um pouco mais presente que o corpo; sem compressão agressiva.
    v4.run([
        "ffmpeg", "-y", "-ss", f"{trim_start:.4f}", "-t", f"{trim_duration:.4f}",
        "-i", str(raw), "-af", "loudnorm=I=-15:TP=-2:LRA=7",
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(final),
    ])
    shifted = [{**w, "start": max(0.0, w["start"] - trim_start), "end": max(0.0, w["end"] - trim_start)} for w in best["words"]]
    (cont.POST / "signoff_qa.json").write_text(
        json.dumps({"selected": best["metrics"], "candidates": candidates}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return final, shifted, best["ratio"], best["transcript"], best["metrics"]


def generate_body_plus_signoff() -> tuple[Path, list[dict], float, str]:
    original_text = v62.FINAL_TEXT
    original_full = v6.FULL_SPEAK_TEXT
    original_critical = set(v6.CRITICAL)
    try:
        v62.FINAL_TEXT = BODY_TEXT
        v6.FULL_SPEAK_TEXT = BODY_TEXT
        v6.CRITICAL.clear()
        v6.CRITICAL.update(BODY_CRITICAL)
        body_audio, body_words, body_ratio, body_transcript = v62.generate_final_single_take()
    finally:
        v62.FINAL_TEXT = original_text
        v6.FULL_SPEAK_TEXT = original_full
        v6.CRITICAL.clear()
        v6.CRITICAL.update(original_critical)

    signoff_audio, signoff_words, signoff_ratio, signoff_transcript, signoff_metrics = generate_signoff()
    body_duration = cont.probe_duration(body_audio)
    signoff_offset = body_duration + GAP_SECONDS

    final_audio = cont.AUDIO / "narration_continuous.wav"
    tmp = cont.AUDIO / "narration_body_signoff_joined.wav"
    # Uma única emenda, numa pausa intencional antes da assinatura.
    v4.run([
        "ffmpeg", "-y", "-i", str(body_audio), "-i", str(signoff_audio),
        "-filter_complex",
        f"anullsrc=r=48000:cl=mono:d={GAP_SECONDS}[sil];[0:a][sil][1:a]concat=n=3:v=0:a=1[out]",
        "-map", "[out]", "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(tmp),
    ])
    shutil.move(str(tmp), str(final_audio))

    combined_words = list(body_words) + [
        {**w, "start": w["start"] + signoff_offset, "end": w["end"] + signoff_offset}
        for w in signoff_words
    ]
    combined_transcript = (body_transcript.rstrip() + " " + signoff_transcript.lstrip()).strip()
    combined_ratio = min(body_ratio, signoff_ratio)

    (cont.POST / "alignment_words.json").write_text(
        json.dumps(combined_words, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (cont.POST / "asr_transcript.txt").write_text(combined_transcript, encoding="utf-8")
    (cont.POST / "final_voice_architecture.json").write_text(
        json.dumps({
            "body": "single calm continuous take",
            "signoff": "single short take using same approved voice reference",
            "join": f"one intentional {int(GAP_SECONDS*1000)}ms pause before signoff",
            "body_asr_ratio": body_ratio,
            "signoff_asr_ratio": signoff_ratio,
            "signoff_transcript": signoff_transcript,
            "signoff_metrics": signoff_metrics,
            "display_signoff": SIGNOFF_DISPLAY,
        }, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return final_audio, combined_words, combined_ratio, combined_transcript


def main() -> None:
    # O texto visual continua sendo o template V6.4 aprovado.
    cont.words_from_text = v4.words_from_text
    cont.align_tokens = v4.align_tokens
    cont.generate_continuous_narration = generate_body_plus_signoff
    cont.render_video = v64.render_word_pop_video
    cont._qa_original = cont.qa_and_copy
    cont.qa_and_copy = v64.qa_v64
    cont.main()


if __name__ == "__main__":
    main()
