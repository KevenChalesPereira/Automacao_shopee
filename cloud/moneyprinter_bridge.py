from __future__ import annotations

"""MoneyPrinter bridge for Zé Curioso Studio.

Reuses the MoneyPrinter pipeline ideas that fit GitHub Actions:
- TikTok TTS endpoints/voice ids
- Pexels stock-video search
- script/search-term/metadata stages

Upstream: FujiwaraChoki/MoneyPrinter (MIT).
The original project uses Ollama for the LLM stage. In Actions we keep the
same pipeline stage boundaries but use the already configured Groq endpoint,
because a local Ollama daemon is not practical on the hosted runner.
"""

import base64
import json
import os
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

import requests

TTS_ENDPOINTS = [
    "https://tiktok-tts.weilnet.workers.dev/api/generation",
    "https://tiktoktts.com/api/tiktok-tts",
]
MONEYPRINTER_VOICE = "br_005"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]

DEFAULT_BLACKLIST = [
    "sapo-da-floresta",
    "axolote",
    "tardígrado",
    "besouro-bombardeiro",
    "Turritopsis dohrnii",
]


def _looks_like_b64(value: str) -> bool:
    value = value.strip()
    if value.startswith("data:") and "," in value:
        value = value.split(",", 1)[1]
    return len(value) >= 500 and bool(re.fullmatch(r"[A-Za-z0-9+/=\s]+", value))


def _find_audio_b64(obj):
    if isinstance(obj, str):
        if obj.startswith("data:") and "," in obj:
            obj = obj.split(",", 1)[1]
        return obj if _looks_like_b64(obj) else None
    if isinstance(obj, dict):
        for key in ("data", "audio", "audio_data", "base64", "base64_data"):
            if key in obj:
                found = _find_audio_b64(obj[key])
                if found:
                    return found
        for value in obj.values():
            found = _find_audio_b64(value)
            if found:
                return found
    if isinstance(obj, list):
        for value in obj:
            found = _find_audio_b64(value)
            if found:
                return found
    return None


def split_text(text: str, limit: int = 280) -> list[str]:
    # MoneyPrinter splits around its 300-char TikTok TTS limit. Prefer sentence
    # boundaries so a reference clip never starts mid-thought.
    sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text).strip())
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        if len(sentence) > limit:
            words = sentence.split()
            for word in words:
                trial = (current + " " + word).strip()
                if len(trial) > limit and current:
                    chunks.append(current)
                    current = word
                else:
                    current = trial
            continue
        trial = (current + " " + sentence).strip()
        if len(trial) > limit and current:
            chunks.append(current)
            current = sentence
        else:
            current = trial
    if current:
        chunks.append(current)
    return chunks


def _synth_chunk(text: str, voice: str = MONEYPRINTER_VOICE) -> bytes:
    errors = []
    for endpoint in TTS_ENDPOINTS:
        try:
            r = requests.post(
                endpoint,
                headers={"Content-Type": "application/json", "User-Agent": "ZeCurioso-MoneyPrinter-Bridge/1.0"},
                json={"text": text, "voice": voice},
                timeout=90,
            )
            r.raise_for_status()
            ctype = r.headers.get("content-type", "").lower()
            if "audio/" in ctype and len(r.content) > 1000:
                return r.content
            data = r.json()
            payload = _find_audio_b64(data)
            if not payload:
                raise RuntimeError("response has no recognizable audio payload")
            raw = base64.b64decode(payload)
            if len(raw) < 1000:
                raise RuntimeError("audio payload too small")
            return raw
        except Exception as exc:
            errors.append(f"{endpoint}: {type(exc).__name__}: {exc}")
    raise RuntimeError("MoneyPrinter TTS unavailable: " + " | ".join(errors))


def tts(text: str, filename: str | Path, voice: str = MONEYPRINTER_VOICE) -> Path:
    """Robust Actions-friendly equivalent of MoneyPrinter Backend/tiktokvoice.py."""
    dest = Path(filename)
    dest.parent.mkdir(parents=True, exist_ok=True)
    chunks = split_text(text)
    if not chunks:
        raise RuntimeError("empty text passed to MoneyPrinter TTS")
    if len(chunks) == 1:
        dest.write_bytes(_synth_chunk(chunks[0], voice))
        return dest

    part_dir = dest.parent / (dest.stem + "_parts")
    part_dir.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    for idx, chunk in enumerate(chunks, 1):
        p = part_dir / f"part_{idx:02d}.mp3"
        p.write_bytes(_synth_chunk(chunk, voice))
        parts.append(p)

    concat = part_dir / "concat.txt"
    concat.write_text("\n".join(f"file '{p.resolve()}'" for p in parts) + "\n", encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(dest)],
        check=True,
    )
    if not dest.exists() or dest.stat().st_size < 3000:
        raise RuntimeError("MoneyPrinter TTS concat failed")
    return dest


