#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ze_curioso_v24 import FCC_API_KEY, FCC_MODEL, FCC_URL, clean, extract_json_object, http_json, slugify

VERSION = "24.3.0"
DEFAULT_VOICE = "pt-BR-AntonioNeural"

CHARACTER_BIBLE = (
    "Zé Curioso: apresentador adulto brasileiro, simpático, rosto expressivo, "
    "chapéu de palha pequeno, camisa branca e gravata vermelha. Visual consistente "
    "entre cenas, sem caricatura ofensiva."
)


def validate_plan(plan: dict, tema_original: str = "") -> dict:
    if not isinstance(plan, dict):
        raise RuntimeError("Plano V24.3 inválido.")

    titulo = clean(plan.get("titulo"))
    hook = clean(plan.get("hook"))
    roteiro = clean(plan.get("roteiro"))
    cenas = [x for x in (plan.get("cenas") or []) if isinstance(x, dict)]

    if not titulo or not hook:
        raise RuntimeError("Plano sem título ou hook.")
    if not 45 <= len(roteiro.split()) <= 110:
        raise RuntimeError("Roteiro deve ter entre 45 e 110 palavras.")
    if not 5 <= len(cenas) <= 7:
        raise RuntimeError("Plano precisa de 5 a 7 cenas.")

    normalized = []
    total = 0.0
    for idx, scene in enumerate(cenas, 1):
        headline = clean(scene.get("headline"))[:80]
        narration = clean(scene.get("narration"))[:240]
        visual_prompt = clean(scene.get("visual_prompt"))[:900]
        motion_prompt = clean(scene.get("motion_prompt"))[:500]
        camera = clean(scene.get("camera"))[:120]
        transition = clean(scene.get("transition"))[:80]
        input_mode = clean(scene.get("input_mode")).lower() or "text_to_video"
        if input_mode not in {"text_to_video", "image_to_video"}:
            input_mode = "text_to_video"
        try:
            duration = float(scene.get("duration_seconds") or 5.0)
        except Exception:
            duration = 5.0
        duration = max(4.0, min(8.0, duration))
        total += duration

        if not headline or not narration or not visual_prompt or not motion_prompt:
            raise RuntimeError(f"Cena {idx} incompleta para geração Dola.")

        normalized.append({
            "index": idx,
            "headline": headline,
            "narration": narration,
            "duration_seconds": round(duration, 1),
            "input_mode": input_mode,
            "visual_prompt": visual_prompt,
            "motion_prompt": motion_prompt,
            "camera": camera or "slow cinematic push-in",
            "transition": transition or "hard cut",
            "ze_presence": bool(scene.get("ze_presence")),
            "clip_filename": f"scene_{idx:02d}.mp4",
        })

    return {
        "version": VERSION,
        "pipeline": "ai_video_first",
        "provider": "dola_ai",
        "model_hint": "Seedance 2.5 Audio",
        "aspect_ratio": "9:16",
        "quality_hint": "720p",
        "procedural_visual_fallback": False,
        "tema": clean(plan.get("tema")) or clean(tema_original),
        "titulo": titulo[:110],
        "hook": hook[:240],
        "roteiro": roteiro,
        "voz": clean(plan.get("voz")) or DEFAULT_VOICE,
        "cta": clean(plan.get("cta")) or "Segue o Zé Curioso para mais curiosidades rápidas.",
        "character_bible": CHARACTER_BIBLE,
        "target_duration_seconds": round(total, 1),
        "cenas": normalized,
        "render_contract": {
            "required": [x["clip_filename"] for x in normalized],
            "rule": "Sem clipes de IA reais, o renderer NÃO deve substituir por cards, desenhos ou slides procedurais.",
        },
    }


