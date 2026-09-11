#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def probe(path: Path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=index,codec_type,codec_name,width,height",
        "-of", "json", str(path),
    ]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
    if r.returncode != 0:
        return {"ok": False, "error": r.stderr[-2000:]}
    data = json.loads(r.stdout or "{}")
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except Exception:
        duration = 0.0
    return {
        "ok": True,
        "duration_seconds": round(duration, 2),
        "width": video.get("width"),
        "height": video.get("height"),
        "video_codec": video.get("codec_name"),
        "has_audio": bool(audio),
        "audio_codec": audio.get("codec_name"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", required=True)
    args = ap.parse_args()
    out = Path(args.output_dir)

    final = out / "anuncio_final.mp4"
    job_path = out / "curiosidade.json"
    diag_path = out / "diagnostico_render.json"

    passed = []
    warnings = []
    recommendations = []

    if not final.is_file():
        warnings.append("MP4 final ausente.")
        meta = {"ok": False}
    else:
        meta = probe(final)
        if meta.get("ok"):
            if meta.get("width") == 1080 and meta.get("height") == 1920:
                passed.append("Formato vertical 1080x1920 confirmado.")
            else:
                warnings.append(f"Formato inesperado: {meta.get('width')}x{meta.get('height')}.")
            if meta.get("has_audio"):
                passed.append("Faixa de áudio presente.")
            else:
                warnings.append("Vídeo sem áudio.")
            duration = float(meta.get("duration_seconds") or 0)
            if 10 <= duration <= 60:
                passed.append(f"Duração adequada para vídeo curto: {duration:.2f}s.")
            else:
                warnings.append(f"Duração fora da faixa alvo de 10–60s: {duration:.2f}s.")
        else:
            warnings.append("ffprobe não conseguiu validar o vídeo final.")

    job = {}
    if job_path.is_file():
        try:
            job = json.loads(job_path.read_text(encoding="utf-8"))
        except Exception:
            warnings.append("curiosidade.json inválido.")
    else:
        warnings.append("curiosidade.json ausente.")

    script = str(job.get("roteiro") or "").strip()
    words = script.split()
    if 35 <= len(words) <= 150:
        passed.append(f"Roteiro curto e narrável: {len(words)} palavras.")
    elif words:
        warnings.append(f"Roteiro com {len(words)} palavras; alvo recomendado é 35–150.")
    else:
        warnings.append("Roteiro ausente.")

    hook = str(job.get("hook") or "").strip()
    if hook:
        passed.append("Hook presente.")
    else:
        warnings.append("Hook ausente.")

    scenes = [x for x in (job.get("cenas") or []) if isinstance(x, dict)]
    if len(scenes) >= 3:
        passed.append(f"Estrutura visual com {len(scenes)} cenas.")
    else:
        warnings.append("Menos de 3 cenas estruturadas.")

    if hook and len(hook.split()) > 20:
        recommendations.append("Encurtar o hook para melhorar impacto nos primeiros segundos.")

    hard_fail = not final.is_file() or not meta.get("ok") or not meta.get("has_audio")
    postable = not hard_fail and not warnings

    diagnostics = {}
    if diag_path.is_file():
        try:
            diagnostics = json.loads(diag_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    report = {
        "version": "ze-curioso-v24",
        "hard_fail": hard_fail,
        "postable_standard": postable,
        "video": meta,
        "script_word_count": len(words),
        "scene_count": len(scenes),
        "passed": passed,
        "warnings": warnings,
        "recommendations": recommendations,
        "diagnostics": diagnostics,
        "note": "QA técnico do Zé Curioso V24. Não mede retenção real, CTR ou desempenho de plataforma.",
    }
    (out / "qa_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    status = "POSTÁVEL TECNICAMENTE" if postable else ("FALHA TÉCNICA" if hard_fail else "POSTÁVEL COM ALERTAS")
    lines = [
        "QA ZÉ CURIOSO STUDIO V24",
        "",
        f"STATUS: {status}",
        "",
        "PASSOU:",
        *([f"- {x}" for x in passed] or ["- Nenhum check aprovado."]),
        "",
        "ALERTAS:",
        *([f"- {x}" for x in warnings] or ["- Nenhum alerta principal."]),
        "",
        "RECOMENDAÇÕES:",
        *([f"- {x}" for x in recommendations] or ["- Nenhuma recomendação adicional."]),
        "",
        report["note"],
    ]
    (out / "qa_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines), flush=True)


if __name__ == "__main__":
    main()
