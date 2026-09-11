#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Launcher V24.2: usa a infraestrutura estável do V24 com roteiro mais curto."""

import ze_curioso_v24 as core


def fcc_generate_topic_v24_2(tema: str, timeout=120):
    prompt = f"""
Você é o roteirista do Zé Curioso Studio V24.2.
Crie um vídeo vertical curto em português do Brasil sobre o tema abaixo.

PERSONAGEM E TOM
- Zé Curioso é um apresentador adulto, simpático e curioso.
- Pode usar naturalmente expressões como "Oxente...", "Rapaz...", "Mas pera aí..." e "Agora olha isso...".
- Não caricature sotaque nem escreva palavras propositalmente erradas.
- O texto deve soar natural em voz TTS brasileira.

REGRAS DE CONTEÚDO
- Priorize fatos amplamente aceitos e explicações simples.
- Não invente números, pesquisas, instituições ou estatísticas.
- Não faça diagnóstico médico, promessa de saúde ou afirmação extraordinária.
- Se o tema depender de informação atual ou controversa, marque precisa_verificacao=true.
- Hook direto já na primeira frase, sem clickbait falso.
- Roteiro entre 60 e 90 palavras, mirando aproximadamente 25 a 35 segundos.
- Exatamente 5 cenas.
- Cada cena deve ter título curto e texto de no máximo 12 palavras.
- A cena 1 apresenta a pergunta; cenas 2 a 4 desenvolvem; cena 5 fecha a ideia.
- O CTA aparece só no final e convida a seguir o Zé Curioso.

TEMA:
{tema}

Responda SOMENTE JSON válido neste formato:
{{
  "tema": "...",
  "titulo": "...",
  "hook": "...",
  "roteiro": "...",
  "voz": "pt-BR-AntonioNeural",
  "cta": "Segue o Zé Curioso para mais curiosidades rápidas.",
  "precisa_verificacao": false,
  "cenas": [
    {{"titulo":"...","texto":"..."}},
    {{"titulo":"...","texto":"..."}},
    {{"titulo":"...","texto":"..."}},
    {{"titulo":"...","texto":"..."}},
    {{"titulo":"...","texto":"..."}}
  ]
}}
""".strip()

    body = {
        "model": core.FCC_MODEL,
        "max_tokens": 3000,
        "temperature": 0.22,
        "stream": False,
        "messages": [{"role": "user", "content": prompt}],
    }
    core.emit("[>] Zé Curioso V24.2: pedindo roteiro curto ao FCC...")
    status, data = core.http_json(
        core.FCC_URL,
        method="POST",
        data=body,
        headers={
            "x-api-key": core.FCC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        timeout=timeout,
    )
    if status != 200:
        raise RuntimeError(f"FCC retornou HTTP {status}: {str(data)[:800]}")

    text_parts = []
    for block in data.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(str(block.get("text") or ""))
    result = core.extract_json_object("\n".join(text_parts))
    if not result:
        raise RuntimeError("FCC não retornou JSON utilizável.")

    job = core.validate_job(result, tema)
    job["versao"] = "24.2"
    words = len(core.clean(job.get("roteiro")).split())
    if words > 100:
        raise RuntimeError(f"FCC retornou roteiro longo demais para V24.2: {words} palavras.")
    return job


core.fcc_generate_topic = fcc_generate_topic_v24_2

if __name__ == "__main__":
    core.main()
