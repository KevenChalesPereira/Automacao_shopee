from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

import ze_postavel_woodfrog_final as base

POST = base.POST
ASSETS = base.ASSETS
AUDIO = base.AUDIO
SCENES = base.SCENES
VIDEO = base.VIDEO
W, H = base.W, base.H
FONT_BOLD = base.FONT_BOLD
BUBBLE_FRAMES = POST / "bubble_frames"

# Cada bloco abaixo gera UM áudio próprio. O balão fica na tela exatamente
# durante a duração real desse áudio — sem estimativa por quantidade de palavras.
SCENE_BLOCKS = [
    [
        {"text": "Esse sapo congela no inverno.", "bubble": ["Congela?!"], "caption": "Esse sapo CONGELA\\Nno inverno."},
        {"text": "Para de respirar.", "bubble": ["Sem respirar?!"], "caption": "PARA DE RESPIRAR."},
        {"text": "E o coração simplesmente para de bater.", "bubble": ["E sem", "batimento?!"], "caption": "E o CORAÇÃO\\Npara de bater."},
    ],
    [
        {"text": "E o mais absurdo: meses depois...", "bubble": ["Meses depois?!"], "caption": "E o mais absurdo:\\NMESES DEPOIS..."},
        {"text": "Ele descongela.", "bubble": ["Descongela..."], "caption": "ELE DESCONGELA."},
        {"text": "E sai andando como se nada tivesse acontecido. É o sapo-da-floresta.", "bubble": ["E volta", "a andar?!"], "caption": "E volta a andar como se\\Nnada tivesse acontecido."},
    ],
    [
        {"text": "Quando a temperatura cai, o fígado libera muita glicose.", "bubble": ["O truque?", "GLICOSE."], "caption": "O fígado libera\\Nmuita GLICOSE."},
        {"text": "Ela protege as células enquanto o gelo se forma ao redor delas.", "bubble": ["Ela protege", "as células."], "caption": "Ela protege as células\\Nenquanto o gelo se forma."},
    ],
    [
        {"text": "Na primavera, ele descongela de dentro pra fora: primeiro o coração volta.", "bubble": ["Coração", "primeiro."], "caption": "Descongela de dentro pra fora:\\Nprimeiro, o CORAÇÃO."},
        {"text": "Depois o cérebro.", "bubble": ["Depois", "o cérebro."], "caption": "Depois, o CÉREBRO."},
        {"text": "E, por fim, as pernas.", "bubble": ["Por fim,", "as pernas."], "caption": "Por fim, as PERNAS."},
    ],
    [
        {"text": "Parece ficção, mas é sobrevivência real.", "bubble": ["Parece", "ficção..."], "caption": "Parece ficção, mas é\\NSOBREVIVÊNCIA REAL."},
        {"text": "A natureza consegue ser mais estranha que qualquer filme.", "bubble": ["Mas é", "REAL."], "caption": "A natureza é mais estranha\\Nque qualquer filme."},
        {"text": "Eu sou o Zé Curioso.", "bubble": ["Eu sou o", "Zé Curioso."], "caption": "EU SOU O ZÉ CURIOSO."},
        {"text": "E aqui... parece mentira, mas é real.", "bubble": ["Parece mentira...", "mas é REAL."], "caption": "E aqui...\\Nparece mentira, mas é real."},
    ],
]

SCENE_CONFIG = [
    {"photo": "frog_01.jpg", "title": ["ELE CONGELA.", "O CORAÇÃO PARA."], "accent": "#FFD84A", "side": "left", "tint": (36, 110, 190)},
    {"photo": "frog_02.jpg", "title": ["MESES DEPOIS…", "ELE VOLTA."], "accent": "#79FF9F", "side": "right", "tint": (35, 135, 95)},
    {"photo": "frog_01.jpg", "title": ["O SEGREDO?", "GLICOSE."], "accent": "#FFD84A", "side": "left", "tint": (160, 100, 30)},
    {"photo": "frog_02.jpg", "title": ["DESCONGELA", "DE DENTRO PRA FORA"], "accent": "#BCEEFF", "side": "right", "tint": (40, 95, 155)},
    {"photo": "frog_01.jpg", "title": ["PARECE FICÇÃO.", "MAS É REAL."], "accent": "#79FF9F", "side": "left", "tint": (120, 90, 45)},
]

VOICE_CONTROL = (
    base.VOICE_CONTROL
    + " Keep each short fragment connected to the previous one, with the same timbre, volume and energy."
    + " Keep the voice clean and relaxed; avoid raspiness, vocal fry and rough endings."
)
FINAL_VOICE_CONTROL = (
    base.VOICE_CONTROL
    + " This is the channel signature. Say it calmly and confidently, with a clean smooth voice, a small natural smile,"
    + " and a deliberate pause between clauses. Avoid raspiness, vocal fry, hoarseness and dramatic announcer delivery."
)


def run_quiet(args: list[str]) -> None:
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def probe_duration(path: Path) -> float:
    return float(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            text=True,
        ).strip()
    )


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


