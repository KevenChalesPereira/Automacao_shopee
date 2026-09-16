from __future__ import annotations

import json
import math
import random
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

import ze_postavel_woodfrog_final as base


# Mantém a take 02 antiga; muda somente o conteúdo final da narração.
base.SCRIPT[-1] = (
    "Parece ficção, mas é sobrevivência real. "
    "A natureza consegue ser mais estranha que qualquer filme. "
    "Zé Curioso: parece mentira, mas é real."
)

POST = base.POST
ASSETS = base.ASSETS
AUDIO = base.AUDIO
SCENES = base.SCENES
VIDEO = base.VIDEO
W, H = base.W, base.H
FONT_BOLD = base.FONT_BOLD
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BUBBLE_FRAMES = POST / "bubble_frames"

# O texto em timing_text representa o trecho da narração durante o qual
# aquele balão deve permanecer visível. Assim a troca acompanha a fala.
BUBBLES = [
    [
        {"bubble": ["Congela?"], "timing_text": "Esse sapo congela no inverno"},
        {"bubble": ["Sem respirar?"], "timing_text": "para de respirar"},
        {"bubble": ["E sem", "batimento?!"], "timing_text": "e o coração simplesmente para de bater"},
    ],
    [
        {"bubble": ["Meses depois?"], "timing_text": "E o mais absurdo meses depois"},
        {"bubble": ["Descongela..."], "timing_text": "ele descongela"},
        {"bubble": ["E volta", "a andar?!"], "timing_text": "e sai andando como se nada tivesse acontecido é o sapo da floresta"},
    ],
    [
        {"bubble": ["O truque?", "GLICOSE."], "timing_text": "Quando a temperatura cai o fígado libera muita glicose"},
        {"bubble": ["Ela protege", "as células."], "timing_text": "Ela protege as células enquanto o gelo se forma ao redor delas"},
    ],
    [
        {"bubble": ["Coração", "primeiro."], "timing_text": "Na primavera ele descongela de dentro pra fora primeiro o coração volta"},
        {"bubble": ["Depois", "o cérebro."], "timing_text": "depois o cérebro"},
        {"bubble": ["Por fim,", "as pernas."], "timing_text": "e por fim as pernas"},
    ],
    [
        {"bubble": ["Parece", "ficção..."], "timing_text": "Parece ficção mas é sobrevivência real"},
        {"bubble": ["Mas é", "REAL."], "timing_text": "A natureza consegue ser mais estranha que qualquer filme"},
        {"bubble": ["Zé Curioso:", "parece mentira,", "mas é real."], "timing_text": "Zé Curioso parece mentira mas é real"},
    ],
]

CAPTIONS = [
    [
        "Esse sapo CONGELA\\Nno inverno…",
        "para de respirar —\\Ne o CORAÇÃO PARA.",
    ],
    [
        "Meses depois,\\Nele descongela…",
        "e sai andando como se\\Nnada tivesse acontecido.",
        "É o SAPO-DA-FLORESTA.",
    ],
    [
        "Quando esfria, o fígado\\Nlibera GLICOSE.",
        "Ela protege as células\\Nenquanto o gelo se forma\\Nao redor delas.",
    ],
    [
        "Na primavera, descongela\\NDE DENTRO PRA FORA.",
        "Primeiro coração.\\NDepois cérebro.\\NPor fim, pernas.",
    ],
    [
        "Parece ficção, mas é\\NSOBREVIVÊNCIA REAL.",
        "A natureza consegue ser\\Nmais estranha que qualquer filme.",
        "ZÉ CURIOSO:\\Nparece mentira, mas é real.",
    ],
]

