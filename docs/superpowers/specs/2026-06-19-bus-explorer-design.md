# Design — Explorador de barramento (scan + controles de baud/endereço)

**Data:** 2026-06-19
**Status:** Aprovado para implementação (decisões tomadas no recomendado, por delegação do usuário)
**Fase:** 2 de 4 incrementos · sub-projeto **A** de **A → B → C**
(A = explorar barramento · B = parametrizar qualquer escravo · C = perfis declarativos)

## 1. Objetivo

Transformar o dashboard v1 (encoder-específico) na **fundação de uma ferramenta de
comissionamento**: além de ler o encoder, o usuário pode **varrer o barramento**
(descobrir quem está vivo, 0–126) e **ajustar baud + endereço do mestre pela UI**,
com persistência. É o menor pedaço útil que já firma a arquitetura nova de **dono
único da serial com modos**, que B e C vão reusar.

## 2. Escopo

**Dentro:**
- Um `BusController`: dono único da serial, com modos (`exchange` / `scanning` /
  `idle`). Substitui o `EncoderPoller` como dono do ciclo e da porta.
- Varredura *live list*: para cada endereço 0–126, um FDL **Request-FDL-Status**;
  mostra quem respondeu, o **tipo de estação** (escravo / mestre não-pronto /
  mestre pronto / mestre no anel) e o **tempo de resposta**.
- Controles de **baud** (dropdown padrão PROFIBUS, com aviso honesto) e **endereço
  do mestre** (1–126) pela UI, **persistidos em `config/bus.json`**.
- Frontend: shell com duas vistas — **Encoder** (dashboard v1, intacto) e
  **Barramento** (varredura + controles).

**Fora (B/C ou nunca):**
- Identificação detalhada do escravo (ident number/modelo, diagnóstico DP) → **B**
  (usa `Get_Diag`/GSD).
- Upload/gestão de GSD, parametrizar escravos → **B**.
- Perfis declarativos de decode → **C**.
- **Reatribuir o endereço de um escravo pelo barramento** (`Set_Slave_Address`,
  SAP 55): **não existe no pyprofibus → fora**. "Endereço pela UI" = endereço do
  **mestre** e (em B) qual escravo-alvo, não reendereçar escravos remotamente.
- **Baud acima do teto do Pi não-RT**: a UI permite escolher, mas o teto **continua
  valendo e é documentado, não "resolvido"** (ver §7).

## 3. Verdade técnica (aterrada no fonte do pyprofibus)

- **Scan é real e construído por nós** sobre o FDL: `FdlTelegram_FdlStat_Req(da,
  sa)` + `FdlTransceiver(phy).send(fcb, tel)` + `.poll(timeout)`. Não há `scan()`
  pronto. O byte FC da resposta dá o tipo: `fc & 0x30` ∈ {`FC_SLAVE`=0x00,
  `FC_MNRDY`=0x10, `FC_MRDY`=0x20, `FC_MTR`=0x30}.
- **PHY avulsa:** `PbConf.fromFile(...).makePhy()` cria a `CpPhySerial` em qualquer
  baud (`conf.phyBaud`). `phy.close()` libera a serial; `DpMaster.destroy()` chama
  `phy.close()`. Logo **scan e exchange nunca seguram a porta ao mesmo tempo**.
- **Mestre único** no barramento é premissa (ferramenta pessoal de comissionamento).
  Varrer com outro mestre dono do token colidiria.

## 4. Arquitetura (em camadas, SOLID)

```
 frontend Preact ──(WebSocket /ws)──▶ web/server.py (Flask + flask-sock)
   2 vistas: Encoder/Barramento            │ depende de
                                            ▼
                                     web/controller.py · BusController     (serviço de app)
                                       dono único da serial + modos
                            ┌───────────────┼────────────────────────┐
                            ▼ (factory)      ▼ (factory)              ▼
                  ExchangeEngine(Protocol)  BusProbe(Protocol)   SettingsStore
                     ▲          ▲             ▲          ▲       (config/bus.json)
              EncoderPoller  FakeEngine  FdlBusProbe  FakeProbe
              (=v1, reusado)   (test)    (pyprofibus)   (test)
                     │                       │
              profibus_amg11 (master/decode/config)  ·  profibus_amg11/scan.py
```

**SRP — responsabilidade de cada unidade:**