def _groq(messages: list[dict], temperature: float = 0.5) -> str:
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    errors = []
    for model in GROQ_MODELS:
        for json_mode in (True, False):
            payload = {"model": model, "messages": messages, "temperature": temperature}
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            try:
                r = requests.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=120,
                )
                if not r.ok:
                    errors.append(f"{model} json_mode={json_mode}: HTTP {r.status_code}: {r.text[:500]}")
                    continue
                content = r.json()["choices"][0]["message"]["content"]
                if not content or not str(content).strip():
                    errors.append(f"{model} json_mode={json_mode}: empty content")
                    continue
                return str(content)
            except Exception as exc:
                errors.append(f"{model} json_mode={json_mode}: {type(exc).__name__}: {exc}")
    raise RuntimeError("Groq stage failed: " + " | ".join(errors[-6:]))


def _parse_json_text(text: str) -> dict:
    raw = str(text).strip()
    if raw.startswith("~~~") or raw.startswith("```"):
        raw = re.sub(r"^(?:~~~|```)(?:json)?\\s*", "", raw, flags=re.I)
        raw = re.sub(r"\\s*(?:~~~|```)\\s*$", "", raw)
    try:
        return json.loads(raw)
    except Exception:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start:end + 1])
        raise


def propose_fresh_topic(extra_blacklist: list[str] | None = None) -> dict:
    blocked = DEFAULT_BLACKLIST + list(extra_blacklist or [])
    prompt = (
        "Escolha UMA curiosidade real, visual e imediatamente compreensível sobre animal/natureza para um Short brasileiro. "
        "A curiosidade precisa causar reação do tipo 'como assim?' em uma frase, sem depender de taxonomia, contexto científico longo "
        "ou explicação enciclopédica. Prefira capacidades estranhas, comportamentos improváveis, mecanismos físicos visuais ou fatos "
        "que possam ser revelados aos poucos. O assunto precisa ter artigo específico na Wikipédia e imagens pesquisáveis. "
        "Evite temas cujo fato principal seja apenas tamanho, classificação, habitat ou nome científico. "
        "Evite estes temas: " + ", ".join(blocked) + ". "
        "Não invente fatos. O hook deve ter no máximo 12 palavras e NÃO entregar toda a explicação. "
        "Retorne JSON: {theme, hook, wikipedia_query, pexels_queries:[3 strings]}."
    )
    return _parse_json_text(_groq([
        {"role": "system", "content": "Você é a etapa de topic/search planning do MoneyPrinter adaptada ao Zé Curioso."},
        {"role": "user", "content": prompt},
    ], temperature=0.9))

def plan_explicit_theme(theme: str) -> dict:
    prompt = (
        "Normalize este tema para o pipeline brasileiro do Zé Curioso: " + theme + ". "
        "Identifique o assunto específico e retorne um termo de busca em PORTUGUÊS que encontre o artigo exato "
        "na Wikipédia em português; evite categorias genéricas. Também gere 3 termos Pexels, preferindo inglês "
        "ou nome científico para achar mídia. Não invente fatos. "
        "Retorne JSON: {theme, hook, wikipedia_query, pexels_queries:[3 strings]}."
    )
    return _parse_json_text(_groq([
        {"role": "system", "content": "Você é a etapa de topic/search planning do MoneyPrinter adaptada ao Zé Curioso."},
        {"role": "user", "content": prompt},
    ], temperature=0.2))


