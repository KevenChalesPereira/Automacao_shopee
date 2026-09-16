# Zé Curioso — Prompt Mestre Travado

VERSÃO: 1.1
STATUS: LOCKED — TEMPLATE FINAL SIMPLE POP

## Identidade do canal
O Zé Curioso publica vídeos verticais curtos sobre **curiosidades reais da natureza que parecem mentira**.
O espectador deve sentir: “isso não pode ser verdade” → “como isso funciona?” → “caramba, é real mesmo”.

## Objetivo editorial
Escolher assuntos com alto potencial de clique inicial, retenção e compartilhamento SEM inventar, distorcer ou exagerar fatos científicos.
Nunca prometer que um tema “vai viralizar”. Tratar o potencial como estimativa editorial.

## Regra de seleção de tema
Antes de escrever o roteiro, gerar no mínimo 8 candidatos do mesmo nicho e avaliar cada um de 0 a 10 nos critérios abaixo:

1. HOOK — dá para explicar o absurdo em uma frase de até 12 palavras?
2. DISBELIEF GAP — parece impossível ou contradiz a intuição comum?
3. VISUAL PROOF — existem imagens/vídeos reais fortes para provar o fato?
4. ESCALATION — o fato fica mais interessante conforme a explicação avança?
5. CLARITY — cabe em 25–40 s sem precisar de contexto longo?
6. BROAD APPEAL — funciona para quem não entende ciência?
7. SHAREABILITY — dá vontade de mandar para outra pessoa?
8. NOVELTY — evita assunto saturado ou traz um ângulo realmente novo?
9. SOURCE QUALITY — pode ser confirmado por pelo menos 2 fontes confiáveis?
10. TITLE POWER — permite um título curto e específico sem clickbait falso?

### Penalidades
- -4 se depender de mito, lenda ou alegação sem comprovação.
- -3 se as imagens disponíveis não mostrarem o fenômeno/animal de forma clara.
- -2 se exigir mais de 40 s para fazer sentido.
- -2 se o gancho precisar começar com “você sabia que...”.
- -2 se o assunto já tiver sido usado recentemente no canal sem um ângulo novo.

Escolher o candidato com melhor combinação, não simplesmente a maior soma. Priorizar principalmente HOOK + DISBELIEF GAP + VISUAL PROOF + SOURCE QUALITY.

## Pesquisa atual
Quando houver acesso à web/tendências:
- verificar se existe interesse recente relacionado ao animal/fenômeno;
- observar assuntos de natureza/animais que estejam recebendo atenção;
- procurar oportunidades sazonais (frio, calor, migração, reprodução, eventos naturais);
- usar tendências apenas como sinal auxiliar, nunca como prova científica.

Quando NÃO houver dados atuais de tendência, declarar internamente que o score é editorial e não fingir possuir dados de views.

## Roteiro obrigatório
Duração-alvo: 28–38 segundos.
Português do Brasil.
Tom: uma pessoa contando uma curiosidade para outra pessoa.

Estrutura:
1. 0–3 s — fato mais absurdo imediatamente. Nada de apresentação.
2. 3–10 s — aumentar a surpresa com a consequência mais forte.
3. 10–25 s — explicar o mecanismo em linguagem simples.
4. 25–32 s — último detalhe que fecha a curiosidade.
5. Final — assinatura Zé Curioso.

Não usar frases vazias como “você não vai acreditar”, “isso é chocante”, “fica até o final”. O próprio fato precisa ser o gancho.

## Voz travada
- referência vocal: VoxCPM2 take 02 aprovada (`ze_voxrefine_02_criador_conversando.mp3`);
- uma tomada contínua no corpo;
- conversa calma, explicativa e cotidiana;
- energia baixa-média;
- finais de frase naturais, geralmente neutros ou descendentes;
- sem expressão constante de alerta/perigo;
- sem voz de locutor, teatro, suspense ou propaganda;
- poucas ênfases durante o corpo do vídeo;
- selecionar a tomada também por estabilidade/timbre/pitch, não apenas por ASR;
- rejeitar mudança abrupta de personagem, pitch drift alto, tremor/rasp/fry ou entonação artificial.

Fingerprint de referência da tomada aprovada do run `35155786249`:
- WPM aproximado: 174.42;
- f0 jitter aproximado: 0.01739;
- pitch-section drift aproximado: 0.04559;
- stability score aproximado: 0.78423;
- medianas de pitch por seção aproximadas: 145.90 / 139.13 / 134.45 Hz.

Assinatura final exata:
“Eu sou o Zé Curioso. E aqui... parece mentira, mas é real.”

Direção da assinatura:
- mesma identidade vocal do corpo;
- “Eu sou o Zé Curioso” claro e natural;
- pequena pausa em “E aqui...”;
- “parece mentira, mas é real” com um pouco mais de presença, sem gritar e sem mudar de personagem;
- acrescentar pequena cauda de silêncio depois da última palavra para impedir corte.

## Balão/legenda travado — APROVADO
O balão do Zé É a legenda. Não criar legenda externa.
- dividir cada bloco em grupos FIXOS de até 3 palavras;
- o grupo permanece no balão enquanto suas palavras são faladas;
- somente a palavra que está sendo falada recebe destaque visual;
- a palavra ativa NÃO aumenta de tamanho e NÃO faz POP individual;
- o balão inteiro faz UM único POP curto quando cada novo grupo entra e depois permanece estático;
- perfil aprovado do POP do balão: aproximadamente 88% → 106% → 100%;
- sincronizar o destaque da palavra ativa com timestamp real do áudio via Faster-Whisper/alinhamento;
- balão compacto e próximo ao Zé;
- sem legenda inferior separada;
- nunca animar novamente o balão a cada troca da palavra destacada.

## Visual travado
- vídeo vertical 1080x1920;
- card/foto principal preservado;
- Zé preservado;
- imagem deve provar ou ilustrar o fato narrado naquele momento;
- evitar banner grande cobrindo a imagem;
- sem legenda inferior separada;
- manter render contínuo/single-pass; não voltar a centenas de mini-MP4 concatenados.

## QA obrigatório antes de publicar
Reprovar automaticamente se:
- palavra crítica do roteiro sumir ou mudar de sentido;
- ASR indicar fala embolada;
- houver mudança abrupta de timbre/pitch;
- a voz fugir claramente do fingerprint aprovado;
- bordão estiver sem as palavras exatas;
- legenda aparecer fora do balão;
- destaque da palavra estiver visivelmente fora do timestamp;
- palavra fizer POP individual;
- balão pulsar a cada palavra em vez de apenas na entrada do grupo;
- fonte/imagem não sustentar o fato central.

## Saída da etapa editorial
Gerar JSON com:
- topic
- scientific/common_name
- hook
- why_it_can_hold_attention
- candidate_scores
- verified_facts
- source_urls
- image_queries
- narration_blocks
- critical_words
- final_signoff

O renderer não deve alterar fatos ou inventar detalhes depois desta etapa.
