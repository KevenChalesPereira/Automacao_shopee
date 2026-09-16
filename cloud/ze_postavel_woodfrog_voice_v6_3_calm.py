from __future__ import annotations

import json

import ze_postavel_woodfrog_voice_v6_2_final as v62

v6 = v62.v6
cont = v62.cont
v4 = v62.v4

# V6.3: preserva identidade/timbre do take 02, mas remove a direcao antiga de
# "surpresa constante". Queremos uma explicacao natural, calma e cotidiana.
v6.VOICE_CONTROL = (
    "Brazilian Portuguese male voice. Keep the exact same vocal identity, timbre and age impression as the reference voice. "
    "Speak as if calmly explaining an interesting fact to one friend sitting beside you. "
    "Use a relaxed, ordinary conversational delivery with low-to-medium energy. "
    "Do NOT sound urgent, alarmed, dangerous, suspenseful, dramatic, promotional, theatrical, or like a radio/TV announcer. "
    "Do NOT keep a constant 'attention' expression across the whole script. "
    "Most words should be neutral and unaccented; emphasize only one occasional key word when the meaning genuinely calls for it. "
    "Let every sentence resolve naturally: slightly release the vocal tension near the end, usually with a gentle downward or neutral cadence, then a small human pause. "
    "Do not lift or punch the ending of every sentence. Do not smile through every phrase. "
    "Allow subtle phrase-to-phrase variation like normal speech, while keeping the same speaker identity and microphone distance. "
    "The first sentence should begin naturally, not as a hook shouted at the viewer. "
    "Read the entire script as one continuous take, connected and unforced, with clean articulation and complete word endings. "
    "Avoid raspiness, vocal fry, hoarseness, tremolo, wavering pitch, breathy instability, swallowed syllables, clicks, or abrupt changes of intensity. "
    "Target roughly 155 to 168 words per minute without sounding deliberately slow. "
    "The final words are exactly: 'Zé Curioso: parece mentira, mas é real.' Say them calmly and simply, like a familiar sign-off, not a slogan or dramatic punchline."
)


def qa_v63(asr_ratio: float, alignment_ratio: float, timing: list[dict]) -> None:
    v6.qa_final(asr_ratio, alignment_ratio, timing)
    qa_path = cont.POST / "qa.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    qa.update({
        "revision": "card-v6.3-calm-explanatory-prosody",
        "prosody_direction": "calm ordinary explanatory conversation",
        "constant_alert_expression": False,
        "sentence_endings": "relaxed neutral/downward resolution with small natural pauses",
        "emphasis_policy": "sparse semantic emphasis; most words neutral",
        "voice_reference": "VoxCPM2 take 02 original",
    })
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    cont.words_from_text = v4.words_from_text
    cont.align_tokens = v4.align_tokens
    cont.generate_continuous_narration = v62.generate_final_single_take
    cont._qa_original = cont.qa_and_copy
    cont.qa_and_copy = qa_v63
    cont.main()
