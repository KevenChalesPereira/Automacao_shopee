from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

import ze_postavel_woodfrog_v6_4_voicefixed_simplebubble as vf

sb = vf.sb
fs = vf.fs
v62 = vf.v62
v6 = vf.v6
v64 = sb.v64
cont = sb.cont
card = sb.card
base = cont.base
v4 = sb.v4

POST = sb.POST
ASSETS = sb.cont.ASSETS
SCENES = sb.SCENES
FONT_BOLD = sb.FONT_BOLD
W, H = sb.W, sb.H

SIGNOFF = sb.PREVIOUS_SIGNOFF

# Pendência aprovada para depois: acrescentar um detector/filtro específico de
# rouquidão/aspereza. Não bloqueia a primeira versão produtiva.
VOICE_TODO = "future: reject excessive hoarseness/roughness without changing approved identity"

AUTO_CATALOG = [
    {
        "id": "wood-frog",
        "aliases": ["sapo que congela", "sapo congelado", "wood frog", "sapo-da-floresta"],
        "topic": "O sapo que congela e volta à vida na primavera",
        "common_name": "sapo-da-floresta",
        "scientific_name": "Lithobates sylvaticus",
        "commons_query": "Lithobates sylvaticus wood frog",
        "titles": [
            ["ELE CONGELA.", "E SOBREVIVE."],
            ["O CORAÇÃO", "PODE PARAR."],
            ["O SEGREDO?", "GLICOSE."],
            ["DEPOIS ELE", "DESCONGELA."],
            ["PARECE FICÇÃO.", "MAS É REAL."],
        ],
        "blocks": [
            ["Esse sapo pode congelar durante o inverno.", "A respiração para e o coração deixa de bater."],
            ["Mesmo assim, ele consegue sobreviver por semanas em estado congelado."],
            ["Quando o frio chega, o corpo acumula muita glicose.", "Ela ajuda a proteger as células enquanto parte da água vira gelo."],
            ["Com a primavera, o sapo descongela e os órgãos voltam a funcionar."],
            ["É uma adaptação real do sapo-da-floresta.", SIGNOFF],
        ],
        "source_urls": [
            "https://www.nps.gov/gaar/learn/nature/wood-frog-page-2.htm",
            "https://www.nps.gov/dena/learn/nature/amphibians.htm",
        ],
    },
    {
        "id": "axolotl",
        "aliases": ["axolote", "axolotl", "ambystoma mexicanum"],
        "topic": "O axolote regenera partes do próprio corpo",
        "common_name": "axolote",
        "scientific_name": "Ambystoma mexicanum",
        "commons_query": "Ambystoma mexicanum axolotl",
        "titles": [
            ["ELE PERDE UM", "MEMBRO."],
            ["E CONSEGUE", "REGENERAR."],
            ["SEM VIRAR", "UMA CICATRIZ."],
            ["O CORPO", "RECONSTRÓI."],
            ["PARECE FICÇÃO.", "MAS É REAL."],
        ],
        "blocks": [
            ["O axolote consegue regenerar uma pata perdida."],
            ["E não é só pele: músculos, nervos, vasos e ossos podem voltar a se formar."],
            ["Ele também é estudado pela capacidade de reparar outros tecidos com pouca cicatrização."],
            ["Por isso, cientistas usam o axolote para entender como a regeneração funciona em vertebrados."],
            ["Esse animal existe de verdade e é nativo do México.", SIGNOFF],
        ],
        "source_urls": [
            "https://www.nigms.nih.gov/education/fact-sheets/Pages/axolotls.aspx",
            "https://nationalzoo.si.edu/animals/axolotl",
        ],
    },
    {
        "id": "tardigrade",
        "aliases": ["tardigrado", "tardígrado", "urso d'água", "water bear"],
        "topic": "O tardígrado pode sobreviver ao vácuo do espaço em estado dormente",
        "common_name": "tardígrado",
        "scientific_name": "Tardigrada",
        "commons_query": "Tardigrada water bear microscope",
        "titles": [
            ["QUASE SECO.", "QUASE PARADO."],
            ["ELE ENTRA", "EM CRIPTOBIOSE."],
            ["SUPORTA", "EXTREMOS."],
            ["ATÉ O VÁCUO", "DO ESPAÇO."],
            ["NÃO É INVENCÍVEL.", "MAS É REAL."],
        ],
        "blocks": [
            ["Tardígrados podem entrar num estado quase totalmente dormente quando falta água."],
            ["Nesse estado, o metabolismo cai drasticamente e o corpo fica encolhido."],
            ["Isso permite suportar condições extremas que matariam muitos outros animais."],
            ["Experimentos já mostraram tardígrados sobrevivendo até à exposição ao vácuo do espaço."],
            ["Isso não os torna indestrutíveis, mas a resistência é real.", SIGNOFF],
        ],
        "source_urls": [
            "https://www.esa.int/Science_Exploration/Human_and_Robotic_Exploration/Research/Tiny_animals_survive_exposure_to_space",
            "https://www.nasa.gov/mission/station/research-explorer/investigation/?#id=7670",
        ],
    },
    {
        "id": "bombardier-beetle",
        "aliases": ["besouro bombardeiro", "besouro-bombardeiro", "bombardier beetle"],
        "topic": "O besouro-bombardeiro dispara um jato químico muito quente",
        "common_name": "besouro-bombardeiro",
        "scientific_name": "Brachininae",
        "commons_query": "bombardier beetle Brachininae",
        "titles": [
            ["ELE MISTURA", "QUÍMICA."],
            ["A REAÇÃO", "ESQUENTA."],
            ["O JATO SAI", "EM PULSOS."],
            ["É DEFESA", "DE VERDADE."],
            ["PARECE ARMA.", "MAS É BIOLOGIA."],
        ],
        "blocks": [
            ["O besouro-bombardeiro guarda substâncias químicas separadas dentro do corpo."],
            ["Quando é ameaçado, ele mistura essas substâncias numa câmara de reação."],
            ["A reação libera calor e pressão muito rápido."],
            ["Então o inseto lança um jato quente e irritante em pulsos contra o atacante."],
            ["É um mecanismo natural de defesa, não ficção.", SIGNOFF],
        ],
        "source_urls": [
            "https://www.si.edu/newsdesk/releases/how-bombardier-beetles-survive-their-own-explosions",
            "https://news.mit.edu/2015/bombardier-beetle-defense-mechanism-0430",
        ],
    },
    {
        "id": "immortal-jellyfish",
        "aliases": ["água viva imortal", "agua viva imortal", "turritopsis dohrnii", "immortal jellyfish"],
        "topic": "A água-viva que consegue voltar a uma fase jovem",
        "common_name": "água-viva-imortal",
        "scientific_name": "Turritopsis dohrnii",
        "commons_query": "Turritopsis dohrnii immortal jellyfish",
        "titles": [
            ["ADULTA.", "DEPOIS JOVEM."],
            ["ELA REVERTE", "O CICLO."],
            ["VOLTA A", "SER PÓLIPO."],
            ["MAS AINDA", "PODE MORRER."],
            ["QUASE IMORTAL?", "NÃO EXATAMENTE."],
        ],
        "blocks": [
            ["Existe uma água-viva capaz de reverter o próprio ciclo de vida."],
            ["Em certas condições, a forma adulta pode voltar ao estágio de pólipo."],
            ["É como retornar a uma fase juvenil e começar o desenvolvimento outra vez."],
            ["Isso pode se repetir, mas o animal ainda pode morrer por doença ou ser devorado."],
            ["Por isso, 'imortal' é um apelido, não invencibilidade.", SIGNOFF],
        ],
        "source_urls": [
            "https://oceanservice.noaa.gov/facts/immortal-jellyfish.html",
            "https://www.amnh.org/explore/news-blogs/on-exhibit-posts/the-immortal-jellyfish",
        ],
    },
]

