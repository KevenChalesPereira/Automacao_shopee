#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "cloud" / "render_ze_curioso_auto_v24.py"

spec = importlib.util.spec_from_file_location("ze_renderer_base", BASE_PATH)
base = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(base)

VOICE = "pt-BR-AntonioNeural"
RATES = ["+6%", "+3%", "+1%", "+3%", "+5%"]


def performance_text_ptbr(text: str, index: int) -> str:
    text = base.clean(text)
    if index == 0:
        text = re.sub(
            r"^Se liga nessa,\s*curioso\s*:",
            "Se liga nessa, curioso!",
            text,
            flags=re.I,
        )
    if index == 4:
        text = text.replace(
            "Agora você sabe. Bora pra próxima com o Zé!",
            "Agora você sabe! Bora pra próxima com o Zé!",
        )
    text = re.sub(r"\s+(mas|só que|e aqui fica interessante),?\s+", r", \1, ", text, flags=re.I)
    return text


def synthesize_native_ptbr(scenes, requested_voice, work):
    print(f"[>] Voz final pt-BR nativa: {VOICE}", flush=True)
    audio_files = []

    for i, scene in enumerate(scenes):
        dest = work / f"audio_scene_{i+1:02d}.mp3"
        cmd = [
            "edge-tts",
            "--voice", VOICE,
            f"--rate={RATES[i]}",
            "--pitch=+0Hz",
            "--text", performance_text_ptbr(scene.get("texto"), i),
            "--write-media", str(dest),
        ]
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
        if r.returncode != 0 or not dest.is_file() or dest.stat().st_size < 1000:
            raise RuntimeError(f"Edge TTS pt-BR falhou na cena {i+1}: {r.stderr[-1200:]}")
        audio_files.append(dest)

    durations = [base.ffprobe_duration(p) for p in audio_files]
    concat = work / "audio_concat_ptbr.txt"
    concat.write_text("".join(f"file '{p.resolve()}'\n" for p in audio_files), encoding="utf-8")

    narration = work / "narracao_ptbr.mp3"
    base.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat,
        "-af", "loudnorm=I=-16:LRA=7:TP=-1.5",
        "-c:a", "libmp3lame", "-q:a", "2",
        narration,
    ])
    print(f"[OK] Voz brasileira ativa: {VOICE}", flush=True)
    return VOICE, narration, durations


def build_video(job, job_dir, out_dir):
    original = base.synthesize_supertonic
    base.synthesize_supertonic = synthesize_native_ptbr
    try:
        base.build_video(job, job_dir, out_dir)
    finally:
        base.synthesize_supertonic = original

    diag_path = out_dir / "diagnostico_render.json"
    if diag_path.is_file():
        diag = json.loads(diag_path.read_text(encoding="utf-8"))
        diag["version"] = "ze-curioso-ptbr-v9"
        diag["voice"] = VOICE
        diag["voice_treatment"] = "native-ptBR-no-pitch-shift"
        diag["edge_rates"] = RATES
        diag_path.write_text(json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    if len(sys.argv) < 3:
        raise SystemExit("Uso: render_ze_curioso_ptbr_v9.py <job_dir> <output_dir>")
    job_dir = Path(sys.argv[1]).resolve()
    out_dir = Path(sys.argv[2]).resolve()
    job = json.loads((job_dir / "curiosidade.json").read_text(encoding="utf-8"))
    build_video(job, job_dir, out_dir)
    print("[OK] Zé Curioso v9: visual aprovado + voz pt-BR nativa.", flush=True)


if __name__ == "__main__":
    main()
