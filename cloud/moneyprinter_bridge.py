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
import unicodedata
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
  "scene_visuals": [
    {"query":"busca Pexels específica da cena 1 em inglês","fallback_query":"busca mais simples","must_terms":["termo visual essencial"]},
    {"query":"...","fallback_query":"...","must_terms":["..."]},
    {"query":"...","fallback_query":"...","must_terms":["..."]},
    {"query":"...","fallback_query":"...","must_terms":["..."]},
    {"query":"...","fallback_query":"...","must_terms":["..."]}
  ],
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
- REGRA OBRIGATÓRIA PARA VOZ: dentro de "blocks", NUNCA use algarismos ou abreviações de unidade.
- escreva TODO número e unidade por extenso em português do Brasil.
- exemplos: "218 dB" vira "duzentos e dezoito decibéis"; "4700°C" vira "quatro mil e setecentos graus Celsius"; "100 J" vira "cem joules".
- algarismos podem aparecer somente em search_terms/metadata, nunca no texto falado.

VISUAL POR CENA:
- scene_visuals deve ter exatamente 5 itens, na mesma ordem das cenas.
- cada query deve descrever EXATAMENTE o que aquela cena precisa mostrar, não apenas o assunto geral.
- prefira inglês, nomes conhecidos e objetos/ações concretos que existam em bancos de mídia.
- fallback_query deve ser uma versão mais simples, mas ainda fiel à cena.
- must_terms deve ter 1 a 3 palavras/conceitos que precisam aparecer na descrição/URL da mídia para ela ser aceita.
- não use termos abstratos como "curiosity", "amazing", "science" ou "technology" sozinhos.
- exemplo: fala sobre sinal Wi-Fi atravessando parede -> query "wifi router signal through wall home", fallback "wifi router wall", must_terms ["wifi","router"].

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
    system = {
        "role": "system",
        "content": (
            "Você é o roteirista de retenção do MoneyPrinter adaptado ao Zé Curioso. "
            "Seu trabalho é transformar um fato verdadeiro em uma história oral simples, curta e viciante. "
            "Fatos vêm da fonte; o estilo vem de conversa informal brasileira. "
            "O texto falado deve ser totalmente pronunciável em pt-BR: sem algarismos e sem abreviações de unidade."
        ),
    }
    last = None
    for attempt in range(1, 4):
        extra = "" if attempt == 1 else (
            "\nCORREÇÃO OBRIGATÓRIA: a resposta anterior tinha algarismos no texto falado. "
            "Reescreva TODOS os blocks com números e unidades por extenso em português. "
            "Não altere os fatos."
        )
        data = _parse_json_text(_groq([
            system,
            {"role": "user", "content": prompt + extra},
        ], temperature=0.45 if attempt == 1 else 0.2))
        spoken = " ".join(
            str(x)
            for row in list(data.get("blocks") or [])
            for x in (row if isinstance(row, list) else [])
        )
        visuals = list(data.get("scene_visuals") or [])
        visuals_ok = (
            len(visuals) == 5
            and all(
                isinstance(x, dict)
                and str(x.get("query") or "").strip()
                and str(x.get("fallback_query") or "").strip()
                and list(x.get("must_terms") or [])
                for x in visuals
            )
        )
        numbers_ok = not re.search(r"\d", spoken)
        if numbers_ok and visuals_ok:
            data["spoken_numbers_normalized_ptbr"] = True
            data["scene_visuals_validated"] = True
            return data
        last = {"spoken": spoken, "numbers_ok": numbers_ok, "visuals_ok": visuals_ok}
        print("MONEYPRINTER_SCRIPT_RETRY", attempt, json.dumps(last, ensure_ascii=False), flush=True)
        prompt += (
            "\nCORREÇÃO OBRIGATÓRIA: devolva exatamente 5 scene_visuals completos, um por cena, "
            "cada um com query, fallback_query e must_terms; e mantenha o texto falado sem algarismos."
        )
    raise RuntimeError(f"Roteiro inválido após 3 tentativas: {last}")

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


def _norm_media_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-zA-Z0-9]+", " ", value.lower())
    return re.sub(r"\\s+", " ", value).strip()


def _media_relevance(text: str, query: str, must_terms: list[str] | None = None) -> tuple[float, dict]:
    hay = _norm_media_text(text)
    q_tokens = [
        t for t in _norm_media_text(query).split()
        if len(t) >= 3 and t not in {"the", "and", "with", "from", "this", "that", "para", "com", "uma", "por"}
    ]
    must = [_norm_media_text(x) for x in list(must_terms or []) if _norm_media_text(x)]
    query_hits = sum(1 for token in set(q_tokens) if token in hay)
    must_hits = sum(1 for term in must if all(part in hay for part in term.split()))
    score = min(query_hits, 4) * 0.8 + must_hits * 2.5
    if must and must_hits == 0:
        score -= 3.0
    return score, {
        "query_hits": query_hits,
        "must_hits": must_hits,
        "must_total": len(must),
    }