STOPWORDS = {
    "a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "um", "uma", "para", "por",
    "com", "que", "é", "são", "se", "no", "na", "nos", "nas", "ao", "aos", "como", "mais", "ou",
}
INTERESTING = {
    "sobrevive": 5, "sobreviver": 5, "regenera": 5, "regenerar": 5, "veneno": 4, "congela": 5,
    "congelar": 5, "coração": 4, "cerebro": 4, "cérebro": 4, "sangue": 3, "temperatura": 3,
    "extremo": 3, "extremas": 3, "sem": 2, "pode": 2, "capaz": 3, "consegue": 3, "anos": 2,
    "metros": 2, "quilômetros": 2, "vacuo": 5, "vácuo": 5, "espaço": 4, "luz": 2,
}


def _http_json(url: str, params: dict, timeout: int = 30) -> dict:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url + "?" + query,
        headers={"User-Agent": "ZeCuriosoStudio/1.0 (github.com/KevenChalesPereira/Automacao_shopee)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _download(url: str, path: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "ZeCuriosoStudio/1.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        path.write_bytes(response.read())
    if path.stat().st_size < 10_000:
        raise RuntimeError(f"Imagem pequena/inválida: {url}")
    Image.open(path).verify()


def _clean_text(text: str) -> str:
    text = re.sub(r"\([^)]{0,120}\)", "", text)
    text = re.sub(r"\[[^]]+\]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _sentences(text: str) -> list[str]:
    rows = re.split(r"(?<=[.!?])\s+", _clean_text(text))
    return [x.strip() for x in rows if 35 <= len(x.strip()) <= 260]


def _sentence_score(sentence: str) -> float:
    low = sentence.lower()
    score = 0.0
    for key, weight in INTERESTING.items():
        if key in low:
            score += weight
    if re.search(r"\d", sentence):
        score += 2.0
    words = sentence.split()
    if 8 <= len(words) <= 24:
        score += 2.0
    if len(words) > 34:
        score -= 2.0
    return score


def _short_clause(sentence: str, limit: int = 24) -> str:
    sentence = sentence.strip()
    words = sentence.split()
    if len(words) <= limit:
        return sentence
    clauses = re.split(r"(?<=[,;:])\s+|\s+(?:mas|porém|enquanto)\s+", sentence)
    for clause in clauses:
        if 8 <= len(clause.split()) <= limit:
            return clause.rstrip(",;:") + "."
    return " ".join(words[:limit]).rstrip(",;:") + "."


def wikipedia_topic(theme: str) -> dict:
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": theme,
        "gsrlimit": 5,
        "prop": "extracts|pageimages",
        "exintro": 1,
        "explaintext": 1,
        "piprop": "original",
        "format": "json",
        "formatversion": 2,
    }
    data = _http_json("https://pt.wikipedia.org/w/api.php", params)
    pages = data.get("query", {}).get("pages", [])
    pages = [p for p in pages if p.get("extract")]
    if not pages:
        raise RuntimeError(f"Não encontrei material enciclopédico para: {theme}")
    page = max(pages, key=lambda p: len(p.get("extract", "")))
    title = page["title"]
    return {
        "title": title,
        "extract": page.get("extract", ""),
        "page_url": "https://pt.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
        "original_image": (page.get("original") or {}).get("source"),
    }


def commons_images(query: str, fallback: str | None = None, limit: int = 5) -> list[dict]:
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,
        "gsrlimit": 30,
        "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata",
        "iiurlwidth": 1400,
        "format": "json",
        "formatversion": 2,
    }
    data = _http_json("https://commons.wikimedia.org/w/api.php", params)
    out: list[dict] = []
    if fallback:
        out.append({"url": fallback, "title": "Wikipedia main image", "license": "see source page", "artist": ""})
    seen = {fallback} if fallback else set()
    for page in data.get("query", {}).get("pages", []):
        info_rows = page.get("imageinfo") or []
        if not info_rows:
            continue
        info = info_rows[0]
        mime = str(info.get("mime", ""))
        if mime not in {"image/jpeg", "image/png"}:
            continue
        width, height = int(info.get("width", 0)), int(info.get("height", 0))
        if min(width, height) < 500:
            continue
        url = info.get("thumburl") or info.get("url")
        if not url or url in seen:
            continue
        meta = info.get("extmetadata") or {}
        license_name = str((meta.get("LicenseShortName") or {}).get("value", ""))
        artist = re.sub(r"<[^>]+>", "", str((meta.get("Artist") or {}).get("value", "")))
        out.append({"url": url, "title": page.get("title", ""), "license": license_name, "artist": artist})
        seen.add(url)
        if len(out) >= limit:
            break
    if len(out) < 2:
        raise RuntimeError(f"Poucas imagens úteis encontradas no Wikimedia Commons para: {query}")
    while len(out) < limit:
        out.append(out[len(out) % len(out)])
    return out[:limit]


