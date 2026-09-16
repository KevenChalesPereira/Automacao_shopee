from __future__ import annotations

import json
import math
import os
import random
import shutil
import subprocess
import time
from pathlib import Path

from gradio_client import Client, handle_file
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

ROOT = Path.cwd()
POST = ROOT / "post_final"
ASSETS = POST / "assets"
AUDIO = POST / "audio"
SCENES = POST / "scenes"
VIDEO = POST / "video"
W, H = 1080, 1920
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

SCRIPT = [
    "Esse sapo congela no inverno, para de respirar e o coração simplesmente para de bater.",
    "E o mais absurdo: meses depois, ele descongela e sai andando como se nada tivesse acontecido. É o sapo-da-floresta.",
    "Quando a temperatura cai, o fígado libera muita glicose. Ela protege as células enquanto o gelo se forma ao redor delas.",
    "Na primavera, ele descongela de dentro pra fora: primeiro o coração volta, depois o cérebro e, por fim, as pernas.",
    "Parece ficção, mas é sobrevivência real. A natureza consegue ser mais estranha que qualquer filme.",
]

CAPTIONS = [
    ["Esse sapo CONGELA no inverno…", "para de respirar — e o CORAÇÃO PARA."],
    ["Meses depois, ele descongela…", "e sai andando como se nada tivesse acontecido.", "É o SAPO-DA-FLORESTA."],
    ["Quando esfria, o fígado libera GLICOSE.", "Ela protege as células enquanto o gelo se forma ao redor."],
    ["Na primavera, descongela DE DENTRO PRA FORA.", "Primeiro coração. Depois cérebro. Por fim, pernas."],
    ["Parece ficção, mas é SOBREVIVÊNCIA REAL.", "A natureza pode ser mais estranha que qualquer filme."],
]

VOICE_CONTROL = (
    "Brazilian Portuguese male short-form content creator. Keep the exact reference timbre and personality. "
    "Speak like telling a surprising fact directly to one friend: warm, spontaneous and naturally animated. "
    "Clear emphasis on surprising words, human micro-pauses, subtle pace changes, around 160 to 170 words per minute. "
    "No radio announcer voice, no theatrical delivery, no shouting."
)

FROG_URLS = [
    "https://upload.wikimedia.org/wikipedia/commons/thumb/6/61/Lithobates_sylvaticus_%28wood_frog%29.jpg/1280px-Lithobates_sylvaticus_%28wood_frog%29.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b9/Lithobates_sylvaticus_-_Wood_Frog_01.jpg/1280px-Lithobates_sylvaticus_-_Wood_Frog_01.jpg",
]


def run(*args: str, capture: bool = False) -> str:
    print("+", " ".join(args), flush=True)
    if capture:
        return subprocess.check_output(args, text=True).strip()
    subprocess.run(args, check=True)
    return ""


def prepare_dirs() -> None:
    if POST.exists():
        shutil.rmtree(POST)
    for p in (ASSETS, AUDIO, SCENES, VIDEO):
        p.mkdir(parents=True, exist_ok=True)


def rebuild_mascot() -> None:
    parts = ["part01.txt", "part02.txt", "part03c.txt", "part03.txt", "part04.txt", "part06.txt", "part07.txt"]
    b64 = ""
    for part in parts:
        ref = f"origin/ze-curioso-v24:assets/ze_curioso/ze_final_b64/{part}"
        b64 += run("git", "show", ref, capture=True)
    import base64
    data = base64.b64decode(b64)
    path = ASSETS / "ze_main.png"
    path.write_bytes(data)
    im = Image.open(path).convert("RGBA")
    if im.width < 250 or im.height < 300:
        raise RuntimeError(f"Mascote inválido: {im.size}")
    print("Mascote Zé OK:", im.size)


