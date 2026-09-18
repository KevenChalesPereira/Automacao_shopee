from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import urllib.request

import requests
from pathlib import Path

import moneyprinter_bridge as mp
import ze_moneyprinter_voice as moneyvoice
import ze_studio_dynamic_prod as prod

dyn = prod.dyn
vf = dyn.vf

_original_enrich = dyn.enrich_episode
_original_rewrite = dyn.rewrite_outputs
_original_download_photos = dyn.download_episode_photos


def _moneyprinter_wikipedia_topic(query: str) -> dict:
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrlimit": 8,
        "prop": "extracts|pageimages",
        "exintro": 1,
        "explaintext": 1,
        "piprop": "original",
        "format": "json",
        "formatversion": 2,
    }
    data = dyn._http_json("https://pt.wikipedia.org/w/api.php", params)
    pages = [p for p in data.get("query", {}).get("pages", []) if p.get("extract")]
    if not pages:
        raise RuntimeError(f"Não encontrei artigo específico para: {query}")
    # MediaWiki search exposes an index/ranking. The previous helper chose the
    # longest extract, which could replace a specific animal with a broad taxon.
    page = min(pages, key=lambda p: int(p.get("index", 999999)))
    title = page["title"]
    return {
        "title": title,
        "extract": page.get("extract", ""),
        "page_url": "https://pt.wikipedia.org/wiki/" + dyn.urllib.parse.quote(title.replace(" ", "_")),
        "original_image": (page.get("original") or {}).get("source"),
    }


def _validate_script(data: dict) -> None:
    blocks = data.get("blocks")
    titles = data.get("titles")
    if not isinstance(blocks, list) or len(blocks) != 5:
        raise RuntimeError("MoneyPrinter/Groq script must have exactly 5 scene blocks")
    if not isinstance(titles, list) or len(titles) != 5:
        raise RuntimeError("MoneyPrinter/Groq script must have exactly 5 title pairs")
    for row in blocks:
        if not isinstance(row, list) or not row:
            raise RuntimeError("Every MoneyPrinter scene needs at least one sentence")


def moneyprinter_choose_episode(request: dict) -> dict:
    mode = str(request.get("mode") or "moneyprinter_auto")
    if mode not in {"moneyprinter_auto", "moneyprinter", "auto"}:
        return prod.choose_episode(request)

    explicit = str(request.get("theme") or "").strip()
    if explicit:
        plan = mp.plan_explicit_theme(explicit)
    else:
        plan = mp.propose_fresh_topic()

    theme = str(plan.get("theme") or plan.get("wikipedia_query") or "").strip()
    wiki_query = str(plan.get("wikipedia_query") or theme).strip()
    if not theme:
        raise RuntimeError("MoneyPrinter topic planner returned no theme")

    wiki = _moneyprinter_wikipedia_topic(wiki_query)
    script = mp.script_from_grounded_source(theme, wiki["title"], wiki["extract"])
    _validate_script(script)

    blocks = [[str(x).strip() for x in row if str(x).strip()] for row in script["blocks"]]
    # Zé-specific locked ending stays outside the generic MoneyPrinter script stage.
    blocks[-1].append(dyn.SIGNOFF)

    search_terms = []
    for value in list(script.get("search_terms") or []) + list(plan.get("pexels_queries") or []):
        value = str(value).strip()
        if value and value.lower() not in [x.lower() for x in search_terms]:
            search_terms.append(value)

    episode = {
        "id": "moneyprinter-" + hashlib.sha1((theme + wiki["title"]).encode("utf-8")).hexdigest()[:10],
        "topic": str(script.get("topic") or theme),
        "common_name": wiki["title"],
        "scientific_name": "",
        "commons_query": wiki["title"],
        "moneyprinter_requested_commons_query": str(script.get("commons_query") or wiki["title"]),
        "titles": [[str(x)[:28] for x in row[:2]] for row in script["titles"]],
        "blocks": blocks,
        "source_urls": [wiki["page_url"]],
        "wiki_main_image": wiki.get("original_image"),
        "editorial_mode": "moneyprinter-groq-grounded-wikipedia",
        "moneyprinter": {
            "upstream": "FujiwaraChoki/MoneyPrinter",
            "license": "MIT",
            "topic_plan": plan,
            "search_terms": search_terms,
            "script_stage": "MoneyPrinter generate_script/get_search_terms architecture via Groq on GitHub Actions",
            "tts_voice": "br_005",
            "voice_pass": "MoneyPrinter br_005 -> VoxCPM2",
        },
        "caption": str(script.get("caption") or ""),
    }
    return episode


