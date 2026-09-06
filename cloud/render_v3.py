#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import math
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps


VOICE = "pt-BR-FranciscaNeural"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def run(cmd, cwd=None):
    print(
        "[>] " + " ".join(str(x) for x in cmd),
        flush=True,
    )

    result = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )

    if result.returncode != 0:
        print(
            result.stderr[-9000:],
            flush=True,
        )
        raise RuntimeError(
            f"Comando falhou: {cmd[0]}"
        )

    return result


def duration(audio):
    result = run([
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio),
    ])

    try:
        value = float(
            result.stdout.strip()
        )
        return max(20.0, min(value, 38.0))
    except Exception:
        return 30.0


def wrap(value, width):
    return "\n".join(
        textwrap.wrap(
            str(value),
            width=width,
            break_long_words=False,
            break_on_hyphens=False,
        )
    )


def font(path, size):
    try:
        return ImageFont.truetype(
            path,
            size,
        )
    except Exception:
        return ImageFont.load_default()


def create_procedural_background(path):
    w, h = 1080, 1920
    image = Image.new(
        "RGB",
        (w, h),
        (8, 9, 16),
    )
    px = image.load()

    # Gradiente radial/vertical com aparência tech sem depender de IA.
    for y in range(h):
        ny = y / h

        for x in range(w):
            nx = x / w

            glow1 = max(
                0.0,
                1.0 - (
                    ((nx - 0.2) / 0.55) ** 2
                    + ((ny - 0.18) / 0.42) ** 2
                )
            )

            glow2 = max(
                0.0,
                1.0 - (
                    ((nx - 0.85) / 0.55) ** 2
                    + ((ny - 0.65) / 0.46) ** 2
                )
            )

            r = int(
                min(
                    255,
                    8
                    + 22 * glow1
                    + 55 * glow2,
                )
            )
            g = int(
                min(
                    255,
                    9
                    + 52 * glow1
                    + 15 * glow2,
                )
            )
            b = int(
                min(
                    255,
                    16
                    + 85 * glow1
                    + 75 * glow2,
                )
            )

            px[x, y] = (
                r,
                g,
                b,
            )

    draw = ImageDraw.Draw(
        image,
        "RGBA",
    )

    # luz central / pedestal
    for radius in range(
        420,
        20,
        -18,
    ):
        alpha = int(
            2 + (420 - radius) / 420 * 4
        )

        draw.ellipse(
            (
                540 - radius,
                870 - radius // 4,
                540 + radius,
                870 + radius // 4,
            ),
            fill=(
                130,
                90,
                255,
                alpha,
            ),
        )

    draw.ellipse(
        (180, 1260, 900, 1430),
        fill=(0, 0, 0, 90),
    )

    image = image.filter(
        ImageFilter.GaussianBlur(1.2)
    )

    image.save(
        path,
        quality=94,
    )


def remove_background(input_path, output_path):
    """
    Tenta rembg. Se algo falhar, usa a imagem inteira com cantos arredondados.
    """
    try:
        run([
            sys.executable,
            "-m",
            "rembg",
            "i",
            str(input_path),
            str(output_path),
        ])

        if output_path.is_file():
            return True

    except Exception as exc:
        print(
            f"[!] rembg falhou: {exc}",
            flush=True,
        )

    return False


def fallback_product_card(input_path, output_path):
    src = Image.open(
        input_path
    ).convert("RGB")

    src.thumbnail(
        (760, 760),
        Image.Resampling.LANCZOS,
    )

    card = Image.new(
        "RGBA",
        (820, 820),
        (255, 255, 255, 0),
    )

    shadow = Image.new(
        "RGBA",
        card.size,
        (0, 0, 0, 0),
    )

    sd = ImageDraw.Draw(
        shadow
    )

    sd.rounded_rectangle(
        (20, 35, 800, 800),
        radius=70,
        fill=(0, 0, 0, 100),
    )

    shadow = shadow.filter(
        ImageFilter.GaussianBlur(24)
    )

    card.alpha_composite(
        shadow
    )

    draw = ImageDraw.Draw(
        card
    )

    draw.rounded_rectangle(
        (20, 20, 800, 780),
        radius=70,
        fill=(255, 255, 255, 250),
    )

    x = (
        card.width - src.width
    ) // 2
    y = (
        20
        + (760 - src.height) // 2
    )

    card.paste(
        src,
        (x, y),
    )

    card.save(
        output_path
    )


