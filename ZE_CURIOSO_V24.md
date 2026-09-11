# Zé Curioso Studio V24

Protótipo separado da linha Shopee. O cliente local conversa com o FCC em `127.0.0.1:8082`, gera um job de curiosidade estruturado e dispara o render no GitHub Actions.

## Fluxo

`tema -> FCC local -> JSON estruturado -> GitHub Actions -> TTS + render vertical -> QA -> download do MP4`

## Teste local

Com o FCC já iniciado e a mesma configuração GitHub usada pelo projeto anterior:

```bash
uv run --python 3.14 python ze_curioso_v24.py "Por que os gatos seguem a gente até o banheiro?"
```

Para testar apenas a geração do roteiro pelo FCC, sem render:

```bash
uv run --python 3.14 python ze_curioso_v24.py "Por que os gatos seguem a gente até o banheiro?" --somente-json
```

Os resultados ficam em `saida_ze_curioso/<titulo>/`.

## Backend

- `cloud/render_ze_curioso_v24.py`: renderer vertical 1080x1920 com mascote procedural, TTS e legendas.
- `qa_ze_curioso.py`: QA técnico dedicado.
- `.github/workflows/ze_curioso_v24.yml`: workflow de render/teste.
- `examples/ze_curioso_demo.json`: job de demonstração usado no CI.

## Segurança de desenvolvimento

A branch `ze-curioso-v24` é separada da `main`; o fluxo Shopee antigo não é substituído por este protótipo.