def moneyprinter_enrich(episode: dict) -> dict:
    # Wikimedia is the no-key media baseline. Retry progressively broader,
    # source-grounded terms instead of failing on one overly specific query.
    attempts = []
    candidates = [
        str(episode.get("commons_query") or "").strip(),
        str(episode.get("common_name") or "").strip(),
        str(episode.get("topic") or "").strip(),
    ]
    last = None
    for query in candidates:
        if not query or query.lower() in [x.lower() for x in attempts]:
            continue
        attempts.append(query)
        trial = json.loads(json.dumps(episode, ensure_ascii=False))
        trial["commons_query"] = query
        try:
            episode = _original_enrich(trial)
            episode.setdefault("moneyprinter", {})["commons_query_used"] = query
            episode["moneyprinter"]["commons_query_attempts"] = attempts
            break
        except Exception as exc:
            last = exc
            print("MONEYPRINTER_COMMONS_RETRY", query, repr(exc), flush=True)
    else:
        raise RuntimeError(f"MoneyPrinter media search failed after {attempts}: {last}")

    terms = list((episode.get("moneyprinter") or {}).get("search_terms") or [])
    stock = mp.collect_stock_videos(terms, max_videos=5) if terms else []
    episode.setdefault("moneyprinter", {})["pexels_stock_videos"] = stock
    episode["moneyprinter"]["pexels_enabled"] = bool(os.getenv("PEXELS_API_KEY", "").strip())
    episode["moneyprinter"]["pexels_results"] = len(stock)
    return episode


def _download_stock_frame(url: str, target: Path, index: int) -> bool:
    try:
        clip = target.parent / f"moneyprinter_stock_{index:02d}.mp4"
        req = urllib.request.Request(url, headers={"User-Agent": "ZeCurioso-MoneyPrinter/1.0"})
        with urllib.request.urlopen(req, timeout=90) as response:
            clip.write_bytes(response.read())
        if clip.stat().st_size < 100_000:
            return False
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-ss", "1.0", "-i", str(clip),
            "-frames:v", "1", "-vf", "scale=1200:-2", str(target)
        ], check=True)
        return target.exists() and target.stat().st_size > 10_000
    except Exception as exc:
        print("MONEYPRINTER_STOCK_FRAME_WARN", index, repr(exc), flush=True)
        return False


