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
            "cenas": {"type": "array", "minItems": 5, "maxItems": 5, "items": scene},
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
            "json_schema": {"name": "ze_curioso_script", "strict": True, "schema": script_schema()},
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


def final_background_prompt(topic: str, title: str, text: str, raw_visual: str, index: int) -> str:
    return clean(f"""
Vertical 9:16 cinematic image for a Brazilian TikTok curiosity video.
Topic: {topic}.
Narration in this scene: {text}.
Concrete visual to show: {raw_visual}.
Create a literal, easy-to-understand scene that directly illustrates the narration. Do not use an unrelated metaphor, abstract symbolism, underwater imagery, space, fantasy, surrealism, or random scenery unless the narration explicitly requires it. Keep visual continuity with a modern cinematic curiosity channel. Strong subject, depth, realistic or polished illustrative lighting, high contrast, visually interesting but believable. Leave some clean negative space in the lower side for a recurring cartoon presenter overlay. Do not generate a presenter, host, mascot, straw-hat man, text, captions, letters, logos, interface, infographic, poster, frame, watermark, or border. Scene {index + 1} of 5. Title idea: {title}.
""")[:2000]


def normalize_job(result: dict, topic: str) -> dict:
    scenes_in = [x for x in (result.get("cenas") or []) if isinstance(x, dict)]
    if len(scenes_in) != 5:
        raise RuntimeError(f"Groq retornou {len(scenes_in)} cenas; esperado: 5.")

    scenes = []
    for idx, source in enumerate(scenes_in):
        title = clean(source.get("titulo"))[:70] or (clean(topic)[:70] if idx == 0 else f"Cena {idx + 1}")
        text = clean(source.get("texto"))[:220]
        if not text:
            raise RuntimeError(f"Groq retornou a cena {idx + 1} sem texto narrável.")
        mood = clean(source.get("mood")) or ("surprised" if idx == 0 else "curious")
        raw_visual = clean(source.get("background_prompt"))
        if not raw_visual:
            raw_visual = f"A concrete scene that visually demonstrates: {text}"
        scenes.append({
            "titulo": title,
            "texto": text,
            "mood": mood,
            "background_prompt": final_background_prompt(topic, title, text, raw_visual, idx),
        })

    hook = clean(result.get("hook")) or scenes[0]["texto"]
    cta = clean(result.get("cta")) or "Segue o Zé Curioso para mais curiosidades rápidas."
    title = clean(result.get("titulo")) or clean(topic)[:100]

    scene_script = clean(" ".join(scene["texto"] for scene in scenes))
    model_script = clean(result.get("roteiro"))
    roteiro = scene_script if len(scene_script.split()) >= 45 else model_script
    if len(roteiro.split()) < 45:
        roteiro = clean(f"{hook} {scene_script} {cta}")
    if len(roteiro.split()) < 35:
        raise RuntimeError(f"Roteiro realmente curto demais após normalização: {len(roteiro.split())} palavras.")

    return {
        "versao": "24.mobile.4",
        "tema": clean(result.get("tema")) or clean(topic),
        "titulo": title[:110],
        "hook": hook[:240],
        "roteiro": roteiro,
        "voz": clean(result.get("voz")) or "pt-BR-AntonioNeural",
        "cta": cta,
        "precisa_verificacao": bool(result.get("precisa_verificacao")),
        "cenas": scenes,
        "visual_mode": "cloud_ai_scene_plus_fixed_final_mascot",
        "mascot_asset": "assets/ze_curioso/ze_main.webp",
        "manual_background_required": False,
    }


def make_script(topic: str) -> dict:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY não configurada nos GitHub Actions Secrets.")

    prompt = f"""
Você é o roteirista do canal de curiosidades Zé Curioso. Crie um vídeo vertical curto para TikTok/Reels/Shorts.
Idioma: português brasileiro.
Tema/pergunta: {topic}

O personagem fixo Zé Curioso já existe como PNG e será colocado automaticamente sobre as imagens. NÃO descreva o Zé dentro dos backgrounds.

Regras do roteiro:
- hook forte e verdadeiro já na primeira fala, sem escrever a palavra 'HOOK';
- linguagem natural, simples, curiosa e humana;
- exatamente 5 cenas;
- cada fala com aproximadamente 10 a 18 palavras;
- as 5 falas juntas devem formar uma narração coesa de aproximadamente 60 a 90 palavras;
- sem repetir a mesma informação entre cenas;
- CTA somente na fala da cena 5 e curto: seguir o Zé Curioso;
- não invente estudos, estatísticas ou números;
- evite afirmações médicas ou extraordinárias;
- Zé pode dizer naturalmente 'Oxente...', 'Rapaz...', 'Mas pera aí...' ou 'Agora olha isso...', no máximo uma ou duas vezes no vídeo;
- titulo geral e titulo de cada cena devem ser frases reais e interessantes, nunca rótulos como 'HOOK', 'CENA 1', 'EXPLICAÇÃO' ou 'CTA';
- voz: pt-BR-AntonioNeural.

Regras de background_prompt de cada cena:
- descreva UMA imagem concreta que mostre exatamente o que a fala está dizendo;
- prefira ações, ambientes e objetos reconhecíveis, não conceitos vagos;
- mantenha relação literal com o tema;
- não mande criar texto, legenda, apresentador, mascote ou interface;
- não use cenários aleatórios/metafóricos (oceano, espaço, laboratório, floresta etc.) se isso não estiver diretamente ligado à fala;
- pense no background como a cena visual de um TikTok que precisa fazer sentido mesmo sem som.

precisa_verificacao deve ser true apenas se o tema depender de informação atual ou controversa.
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

    url = "https://api.cloudflare.com/client/v4/accounts/" + urllib.parse.quote(account) + "/ai/run/" + CF_MODEL
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    payload = {"prompt": prompt[:2000], "steps": 6}
    status, data = request_json(url, payload, headers, timeout=180)
    if status == 400 and "steps" in str(data).lower():
        print("[!] Cloudflare rejeitou 'steps'; tentando apenas prompt...", flush=True)
        status, data = request_json(url, {"prompt": prompt[:2000]}, headers, timeout=180)
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
    print("[>] Gerando roteiro e direção visual no Groq...", flush=True)
    job = make_script(topic)
    print(f"[OK] Roteiro pronto: {len(job['roteiro'].split())} palavras.", flush=True)
    scenes = job.get("cenas") or []
    for idx, scene in enumerate(scenes, 1):
        print(f"[>] Gerando cena IA {idx}/{len(scenes)}...", flush=True)
        generate_background(scene["background_prompt"], out_dir / f"scene_{idx:02d}.jpg", 24000 + idx * 113)
    (out_dir / "curiosidade.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[OK] Job mobile cloud pronto: roteiro + 5 cenas IA + mascote fixo definido.", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tema", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    build_job(clean(args.tema), Path(args.out_dir))


if __name__ == "__main__":
    main()