SCENE_CONFIG = [
    {"photo": "frog_01.jpg", "title": ["ELE CONGELA.", "O CORAÇÃO PARA."], "accent": "#FFD84A", "side": "left", "tint": (36, 110, 190)},
    {"photo": "frog_02.jpg", "title": ["MESES DEPOIS…", "ELE VOLTA."], "accent": "#79FF9F", "side": "right", "tint": (35, 135, 95)},
    {"photo": "frog_01.jpg", "title": ["O SEGREDO?", "GLICOSE."], "accent": "#FFD84A", "side": "left", "tint": (160, 100, 30)},
    {"photo": "frog_02.jpg", "title": ["DESCONGELA", "DE DENTRO PRA FORA"], "accent": "#BCEEFF", "side": "right", "tint": (40, 95, 155)},
    {"photo": "frog_01.jpg", "title": ["PARECE FICÇÃO.", "MAS É REAL."], "accent": "#79FF9F", "side": "left", "tint": (120, 90, 45)},
]


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def make_outer_background(photo: Image.Image, tint: tuple[int, int, int]) -> Image.Image:
    bg = ImageOps.fit(photo.convert("RGB"), (W, H), method=Image.Resampling.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(32))
    bg = ImageEnhance.Brightness(bg).enhance(0.37).convert("RGBA")
    tint_layer = Image.new("RGBA", (W, H), (*tint, 58))
    bg = Image.alpha_composite(bg, tint_layer)
    # Vinheta simples para separar bem o card da moldura externa.
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle((0, 0, W, 250), fill=(0, 0, 0, 65))
    od.rectangle((0, 1500, W, H), fill=(0, 0, 0, 85))
    return Image.alpha_composite(bg, overlay)


def paste_photo_card(canvas: Image.Image, photo: Image.Image) -> None:
    # Card menor que a tela: a foto deixa de ser um fundo gigante e vira objeto analisável.
    x1, y1, x2, y2 = 82, 360, 998, 1165
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((x1 + 12, y1 + 20, x2 + 12, y2 + 20), radius=52, fill=(0, 0, 0, 125))
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    canvas.alpha_composite(shadow)

    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle((x1, y1, x2, y2), radius=52, fill=(244, 244, 238, 255), outline=(255, 255, 255, 220), width=6)

    inner = (x1 + 28, y1 + 28, x2 - 28, y2 - 28)
    iw, ih = inner[2] - inner[0], inner[3] - inner[1]

    # Fundo do interior acompanha a foto, mas a foto principal usa CONTAIN:
    # mostra mais detalhes e evita o recorte agressivo do full-screen antigo.
    inner_bg = ImageOps.fit(photo.convert("RGB"), (iw, ih), method=Image.Resampling.LANCZOS)
    inner_bg = inner_bg.filter(ImageFilter.GaussianBlur(22))
    inner_bg = ImageEnhance.Brightness(inner_bg).enhance(0.38).convert("RGBA")

    main = ImageOps.contain(photo.convert("RGB"), (iw - 36, ih - 36), method=Image.Resampling.LANCZOS).convert("RGBA")
    mx = (iw - main.width) // 2
    my = (ih - main.height) // 2
    inner_bg.alpha_composite(main, (mx, my))

    mask = rounded_mask((iw, ih), 34)
    canvas.paste(inner_bg, (inner[0], inner[1]), mask)

    # Pequena etiqueta para reforçar que o quadro central é a imagem/assunto.
    label_font = ImageFont.truetype(FONT_BOLD, 27)
    d.rounded_rectangle((118, 1090, 394, 1145), radius=22, fill=(0, 0, 0, 170))
    d.text((142, 1103), "SAPO-DA-FLORESTA", font=label_font, fill="white")


def draw_brand_and_title(canvas: Image.Image, title_lines: list[str], accent: str) -> None:
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle((44, 48, 316, 116), radius=25, fill=(0, 0, 0, 170), outline=(255, 255, 255, 45), width=2)
    d.text((72, 65), "ZÉ CURIOSO", font=ImageFont.truetype(FONT_BOLD, 32), fill="white")

    font_size = 72 if len(title_lines[1]) < 18 else 59
    font = ImageFont.truetype(FONT_BOLD, font_size)
    yy = 158
    for idx, line in enumerate(title_lines):
        box = d.textbbox((0, 0), line, font=font, stroke_width=5)
        x = (W - (box[2] - box[0])) // 2
        fill = "white" if idx == 0 else accent
        d.text((x, yy), line, font=font, fill=fill, stroke_width=5, stroke_fill=(0, 0, 0, 220))
        yy += int(font_size * 1.04)


def paste_mascot(canvas: Image.Image, side: str) -> None:
    ze = Image.open(ASSETS / "ze_main.png").convert("RGBA")
    target_w = 290
    target_h = int(ze.height * target_w / ze.width)
    ze = ze.resize((target_w, target_h), Image.Resampling.LANCZOS)
    x = 34 if side == "left" else W - target_w - 34
    y = 1175
    canvas.alpha_composite(ze, (x, y))