def moneyprinter_download_episode_photos() -> None:
    # Accurate Commons/Wikipedia images remain the factual baseline, but use a
    # rate-limit-safe downloader. Repeated URLs are copied locally instead of
    # hitting Wikimedia again.
    cache: dict[str, Path] = {}
    urls = list(dyn.EPISODE["image_urls"])
    for idx in range(1, 6):
        url = urls[idx - 1]
        target = dyn.ASSETS / f"frog_{idx:02d}.jpg"
        if url in cache and cache[url].exists():
            shutil.copy2(cache[url], target)
            print("EPISODE_IMAGE_CACHE_OK", idx, url, flush=True)
            continue

        suffix = ".png" if ".png" in url.lower().split("?")[0] else ".jpg"
        raw = dyn.ASSETS / f"episode_raw_{idx:02d}{suffix}"
        last = None
        for attempt in range(1, 6):
            try:
                response = requests.get(
                    url,
                    headers={
                        "User-Agent": "ZeCuriosoStudio/1.0 (GitHub Actions; KevenChalesPereira/Automacao_shopee)",
                        "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.8",
                    },
                    timeout=60,
                )
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else min(2.0 * attempt, 8.0)
                    print("WIKIMEDIA_429_RETRY", idx, attempt, delay, flush=True)
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                raw.write_bytes(response.content)
                if raw.stat().st_size < 10_000:
                    raise RuntimeError("imagem pequena")
                dyn.Image.open(raw).verify()
                im = dyn.Image.open(raw).convert("RGB")
                im.save(target, quality=94)
                cache[url] = target
                print("EPISODE_IMAGE_OK", idx, url, flush=True)
                time.sleep(0.65)
                break
            except Exception as exc:
                last = exc
                if attempt < 5:
                    time.sleep(min(1.5 * attempt, 6.0))
        else:
            # A scene should not kill the whole episode when a CDN throttles.
            # Reuse the immediately previous accurate subject image.
            if idx > 1 and (dyn.ASSETS / f"frog_{idx-1:02d}.jpg").exists():
                shutil.copy2(dyn.ASSETS / f"frog_{idx-1:02d}.jpg", target)
                print("EPISODE_IMAGE_RATE_LIMIT_FALLBACK", idx, repr(last), flush=True)
            else:
                raise RuntimeError(f"Falha ao baixar imagem {idx}: {last}")

    stock = list((dyn.EPISODE.get("moneyprinter") or {}).get("pexels_stock_videos") or [])
    # MoneyPrinter media becomes visibly part of the video where available.
    # Use alternating scenes so the exact-subject Wikimedia image still anchors it.
    for slot, scene in enumerate((2, 4), 0):
        if slot >= len(stock):
            break
        target = dyn.ASSETS / f"frog_{scene:02d}.jpg"
        if _download_stock_frame(str(stock[slot].get("url") or ""), target, scene):
            print("MONEYPRINTER_PEXELS_FRAME_OK", scene, stock[slot].get("query"), flush=True)


def moneyprinter_rewrite_outputs(episode: dict) -> None:
    _original_rewrite(episode)
    post = dyn.POST

    copy_path = post / "copy_postagem.txt"
    if copy_path.exists():
        text = copy_path.read_text(encoding="utf-8")
        text = text.replace(
            "Voz: VoxCPM2 — identidade aprovada do Zé Curioso.",
            "Voz: MoneyPrinter br_005 → VoxCPM2 — híbrido aprovado do Zé Curioso."
        )
        copy_path.write_text(text, encoding="utf-8")

    qa_path = post / "qa.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    qa.update({
        "moneyprinter_primary_pipeline": True,
        "moneyprinter_upstream": "FujiwaraChoki/MoneyPrinter",
        "moneyprinter_components": [
            "topic planning",
            "script stage",
            "search-term generation",
            "Pexels stock-video search when configured",
            "TikTok TTS br_005",
            "voice reference/fallback",
        ],
        "ze_specific_components_retained": [
            "mascot",
            "5-scene branded card",
            "3-word speech bubble",
            "active-word highlight",
            "bubble pop",
            "Faster-Whisper timing QA",
            "single-pass final renderer",
        ],
        "moneyprinter_pexels_results": len((episode.get("moneyprinter") or {}).get("pexels_stock_videos") or []),
    })
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")

    (post / "moneyprinter_pipeline.json").write_text(
        json.dumps(episode.get("moneyprinter") or {}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


dyn.choose_episode = moneyprinter_choose_episode
dyn.enrich_episode = moneyprinter_enrich
dyn.download_episode_photos = moneyprinter_download_episode_photos
dyn.rewrite_outputs = moneyprinter_rewrite_outputs
moneyvoice.install(vf)

if __name__ == "__main__":
    dyn.main()