- **`profibus_amg11/scan.py`** (domínio; conhece pyprofibus FDL):
  - `StationType` (enum) + `from_fc(fc)`; `Station` (frozen: `addr`,
    `station_type`, `response_ms`).
  - `BusProbe` (Protocol): `probe(addr:int) -> Station | None` (None = silêncio),
    `close() -> None`.
  - `FdlBusProbe`: implementação real. Constrói/possui uma `phy` (via `makePhy` num
    baud dado) + `FdlTransceiver` + `FdlFCB(enable=False)` + `master_addr` como
    `sa`. `probe` envia `FdlStat_Req`, faz `poll(timeout)` medindo o tempo, decodifica
    o FC. **Toda a dependência de pyprofibus do scan mora aqui.**
- **`web/scanner.py`** (app; **lógica pura, passo-a-passo, sem pyprofibus**):
  - `ScanState` (frozen): `status` (`idle`|`scanning`|`done`), `current_addr`,
    `scanned`, `total`, `found: tuple[Station,...]`, `started_ts`, `done_ts`.
  - `BusScan(probe, addresses, now)`: `step()` sonda **um** endereço por chamada e
    atualiza o progresso; `done` (bool); `state()`. Testável com `FakeProbe` +
    `FakeClock`, **sem sleep**.
- **`web/settings.py`** (app):
  - `BusSettings` (frozen: `baud:int`, `master_addr:int`) com validação
    (`master_addr` 1–126; `baud` no conjunto permitido).
  - `SettingsStore(path)`: `load(defaults) -> BusSettings` (lê `bus.json` ou cai no
    default), `save(BusSettings)`. JSON. Testado com `tmp_path`.
- **`web/controller.py` · `BusController`** (serviço de app; dono único da serial,
  uma thread):
  - Reusa `EncoderPoller` como **motor de exchange** via Protocol `ExchangeEngine`
    (`step()`, `snapshot()`, `zero()`, `clear_zero()`, `stop()`). **DIP:** o
    controller depende do Protocol, não do `EncoderPoller` concreto → testável com
    `FakeEngine`.
  - **Factories injetadas:** `make_exchange(BusSettings, offset) -> ExchangeEngine`
    e `make_probe(BusSettings) -> BusProbe`. O controller **garante um dono por
    vez**:
    derruba o exchange (`stop()` → fecha a serial) antes de criar a probe, e
    recria o exchange ao terminar.
  - `step()` determinístico: drena comandos, executa **um** passo do modo atual,
    publica snapshots sob `lock`. A thread só chama `step()` em loop (mesmo padrão
    testável do v1).
  - Comandos (fila thread-safe): `scan()`, `apply_settings(baud, master_addr)`,
    `zero()`, `clear_zero()`.
  - Snapshots: `encoder_snapshot()` (o `Snapshot` do v1; durante o scan fica o
    último, marcado pausado) e `bus_snapshot()` (`ScanState` + `BusSettings` + modo).
- **`web/server.py`:** `create_app(controller)`. O `/ws` empurra **dois** tipos de
  mensagem por tick e recebe os comandos novos. Não conhece pyprofibus.
- **`web/snapshot.py`:** ganha `bus_snapshot_to_dict(scan_state, settings, mode)`
  (puro). O `snapshot_to_dict` do encoder fica igual.
- **`profibus_amg11/master.py`:** `Amg11Master.__init__` ganha `baud=None,
  master_addr=None` (override de `conf.phyBaud`/`conf.dpMasterAddr` antes do
  `makeDPM`). Mínimo e retrocompatível.
- **`serve.py`:** monta `SettingsStore(config/bus.json)`, carrega settings (default
  vindo do `.conf`), monta `BusController` com as factories de produção,
  `controller.start()`, `create_app(controller)`.

