# Design — Dashboard web v1 (leitura ao vivo + zerar)

**Data:** 2026-06-19
**Status:** Aprovado para implementação
**Fase:** 1 de 3 (1 dashboard → 2 comissionador genérico → 3 perfis de device)

## 1. Objetivo

Expor a leitura do encoder, que já funciona no Pi3, num **dashboard web em tempo
real**: ângulo, `raw`, bytes, estado da conexão, diagnóstico DP e taxa de
atualização. Inclui **um** controle: "zerar aqui" (ajusta o `offset` por software
ao vivo, só na sessão). É a fundação para as fases 2 e 3.

## 2. Escopo

**Dentro:** backend que roda o mestre PROFIBUS continuamente e publica o último
snapshot; transporte WebSocket; frontend Preact (sem build); botão zerar/desfazer.

**Fora (fases futuras):** persistir o zero; varredura de barramento; upload/gestão
de GSD; parametrizar qualquer escravo; perfis de device declarativos; controles de
baud/endereço pela UI. O teto de baud do pyprofibus continua valendo e é
documentado, não "resolvido".

## 3. Arquitetura (em camadas, SOLID)

```
 frontend Preact ──(WebSocket /ws)──▶ server.py (Flask + flask-sock)
                                          │ depende de
                                          ▼
                                     EncoderPoller            (serviço de aplicação)
                                          │ depende de
                                          ▼
                                   ReadingSource (Protocol)   (abstração)
                                       ▲            ▲
                            Amg11Master(prod)   FakeSource(test)
                                       │
                              profibus_amg11 (decode/config/pyprofibus)  (domínio)
```

A biblioteca `profibus_amg11/` **não muda**, exceto um método pequeno
`Amg11Master.set_offset(int)` que reusa o `decode` existente (sem duplicar a
matemática — DRY) e a aderência ao `ReadingSource`.

### Responsabilidade de cada unidade (SRP)
- **`profibus_amg11/source.py` → `ReadingSource` (Protocol):** `poll() ->
  EncoderReading | None`, `set_offset(int) -> None`, `close() -> None`. **DIP:** o
  poller depende disto, não do `Amg11Master` concreto.
- **`profibus_amg11/master.py` → `Amg11Master`:** implementa `ReadingSource`
  (ganha `set_offset`). Continua dono da serial e da máquina de estados DP.
- **`web/poller.py` → `EncoderPoller`:** mantém um `Snapshot` vivo e aplica
  comandos. Dono da thread de fundo e do `ReadingSource`.
- **`web/snapshot.py` → `Snapshot` + `snapshot_to_dict`:** dataclass imutável do
  estado publicado + serialização pura (testável isolada).
- **`web/server.py`:** Flask + flask-sock; serve estáticos, faz broadcast do
  snapshot e recebe comandos. **Não conhece pyprofibus.**
- **`web/static/`:** frontend Preact vendorizado (ver seção 7).
- **`serve.py`:** entrypoint (`python serve.py [--host --port --sim --conf --encoder]`).

### Estrutura de arquivos
```
profibus_amg11/
  source.py          # ReadingSource (Protocol)   [novo]
  master.py          # + set_offset()             [edição mínima]
  (config.py, encoder.py inalterados)
web/
  __init__.py
  poller.py          # EncoderPoller (thread + snapshot + comandos)
  snapshot.py        # Snapshot (dataclass) + snapshot_to_dict (puro)
  server.py          # Flask + flask-sock (/ws, estáticos)
  static/
    index.html
    app.js           # dashboard Preact (htm)
    styles.css       # tokens + componentes (CSS autoral)
    vendor/          # preact.module.js, htm.module.js, fontes .woff2
serve.py
tests/
  test_source_fake.py   # FakeSource satisfaz o contrato
  test_poller.py        # snapshot, zero, taxa (relógio injetado), sem sleeps
  test_snapshot.py      # serialização pura
  test_server.py        # Flask test-client (rotas, estáticos)
```

## 4. Concorrência e thread-safety

- O `EncoderPoller` roda o loop do `ReadingSource` numa **thread daemon** que é a
  **única** dona da serial. A web nunca toca no master direto.
- A lógica fica separada da thread: `EncoderPoller.step()` processa **uma** iteração
  (lê uma leitura, aplica comandos pendentes, atualiza o snapshot sob `lock`). A
  thread só chama `step()` em loop. Isso torna a lógica testável sem threads nem
  `sleep`.
- Comandos (ex.: zerar) entram numa fila/flag thread-safe e são consumidos **dentro**
  da thread do poller (toda mutação do master num único lugar → sem corrida).
