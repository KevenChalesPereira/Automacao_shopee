#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "cloud" / "render_ze_curioso_auto_v24.py"

spec = importlib.util.spec_from_file_location("ze_renderer_base", BASE_PATH)
base = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(base)

# Mantém exatamente o visual aprovado da v7 e troca somente a interpretação da voz.
# A v7 ficou artificial porque alterava pitch por pós-processamento. Aqui a voz M4
# fica limpa, com ritmo levemente variável e pontuação de performance.
CLEAN_SPEED = [1.055, 1.025, 1.000, 1.020, 1.045]


def performance_text_clean(text: str, index: int) -> str:
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
    # Pausas naturais sem distorcer timbre nem alongar demais.
    text = re.sub(r"\s+(mas|só que|e aqui fica interessante),?\s+", r", \1, ", text, flags=re.I)
    return text


def synthesize_supertonic_clean(scenes, requested_voice, work):
    voice_name = "M4"
    if requested_voice.startswith("supertonic:"):
        voice_name = requested_voice.split(":", 1)[1].strip() or "M4"

    print(f"[>] Supertonic limpo {voice_name}: sem pitch shift e sem voz artificial...", flush=True)

    try:
        from supertonic import TTS

        tts = TTS(auto_download=True)
        style = tts.get_voice_style(voice_name=voice_name)
        audio_files = []

        for i, scene in enumerate(scenes):
            dest = work / f"audio_scene_{i+1:02d}.wav"
            wav, _ = tts.synthesize(
                text=performance_text_clean(scene.get("texto"), i),
                voice_style=style,
                total_steps=8,
                speed=CLEAN_SPEED[i],
                max_chunk_length=300,
                silence_duration=0.075,
                lang="pt",
                verbose=False,
            )
            tts.save_audio(wav, str(dest))
            if not dest.is_file() or dest.stat().st_size < 1000:
                raise RuntimeError(f"Supertonic não gerou {dest.name}")
            audio_files.append(dest)

        durations = [base.ffprobe_duration(p) for p in audio_files]
        concat = work / "audio_concat_supertonic_clean.txt"
        concat.write_text(
            "".join(f"file '{p.resolve()}'\n" for p in audio_files),
            encoding="utf-8",
        )

        narration = work / "narracao.wav"
        base.run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", concat,
            "-af", "loudnorm=I=-16:LRA=8:TP=-1.5",
            "-c:a", "pcm_s16le",
            narration,
        ])
        print(f"[OK] Supertonic M4 limpa ativa: {voice_name}", flush=True)
        return f"supertonic:{voice_name}:clean", narration, durations

    except Exception as exc:
        print(f"[!] Supertonic limpa falhou; usando fallback do renderer base: {exc}", flush=True)
        return None


def build_video(job, job_dir, out_dir):
    # Substitui somente o TTS Supertonic do renderer aprovado.
    original = base.synthesize_supertonic
    base.synthesize_supertonic = synthesize_supertonic_clean
    base.SUPER_SPEED = CLEAN_SPEED
    try:
        base.build_video(job, job_dir, out_dir)
    finally:
        base.synthesize_supertonic = original

    diag_path = out_dir / "diagnostico_render.json"
    if diag_path.is_file():
        diag = json.loads(diag_path.read_text(encoding="utf-8"))
        diag["version"] = "ze-curioso-final-v8-clean-voice"
        diag["voice_treatment"] = "supertonic-M4-clean-no-pitch-shift"
        diag["supertonic_speed"] = CLEAN_SPEED
        diag.pop("supertonic_pitch", None)
        diag_path.write_text(json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    if len(sys.argv) < 3:
        raise SystemExit("Uso: render_ze_curioso_final_v8.py <job_dir> <output_dir>")
    job_dir = Path(sys.argv[1]).resolve()
    out_dir = Path(sys.argv[2]).resolve()
    job = json.loads((job_dir / "curiosidade.json").read_text(encoding="utf-8"))
    build_video(job, job_dir, out_dir)
    print("[OK] Zé Curioso final v8: voz limpa, ritmo natural e visual aprovado.", flush=True)


if __name__ == "__main__":
    main()