### Estrutura de arquivos (novos vs editados)
```
profibus_amg11/
  scan.py            # StationType, Station, BusProbe(Protocol), FdlBusProbe   [novo]
  master.py          # + overrides baud/master_addr                            [edição mínima]
web/
  settings.py        # BusSettings + SettingsStore (bus.json)                  [novo]
  scanner.py         # BusScan (passo-a-passo) + ScanState                     [novo]
  controller.py      # BusController + ExchangeEngine(Protocol)                [novo]
  snapshot.py        # + bus_snapshot_to_dict                                  [edição]
  server.py          # create_app(controller); /ws 2 tipos + comandos novos    [edição]
  poller.py          # inalterado (vira o motor de exchange)
  static/
    app.js           # shell 2 vistas + Barramento                            [edição]
    styles.css       # tokens da vista Barramento (tabela, abas, progresso)   [edição]
    index.html       # inalterado (mesmo importmap)
serve.py             # monta SettingsStore + BusController                     [edição]
config/
  bus.json           # gerado em runtime (gitignored)                          [novo, runtime]
tests/
  test_scan.py           # StationType.from_fc; FdlBusProbe (com fake phy/transceiver)
  test_scanner.py        # BusScan passo-a-passo (FakeProbe, FakeClock)
  test_settings.py       # BusSettings validação; SettingsStore load/save (tmp_path)
  test_controller.py     # modos, troca de dono, comandos (FakeEngine, FakeProbe)
  test_snapshot.py       # + bus_snapshot_to_dict
  test_server.py         # rotas + comandos novos (test-client)
```

## 5. Modos e troca de dono da serial (o coração)

Estado do `BusController`: `mode ∈ {exchange, scanning, idle}` + `settings`.

- **exchange (padrão):** cada `step()` → `engine.step()`; atualiza o encoder
  snapshot. É o comportamento do v1, agora dirigido pelo controller (não pela
  thread interna do `EncoderPoller`).
- **scan() (comando):** o controller (1) derruba o motor de exchange
  (`engine.stop()` → fecha a serial), (2) cria a `BusProbe` no baud atual (abre a
  serial p/ FDL), (3) cria `BusScan(probe, 0..126 sem o master_addr, now)` e entra
  em `scanning`.
- **scanning:** cada `step()` → `scan.step()` (sonda um endereço; progresso vai pro
  bus snapshot ao vivo). Quando `scan.done`: fecha a probe e **recria** o motor de
  exchange (reabre a serial → re-estabelece o Data_Exchange), volta a `exchange`.
- **apply_settings(baud, master_addr):** valida, **persiste** (`SettingsStore.save`),
  e marca rebuild do exchange no novo baud/endereço (derruba + recria). Se um scan
  estiver em curso, aplica ao terminá-lo.
- **erro ao recriar o exchange** (ex.: encoder ausente após scan): vira `idle` com
  diag claro; **o servidor não cai**; um novo scan/apply ainda funciona.

**Preservar o zero entre rebuilds:** o controller guarda o `offset` corrente (lido
do encoder snapshot a cada passo de exchange) e o repassa ao `make_exchange(settings,
offset)` ao recriar o motor. Assim o "zero" da sessão **sobrevive** a um scan/apply
(sem regressão de UX vs v1).

**Custo aceito:** recriar o mestre após o scan re-roda o startup DP (alguns
segundos até o Data_Exchange voltar). Scan é ação explícita e ocasional → ok.
Documentado.

## 6. Varredura (detalhes)

- **Faixa:** 0–126, **pulando o `master_addr`** (não faz sentido sondar a si mesmo).
- **Timeout por endereço:** parâmetro da probe (default **0.05 s**). Pior caso (tudo
  silencioso) ≈ 127 × 50 ms ≈ 6,4 s. Quem responde, responde rápido.
- **Tentativa única** por endereço em A (retry fica como melhoria futura, anotada).
- **Progresso ao vivo:** `current_addr`, `scanned/total`, e `found` crescendo — tudo
  publicado no bus snapshot a cada `step()`, então a UI mostra a barra andando.
- **FCB:** `FdlFCB(enable=False)` (request FDL-status inicial dispensa FCB/FCV).

## 7. Controles de baud/endereço (honestidade embutida)

- **Baud (dropdown):** conjunto padrão PROFIBUS `{9600, 19200, 45450, 93750, 187500,
  500000, 1500000}`. Default = atual.
  - **Aviso direto na UI:** "No Raspberry Pi (Linux não-RT) via pyprofibus, apenas
    **9600 e 19200** são confiáveis. Acima disso o timing de slot tende a falhar —
    best-effort." As opções acima de 19200 ficam visualmente marcadas como
    best-effort. **Nada de prometer 12 Mbit.**
- **Endereço do mestre:** input 1–126, validado.
- **Aplicar:** botão único → `apply_settings`. A UI reflete o estado (aplicando…,
  reconectando…) via bus snapshot.
- **Persistência:** `config/bus.json` (`{ "baud": …, "master_addr": … }`). Carregado
  no boot; default vem do `.conf` se o arquivo não existir. **Gitignored** (estado
  de runtime, como o futuro `zero.json`).

