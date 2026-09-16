from __future__ import annotations

import ze_postavel_woodfrog_v6_4_locked as v64

# O único problema restante do render anterior foi o nome da marca: o ASR ouviu
# "Isso é curioso". Como "Zé" não aparece em nenhum outro ponto do roteiro,
# torná-lo palavra crítica garante que a tomada inteira seja rejeitada se o nome
# da marca não sair claramente reconhecível.
v64.v6.CRITICAL.add("ze")

# Mantém exatamente as mesmas palavras, mas dá uma fronteira prosódica mais
# clara antes do slogan. O texto exibido nos balões continua vindo de
# FINAL_BLOCKS e, portanto, continua "Zé Curioso: parece mentira, mas é real.".
v64.v62.FINAL_TEXT = v64.v62.FINAL_TEXT.replace(
    "Zé Curioso: parece mentira, mas é real.",
    "Zé Curioso. Parece mentira, mas é real.",
)

v64.v6.VOICE_CONTROL += (
    " In the final signature, pronounce the brand name literally and distinctly as the two words 'Zé Curioso'."
    " Make the first word unmistakably 'Zé'. Never turn the brand name into 'isso é curioso', 'é curioso', or 'José Curioso'."
    " Give a short natural boundary after 'Zé Curioso', then say 'parece mentira, mas é real' with slightly more presence than the body, still calm and conversational."
)


def main() -> None:
    v64.cont.words_from_text = v64.v4.words_from_text
    v64.cont.align_tokens = v64.v4.align_tokens
    v64.cont.generate_continuous_narration = v64.generate_v64
    v64.cont.render_video = v64.render_word_pop_video
    v64.cont._qa_original = v64.cont.qa_and_copy
    v64.cont.qa_and_copy = v64.qa_v64
    v64.cont.main()


if __name__ == "__main__":
    main()