def script_from_grounded_source(topic: str, source_title: str, source_text: str) -> dict:
    source_text = re.sub(r"\s+", " ", source_text).strip()[:9000]
    prompt = f"""
Crie um roteiro CURTO do Zé Curioso usando SOMENTE fatos sustentados pelo texto-fonte abaixo.

Formato obrigatório: JSON com:
{{
  "topic": "...",
  "commons_query": "...",
  "titles": [["linha1","linha2"], ... exatamente 5],
  "blocks": [[frases...], ... exatamente 5],
  "search_terms": ["...", "...", "...", "...", "..."],
  "caption": "..."
}}

OBJETIVO:
A pessoa precisa pensar "pera, como assim?" nos primeiros segundos e querer ouvir a próxima frase.
O roteiro deve soar como alguém contando uma curiosidade absurda para um amigo — NÃO como documentário, aula ou Wikipédia.

REGRAS DE RETENÇÃO:
- escolha UMA única curiosidade central e construa tudo em volta dela.
- primeira frase: 5 a 11 palavras, forte, concreta e fácil de entender.
- NÃO comece com "Você sabia?", "Existe um animal", nome científico, classificação, habitat ou contexto.
- NÃO explique tudo no começo. Abra uma dúvida e responda aos poucos.
- use frases curtas; idealmente 4 a 10 palavras por frase.
- use palavras comuns. Termo técnico só se for indispensável, e explique imediatamente.
- uma ideia por frase.
- retire detalhes que não aumentem surpresa, entendimento ou curiosidade.
- não use listas de características.
- não repita a mesma ideia com palavras diferentes.
- não invente suspense falso e não exagere além da fonte.

ESTRUTURA:
- Cena 1 — GANCHO: mostre o fato mais estranho sem explicar tudo.
- Cena 2 — PROVA: diga o que realmente acontece, de forma concreta.
- Cena 3 — COMO: explique o mecanismo em linguagem simples.
- Cena 4 — VIRADA: entregue o detalhe mais surpreendente ou a consequência mais curiosa.
- Cena 5 — FECHO: uma frase curta que faz o fato "cair a ficha".
- O sistema acrescenta o bordão fixo depois; NÃO escreva o bordão.

TAMANHO:
- exatamente 5 cenas.
- corpo total entre 55 e 75 palavras antes do bordão.
- no máximo 2 frases por cena.
- nenhuma frase com mais de 14 palavras.

TÍTULOS:
- 2 linhas por cena.
- cada linha com no máximo 4 palavras.
- linguagem simples e forte; sem termos técnicos desnecessários.

Antes de devolver o JSON, corte qualquer frase que pareça enciclopédica, formal ou dispensável.

Tema pedido: {topic}
Fonte: {source_title}
TEXTO-FONTE:
{source_text}
"""
    return _parse_json_text(_groq([
        {
            "role": "system",
            "content": (
                "Você é o roteirista de retenção do MoneyPrinter adaptado ao Zé Curioso. "
                "Seu trabalho é transformar um fato verdadeiro em uma história oral simples, curta e viciante. "
                "Fatos vêm da fonte; o estilo vem de conversa informal brasileira."
            ),
        },
        {"role": "user", "content": prompt},
    ], temperature=0.45))

def metadata_from_script(video_subject: str, script: str) -> dict:
    """Hosted adaptation of MoneyPrinter Backend/gpt.py generate_metadata()."""
    prompt = f"""
Gere metadados para um vídeo vertical curto brasileiro sobre: {video_subject}
Baseie-se neste roteiro:
{script}

Retorne JSON estrito:
{{
  "title": "título curto, forte e natural em pt-BR",
  "description": "descrição curta e envolvente em pt-BR",
  "keywords": ["6 termos curtos"]
}}
Evite clickbait falso e não acrescente fatos que não estejam no roteiro.
"""
    try:
        data = _parse_json_text(_groq([
            {"role": "system", "content": "Você é a etapa generate_metadata do MoneyPrinter adaptada a Shorts/TikTok do Zé Curioso."},
            {"role": "user", "content": prompt},
        ], temperature=0.35))
        title = str(data.get("title") or "").strip()
        description = str(data.get("description") or "").strip()
        keywords = [str(x).strip() for x in list(data.get("keywords") or []) if str(x).strip()][:6]
        if not title or not description:
            raise ValueError("metadata incompleta")
        return {"title": title, "description": description, "keywords": keywords}
    except Exception as exc:
        print("MONEYPRINTER_METADATA_WARN", repr(exc), flush=True)
        return {"title": video_subject, "description": "", "keywords": []}


def pexels_search(query: str, api_key: str | None = None, per_page: int = 15, min_duration: int = 5) -> list[dict]:
    """Adapted from MoneyPrinter Backend/search.py, retaining best-resolution selection."""
    key = (api_key or os.getenv("PEXELS_API_KEY", "")).strip()
    if not key:
        return []
    r = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": key},
        params={"query": query, "per_page": per_page, "orientation": "portrait"},
        timeout=60,
    )
    r.raise_for_status()
    out = []
    for item in r.json().get("videos", []):
        if float(item.get("duration", 0)) < min_duration:
            continue
        files = [x for x in item.get("video_files", []) if x.get("link")]
        if not files:
            continue
        best = max(files, key=lambda x: int(x.get("width", 0)) * int(x.get("height", 0)))
        out.append({
            "id": item.get("id"),
            "duration": item.get("duration"),
            "url": best.get("link"),
            "width": best.get("width"),
            "height": best.get("height"),
            "page_url": item.get("url"),
            "query": query,
        })
    return out


def collect_stock_videos(search_terms: list[str], max_videos: int = 5) -> list[dict]:
    found: list[dict] = []
    seen: set[str] = set()
    for term in search_terms:
        try:
            rows = pexels_search(term)
        except Exception as exc:
            print("MONEYPRINTER_PEXELS_WARN", term, repr(exc), flush=True)
            continue
        for row in rows:
            url = str(row.get("url") or "")
            if url and url not in seen:
                found.append(row)
                seen.add(url)
                break
        if len(found) >= max_videos:
            break
    return found
