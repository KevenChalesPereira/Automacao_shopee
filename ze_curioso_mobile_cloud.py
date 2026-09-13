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


def groq_json(api_key: str, prompt: str):
    """Pede JSON válido sem depender de JSON Schema específico do modelo."""
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": GROQ_MODEL,
        "temperature": 0.38,
        "max_completion_tokens": 8000,
        "reasoning_effort": "low",
        "include_reasoning": False,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": prompt}],
    }
    status, data = request_json(GROQ_URL, payload, headers, timeout=180)
    if status != 200:
        raise RuntimeError(f"Groq HTTP {status}: {str(data)[:800]}")
    return data


def pick(obj: dict, *keys):
    for key in keys:
        value = obj.get(key)
        if clean(value):
            return value
    return ""


def split_into_five(text: str):
    """Divide uma narração em 5 blocos equilibrados sem depender da pontuação do modelo."""
    words = clean(text).split()
    if len(words) < 35:
        return []
    chunks = []
    n = len(words)
    start = 0
    for i in range(5):
        end = round((i + 1) * n / 5)
        chunks.append(" ".join(words[start:end]).strip())
        start = end
    return chunks if all(chunks) else []


def final_background_prompt(topic: str, title: str, text: str, raw_visual: str, index: int) -> str:
    return clean(f"""
Vertical 9:16 cinematic image for a Brazilian TikTok curiosity video.
Topic: {topic}.
Narration in this scene: {text}.
Concrete visual to show: {raw_visual}.
Create a literal, easy-to-understand scene that directly illustrates the narration. Do not use an unrelated metaphor, abstract symbolism, underwater imagery, space, fantasy, surrealism, or random scenery unless the narration explicitly requires it. Keep visual continuity with a modern cinematic curiosity channel. Strong subject, depth, realistic or polished illustrative lighting, high contrast, visually interesting but believable. Leave some clean negative space in the lower side for a recurring cartoon presenter overlay. Do not generate a presenter, host, mascot, straw-hat man, text, captions, letters, logos, interface, infographic, poster, frame, watermark, or border. Scene {index + 1} of 5. Title idea: {title}.
""")[:2000]


