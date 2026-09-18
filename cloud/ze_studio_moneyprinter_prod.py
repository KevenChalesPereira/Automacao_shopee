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

    # MoneyPrinter needs more than the lead paragraph to find the strongest
    # curiosity. Fetch the article text after selecting the relevant page.
    full = dyn._http_json("https://pt.wikipedia.org/w/api.php", {
        "action": "query",
        "titles": title,
        "prop": "extracts",
        "explaintext": 1,
        "redirects": 1,
        "format": "json",
        "formatversion": 2,
    })
    full_pages = full.get("query", {}).get("pages", [])
    full_extract = next((str(x.get("extract") or "") for x in full_pages if x.get("extract")), "")
    return {
        "title": title,
        "extract": full_extract or page.get("extract", ""),
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
    history_path = Path("data/ze_moneyprinter_history.json")
    history_rows = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
            history_rows = list(history.get("topics", []))
        except Exception as exc:
            print("MONEYPRINTER_HISTORY_WARN", repr(exc), flush=True)

    blocked_topics = [
        str(row.get("topic") or "").strip()
        for row in history_rows
        if str(row.get("topic") or "").strip()
    ]
    blocked_sources = {
        str(row.get("source") or "").split("#", 1)[0].rstrip("/").lower()
        for row in history_rows
        if str(row.get("source") or "").strip().startswith("http")
    }

    if explicit:
        plan = mp.plan_explicit_theme(explicit)
        theme = str(plan.get("theme") or plan.get("wikipedia_query") or "").strip()
        wiki_query = str(plan.get("wikipedia_query") or theme).strip()
        if not theme:
            raise RuntimeError("MoneyPrinter topic planner returned no theme")
        wiki = _moneyprinter_wikipedia_topic(wiki_query)
    else:
        wiki = None
        plan = None
        theme = ""
        # A textual blacklist catches aliases; the source-URL check catches the
        # same subject proposed under a different wording.
        for planner_attempt in range(1, 6):
            plan = mp.propose_fresh_topic(extra_blacklist=blocked_topics)
            theme = str(plan.get("theme") or plan.get("wikipedia_query") or "").strip()
            wiki_query = str(plan.get("wikipedia_query") or theme).strip()
            if not theme:
                continue
            candidate = _moneyprinter_wikipedia_topic(wiki_query)
            source_key = str(candidate["page_url"]).split("#", 1)[0].rstrip("/").lower()
            if source_key in blocked_sources:
                print("MONEYPRINTER_DUPLICATE_REJECT", planner_attempt, theme, candidate["page_url"], flush=True)
                blocked_topics.append(theme)
                continue
            wiki = candidate
            plan["history_blacklist_count"] = len(history_rows)
            plan["freshness_check"] = "topic blacklist + source URL unique"
            break
        if wiki is None or plan is None:
            raise RuntimeError("MoneyPrinter não encontrou tema inédito após 5 tentativas")
    script = mp.script_from_grounded_source(theme, wiki["title"], wiki["extract"])
    _validate_script(script)

    blocks = [[str(x).strip() for x in row if str(x).strip()] for row in script["blocks"]]
    # Zé-specific locked ending stays outside the generic MoneyPrinter script stage.
    blocks[-1].append(dyn.SIGNOFF)

    spoken_script = " ".join(" ".join(row) for row in blocks)
    metadata = mp.metadata_from_script(str(script.get("topic") or theme), spoken_script)

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
            "metadata": metadata,
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
        clean_url = url.split("?", 1)[0]
        proxy_source = clean_url.replace("https://", "").replace("http://", "")
        proxy_url = "https://wsrv.nl/?url=" + urllib.parse.quote(proxy_source, safe="/") + "&w=1400&output=jpg"
        sources = [url, proxy_url]
        downloaded = False
        for source_no, source_url in enumerate(sources, 1):
            for attempt in range(1, 4):
                try:
                    response = requests.get(
                        source_url,
                        headers={
                            "User-Agent": "ZeCuriosoStudio/1.0 (GitHub Actions; KevenChalesPereira/Automacao_shopee)",
                            "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.8",
                        },
                        timeout=60,
                    )
                    if response.status_code == 429:
                        last = RuntimeError(f"HTTP 429 from source {source_no}")
                        print("IMAGE_429_SWITCH_OR_RETRY", idx, source_no, attempt, flush=True)
                        # Switch quickly to the CDN proxy instead of spending ~50 s
                        # retrying a Wikimedia edge that already blocked this runner.
                        if source_no == 1:
                            break
                        time.sleep(min(1.5 * attempt, 4.0))
                        continue
                    response.raise_for_status()
                    raw.write_bytes(response.content)
                    if raw.stat().st_size < 10_000:
                        raise RuntimeError("imagem pequena")
                    dyn.Image.open(raw).verify()
                    im = dyn.Image.open(raw).convert("RGB")
                    im.save(target, quality=94)
                    cache[url] = target
                    print("EPISODE_IMAGE_OK", idx, "direct" if source_no == 1 else "cdn-proxy", url, flush=True)
                    time.sleep(0.4)
                    downloaded = True
                    break
                except Exception as exc:
                    last = exc
                    if attempt < 3:
                        time.sleep(min(1.2 * attempt, 3.0))
            if downloaded:
                break
        if not downloaded:
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
    metadata = (episode.get("moneyprinter") or {}).get("metadata") or {}
    if copy_path.exists():
        title = str(metadata.get("title") or episode["topic"]).strip()
        description = str(metadata.get("description") or episode.get("caption") or episode["topic"]).strip()
        keywords = [str(x).strip() for x in metadata.get("keywords", []) if str(x).strip()]
        source_lines = "\n".join(f"- {u}" for u in episode.get("source_urls", []))
        credits = []
        for img in episode.get("images", []):
            bits = [img.get("title", "")]
            if img.get("artist"):
                bits.append(img["artist"])
            if img.get("license"):
                bits.append(img["license"])
            credits.append(" — ".join(x for x in bits if x))
        tags = ["#zecurioso", "#curiosidades", "#natureza", "#ciencia", "#shorts"]
        for keyword in keywords:
            tag = "#" + "".join(ch for ch in keyword.lower().replace(" ", "") if ch.isalnum() or ch == "_")
            if len(tag) > 1 and tag not in tags:
                tags.append(tag)
        copy = (
            f"TÍTULO/CAPA:\n{title}\n\n"
            f"LEGENDA:\n{description}\n\n"
            + " ".join(tags[:10])
            + f"\n\nPalavras-chave MoneyPrinter: {', '.join(keywords)}\n\n"
            + f"Fontes factuais:\n{source_lines}\n\n"
            + "Imagens: Wikimedia Commons/Wikipedia"
            + (" + Pexels (MoneyPrinter)." if (episode.get("moneyprinter") or {}).get("pexels_results") else ".")
            + "\nCréditos:\n"
            + "\n".join(f"- {x}" for x in credits)
            + "\n\nVoz: MoneyPrinter br_005 → VoxCPM2 — híbrido aprovado do Zé Curioso.\n"
        )
        copy_path.write_text(copy, encoding="utf-8")

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
