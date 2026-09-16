from __future__ import annotations

import importlib
import json

import ze_postavel_woodfrog_card_sync as card

# O módulo de layout importa e configura o renderer base. Recarregar aqui nos dá
# uma cópia limpa das funções estáveis e evita qualquer monkeypatch recursivo.
base = importlib.reload(card.base)

base.SCRIPT[-1] = (
    "Parece ficção, mas é sobrevivência real. "
    "A natureza consegue ser mais estranha que qualquer filme. "
    "Zé Curioso: parece mentira, mas é real."
)

original_qa_and_copy = base.qa_and_copy


def qa_and_copy_card() -> None:
    original_qa_and_copy()

    qa_path = base.POST / "qa.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    qa.update(
        {
            "layout_revision": "card-frame-v1",
            "speech_bubbles": "synced-by-narration-block",
            "catchphrase_spoken": "Zé Curioso: parece mentira, mas é real.",
            "full_screen_photo_removed": True,
            "photo_mode": "framed-card-contain",
        }
    )
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")

    copy_path = base.POST / "copy_postagem.txt"
    copy_text = copy_path.read_text(encoding="utf-8")
    copy_text += (
        "\nIdentidade do formato: card central + Zé Curioso + balões sincronizados.\n"
        "Bordão: Zé Curioso: parece mentira, mas é real.\n"
    )
    copy_path.write_text(copy_text, encoding="utf-8")


base.build_scenes = card.build_scenes_card
base.render_video = card.render_video_synced
base.qa_and_copy = qa_and_copy_card

if __name__ == "__main__":
    base.main()
