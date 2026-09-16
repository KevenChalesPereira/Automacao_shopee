from __future__ import annotations

import difflib
import json
import shutil
import time
from pathlib import Path

import ze_postavel_woodfrog_v6_4_locked as v64

v62 = v64.v62
v6 = v64.v6
cont = v64.cont
v4 = v64.v4
AUDIO = v64.AUDIO
POST = v64.POST

BODY_TEXT = " ".join(item["text"] for item in v62.FINAL_BLOCKS[:-1])
SIGNOFF_DISPLAY = v62.FINAL_BLOCKS[-1]["text"]
SIGNOFF_SPEAK = "Zé Curioso. Parece mentira, mas é real."
SIGNOFF_GAP = 0.18

# Mantém o corpo exatamente na direção calma da V6.3/V6.4.
# A assinatura é gerada separadamente porque o VoxCPM estava transformando
# semanticamente "Zé Curioso" em "Isso é curioso" quando o nome aparecia no fim
# de uma tomada longa. O corpo continua sendo UMA tomada contínua; só o bordão,
# que já deve ter mais ênfase, vira uma assinatura curta e controlada.
v64.v6.VOICE_CONTROL += (
    " Keep the body calm and explanatory. Do not add any words after the supplied text."
)


def _generate_body() -> tuple[Path, list[dict], float, str, dict]:
    original_text = v62.FINAL_TEXT
    original_critical = set(v6.CRITICAL)
    original_control = v6.VOICE_CONTROL
    try:
        v62.FINAL_TEXT = BODY_TEXT
        v6.CRITICAL.clear()
        v6.CRITICAL.update(original_critical - {"ze", "curioso", "mentira", "real"})
        v6.VOICE_CONTROL = (
            original_control
            + " This pass is only the explanatory body. Stop naturally after the exact words 'qualquer filme'."
            + " Do not say the channel name and do not add a sign-off."
        )
        audio, words, ratio, transcript = v62.generate_final_single_take()
        body_copy = AUDIO / "narration_body_continuous.wav"
        shutil.copy2(audio, body_copy)
        metrics = dict(v6.SELECTED_METRICS)
        return body_copy, words, ratio, transcript, metrics
    finally:
        v62.FINAL_TEXT = original_text
        v6.CRITICAL.clear()
        v6.CRITICAL.update(original_critical)
        v6.VOICE_CONTROL = original_control


