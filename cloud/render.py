#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


VOICE = "pt-BR-FranciscaNeural"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def run(cmd, cwd=None):
    print("[>] " + " ".join(str(x) for x in cmd), flush=True)

    result = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )

    if result.returncode != 0:
        print(result.stderr[-8000:], flush=True)
        raise RuntimeError(
            f"Comando falhou: {cmd[0]}"
        )

    return result


def ffprobe_duration(audio):
    result = run([
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio),
    ])

    try:
        return max(1.0, float(result.stdout.strip()))
    except Exception:
        return 35.0


def wrap_text(text, width):
    return "\n".join(
        textwrap.wrap(
            str(text),
            width=width,
            break_long_words=False,
            break_on_hyphens=False,
        )
    )


def make_fallback_image(product, path):
    image = Image.new("RGB", (1080, 1920), (18, 18, 24))
    draw = ImageDraw.Draw(image)

    # Gradiente simples, sem depender de mídia externa.
    for y in range(1920):
        ratio = y / 1919
        r = int(18 + 42 * ratio)
        g = int(18 + 14 * ratio)
        b = int(24 + 55 * ratio)
        draw.line((0, y, 1080, y), fill=(r, g, b))

    try:
        font_big = ImageFont.truetype(FONT, 86)
        font_small = ImageFont.truetype(FONT, 44)
    except Exception:
        font_big = ImageFont.load_default()
        font_small = ImageFont.load_default()

    title = wrap_text(
        product.get("nome_limpo", "Produto"),
        18,
    )

    draw.rounded_rectangle(
        (110, 500, 970, 1320),
        radius=65,
        fill=(255, 255, 255),
    )

    # "Produto" ilustrativo sem inventar aparência.
    draw.text(
        (540, 760),
        title,
        anchor="mm",
        align="center",
        fill=(20, 20, 24),
        font=font_big,
        spacing=20,
    )

    draw.text(
        (540, 1130),
        "IMAGEM ILUSTRATIVA",
        anchor="mm",
        fill=(100, 100, 110),
        font=font_small,
    )

    image.save(path, quality=94)


def find_product_image(job_dir, product):
    for ext in ("jpg", "jpeg", "png", "webp"):
        path = job_dir / f"product.{ext}"
        if path.is_file():
            return path

    path = job_dir / "fallback.jpg"
    make_fallback_image(product, path)
    return path


def make_text_files(work, product):
    points = product.get("pontos_visuais") or []
    points = [str(x) for x in points][:3]

    while len(points) < 3:
        points.append("CONFIRA")

    files = {
        "hook.txt": wrap_text(
            product.get(
                "hook_visual",
                "OLHA ESSE ACHADO",
            ),
            25,
        ),
        "title.txt": wrap_text(
            product.get(
                "nome_limpo",
                "Produto",
            ).upper(),
            22,
        ),
        "badge1.txt": points[0],
        "badge2.txt": points[1],
        "badge3.txt": points[2],
        "cta.txt": "CONFIRA AS CONDIÇÕES\nATUAIS NA SHOPEE",
    }

    for filename, content in files.items():
        (work / filename).write_text(
            content,
            encoding="utf-8",
        )