- O `now` (relógio) é **injetado** no poller para o cálculo de `rate_hz`, evitando
  testes dependentes de tempo real.

## 5. Contrato do WebSocket (`/ws`)

- Servidor → browser, ~15 Hz, JSON:
  `{type:"reading", angle_deg, raw, bytes_hex, offset, connected, rate_hz, diag, ts}`.
  Quando o `Data_Exchange` cai: `connected:false` (os campos numéricos mantêm o
  último valor conhecido, marcados como stale pela flag).
- Browser → servidor: `{cmd:"zero"}` e `{cmd:"clear_zero"}`.
- Vários clientes podem conectar (broadcast). O cliente reconecta sozinho se a
  conexão cair.

## 6. "Zerar aqui" (só sessão no v1)

- `{cmd:"zero"}` → o poller calcula `offset_novo = (raw_exibido_atual + offset_atual)
  mod 2^bits` e chama `source.set_offset(...)`. O ângulo passa a marcar ~0.
- `{cmd:"clear_zero"}` → `set_offset(0)`.
- O `offset` atual vai no snapshot (a UI mostra). **Sem persistência** entre
  reinícios no v1 (fase futura grava num `config/zero.json` à parte para não
  mexer no `encoder.yaml` comentado).

## 7. Frontend (Preact sem build, princípios premium)

**Stack (resolvendo o conflito skills × no-build):** as skills de frontend assumem
React/Next + Tailwind + Motion + npm; o nosso alvo é um Pi sem Node. Honro os
**princípios**, não a toolchain:
- **Preact + `htm` vendorizados** (ESM locais em `static/vendor/`). Reatividade real,
  zero build.
- **CSS autoral com tokens** (custom properties) no lugar do Tailwind.
- **Fonte premium vendorizada** (`.woff2` self-hosted, licença OFL): grotesca para
  rótulos/títulos + **mono para os numerais** (leitura de instrumento). Stack de
  fallback do sistema. **Inter banido como default.**
- **Movimento por CSS** com `cubic-bezier` próprio (a agulha interpola suave; pulso
  no estado de conexão). Sem biblioteca de animação. Respeita
  `prefers-reduced-motion`.

**Design read:** painel de instrumento industrial, dark-tech.
- **Mostrador circular** (dial + agulha) do ângulo 0–360°, tratado como hardware
  usinado (bezel aninhado, hairline, sombra tingida — não preta dura).
- **Numerais ao vivo em mono:** ângulo grande; `raw/8191`, `bytes`, `offset`,
  `rate_hz` secundários.
- **Acento único contido** (ex.: verde-esmeralda ou azul-elétrico) — sem
  roxo-de-IA, sem gradiente genérico. Um tema travado (dark), sem inverter seções.
- **Estados completos:** *conectando* (skeleton/placeholder), *conectado* (badge +
  taxa), *sem leitura/perdido* (badge vermelho + valores marcados como stale),
  *erro de init* (mensagem clara, o servidor não cai).
- **Acessibilidade:** contraste WCAG AA em texto e badges; foco visível no botão;
  rótulos legíveis. **Sem emoji** na UI.
- **Copy anti-slop (stop-slop):** rótulos diretos e funcionais ("Ângulo", "Bruto",
  "Zerar aqui"), sem frases de efeito, sem em-dash.

## 8. Tratamento de erros

- Se o `ReadingSource` falhar ao iniciar (serial ausente), o poller publica
  `connected:false` + mensagem de erro; o **servidor continua de pé** e a UI mostra
  o erro em vez de quebrar.
- Queda de `Data_Exchange`: o pyprofibus re-inicia sozinho; o snapshot fica
  `connected:false` no intervalo.
- WS: desconexão de cliente tratada; múltiplos clientes suportados.

## 9. Testes (TDD, sem test-smells)

- **`FakeSource`** implementa `ReadingSource` com leituras roteirizadas → testa o
  poller **sem hardware, sem pyprofibus**.
- **`EncoderPoller.step()`** testado de forma síncrona e determinística: snapshot
  atualiza; `zero` faz o `raw` exibido ir a 0; `rate_hz` calculado com **relógio
  injetado** (sem `sleep`, sem flakiness de thread).
- **`snapshot_to_dict`** é função pura → teste isolado do contrato JSON.
- **`server.py`** via Flask test-client: rotas, estáticos servidos.
- Os **23 testes atuais** seguem verdes (a lib só ganha `set_offset`, coberto por
  teste novo).

## 10. Dependências novas

`flask`, `flask-sock` (adicionadas ao `requirements.txt`). Frontend sem deps de
runtime (vendorizado). Porta padrão **8600** (configurável via `serve.py`).
