from __future__ import annotations

import json
import shutil
from pathlib import Path

import ze_postavel_woodfrog_v6_4_carrierfix as carrier

fs = carrier.fs
v64 = fs.v64
v4 = fs.v4
cont = fs.cont
POST = cont.POST
AUDIO = cont.AUDIO

# Ajuste final aprovado pelo feedback:
# - não mexe no timbre/roteiro/layout;
# - adiciona cauda real depois do bordão para não cortar a última sílaba;
# - mantém uma palavra por vez, mas com tempo mínimo de leitura;
# - POP menos agressivo e com sustentação visível.
TAIL_SECONDS = 0.70
LAST_WORD_HOLD_SECONDS = 0.36
MIN_WORD_DISPLAY_SECONDS = 0.28
POP_IN_SECONDS = 0.07
POP_OVERSHOOT_SECONDS = 0.09

_original_generate_signoff = carrier.generate_signoff_carrier
_original_qa_v64 = v64.qa_v64


def generate_signoff_with_tail():
    final, words, ratio, transcript, metrics = _original_generate_signoff()

    original_duration = v4.probe_duration(final)
    padded = AUDIO / "signoff_final_padded.wav"
    # Acrescenta silêncio DEPOIS da assinatura. Não corta nem altera a fala.
    v4.run([
        "ffmpeg", "-y",
        "-i", str(final),
        "-f", "lavfi", "-t", f"{TAIL_SECONDS:.3f}",
        "-i", "anullsrc=r=48000:cl=mono",
        "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[out]",
        "-map", "[out]",
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le",
        str(padded),
    ])
    shutil.move(str(padded), str(final))

    metrics = {
        **metrics,
        "tail_padding_seconds": TAIL_SECONDS,
        "duration_before_tail": round(original_duration, 3),
        "duration_after_tail": round(v4.probe_duration(final), 3),
    }

    qa_path = POST / "signoff_qa.json"
    if qa_path.exists():
        data = json.loads(qa_path.read_text(encoding="utf-8"))
        data["selected"] = metrics
        data["final_tail_seconds"] = TAIL_SECONDS
        qa_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return final, words, ratio, transcript, metrics


def _reduce_to_span(durations: list[float], minimum: float, target_span: float) -> list[float]:
    out = [max(minimum, float(x)) for x in durations]
    excess = sum(out) - target_span
    # Como target_span >= n*minimum no roteiro atual, sempre existe folga.
    # Reduz primeiro apenas a parte acima do mínimo, proporcionalmente.
    for _ in range(12):
        if excess <= 1e-8:
            break
        reducible = [max(0.0, x - minimum) for x in out]
        total = sum(reducible)
        if total <= 1e-9:
            break
        removed = 0.0
        for i, room in enumerate(reducible):
            if room <= 0:
                continue
            cut = min(room, excess * (room / total))
            out[i] -= cut
            removed += cut
        excess -= removed
    return out