## 8. Contrato do WebSocket (`/ws`)

Servidor → browser, ~15 Hz, **dois** tipos por tick:
- Encoder (igual ao v1): `{type:"reading", angle_deg, raw, raw_max, bytes_hex,
  offset, connected, rate_hz, diag, ts}`.
- Barramento (novo): `{type:"bus", mode, settings:{baud, master_addr},
  scan:{status, current_addr, scanned, total, found:[{addr, station_type,
  response_ms}], started_ts, done_ts}}`.

Browser → servidor: `{cmd:"zero"}`, `{cmd:"clear_zero"}` (já existem),
`{cmd:"scan"}` e `{cmd:"apply_settings", baud, master_addr}` (novos). Comando
inválido é ignorado (mesmo padrão defensivo do v1).

## 9. Frontend (Preact sem build, mesma stack vendorizada)

- **Shell com abas** "Encoder" / "Barramento" (estado local; sem router externo).
  Um `useBusSocket()` roteia por `msg.type` e devolve `{encoder, bus, send}`.
- **Vista Encoder:** o dashboard v1 **intacto** (mostrador, numerais, zerar).
- **Vista Barramento:**
  - **Controles:** dropdown de baud (com o aviso §7), input de endereço do mestre,
    botão **Aplicar**.
  - **Varredura:** botão **Varrer** (desabilita enquanto varre), **barra de
    progresso** (`scanned/total`, endereço atual), e **tabela** das estações
    encontradas (endereço · tipo · ms). Vazio → estado claro ("nenhuma estação"
    após varrer; "ainda não varrido" antes).
- **Princípios v1 mantidos:** tema escuro de instrumento, acento único, **mono nos
  numerais/endereços**, **sem emoji**, contraste AA, foco visível,
  `prefers-reduced-motion`, copy direta (sem em-dash, sem frase de efeito).

## 10. Tratamento de erros

- Probe falha ao abrir a serial (porta ausente): scan termina com `status:"done"` +
  diag de erro no bus snapshot; servidor de pé.
- Exchange falha ao recriar após scan/apply: modo `idle` + diag; UI mostra; novo
  comando ainda funciona.
- `apply_settings` com valor inválido: rejeitado (não persiste), diag na UI.
- WS: desconexão de cliente tratada; múltiplos clientes (broadcast); reconexão
  automática (igual v1).

## 11. Testes (TDD, sem test-smells)

- **`BusScan`** dirigido por `FakeProbe` (respostas roteirizadas) + `FakeClock`:
  progresso, `found` correto, pula o master, termina. **Sem sleep, sem hardware.**
- **`StationType.from_fc`**: mapeia os 4 bits de tipo; `FdlBusProbe` testado com uma
  **phy/transceiver fake** (telegramas roteirizados) — sem serial real.
- **`SettingsStore`**: load sem arquivo → default; save+load round-trip; valor
  inválido rejeitado (`tmp_path`).
- **`BusController`** com `FakeEngine`+`FakeProbe`+factories fake: começa em
  exchange; `scan()` derruba o engine, varre, recria o engine, volta a exchange;
  `apply_settings` persiste e reconstrói; erro de rebuild → `idle`; `zero` é
  encaminhado ao engine. **Determinístico via `step()`.**
- **`bus_snapshot_to_dict`**: função pura → contrato JSON isolado.
- **`server.py`** via test-client: rotas e os comandos novos.
- **Os 44 testes do v1 seguem verdes** (poller/snapshot/source intactos; master só
  ganha overrides opcionais cobertos por teste novo).

## 12. Abordagens consideradas

- **(escolhida) Teardown + rebuild do exchange a cada scan.** Separação limpa: o
  scan é **independente do encoder** (a probe cria a própria phy). Custo: re-init DP
  no retorno. Melhor p/ B/C (abstrações limpas).
- **(rejeitada) "Emprestar" a phy do mestre vivo p/ o scan.** Mais rápido (sem
  re-init), porém **vaza a phy** através das abstrações e acopla scan ao mestre do
  encoder — ruim para a generalização de B/C.
- **(rejeitada) Dois processos/portas.** Impossível: barramento único, serial única,
  mestre único.

## 13. Dependências novas

Nenhuma nova lib (Flask/flask-sock/Preact já estão). `config/bus.json` é runtime e
entra no `.gitignore`. Porta padrão **8600** (inalterada).
