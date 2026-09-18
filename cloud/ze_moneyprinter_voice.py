from __future__ import annotations

"""MoneyPrinter -> VoxCPM2 hybrid voice for Zé Curioso Studio.

The user-approved test uses MoneyPrinter br_005 as the reference and VoxCPM2
as the expressive cloning pass. If VoxCPM2 is unavailable, the MoneyPrinter
audio remains a usable fallback instead of failing the whole video.
"""

import json
import shutil
import time
from pathlib import Path

import moneyprinter_bridge as mp


def install(vf) -> None:
    sb = vf.sb
    fs = vf.fs
    v62 = vf.v62
    v6 = vf.v6
    v4 = vf.v4
    cont = vf.cont
    AUDIO = vf.AUDIO
    POST = vf.POST

    def _audio_path(result):
        return Path(cont.base.extract_path(result))

    def _prepare_reference(text: str, stem: str) -> tuple[Path, Path]:
        source = AUDIO / f"{stem}_moneyprinter_br005.mp3"
        mp.tts(text, source, voice="br_005")
        ref = AUDIO / f"{stem}_moneyprinter_ref.wav"
        v4.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(source), "-t", "14.0",
            "-af", "loudnorm=I=-16:TP=-2:LRA=8",
            "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(ref),
        ])
        return source, ref

    def _analyze(model, raw: Path, expected_text: str, critical: set[str]) -> dict:
        expected = v4.words_from_text(expected_text)
        words, transcript = v4.transcribe(model, raw)
        if not words:
            raise RuntimeError("ASR returned no words")
        actual = [w["norm"] for w in words]
        _, ratio = v4.align_tokens(expected, actual)
        missing = sorted(set(critical) - set(actual))
        span = max(0.5, float(words[-1]["end"]) - float(words[0]["start"]))
        wpm = len(expected) * 60.0 / span
        metrics = v6.stability_metrics(raw)
        return {
            "words": words,
            "transcript": transcript,
            "ratio": float(ratio),
            "missing": missing,
            "wpm": float(wpm),
            "metrics": metrics,
        }

    def _finalize(raw: Path, analysis: dict, final: Path, target_wpm: float = 170.0):
        words = analysis["words"]
        first = float(words[0]["start"])
        last = float(words[-1]["end"])
        trim_start = max(0.0, first - 0.08)
        trim_end = min(v4.probe_duration(raw), last + 0.18)
        trim_duration = max(0.5, trim_end - trim_start)

        source_wpm = float(analysis["wpm"])
        tempo = 1.0
        if source_wpm > 186.0:
            tempo = max(0.86, min(1.0, target_wpm / source_wpm))

        filters = []
        if tempo < 0.999:
            filters.append(f"atempo={tempo:.6f}")
        filters.append("loudnorm=I=-16:TP=-2:LRA=8")
        v4.run([
            "ffmpeg", "-y", "-ss", f"{trim_start:.4f}", "-t", f"{trim_duration:.4f}",
            "-i", str(raw), "-af", ",".join(filters),
            "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(final),
        ])
        shifted = [{
            **w,
            "start": max(0.0, (float(w["start"]) - trim_start) / tempo),
            "end": max(0.0, (float(w["end"]) - trim_start) / tempo),
        } for w in words]
        return shifted, tempo

    def _hybrid_generate(text: str, stem: str, critical: set[str], control: str, max_attempts: int = 4):
        source_mp3, ref_wav = _prepare_reference(text, stem)
        model = v4.WhisperModel("small", device="cpu", compute_type="int8")
        client = cont.base.Client("openbmb/VoxCPM-Demo", verbose=False)
        ref = cont.base.handle_file(str(ref_wav))

        rows = []
        valid = []
        for attempt in range(1, max_attempts + 1):
            try:
                print(f"MONEYVOX_{stem.upper()}_ATTEMPT {attempt}", flush=True)
                result = client.predict(
                    text,
                    control,
                    ref,
                    False,
                    "",
                    2.0,
                    True,
                    False,
                    api_name="/generate",
                )
                src = _audio_path(result)
                if not src.exists() or src.stat().st_size < 5000:
                    raise RuntimeError("VoxCPM returned invalid audio")
                raw = AUDIO / f"{stem}_hybrid_candidate_{attempt:02d}.wav"
                v4.run([
                    "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                    "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(raw),
                ])
                a = _analyze(model, raw, text, critical)
                stab = a["metrics"]
                score = (
                    a["ratio"] * 5.0
                    + float(stab.get("stability_score", 0.0)) * 2.0
                    - len(a["missing"]) * 0.8
                    - abs(a["wpm"] - 170.0) / 100.0
                )
                row = {
                    "attempt": attempt,
                    "path": raw.name,
                    "engine": "MoneyPrinter br_005 -> VoxCPM2",
                    "reference_file": ref_wav.name,
                    "asr_ratio": round(a["ratio"], 4),
                    "missing_critical": a["missing"],
                    "source_wpm": round(a["wpm"], 2),
                    "score": round(score, 5),
                    "transcript": a["transcript"],
                    **stab,
                }
                rows.append(row)
                print("MONEYVOX_QA", json.dumps(row, ensure_ascii=False), flush=True)
                if a["ratio"] >= 0.91 and not a["missing"]:
                    valid.append((score, raw, a, row))
                    # Do not spend extra VoxCPM queue time once a take is already
                    # text-clean and prosodically stable.
                    if (
                        a["ratio"] >= 0.97
                        and float(stab.get("stability_score", 0.0)) >= 0.70
                        and float(stab.get("pitch_section_drift", 9.0)) <= 0.15
                        and float(stab.get("f0_jitter", 9.0)) <= 0.04
                    ):
                        print("MONEYVOX_EARLY_ACCEPT", attempt, flush=True)
                        break
            except Exception as exc:
                print("MONEYVOX_ATTEMPT_WARN", attempt, repr(exc), flush=True)
                time.sleep(3)

        if valid:
            valid.sort(key=lambda x: x[0], reverse=True)
            _, raw, analysis, row = valid[0]
            return raw, analysis, row, rows, "hybrid"

        # Fallback is still MoneyPrinter, so the video can complete even if the
        # external VoxCPM Space is busy or temporarily unavailable.
        fallback = AUDIO / f"{stem}_moneyprinter_fallback.wav"
        v4.run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(source_mp3),
            "-af", "loudnorm=I=-16:TP=-2:LRA=8",
            "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(fallback),
        ])
        analysis = _analyze(model, fallback, text, critical)
        if analysis["ratio"] < 0.86:
            raise RuntimeError(f"MoneyPrinter fallback ASR too low: {analysis['ratio']:.4f}")
        row = {
            "attempt": 0,
            "path": fallback.name,
            "engine": "MoneyPrinter br_005 fallback",
            "asr_ratio": round(analysis["ratio"], 4),
            "missing_critical": analysis["missing"],
            "source_wpm": round(analysis["wpm"], 2),
            "transcript": analysis["transcript"],
            **analysis["metrics"],
        }
        rows.append(row)
        return fallback, analysis, row, rows, "moneyprinter-fallback"

    def generate_body():
        text = fs.BODY_TEXT
        critical = set(fs.BODY_CRITICAL)
        control = (
            "Brazilian Portuguese male short-form creator. Preserve the MoneyPrinter reference voice identity, "
            "clarity and clean diction very closely. Make the delivery human and conversational, with natural "
            "micro-pauses, gentle curiosity, smoother sentence flow and subtle emphasis on surprising facts. "
            "Calm confidence, no radio announcer, no advertisement, no theatrical delivery and no shouting."
        )
        raw, analysis, selected, rows, mode = _hybrid_generate(text, "body", critical, control, 3)
        final = AUDIO / "narration_continuous.wav"
        shifted, tempo = _finalize(raw, analysis, final, 170.0)
        selected = {
            **selected,
            "selected": True,
            "voice_architecture": mode,
            "moneyprinter_voice": "br_005",
            "playback_tempo": round(tempo, 6),
            "wpm": round(float(analysis["wpm"]) * tempo, 2),
            "accepted_file": final.name,
        }
        v6.SELECTED_METRICS = selected
        (POST / "voice_consistency.json").write_text(
            json.dumps({"selected": selected, "candidates": rows, "moneyprinter_primary": True}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (POST / "asr_transcript.txt").write_text(analysis["transcript"], encoding="utf-8")
        (POST / "alignment_words.json").write_text(json.dumps(shifted, ensure_ascii=False, indent=2), encoding="utf-8")
        return final, shifted, float(analysis["ratio"]), str(analysis["transcript"])

    def generate_signoff():
        text = sb.PREVIOUS_SIGNOFF
        critical = {"ze", "curioso", "mentira", "real"}
        control = (
            "Brazilian Portuguese male short-form creator. Preserve the MoneyPrinter reference voice. "
            "Say the channel signature naturally and clearly. 'Eu sou o Zé Curioso' is confident identification, "
            "then a small natural pause. Give 'parece mentira' a light curiosity lift and land 'mas é real' firmly. "
            "Do not shout and do not sound like an announcer or advertisement."
        )
        raw, analysis, selected, rows, mode = _hybrid_generate(text, "signoff", critical, control, 3)
        final = AUDIO / "signoff_final.wav"
        shifted, tempo = _finalize(raw, analysis, final, 165.0)
        selected = {
            **selected,
            "selected": True,
            "voice_architecture": mode,
            "moneyprinter_voice": "br_005",
            "playback_tempo": round(tempo, 6),
            "accepted_file": final.name,
        }
        (POST / "signoff_qa.json").write_text(
            json.dumps({"selected": selected, "candidates": rows, "expected_signoff": text}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return final, shifted, float(analysis["ratio"]), str(analysis["transcript"]), selected

    vf.generate_body_voice_locked = generate_body
    vf.generate_stable_previous_signoff = generate_signoff
