from __future__ import annotations

import json
import time
from pathlib import Path

import ze_postavel_woodfrog_v6_4_finalsplit as fs

CARRIER_TEXT = "Meu nome é Zé Curioso. Parece mentira, mas é real."
EXPECTED_SIGNOFF = fs.v4.words_from_text(fs.SIGNOFF_SPEAK)
CRITICAL = {"ze", "curioso", "mentira", "real"}


def _tail_from_ze(words: list[dict]) -> tuple[list[dict], int | None]:
    for idx, word in enumerate(words):
        if word.get("norm") == "ze":
            return words[idx:], idx
    return [], None


def generate_signoff_carrier() -> tuple[Path, list[dict], float, str, dict]:
    client = fs.cont.base.Client("openbmb/VoxCPM-Demo", verbose=False)
    ref = fs.cont.base.handle_file(str(fs.cont.ASSETS / "voice_ref.mp3"))
    model = fs.v4.WhisperModel("small", device="cpu", compute_type="int8")
    candidates: list[dict] = []
    valid: list[dict] = []

    control = (
        "Use exactly the same speaker identity and timbre as the reference. "
        "Speak calmly and conversationally. The first three words are only a pronunciation lead-in. "
        "In the phrase 'Meu nome é Zé Curioso', pronounce the name literally as Zé Curioso, with Zé clear and separate from Curioso. "
        "Then give a short natural pause and say 'Parece mentira, mas é real' with slightly more presence, never shouted, urgent or theatrical."
    )

    for attempt in range(1, 11):
        print(f"CARRIER_SIGNOFF_ATTEMPT {attempt}", flush=True)
        result = client.predict(
            CARRIER_TEXT,
            control,
            ref,
            False,
            "",
            2.0,
            True,
            False,
            api_name="/generate",
        )
        src = Path(fs.cont.base.extract_path(result))
        if not src.exists() or src.stat().st_size < 5000:
            time.sleep(2)
            continue

        raw = fs.cont.AUDIO / f"signoff_carrier_candidate_{attempt:02d}.wav"
        fs.v4.run([
            "ffmpeg", "-y", "-i", str(src), "-ar", "48000", "-ac", "1",
            "-c:a", "pcm_s16le", str(raw),
        ])

        words, transcript = fs.v4.transcribe(model, raw)
        tail, ze_idx = _tail_from_ze(words)
        actual_tail = [w["norm"] for w in tail]
        _, ratio = fs.v4.align_tokens(EXPECTED_SIGNOFF, actual_tail) if tail else ([], 0.0)
        missing = sorted(CRITICAL - set(actual_tail))
        stab = fs.v6.stability_metrics(raw)
        row = {
            "attempt": attempt,
            "path": raw.name,
            "duration": round(fs.v4.probe_duration(raw), 3),
            "asr_ratio_after_ze": round(ratio, 4),
            "ze_index": ze_idx,
            "missing_critical": missing,
            "transcript": transcript,
            **stab,
        }
        candidates.append(row)
        print("CARRIER_SIGNOFF_QA", json.dumps(row, ensure_ascii=False), flush=True)

        if tail and ratio >= 0.86 and not missing:
            valid.append({"raw": raw, "tail": tail, "ratio": ratio, "transcript": transcript, "metrics": row})
            if ratio >= 0.98:
                break
        time.sleep(2)

    if not valid:
        (fs.cont.POST / "signoff_qa.json").write_text(
            json.dumps({"selected": None, "strategy": "carrier phrase then trim from Zé", "candidates": candidates}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        raise RuntimeError("Nenhum carrier phrase produziu 'Zé Curioso' claramente")

    best = max(valid, key=lambda x: (x["ratio"], x["metrics"]["stability_score"]))
    raw = best["raw"]
    tail = best["tail"]
    first = float(tail[0]["start"])
    last = float(tail[-1]["end"])
    trim_start = max(0.0, first - 0.04)
    trim_duration = max(0.4, min(fs.v4.probe_duration(raw), last + 0.16) - trim_start)
    final = fs.cont.AUDIO / "signoff_final.wav"
    fs.v4.run([
        "ffmpeg", "-y", "-ss", f"{trim_start:.4f}", "-t", f"{trim_duration:.4f}",
        "-i", str(raw), "-af", "loudnorm=I=-15:TP=-2:LRA=7",
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(final),
    ])

    shifted = [
        {**w, "start": max(0.0, float(w["start"]) - trim_start), "end": max(0.0, float(w["end"]) - trim_start)}
        for w in tail
    ]
    selected = {**best["metrics"], "trimmed_from": "Zé", "strategy": "carrier phrase then trim from Zé"}
    (fs.cont.POST / "signoff_qa.json").write_text(
        json.dumps({"selected": selected, "candidates": candidates}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tail_transcript = " ".join(str(w.get("word", "")).strip() for w in tail).strip()
    return final, shifted, best["ratio"], tail_transcript, selected


def main() -> None:
    fs.generate_signoff = generate_signoff_carrier
    fs.main()


if __name__ == "__main__":
    main()