def prepare_product(job_dir, work):
    for ext in (
        "png",
        "jpg",
        "jpeg",
        "webp",
    ):
        p = (
            job_dir
            / f"product.{ext}"
        )

        if p.is_file():
            source = p
            break
    else:
        return None

    rgba = (
        work
        / "product.png"
    )

    if remove_background(
        source,
        rgba,
    ):
        try:
            im = Image.open(
                rgba
            ).convert("RGBA")

            bbox = im.getbbox()

            if bbox:
                im = im.crop(
                    bbox
                )

            im.thumbnail(
                (800, 930),
                Image.Resampling.LANCZOS,
            )

            canvas = Image.new(
                "RGBA",
                (900, 1030),
                (0, 0, 0, 0),
            )

            x = (
                canvas.width
                - im.width
            ) // 2
            y = (
                canvas.height
                - im.height
            ) // 2

            # sombra
            shadow = Image.new(
                "RGBA",
                canvas.size,
                (0, 0, 0, 0),
            )

            alpha = Image.new(
                "L",
                im.size,
                0,
            )
            alpha.paste(
                im.getchannel("A")
            )

            shadow_piece = Image.new(
                "RGBA",
                im.size,
                (0, 0, 0, 135),
            )
            shadow_piece.putalpha(
                alpha.filter(
                    ImageFilter.GaussianBlur(26)
                )
            )

            shadow.alpha_composite(
                shadow_piece,
                (x + 10, y + 28),
            )

            canvas.alpha_composite(
                shadow
            )
            canvas.alpha_composite(
                im,
                (x, y),
            )

            canvas.save(
                rgba
            )

            return rgba

        except Exception:
            pass

    fallback_product_card(
        source,
        rgba,
    )

    return rgba


