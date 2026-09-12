#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import ze_curioso_v24 as core

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
CF_MODEL = "@cf/black-forest-labs/flux-1-schnell"


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def request_json(url, payload, headers, timeout=180):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "ze-curioso-mobile", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            data = json.loads(raw)
        except Exception:
            data = {"raw": raw}
        return exc.code, data


def make_script(topic: str) -> dict:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY não configurada nos GitHub Actions Secrets.")

    prompt = f"""
Você é o roteirista do canal dark de TikTok Zé Curioso.
Crie um roteiro curto, curioso e natural em português brasileiro.

OBJETIVO
- prender atenção nos 2 primeiros segundos;
- criar vínculo com quem assiste;
- explicar uma curiosidade de forma simples;
- soar como fala humana, não como texto de apresentação;
- usar o Zé Curioso como personagem recorrente, mas sem caricatura de sotaque.

ESTILO
- pode usar naturalmente: "Oxente...", "Rapaz...", "Mas pera aí...", "Agora olha isso...";
- sem bullet points na narração;
- sem estatísticas, estudos ou números inventados;
- sem afirmações médicas ou extraordinárias;
- 60 a 90 palavras;
- exatamente 5 cenas;
- CTA somente na quinta cena.

TEMA: {topic}

Responda SOMENTE JSON válido:
{{
  "tema": "...",
  "titulo": "...",
  "hook": "...",
  "roteiro": "...",
  "voz": "pt-BR-AntonioNeural",
  "cta": "Segue o Zé Curioso para mais curiosidades rápidas.",
  "precisa_verificacao": false,
  "cenas": [
    {{"titulo":"...","texto":"...","mood":"surprised","background_prompt":"..."}},
    {{"titulo":"...","texto":"...","mood":"curious","background_prompt":"..."}},
    {{"titulo":"...","texto":"...","mood":"curious","background_prompt":"..."}},
    {{"titulo":"...","texto":"...","mood":"point","background_prompt":"..."}},
    {{"titulo":"...","texto":"...","mood":"smile","background_prompt":"..."}}
  ]
}}

REGRAS PARA background_prompt
- descreva apenas o FUNDO da cena;
- imagem vertical 9:16 cinematográfica e chamativa;
- coerente com a frase da cena;
- alto contraste, profundidade e iluminação interessante;
- sem texto, sem letras, sem logo, sem UI;
- deixe espaço livre lateral ou inferior para o PNG do Zé Curioso e legendas.
""".strip()

    payload = {
        "model": GROQ_MODEL,
        "temperature": 0.3,
        "max_tokens": 3500,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": prompt}],
    }
    status, data = request_json(
        GROQ_URL,
        payload,
        {"Authorization": f"Bearer {api_key}"},
        timeout=150,
    )
    if status != 200:
        raise RuntimeError(f"Groq HTTP {status}: {str(data)[:800]}")

    text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    result = core.extract_json_object(text)
    if not result:
        raise RuntimeError("Groq não retornou JSON utilizável.")

    job = core.validate_job(result, topic)
    original_scenes = [x for x in (result.get("cenas") or []) if isinstance(x, dict)]
    for idx, scene in enumerate(job["cenas"]):
        source = original_scenes[idx] if idx < len(original_scenes) else {}
        scene["mood"] = clean(source.get("mood")) or "curious"
        scene["background_prompt"] = clean(source.get("background_prompt"))
        if not scene["background_prompt"]:
            scene["background_prompt"] = (
                f"Vertical 9:16 cinematic dark TikTok background about {topic}. "
                f"Scene: {scene['titulo']}. Context: {scene['texto']}. "
                "High contrast, strong depth, dramatic realistic lighting, no text, no watermark, "
                "leave breathing room for mascot and captions."
            )
    job["versao"] = "24.mobile"
    job["visual_mode"] = "cloud_ai_background_plus_mascot"
    job["manual_background_required"] = False
    return job


def generate_background(prompt: str, destination: Path, seed: int):
    account = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    token = os.getenv("CLOUDFLARE_API_TOKEN")
    if not account or not token:
        raise RuntimeError("Cloudflare não configurado nos GitHub Actions Secrets.")

    url = (
        "https://api.cloudflare.com/client/v4/accounts/"
        + urllib.parse.quote(account)
        + "/ai/run/"
        + CF_MODEL
    )
    payload = {"prompt": prompt[:2000], "seed": seed, "steps": 6}
    status, data = request_json(
        url,
        payload,
        {"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=180,
    )
    if status != 200:
        raise RuntimeError(f"Cloudflare HTTP {status}: {str(data)[:800]}")

    result = data.get("result")
    image_b64 = result.get("image") if isinstance(result, dict) else None
    if not image_b64 and isinstance(result, str):
        image_b64 = result
    if not image_b64:
        raise RuntimeError("Cloudflare não retornou imagem.")
    if image_b64.startswith("data:") and "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]
    destination.write_bytes(base64.b64decode(image_b64))


def build_job(topic: str, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    job = make_script(topic)
    scenes = job.get("cenas") or []
    for idx, scene in enumerate(scenes, 1):
        print(f"[>] Gerando background IA {idx}/{len(scenes)}...", flush=True)
        generate_background(scene["background_prompt"], out_dir / f"scene_{idx:02d}.jpg", 24000 + idx * 113)
    (out_dir / "curiosidade.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[OK] Job mobile cloud pronto.", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tema", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    build_job(clean(args.tema), Path(args.out_dir))


if __name__ == "__main__":
    main()