def catalog_match(theme: str) -> dict | None:
    low = theme.lower().strip()
    for item in AUTO_CATALOG:
        aliases = [item["topic"], item["common_name"], item["scientific_name"], *item["aliases"]]
        if any(a.lower() in low or low in a.lower() for a in aliases if a):
            return json.loads(json.dumps(item, ensure_ascii=False))
    return None


def fallback_episode(theme: str) -> dict:
    wiki = wikipedia_topic(theme)
    rows = _sentences(wiki["extract"])
    if len(rows) < 4:
        raise RuntimeError("O artigo encontrado tem poucas frases úteis para montar um vídeo.")
    ranked = sorted(enumerate(rows), key=lambda x: (_sentence_score(x[1]), -x[0]), reverse=True)
    hook_idx = ranked[0][0]
    selected_ids = [hook_idx]
    for idx, sentence in ranked[1:]:
        if idx not in selected_ids:
            selected_ids.append(idx)
        if len(selected_ids) >= 6:
            break
    facts = [_short_clause(rows[i]) for i in selected_ids]
    subject = wiki["title"]
    # O fallback é propositalmente conservador: usa fatos do resumo enciclopédico
    # sem inventar mecanismo não presente na fonte.
    blocks = [
        [facts[0]],
        [facts[1]],
        [facts[2]],
        [facts[3]],
        [facts[4] if len(facts) > 4 else facts[-1], SIGNOFF],
    ]
    words = [w for w in re.findall(r"[A-Za-zÀ-ÿ0-9'-]+", " ".join(sum(blocks, []))) if w.lower() not in STOPWORDS]
    keys = []
    for word in words:
        if len(word) >= 6 and word.lower() not in [x.lower() for x in keys]:
            keys.append(word)
        if len(keys) >= 5:
            break
    while len(keys) < 5:
        keys.append(subject.split()[0])
    titles = [
        [subject.upper()[:22], "PARECE IMPOSSÍVEL."],
        [keys[1].upper()[:22], "MAS ACONTECE."],
        ["COMO ISSO", "FUNCIONA?"],
        [keys[3].upper()[:22], "É O DETALHE."],
        ["PARECE MENTIRA.", "MAS É REAL."],
    ]
    return {
        "id": "wiki-" + hashlib.sha1(theme.encode("utf-8")).hexdigest()[:10],
        "topic": subject,
        "common_name": subject,
        "scientific_name": "",
        "commons_query": subject,
        "titles": titles,
        "blocks": blocks,
        "source_urls": [wiki["page_url"]],
        "wiki_main_image": wiki.get("original_image"),
        "editorial_mode": "wikipedia-conservative-fallback",
    }


