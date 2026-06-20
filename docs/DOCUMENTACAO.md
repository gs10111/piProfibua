# Documentação — Comissionador PROFIBUS-DP no Raspberry Pi

> Documento mestre do projeto. Explica **o que é**, **como rodar**, a **arquitetura**,
> e **cada arquivo do código** (o que faz, como funciona, como usar, de que depende).
> Para fiação e checklist de campo, ver também o [README](../README.md).

---

## Sumário

1. [Visão geral](#1-visão-geral)
2. [Como rodar (rápido)](#2-como-rodar-rápido)
3. [Arquitetura em camadas](#3-arquitetura-em-camadas)
4. [O domínio: `profibus_amg11/`](#4-o-domínio-profibus_amg11)
5. [A aplicação web: `web/`](#5-a-aplicação-web-web)
6. [Entrypoints: `run.py` e `serve.py`](#6-entrypoints-runpy-e-servepy)
7. [Frontend: `web/static/`](#7-frontend-webstatic)
8. [Configuração: `config/` e `gsd/`](#8-configuração-config-e-gsd)
9. [Contratos de comunicação (WebSocket + HTTP)](#9-contratos-de-comunicação)
10. [A máquina de modos do `BusController`](#10-a-máquina-de-modos-do-buscontroller)
11. [Testes](#11-testes)
12. [Roadmap A → B → C](#12-roadmap-a--b--c)
13. [Limitações honestas](#13-limitações-honestas)
14. [Glossário PROFIBUS](#14-glossário-profibus)

---

## 1. Visão geral

Um **Raspberry Pi 3** atua como **mestre PROFIBUS-DP (DPM1)** usando a biblioteca
**pyprofibus** (mestre 100% Python). A camada física é um **módulo RS485↔TTL** ligado
direto na **UART de hardware** do Pi (`/dev/serial0`). O dispositivo de referência é um
encoder absoluto **Baumer/Hübner AMG 11 P 13** (singleturn 13-bit).

O projeto tem **duas faces**:

- **CLI** (`run.py`): lê a posição do encoder no terminal. Bom para diagnóstico.
- **Ferramenta web de comissionamento** (`serve.py`): um painel com três abas —
  - **Encoder**: leitura ao vivo (ângulo, bruto, bytes, taxa, diagnóstico) + "zerar".
  - **Barramento**: varredura (*live list* 0–126) + controles de baud/endereço.
  - **GSD**: enviar/inspecionar arquivos `.gsd` e pré-visualizar a parametrização.

Tudo roda **sem hardware** no modo simulação (`--sim`, PHY dummy do pyprofibus), o que
torna o desenvolvimento e os testes independentes do barramento real.

**Princípios de engenharia:** SOLID (camadas com interfaces claras), TDD (lógica em
funções `step()` determinísticas, relógio e dependências injetados, *fakes* no lugar de
hardware), honestidade técnica (o teto de baud do Pi não-RT é documentado, não "resolvido").

---

## 2. Como rodar (rápido)

```bash
cd ~/repos/pi5-profibus-amg11
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# CLI sem hardware (valida o pipeline):
python run.py --sim --once

# Web sem hardware (abre as 3 abas):
python serve.py --sim                 # http://localhost:8600

# Com encoder real (após setup do Pi — ver README):
python run.py --hz 20                 # CLI contínua
python serve.py                       # painel web

# Testes:
pytest -q
```

Flags úteis: `run.py` aceita `--once`, `--hz`, `-v` (trace do pyprofibus), `--sim`,
`--conf`, `--encoder`. `serve.py` aceita `--host`, `--port`, `--conf`, `--encoder`, `--sim`.

---

## 3. Arquitetura em camadas

A regra de ouro é **separar responsabilidades** e **depender de abstrações** (DIP):

```
┌──────────────────────────────────────────────────────────────────────┐
│ FRONTEND (Preact vendorizado, sem build)  web/static/                  │
│   3 abas: Encoder · Barramento · GSD                                   │
└───────────────┬───────────────────────────────┬──────────────────────┘
        WebSocket /ws (telemetria)      HTTP /api/gsd* (CRUD de GSD)
                │                                 │
┌───────────────▼─────────────────────────────────▼────────────────────┐
│ TRANSPORTE  web/server.py (Flask + flask-sock)                        │
│   create_app(controller, gsd_store) — não conhece pyprofibus          │
└───────────────┬───────────────────────────────┬──────────────────────┘
                │ usa                            │ usa
┌───────────────▼──────────────┐   ┌────────────▼──────────────────────┐
│ SERVIÇO  web/controller.py   │   │ web/gsd_store.py (arquivos .gsd)   │
│ BusController: dono único da  │   │ valida via ↓                       │
│ serial, modos exchange/scan/  │   └────────────┬──────────────────────┘
│ idle. Publica snapshots.      │                │
└──────┬──────────────┬─────────┘                │
       │ depende de    │ depende de              │
┌──────▼──────┐ ┌──────▼─────────┐  ┌────────────▼──────────────────────┐
│ ExchangeEng.│ │ BusProbe       │  │ DOMÍNIO  profibus_amg11/           │
│ (Protocol)  │ │ (Protocol)     │  │  encoder.decode · scan.FdlBusProbe │
│  =Encoder   │ │  =FdlBusProbe  │  │  master.Amg11Master · gsd_info     │
│   Poller    │ │  /SimBusProbe  │  │  (única camada que conhece         │
└──────┬──────┘ └──────┬─────────┘  │   pyprofibus)                      │
       └───────┬────────┘            └────────────────────────────────────┘
               ▼
        pyprofibus (FDL, DP, GSD, PHY serial)  ←→  RS485 ←→ escravos
```

**Por que assim?** A web nunca toca o pyprofibus nem a serial. O `BusController` é o
**único dono da porta** — varrer, trocar dados e parametrizar são mutuamente exclusivos
nela. As fronteiras (`ReadingSource`, `ExchangeEngine`, `BusProbe` — todas `Protocol`)
permitem testar tudo com *fakes*, sem hardware.

---

## 4. O domínio: `profibus_amg11/`

A **única** camada que conhece o pyprofibus e a matemática do encoder. Pura e testável.

### `encoder.py` — decodificação (função pura)
- **O que faz:** transforma os 2 bytes de posição do escravo em ângulo.
- **Como funciona:** `decode(data, cfg) -> EncoderReading`. Lê `Unsigned16` big-endian,
  aplica a máscara de `2**resolution_bits` (8192 p/ 13 bit), espelha se `direction=="ccw"`,
  subtrai o `offset` (zero por software) e converte para graus (`raw/period*360`).
  `EncoderReading` é um dataclass *frozen* com `raw`, `angle_deg`, `bytes_hex`.
- **Como usar:** `from profibus_amg11.encoder import decode; decode(b"\x08\x00", cfg)`.
- **Depende de:** nada além do `EncoderConfig`. É a peça mais reusável (todo "zero" e
  sentido passam por aqui — DRY).

### `config.py` — carregamento do `encoder.yaml`
- **O que faz:** lê e valida os parâmetros de pós-processamento.
- **Como funciona:** `EncoderConfig` (frozen: `resolution_bits`, `direction`, `offset`,
  `control_word`) valida faixas no `__post_init__`. `load_config(path) -> EncoderConfig`
  abre o YAML.
- **Como usar:** `cfg = load_config("config/encoder.yaml")`.

### `source.py` — a abstração `ReadingSource` (Protocol)
- **O que faz:** define o **contrato** de uma fonte de leituras: `poll() ->
  EncoderReading | None`, `set_offset(int)`, `close()`.
- **Por que existe (DIP):** o `EncoderPoller` depende **disto**, não do `Amg11Master`
  concreto. Em produção a implementação é o `Amg11Master`; em teste é o `FakeSource`.
- **`@runtime_checkable`:** permite `isinstance(x, ReadingSource)` nos testes.

### `master.py` — `Amg11Master` (o mestre DP do encoder)
- **O que faz:** dono da serial e da máquina de estados DP para **um** escravo (o encoder).
  Implementa `ReadingSource`.
- **Como funciona:**
  - `__init__(conf_path, encoder_cfg, sim=False, debug=False, baud=None, master_addr=None)`:
    faz `chdir` para a raiz (o GSD no `.conf` é relativo), carrega `PbConf.fromFile`,
    aplica overrides opcionais de `baud`/`master_addr` (usados pela aba Barramento),
    monta o `DpMaster`, adiciona o escravo e chama `initialize()`.
  - `poll()`: re-arma a palavra de saída e roda **um passo** (`master.run()`); se o passo
    tratou o nosso escravo e há dados de entrada, retorna `decode(...)`, senão `None`.
  - `set_offset(v)`: reusa o `decode` (troca o `offset` no `cfg` — sem duplicar a matemática).
  - `read_once`, `run(callback, hz)`: conveniências da CLI. `close()`: `master.destroy()`
    (libera a serial).
- **`build_scan_phy(conf_path, baud)`** (módulo): cria uma **PHY avulsa** no baud dado,
  reusando o mesmo `.conf`, para a varredura FDL. O chamador fecha com `phy.close()`.
- **Caveat:** o pyprofibus exige `input_size>=1`, por isso usamos o **módulo Classe 2
  (`0xF0`)** e enviamos 2 B de `control_word` por ciclo só para sustentar o `Data_Exchange`.

### `scan.py` — varredura de barramento (domínio do FDL)
- **O que faz:** descobre quem está vivo no barramento (*live list*).
- **Como funciona:**
  - `StationType` (enum) + `from_fc(fc)`: decodifica o tipo de estação do byte FC da
    resposta (`fc & 0x30` → escravo / mestre não-pronto / mestre pronto / mestre no anel).
  - `Station` (frozen): `addr`, `station_type`, `response_ms`.
  - `BusProbe` (Protocol): `probe(addr) -> Station | None`, `close()`.
  - `FdlBusProbe`: implementação real. Monta `FdlTelegram_FdlStat_Req(da=addr, sa=master)`,
    envia via `FdlTransceiver`, faz `poll(timeout)`, valida que o `sa` da resposta bate com
    o endereço sondado (o filtro RX do FDL aceita qualquer um) e mede o tempo de resposta.
  - `SimBusProbe`: sem hardware — "encontra" os endereços de uma lista (usado no `--sim`).
- **Como usar:** o `BusController` cria a probe e a entrega ao `BusScan` (ver `web/`).

### `gsd_info.py` — inspeção de GSD e preview de parametrização (puro)
- **O que faz:** lê um arquivo `.gsd` e responde "que dispositivo é esse?" e "o que a
  parametrização enviaria?". **Offline** (não toca no barramento).
- **Como funciona:**
  - `parse_gsd(data: bytes, filename) -> GsdSummary`: usa `GsdInterp.fromBytes` (decodifica
    `latin_1`), exige `Ident_Number` (senão não é um GSD válido → `GsdInfoError`), e extrai
    fabricante, modelo, revisão, ident, order, `modular`, `dpv1`, lista de módulos
    (nome + config bytes + preset) e a tabela de `MaxTSDR` por baud.
  - `preview_params(data, module_names) -> ParamPreview`: escolhe módulo(s)
    (`clearConfiguredModules` + `setConfiguredModule`) e computa **ident + cfg bytes**
    (`getCfgDataElements().getDU()` → o que vai num `Chk_Cfg`) + **user_prm bytes**
    (`getUserPrmData()` → o que vai num `Set_Prm`).
  - `summary_to_dict` / `preview_to_dict` / `module_to_dict`: serialização pura p/ JSON.
- **Como usar:** `parse_gsd(open("gsd/PB13DPV0.gsd","rb").read(), "x.gsd")`. Ex.: AMG11
  módulo "16 Bit Class 2 Encoder" → ident `0x059B`, cfg `f0`, user_prm `000a…`.

---

## 5. A aplicação web: `web/`

Camadas de **serviço/transporte** que não conhecem o pyprofibus diretamente (só pelos
Protocols do domínio).

### `snapshot.py` — estado publicado + serialização
- **`Snapshot`** (frozen): o estado do encoder publicado para a UI (`angle_deg`, `raw`,
  `raw_max`, `bytes_hex`, `offset`, `connected`, `rate_hz`, `diag`, `ts`).
- `initial_snapshot(offset, raw_max)`: estado "conectando".
- `snapshot_to_dict(s)`: contrato JSON do encoder (`type:"reading"`, arredonda ângulo/taxa).
- `bus_snapshot_to_dict(bus)`: contrato JSON do barramento (`type:"bus"` — modo, settings,
  estado do scan com `found`).

### `poller.py` — `EncoderPoller` (motor de troca cíclica)
- **O que faz:** mantém um `Snapshot` vivo lendo o `ReadingSource` numa thread.
- **Como funciona (padrão central do projeto):** a **lógica** vive em `step()` (lê uma
  leitura, drena comandos pendentes — zero/clear_zero —, calcula a taxa com **relógio
  injetado**, monta o `Snapshot` sob `lock`); a **thread** só chama `step()` em loop. Isso
  torna a lógica testável **sem threads e sem `sleep`**. `zero()` calcula
  `offset = (raw_atual + offset) % período`. Marca "sem leitura"/"conectando" conforme o
  tempo desde a última leitura válida (`stale_after`).
- **Papel atual:** sob o `BusController`, é o **motor do modo `exchange`** (atrás do
  Protocol `ExchangeEngine`); o controller chama o `step()` dele.

### `settings.py` — `BusSettings` + `SettingsStore`
- **`BusSettings`** (frozen): `baud`, `master_addr`, validados (`ALLOWED_BAUDS`;
  `RELIABLE_BAUDS=(9600,19200)` — o resto é best-effort no Pi não-RT).
- **`SettingsStore(path)`**: `load(defaults)` (lê `config/bus.json` ou cai no default) e
  `save(settings)`. Persiste os controles de baud/endereço entre reinícios.

### `scanner.py` — `BusScan` (lógica de varredura, pura)
- **`ScanState`** (frozen): `status` (idle/scanning/done), `current_addr`, `scanned`,
  `total`, `found`, timestamps, `error`.
- **`BusSnapshot`** (frozen): o que a aba Barramento lê — `mode`, `settings`, `scan_state`,
  `diag`.
- **`BusScan(probe, addresses, now)`**: `step()` sonda **um** endereço por chamada e
  atualiza o progresso; `done` indica fim. Determinístico (relógio injetado), testável com
  `FakeProbe` sem hardware.

### `controller.py` — `BusController` (o coração)
- **O que faz:** **dono único da serial**, numa só thread, orquestrando os modos.
- **Como funciona:**
  - Recebe **factories injetadas**: `make_exchange(settings, offset) -> ExchangeEngine` e
    `make_probe(settings) -> BusProbe` (em produção, criadas pelo `serve.py`; em teste,
    *fakes*). Isso é o que permite testar o controller **sem pyprofibus**.
  - `ExchangeEngine` (Protocol): `step()/snapshot()/zero()/clear_zero()/stop()` — o
    `EncoderPoller` satisfaz.
  - **Concorrência (padrão publish-imutável):** todo estado de trabalho
    (`mode/diag/settings/scan`) é mutado **só pela thread do controller**; o que a web lê é
    publicado como objeto **imutável sob `lock`** (`encoder_snapshot()`, `bus_snapshot()`).
    Sem corrida, sem leitura rasgada.
  - **Comandos** (fila thread-safe): `scan()`, `apply_settings(baud, addr)`, `zero()`,
    `clear_zero()`. Drenados no topo do `step()`.
  - **Troca de dono da serial:** ao varrer, **derruba** o motor de exchange
    (`stop()` → fecha a serial), **abre** a probe, varre passo-a-passo, **fecha** a probe e
    **recria** o motor (preservando o `offset` da sessão). Falha ao recriar → modo `idle`
    com diag claro, **servidor não cai**.
  - `apply_settings`: valida, **persiste** (callback do `SettingsStore`) e reconstrói o
    motor no novo baud/endereço; se uma varredura estiver em curso, aplica ao terminá-la.
    Falha de persistência **não** derruba o loop nem pula o rebuild.

### `gsd_store.py` — `GsdStore` (biblioteca de arquivos GSD)
- **O que faz:** guarda/lista/lê arquivos `.gsd` com segurança.
- **Como funciona:** `save(filename, data)` **valida por parse** (rejeita não-GSD), recusa
  **sobrescrever** (protege fixtures, evita troca furtiva) e tem **path-safety** (rejeita
  separadores e `..`; só `[A-Za-z0-9._-]+.gsd`). `list()` (case-insensitive), `read(name)`,
  `summary(name)`.

### `gsd_api.py` — rotas HTTP de GSD
- **O que faz:** o CRUD de GSD por HTTP (separado do WebSocket de telemetria).
- **Rotas** (`register_gsd_routes(app, store)`): `GET/POST /api/gsd`,
  `GET /api/gsd/<name>`, `POST /api/gsd/<name>/preview`. Erros viram 400/404/409/413 com
  `{"error": ...}`. Upload via `multipart` (campo `file`) ou bytes crus com `X-Filename`.

### `server.py` — `create_app` (transporte Flask)
- **O que faz:** serve os estáticos, o WebSocket `/ws` e (opcionalmente) as rotas de GSD.
- **Como funciona:** `create_app(controller, gsd_store=None)`. Define
  `MAX_CONTENT_LENGTH` (2 MB, anti-DoS). `/ws`: a cada tick (~15 Hz) envia **dois** JSON
  (encoder + barramento) e recebe comandos via `handle_ws_message` (função pura,
  testável). Se `gsd_store` for dado, registra as rotas `/api/gsd*`. **Não conhece
  pyprofibus.**

---

## 6. Entrypoints: `run.py` e `serve.py`

### `run.py` — a CLI
- Monta `Amg11Master(conf, cfg, sim, debug)` e: `--once` (uma leitura), padrão (loop
  contínuo a `--hz`), `-v` (trace do pyprofibus). Bom para o **primeiro contato** com o
  encoder e diagnóstico DP.

### `serve.py` — o servidor web
- **`build_controller(conf, encoder, sim, bus_json, addresses)`**: monta o `BusController`
  de produção. Define as factories: `make_exchange` cria `Amg11Master` (com baud/endereço
  das settings) embrulhado num `EncoderPoller`; `make_probe` cria `FdlBusProbe` real (ou
  `SimBusProbe` no `--sim`). Carrega `BusSettings` do `bus.json` (default vindo do `.conf`).
- **`main()`**: monta o controller + `GsdStore(gsd/)`, sobe o Flask (`create_app`,
  `threaded=True`) e garante `controller.stop()` no fim. Porta padrão **8600**.

---

## 7. Frontend: `web/static/`

Preact + `htm` **vendorizados** (ESM locais, **sem npm/build**), CSS autoral com *tokens*,
fontes `.woff2` self-hosted. Tema escuro de instrumento, **um acento**, **sem emoji**,
contraste AA, respeita `prefers-reduced-motion`.

- **`index.html`**: `importmap` mapeando `preact`/`preact/hooks`/`htm` para `/vendor/*`,
  `<div id="app">`, `app.js` como módulo.
- **`app.js`**:
  - `useBusSocket()`: abre o WebSocket, roteia por `type` (`reading`→encoder, `bus`→
    barramento), reconecta sozinho, e expõe `send(obj)`.
  - `EncoderView`: mostrador circular (agulha + numerais em mono), linhas
    bruto/bytes/offset/diag, botões "Zerar aqui"/"Desfazer".
  - `BusView`: dropdown de baud (com **aviso honesto** sobre o teto do Pi), endereço do
    mestre, "Aplicar"; botão "Varrer" com barra de progresso e tabela das estações.
  - `GsdView`: enviar `.gsd` (`FormData` → `POST /api/gsd`), lista, inspetor, e **preview**
    (escolher módulo → `POST .../preview` → ident + cfg/prm em hex).
  - `App`: as três abas + roteamento de vista.
- **`styles.css`**: *tokens* (`--bg/--panel/--accent/--mono/...`), mostrador, abas,
  controles, tabela, progresso, aviso. **Inter banida** como default.
- **`vendor/`**: `preact.module.js`, `hooks.module.js`, `htm.module.js`, fontes
  (Space Grotesk + JetBrains Mono).

---

## 8. Configuração: `config/` e `gsd/`

- **`config/amg11.conf`** (formato do pyprofibus): `[PHY]` (`dev=/dev/serial0`, `baud`),
  `[DP]` (`master_class=1`, `master_addr`), `[SLAVE_3]` (endereço, GSD, watchdog,
  `input_size=2`/`output_size=2`, `module_0 = 16 Bit Class 2 Encoder`). Controla o **enlace**.
- **`config/encoder.yaml`**: `resolution_bits`, `direction`, `offset`, `control_word`.
  Controla o **pós-processamento** por software.
- **`config/bus.json`** (runtime, gitignored): baud + endereço do mestre persistidos pela
  aba Barramento.
- **`gsd/`**: arquivos GSD. Versionados como fixtures: `PB13DPV0.gsd` (AMG11, ident
  `0x059B`) e `IFM_0E75.gsd` (ifm, ident `0x0E75`). Uploads de runtime são **ignorados**
  pelo git (só as 2 fixtures ficam).

---

## 9. Contratos de comunicação

### WebSocket `/ws` (telemetria, ~15 Hz)
**Servidor → browser** (dois tipos por tick):
```json
{ "type":"reading", "angle_deg":90.0, "raw":2048, "raw_max":8191, "bytes_hex":"0800",
  "offset":0, "connected":true, "rate_hz":20.0, "diag":"OK", "ts":123.4 }
{ "type":"bus", "mode":"exchange", "diag":"ok",
  "settings":{"baud":19200,"master_addr":1},
  "scan":{"status":"idle","current_addr":null,"scanned":0,"total":0,"error":null,"found":[]} }
```
**Browser → servidor:** `{"cmd":"zero"}`, `{"cmd":"clear_zero"}`, `{"cmd":"scan"}`,
`{"cmd":"apply_settings","baud":19200,"master_addr":1}`.

### HTTP `/api/gsd*` (gestão de GSD)
| Método | Rota | Corpo | Resposta |
|---|---|---|---|
| GET | `/api/gsd` | — | `{"gsds":[<summary>...]}` |
| POST | `/api/gsd` | `multipart file` ou bytes + `X-Filename` | `<summary>` (200) · 400 inválido · 409 já existe · 413 grande |
| GET | `/api/gsd/<name>` | — | `<summary>` · 404 |
| POST | `/api/gsd/<name>/preview` | `{"modules":[...]}` | `<preview>` · 400 módulo inexistente · 404 |

`<summary>`: `filename, vendor, model, revision, ident, ident_hex, order, modular, dpv1,
modules:[{name,config_hex,preset}], max_tsdr:{"19200":60,...}`.
`<preview>`: `ident, ident_hex, modules, cfg_hex, user_prm_hex`.

---

## 10. A máquina de modos do `BusController`

```
        ┌──────────── apply_settings (rebuild) ────────────┐
        ▼                                                   │
   [ exchange ] ──scan()──▶ derruba motor, abre probe ──▶ [ scanning ]
        ▲                                                   │
        │            scan termina: fecha probe,             │
        └────────────  recria motor (preserva zero) ◀───────┘
        │
        └─ falha ao recriar motor ──▶ [ idle ] (diag de erro; servidor de pé)
```

- **exchange:** lê o encoder ciclicamente (motor = `EncoderPoller`). `zero`/`clear_zero`
  vão pro motor.
- **scanning:** varre 0–126 (pulando o endereço do mestre), um endereço por `step()`;
  progresso ao vivo no `bus_snapshot`.
- **idle:** porta parada (ex.: encoder ausente após um scan) — a UI mostra o diag; novo
  scan/apply ainda funciona.

**Invariante central:** scan, troca e (futuramente) parametrização **nunca** seguram a
serial ao mesmo tempo.

---

## 11. Testes

Rodar: `pytest -q` (atualmente **106 passam, 1 skip** — o skip é o teste de porta serial
real, esperado fora do Pi). Config em `pyproject.toml` (`pythonpath=["."]`).

| Arquivo | Cobre |
|---|---|
| `test_encoder.py` | decode (sentido, offset, máscara) |
| `test_config.py` / `test_conf_load.py` | EncoderConfig e parse do `.conf` |
| `test_source_fake.py` | `FakeSource` satisfaz `ReadingSource` |
| `test_poller.py` | `EncoderPoller.step()`: snapshot, zero, taxa (relógio injetado), stale |
| `test_snapshot.py` | `snapshot_to_dict` + `bus_snapshot_to_dict` |
| `test_settings.py` | `BusSettings`/`SettingsStore` (validação, round-trip) |
| `test_scan.py` | `StationType.from_fc`, `FdlBusProbe` (transceiver fake) |
| `test_scanner.py` | `BusScan` passo-a-passo (FakeProbe, FakeClock) |
| `test_controller.py` | modos, troca de dono, apply, offset preservado, erros |
| `test_server.py` | rotas + `handle_ws_message` |
| `test_gsd_info.py` | parse + preview das **2 GSDs reais** |
| `test_gsd_store.py` | save valida/rejeita/overwrite, path-safety |
| `test_gsd_api.py` | upload/list/get/preview, 400/404/409/413, X-Filename |
| `test_integration_sim.py` | caminho real em sim: troca → scan acha o escravo → retoma |
| `test_master_sim.py` / `test_master_overrides.py` | master no dummy + overrides baud/addr |
| `test_cli_sim.py` | a CLI no `--sim` |
| `test_frontend_assets.py` | vendor presente, sem emoji, sem Inter, abas/GSD/aviso honesto |

`tests/fakes.py` traz o `FakeSource` (leituras roteirizadas, sem hardware).

---

## 12. Roadmap A → B → C

Fundação: **v1** (dashboard do encoder + zerar).

- **A — Explorador de barramento** ✅: `BusController` (dono único da serial, modos),
  *live list* via FDL, controles de baud/endereço persistidos. (spec/plano de 2026-06-19)
- **B — Parametrizar qualquer escravo** (em andamento):
  - **B1 — Gestão/inspeção de GSD + preview** ✅: upload HTTP, inspeção, preview offline
    dos bytes de `Chk_Cfg`/`Set_Prm`. (este documento; spec/plano de 2026-06-20)
  - **B2 — Parametrizar ao vivo + I/O cru** ⏳: novo modo do `BusController` que envia
    `Set_Prm`/`Chk_Cfg`, alcança o `Data_Exchange` com a estação-alvo e mostra input cru /
    seta output cru.
- **C — Perfis declarativos** ⏳: decodificar o I/O cru em grandeza de engenharia por um
  perfil de device (o `decode` do AMG11 vira "só mais um perfil").

Specs e planos detalhados em `docs/superpowers/specs/` e `docs/superpowers/plans/`.

---

## 13. Limitações honestas

- **Teto de baud:** o pyprofibus é mestre em **Python puro**; em **Linux não-RT** o timing
  de slot só é confiável em baud moderado. Provado em **19200**; acima é best-effort e
  tende a falhar. A UI deixa escolher, **mas avisa** — não promete 12 Mbit. Para alta
  velocidade real, uma PHY dedicada (FPGA) seria necessária.
- **Físico:** assume transceiver **3,3 V** (o GPIO do Pi não tolera 5 V) e módulo de
  **auto-direção** (a via `.conf` do pyprofibus não controla DE/RE por RTS). Ver alertas
  no [README](../README.md).
- **Escopo do encoder:** singleturn 13-bit, um escravo, **DPV0** (sem acesso acíclico).
- **Mestre único:** a varredura assume que somos o único mestre no barramento.
- **`control_word`:** os 2 B mestre→escravo existem para sustentar o `Data_Exchange`; a
  semântica de preset/scaling no perfil Baumer **não está confirmada** (ver checklist do
  README).
- **Reendereçar escravo pelo barramento** (`Set_Slave_Address`): **não existe** no
  pyprofibus → fora de escopo.

---

## 14. Glossário PROFIBUS

- **DP / DPM1:** Decentralized Periphery; mestre classe 1 (troca cíclica de I/O).
- **GSD:** arquivo-texto que descreve um escravo (ident, módulos, parâmetros, timings).
- **Ident_Number:** identificador do tipo de dispositivo; tem que bater na parametrização.
- **FDL:** camada 2 (enlace). O *Request-FDL-Status* é o que usamos para o *live list*.
- **Set_Prm / Chk_Cfg / Data_Exchange:** parametrizar → checar config → trocar I/O.
- **Live list:** o conjunto de estações que respondem no barramento.
- **PHY:** camada física. Aqui, serial RS485 via UART do Pi.
- **MaxTSDR:** atraso máximo de resposta da estação, por baud (vem do GSD).
- **Watchdog:** se o mestre some, o escravo cai para um estado seguro após o timeout.