def _generate_signoff() -> tuple[Path, list[dict], float, str, dict]:
    client = cont.base.Client("openbmb/VoxCPM-Demo", verbose=False)
    ref = cont.base.handle_file(str(cont.ASSETS / "voice_ref.mp3"))
    model = v4.WhisperModel("small", device="cpu", compute_type="int8")
    expected = v4.words_from_text(SIGNOFF_DISPLAY)
    required = {"ze", "curioso", "mentira", "real"}
    valid: list[dict] = []
    rows: list[dict] = []

    control = (
        "Brazilian Portuguese male voice. Use the exact same speaker identity, timbre, age impression and microphone distance as the reference. "
        "This is a short familiar channel sign-off after a calm explanation. Give it only a little more presence than the body; do not sound urgent, theatrical, promotional or like an announcer. "
        "Pronounce the brand name literally as two words: 'Zé Curioso'. The first word is the Brazilian nickname Zé, one clear syllable, pronounced roughly /zɛ/. "
        "Do NOT say 'isso é curioso', 'é curioso' or 'José Curioso'. Say Zé first, then Curioso, with a tiny natural boundary between them. "
        "Use a small lift on 'parece mentira' and land naturally downward on 'mas é real'. Keep the voice steady, clean and conversational."
    )

    for attempt in range(1, 11):
        print(f"SIGNOFF_ATTEMPT {attempt}", flush=True)
        try:
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
        except Exception as exc:
            print("SIGNOFF_QUEUE_ERROR", attempt, repr(exc), flush=True)
            time.sleep(4)
            continue

        src = Path(cont.base.extract_path(result))
        if not src.exists() or src.stat().st_size < 5000:
            time.sleep(2)
            continue

        raw = AUDIO / f"signoff_candidate_{attempt:02d}.wav"
        v4.run([
            "ffmpeg", "-y", "-i", str(src), "-ar", "48000", "-ac", "1",
            "-c:a", "pcm_s16le", str(raw),
        ])
        duration = v4.probe_duration(raw)
        words, transcript = v4.transcribe(model, raw)
        if not words:
            continue

        actual = [w["norm"] for w in words]
        mapping, exact_ratio = v4.align_tokens(expected, actual)
        sequence_ratio = difflib.SequenceMatcher(None, expected, actual).ratio()
        missing = sorted(required - set(actual))
        stab = v6.stability_metrics(raw)
        span = max(0.4, words[-1]["end"] - words[0]["start"])
        wpm = len(expected) * 60.0 / span
        score = exact_ratio * 6.0 + sequence_ratio * 3.0 + stab["stability_score"] * 1.5 - len(missing) * 2.0
        row = {
            "attempt": attempt,
            "duration": round(duration, 3),
            "asr_ratio": round(exact_ratio, 4),
            "sequence_ratio": round(sequence_ratio, 4),
            "missing_critical": missing,
            "wpm": round(wpm, 2),
            "score": round(score, 5),
            **stab,
            "transcript": transcript,
        }
        rows.append(row)
        print("SIGNOFF_QA", json.dumps(row, ensure_ascii=False), flush=True)

        if (
            exact_ratio >= 0.90
            and sequence_ratio >= 0.90
            and not missing
            and 1.8 <= duration <= 7.0
            and stab["f0_jitter"] <= 0.09
        ):
            valid.append({"raw": raw, "words": words, "ratio": exact_ratio, "transcript": transcript, "row": row, "score": score})
        time.sleep(2)

    if not valid:
        raise RuntimeError(f"Nenhum bordão pronunciou claramente 'Zé Curioso': {rows}")

    best = max(valid, key=lambda x: x["score"])
    raw = best["raw"]
    first = float(best["words"][0]["start"])
    last = float(best["words"][-1]["end"])
    raw_duration = v4.probe_duration(raw)
    trim_start = max(0.0, first - 0.06)
    trim_end = min(raw_duration, last + 0.16)
    trim_duration = max(0.5, trim_end - trim_start)
    out = AUDIO / "signoff_ze_curioso.wav"
    v4.run([
        "ffmpeg", "-y", "-ss", f"{trim_start:.4f}", "-t", f"{trim_duration:.4f}",
        "-i", str(raw),
        "-af", "loudnorm=I=-15:TP=-2:LRA=7",
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(out),
    ])
    shifted = [
        {**w, "start": max(0.0, float(w["start"]) - trim_start), "end": max(0.0, float(w["end"]) - trim_start)}
        for w in best["words"]
    ]
    (POST / "signoff_qa.json").write_text(
        json.dumps({"selected": best["row"], "candidates": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out, shifted, best["ratio"], best["transcript"], best["row"]


def generate_brandfixed() -> tuple[Path, list[dict], float, str]:
    body_audio, body_words, body_ratio, body_transcript, body_metrics = _generate_body()
    sign_audio, sign_words, sign_ratio, sign_transcript, sign_metrics = _generate_signoff()

    body_duration = v4.probe_duration(body_audio)
    final_audio = AUDIO / "narration_continuous.wav"
    v4.run([
        "ffmpeg", "-y",
        "-i", str(body_audio),
        "-f", "lavfi", "-t", f"{SIGNOFF_GAP:.3f}", "-i", "anullsrc=r=48000:cl=mono",
        "-i", str(sign_audio),
        "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1[outa]",
        "-map", "[outa]", "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le",
        str(final_audio),
    ])

    offset = body_duration + SIGNOFF_GAP
    combined_words = list(body_words) + [
        {**w, "start": float(w["start"]) + offset, "end": float(w["end"]) + offset}
        for w in sign_words
    ]
    expected = v4.words_from_text(" ".join(item["text"] for item in v62.FINAL_BLOCKS))
    actual = [w["norm"] for w in combined_words]
    _, combined_ratio = v4.align_tokens(expected, actual)
    transcript = (body_transcript.rstrip(" .") + ". " + sign_transcript.strip()).strip()

    (POST / "alignment_words.json").write_text(
        json.dumps(combined_words, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (POST / "asr_transcript.txt").write_text(transcript, encoding="utf-8")
    (POST / "voice_consistency.json").write_text(
        json.dumps({
            "architecture": "one continuous calm body take + separately emphasized final signature",
            "body": body_metrics,
            "signoff": sign_metrics,
            "signoff_gap_seconds": SIGNOFF_GAP,
            "combined_alignment_ratio": round(combined_ratio, 4),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # qa_v63/qa_final usa SELECTED_METRICS como gate técnico. O corpo é a parte
    # longa que precisa manter estabilidade; o bordão tem QA próprio e obrigatório.
    v6.SELECTED_METRICS = body_metrics
    return final_audio, combined_words, min(body_ratio, sign_ratio, combined_ratio), transcript


def qa_brandfixed(asr_ratio: float, alignment_ratio: float, timing: list[dict]) -> None:
    v64.qa_v64(asr_ratio, alignment_ratio, timing)
    qa_path = POST / "qa.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    sign = json.loads((POST / "signoff_qa.json").read_text(encoding="utf-8"))["selected"]
    qa.update({
        "revision": "card-v6.4-LOCKED-word-pop-clear-brand-signoff",
        "audio_generation_mode": "one continuous calm body take + one short final brand signature",
        "body_scene_audio_concatenation": False,
        "signoff_separate_by_design": True,
        "signoff_reason": "final signature intentionally has more emphasis and strict Zé Curioso pronunciation QA",
        "signoff_asr": sign,
        "signoff_post_gain": "separate signoff loudness normalized to -15 LUFS; no post gain on body",
    })
    qa["passed"] = bool(qa.get("passed")) and not sign.get("missing_critical") and float(sign.get("asr_ratio", 0)) >= 0.90
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    if not qa["passed"]:
        raise RuntimeError(f"QA bordão final falhou: {qa}")


def main() -> None:
    cont.words_from_text = v4.words_from_text
    cont.align_tokens = v4.align_tokens
    cont.generate_continuous_narration = generate_brandfixed
    cont.render_video = v64.render_word_pop_video
    cont._qa_original = cont.qa_and_copy
    cont.qa_and_copy = qa_brandfixed
    cont.main()


if __name__ == "__main__":
    main()
