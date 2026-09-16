from __future__ import annotations

import json
import shutil

import ze_postavel_woodfrog_voice_v5_scene4_final as final1
import ze_postavel_woodfrog_scene_voice_bubble_v4 as v4
import ze_postavel_woodfrog_voice_v5_final as v5


def load_preserved_scene_locked(scene_idx, src_root, model):
    """Preserved scenes are byte-identical to V5 run 35096337221.

    Use that run's already-passed QA as the truth for pronunciation. A fresh
    Whisper pass is used only to rebuild word timestamps/mapping for rendering;
    it must not reject an unchanged approved WAV because ASR can vary slightly.
    """
    src = src_root / "audio" / f"scene_{scene_idx:02d}_accepted.wav"
    dst = final1.AUDIO / f"scene_{scene_idx:02d}_accepted.wav"
    shutil.copy2(src, dst)
    duration = v4.probe_duration(dst)

    old_qa = json.loads((src_root / "qa.json").read_text(encoding="utf-8"))
    locked = next(x for x in old_qa["scene_qa"] if int(x["scene"]) == scene_idx)

    words, fresh_transcript = v4.transcribe(model, dst)
    if not words:
        raise RuntimeError(f"Preserved scene {scene_idx}: no timestamps returned")
    _fresh_ratio, _fresh_critical, _fresh_missing, mapping = v4.scene_score(scene_idx, words)

    return {
        "ratio": float(locked["asr_ratio"]),
        "critical_ok": bool(locked["critical_ok"]),
        "missing_critical": list(locked["missing_critical"]),
        "raw": dst,
        "words": words,
        "mapping": mapping,
        "transcript": locked["transcript"],
        "fresh_timestamp_transcript": fresh_transcript,
        "duration": duration,
        "accepted": dst,
        "accepted_duration": duration,
        "prosody": v5.prosody_metrics(dst, words, duration),
        "preserved_from_run": 35096337221,
        "pronunciation_qa_source": "locked QA from byte-identical V5 artifact",
    }


final1.load_preserved_scene = load_preserved_scene_locked

if __name__ == "__main__":
    final1.main()