def fcc_make_dola_plan(tema: str, timeout: int = 120) -> dict:
    prompt = f"""
Você é diretor de um canal de vídeos curtos chamado Zé Curioso.
Sua tarefa NÃO é desenhar cards nem slides. Você deve planejar CLIPES DE VÍDEO GERADOS POR IA,
com movimento de câmera, ação, iluminação e continuidade visual, preparados para um gerador
text-to-video/image-to-video como Dola AI / Seedance.

TEMA: {tema}

IDENTIDADE DO PERSONAGEM
{CHARACTER_BIBLE}

OBJETIVO VISUAL
- vídeo vertical 9:16, 25 a 35 segundos;
- 5 a 7 cenas, cada uma com 4 a 8 segundos;
- visual cinematográfico, vivo, com profundidade, iluminação e movimento;
- uma ideia visual forte por cena;
- Zé Curioso aparece somente em cenas estratégicas, não o tempo inteiro;
- nada de quadro preto, bullet points, cards de apresentação ou aparência de PowerPoint;
- headlines curtas são sobrepostas depois pelo renderer, não devem fazer parte da imagem gerada;
- o prompt visual deve descrever a cena sem texto escrito dentro da imagem;
- cada cena deve indicar movimento real: sujeito + ação + câmera + ambiente;
- o roteiro total deve ter 45 a 110 palavras e soar natural em voz brasileira;
- não invente estatísticas, estudos, números ou fatos específicos sem segurança;
- CTA somente no final.

Responda SOMENTE JSON válido:
{{
  "tema": "...",
  "titulo": "...",
  "hook": "...",
  "roteiro": "...",
  "voz": "pt-BR-AntonioNeural",
  "cta": "Segue o Zé Curioso para mais curiosidades rápidas.",
  "cenas": [
    {{
      "headline": "...",
      "narration": "...",
      "duration_seconds": 5,
      "input_mode": "text_to_video",
      "visual_prompt": "descrição cinematográfica completa, sem texto na imagem",
      "motion_prompt": "ação principal e movimento natural da cena",
      "camera": "movimento de câmera",
      "transition": "hard cut",
      "ze_presence": true
    }}
  ]
}}
""".strip()

    body = {
        "model": FCC_MODEL,
        "max_tokens": 5000,
        "temperature": 0.35,
        "stream": False,
        "messages": [{"role": "user", "content": prompt}],
    }

    print("[>] V24.3: criando storyboard de vídeo IA para Dola/Seedance...", flush=True)
    status, data = http_json(
        FCC_URL,
        method="POST",
        data=body,
        headers={"x-api-key": FCC_API_KEY, "anthropic-version": "2023-06-01"},
        timeout=timeout,
    )
    if status != 200:
        raise RuntimeError(f"FCC retornou HTTP {status}: {str(data)[:800]}")

    text = "\n".join(
        str(block.get("text") or "")
        for block in (data.get("content") or [])
        if isinstance(block, dict) and block.get("type") == "text"
    )
    raw = extract_json_object(text)
    if not raw:
        raise RuntimeError("FCC não retornou JSON utilizável para o storyboard Dola.")
    return validate_plan(raw, tema)


def main():
    ap = argparse.ArgumentParser(description="Zé Curioso V24.3 — AI Video First / Dola-ready")
    ap.add_argument("tema", nargs="*", help="tema ou pergunta da curiosidade")
    ap.add_argument("--validar-json", help="valida um plano V24.3 já existente sem chamar FCC")
    args = ap.parse_args()

    if args.validar_json:
        path = Path(args.validar_json)
        data = json.loads(path.read_text(encoding="utf-8"))
        plan = validate_plan(data, data.get("tema", ""))
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return

    tema = clean(" ".join(args.tema)) or clean(input("Tema/curiosidade: "))
    if not tema:
        raise SystemExit("Nenhum tema informado.")

    plan = fcc_make_dola_plan(tema)
    out = Path.cwd() / "saida_ze_curioso" / slugify(plan["titulo"])
    out.mkdir(parents=True, exist_ok=True)
    target = out / "dola_manifest.json"
    target.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Storyboard Dola/Seedance salvo: {target}", flush=True)
    print("[!] V24.3 não gera cards procedurais. O próximo estágio exige clipes reais de vídeo IA.", flush=True)


if __name__ == "__main__":
    main()
