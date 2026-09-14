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
VOICE = "pt-BR-JulioNeural"
OPENING = "Se liga nessa, curioso:"
CLOSING = "Agora você sabe. Bora pra próxima com o Zé!"


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
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": GROQ_MODEL,
        "temperature": 0.46,
        "max_completion_tokens": 7000,
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
    words = clean(text).split()
    if len(words) < 35:
        return []
    chunks, start, n = [], 0, len(words)
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

IMPORTANT COMPOSITION RULES:
- This image is ONLY the background. A separate cartoon host will be overlaid later.
- DO NOT generate any human, person, man, woman, child, face, silhouette, humanoid, cartoon person, presenter, host, mascot, straw-hat character, tiny person, figurine, doll, statue shaped like a person, or human-like figure anywhere in the image, including the distance or background.
- If the topic involves an animal, show only the animal and environment needed for the explanation; do not add a human owner.
- No text, captions, letters, logos, interface, infographic, poster, watermark or border.
- Keep both lower corners reasonably clean because the recurring host can appear on either side.
- Keep the center visually useful; do not create a giant empty presentation-like area.
- Keep visual continuity across all scenes: same general lighting, color mood and subject identity whenever possible.

Create a literal, easy-to-understand scene that directly illustrates the narration. Avoid unrelated metaphors, surrealism, fantasy or random scenery unless the narration explicitly requires them. Use a polished cinematic curiosity-channel look, strong depth, believable lighting and high contrast. Scene {index + 1} of 5. Title idea: {title}.
""")[:2000]


def normalize_job(result: dict, topic: str) -> dict:
    scenes_in = result.get("cenas") or result.get("scenes") or []
    scenes_in = [x for x in scenes_in if isinstance(x, dict)]
    if len(scenes_in) != 5:
        raise RuntimeError(f"Groq retornou {len(scenes_in)} cenas; esperado: 5.")

    texts = [clean(pick(scene, "texto", "fala", "narracao", "narração", "voiceover", "script", "caption"))[:210] for scene in scenes_in]
    if any(not t for t in texts):
        general_script = clean(pick(result, "roteiro", "narracao", "narração", "script", "voiceover"))
        rebuilt = split_into_five(general_script)
        if rebuilt:
            texts = rebuilt
    if any(not t for t in texts):
        missing = [str(i + 1) for i, t in enumerate(texts) if not t]
        raise RuntimeError("Groq deixou cena(s) sem fala: " + ", ".join(missing))

    if not texts[0].lower().startswith("se liga nessa"):
        texts[0] = clean(f"{OPENING} {texts[0]}")[:235]
    if "bora pra próxima com o zé" not in texts[-1].lower():
        texts[-1] = clean(f"{texts[-1]} {CLOSING}")[:250]

    scenes = []
    for idx, source in enumerate(scenes_in):
        title = clean(pick(source, "titulo", "title", "headline"))[:70] or (clean(topic)[:70] if idx == 0 else f"Cena {idx + 1}")
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

    hook = scenes[0]["texto"]
    title = clean(pick(result, "titulo", "title")) or clean(topic)[:100]
    roteiro = clean(" ".join(scene["texto"] for scene in scenes))
    wc = len(roteiro.split())
    if wc < 45:
        raise RuntimeError(f"Roteiro curto demais: {wc} palavras.")

    return {
        "versao": "24.mobile.8",
        "tema": clean(pick(result, "tema", "topic")) or clean(topic),
        "titulo": title[:110],
        "hook": hook[:250],
        "roteiro": roteiro,
        "voz": VOICE,
        "cta": CLOSING,
        "bordao_abertura": OPENING,
        "bordao_fechamento": CLOSING,
        "precisa_verificacao": bool(result.get("precisa_verificacao") or result.get("needs_verification")),
        "cenas": scenes,
        "visual_mode": "cloud_ai_background_plus_fixed_mascot_organic_dynamic_bubble",
        "mascot_asset": "assets/ze_curioso/ze_main.png",
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

Use EXATAMENTE esta estrutura:
{{
  "tema": "...",
  "titulo": "...",
  "hook": "...",
  "roteiro": "narração completa",
  "voz": "{VOICE}",
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

O Zé Curioso já existe como PNG e será colocado depois. NÃO descreva nenhum apresentador ou pessoa nos backgrounds.

IDENTIDADE DO CANAL:
- A primeira fala começa naturalmente com: "{OPENING}"
- A última fala termina naturalmente com: "{CLOSING}"
- Chame o espectador de "curioso" no máximo uma vez além do bordão.
- O bordão é assinatura, não introdução longa.

REGRAS DE RETENÇÃO E ROTEIRO:
- exatamente 5 cenas, todas com "texto";
- o primeiro fato/pergunta forte precisa aparecer já na primeira frase;
- 7 a 13 palavras de conteúdo por cena, antes dos bordões;
- alvo de 55 a 78 palavras no vídeo inteiro, incluindo bordões;
- cada cena deve avançar a resposta; zero repetição e zero enchimento;
- frases curtas, pontuação natural e pausas que ajudem a narração;
- linguagem jovem, conversada, curiosa e humana; nunca texto escolar;
- use no máximo UMA microvirada do tipo "só que tem um detalhe" ou "e aqui fica interessante";
- não use explicações absolutas quando houver várias causas plausíveis;
- prefira "pode", "costuma", "uma explicação comum" quando a ciência/comportamento não for absoluto;
- não invente estudos, números, estatísticas, instintos ou causas;
- feche a resposta antes do bordão final;
- "roteiro" deve ser exatamente a concatenação das 5 falas;
- títulos reais, nunca rótulos técnicos;
- cada background_prompt descreve UMA imagem concreta e literal da fala;
- NÃO pedir pessoa, apresentador, rosto, silhueta, mascote, boneco, personagem humano, texto, legenda ou interface no background;
- em temas com animais, mostrar o animal e o ambiente, sem dono humano;
- "precisa_verificacao" só é true quando o tema depende de informação atual ou controversa.
""".strip()

    print("[>] Gerando roteiro e direção visual no Groq...", flush=True)
    data = groq_json(api_key, prompt)
    text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    result = core.extract_json_object(text)
    if not result:
        raise RuntimeError("Groq respondeu, mas não retornou JSON utilizável.")
    return normalize_job(result, topic)


def generate_background(prompt: str, destination: Path):
    account = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    token = os.getenv("CLOUDFLARE_API_TOKEN")
    if not account or not token:
        raise RuntimeError("Cloudflare não configurado nos GitHub Actions Secrets.")

    url = "https://api.cloudflare.com/client/v4/accounts/" + urllib.parse.quote(account) + "/ai/run/" + CF_MODEL
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    payload = {"prompt": prompt[:2000], "steps": 6}
    status, data = request_json(url, payload, headers, timeout=180)
    if status == 400 and "steps" in str(data).lower():
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
        generate_background(scene["background_prompt"], out_dir / f"scene_{idx:02d}.jpg")
    (out_dir / "curiosidade.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[OK] Job mobile cloud pronto: roteiro refinado + backgrounds + Zé + voz jovem.", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tema", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    build_job(clean(args.tema), Path(args.out_dir))


if __name__ == "__main__":
    main()