def build_scenes_card() -> None:
    BUBBLE_FRAMES.mkdir(parents=True, exist_ok=True)
    for idx, cfg in enumerate(SCENE_CONFIG, 1):
        photo = Image.open(ASSETS / cfg["photo"]).convert("RGB")
        canvas = make_outer_background(photo, cfg["tint"])
        draw_brand_and_title(canvas, cfg["title"], cfg["accent"])
        paste_photo_card(canvas, photo)
        paste_mascot(canvas, cfg["side"])
        canvas.convert("RGB").save(SCENES / f"scene_{idx:02d}.jpg", quality=95)
    shutil.copy2(SCENES / "scene_01.jpg", POST / "capa_sapo_congela_final.jpg")


def draw_bubble(base_img: Image.Image, lines: list[str], side: str, accent: str) -> Image.Image:
    im = base_img.copy().convert("RGBA")
    d = ImageDraw.Draw(im)

    if side == "left":
        box = (328, 1225, 1020, 1515)
        tail = [(335, 1365), (282, 1422), (350, 1400)]
    else:
        box = (60, 1225, 752, 1515)
        tail = [(745, 1365), (798, 1422), (730, 1400)]

    # Sombra do balão.
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((box[0] + 7, box[1] + 10, box[2] + 7, box[3] + 10), radius=44, fill=(0, 0, 0, 105))
    shadow = shadow.filter(ImageFilter.GaussianBlur(9))
    im.alpha_composite(shadow)
    d = ImageDraw.Draw(im)

    d.rounded_rectangle(box, radius=44, fill=(255, 255, 255, 244), outline=accent, width=7)
    d.polygon(tail, fill=(255, 255, 255, 244))

    # Uma micro-etiqueta dentro do balão ajuda a parecer fala do mascote, não legenda.
    tag_font = ImageFont.truetype(FONT_BOLD, 23)
    d.rounded_rectangle((box[0] + 24, box[1] + 20, box[0] + 128, box[1] + 57), radius=16, fill=(20, 20, 20, 230))
    d.text((box[0] + 42, box[1] + 27), "ZÉ", font=tag_font, fill="white")

    font_size = 50 if len(lines) <= 2 else 43
    font = ImageFont.truetype(FONT_BOLD, font_size)
    line_h = int(font_size * 1.17)
    total_h = len(lines) * line_h
    yy = box[1] + 77 + max(0, ((box[3] - box[1] - 90) - total_h) // 2)
    for line in lines:
        tb = d.textbbox((0, 0), line, font=font)
        x = box[0] + ((box[2] - box[0]) - (tb[2] - tb[0])) // 2
        d.text((x, yy), line, font=font, fill=(18, 18, 18, 255))
        yy += line_h
    return im


def bubble_segment_durations(scene_duration: float, entries: list[dict]) -> list[float]:
    weights = [max(1, len(x["timing_text"].split())) for x in entries]
    total = sum(weights)
    durations = [scene_duration * w / total for w in weights]
    # Corrige resíduo de ponto flutuante no último bloco para fechar exatamente a cena.
    durations[-1] += scene_duration - sum(durations)
    return durations


def ass_time(sec: float) -> str:
    h = int(sec // 3600)
    sec -= h * 3600
    m = int(sec // 60)
    sec -= m * 60
    return f"{h}:{m:02d}:{sec:05.2f}"


def write_safe_captions(durations: list[float]) -> Path:
    ass_path = POST / "captions_card_sync.ass"
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Cap,DejaVu Sans,43,&H00FFFFFF,&H00FFFFFF,&H00101010,&HA0000000,-1,0,0,0,100,100,0,0,3,3,0,2,92,92,185,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events: list[str] = []
    t = 0.0
    for dur, parts in zip(durations, CAPTIONS):
        weights = [max(1, len(p.replace("\\N", " ").split())) for p in parts]
        total = sum(weights)
        cur = t
        for part, weight in zip(parts, weights):
            end = cur + dur * weight / total
            safe = part.replace("{", "").replace("}", "")
            events.append(f"Dialogue: 0,{ass_time(cur)},{ass_time(end)},Cap,,0,0,0,,{safe}")
            cur = end
        t += dur
    ass_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return ass_path


def render_video_synced() -> None:
    audios, durations = base.audio_durations()
    BUBBLE_FRAMES.mkdir(parents=True, exist_ok=True)
    scene_list = VIDEO / "scene_list_card_sync.txt"
    scene_list.write_text("", encoding="utf-8")

    for scene_idx, (audio, scene_duration, entries, cfg) in enumerate(
        zip(audios, durations, BUBBLES, SCENE_CONFIG), 1
    ):
        base_img = Image.open(SCENES / f"scene_{scene_idx:02d}.jpg").convert("RGBA")
        seg_durations = bubble_segment_durations(scene_duration, entries)
        segment_list = VIDEO / f"bubble_segments_{scene_idx:02d}.txt"
        segment_list.write_text("", encoding="utf-8")

        for bubble_idx, (entry, seg_duration) in enumerate(zip(entries, seg_durations), 1):
            frame = draw_bubble(base_img, entry["bubble"], cfg["side"], cfg["accent"])
            frame_path = BUBBLE_FRAMES / f"scene_{scene_idx:02d}_bubble_{bubble_idx:02d}.jpg"
            frame.convert("RGB").save(frame_path, quality=95)

            seg_path = VIDEO / f"scene_{scene_idx:02d}_bubble_{bubble_idx:02d}.mp4"
            # Movimento muito discreto: o card continua analisável, mas não parece uma foto morta.
            if bubble_idx % 2:
                zoom = "min(zoom+0.00022,1.022)"
            else:
                zoom = "if(lte(zoom,1.0),1.022,max(1.0,zoom-0.00018))"
            vf = (
                f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                "d=1:s=1080x1920:fps=30,format=yuv420p"
            )
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loop", "1", "-i", str(frame_path),
                    "-t", f"{seg_duration:.6f}", "-vf", vf,
                    "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                    "-g", "30", "-pix_fmt", "yuv420p", str(seg_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with segment_list.open("a", encoding="utf-8") as f:
                f.write(f"file '{seg_path.resolve()}'\n")

        visual = VIDEO / f"scene_{scene_idx:02d}_visual.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(segment_list), "-c", "copy", str(visual)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        out = VIDEO / f"scene_{scene_idx:02d}.mp4"
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(visual), "-i", str(audio),
                "-map", "0:v:0", "-map", "1:a:0", "-t", f"{scene_duration:.6f}",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                "-shortest", str(out),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with scene_list.open("a", encoding="utf-8") as f:
            f.write(f"file '{out.resolve()}'\n")

    base_video = POST / "video_base_card_sync.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(scene_list), "-c", "copy", str(base_video)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    captions = write_safe_captions(durations)
    final = POST / "ze_curioso_sapo_congela_final.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(base_video), "-vf", f"ass={captions}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-movflags", "+faststart", str(final),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    timing_report = {
        f"scene_{idx:02d}": [
            {
                "bubble": " / ".join(entry["bubble"]),
                "seconds": round(seg, 3),
                "timing_text": entry["timing_text"],
            }
            for entry, seg in zip(entries, bubble_segment_durations(dur, entries))
        ]
        for idx, (dur, entries) in enumerate(zip(durations, BUBBLES), 1)
    }
    (POST / "bubble_timing.json").write_text(
        json.dumps(timing_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def qa_and_copy_card() -> None:
    # Reaproveita o QA técnico já validado e acrescenta as decisões desta versão.
    base.qa_and_copy()
    qa_path = POST / "qa.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    qa.update(
        {
            "layout_revision": "card-frame-v1",
            "speech_bubbles": "synced-by-narration-block",
            "catchphrase_spoken": "Zé Curioso: parece mentira, mas é real.",
            "full_screen_photo_removed": True,
            "photo_mode": "framed-card-contain",
        }
    )
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")

    copy_path = POST / "copy_postagem.txt"
    original = copy_path.read_text(encoding="utf-8")
    original += (
        "\nIdentidade do formato: card central + Zé Curioso + balões sincronizados.\n"
        "Bordão: Zé Curioso: parece mentira, mas é real.\n"
    )
    copy_path.write_text(original, encoding="utf-8")


# Monkeypatch controlado: todo o resto (download da take 02, assets e TTS) continua no renderer estável.
base.build_scenes = build_scenes_card
base.render_video = render_video_synced
base.qa_and_copy = qa_and_copy_card


if __name__ == "__main__":
    base.main()
