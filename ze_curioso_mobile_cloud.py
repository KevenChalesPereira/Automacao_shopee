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


def script_schema():
    scene = {
        "type": "object",
        "properties": {
            "titulo": {"type": "string"},
            "texto": {"type": "string"},
            "mood": {"type": "string", "enum": ["surprised", "curious", "point", "smile"]},
            "background_prompt": {"type": "string"},
        },
        "required": ["titulo", "texto", "mood", "background_prompt"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "tema": {"type": "string"},
            "titulo": {"type": "string"},
            "hook": {"type": "string"},
            "roteiro": {"type": "string"},
            "voz": {"type": "string"},
            "cta": {"type": "string"},
            "precisa_verificacao": {"type": "boolean"},
            "cenas": {
                "type": "array",
                "minItems": 5,
                "maxItems": 5,
                "items": scene,
            },
        },
        "required": ["tema", "titulo", "hook", "roteiro", "voz", "cta", "precisa_verificacao", "cenas"],
        "additionalProperties": False,
    }


def groq_generate(api_key: str, prompt: str):
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": GROQ_MODEL,
        "temperature": 0.45,
        "max_completion_tokens": 7000,
        "reasoning_effort": "low",
        "include_reasoning": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "ze_curioso_script",
                "strict": True,
                "schema": script_schema(),
            },
        },
        "messages": [{"role": "user", "content": prompt}],
    }
    status, data = request_json(GROQ_URL, payload, headers, timeout=180)
    if status == 200:
        return data

    print(f"[!] Groq structured output falhou HTTP {status}; tentando fallback JSON mode...", flush=True)
    fallback = {
        "model": GROQ_MODEL,
        "temperature": 0.35,
        "max_completion_tokens": 12000,
        "reasoning_effort": "low",
        "include_reasoning": False,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": prompt + "\nRetorne um único objeto JSON completo e feche todas as chaves."}],
    }
    status2, data2 = request_json(GROQ_URL, fallback, headers, timeout=180)
    if status2 != 200:
        raise RuntimeError(
            f"Groq falhou nas duas tentativas. Structured HTTP {status}: {str(data)[:350]} | "
            f"Fallback HTTP {status2}: {str(data2)[:500]}"
        )
    return data2


def normalize_job(result: dict, topic: str) -> dict:
    """Normaliza a saída do Groq sem depender do validador rígido do FCC antigo."""
    scenes_in = [x for x in (result.get("cenas") or []) if isinstance(x, dict)]
    if len(scenes_in) != 5:
        raise RuntimeError(f"Groq retornou {len(scenes_in)} cenas; esperado: 5.")

    scenes = []
    for idx, source in enumerate(scenes_in):
        title = clean(source.get("titulo"))[:70] or f"Cena {idx + 1}"
        text = clean(source.get("texto"))[:220]
        if not text:
            raise RuntimeError(f"Groq retornou a cena {idx + 1} sem texto narrável.")
        mood = clean(source.get("mood")) or ("surprised" if idx == 0 else "curious")
        background_prompt = clean(source.get("background_prompt"))
        if not background_prompt:
            background_prompt = (
                f"Vertical 9:16 cinematic dark TikTok background about {topic}. "
                f"Scene: {title}. Context: {text}. High contrast, strong depth, dramatic realistic lighting, "
                "no text, no letters, no logo, no watermark, leave breathing room for mascot and captions."
            )
        scenes.append({
            "titulo": title,
            "texto": text,
            "mood": mood,
            "background_prompt": background_prompt[:2000],
        })

    hook = clean(result.get("hook"))
    if not hook:
        hook = scenes[0]["texto"]

    cta = clean(result.get("cta")) or "Segue o Zé Curioso para mais curiosidades rápidas."
    title = clean(result.get("titulo")) or clean(topic)[:100]

    # A narração final deve acompanhar exatamente as cenas. O modelo às vezes
    # devolve o campo 'roteiro' curto, apesar de as cinco cenas estarem boas.
    # Usar as falas das cenas evita rejeitar um job válido e evita duplicações.
    scene_script = clean(" ".join(scene["texto"] for scene in scenes))
    model_script = clean(result.get("roteiro"))
    roteiro = scene_script if len(scene_script.split()) >= 45 else model_script
    if len(roteiro.split()) < 45:
        roteiro = clean(f"{hook} {scene_script} {cta}")
    if len(roteiro.split()) < 35:
        raise RuntimeError(
            f"Roteiro realmente curto demais após normalização: {len(roteiro.split())} palavras."
        )

    return {
        "versao": "24.mobile.2",
        "tema": clean(result.get("tema")) or clean(topic),
        "titulo": title[:110],
        "hook": hook[:240],
        "roteiro": roteiro,
        "voz": clean(result.get("voz")) or "pt-BR-AntonioNeural",
        "cta": cta,
        "precisa_verificacao": bool(result.get("precisa_verificacao")),
        "cenas": scenes,
        "visual_mode": "cloud_ai_background_plus_mascot",
        "manual_background_required": False,
    }


def make_script(topic: str) -> dict:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY não configurada nos GitHub Actions Secrets.")

    prompt = f"""
Crie o roteiro de um vídeo vertical curto do canal dark de TikTok Zé Curioso.
Idioma: português brasileiro.
Tema: {topic}

Regras:
- hook forte e verdadeiro nos primeiros 2 segundos;
- linguagem natural, simples e curiosa;
- exatamente 5 cenas;
- cada texto de cena deve ter aproximadamente 10 a 18 palavras;
- a concatenação das 5 falas deve formar uma narração coesa de aproximadamente 60 a 90 palavras;
- a cena 1 já começa com o hook, sem repetir depois;
- CTA somente na cena 5: seguir o Zé Curioso;
- não invente estudos, estatísticas ou números;
- evite afirmações médicas ou extraordinárias;
- Zé pode usar naturalmente "Oxente...", "Rapaz...", "Mas pera aí..." ou "Agora olha isso...", sem caricatura;
- cada cena precisa de título curto, texto narrável e mood;
- cada background_prompt descreve SOMENTE o cenário/fundo daquela cena: vertical 9:16, cinematográfico, chamativo, alto contraste, profundidade, iluminação interessante, coerente com a fala, sem texto, letras, logos, UI ou watermark, deixando espaço para personagem PNG e legendas;
- voz: pt-BR-AntonioNeural;
- precisa_verificacao deve ser true apenas se o tema depender de informação atual/controversa.
""".strip()

    data = groq_generate(api_key, prompt)
    text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    result = core.extract_json_object(text)
    if not result:
        raise RuntimeError("Groq respondeu, mas não retornou JSON utilizável.")
    return normalize_job(result, topic)


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
    print("[>] Gerando roteiro estruturado no Groq...", flush=True)
    job = make_script(topic)
    print(f"[OK] Roteiro Groq pronto: {len(job['roteiro'].split())} palavras.", flush=True)
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
