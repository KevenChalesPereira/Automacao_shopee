from __future__ import annotations

import time

import ze_postavel_woodfrog_voice_v6_single_take as v6


# A V4 tinha uma assinatura antiga ("Eu sou o Zé Curioso...").
# Para a versão final usamos exatamente o texto exibido/aprovado no vídeo.
v6.FULL_SPEAK_TEXT = v6.cont.FULL_NARRATION

# Mantém os tokens mais sensíveis explicitamente obrigatórios.
v6.CRITICAL.update({
    "meses", "descongela", "glicose", "primavera",
    "curioso", "mentira", "real",
})

# O Space público do VoxCPM às vezes responde "Queue is full". Isso não é
# reprovação de áudio e não deve abortar o render. Cada tomada tem retries com
# backoff; só uma tomada realmente gerada entra no QA.
OriginalClient = v6.cont.base.Client


class QueueResilientClient:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.inner = OriginalClient(*args, **kwargs)

    def _reset(self):
        self.inner = OriginalClient(*self.args, **self.kwargs)

    def predict(self, *args, **kwargs):
        last = None
        for retry in range(1, 9):
            try:
                return self.inner.predict(*args, **kwargs)
            except Exception as exc:
                last = exc
                msg = f"{type(exc).__name__}: {exc}"
                transient = any(token in msg.lower() for token in (
                    "queue is full", "queue", "timeout", "timed out",
                    "connection", "502", "503", "504", "rate limit",
                ))
                if not transient or retry >= 8:
                    raise
                delay = min(35, 7 + retry * 4)
                print(f"VOXCPM_TRANSIENT retry={retry}/8 wait={delay}s error={msg}", flush=True)
                time.sleep(delay)
                try:
                    self._reset()
                except Exception as reset_exc:
                    print(f"VOXCPM_CLIENT_RESET_WARN {reset_exc}", flush=True)
        raise last


v6.cont.base.Client = QueueResilientClient

if __name__ == "__main__":
    # Mesmo encadeamento da V6, mas com texto final correto e fila resiliente.
    v6.cont.words_from_text = v6.v4.words_from_text
    v6.cont.align_tokens = v6.v4.align_tokens
    v6.cont.generate_continuous_narration = v6.generate_single_take
    v6.cont._qa_original = v6.cont.qa_and_copy
    v6.cont.qa_and_copy = v6.qa_final
    v6.cont.main()