def render(product, image_path, audio, subtitles, work):
    duration = ffprobe_duration(audio)
    duration = max(30.0, min(duration, 42.0))

    # Cópias com nomes simples evitam problemas de filtros com caminhos.
    source_img = work / "product.jpg"

    # Converte para JPG de forma previsível.
    img = Image.open(image_path).convert("RGB")
    img.thumbnail((1600, 1600))
    img.save(source_img, quality=95)

    make_text_files(work, product)

    # Imagem principal + fundo da própria imagem desfocado.
    # O produto fica em uma única cena contínua: fundo com zoom,
    # cartão flutuante, textos entrando em momentos diferentes.
    filter_complex = f"""
[0:v]split=2[bgsrc][fgsrc];
[bgsrc]
scale=1250:2223:force_original_aspect_ratio=increase,
crop=1250:2223,
zoompan=z='min(1.0+0.00022*on,1.075)':
x='iw/2-(iw/zoom/2)':
y='ih/2-(ih/zoom/2)':
d=1:s=1080x1920:fps=30,
gblur=sigma=35,
eq=brightness=-0.32:saturation=1.15
[bg];

[fgsrc]
scale=820:980:force_original_aspect_ratio=decrease,
format=rgba,
pad=860:1020:(ow-iw)/2:(oh-ih)/2:color=white
[fg];

[bg]
drawbox=x=55:y=70:w=970:h=1775:color=black@0.18:t=fill,
drawbox=x=55:y=70:w=970:h=8:color=0xFF5A36:t=fill
[stage];

[stage][fg]
overlay=x='(W-w)/2+8*sin(2*PI*t/4.8)':
y='430+18*sin(2*PI*t/3.2)':
eval=frame
[v0];

[v0]
drawtext=fontfile={FONT}:textfile=hook.txt:
fontcolor=white:fontsize=66:line_spacing=12:
x='if(lt(t,0.55),W-(t/0.55)*(W-text_w),(W-text_w)/2)':
y=125:
borderw=3:bordercolor=black:
enable='between(t,0,4.5)':
expansion=none,

drawtext=fontfile={FONT}:textfile=title.txt:
fontcolor=white:fontsize=58:line_spacing=10:
x=(w-text_w)/2:y=1450:
borderw=3:bordercolor=black:
enable='between(t,4,14)':
expansion=none,

drawbox=x='if(lt(t,13),-520+520*(t-10)/3,80)':
y=1460:w=420:h=120:color=0xFF5A36@0.95:t=fill:
enable='between(t,10,20)',

drawtext=fontfile={FONT}:textfile=badge1.txt:
fontcolor=white:fontsize=48:
x='if(lt(t,13),-470+520*(t-10)/3,130)':
y=1493:
enable='between(t,10,20)':
expansion=none,

drawbox=x='if(lt(t,15),1080-520*(t-12)/3,580)':
y=1595:w=420:h=120:color=white@0.94:t=fill:
enable='between(t,12,22)',

drawtext=fontfile={FONT}:textfile=badge2.txt:
fontcolor=0x16161C:fontsize=45:
x='if(lt(t,15),1130-520*(t-12)/3,630)':
y=1628:
enable='between(t,12,22)':
expansion=none,

drawbox=x=80:y=1730:w=420:h=105:color=0x252530@0.95:t=fill:
enable='between(t,15,24)',

drawtext=fontfile={FONT}:textfile=badge3.txt:
fontcolor=white:fontsize=42:
x=125:y=1758:
enable='between(t,15,24)':
expansion=none,

drawbox=x=75:y=140:w=930:h=240:
color=0xFF5A36@0.96:t=fill:
enable='gte(t,{max(0, duration-6):.2f})',

drawtext=fontfile={FONT}:textfile=cta.txt:
fontcolor=white:fontsize=64:line_spacing=12:
x=(w-text_w)/2:y=190:
borderw=2:bordercolor=black:
enable='gte(t,{max(0, duration-6):.2f})':
expansion=none,

subtitles=subtitles.srt:
force_style='FontName=DejaVu Sans,FontSize=22,Bold=1,BorderStyle=3,BackColour=&H88000000,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=1,Shadow=0,Alignment=2,MarginV=235'
[v]
""".replace("\n", "")

    output = work / "anuncio_final.mp4"

    run(
        [
            "ffmpeg",
            "-y",
            "-loop", "1",
            "-framerate", "30",
            "-i", str(source_img),
            "-i", str(audio),
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "1:a:0",
            "-t", f"{duration:.3f}",
            "-r", "30",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            str(output),
        ],
        cwd=work,
    )

    return output


def main():
    if len(sys.argv) != 3:
        raise SystemExit(
            "Uso: render.py JOB_DIR OUTPUT_DIR"
        )

    job_dir = Path(sys.argv[1]).resolve()
    output_dir = Path(sys.argv[2]).resolve()

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    product = json.loads(
        (job_dir / "produto.json").read_text(
            encoding="utf-8"
        )
    )

    work = output_dir / "_work"
    work.mkdir(
        parents=True,
        exist_ok=True,
    )

    script_file = work / "roteiro.txt"
    script_file.write_text(
        product["roteiro_comercial"],
        encoding="utf-8",
    )

    audio = work / "narracao.mp3"
    subtitles = work / "subtitles.srt"

    run([
        "edge-tts",
        "--file", str(script_file),
        "--voice", VOICE,
        "--rate=+5%",
        "--write-media", str(audio),
        "--write-subtitles", str(subtitles),
    ])

    image = find_product_image(
        job_dir,
        product,
    )

    video = render(
        product,
        image,
        audio,
        subtitles,
        work,
    )

    shutil.copy2(
        video,
        output_dir / "anuncio_final.mp4",
    )

    shutil.copy2(
        job_dir / "produto.json",
        output_dir / "produto.json",
    )

    live = (
        f"🔥 ACHADO NA SHOPEE\n\n"
        f"{product.get('nome_limpo', 'Produto')}\n\n"
        "🛒 Confira preço, avaliações, cupons, frete e "
        "condições atuais diretamente no anúncio.\n\n"
        + " ".join(
            product.get("tags_engajamento") or []
        )
        + "\n"
    )

    (
        output_dir / "copie_e_cole_na_live.txt"
    ).write_text(
        live,
        encoding="utf-8",
    )

    print("[OK] Vídeo concluído.", flush=True)


if __name__ == "__main__":
    main()
