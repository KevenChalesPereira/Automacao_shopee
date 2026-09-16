from __future__ import annotations

import json
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import ze_postavel_woodfrog_v6_4_finalpolish as fp

carrier = fp.carrier
fs = carrier.fs
v4 = fp.v4
cont = fp.cont
POST = fp.POST
AUDIO = fp.AUDIO
FONT_BOLD = fp.FONT_BOLD

# Pedido final do template:
# - janela de ate 3 palavras continua;
# - somente a palavra sendo falada recebe destaque visual (sem POP por palavra);
# - o BALAO inteiro faz um unico POP quando entra um novo bloco/frase;
# - restaura o bordao anterior;
# - preserva voz calma, timestamps Faster-Whisper e render single-pass.
PREVIOUS_SIGNOFF = "Eu sou o Zé Curioso. E aqui... parece mentira, mas é real."
EXPECTED_SIGNOFF = v4.words_from_text(PREVIOUS_SIGNOFF)
CRITICAL_SIGNOFF = {"ze", "curioso", "mentira", "real"}

_original_build_three_word_timing = fp.build_three_word_timing
_original_qa_three_word_window = fp.qa_three_word_window


def generate_previous_signoff():
    client = cont.base.Client("openbmb/VoxCPM-Demo", verbose=False)
    ref = cont.base.handle_file(str(cont.ASSETS / "voice_ref.mp3"))
    model = v4.WhisperModel("small", device="cpu", compute_type="int8")
    candidates: list[dict] = []
    valid: list[dict] = []

    control = (
        "Use exactly the same speaker identity and timbre as the reference. "
        "Speak calmly, naturally and conversationally. "
        "Say the sentence exactly as written. Pronounce 'Zé Curioso' clearly, with Zé separate from Curioso. "
        "Give the final words 'parece mentira, mas é real' a little more presence, but never shout, never sound urgent, theatrical or like an announcer."
    )

    for attempt in range(1, 9):
        print(f"PREVIOUS_SIGNOFF_ATTEMPT {attempt}", flush=True)
        result = client.predict(
            PREVIOUS_SIGNOFF,
            control,
            ref,
            False,
            "",
            2.0,
            True,
            False,
            api_name="/generate",
        )
        src = Path(cont.base.extract_path(result))
        if not src.exists() or src.stat().st_size < 5000:
            time.sleep(2)
            continue

        raw = AUDIO / f"signoff_previous_candidate_{attempt:02d}.wav"
        v4.run([
            "ffmpeg", "-y", "-i", str(src), "-ar", "48000", "-ac", "1",
            "-c:a", "pcm_s16le", str(raw),
        ])
        words, transcript = v4.transcribe(model, raw)
        actual = [w["norm"] for w in words]
        _, ratio = v4.align_tokens(EXPECTED_SIGNOFF, actual)
        missing = sorted(CRITICAL_SIGNOFF - set(actual))
        stab = fs.v6.stability_metrics(raw)
        row = {
            "attempt": attempt,
            "path": raw.name,
            "duration": round(v4.probe_duration(raw), 3),
            "asr_ratio": round(ratio, 4),
            "missing_critical": missing,
            "transcript": transcript,
            **stab,
        }
        candidates.append(row)
        print("PREVIOUS_SIGNOFF_QA", json.dumps(row, ensure_ascii=False), flush=True)
        if ratio >= 0.90 and not missing:
            valid.append({"raw": raw, "words": words, "ratio": ratio, "transcript": transcript, "metrics": row})
            if ratio >= 0.98:
                break
        time.sleep(2)

    if not valid:
        (POST / "signoff_qa.json").write_text(
            json.dumps({"selected": None, "strategy": "previous signoff direct generation", "candidates": candidates}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        raise RuntimeError("Bordao anterior nao passou no ASR")

    best = max(valid, key=lambda x: (x["ratio"], x["metrics"].get("stability_score", 0.0)))
    final = AUDIO / "signoff_final.wav"
    v4.run([
        "ffmpeg", "-y", "-i", str(best["raw"]),
        "-af", "loudnorm=I=-15:TP=-2:LRA=7",
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(final),
    ])
    selected = {
        **best["metrics"],
        "strategy": "previous signoff direct generation",
        "expected_text": PREVIOUS_SIGNOFF,
    }
    (POST / "signoff_qa.json").write_text(
        json.dumps({"selected": selected, "candidates": candidates}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return final, best["words"], best["ratio"], best["transcript"], selected


def build_simple_timing(words: list[dict]):
    timing, ratio = _original_build_three_word_timing(words)
    for idx, item in enumerate(timing):
        first_in_block = idx == 0 or (
            timing[idx - 1]["scene"] != item["scene"]
            or timing[idx - 1]["block"] != item["block"]
        )
        item["animation"] = (
            "bubble entrance POP once; active spoken word highlight only"
            if first_in_block
            else "active spoken word highlight only; no pop"
        )
        item["bubble_pop_once"] = first_in_block
        item["active_word_effect"] = "highlight only"

    p = POST / "word_bubble_timing.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["words"] = timing
    data["active_word_only"] = False
    data["active_word_effect"] = "highlight only"
    data["bubble_pop"] = "once at each block/phrase entrance"
    data["pop_profile"] = "whole bubble 86%-108%-100% once; no per-word pop"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return timing, ratio


def _scaled_point(point: tuple[float, float], center: tuple[float, float], scale: float):
    return (
        center[0] + (point[0] - center[0]) * scale,
        center[1] + (point[1] - center[1]) * scale,
    )


def draw_simple_bubble(
    base_img: Image.Image,
    timing: list[dict],
    active_index: int,
    side: str,
    accent: str,
    active_scale: float,
) -> Image.Image:
    """Palavra ativa apenas destaca; balão inteiro faz POP somente no início do bloco."""
    im = base_img.copy().convert("RGBA")
    d = ImageDraw.Draw(im)
    base_box, base_tail = fp.bubble_geometry_static(side)

    item = timing[active_index]
    first_in_block = active_index == 0 or (
        timing[active_index - 1]["scene"] != item["scene"]
        or timing[active_index - 1]["block"] != item["block"]
    )
    bubble_scale = active_scale if first_in_block else 1.0

    cx = (base_box[0] + base_box[2]) / 2.0
    cy = (base_box[1] + base_box[3]) / 2.0
    center = (cx, cy)
    box = (
        cx + (base_box[0] - cx) * bubble_scale,
        cy + (base_box[1] - cy) * bubble_scale,
        cx + (base_box[2] - cx) * bubble_scale,
        cy + (base_box[3] - cy) * bubble_scale,
    )
    tail = [_scaled_point(p, center, bubble_scale) for p in base_tail]

    d.polygon(tail, fill=(255, 255, 255, 248))
    d.rounded_rectangle(
        box,
        radius=max(22, int(round(34 * bubble_scale))),
        fill=(255, 255, 255, 248),
        outline=accent,
        width=max(4, int(round(6 * bubble_scale))),
    )

    win = fp._window_indices(timing, active_index)
    labels = [str(timing[j]["display"]) for j in win]
    usable_width = int((box[2] - box[0]) - 50 * bubble_scale)
    _font, base_size, widths, gap = fp._fit_window_font(d, labels, usable_width)

    # No POP individual: todos usam o mesmo tamanho-base. A palavra falada só recebe destaque.
    total = sum(widths) + gap * max(0, len(widths) - 1)
    cursor = box[0] + ((box[2] - box[0]) - total) / 2.0
    centers: list[float] = []
    for width in widths:
        centers.append(cursor + width / 2.0)
        cursor += width + gap

    for slot, word_idx in enumerate(win):
        label = str(timing[word_idx]["display"])
        is_active = word_idx == active_index
        font = ImageFont.truetype(FONT_BOLD, base_size)
        tb = d.textbbox((0, 0), label, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        x = centers[slot] - tw / 2.0
        y = box[1] + ((box[3] - box[1]) - th) / 2.0 - tb[1]
        fill = (10, 10, 10, 255) if is_active else (100, 100, 100, 255)
        d.text((x, y), label, font=font, fill=fill)

    return im


def qa_simple(asr_ratio: float, alignment_ratio: float, timing: list[dict]) -> None:
    _original_qa_three_word_window(asr_ratio, alignment_ratio, timing)
    p = POST / "qa.json"
    qa = json.loads(p.read_text(encoding="utf-8"))
    qa.update({
        "revision": "card-v6.5-SIMPLE-HIGHLIGHT-BUBBLE-POP",
        "template_status": "FINAL CANDIDATE - simplified per user feedback",
        "active_word_effect": "highlight only; no word scaling",
        "bubble_animation": "whole bubble POP 86%-108%-100% once at block/phrase entrance",
        "per_word_pop": False,
        "previous_signoff_restored": PREVIOUS_SIGNOFF,
    })
    p.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    # fp.generate_signoff_with_tail chama este gerador e depois mantém a cauda anti-corte.
    fp._original_generate_signoff = generate_previous_signoff
    fp.build_three_word_timing = build_simple_timing
    fp.draw_three_word_bubble = draw_simple_bubble
    fp.qa_three_word_window = qa_simple
    fp.main()


if __name__ == "__main__":
    main()