def normalize_job(result: dict, topic: str) -> dict:
    scenes_in = result.get("cenas") or result.get("scenes") or []
    scenes_in = [x for x in scenes_in if isinstance(x, dict)]
    if len(scenes_in) != 5:
        raise RuntimeError(f"Groq retornou {len(scenes_in)} cenas; esperado: 5.")

    texts = [
        clean(pick(scene, "texto", "fala", "narracao", "narração", "voiceover", "script", "caption"))[:220]
        for scene in scenes_in
    ]

    # Alguns modelos devolvem as cenas visuais certas, mas deixam as falas vazias.
    # Nesse caso, reaproveita a narração geral e a divide em 5 partes equilibradas.
    if any(not t for t in texts):
        general_script = clean(pick(result, "roteiro", "narracao", "narração", "script", "voiceover"))
        rebuilt = split_into_five(general_script)
        if rebuilt:
            texts = rebuilt

    if any(not t for t in texts):
        missing = [str(i + 1) for i, t in enumerate(texts) if not t]
        raise RuntimeError("Groq deixou cena(s) sem fala: " + ", ".join(missing))

    scenes = []
    for idx, source in enumerate(scenes_in):
        title = clean(pick(source, "titulo", "title", "headline"))[:70]
        if not title:
            title = clean(topic)[:70] if idx == 0 else f"Cena {idx + 1}"
        mood = clean(pick(source, "mood", "expressao", "expressão", "expression")) or ("surprised" if idx == 0 else "curious")
        raw_visual = clean(pick(source, "background_prompt", "visual", "imagem", "image_prompt", "cenario", "cenário", "scene_prompt"))
        if not raw_visual:
            raw_visual = f"A concrete scene that visually demonstrates: {texts[idx]}"
        scenes.append({
            "titulo": title,
            "texto": texts[idx],
            "mood": mood,
            "background_prompt": final_background_prompt(topic, title, texts[idx], raw_visual, idx),
        })

    hook = clean(pick(result, "hook", "gancho")) or scenes[0]["texto"]
    cta = clean(pick(result, "cta", "call_to_action")) or "Segue o Zé Curioso para mais curiosidades rápidas."
    title = clean(pick(result, "titulo", "title")) or clean(topic)[:100]

    # O áudio deve ser exatamente a soma das 5 falas, sem texto escondido nem repetição.
    roteiro = clean(" ".join(scene["texto"] for scene in scenes))
    if len(roteiro.split()) < 45:
        raise RuntimeError(f"Roteiro curto demais: {len(roteiro.split())} palavras.")

    return {
        "versao": "24.mobile.5",
        "tema": clean(pick(result, "tema", "topic")) or clean(topic),
        "titulo": title[:110],
        "hook": hook[:240],
        "roteiro": roteiro,
        "voz": "pt-BR-AntonioNeural",
        "cta": cta,
        "precisa_verificacao": bool(result.get("precisa_verificacao") or result.get("needs_verification")),
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
Você é o roteirista do canal de curiosidades Zé Curioso. Gere SOMENTE um objeto JSON válido.
Idioma: português brasileiro.
Tema/pergunta: {topic}

Use EXATAMENTE esta estrutura e estes nomes de campos:
{{
  "tema": "...",
  "titulo": "...",
  "hook": "...",
  "roteiro": "narração completa",
  "voz": "pt-BR-AntonioNeural",
  "cta": "...",
  "precisa_verificacao": false,
  "cenas": [
    {{"titulo":"...", "texto":"...", "mood":"surprised", "background_prompt":"..."}},
    {{"titulo":"...", "texto":"...", "mood":"curious", "background_prompt":"..."}},
    {{"titulo":"...", "texto":"...", "mood":"point", "background_prompt":"..."}},
    {{"titulo":"...", "texto":"...", "mood":"curious", "background_prompt":"..."}},
    {{"titulo":"...", "texto":"...", "mood":"smile", "background_prompt":"..."}}
  ]
}}

O personagem fixo Zé Curioso já existe como PNG e será colocado automaticamente sobre as imagens. NÃO descreva o Zé dentro dos backgrounds.

Regras obrigatórias:
- exatamente 5 cenas e todas precisam ter o campo "texto" preenchido;
- hook forte e verdadeiro já no "texto" da primeira cena, sem escrever a palavra HOOK;
- linguagem natural, simples e humana;
- cada "texto" deve ter aproximadamente 10 a 18 palavras;
- as 5 falas juntas devem formar uma explicação coesa de aproximadamente 60 a 90 palavras;
- "roteiro" deve ser exatamente a concatenação das 5 falas, sem conteúdo extra;
- sem repetir a mesma informação;
- CTA curto somente no "texto" da cena 5: seguir o Zé Curioso;
- não invente estudos, estatísticas, números, causas absolutas ou explicações científicas que não sejam bem estabelecidas;
- quando houver mais de uma explicação plausível, diga isso de forma simples (por exemplo: companhia, curiosidade, rotina, segurança ou atenção);
- no máximo uma ou duas expressões como "Oxente..." ou "Rapaz..." no vídeo;
- títulos reais e interessantes; nunca use rótulos como HOOK, CENA 1, EXPLICAÇÃO ou CTA;
- "background_prompt" deve descrever UMA imagem concreta e literal que mostre a fala daquela cena;
- não peça texto, legenda, apresentador, mascote ou interface no background;
- não use oceano, espaço, laboratório, floresta ou cenários aleatórios se a fala não exigir isso;
- "precisa_verificacao" só é true se o tema depender de informação atual ou controversa.
""".strip()

    print("[>] Gerando roteiro e direção visual no Groq...", flush=True)
    data = groq_json(api_key, prompt)
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
    job = make_script(topic)
    print(f"[OK] Roteiro pronto: {len(job['roteiro'].split())} palavras.", flush=True)
    scenes = job.get("cenas") or []
    for idx, scene in enumerate(scenes, 1):
        print(f"[>] Gerando cena IA {idx}/{len(scenes)}...", flush=True)
        generate_background(scene["background_prompt"], out_dir / f"scene_{idx:02d}.jpg", 24000 + idx * 113)
    (out_dir / "curiosidade.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[OK] Job mobile cloud pronto: roteiro + 5 cenas IA + mascote final.", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tema", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    build_job(clean(args.tema), Path(args.out_dir))


if __name__ == "__main__":
    main()