def choose_episode(request: dict) -> dict:
    mode = request.get("mode", "manual")
    if mode == "auto":
        seed = str(request.get("request_id") or os.environ.get("GITHUB_RUN_ID") or "0")
        idx = int(hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8], 16) % len(AUTO_CATALOG)
        episode = json.loads(json.dumps(AUTO_CATALOG[idx], ensure_ascii=False))
        episode["editorial_mode"] = "curated-auto-catalog"
        return episode
    theme = str(request.get("theme") or "").strip()
    if not theme:
        raise RuntimeError("Request manual sem tema")
    episode = catalog_match(theme)
    if episode:
        episode["editorial_mode"] = "curated-manual-match"
        return episode
    return fallback_episode(theme)


def enrich_episode(episode: dict) -> dict:
    fallback_image = episode.pop("wiki_main_image", None)
    images = commons_images(episode.get("commons_query") or episode["topic"], fallback=fallback_image, limit=5)
    episode["images"] = images
    episode["image_urls"] = [x["url"] for x in images]
    episode["final_signoff"] = SIGNOFF
    episode["voice_todo"] = VOICE_TODO
    episode["critical_words"] = critical_words(episode)
    return episode


def critical_words(episode: dict) -> list[str]:
    text = " ".join(" ".join(scene) for scene in episode["blocks"][:-1])
    candidates = []
    for word in re.findall(r"[A-Za-zÀ-ÿ0-9'-]+", text):
        low = v4.norm_word(word)
        if len(low) < 5 or low in STOPWORDS:
            continue
        if low not in candidates:
            candidates.append(low)
        if len(candidates) >= 8:
            break
    return candidates