def paste_photo_card(canvas: Image.Image, photo: Image.Image) -> None:
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

    inner_bg = ImageOps.fit(photo.convert("RGB"), (iw, ih), method=Image.Resampling.LANCZOS)
    inner_bg = inner_bg.filter(ImageFilter.GaussianBlur(22))
    inner_bg = ImageEnhance.Brightness(inner_bg).enhance(0.38).convert("RGBA")
    main = ImageOps.contain(photo.convert("RGB"), (iw - 36, ih - 36), method=Image.Resampling.LANCZOS).convert("RGBA")
    inner_bg.alpha_composite(main, ((iw - main.width) // 2, (ih - main.height) // 2))
    canvas.paste(inner_bg, (inner[0], inner[1]), rounded_mask((iw, ih), 34))

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
        d.text((x, yy), line, font=font, fill="white" if idx == 0 else accent, stroke_width=5, stroke_fill=(0, 0, 0, 220))
        yy += int(font_size * 1.04)


def paste_mascot(canvas: Image.Image, side: str) -> None:
    ze = Image.open(ASSETS / "ze_main.png").convert("RGBA")
    target_w = 290
    target_h = int(ze.height * target_w / ze.width)
    ze = ze.resize((target_w, target_h), Image.Resampling.LANCZOS)
    x = 34 if side == "left" else W - target_w - 34
    canvas.alpha_composite(ze, (x, 1175))


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

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((box[0] + 7, box[1] + 10, box[2] + 7, box[3] + 10), radius=44, fill=(0, 0, 0, 105))
    im.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(9)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle(box, radius=44, fill=(255, 255, 255, 244), outline=accent, width=7)
    d.polygon(tail, fill=(255, 255, 255, 244))

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


def generate_exact_narration() -> None:
    client = base.Client("openbmb/VoxCPM-Demo", verbose=False)
    ref = base.handle_file(str(ASSETS / "voice_ref.mp3"))
    roteiro: list[str] = []

    for scene_idx, blocks in enumerate(SCENE_BLOCKS, 1):
        roteiro.append(" ".join(block["text"] for block in blocks))
        for block_idx, block in enumerate(blocks, 1):
            last = None
            for attempt in range(1, 18):
                try:
                    control = FINAL_VOICE_CONTROL if scene_idx == 5 and block_idx >= 3 else VOICE_CONTROL
                    result = client.predict(
                        block["text"], control, ref, False, "", 2.0, True, False, api_name="/generate"
                    )
                    src = Path(base.extract_path(result))
                    if not src.exists() or src.stat().st_size < 3500:
                        raise RuntimeError(f"Áudio inválido: {src}")

                    # Padroniza todos os microáudios em WAV 48 kHz. O FFmpeg mede depois
                    # a duração REAL que comandará tanto o balão quanto a legenda.
                    dst = AUDIO / f"scene_{scene_idx:02d}_block_{block_idx:02d}.wav"
                    run_quiet([
                        "ffmpeg", "-y", "-i", str(src), "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)
                    ])
                    if probe_duration(dst) < 0.35:
                        raise RuntimeError(f"Microáudio curto demais: {dst}")
                    print("MICRO_AUDIO_OK", scene_idx, block_idx, round(probe_duration(dst), 3), flush=True)
                    break
                except Exception as exc:
                    last = exc
                    msg = str(exc).lower()
                    if "queue is full" in msg or "429" in msg or "busy" in msg:
                        time.sleep(min(12 + attempt * 3, 42))
                        continue
                    raise
            else:
                raise RuntimeError(last)

    (POST / "roteiro.txt").write_text("\n\n".join(roteiro), encoding="utf-8")


def ass_time(sec: float) -> str:
    h = int(sec // 3600)
    sec -= h * 3600
    m = int(sec // 60)
    sec -= m * 60
    return f"{h}:{m:02d}:{sec:05.2f}"


def write_exact_captions(timing: list[dict]) -> Path:
    path = POST / "captions_card_sync.ass"
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
    events = []
    for item in timing:
        safe = item["caption"].replace("{", "").replace("}", "")
        events.append(
            f"Dialogue: 0,{ass_time(item['start'])},{ass_time(item['end'])},Cap,,0,0,0,,{safe}"
        )
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return path


def render_video_exact() -> None:
    BUBBLE_FRAMES.mkdir(parents=True, exist_ok=True)
    segment_list = VIDEO / "all_exact_segments.txt"
    segment_list.write_text("", encoding="utf-8")
    timing: list[dict] = []
    scene_totals = [0.0 for _ in SCENE_BLOCKS]
    cursor = 0.0

    for scene_idx, (blocks, cfg) in enumerate(zip(SCENE_BLOCKS, SCENE_CONFIG), 1):
        base_img = Image.open(SCENES / f"scene_{scene_idx:02d}.jpg").convert("RGBA")
        for block_idx, block in enumerate(blocks, 1):
            audio = AUDIO / f"scene_{scene_idx:02d}_block_{block_idx:02d}.wav"
            duration = probe_duration(audio)
            scene_totals[scene_idx - 1] += duration

            frame = draw_bubble(base_img, block["bubble"], cfg["side"], cfg["accent"])
            frame_path = BUBBLE_FRAMES / f"scene_{scene_idx:02d}_bubble_{block_idx:02d}.jpg"
            frame.convert("RGB").save(frame_path, quality=95)

            segment = VIDEO / f"scene_{scene_idx:02d}_block_{block_idx:02d}.mp4"
            zoom = "min(zoom+0.00020,1.020)" if block_idx % 2 else "if(lte(zoom,1.0),1.020,max(1.0,zoom-0.00016))"
            vf = (
                f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                "d=1:s=1080x1920:fps=30,format=yuv420p"
            )
            run_quiet([
                "ffmpeg", "-y", "-loop", "1", "-i", str(frame_path), "-i", str(audio),
                "-t", f"{duration:.6f}", "-vf", vf,
                "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-g", "30", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-shortest", str(segment),
            ])
            with segment_list.open("a", encoding="utf-8") as f:
                f.write(f"file '{segment.resolve()}'\n")

            timing.append({
                "scene": scene_idx,
                "block": block_idx,
                "start": round(cursor, 3),
                "end": round(cursor + duration, 3),
                "seconds": round(duration, 3),
                "narration": block["text"],
                "bubble": " / ".join(block["bubble"]),
                "caption": block["caption"],
                "source": audio.name,
                "sync_method": "exact-audio-duration",
            })
            cursor += duration

    base_video = POST / "video_base_card_sync.mp4"
    run_quiet([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(segment_list), "-c", "copy", str(base_video)
    ])
    captions = write_exact_captions(timing)
    final = POST / "ze_curioso_sapo_congela_final.mp4"
    run_quiet([
        "ffmpeg", "-y", "-i", str(base_video), "-vf", f"ass={captions}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart", str(final)
    ])

    (POST / "durations.json").write_text(json.dumps(scene_totals, indent=2), encoding="utf-8")
    (POST / "bubble_timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8")


def qa_and_copy_card() -> None:
    final = POST / "ze_curioso_sapo_congela_final.mp4"
    info = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(final)], text=True
        )
    )
    duration = float(info["format"]["duration"])
    videos = [s for s in info["streams"] if s.get("codec_type") == "video"]
    audios = [s for s in info["streams"] if s.get("codec_type") == "audio"]
    if not videos or not audios:
        raise RuntimeError("QA: stream de vídeo ou áudio ausente")
    v, a = videos[0], audios[0]
    qa = {
        "duration_seconds": duration,
        "width": v.get("width"),
        "height": v.get("height"),
        "video_codec": v.get("codec_name"),
        "audio_codec": a.get("codec_name"),
        "duration_target_ok": 24.0 <= duration <= 48.0,
        "vertical_1080x1920_ok": v.get("width") == 1080 and v.get("height") == 1920,
        "h264_ok": v.get("codec_name") == "h264",
        "aac_ok": a.get("codec_name") == "aac",
        "layout_revision": "card-frame-v2-exact-sync",
        "speech_bubbles": "exact-duration-per-narration-audio-block",
        "sync_is_wordcount_estimate": False,
        "catchphrase_spoken": "Eu sou o Zé Curioso. E aqui... parece mentira, mas é real.",
        "voice_reference": "VoxCPM2 take 02 original",
        "final_voice_direction": "clean-smooth-no-raspiness",
        "photo_mode": "framed-card-contain",
    }
    qa["passed"] = all((qa["duration_target_ok"], qa["vertical_1080x1920_ok"], qa["h264_ok"], qa["aac_ok"]))
    (POST / "qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    if not qa["passed"]:
        raise RuntimeError(f"QA final falhou: {qa}")

    copy = """TÍTULO/CAPA:
O sapo que CONGELA e volta meses depois 🐸❄️

LEGENDA:
Esse sapo passa o inverno sem respirar e sem o coração bater — e depois descongela e volta à atividade. O segredo envolve uma carga enorme de glicose protegendo as células. 🐸❄️

#curiosidades #natureza #animais #ciencia #zecurioso #shorts #tiktokbr

Fontes factuais: U.S. National Park Service — Biological Miracle (Gates of the Arctic) e Amphibians (Denali).
Imagens: MichaelZahniser (Public Domain) e Jasper Shide (CC0 1.0), via Wikimedia Commons.
Voz: VoxCPM2 — take 02 original aprovada do Zé Curioso.
Formato: card central + balão sincronizado pela duração real de cada microáudio.
Bordão: Eu sou o Zé Curioso... e aqui, parece mentira, mas é real.
"""
    (POST / "copy_postagem.txt").write_text(copy, encoding="utf-8")
    print(json.dumps(qa, ensure_ascii=False, indent=2), flush=True)


def main() -> None:
    base.prepare_dirs()
    base.rebuild_mascot()
    base.download_voice_reference()
    base.download_frog_photos()
    generate_exact_narration()
    build_scenes_card()
    render_video_exact()
    qa_and_copy_card()
    print("FINAL_EXACT_SYNC_OK", POST / "ze_curioso_sapo_congela_final.mp4", flush=True)


if __name__ == "__main__":
    main()
