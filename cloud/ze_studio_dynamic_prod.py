from __future__ import annotations

import re

import ze_studio_dynamic as dyn

# O gerador de voz aprovado foi calibrado para um corpo de narração com cerca de
# 25-32 s. Estes complementos mantêm os episódios curados nessa faixa sem
# alterar o template visual, POP ou identidade vocal.
EXPANSIONS = {
    "wood-frog": [
        "Durante esse processo, parte da água do corpo congela fora das células.",
        "Os açúcares ajudam a limitar os danos provocados pelo gelo nos tecidos.",
    ],
    "axolotl": [
        "O axolote continua aquático na fase adulta e mantém brânquias externas.",
        "A regeneração reconstrói estruturas organizadas, em vez de apenas fechar a ferida com uma cicatriz.",
    ],
    "tardigrade": [
        "Eles são animais microscópicos encontrados em ambientes úmidos, como musgos e líquens.",
        "Quando a água volta, muitos conseguem sair do estado dormente e retomar a atividade.",
    ],
    "bombardier-beetle": [
        "O spray pode ser direcionado e é liberado em pulsos muito rápidos.",
        "A reação acontece dentro de uma estrutura resistente no abdômen do besouro.",
        "Isso ajuda o inseto a evitar danos graves com a própria reação.",
    ],
    "immortal-jellyfish": [
        "Esse retorno acontece por uma reorganização das células do animal.",
        "Depois, o pólipo pode formar novas medusas e reiniciar o ciclo.",
    ],
}

CRITICAL = {
    "wood-frog": ["congelar", "coracao", "glicose", "descongela"],
    "axolotl": ["axolote", "regenerar", "musculos", "cicatriz"],
    "tardigrade": ["tardigrados", "metabolismo", "vacuo", "espaco"],
    "bombardier-beetle": ["besouro", "quimicas", "reacao", "jato"],
    "immortal-jellyfish": ["reverter", "polipo", "medusas", "imortal"],
}

_original_choose = dyn.choose_episode
_original_critical = dyn.critical_words


def word_count(episode: dict) -> int:
    body = " ".join(" ".join(scene) for scene in episode["blocks"][:-1])
    return len(re.findall(r"[A-Za-zÀ-ÿ0-9'-]+", body))


def choose_episode(request: dict) -> dict:
    episode = _original_choose(request)
    extras = list(EXPANSIONS.get(episode.get("id"), []))
    # Insere antes do encerramento. Não duplica o bordão e preserva 5 cenas.
    while word_count(episode) < 78 and extras:
        episode["blocks"][3].append(extras.pop(0))
    episode["body_word_count"] = word_count(episode)
    return episode


def critical_words(episode: dict) -> list[str]:
    fixed = CRITICAL.get(episode.get("id"))
    if fixed:
        return fixed
    # Fallback enciclopédico: no máximo quatro palavras críticas para não
    # reprovar uma tomada boa por variação pequena do ASR.
    return _original_critical(episode)[:4]


dyn.choose_episode = choose_episode
dyn.critical_words = critical_words

if __name__ == "__main__":
    dyn.main()