def flatten_blocks(episode: dict) -> list[dict]:
    out = []
    for scene_no, scene_blocks in enumerate(episode["blocks"], 1):
        for block_no, text in enumerate(scene_blocks, 1):
            out.append({"scene": scene_no, "block": block_no, "text": text})
    return out


def apply_episode_text(episode: dict) -> None:
    rows = flatten_blocks(episode)
    if len(episode["blocks"]) != 5:
        raise RuntimeError("O renderer final exige exatamente 5 cenas")
    if rows[-1]["text"] != SIGNOFF:
        raise RuntimeError("O último bloco precisa ser o bordão travado")

    v62.FINAL_BLOCKS = rows
    v62.FINAL_TEXT = " ".join(x["text"] for x in rows)
    cont.BLOCKS = rows
    cont.FULL_NARRATION = v62.FINAL_TEXT
    v6.FULL_SPEAK_TEXT = v62.FINAL_TEXT

    fs.BODY_BLOCKS = rows[:-1]
    fs.SIGNOFF_BLOCK = rows[-1]
    fs.BODY_TEXT = " ".join(x["text"] for x in rows[:-1])
    fs.SIGNOFF_SPEAK = SIGNOFF
    fs.SIGNOFF_DISPLAY = SIGNOFF
    fs.BODY_CRITICAL = set(episode.get("critical_words") or [])


def download_episode_photos() -> None:
    urls = EPISODE["image_urls"]
    for idx in range(1, 6):
        url = urls[idx - 1]
        suffix = ".png" if ".png" in url.lower().split("?")[0] else ".jpg"
        raw = ASSETS / f"episode_raw_{idx:02d}{suffix}"
        _download(url, raw)
        im = Image.open(raw).convert("RGB")
        im.save(ASSETS / f"frog_{idx:02d}.jpg", quality=94)
        print("EPISODE_IMAGE_OK", idx, url, flush=True)


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def make_outer_background(photo: Image.Image, tint: tuple[int, int, int]) -> Image.Image:
    bg = ImageOps.fit(photo.convert("RGB"), (W, H), method=Image.Resampling.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(32))
    bg = ImageEnhance.Brightness(bg).enhance(0.37).convert("RGBA")
    bg = Image.alpha_composite(bg, Image.new("RGBA", (W, H), (*tint, 58)))
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle((0, 0, W, 250), fill=(0, 0, 0, 65))
    od.rectangle((0, 1500, W, H), fill=(0, 0, 0, 85))
    return Image.alpha_composite(bg, overlay)


