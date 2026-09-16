from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from faster_whisper import WhisperModel

import ze_postavel_woodfrog_scene_voice_bubble_v4 as v4
import ze_postavel_woodfrog_voice_v5_final as v5

POST = v4.POST
ASSETS = v4.ASSETS
AUDIO = v4.AUDIO
SCENES = v4.SCENES
BASE_V5_ARTIFACT_ID = 10446004953

SCENE4_TEXT = (
    "Na primavera ele descongela de dentro pra fora! "
    "Primeiro o coração volta; depois o cérebro; e por fim, as pernas."
)
SCENE4_CONTROL = (
    v5.VOICE_CONTROL
    + " This scene must feel brisk, animated and progressive, because you are listing a surprising recovery sequence."
    + " Keep forward momentum from start to finish. No contemplative delivery and no dramatic long pauses."
    + " Speak the sequence in a compact conversational rhythm around 165 to 175 words per minute."
    + " Give a small energetic lift to 'coração', then 'cérebro', then 'pernas'."
)


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def download_v5_base() -> Path:
    token = os.environ["GH_TOKEN"]
    z = Path("/tmp/v5_good_takes.zip")
    out = Path("/tmp/v5_good_takes")
    shutil.rmtree(out, ignore_errors=True)
    run([
        "curl", "--fail", "--location", "--retry", "3",
        "-H", f"Authorization: Bearer {token}",
        "-H", "Accept: application/vnd.github+json",
        "-H", "X-GitHub-Api-Version: 2022-11-28",
        f"https://api.github.com/repos/KevenChalesPereira/Automacao_shopee/actions/artifacts/{BASE_V5_ARTIFACT_ID}/zip",
        "-o", str(z),
    ])
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(z) as archive:
        archive.extractall(out)
    return out


def load_preserved_scene(scene_idx: int, src_root: Path, model: WhisperModel) -> dict:
    src = src_root / "audio" / f"scene_{scene_idx:02d}_accepted.wav"
    dst = AUDIO / f"scene_{scene_idx:02d}_accepted.wav"
    shutil.copy2(src, dst)
    duration = v4.probe_duration(dst)
    words, transcript = v4.transcribe(model, dst)
    ratio, critical_ok, missing, mapping = v4.scene_score(scene_idx, words)
    if ratio < 0.94 or not critical_ok:
        raise RuntimeError(f"Preserved V5 scene {scene_idx} failed recheck: ratio={ratio}, missing={missing}")
    return {
        "ratio": ratio,
        "critical_ok": critical_ok,
        "missing_critical": missing,
        "raw": dst,
        "words": words,
        "mapping": mapping,
        "transcript": transcript,
        "duration": duration,
        "accepted": dst,
        "accepted_duration": duration,
        "prosody": v5.prosody_metrics(dst, words, duration),
        "preserved_from_run": 35096337221,
    }


def speed_to_target(candidate: dict, target_wpm: float = 158.0) -> dict:
    current = float(candidate["prosody"]["words_per_minute"])
    if current >= 150.0:
        return candidate
    factor = min(1.14, max(1.0, target_wpm / max(current, 1.0)))
    src = candidate["raw"]
    sped = AUDIO / "scene_04_speed_corrected.wav"
    run([
        "ffmpeg", "-y", "-i", str(src),
        "-af", f"atempo={factor:.5f}",
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(sped),
    ])
    words = [
        {**w, "start": float(w["start"]) / factor, "end": float(w["end"]) / factor}
        for w in candidate["words"]
    ]
    duration = v4.probe_duration(sped)
    candidate = dict(candidate)
    candidate["raw"] = sped
    candidate["words"] = words
    candidate["duration"] = duration
    candidate["prosody"] = v5.prosody_metrics(sped, words, duration)
    candidate["tempo_correction_factor"] = round(factor, 5)
    return candidate


