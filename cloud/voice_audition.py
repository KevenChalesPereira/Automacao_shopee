#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

CANDIDATES = [
    ("julio", "pt-BR-JulioNeural", ["+9%", "+5%", "+3%", "+5%", "+8%"], ["+3Hz", "+1Hz", "+0Hz", "+1Hz", "+2Hz"]),
    ("humberto", "pt-BR-HumbertoNeural", ["+8%", "+4%", "+3%", "+4%", "+7%"], ["+2Hz", "+1Hz", "+0Hz", "+1Hz", "+2Hz"]),
    ("valerio", "pt-BR-ValerioNeural", ["+8%", "+4%", "+2%", "+4%", "+7%"], ["+3Hz", "+1Hz", "+0Hz", "+1Hz", "+2Hz"]),
    ("nicolau", "pt-BR-NicolauNeural", ["+9%", "+5%", "+3%", "+5%", "+8%"], ["+3Hz", "+1Hz", "+0Hz", "+1Hz", "+2Hz"]),
]


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def perform(text: str, index: int) -> str:
    text = clean(text)
    if index == 0:
        text = re.sub(r"^Se liga nessa,\s*curioso\s*:", "Se liga nessa, curioso!", text, flags=re.I)
    if index == 4:
        text = text.replace("Agora você sabe. Bora pra próxima com o Zé!", "Agora você sabe! Bora pra próxima com o Zé!")
    text = re.sub(r"\s+(mas|só que|e aqui fica interessante),?\s+", r", \1... ", text, flags=re.I)
    return text


def run(cmd):
    print("[>] " + " ".join(str(x) for x in cmd), flush=True)
    r = subprocess.run([str(x) for x in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
    if r.returncode:
        print(r.stderr[-3000:], flush=True)
        raise RuntimeError(f"Falhou: {cmd[0]}")
    return r


def generate_voice(scenes, slug, voice, rates, pitches, out_dir: Path):
    work = out_dir / f"_{slug}"
    work.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, scene in enumerate(scenes):
        part = work / f"part_{i+1:02d}.mp3"
        cmd = [
            "edge-tts", "--voice", voice,
            f"--rate={rates[i]}", f"--pitch={pitches[i]}",
            "--text", perform(scene.get("texto"), i),
            "--write-media", str(part),
        ]
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
        if r.returncode or not part.is_file() or part.stat().st_size < 1000:
            raise RuntimeError(f"{voice} falhou na cena {i+1}: {r.stderr[-500:]}")
        parts.append(part)

    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    raw = work / "raw.mp3"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat, "-c:a", "libmp3lame", "-q:a", "2", raw])
    final = out_dir / f"voz_{slug}.mp3"
    run(["ffmpeg", "-y", "-i", raw, "-af", "loudnorm=I=-16:LRA=7:TP=-1.5", "-c:a", "libmp3lame", "-q:a", "2", final])
    print(f"[OK] {slug}: {voice} -> {final}", flush=True)


def main():
    if len(sys.argv) < 3:
        raise SystemExit("Uso: voice_audition.py <job_dir> <out_dir>")
    job_dir = Path(sys.argv[1]).resolve()
    out_dir = Path(sys.argv[2]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    job = json.loads((job_dir / "curiosidade.json").read_text(encoding="utf-8"))
    scenes = [x for x in (job.get("cenas") or []) if isinstance(x, dict)][:5]
    if len(scenes) != 5:
        raise RuntimeError("Esperava 5 cenas para o teste de voz.")

    ok = 0
    errors = []
    for slug, voice, rates, pitches in CANDIDATES:
        try:
            generate_voice(scenes, slug, voice, rates, pitches, out_dir)
            ok += 1
        except Exception as exc:
            errors.append(f"{slug}: {exc}")
            print(f"[!] {errors[-1]}", flush=True)
    (out_dir / "README.txt").write_text(
        "Teste de vozes do Zé Curioso. Compare os MP3s usando o mesmo roteiro.\n" + "\n".join(errors),
        encoding="utf-8",
    )
    if ok == 0:
        raise RuntimeError("Nenhuma voz do teste foi gerada.")


if __name__ == "__main__":
    main()