def create_missing_product(product, path):
    image = Image.new(
        "RGBA",
        (900, 1030),
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(
        image
    )

    draw.rounded_rectangle(
        (65, 160, 835, 860),
        radius=70,
        fill=(255, 255, 255, 245),
    )

    title = wrap(
        product.get(
            "nome_limpo",
            "Produto",
        ),
        18,
    )

    draw.text(
        (450, 460),
        title,
        anchor="mm",
        align="center",
        fill=(18, 18, 24),
        font=font(
            FONT_BOLD,
            70,
        ),
        spacing=18,
    )

    draw.text(
        (450, 740),
        "IMAGEM DO PRODUTO\nNÃO DISPONÍVEL",
        anchor="mm",
        align="center",
        fill=(110, 110, 125),
        font=font(
            FONT_BOLD,
            28,
        ),
        spacing=8,
    )

    image.save(
        path
    )


def make_visual_texts(work, product):
    points = list(
        product.get(
            "pontos_visuais"
        )
        or []
    )[:3]

    while len(points) < 3:
        points.append("CONFIRA")

    values = {
        "hook.txt": wrap(
            product.get(
                "hook_visual",
                "OLHA ESSE ACHADO",
            ).upper(),
            22,
        ),
        "badge1.txt": points[0],
        "badge2.txt": points[1],
        "badge3.txt": points[2],
        "cta.txt": "CONFIRA AS CONDIÇÕES\nATUAIS NA SHOPEE",
    }

    for name, value in values.items():
        (
            work
            / name
        ).write_text(
            value,
            encoding="utf-8",
        )


def render(product, background, product_png, audio, subtitles, work):
    total = duration(
        audio
    )

    make_visual_texts(
        work,
        product,
    )

    bg_local = (
        work
        / "background.jpg"
    )

    Image.open(
        background
    ).convert(
        "RGB"
    ).resize(
        (1080, 1920),
        Image.Resampling.LANCZOS,
    ).save(
        bg_local,
        quality=94,
    )

    # Uma cena contínua:
    # - fundo com zoom suave e leve drift
    # - produto flutua e faz microzoom
    # - badges entram em sequência
    # - legenda menor, sem cobrir metade do vídeo
    # - CTA final
    end_cta = max(
        15.0,
        total - 5.5,
    )

    fc = f"""
[0:v]
zoompan=
z='1.03+0.00018*on':
x='iw/2-(iw/zoom/2)+18*sin(on/38)':
y='ih/2-(ih/zoom/2)+12*cos(on/45)':
d=1:s=1080x1920:fps=30,
eq=brightness=-0.07:saturation=1.12
[bg];

[1:v]
format=rgba,
scale='760+24*sin(t*1.35)':'-1'
[prod];

[bg][prod]
overlay=
x='(W-w)/2+11*sin(t*1.55)':
y='430+18*sin(t*1.15)':
eval=frame
[v0];

[v0]
drawbox=x=0:y=0:w=1080:h=330:color=black@0.22:t=fill:
enable='between(t,0,4.2)',

drawtext=
fontfile={FONT_BOLD}:
textfile=hook.txt:
fontcolor=white:
fontsize=58:
line_spacing=12:
borderw=3:
bordercolor=black@0.45:
x='if(lt(t,0.5),1080-(t/0.5)*(1080-text_w),(w-text_w)/2)':
y=105:
enable='between(t,0,4.2)':
expansion=none,

drawbox=
x='if(lt(t,8.8),-470+(t-6.8)*260,75)':
y=1450:w=390:h=108:
color=0xFF5A36@0.96:t=fill:
enable='between(t,6.8,13.0)',

drawtext=
fontfile={FONT_BOLD}:
textfile=badge1.txt:
fontcolor=white:
fontsize=42:
x='if(lt(t,8.8),-425+(t-6.8)*260,120)':
y=1480:
enable='between(t,6.8,13.0)':
expansion=none,

drawbox=
x='if(lt(t,11.8),1080-(t-9.8)*250,610)':
y=1585:w=395:h=108:
color=white@0.96:t=fill:
enable='between(t,9.8,16.0)',

drawtext=
fontfile={FONT_BOLD}:
textfile=badge2.txt:
fontcolor=0x17171F:
fontsize=40:
x='if(lt(t,11.8),1125-(t-9.8)*250,655)':
y=1615:
enable='between(t,9.8,16.0)':
expansion=none,

drawbox=x=75:y=1715:w=390:h=100:
color=0x242433@0.94:t=fill:
enable='between(t,13.2,19.0)',

drawtext=
fontfile={FONT_BOLD}:
textfile=badge3.txt:
fontcolor=white:
fontsize=38:
x=120:y=1742:
enable='between(t,13.2,19.0)':
expansion=none,

drawbox=x=70:y=120:w=940:h=260:
color=0xFF5A36@0.96:t=fill:
enable='gte(t,{end_cta:.3f})',

drawtext=
fontfile={FONT_BOLD}:
textfile=cta.txt:
fontcolor=white:
fontsize=60:
line_spacing=12:
borderw=2:
bordercolor=black@0.4:
x=(w-text_w)/2:
y=175:
enable='gte(t,{end_cta:.3f})':
expansion=none,

subtitles=subtitles.srt:
force_style='FontName=DejaVu Sans,FontSize=19,Bold=1,BorderStyle=3,BackColour=&H99000000,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=1,Shadow=0,Alignment=2,MarginV=165'
[v]
""".replace(
        "\n",
        "",
    )

    output = (
        work
        / "anuncio_final.mp4"
    )

    run(
        [
            "ffmpeg",
            "-y",
            "-loop", "1",
            "-framerate", "30",
            "-i", str(bg_local),
            "-loop", "1",
            "-framerate", "30",
            "-i", str(product_png),
            "-i", str(audio),
            "-filter_complex", fc,
            "-map", "[v]",
            "-map", "2:a:0",
            "-t", f"{total:.3f}",
            "-r", "30",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "22",
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
            "Uso: render_v3.py JOB_DIR OUTPUT_DIR"
        )

    job_dir = Path(
        sys.argv[1]
    ).resolve()

    output_dir = Path(
        sys.argv[2]
    ).resolve()

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    work = (
        output_dir
        / "_work"
    )

    work.mkdir(
        parents=True,
        exist_ok=True,
    )

    product = json.loads(
        (
            job_dir
            / "produto.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    roteiro = (
        work
        / "roteiro.txt"
    )

    roteiro.write_text(
        product["roteiro_comercial"],
        encoding="utf-8",
    )

    audio = (
        work
        / "narracao.mp3"
    )

    subtitles = (
        work
        / "subtitles.srt"
    )

    run([
        "edge-tts",
        "--file", str(roteiro),
        "--voice", VOICE,
        "--rate=+7%",
        "--write-media", str(audio),
        "--write-subtitles", str(subtitles),
    ])

    background = (
        job_dir
        / "background.jpg"
    )

    if not background.is_file():
        background = (
            work
            / "procedural.jpg"
        )

        create_procedural_background(
            background
        )

    product_png = prepare_product(
        job_dir,
        work,
    )

    if not product_png:
        product_png = (
            work
            / "product.png"
        )

        create_missing_product(
            product,
            product_png,
        )

    final = render(
        product,
        background,
        product_png,
        audio,
        subtitles,
        work,
    )

    shutil.copy2(
        final,
        output_dir
        / "anuncio_final.mp4",
    )

    shutil.copy2(
        job_dir
        / "produto.json",
        output_dir
        / "produto.json",
    )

    (
        output_dir
        / "copie_e_cole_na_live.txt"
    ).write_text(
        (
            f"🔥 ACHADO NA SHOPEE\n\n"
            f"{product.get('nome_limpo', 'Produto')}\n\n"
            "🛒 Confira preço, avaliações, cupons, frete e condições atuais no anúncio.\n\n"
            + " ".join(
                product.get(
                    "tags_engajamento"
                )
                or []
            )
            + "\n"
        ),
        encoding="utf-8",
    )

    print(
        "[OK] Render V3 concluído.",
        flush=True,
    )


if __name__ == "__main__":
    main()