def generate_scene4(client, ref, model: WhisperModel) -> dict:
    valid = []
    fallback = None
    for attempt in range(1, 9):
        print(f"SCENE_04_FINAL_ATTEMPT {attempt}", flush=True)
        try:
            result = client.predict(
                SCENE4_TEXT, SCENE4_CONTROL, ref, False, "", 2.0, True, False, api_name="/generate"
            )
        except Exception as exc:
            msg = str(exc).lower()
            if "queue is full" in msg or "429" in msg or "busy" in msg:
                time.sleep(min(10 + attempt * 2, 24))
                continue
            raise

        src = Path(v4.base.extract_path(result))
        if not src.exists() or src.stat().st_size < 8000:
            continue
        raw = AUDIO / f"scene_04_final_candidate_{attempt:02d}.wav"
        run(["ffmpeg", "-y", "-i", str(src), "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(raw)])
        duration = v4.probe_duration(raw)
        words, transcript = v4.transcribe(model, raw)
        if not words:
            continue
        ratio, critical_ok, missing, mapping = v4.scene_score(4, words)
        prosody = v5.prosody_metrics(raw, words, duration)
        c = {
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
        print(
            "SCENE4_FINAL_QA", attempt,
            "ratio", round(ratio, 4),
            "critical", critical_ok,
            "wpm", prosody["words_per_minute"],
            "lively", prosody["liveliness_score"],
            "transcript", transcript,
            flush=True,
        )
        if critical_ok and ratio >= 0.94:
            valid.append(c)
            if fallback is None or prosody["words_per_minute"] > fallback["prosody"]["words_per_minute"]:
                fallback = c
            if prosody["words_per_minute"] >= 150.0 and prosody["liveliness_score"] >= 0.78:
                break
        time.sleep(1.5)

    if not valid:
        raise RuntimeError("Scene 4 final: no intelligible take")

    fast = [c for c in valid if c["prosody"]["words_per_minute"] >= 150.0]
    if fast:
        best = max(fast, key=lambda c: (c["prosody"]["liveliness_score"], c["ratio"]))
    else:
        best = speed_to_target(max(valid, key=lambda c: c["prosody"]["words_per_minute"]))

    # Re-validate after any small tempo correction.
    check_words, check_transcript = v4.transcribe(model, best["raw"])
    ratio, critical_ok, missing, mapping = v4.scene_score(4, check_words)
    if ratio < 0.94 or not critical_ok:
        raise RuntimeError(f"Scene 4 final failed after selection: ratio={ratio}, missing={missing}")
    best["words"] = check_words
    best["mapping"] = mapping
    best["transcript"] = check_transcript
    best["ratio"] = ratio
    best["critical_ok"] = critical_ok
    best["missing_critical"] = missing
    best["duration"] = v4.probe_duration(best["raw"])
    best["prosody"] = v5.prosody_metrics(best["raw"], check_words, best["duration"])

    first = check_words[0]["start"]
    last = check_words[-1]["end"]
    trim_start = max(0.0, first - 0.08)
    trim_end = min(best["duration"], last + 0.18)
    trimmed_duration = max(0.5, trim_end - trim_start)
    accepted = AUDIO / "scene_04_accepted.wav"
    fade_out_start = max(0.0, trimmed_duration - 0.012)
    run([
        "ffmpeg", "-y", "-ss", f"{trim_start:.4f}", "-t", f"{trimmed_duration:.4f}",
        "-i", str(best["raw"]),
        "-af", f"loudnorm=I=-16:TP=-2:LRA=8,afade=t=in:st=0:d=0.010,afade=t=out:st={fade_out_start:.4f}:d=0.012",
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(accepted),
    ])
    words2, transcript2 = v4.transcribe(model, accepted)
    ratio2, critical2, missing2, mapping2 = v4.scene_score(4, words2)
    if ratio2 < 0.94 or not critical2:
        raise RuntimeError(f"Accepted scene 4 failed final QA: ratio={ratio2}, missing={missing2}")
    dur2 = v4.probe_duration(accepted)
    prosody2 = v5.prosody_metrics(accepted, words2, dur2)
    if prosody2["words_per_minute"] < 150.0:
        raise RuntimeError(f"Accepted scene 4 still too slow: {prosody2['words_per_minute']} WPM")
    return {
        **best,
        "ratio": ratio2,
        "critical_ok": critical2,
        "missing_critical": missing2,
        "words": words2,
        "mapping": mapping2,
        "transcript": transcript2,
        "accepted": accepted,
        "accepted_duration": dur2,
        "prosody": prosody2,
    }


def main() -> None:
    v4.base.prepare_dirs()
    v4.base.rebuild_mascot()
    v4.base.download_voice_reference()
    v4.base.download_frog_photos()
    v4.card.build_scenes_card()
    (POST / "roteiro.txt").write_text(" ".join(v4.SCENE_DISPLAY_TEXTS), encoding="utf-8")

    model = WhisperModel("small", device="cpu", compute_type="int8")
    base = download_v5_base()
    results = []
    preserved = {1, 2, 3, 5}
    preserved_results = {i: load_preserved_scene(i, base, model) for i in preserved}

    client = v4.base.Client("openbmb/VoxCPM-Demo", verbose=False)
    ref = v4.base.handle_file(str(ASSETS / "voice_ref.mp3"))
    new4 = generate_scene4(client, ref, model)
    for i in range(1, 6):
        results.append(new4 if i == 4 else preserved_results[i])

    narration, offsets = v4.concat_scenes(results)
    timing, alignment_ratio = v4.build_bubble_timing(results, offsets)
    v4.bubble.render_video(timing, narration)
    shutil.copy2(SCENES / "scene_01.jpg", POST / "capa_sapo_congela_final.jpg")
    v5.final_qa_v5(results, timing, alignment_ratio, narration)

    qa_path = POST / "qa.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    qa["revision"] = "card-v5-final-locked-good-takes-scene4-revived"
    qa["preserved_scenes_from_run"] = {"run_id": 35096337221, "scenes": [1, 2, 3, 5]}
    qa["scene4_min_wpm_gate"] = 150.0
    qa["only_changed_from_v5"] = "scene 4 narration take"
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    print("FINAL_V5_SCENE4_REVIVED_OK", POST / "ze_curioso_sapo_congela_final.mp4", flush=True)


if __name__ == "__main__":
    main()