def download_voice_reference() -> None:
    token = os.environ.get("GH_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "KevenChalesPereira/Automacao_shopee")
    if not token:
        raise RuntimeError("GH_TOKEN ausente")
    z = Path("/tmp/ze_voice_take02.zip")
    out = Path("/tmp/ze_voice_take02")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    run(
        "curl", "--fail", "--location", "--retry", "3",
        "-H", f"Authorization: Bearer {token}",
        "-H", "Accept: application/vnd.github+json",
        "-H", "X-GitHub-Api-Version: 2022-11-28",
        f"https://api.github.com/repos/{repo}/actions/artifacts/10419929060/zip",
        "-o", str(z),
    )
    run("unzip", "-o", str(z), "-d", str(out))
    matches = sorted(out.rglob("*02_criador_conversando*"))
    if not matches:
        raise RuntimeError("Take 02 original não encontrada no artifact 10419929060")
    shutil.copy2(matches[0], ASSETS / "voice_ref.mp3")
    print("Voz travada:", matches[0].name)


def download_frog_photos() -> None:
    for idx, url in enumerate(FROG_URLS, 1):
        dst = ASSETS / f"frog_{idx:02d}.jpg"
        run("curl", "--fail", "--location", "--retry", "3", url, "-o", str(dst))
        if dst.stat().st_size < 10_000:
            raise RuntimeError(f"Foto suspeita/pequena: {dst}")
        Image.open(dst).verify()
        print("Foto OK:", dst, dst.stat().st_size)


def extract_path(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("path", "name", "url"):
            v = value.get(key)
            if isinstance(v, str) and v:
                return v
    if isinstance(value, (list, tuple)):
        for item in value:
            try:
                return extract_path(item)
            except Exception:
                pass
    raise RuntimeError(f"Saída inesperada do VoxCPM: {value!r}")


def generate_narration() -> None:
    client = Client("openbmb/VoxCPM-Demo", verbose=False)
    ref = handle_file(str(ASSETS / "voice_ref.mp3"))
    for i, text in enumerate(SCRIPT, 1):
        last = None
        for attempt in range(1, 18):
            try:
                result = client.predict(text, VOICE_CONTROL, ref, False, "", 2.0, True, False, api_name="/generate")
                src = Path(extract_path(result))
                if not src.exists() or src.stat().st_size < 4000:
                    raise RuntimeError(f"Áudio inválido: {src}")
                suffix = src.suffix.lower() or ".wav"
                dst = AUDIO / f"scene_{i:02d}{suffix}"
                shutil.copy2(src, dst)
                print("Áudio", i, dst, dst.stat().st_size)
                break
            except Exception as exc:
                last = exc
                msg = str(exc).lower()
                if "queue is full" in msg or "429" in msg or "busy" in msg:
                    time.sleep(min(15 + attempt * 3, 45))
                    continue
                raise
        else:
            raise RuntimeError(last)
    (POST / "roteiro.txt").write_text("\n\n".join(SCRIPT), encoding="utf-8")


def fit_bg(path: Path, center=(0.5, 0.5), zoom=1.0) -> Image.Image:
    im = Image.open(path).convert("RGB")
    bg = ImageOps.fit(im, (W, H), method=Image.Resampling.LANCZOS, centering=center)
    if zoom > 1:
        nw, nh = int(W * zoom), int(H * zoom)
        bg = bg.resize((nw, nh), Image.Resampling.LANCZOS)
        left, top = (nw-W)//2, (nh-H)//2
        bg = bg.crop((left, top, left+W, top+H))
    return bg.convert("RGBA")


def shade(im: Image.Image, top=55, bottom=175) -> Image.Image:
    grad = Image.new("L", (1, H))
    px = grad.load()
    for y in range(H):
        px[0, y] = int(top + (bottom-top) * y/(H-1))
    grad = grad.resize((W, H))
    black = Image.new("RGBA", (W, H), (0,0,0,255))
    black.putalpha(grad)
    return Image.alpha_composite(im, black)


def title(draw: ImageDraw.ImageDraw, lines, y=140, size=76, fills=None) -> None:
    fills = fills or ["white"] * len(lines)
    font = ImageFont.truetype(FONT_BOLD, size)
    yy = y
    for line, fill in zip(lines, fills):
        box = draw.textbbox((0,0), line, font=font, stroke_width=6)
        x = (W - (box[2]-box[0])) // 2
        draw.text((x,yy), line, font=font, fill=fill, stroke_width=6, stroke_fill="black")
        yy += int(size * 1.08)


def brand(draw: ImageDraw.ImageDraw) -> None:
    draw.rounded_rectangle((45,55,315,120), radius=26, fill=(0,0,0,165))
    draw.text((72,70), "ZÉ CURIOSO", font=ImageFont.truetype(FONT_BOLD,32), fill="white")


def paste_ze(im: Image.Image, bubble_lines, side="left") -> None:
    ze = Image.open(ASSETS / "ze_main.png").convert("RGBA")
    tw = 315
    th = int(ze.height * tw / ze.width)
    ze = ze.resize((tw,th), Image.Resampling.LANCZOS)
    y = 1100
    if side == "left":
        zx = 35
        box = (355,1170,1025,1450)
        tail = [(355,1320),(310,1370),(370,1355)]
    else:
        zx = W-tw-35
        box = (55,1170,725,1450)
        tail = [(725,1320),(770,1370),(710,1355)]
    im.alpha_composite(ze, (zx,y))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle(box, radius=46, fill=(255,255,255,235), outline=(20,20,20,230), width=5)
    d.polygon(tail, fill=(255,255,255,235))
    font = ImageFont.truetype(FONT_BOLD, 46)
    x1,y1,x2,y2 = box
    yy = y1 + ((y2-y1)-len(bubble_lines)*58)//2
    for line in bubble_lines:
        tb = d.textbbox((0,0), line, font=font)
        x = x1 + ((x2-x1)-(tb[2]-tb[0]))//2
        d.text((x,yy), line, font=font, fill=(15,15,15,255))
        yy += 58


def build_scenes() -> None:
    frog1, frog2 = ASSETS / "frog_01.jpg", ASSETS / "frog_02.jpg"

    im = fit_bg(frog1, (0.42,0.48), 1.04)
    im = ImageEnhance.Color(im.convert("RGB")).enhance(0.55).convert("RGBA")
    im = Image.alpha_composite(im, Image.new("RGBA",(W,H),(35,125,220,60)))
    im = shade(im,35,165); d=ImageDraw.Draw(im); brand(d)
    random.seed(7)
    for _ in range(130):
        x=random.randrange(W); y=random.randrange(H); r=random.choice((2,3,4,6))
        d.ellipse((x-r,y-r,x+r,y+r),fill=(238,250,255,random.randrange(80,180)))
    title(d,["ELE CONGELA.","O CORAÇÃO PARA."],185,75,["#E9FAFF","#FFD84A"])
    paste_ze(im,["Sem respirar.","Sem batimento."],"left")
    im.convert("RGB").save(SCENES/"scene_01.jpg",quality=95)

    im = fit_bg(frog2,(0.60,0.46),1.10)
    im = ImageEnhance.Color(im.convert("RGB")).enhance(0.62).convert("RGBA")
    im = shade(im,45,180); d=ImageDraw.Draw(im); brand(d)
    title(d,["MESES DEPOIS…","ELE VOLTA."],175,82,["white","#79FF9F"])
    y=760; pts=[]
    for x in range(70,1010,10):
        if 330 < x < 445: dy=-130*math.sin((x-330)/115*math.pi)
        elif 445 <= x < 560: dy=92*math.sin((x-445)/115*math.pi)
        else: dy=0
        pts.append((x,y+dy))
    d.line(pts,fill=(255,72,72,255),width=9)
    paste_ze(im,["E depois...","ele levanta."],"right")
    im.convert("RGB").save(SCENES/"scene_02.jpg",quality=95)

    im = fit_bg(frog1,(0.70,0.42),1.14)
    im = ImageEnhance.Color(im.convert("RGB")).enhance(0.78).convert("RGBA")
    im = shade(Image.alpha_composite(im,Image.new("RGBA",(W,H),(255,155,35,35))),60,190)
    d=ImageDraw.Draw(im); brand(d); title(d,["O SEGREDO?","GLICOSE."],175,88,["white","#FFD84A"])
    random.seed(11)
    for i in range(15):
        x=random.randint(100,980); y=random.randint(610,1050); r=random.randint(24,43)
        d.ellipse((x-r,y-r,x+r,y+r),fill=(255,211,70,190),outline=(255,245,190,230),width=4)
        if i < 6: d.text((x-14,y-19),"G",font=ImageFont.truetype(FONT_BOLD,28),fill="black")
    paste_ze(im,["Ela protege","as células."],"left")
    im.convert("RGB").save(SCENES/"scene_03.jpg",quality=95)

    im = fit_bg(frog2,(0.40,0.50),1.05)
    im = ImageEnhance.Color(im.convert("RGB")).enhance(0.92).convert("RGBA")
    im = shade(im,40,180); d=ImageDraw.Draw(im); brand(d)
    title(d,["DESCONGELA","DE DENTRO PRA FORA"],165,67,["#BCEEFF","white"])
    yy=600
    for num,label in [("1","CORAÇÃO"),("2","CÉREBRO"),("3","PERNAS")]:
        d.ellipse((135,yy,225,yy+90),fill=(255,216,74,235))
        d.text((165,yy+13),num,font=ImageFont.truetype(FONT_BOLD,43),fill="black")
        d.rounded_rectangle((250,yy+5,900,yy+85),radius=30,fill=(0,0,0,160))
        d.text((290,yy+16),label,font=ImageFont.truetype(FONT_BOLD,43),fill="white")
        yy += 120
    paste_ze(im,["Primeiro coração,","depois cérebro."],"right")
    im.convert("RGB").save(SCENES/"scene_04.jpg",quality=95)

    im = fit_bg(frog1,(0.52,0.45),1.08)
    im = ImageEnhance.Color(im.convert("RGB")).enhance(1.15).convert("RGBA")
    im = shade(Image.alpha_composite(im,Image.new("RGBA",(W,H),(255,185,75,32))),30,170)
    d=ImageDraw.Draw(im); brand(d); title(d,["PARECE FICÇÃO.","MAS É REAL."],190,79,["white","#79FF9F"])
    paste_ze(im,["A natureza é","absurda mesmo."],"left")
    d.rounded_rectangle((230,1540,850,1638),radius=38,fill=(0,0,0,165))
    d.text((305,1563),"SOBREVIVÊNCIA REAL",font=ImageFont.truetype(FONT_BOLD,38),fill="#FFD84A")
    im.convert("RGB").save(SCENES/"scene_05.jpg",quality=95)


def audio_durations():
    audios=sorted(AUDIO.glob("scene_*"))
    if len(audios) != 5:
        raise RuntimeError(f"Esperava 5 áudios, achei {len(audios)}")
    durations=[]
    for p in audios:
        d=float(run("ffprobe","-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",str(p),capture=True))
        durations.append(d)
    (POST/"durations.json").write_text(json.dumps(durations,indent=2),encoding="utf-8")
    return audios,durations


def ass_time(sec: float) -> str:
    h=int(sec//3600); sec-=h*3600
    m=int(sec//60); sec-=m*60
    return f"{h}:{m:02d}:{sec:05.2f}"


def write_captions(durations) -> None:
    ass="""[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Cap,DejaVu Sans,52,&H00FFFFFF,&H00FFFFFF,&H00101010,&H98000000,-1,0,0,0,100,100,0,0,3,3,0,2,70,70,145,1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"""
    t=0.0
    for dur,parts in zip(durations,CAPTIONS):
        weights=[max(1,len(x.split())) for x in parts]
        total=sum(weights); cur=t
        for part,w in zip(parts,weights):
            end=cur+dur*w/total
            safe=part.replace("{","").replace("}","")
            ass += f"Dialogue: 0,{ass_time(cur)},{ass_time(end)},Cap,,0,0,0,,{safe}\\N\n"
            cur=end
        t += dur
    (POST/"captions.ass").write_text(ass,encoding="utf-8")


def render_video() -> None:
    audios,durations=audio_durations()
    write_captions(durations)
    video_list=VIDEO/"video_list.txt"
    video_list.write_text("",encoding="utf-8")
    for i,(audio,dur) in enumerate(zip(audios,durations),1):
        img=SCENES/f"scene_{i:02d}.jpg"
        out=VIDEO/f"scene_{i:02d}.mp4"
        z="min(zoom+0.00055,1.065)" if i in (1,3,5) else "if(lte(zoom,1.0),1.065,max(1.0,zoom-0.00050))"
        vf=f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30,format=yuv420p"
        run("ffmpeg","-y","-loop","1","-i",str(img),"-i",str(audio),"-t",str(dur),"-vf",vf,
            "-c:v","libx264","-preset","medium","-crf","19","-c:a","aac","-b:a","192k","-ar","48000","-ac","2","-shortest",str(out))
        with video_list.open("a",encoding="utf-8") as f:
            f.write(f"file '{out.resolve()}'\n")
    base=POST/"video_base.mp4"
    final=POST/"ze_curioso_sapo_congela_final.mp4"
    run("ffmpeg","-y","-f","concat","-safe","0","-i",str(video_list),"-c","copy",str(base))
    run("ffmpeg","-y","-i",str(base),"-vf",f"ass={POST/'captions.ass'}","-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p","-c:a","copy","-movflags","+faststart",str(final))
    shutil.copy2(SCENES/"scene_01.jpg",POST/"capa_sapo_congela_final.jpg")


def qa_and_copy() -> None:
    final=POST/"ze_curioso_sapo_congela_final.mp4"
    info=json.loads(run("ffprobe","-v","error","-show_format","-show_streams","-of","json",str(final),capture=True))
    duration=float(info["format"]["duration"])
    vids=[s for s in info["streams"] if s.get("codec_type")=="video"]
    auds=[s for s in info["streams"] if s.get("codec_type")=="audio"]
    if not vids or not auds:
        raise RuntimeError("QA: stream de vídeo ou áudio ausente")
    v,a=vids[0],auds[0]
    qa={
        "duration_seconds":duration,
        "width":v.get("width"),"height":v.get("height"),
        "video_codec":v.get("codec_name"),"audio_codec":a.get("codec_name"),
        "duration_target_ok":24.0 <= duration <= 42.0,
        "vertical_1080x1920_ok":v.get("width")==1080 and v.get("height")==1920,
        "h264_ok":v.get("codec_name")=="h264",
        "aac_ok":a.get("codec_name")=="aac",
    }
    qa["passed"]=all((qa["duration_target_ok"],qa["vertical_1080x1920_ok"],qa["h264_ok"],qa["aac_ok"]))
    (POST/"qa.json").write_text(json.dumps(qa,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(qa,ensure_ascii=False,indent=2))
    if not qa["passed"]:
        raise RuntimeError("QA final falhou")
    copy="""TÍTULO/CAPA:\nO sapo que CONGELA e volta meses depois 🐸❄️\n\nLEGENDA:\nEsse sapo passa o inverno sem respirar e sem o coração bater — e depois descongela e volta à atividade. O segredo envolve uma carga enorme de glicose protegendo as células. 🐸❄️\n\n#curiosidades #natureza #animais #ciencia #zecurioso #shorts #tiktokbr\n\nFontes factuais: U.S. National Park Service — Biological Miracle (Gates of the Arctic) e Amphibians (Denali).\nImagens: MichaelZahniser (Public Domain) e Jasper Shide (CC0 1.0), via Wikimedia Commons.\nVoz: VoxCPM2 — take 02 original aprovada do Zé Curioso.\n"""
    (POST/"copy_postagem.txt").write_text(copy,encoding="utf-8")


def main() -> None:
    prepare_dirs()
    rebuild_mascot()
    download_voice_reference()
    download_frog_photos()
    generate_narration()
    build_scenes()
    render_video()
    qa_and_copy()
    print("FINAL_OK", POST/"ze_curioso_sapo_congela_final.mp4")


if __name__ == "__main__":
    main()
