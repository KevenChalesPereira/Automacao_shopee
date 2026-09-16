# Zé Curioso Studio — caminho depois do template final

## Decisão de arquitetura

**Primeiro: script local leve. Depois: app/GUI.**

O computador do usuário NÃO deve renderizar vídeo. O Linux Mint só funciona como controle remoto. GitHub Actions continua fazendo TTS, alinhamento, composição e FFmpeg na nuvem.

Isso permite que uma futura interface gráfica use exatamente o mesmo pipeline sem reescrever a automação.

## Fluxo-alvo

```text
[PC / ze_studio.py]
        |
        | tema escrito OU AUTO
        v
[request JSON]
        |
        v
[GitHub Actions]
        |
        +--> seleção/pesquisa do tema
        +--> verificação factual
        +--> roteiro Zé Curioso
        +--> busca/seleção de imagens
        +--> voz VoxCPM2 take 02
        +--> ASR + timestamps palavra a palavra
        +--> card + Zé + balão POP
        +--> QA automático
        v
[artifact MP4 + capa + copy + QA]
        |
        v
[script baixa para o PC]
```

## Etapas

### Etapa A — AGORA
Fechar o template audiovisual V6.4 e congelá-lo.

### Etapa B — CLI funcional
Comandos planejados:

```bash
python ze_studio.py tema "animal que sobrevive congelado"
python ze_studio.py auto
python ze_studio.py status
python ze_studio.py baixar
```

`tema`: usuário decide o assunto.

`auto`: pipeline usa `prompts/ze_curioso_master.md`, levanta candidatos, verifica fatos e escolhe o melhor assunto editorial.

`status`: mostra o último workflow.

`baixar`: baixa MP4/capa/copy do artifact mais recente aprovado.

### Etapa C — motor editorial dinâmico
Entrada:

```json
{
  "mode": "auto|manual",
  "theme": null,
  "language": "pt-BR",
  "template": "ze-v6.4-locked"
}
```

Saída editorial deve seguir o JSON definido no prompt mestre.

Nunca renderizar um roteiro antes de:
1. confirmar o fato central;
2. possuir imagens adequadas;
3. travar o roteiro;
4. definir palavras críticas para QA.

### Etapa D — App
Somente depois que o CLI estiver confiável.

Interface pode ser feita com uma camada simples (por exemplo, Tauri/Electron leve, Python GUI ou web local), mas ela só chamará os mesmos comandos do `ze_studio.py`.

Tela mínima:
- campo “Tema”;
- botão “Escolher assunto automaticamente”;
- botão “Gerar vídeo”;
- status do workflow;
- preview do MP4;
- botão para abrir pasta do resultado.

## Regra de ouro

O template audiovisual travado não muda quando o tema muda. Conteúdo é variável; identidade visual, voz, balão, QA e assinatura são infraestrutura.