def pexels_search(
    query: str,
    api_key: str | None = None,
    per_page: int = 30,
    min_duration: int = 4,
    must_terms: list[str] | None = None,
) -> list[dict]:
    """Pexels video search using the current v1 endpoint and scene relevance ranking."""
    key = (api_key or os.getenv("PEXELS_API_KEY", "")).strip()
    if not key:
        return []
    r = requests.get(
        "https://api.pexels.com/v1/videos/search",
        headers={"Authorization": key},
        params={
            "query": query,
            "per_page": max(1, min(int(per_page), 80)),
            "orientation": "portrait",
            "size": "large",
            "locale": "pt-BR",
        },
        timeout=60,
    )
    r.raise_for_status()
    out = []
    for rank, item in enumerate(r.json().get("videos", []), 1):
        duration = float(item.get("duration", 0) or 0)
        if duration < min_duration:
            continue
        files = [
            x for x in item.get("video_files", [])
            if x.get("link") and str(x.get("file_type") or "video/mp4").startswith("video/")
        ]
        if not files:
            continue

        def file_score(x):
            w = int(x.get("width", 0) or 0)
            h = int(x.get("height", 0) or 0)
            portrait = 1 if h > w else 0
            full_hd = 1 if h >= 1280 and w >= 720 else 0
            return (portrait, full_hd, min(w, 1080) * min(h, 1920))

        best = max(files, key=file_score)
        w = int(best.get("width", 0) or 0)
        h = int(best.get("height", 0) or 0)
        page_url = str(item.get("url") or "")
        rel, detail = _media_relevance(page_url, query, must_terms)
        quality = (1.2 if h > w else -1.0) + (1.0 if h >= 1280 and w >= 720 else 0.0)
        duration_bonus = 0.4 if 4 <= duration <= 30 else 0.0
        rank_bonus = max(0.0, 0.8 - (rank - 1) * 0.05)
        score = rel + quality + duration_bonus + rank_bonus
        out.append({
            "media_type": "video",
            "id": item.get("id"),
            "duration": duration,
            "url": best.get("link"),
            "width": w,
            "height": h,
            "page_url": page_url,
            "query": query,
            "score": round(score, 4),
            "relevance": detail,
            "creator": (item.get("user") or {}).get("name"),
            "creator_url": (item.get("user") or {}).get("url"),
        })
    return sorted(out, key=lambda x: float(x.get("score", 0.0)), reverse=True)


def pexels_photo_search(
    query: str,
    api_key: str | None = None,
    per_page: int = 30,
    must_terms: list[str] | None = None,
) -> list[dict]:
    """Pexels photo fallback. Photo alt text gives us a stronger relevance check."""
    key = (api_key or os.getenv("PEXELS_API_KEY", "")).strip()
    if not key:
        return []
    r = requests.get(
        "https://api.pexels.com/v1/search",
        headers={"Authorization": key},
        params={
            "query": query,
            "per_page": max(1, min(int(per_page), 80)),
            "orientation": "portrait",
            "size": "large",
            "locale": "pt-BR",
        },
        timeout=60,
    )
    r.raise_for_status()
    out = []
    for rank, item in enumerate(r.json().get("photos", []), 1):
        alt = str(item.get("alt") or "")
        page_url = str(item.get("url") or "")
        rel, detail = _media_relevance(alt + " " + page_url, query, must_terms)
        width = int(item.get("width", 0) or 0)
        height = int(item.get("height", 0) or 0)
        quality = (1.0 if height > width else -0.5) + (0.8 if height >= 1200 else 0.0)
        rank_bonus = max(0.0, 0.7 - (rank - 1) * 0.04)
        score = rel + quality + rank_bonus
        src = item.get("src") or {}
        url = src.get("portrait") or src.get("large2x") or src.get("large") or src.get("original")
        if not url:
            continue
        out.append({
            "media_type": "photo",
            "id": item.get("id"),
            "url": url,
            "width": width,
            "height": height,
            "page_url": page_url,
            "query": query,
            "score": round(score, 4),
            "relevance": detail,
            "alt": alt,
            "creator": item.get("photographer"),
            "creator_url": item.get("photographer_url"),
        })
    return sorted(out, key=lambda x: float(x.get("score", 0.0)), reverse=True)


def collect_scene_media(scene_visuals: list[dict], min_score: float = 2.4) -> list[dict]:
    """Choose one relevant Pexels asset per scene; never fill a scene with weak generic media."""
    if not os.getenv("PEXELS_API_KEY", "").strip():
        return []
    selected: list[dict] = []
    for scene_idx, plan in enumerate(scene_visuals[:5], 1):
        query = str(plan.get("query") or "").strip()
        fallback = str(plan.get("fallback_query") or "").strip()
        must_terms = [str(x).strip() for x in list(plan.get("must_terms") or []) if str(x).strip()]
        queries = []
        for value in (query, fallback):
            if value and value.lower() not in [x.lower() for x in queries]:
                queries.append(value)

        winner = None
        attempts = []
        for q in queries:
            try:
                videos = pexels_search(q, must_terms=must_terms)
                photos = pexels_photo_search(q, must_terms=must_terms)
            except Exception as exc:
                attempts.append({"query": q, "error": repr(exc)})
                continue

            pool = videos[:8] + photos[:8]
            if pool:
                candidate = max(pool, key=lambda x: float(x.get("score", 0.0)))
                attempts.append({
                    "query": q,
                    "best_type": candidate.get("media_type"),
                    "best_score": candidate.get("score"),
                    "best_url": candidate.get("page_url"),
                })
                if float(candidate.get("score", 0.0)) >= min_score:
                    winner = candidate
                    break

        if winner:
            winner = dict(winner)
            winner.update({
                "scene": scene_idx,
                "planned_query": query,
                "fallback_query": fallback,
                "must_terms": must_terms,
                "selection_attempts": attempts,
                "accepted": True,
            })
            selected.append(winner)
        else:
            selected.append({
                "scene": scene_idx,
                "planned_query": query,
                "fallback_query": fallback,
                "must_terms": must_terms,
                "selection_attempts": attempts,
                "accepted": False,
                "reason": "no Pexels asset passed scene relevance threshold",
            })
    return selected


def collect_stock_videos(search_terms: list[str], max_videos: int = 5) -> list[dict]:
    """Compatibility helper for older callers."""
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