def paste_photo_card(canvas: Image.Image, photo: Image.Image, label: str) -> None:
    x1, y1, x2, y2 = 82, 360, 998, 1165
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((x1 + 12, y1 + 20, x2 + 12, y2 + 20), radius=52, fill=(0, 0, 0, 125))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(16)))
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle((x1, y1, x2, y2), radius=52, fill=(244, 244, 238, 255), outline=(255, 255, 255, 220), width=6)
    inner = (x1 + 28, y1 + 28, x2 - 28, y2 - 28)
    iw, ih = inner[2] - inner[0], inner[3] - inner[1]
    inner_bg = ImageOps.fit(photo.convert("RGB"), (iw, ih), method=Image.Resampling.LANCZOS)
    inner_bg = inner_bg.filter(ImageFilter.GaussianBlur(22))
    inner_bg = ImageEnhance.Brightness(inner_bg).enhance(0.38).convert("RGBA")
    main = ImageOps.contain(photo.convert("RGB"), (iw - 36, ih - 36), method=Image.Resampling.LANCZOS).convert("RGBA")
    inner_bg.alpha_composite(main, ((iw - main.width) // 2, (ih - main.height) // 2))
    canvas.paste(inner_bg, (inner[0], inner[1]), rounded_mask((iw, ih), 34))

    label = label.upper()[:28]
    font = ImageFont.truetype(FONT_BOLD, 25)
    while font.getbbox(label)[2] > 320 and font.size > 18:
        font = ImageFont.truetype(FONT_BOLD, font.size - 1)
    box_w = min(410, max(220, font.getbbox(label)[2] + 54))
    d.rounded_rectangle((118, 1090, 118 + box_w, 1145), radius=22, fill=(0, 0, 0, 170))
    d.text((145, 1104), label, font=font, fill="white")


def draw_brand_and_title(canvas: Image.Image, title_lines: list[str], accent: str) -> None:
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle((44, 48, 316, 116), radius=25, fill=(0, 0, 0, 170), outline=(255, 255, 255, 45), width=2)
    d.text((72, 65), "ZÉ CURIOSO", font=ImageFont.truetype(FONT_BOLD, 32), fill="white")
    max_len = max(len(x) for x in title_lines)
    size = 72 if max_len < 18 else (61 if max_len < 24 else 52)
    font = ImageFont.truetype(FONT_BOLD, size)
    yy = 158
    for idx, line in enumerate(title_lines):
        box = d.textbbox((0, 0), line, font=font, stroke_width=5)
        x = max(24, (W - (box[2] - box[0])) // 2)
        d.text((x, yy), line, font=font, fill="white" if idx == 0 else accent, stroke_width=5, stroke_fill=(0, 0, 0, 220))
        yy += int(size * 1.04)


def paste_mascot(canvas: Image.Image, side: str) -> None:
    ze = Image.open(ASSETS / "ze_main.png").convert("RGBA")
    target_w = 290
    target_h = int(ze.height * target_w / ze.width)
    ze = ze.resize((target_w, target_h), Image.Resampling.LANCZOS)
    x = 34 if side == "left" else W - target_w - 34
    canvas.alpha_composite(ze, (x, 1175))


def build_dynamic_scenes() -> None:
    cfgs = card.SCENE_CONFIG
    label = EPISODE.get("common_name") or EPISODE["topic"]
    for idx, cfg in enumerate(cfgs, 1):
        photo = Image.open(ASSETS / f"frog_{idx:02d}.jpg").convert("RGB")
        canvas = make_outer_background(photo, cfg["tint"])
        draw_brand_and_title(canvas, cfg["title"], cfg["accent"])
        paste_photo_card(canvas, photo, label)
        paste_mascot(canvas, cfg["side"])
        canvas.convert("RGB").save(SCENES / f"scene_{idx:02d}.jpg", quality=95)
    shutil.copy2(SCENES / "scene_01.jpg", POST / "capa_sapo_congela_final.jpg")


def apply_episode_visuals(episode: dict) -> None:
    palettes = [
        ("#FFD84A", "left", (36, 110, 190)),
        ("#79FF9F", "right", (35, 135, 95)),
        ("#FFD84A", "left", (160, 100, 30)),
        ("#BCEEFF", "right", (40, 95, 155)),
        ("#79FF9F", "left", (120, 90, 45)),
    ]
    card.SCENE_CONFIG = [
        {"photo": f"frog_{i+1:02d}.jpg", "title": episode["titles"][i], "accent": palettes[i][0], "side": palettes[i][1], "tint": palettes[i][2]}
        for i in range(5)
    ]
    base.download_frog_photos = download_episode_photos
    card.build_scenes_card = build_dynamic_scenes


def rewrite_outputs(episode: dict) -> None:
    final_old = POST / "ze_curioso_sapo_congela_final.mp4"
    final_new = POST / "ze_curioso_final.mp4"
    shutil.copy2(final_old, final_new)
    shutil.copy2(SCENES / "scene_01.jpg", POST / "capa_final.jpg")

    (POST / "episode.json").write_text(json.dumps(episode, ensure_ascii=False, indent=2), encoding="utf-8")
    title = episode["titles"][0][0].title() + " " + episode["titles"][0][1].title()
    source_lines = "\n".join(f"- {u}" for u in episode.get("source_urls", []))
    credits = []
    for img in episode.get("images", []):
        bits = [img.get("title", "")]
        if img.get("artist"):
            bits.append(img["artist"])
        if img.get("license"):
            bits.append(img["license"])
        credits.append(" — ".join(x for x in bits if x))
    copy = (
        f"TÍTULO/CAPA:\n{title}\n\n"
        f"LEGENDA:\n{episode['topic']}. Uma curiosidade real da natureza explicada pelo Zé Curioso.\n\n"
        "#curiosidades #natureza #animais #ciencia #zecurioso #shorts #tiktokbr\n\n"
        f"Fontes factuais:\n{source_lines}\n\n"
        "Imagens: Wikimedia Commons/Wikipedia. Créditos do episódio:\n"
        + "\n".join(f"- {x}" for x in credits)
        + "\n\nVoz: VoxCPM2 — identidade aprovada do Zé Curioso.\n"
    )
    (POST / "copy_postagem.txt").write_text(copy, encoding="utf-8")

    qa_path = POST / "qa.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    qa.update({
        "studio_dynamic": True,
        "episode_id": episode["id"],
        "episode_topic": episode["topic"],
        "editorial_mode": episode.get("editorial_mode"),
        "sources": episode.get("source_urls", []),
        "image_count": len(episode.get("images", [])),
        "voice_hoarseness_todo": VOICE_TODO,
        "dynamic_renderer_status": "v1 data-driven",
    })
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")


def load_request() -> dict:
    raw = os.environ.get("ZE_REQUEST_JSON", "").strip()
    if not raw:
        path = Path(os.environ.get("ZE_REQUEST_FILE", "studio_request.json"))
        if path.exists():
            raw = path.read_text(encoding="utf-8")
    if not raw:
        raise RuntimeError("ZE_REQUEST_JSON ausente")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Request JSON inválido: {exc}") from exc


def main() -> None:
    global EPISODE
    request = load_request()
    EPISODE = enrich_episode(choose_episode(request))
    print("ZE_DYNAMIC_EPISODE", json.dumps({
        "id": EPISODE["id"],
        "topic": EPISODE["topic"],
        "editorial_mode": EPISODE.get("editorial_mode"),
        "sources": EPISODE.get("source_urls"),
    }, ensure_ascii=False), flush=True)

    apply_episode_text(EPISODE)
    apply_episode_visuals(EPISODE)
    vf.main()
    rewrite_outputs(EPISODE)
    print("ZE_STUDIO_DYNAMIC_OK", POST / "ze_curioso_final.mp4", flush=True)


EPISODE: dict = {}

if __name__ == "__main__":
    main()
