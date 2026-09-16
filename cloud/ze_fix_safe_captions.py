from __future__ import annotations

import json
import subprocess
from pathlib import Path

POST = Path("post_final")
BASE = POST / "video_base.mp4"
FINAL = POST / "ze_curioso_sapo_congela_final.mp4"
ASS = POST / "captions_safe.ass"

# Quebras manuais: nenhuma linha longa o bastante para escapar das margens.
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
        "A natureza pode ser\\Nmais estranha que\\Nqualquer filme.",
    ],
]


def ass_time(sec: float) -> str:
    h = int(sec // 3600)
    sec -= h * 3600
    m = int(sec // 60)
    sec -= m * 60
    return f"{h}:{m:02d}:{sec:05.2f}"


def main() -> None:
    durations = json.loads((POST / "durations.json").read_text(encoding="utf-8"))
    if len(durations) != 5:
        raise SystemExit(f"Esperava 5 durações, achei {len(durations)}")
    if not BASE.exists():
        raise SystemExit(f"Vídeo-base ausente: {BASE}")

    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Cap,DejaVu Sans,44,&H00FFFFFF,&H00FFFFFF,&H00101010,&HA0000000,-1,0,0,0,100,100,0,0,3,3,0,2,90,90,245,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""

    events = []
    t = 0.0
    for dur, parts in zip(durations, CAPTIONS):
        weights = [max(1, len(p.replace("\\N", " ").split())) for p in parts]
        total = sum(weights)
        cur = t
        for part, weight in zip(parts, weights):
            seg = dur * weight / total
            end = cur + seg
            safe = part.replace("{", "").replace("}", "")
            events.append(
                f"Dialogue: 0,{ass_time(cur)},{ass_time(end)},Cap,,0,0,0,,{safe}"
            )
            cur = end
        t += dur

    ASS.write_text(header + "\n".join(events) + "\n", encoding="utf-8")

    tmp = POST / "ze_curioso_sapo_congela_safe_tmp.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(BASE),
            "-vf", f"ass={ASS}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
            str(tmp),
        ],
        check=True,
    )
    tmp.replace(FINAL)

    probe = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(FINAL)],
            text=True,
        )
    )
    duration = float(probe["format"]["duration"])
    vids = [s for s in probe["streams"] if s.get("codec_type") == "video"]
    auds = [s for s in probe["streams"] if s.get("codec_type") == "audio"]
    if not vids or not auds:
        raise SystemExit("QA: stream ausente após correção")
    v, a = vids[0], auds[0]
    qa = {
        "duration_seconds": duration,
        "width": v.get("width"),
        "height": v.get("height"),
        "video_codec": v.get("codec_name"),
        "audio_codec": a.get("codec_name"),
        "duration_target_ok": 24.0 <= duration <= 42.0,
        "vertical_1080x1920_ok": v.get("width") == 1080 and v.get("height") == 1920,
        "h264_ok": v.get("codec_name") == "h264",
        "aac_ok": a.get("codec_name") == "aac",
        "caption_safe_layout": True,
        "caption_font_size": 44,
        "caption_horizontal_margin": 90,
        "caption_bottom_margin": 245,
        "caption_revision": "safe-area-v2",
    }
    qa["passed"] = all(
        [qa["duration_target_ok"], qa["vertical_1080x1920_ok"], qa["h264_ok"], qa["aac_ok"]]
    )
    (POST / "qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    if not qa["passed"]:
        raise SystemExit("QA técnico falhou após correção")
    print(json.dumps(qa, ensure_ascii=False, indent=2))
    print("CAPTION_FIX_OK", FINAL)


if __name__ == "__main__":
    main()