def build_readable_word_timing(words: list[dict]):
    expected_rows = v64.expected_word_rows()
    expected = [x["norm"] for x in expected_rows]
    actual = [x["norm"] for x in words]
    mapping, ratio = v4.align_tokens(expected, actual)
    duration = cont.probe_duration(AUDIO / "narration_continuous.wav")

    starts: list[float | None] = [None] * len(expected_rows)
    ends: list[float | None] = [None] * len(expected_rows)
    for i, actual_idx in enumerate(mapping):
        if actual_idx is not None and 0 <= actual_idx < len(words):
            starts[i] = float(words[actual_idx]["start"])
            ends[i] = float(words[actual_idx]["end"])

    # Mesma interpolação segura usada na V6.4 para palavras raramente perdidas pelo ASR.
    i = 0
    while i < len(expected_rows):
        if starts[i] is not None:
            i += 1
            continue
        a = i
        while i < len(expected_rows) and starts[i] is None:
            i += 1
        b = i
        left = ends[a - 1] if a > 0 and ends[a - 1] is not None else 0.0
        right = starts[b] if b < len(expected_rows) and starts[b] is not None else duration
        left = float(left)
        right = max(left + 0.08 * (b - a), float(right))
        step = (right - left) / max(1, b - a)
        for k in range(a, b):
            starts[k] = left + step * (k - a)
            ends[k] = left + step * (k - a + 1)

    if not starts:
        return [], ratio

    spoken_starts = [float(x or 0.0) for x in starts]
    spoken_ends = [float(x or spoken_starts[i] + 0.12) for i, x in enumerate(ends)]

    first_start = max(0.0, spoken_starts[0] - 0.02)
    # "real" permanece um pouco depois de falado; depois há tela limpa antes do fim.
    active_end = min(
        duration - 0.30,
        spoken_ends[-1] + LAST_WORD_HOLD_SECONDS,
    )
    active_end = max(active_end, first_start + len(expected_rows) * MIN_WORD_DISPLAY_SECONDS)
    active_end = min(active_end, duration - 0.18)

    natural_slots: list[float] = []
    for idx, start in enumerate(spoken_starts):
        if idx + 1 < len(spoken_starts):
            natural_slots.append(max(0.03, spoken_starts[idx + 1] - start))
        else:
            natural_slots.append(max(0.03, active_end - start))

    target_span = max(0.01, active_end - spoken_starts[0])
    min_display = min(
        MIN_WORD_DISPLAY_SECONDS,
        max(0.20, target_span / max(1, len(expected_rows)) * 0.92),
    )
    slots = _reduce_to_span(natural_slots, min_display, target_span)

    # Corrige eventual resíduo numérico no último slot.
    residue = target_span - sum(slots)
    slots[-1] = max(min_display, slots[-1] + residue)

    timing: list[dict] = []
    cursor = spoken_starts[0]
    for idx, row in enumerate(expected_rows):
        start = max(0.0, cursor)
        end = min(duration, start + slots[idx])
        cursor = end
        timing.append({
            **row,
            "word_index": idx + 1,
            "start": round(start, 4),
            "end": round(end, 4),
            "seconds": round(end - start, 4),
            "spoken_start": round(spoken_starts[idx], 4),
            "spoken_end": round(spoken_ends[idx], 4),
            "display_vs_speech_start_drift": round(start - spoken_starts[idx], 4),
            "mapped_asr_index": mapping[idx],
            "sync_method": "readable paced word-by-word schedule derived from faster-whisper timestamps",
            "caption_location": "small Ze speech bubble only",
            "animation": "soft pop 92%-106%-100%, then hold",
            "minimum_display_seconds": round(min_display, 3),
        })

    drift = [abs(float(x["display_vs_speech_start_drift"])) for x in timing]
    payload = {
        "alignment_ratio": ratio,
        "words": timing,
        "readability_mode": True,
        "minimum_display_seconds": round(min_display, 3),
        "pop_profile": "92%-106%-100% then hold",
        "max_start_drift_seconds": round(max(drift) if drift else 0.0, 4),
        "mean_start_drift_seconds": round(sum(drift) / max(1, len(drift)), 4),
        "final_audio_tail_seconds": TAIL_SECONDS,
    }
    (POST / "word_bubble_timing.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return timing, ratio


def soft_pop_scale(item: dict, t: float):
    elapsed = max(0.0, t - float(item["start"]))
    if elapsed < POP_IN_SECONDS:
        return 0.92, 1
    if elapsed < POP_IN_SECONDS + POP_OVERSHOOT_SECONDS:
        return 1.06, 2
    return 1.00, 3


def qa_finalpolish(asr_ratio: float, alignment_ratio: float, timing: list[dict]) -> None:
    _original_qa_v64(asr_ratio, alignment_ratio, timing)
    qa_path = POST / "qa.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    wt = json.loads((POST / "word_bubble_timing.json").read_text(encoding="utf-8"))
    qa.update({
        "revision": "card-v6.4-FINAL-readable-word-pop-tail",
        "template_status": "FINAL CANDIDATE",
        "bubble_animation": "soft POP 92%-106%-100%, then hold",
        "word_minimum_display_seconds": wt.get("minimum_display_seconds"),
        "word_mean_start_drift_seconds": wt.get("mean_start_drift_seconds"),
        "word_max_start_drift_seconds": wt.get("max_start_drift_seconds"),
        "final_audio_tail_seconds": TAIL_SECONDS,
        "last_word_hold_seconds": LAST_WORD_HOLD_SECONDS,
        "final_cutoff_protection": True,
    })
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    carrier.generate_signoff_carrier = generate_signoff_with_tail
    v64.build_word_timing = build_readable_word_timing
    v64._pop_scale = soft_pop_scale
    v64.qa_v64 = qa_finalpolish
    carrier.main()


if __name__ == "__main__":
    main()
