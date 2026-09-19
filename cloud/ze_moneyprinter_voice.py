from __future__ import annotations

"""MoneyPrinter -> VoxCPM2 hybrid voice for Zé Curioso Studio.

The user-approved test uses MoneyPrinter br_005 as the reference and VoxCPM2
as the expressive cloning pass. If VoxCPM2 is unavailable, the MoneyPrinter
audio remains a usable fallback instead of failing the whole video.
"""

import json
import os
import shutil
import time
import wave
from pathlib import Path

import numpy as np
import requests
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

    def _roughness_metrics(path: Path) -> dict:
        # Simple hoarseness proxy: clean voiced speech is periodic and has low
        # spectral flatness; rough/breathy takes lose periodicity and gain noise.
        with wave.open(str(path), "rb") as wf:
            sr = wf.getframerate()
            channels = wf.getnchannels()
            samples = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32)
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1)
        samples /= 32768.0
        frame = max(480, int(sr * 0.030))
        hop = max(240, int(sr * 0.015))
        window = np.hanning(frame).astype(np.float32)
        periodicity = []
        flatness = []
        for pos in range(0, max(0, len(samples) - frame), hop):
            y = samples[pos:pos + frame]
            rms = float(np.sqrt(np.mean(y * y) + 1e-12))
            if rms < 0.010:
                continue
            z = (y - float(np.mean(y))) * window
            ac = np.correlate(z, z, mode="full")[frame - 1:]
            base = float(ac[0]) + 1e-12
            lo = max(1, int(sr / 400.0))
            hi = min(len(ac), int(sr / 70.0))
            if hi > lo:
                periodicity.append(float(np.max(ac[lo:hi]) / base))
            spectrum = np.abs(np.fft.rfft(z)) + 1e-9
            flatness.append(float(np.exp(np.mean(np.log(spectrum))) / np.mean(spectrum)))
        return {
            "periodicity_mean": round(float(np.mean(periodicity)) if periodicity else 0.0, 5),
            "periodicity_median": round(float(np.median(periodicity)) if periodicity else 0.0, 5),
            "spectral_flatness_mean": round(float(np.mean(flatness)) if flatness else 1.0, 5),
        }

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

    def _finalize(raw: Path, analysis: dict, final: Path, target_wpm: float = 170.0, pitch_factor: float = 0.97):
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

        # Slightly lower the voice without changing the final duration, so the
        # Faster-Whisper word timing and speech-bubble sync remain valid.
        # 0.97 is intentionally subtle (~half a semitone), avoiding a fake
        # "deep announcer" sound.
        pitch_factor = max(0.94, min(1.0, float(pitch_factor)))
        if pitch_factor < 0.999:
            shifted_rate = int(round(48000 * pitch_factor))
            filters.append(f"asetrate={shifted_rate}")
            filters.append("aresample=48000")
            filters.append(f"atempo={1.0 / pitch_factor:.6f}")

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

    def _elevenlabs_change(source_mp3: Path, stem: str) -> Path:
        api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
        voice_id = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
        if not api_key or not voice_id:
            raise RuntimeError("ElevenLabs not configured")
        endpoint = f"https://api.elevenlabs.io/v1/speech-to-speech/{voice_id}"
        with source_mp3.open("rb") as fh:
            response = requests.post(
                endpoint,
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": api_key},
                files={"audio": (source_mp3.name, fh, "audio/mpeg")},
                data={
                    "model_id": "eleven_multilingual_sts_v2",
                    "remove_background_noise": "true",
                },
                timeout=180,
            )
        response.raise_for_status()
        out_mp3 = AUDIO / f"{stem}_elevenlabs_voice_changer.mp3"
        out_mp3.write_bytes(response.content)
        if out_mp3.stat().st_size < 5000:
            raise RuntimeError("ElevenLabs returned audio too small")
        out_wav = AUDIO / f"{stem}_elevenlabs_voice_changer.wav"
        v4.run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(out_mp3),
            "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(out_wav),
        ])
        return out_wav

    def _hybrid_generate(
        text: str,
        stem: str,
        critical: set[str],
        control: str,
        max_attempts: int = 4,
        roughness_guard: bool = False,
        min_attempts: int = 1,
    ):
        source_mp3, ref_wav = _prepare_reference(text, stem)
        reference_roughness = _roughness_metrics(ref_wav) if roughness_guard else None
        model = v4.WhisperModel("small", device="cpu", compute_type="int8")

        rows = []
        valid = []

        # Preferred optional path: keep MoneyPrinter's delivery but convert it
        # to one fixed ElevenLabs character voice. If credentials/voice are not
        # configured, or the converted take fails QA, fall back to VoxCPM2.
        if os.getenv("ELEVENLABS_API_KEY", "").strip() and os.getenv("ELEVENLABS_VOICE_ID", "").strip():
            try:
                raw = _elevenlabs_change(source_mp3, stem)
                a = _analyze(model, raw, text, critical)
                stab = a["metrics"]
                rough = _roughness_metrics(raw) if roughness_guard else {}
                rough_ok = True
                if roughness_guard and reference_roughness:
                    min_periodicity = max(0.48, float(reference_roughness["periodicity_mean"]) * 0.82)
                    max_flatness = max(0.035, float(reference_roughness["spectral_flatness_mean"]) * 3.0)
                    rough_ok = (
                        float(rough.get("periodicity_mean", 0.0)) >= min_periodicity
                        and float(rough.get("spectral_flatness_mean", 1.0)) <= max_flatness
                    )
                row = {
                    "attempt": 0,
                    "path": raw.name,
                    "engine": "MoneyPrinter br_005 -> ElevenLabs Voice Changer",
                    "model": "eleven_multilingual_sts_v2",
                    "asr_ratio": round(a["ratio"], 4),
                    "missing_critical": a["missing"],
                    "source_wpm": round(a["wpm"], 2),
                    "transcript": a["transcript"],
                    "roughness_guard": roughness_guard,
                    "roughness_ok": rough_ok,
                    "reference_roughness": reference_roughness,
                    **rough,
                    **stab,
                }
                rows.append(row)
                print("ELEVENLABS_VOICE_QA", json.dumps(row, ensure_ascii=False), flush=True)
                if a["ratio"] >= 0.91 and not a["missing"] and rough_ok:
                    return raw, a, row, rows, "elevenlabs-voice-changer"
                print("ELEVENLABS_VOICE_REJECTED", stem, flush=True)
            except Exception as exc:
                print("ELEVENLABS_VOICE_WARN", stem, repr(exc), flush=True)

        client = cont.base.Client("openbmb/VoxCPM-Demo", verbose=False)
        ref = cont.base.handle_file(str(ref_wav))
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
                rough = _roughness_metrics(raw) if roughness_guard else {}
                rough_ok = True
                if roughness_guard and reference_roughness:
                    min_periodicity = max(0.48, float(reference_roughness["periodicity_mean"]) * 0.82)
                    max_flatness = max(0.035, float(reference_roughness["spectral_flatness_mean"]) * 3.0)
                    rough_ok = (
                        float(rough.get("periodicity_mean", 0.0)) >= min_periodicity
                        and float(rough.get("spectral_flatness_mean", 1.0)) <= max_flatness
                    )
                    score += float(rough.get("periodicity_mean", 0.0)) * 1.5
                    score -= float(rough.get("spectral_flatness_mean", 1.0)) * 8.0
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
                    "roughness_guard": roughness_guard,
                    "roughness_ok": rough_ok,
                    "reference_roughness": reference_roughness,
                    **rough,
                    **stab,
                }
                rows.append(row)
                print("MONEYVOX_QA", json.dumps(row, ensure_ascii=False), flush=True)
                if a["ratio"] >= 0.91 and not a["missing"] and rough_ok:
                    valid.append((score, raw, a, row))
                    # Do not spend extra VoxCPM queue time once a take is already
                    # text-clean and prosodically stable.
                    if (
                        attempt >= min_attempts
                        and a["ratio"] >= 0.97
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
            "Use a slightly lower natural pitch center and a warmer chest tone than the reference, while keeping it realistic. "
            "Calm confidence, no radio announcer, no advertisement, no theatrical delivery and no shouting."
        )
        raw, analysis, selected, rows, mode = _hybrid_generate(text, "body", critical, control, 3)
        final = AUDIO / "narration_continuous.wav"
        shifted, tempo = _finalize(raw, analysis, final, 170.0, pitch_factor=0.97)
        selected = {
            **selected,
            "selected": True,
            "voice_architecture": mode,
            "moneyprinter_voice": "br_005",
            "playback_tempo": round(tempo, 6),
            "pitch_factor": 0.97,
            "pitch_direction": "slightly lower and warmer",
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
            "Use the same slightly lower natural pitch center and warmer chest tone as the body. "
            "Do not shout and do not sound like an announcer or advertisement."
        )
        raw, analysis, selected, rows, mode = _hybrid_generate(
            text,
            "signoff",
            critical,
            control,
            max_attempts=4,
            roughness_guard=True,
            min_attempts=3,
        )
        final = AUDIO / "signoff_final.wav"
        shifted, tempo = _finalize(raw, analysis, final, 165.0, pitch_factor=0.97)
        selected = {
            **selected,
            "selected": True,
            "voice_architecture": mode,
            "moneyprinter_voice": "br_005",
            "playback_tempo": round(tempo, 6),
            "accepted_file": final.name,
            "roughness_protection": "periodicity + spectral-flatness guard; MoneyPrinter fallback if all hybrid takes are rough",
        }
        (POST / "signoff_qa.json").write_text(
            json.dumps({"selected": selected, "candidates": rows, "expected_signoff": text}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return final, shifted, float(analysis["ratio"]), str(analysis["transcript"]), selected

    vf.generate_body_voice_locked = generate_body
    vf.generate_stable_previous_signoff = generate_signoff
