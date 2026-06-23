# Documentação — Comissionador PROFIBUS-DP no Raspberry Pi

> Documento mestre do projeto. Explica **o que é**, **como rodar**, a **arquitetura**,
> e **cada arquivo do código** (o que faz, como funciona, como usar, de que depende),
> além do **conhecimento PROFIBUS** necessário para entender por que as coisas são como
> são. Para fiação e checklist de campo, ver também o [README](../README.md).
>
> Estado: domínio + web + frontend completos; fases **A**, **B1** e **B2** implementadas
> e cobertas por testes. Última grande adição: **parametrização de escravo genérico via
> GSD** (B2) e **visualização ao vivo** do encoder genérico (incl. o multivolta IFM
> RM3007).

---

## Sumário

1.  [Visão geral e objetivo](#1-visão-geral-e-objetivo)
2.  [Arquitetura em camadas](#2-arquitetura-em-camadas)
3.  [Como rodar](#3-como-rodar)
4.  [Fase A — Explorador de barramento (scan FDL)](#4-fase-a--explorador-de-barramento-scan-fdl)
5.  [Fase B1 — Gestão e inspeção de GSD](#5-fase-b1--gestão-e-inspeção-de-gsd)
6.  [Fase B2 — Parametrização de escravo genérico](#6-fase-b2--parametrização-de-escravo-genérico)
7.  [Conhecimento PROFIBUS essencial](#7-conhecimento-profibus-essencial)
8.  [Caso prático: comissionar o IFM RM3007](#8-caso-prático-comissionar-o-ifm-rm3007)
9.  [Limitações conhecidas e gotchas do pyprofibus](#9-limitações-conhecidas-e-gotchas-do-pyprofibus)
10. [Referência de arquivos (mapa do repo)](#10-referência-de-arquivos-mapa-do-repo)
11. [Roadmap e próximos passos](#11-roadmap-e-próximos-passos)
12. [Glossário PROFIBUS](#12-glossário-profibus)

---

## 1. Visão geral e objetivo

Um **Raspberry Pi 3** atua como **mestre PROFIBUS-DP classe 1 (DPM1)** usando a biblioteca
**pyprofibus** (mestre 100% Python). A camada física é um **módulo RS485↔TTL** ligado
direto na **UART de hardware** do Pi (`/dev/serial0`). O dispositivo de referência é um
encoder absoluto **Baumer/Hübner AMG 11 P 13** (singleturn 13-bit), e a ferramenta evoluiu
para **parametrizar e ler qualquer escravo DP** a partir do seu arquivo GSD — validado
também contra um encoder **multivolta IFM RM3007**.

> **Por que a pasta se chama `pi5-`?** Legado: o projeto nasceu mirando o Pi 5 + USB-RS485,
> mas migrou para **Pi 3 + UART de GPIO**. O nome da pasta ficou; tudo o mais reflete o Pi 3.

O projeto tem **duas faces**:

- **CLI** (`run.py`): lê a posição do encoder no terminal e varre o barramento. Bom para
  o primeiro contato e diagnóstico de baixo nível.
- **Ferramenta web de comissionamento** (`serve.py`): um painel com **três abas**:
  - **Encoder** — leitura ao vivo do AMG11 (ângulo, bruto, bytes, taxa, diagnóstico) +
    "zerar aqui" / "desfazer".
  - **Barramento** — varredura (*live list* 0–126) + controles de baud/endereço do mestre,
    persistidos.
  - **GSD** — enviar/inspecionar arquivos `.gsd`, pré-visualizar a parametrização **offline**
    e, ao vivo, **parametrizar um escravo genérico** e ver seu **I/O cru** + um **mostrador**
    estilo Baumer que decodifica posição/voltas/ângulo.

Tudo roda **sem hardware** no modo simulação (`--sim`, PHY dummy do pyprofibus), o que
torna desenvolvimento e testes independentes do barramento real.

**Teto de baud (limitação honesta de cara):** pyprofibus é mestre em **Python puro** sob
**Linux não-RT**; o timing de slot só é confiável em baud moderado. **Apenas 9600 e 19200**
são confiáveis no Pi 3; acima é *best-effort*. A UI deixa escolher qualquer baud permitido
**mas avisa**.

**Princípios de engenharia:** SOLID (camadas com interfaces `Protocol`), TDD (lógica em
funções `step()` determinísticas, relógio e dependências injetados, *fakes* no lugar de
hardware), honestidade técnica (limitações documentadas, não maquiadas).

---

## 2. Arquitetura em camadas

A regra de ouro é **separar responsabilidades** e **depender de abstrações** (DIP). Só o
domínio (`profibus_amg11/`) conhece o pyprofibus.

```
┌────────────────────────────────────────────────────────────────────────────┐
│ FRONTEND (Preact + htm vendorizados, sem build)  web/static/                 │
│   3 abas: Encoder · Barramento · GSD                                         │
└───────────────┬──────────────────────────────────────────┬─────────────────┘
        WebSocket /ws (telemetria 3 frames/tick)   HTTP /api/gsd* (CRUD de GSD)
                │                                          │
┌───────────────▼──────────────────────────────────────────▼─────────────────┐
│ TRANSPORTE  web/server.py (Flask + flask-sock)                              │
│   create_app(controller, gsd_store) — NÃO conhece pyprofibus                 │
└───────────────┬──────────────────────────────────────────┬─────────────────┘
                │ usa                                        │ usa
┌───────────────▼──────────────┐               ┌────────────▼─────────────────┐
│ SERVIÇO  web/controller.py   │               │ web/gsd_store.py (.gsd em     │
│ BusController: DONO ÚNICO da  │               │ disco) valida por parse ──┐   │
│ serial, modos:               │               └───────────────────────────│───┘
│   exchange / scanning /       │                                           │
│   generic / idle.             │                                           │
│ Publica snapshots imutáveis.  │                                           │
└──┬──────────┬──────────┬──────┘                                           │
   │ make_     │ make_     │ make_generic                                    │
   │ exchange  │ probe     │ (opcional)                                      │
┌──▼─────────┐┌▼──────────┐┌▼────────────────┐  ┌──────────────────────────▼──┐
│ Exchange   ││ BusProbe  ││ GenericEngine   │  │ DOMÍNIO  profibus_amg11/     │
│ Engine     ││ (Protocol)││ (Protocol)      │  │  encoder.decode (puro)        │
│ (Protocol) ││ =Fdl/Sim  ││ =GenericPoller  │  │  master.Amg11Master           │
│ =Encoder   ││  BusProbe ││  → GenericDp    │  │  generic.GenericDpMaster      │
│  Poller    ││           ││     Master      │  │  scan.FdlBusProbe / SimBusProbe│
└──┬─────────┘└─┬─────────┘└─┬───────────────┘  │  gsd_info.decode_cfg_io/...   │
   └──────┬──────┴────────────┘                 │  (única camada que conhece    │
          ▼                                      │   pyprofibus)                 │
   pyprofibus (FDL, DP, GSD, PHY serial)  ←→ RS485 ←→ escravos                  │
                                                 └───────────────────────────────┘
```

### 2.1 Os quatro modos do `BusController` (single-serial-owner)

A **invariante central** do sistema: **só existe um dono da serial por vez**. Varrer,
trocar dados com o encoder e parametrizar um escravo genérico são **mutuamente exclusivos**
na mesma porta. O `BusController` (`web/controller.py`) materializa isso como uma máquina
de estados de quatro modos, tudo numa **única thread de trabalho**:

```
                apply_settings (rebuild p/ novo baud/addr)
                  ┌───────────────────────────────────────┐
                  ▼                                         │
   ┌─────────────────────────────┐  scan()    ┌──────────────────────┐
   │        exchange             │ ─────────▶ │      scanning        │
   │ (EncoderPoller lê o AMG11)  │            │ varre 0..126 (FDL),  │
   │ zero / clear_zero           │ ◀───────── │ 1 addr por step()    │
   └─────────────────────────────┘  fim do     └──────────────────────┘
        ▲           │   param_read       scan: fecha probe,
        │           │ ───────────▶ recria motor (preserva offset)
        │           ▼
        │   ┌─────────────────────────────┐
        │   │         generic             │  scan() durante generic → derruba generic
        │   │ GenericDpMaster parametriza │  stop_generic → volta para exchange
        │   │ e troca I/O cru (sem decode)│
        │   └─────────────────────────────┘
        │
        └─ falha ao (re)criar o motor de exchange ──▶ idle (diag de erro; servidor de pé)
```

- **exchange** — modo inicial. Motor = `EncoderPoller` (atrás do Protocol `ExchangeEngine`).
  Lê o encoder ciclicamente; `zero`/`clear_zero` são repassados ao motor.
- **scanning** — varre 0–126 (pulando o `master_addr`), **um endereço por `step()`**;
  progresso ao vivo no `bus_snapshot`. Ao terminar, fecha a probe e **recria** o motor de
  exchange (preservando o `offset` da sessão).
- **generic** — parametriza um escravo a partir de um GSD em memória e troca **I/O cru**
  (`GenericPoller` atrás do Protocol `GenericEngine`, sobre `GenericDpMaster`). Publica um
  `IoSnapshot` (in/out hex, tamanhos, taxa, diag).
- **idle** — única origem: **falha ao iniciar o motor de exchange** (ex.: encoder ausente).
  A serial fica parada, a UI mostra o diag de erro e o **servidor não cai**; novo
  scan/apply/param ainda funciona.

### 2.2 Padrões transversais

- **Publish-imutável-sob-lock.** Todo estado mutável é tocado **só pela thread do
  controller**. O que a web lê são dataclasses **`frozen=True`** publicadas **sob `lock`**
  (`encoder_snapshot()`, `bus_snapshot()`, `io_snapshot()`). O objeto é montado **fora** do
  lock; o lock guarda apenas a atribuição da referência. Sem corrida, sem leitura rasgada.
- **Comandos enfileirados.** A thread web nunca executa lógica: `scan()`,
  `apply_settings()`, `zero()`, `clear_zero()`, `param_read()`, `set_output()`,
  `stop_generic()` apenas fazem `with lock: _pending.append(...)`. O `step()` drena a fila
  com swap atômico (`cmds, _pending = _pending, []`) e executa **fora** do lock.
- **`step()` determinístico.** Toda a lógica vive em `step()`; a thread só repete `step()`.
  Isso permite testar a máquina de modos **sem threads e sem `sleep`**, com relógio injetado.
- **Protocols + factories injetadas.** O controller recebe `make_exchange(settings, offset)`,
  `make_probe(settings)` e `make_generic(settings, spec)` (opcional). Nada de pyprofibus
  dentro dele — em teste, *fakes*; em produção, as factories do `serve.py`.
- **Fakes nos testes.** `FakeSource`, `FakeProbe`, `FakeEngine`, `FakeGenericEngine`,
  `FakeGenericSource`, `FakeTransceiver`, `FakeClock`, `FakeController` permitem cobrir o
  sistema inteiro sem hardware nem pyprofibus.

---

## 3. Como rodar

```bash
cd ~/repos/pi5-profibus-amg11
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # pyprofibus, pyserial, PyYAML, flask, flask-sock

# CLI sem hardware (valida o pipeline):
python run.py --sim --once

# Varredura de barramento pelo terminal (sem hardware):
python run.py --scan --sim

# Web sem hardware (abre as 3 abas):
python serve.py --sim                     # http://localhost:8600

# Com hardware real (após setup do Pi — ver README):
python run.py --hz 20                     # CLI contínua
python serve.py                           # painel web

# Testes:
.venv/bin/python -m pytest -q             # 130 passed, 1 skipped
```

### Flags do `serve.py` (servidor web)

| Flag | Default | Descrição |
|---|---|---|
| `--host` | `0.0.0.0` | endereço de bind |
| `--port` | `8600` | porta HTTP/WebSocket |
| `--conf` | `config/amg11.conf` | `.conf` do pyprofibus (PHY/DP/escravo) |
| `--encoder` | `config/encoder.yaml` | pós-processamento do AMG11 |
| `--sim` | (off) | PHY dummy — sem hardware RS485 |

### Flags do `run.py` (CLI)

| Flag | Default | Descrição |
|---|---|---|
| `--conf` | `config/amg11.conf` | `.conf` do pyprofibus |
| `--encoder` | `config/encoder.yaml` | pós-processamento |
| `--sim` | (off) | PHY dummy |
| `--scan` | (off) | varre o barramento (live list FDL) e sai |
| `--baud` | `None` | baud da varredura (se omitido, usa o do `.conf`) |
| `--scan-timeout` | `0.1` s | timeout por endereço na varredura |
| `--retries` | `2` | tentativas por endereço na varredura |
| `--once` | (off) | lê uma vez e sai |
| `--hz` | `20.0` | taxa de leitura no modo contínuo (deve ser > 0) |
| `-v/--verbose` | (off) | trace de debug do pyprofibus |

Modos do `run.py`: `--scan` (varre e sai) > `--once` (1 leitura) > contínuo (default, a
`--hz`, encerra com Ctrl-C).

### O modo `--sim`

No `--sim`, o pyprofibus usa uma PHY dummy. O `Amg11Master` em sim responde o
`Data_Exchange` com `control_word XOR 0xFFFF` (útil para testes determinísticos); a probe
de scan vira `SimBusProbe`, que "encontra" os endereços de escravos declarados no `.conf`
(o AMG11 está em addr 3). Permite exercitar a ferramenta inteira sem barramento.

---

## 4. Fase A — Explorador de barramento (scan FDL)

**Objetivo:** descobrir quem está vivo no barramento (*live list*) sem precisar de
parametrização. O pyprofibus não traz scan pronto, então ele é construído sobre o **FDL**
(camada 2) usando **Request-FDL-Status**.

### Domínio: `profibus_amg11/scan.py`

- `StationType` (enum): `slave`, `master_not_ready`, `master_ready`, `master_in_ring`,
  `unknown`. `StationType.from_fc(fc)` decodifica o byte **FC** da resposta (mascarado por
  `FC_STYPE_MASK`) no tipo de estação.
- `Station` (frozen): `addr`, `station_type`, `response_ms`.
- `BusProbe` (Protocol, `@runtime_checkable`): `probe(addr) -> Station | None`, `close()`.
- `FdlBusProbe` — probe real. Monta `FdlTelegram_FdlStat_Req(da=addr, sa=master)`, envia
  via `FdlTransceiver`, **polla em laço** (`poll(poll_slice)`) até `deadline`, valida que o
  `sa` da resposta bate com o endereço sondado e mede o tempo de resposta.
- `SimBusProbe` — sem hardware; reporta `SLAVE` nos endereços de uma lista (caminho `--sim`).

### A correção de timing crítica: `releaseBus()` + loop de poll

Esta é a peça load-bearing do scan (`scan.py:59-78`):

```python
def probe(self, addr):
    # Libera a reserva de barramento do endereço anterior. Sem isso, o
    # maxReplyLen=255 do FdlTransceiver segura ~146 ms @ 19200 e dessincroniza
    # envio/leitura (o próximo probe pisa na janela de espera do anterior).
    if self._phy is not None:
        self._phy.releaseBus()
    req = FdlTelegram_FdlStat_Req(da=addr, sa=self._master_addr)
    start = self._now()
    self._trans.send(FdlFCB(enable=False), req)   # FCB off: sem sequência/retentativa
    deadline = start + self._timeout
    while True:                                    # polla como o mestre DP faz
        ok, tel = self._trans.poll(self._poll_slice)
        if (ok and tel is not None and tel.sa is not None
                and (tel.sa & FdlTelegram.ADDRESS_MASK) == addr):
            return Station(addr=addr,
                           station_type=StationType.from_fc(tel.fc or 0),
                           response_ms=(self._now() - start) * 1000.0)
        if self._now() >= deadline:
            return None
```

- **`releaseBus()` antes de cada probe** é o fix sem o qual a varredura "não achava nada"
  (commit `1bb2862`): a reserva do FDL com `maxReplyLen=255` segura o ciclo e gera timeouts
  falsos.
- **FCB desabilitado** — Request-FDL-Status não usa Frame Count Bit; é só "quem está em
  `addr`?".
- **Match por `sa`** — descarta respostas de outros endereços/ruído na janela.

### App: `web/scanner.py`

Lógica de varredura **pura**, sem pyprofibus e sem `sleep`:

- `ScanState` (frozen): `status` (idle/scanning/done), `current_addr`, `scanned`, `total`,
  `found`, `started_ts`, `done_ts`, `error`.
- `BusSnapshot` (frozen, **mora aqui**, não em `snapshot.py`): `mode`, `settings`,
  `scan_state`, `diag` — é o snapshot agregado que o `BusController` publica.
- `BusScan(probe, addresses, now)`: `step()` sonda **um** endereço por chamada; `done`
  indica fim. Relógio injetado → testável com `FakeProbe`/`FakeClock`.

### Fluxo no controller

`scan()` (comando) → `_begin_scan`: derruba generic (dono único), derruba o motor de
exchange, abre a probe (`make_probe`), entra em `scanning`. `_scan_step()` avança um
endereço por `step()`; ao terminar, fecha a probe e chama `_start_exchange()` (recria o
motor). Falha ao abrir a probe → `ScanState(status="done", error=...)` + volta a exchange.

### CLI: `run.py --scan`

`scan_bus()` varre `0..126` (pulando o `master_addr`), com até `--retries` tentativas por
endereço e `--scan-timeout` por tentativa, e loga `addr / tipo / ms`.

---

## 5. Fase B1 — Gestão e inspeção de GSD

**Objetivo:** uma biblioteca de arquivos GSD com upload, inspeção e **preview de
parametrização totalmente offline** (sem tocar o barramento). É o pré-requisito da B2.

### Domínio: `profibus_amg11/gsd_info.py` (parser canônico + preview)

Wrap puro sobre `GsdInterp` do pyprofibus. Contém a **fonte de verdade do parser do byte
de config** (`decode_cfg_io`, ver §7).

- `parse_gsd(data, filename) -> GsdSummary`: usa `GsdInterp.fromBytes`, **exige
  `Ident_Number`** (senão `GsdInfoError`), extrai `vendor`, `model`, `revision`, `ident`,
  `order`, `modular`, `dpv1`, lista de módulos (`name` + `config_hex` + `preset`) e a tabela
  `max_tsdr` por baud.
- `preview_params(data, module_names) -> ParamPreview`: escolhe módulo(s)
  (`clearConfiguredModules` + `setConfiguredModule`) e computa, **sem efeitos colaterais**:
  - `ident`,
  - `cfg_hex` — os bytes de **`Chk_Cfg`** (`getCfgDataElements().getDU()`),
  - `user_prm_hex` — os bytes de **`Set_Prm`** (`getUserPrmData()`),
  - `in_size` / `out_size` — derivados por `decode_cfg_io` (ótica do mestre: in = lê, out =
    escreve).
- `*_to_dict`: serialização pura para JSON (`summary_to_dict`, `preview_to_dict`,
  `module_to_dict`); `max_tsdr` tem chaves stringificadas (chaves JSON válidas).

### App: `web/gsd_store.py` (persistência segura)

- `save(filename, data)` — **valida por parse** (rejeita não-GSD), recusa **sobrescrever**
  (`FileExistsError`, protege fixtures), e tem **path-safety**: regex
  `^[A-Za-z0-9._-]+\.gsd$` + rejeição de `/`, `\`, `..`.
- `list()` (só `.gsd`, ordenado), `read(name)`, `summary(name)`.

### App: `web/gsd_api.py` (CRUD HTTP)

`register_gsd_routes(app, store)` separa o CRUD de GSD do WebSocket de telemetria:

| Método | Rota | Corpo | Resposta |
|---|---|---|---|
| GET | `/api/gsd` | — | `{"gsds":[<summary>...]}` (parse falho → `{"filename","error":"parse"}`) |
| POST | `/api/gsd` | `multipart file` ou bytes + `X-Filename` | `<summary>` · 400 inválido/sem arquivo · 409 já existe · 413 grande |
| GET | `/api/gsd/<name>` | — | `<summary>` · 404 · 400 inseguro |
| POST | `/api/gsd/<name>/preview` | `{"modules":[...]}` | `<preview>` · 400 módulo inexistente · 404 |

`MAX_CONTENT_LENGTH` = 2 MiB no `create_app` (corta corpo gigante → 413, defesa anti-DoS).

### Frontend: aba GSD (parte B1)

- **Upload**: `<input type="file" accept=".gsd">` → `FormData` → `POST /api/gsd`; erro vira
  `.warn`.
- **Lista**: tabela `Arquivo / Modelo / Ident` (clicável → abre o inspetor).
- **Inspetor** (`GET /api/gsd/<name>`): `fabricante`, `modelo`, `ident`, `tipo`
  (modular/compacto + `· DPV1`), lista de módulos (checkbox, filtrando os `preset`).
- **Preview** (`POST .../preview` quando um módulo é marcado): `ident`, `cfg (Chk_Cfg)`,
  `user_prm (Set_Prm)`, e **`lê / escreve  in_size B / out_size B`**.

---

## 6. Fase B2 — Parametrização de escravo genérico

**Objetivo:** com um GSD já na biblioteca, **parametrizar um escravo real ao vivo**
(`Set_Prm` → `Chk_Cfg` → `Data_Exchange`) e mostrar o **I/O cru** mais um **mostrador**
decodificado — tudo a partir do GSD, sem código específico do dispositivo. Validado contra
o Baumer (addr 3) e o **IFM RM3007** (addr 9).

### 6.1 Fluxo completo de ponta a ponta

```
[aba GSD]                 [WebSocket]            [BusController]              [GenericPoller]            [GenericDpMaster]            [pyprofibus]
  marcar módulo  ── POST .../preview ──▶ lê/escreve (in_size/out_size)
  "Parametrizar e ler"
      │
      └─ send({cmd:"param_read",      ─────▶ handle_ws_message
                gsd, address, modules})        └─ controller.param_read(dict)
                                                     enfileira ("param", dict)
                                               step() drena → _begin_generic(dict)
                                                 ParamSpec(gsd, address, modules)
                                                 _teardown_engine()
                                                 _generic = make_generic(settings, spec) ─────────────▶ GenericPoller(src, addr,
                                                                                                          src.input_size,
                                                                                                          src.output_size)
                                                                              src = GenericDpMaster(...) ─────────────▶ makeDPM(phy) (mestre vazio)
                                                                                                                       make_generic_slave_desc(gsd_bytes,
                                                                                                                         address, modules)
                                                                                                                       addSlave(); initialize()
                                                 _mode="generic", diag="parametrizando"
  cada tick: step() (modo generic) ─────────────────────────────────────────▶ poller.step() ──────────▶ src.poll():
                                                                                  data = source.poll()      setMasterOutData(_out)
                                                                                  IoSnapshot(active=True,    master.run() (1 passo DP)
                                                                                    in_hex, out_hex,         getMasterInData() → bytes crus
                                                                                    input_size, output_size,
                                                                                    connected, diag, rate_hz)
  _publish_io() (sob lock)
      │
[WebSocket /ws] ◀── io_snapshot_to_dict ── {type:"io", active, address, in_hex, out_hex, input_size, output_size, connected, diag, rate_hz}
      │
[GsdView] decodePosition(io.in_hex, spt) → gauge (ponteiro+graus) + voltas/na-volta/posição/bytes
```

Comandos extras no modo generic:
- `set_output` → `controller.set_output(hex)` → `_do_set_output`: valida o tamanho do hex
  contra `_generic.snapshot().output_size` (rejeita **antes** de o `poll()` lançar `DpError`)
  e repassa a `source.set_output`.
- `stop_generic` → `_teardown_generic()` + `_start_exchange()` (volta ao encoder AMG11).

### 6.2 Domínio: `profibus_amg11/generic.py`

- `GenericError(Exception)` — fronteira de erro estável (encapsula `GsdError` do parser).
- `make_generic_slave_desc(gsd_bytes, address, modules)` — monta um `DpSlaveDesc`
  manualmente (o `Amg11Master` usa `slaveConfs[0].makeDpSlaveDesc()`; aqui o desc é
  construído à mão). Seleciona módulos (`clearConfiguredModules` + `setConfiguredModule`),
  deriva os tamanhos por `decode_cfg_io` e **faz a inversão escravo-cêntrica** (ver §7.2):

  ```python
  read, write = decode_cfg_io(cfg)         # ótica do MESTRE: read=lê, write=escreve
  if write <= 0:
      raise GenericError("módulo só-leitura (mestre escreve 0 B) não é suportado; "
                         "escolha um módulo com saída (Class 2 ou ifm)")
  # convenção ESCRAVO-CÊNTRICA do pyprofibus (cruzado de propósito):
  conf = _GenericSlaveConf(gsd, address, input_size=write, output_size=read)
  ```

- `GenericDpMaster` — DPM1 de **um** escravo genérico; troca DX e expõe I/O cru. Satisfaz o
  Protocol `GenericSource` (poll/set_output/connected/diag/close). Após montar o desc,
  **desfaz** o cruzamento para reexpor na ótica do mestre (intuitiva):

  ```python
  self.input_size  = self.slave.outputSize   # mestre LÊ  (posição)
  self.output_size = self.slave.inputSize    # mestre ESCREVE (preset/controle)
  self._out = bytearray(self.output_size)    # buffer de saída do tamanho de ESCRITA
  ```

  - `poll()` retorna **bytes crus** (sem decode) e re-arma `_out` por ciclo (sustenta o DX).
  - `set_output(data)` troca o buffer; `connected` vem de `slave.isConnected()`;
    `diag` é `"OK"` se conectado, senão `"conectando"`.
  - `_chdir` (reusado de `master.py`) garante `cwd = conf_path.parent.parent` para o GSD
    relativo do `.conf` resolver; cleanup em falha (`self.close(); raise`) — sem vazar PHY.

### 6.3 App: `web/generic_poller.py` + `web/snapshot.py`

- `ParamSpec` (frozen): `gsd`, `address`, `modules`. **Sem tamanhos** — eles são derivados
  do GSD (comentário explícito no código). Construído em `_begin_generic`.
- `GenericSource` (Protocol, `@runtime_checkable`): `poll() -> bytes|None`, `set_output`,
  `connected` (prop), `diag` (prop), `close`.
- `GenericPoller(source, address, input_size, output_size, ...)` — motor do modo generic.
  `step()` lê `source.poll()`, calcula a taxa (EWMA `0.8/0.2`), monta um `IoSnapshot`
  (`active=True`, `in_hex`, `out_hex` preservado, `connected`, `diag`, `rate_hz`). Estados
  derivados por staleness (`"conectando"`/`"OK"`/`"sem leitura"` via `stale_after`). Satisfaz
  o Protocol `GenericEngine`.
- `IoSnapshot` (frozen, em `snapshot.py`): `active`, `address`, `connected`, `diag`,
  `in_hex`, `out_hex`, `input_size`, `output_size`, `rate_hz`, `ts`.
  `io_snapshot_to_dict` → contrato `type:"io"`; `idle_io_snapshot()` → inativo (usado fora
  do modo generic).

### 6.4 Wiring: `serve.py make_generic`

```python
def make_generic(s, spec):
    data = gsd_store.read(spec.gsd)            # FileNotFoundError/GsdInfoError → idle no controller
    src = GenericDpMaster(conf_path, data, spec.address, list(spec.modules),
                          baud=s.baud, master_addr=s.master_addr, sim=sim)
    return GenericPoller(src, spec.address, src.input_size, src.output_size)
    #                                       ^^ tamanhos DERIVADOS do GSD (mestre lê/escreve)
```

### 6.5 Frontend: aba GSD (parte B2 — parametrizar, I/O e visualização)

Estado local do `GsdView`: `sel` (GSD aberto), `chosen` (módulos marcados), `preview`,
`addr` (alvo, default 3), `outHex` (saída a enviar), `spt` (passos/volta, default **8192**
= RM3007).

- **Botão "Parametrizar e ler"** — `disabled = chosen.length===0 || readonly`;
  `send({cmd:"param_read", gsd:sel.filename, address:addr, modules:chosen})`.
- **`readonly`** = `preview && chosen.length>0 && preview.out_size===0` — módulo só-leitura
  (mestre escreve 0 B). Mostra um `.warn` explicando que esse é o perfil correto (Class 1)
  mas o pyprofibus **não pollar escravo só-leitura**, orientando **Class 2 Multiturn** (4 B
  de saída zerados, sem preset).
- **`paramErr`** — espelha `bus.diag` na aba GSD quando contém a palavra "parametrizar"
  (erros de parametrização chegam pelo diag do **Barramento**; sem isso, "nada acontecia"
  na aba GSD — bug #3 corrigido).
- **Painel de I/O com gauge** (só se `io.active`) — reusa o `.gauge` (mesmo CSS do
  EncoderView). `decodePosition(io.in_hex, spt)` decodifica os bytes big-endian:

  ```js
  function decodePosition(hex, stepsPerTurn) {
    if (!hex || hex.length < 2) return null;
    const spt = stepsPerTurn > 0 ? stepsPerTurn : 8192;       // fallback RM3007
    const value = parseInt(hex, 16);                          // 1..4 bytes, MSB primeiro
    if (!Number.isFinite(value)) return null;
    const single = ((value % spt) + spt) % spt;               // módulo seguro
    return { value, single, stepsPerTurn: spt,
             turns: Math.floor(value / spt),
             angle: (single / spt) * 360,
             multiturn: hex.length / 2 >= 4 };                 // ≥4 bytes ⇒ multivolta
  }
  ```

  O painel mostra: **dial + ponteiro** rotacionado por `angle`, graus, e linhas `voltas`
  (só multivolta), `na volta` (single/spt), `posição` (value), `bytes` (hex). Há um campo
  **"passos/volta"** (default 8192) que alimenta o decode, um campo **"Saída (hex)"** e
  botões **Enviar saída** / **Parar**.

  Verificado: `09b0` → 109° / 0 voltas / single; `000209b0` → 109° / 16 voltas / multivolta.

---

## 7. Conhecimento PROFIBUS essencial

Esta seção é a "teoria" que explica os bugs e contornos das fases B2 e do RM3007.

### 7.1 O byte identificador / config dos módulos (`decode_cfg_io`)

Cada módulo de um GSD modular tem um **byte identificador** (config byte) que aparece no
`Chk_Cfg`. Ele codifica direção, unidade e quantidade. `gsd_info.decode_cfg_io(cfg_bytes)`
percorre os bytes e devolve **`(read, write)` na ótica do MESTRE** (read = entrada/posição,
write = saída/preset).

**Formato geral** (a maioria dos módulos de encoder):

| Bit | Máscara | Significado |
|---|---|---|
| consistência | `0x80` | consistência sobre todo o comprimento |
| word/byte | `0x40` | unidade = word (2 B) se setado; byte (1 B) caso contrário |
| saída (OUT) | `0x20` | mestre **escreve** (entrada do escravo) |
| entrada (IN) | `0x10` | mestre **lê** (saída do escravo) |
| nibble baixo | `0x0F` | **(nº de unidades − 1)** |

Cálculo: `size = ((iden & 0x0F) + 1) * (2 if iden & 0x40 else 1)`; soma em `read` se o bit
IN, em `write` se o bit OUT (um byte pode ter ambos).

**Formato especial** (quando `(iden & 0x30) == 0x00`): o nibble baixo é o **nº de
length-bytes que seguem**, e o campo `0xC0` indica direção (`OUT`/`IN`/`INOUT`). Em `INOUT`
vem **primeiro a saída (write), depois a entrada (read)** — trocar a ordem inverte os
tamanhos silenciosamente.

**Tabela dos módulos relevantes** (decodificada para os GSDs reais):

| GSD / módulo | config byte | `(read, write)` mestre |
|---|---|---|
| Baumer `16 Bit Class 1 Encoder` | `0xD0` | 2 / 0 |
| Baumer `16 Bit Class 2 Encoder` | `0xF0` | 2 / 2 |
| IFM Class 1 Singleturn | `0xD0` | 2 / 0 |
| IFM Class 1 Multiturn | `0xD1` | 4 / 0 |
| IFM Class 2 Singleturn | `0xF0` | 2 / 2 |
| IFM Class 2 Multiturn | `0xF1` | 4 / 4 |
| IFM 2.1 Single/Multi | `0xF1` | 4 / 4 |
| IFM 2.2 Single/Multi | `0xF1`,`0xD0` | 6 / 4 |

> Mnemônico: `0xDn` = só-leitura (Class 1, mestre escreve 0); `0xFn` = leitura+escrita
> (Class 2). O nibble baixo +1 vezes 2 B (bit word) dá o nº de bytes: `0xF0` → (0+1)·2 = 2;
> `0xF1` → (1+1)·2 = 4.

### 7.2 A convenção ESCRAVO-CÊNTRICA do pyprofibus (a pegadinha)

No pyprofibus, `inputSize`/`outputSize` do `slaveConf`/`DpSlaveDesc` são do **ponto de vista
do ESCRAVO** — o inverso da intuição "mestre-centrica":

| Campo pyprofibus | Significado | Ótica do mestre |
|---|---|---|
| `slaveDesc.inputSize` | entrada **do escravo** | bytes que o **mestre ESCREVE** (preset/controle) |
| `slaveDesc.outputSize` | saída **do escravo** | bytes que o **mestre LÊ** (posição) |

Evidência no código do pyprofibus:
- `_setToSlaveData` (`dp_master.py:843-855`) valida `len(data) != slaveDesc.inputSize` — ou
  seja, o que o mestre **escreve** é checado contra `inputSize`.
- `run()` (`dp_master.py:829-839`) valida `len(fromSlaveData) != slaveDesc.outputSize` — o
  que o mestre **lê** é checado contra `outputSize`.

**A inversão na fronteira.** Os rótulos da UI são mestre-cêntricos (intuitivos:
entrada = leitura = posição; saída = escrita = preset). Logo, `make_generic_slave_desc`
**inverte na única fronteira**:

```
decode_cfg_io  →  (read, write)  [ótica do mestre]
                       │
                       ▼  inversão proposital
_GenericSlaveConf(input_size = write, output_size = read)   [ótica do escravo, p/ pyprofibus]
                       │
                       ▼  desfaz para a UI
GenericDpMaster.input_size  = slave.outputSize   (mestre lê)
GenericDpMaster.output_size = slave.inputSize    (mestre escreve)
```

> **Por que isso era um bug.** O B2 antigo pedia campos "Entrada/Saída" na UI e os passava
> **direto** para os campos do `DpSlaveDesc` sem inverter. Em módulos **simétricos**
> (Class 2 = 4/4) funcionava por acaso; com tamanhos diferentes, trocava o mapeamento e
> dava **mismatch de `Chk_Cfg`**. A correção foi derivar tudo de `decode_cfg_io` e inverter
> **só** em `make_generic_slave_desc` (bug #1). O buffer de saída também era mal-dimensionado
> (`bytearray(output_size)` com `output_size` = tamanho de leitura) → `setMasterOutData`
> lançava `DpError` no 1º poll e o painel de I/O nunca aparecia (bug #2). Agora
> `_out = bytearray(self.output_size)` com `output_size` = tamanho de **escrita**.

### 7.3 O fluxo de partida: `Set_Prm` → `Chk_Cfg` → `Data_Exchange`

A máquina de estados do pyprofibus por escravo:

```
INIT ──FdlStatus──▶ WDIAG ──SlaveDiag──▶ WPRM ──Set_Prm──▶ WCFG ──Chk_Cfg──▶ WDXRDY ──┬─ isReadyDataEx() ─▶ DX (troca cíclica)
                                                                                       └─ cfgFault()/needsNewPrmCfg() ─▶ INIT (recomeça)
```

- **`Set_Prm`** (estado WPRM): envia os `User_Prm_Data` (do GSD) + `identNumber`. Inclui
  `Ident_Number` — se não bater com o do escravo, ele rejeita.
- **`Chk_Cfg`** (estado WCFG): envia os `Cfg_Data` dos módulos escolhidos. Se o
  tamanho/módulo não bate com o que o escravo espera, o diag volta com **`cfgFault()`** e o
  ciclo **recomeça em INIT** indefinidamente, sem nunca entrar em DX.
- **`Data_Exchange`** (DX): só aqui `isConnected()` vira `True`; o mestre escreve
  `toSlaveData` e lê `fromSlaveData` por ciclo.

A construção canônica de um `DpSlaveDesc` (replicada por `make_generic_slave_desc`) é:
`DpSlaveDesc(slaveConf)` → `setCfgDataElements` → `setUserPrmData` → `setSyncMode` →
`setFreezeMode` → `setGroupMask` → `setWatchdog` (os quatro últimos **antes** da
parametrização). `inputSize`/`outputSize` e `identNumber` precisam estar setados no desc,
senão `addSlave` rejeita e o escravo não aceita o `Set_Prm`.

---

## 8. Caso prático: comissionar o IFM RM3007

Encoder absoluto **multivolta IFM RM3007 (RMK0025-E24/E)** no endereço PROFIBUS **9**, GSD
`IFM_0E75.gsd` (ident `0x0E75`). Especificação:

- **8192 passos/volta** (13 bits, singleturn),
- **4096 voltas** (12 bits, multivolta),
- **25 bits totais**; a **posição multivolta = 4 bytes (32 bits)**.

### 8.1 Perfil correto vs. o que roda no pyprofibus

O perfil "certo" do RM3007 é **Class 1 Multiturn** (`0xD1`): o mestre **lê 4 bytes de
posição e escreve 0**. Mas o pyprofibus **não suporta escravo só-leitura** (ver §9):
`addSlave` rejeita `inputSize<=0` e o loop de DX nunca envia o poll para `inputSize==0`.
Como esse é um limite de **design da lib** (não do encoder/PROFIBUS), o contorno é usar
**Class 2 Multiturn** (`0xF1`): o mestre **lê os mesmos 4 bytes** de posição multivolta e
**escreve 4 bytes zerados** (control word 0 = sem preset). A leitura é idêntica.

### 8.2 Tabela de módulos do RM3007

| Módulo | config byte | mestre lê (read) | mestre escreve (write) | roda no pyprofibus? |
|---|---|---|---|---|
| Class 1 Singleturn | `0xD0` | 2 | 0 | ❌ (só-leitura) |
| Class 1 Multiturn | `0xD1` | 4 | 0 | ❌ (só-leitura, **perfil correto**) |
| Class 2 Singleturn | `0xF0` | 2 | 2 | ✅ (perde voltas) |
| **Class 2 Multiturn** | `0xF1` | **4** | **4** | ✅ **(usar este)** |
| ifm 2.1 Single/Multi | `0xF1` | 4 | 4 | ✅ |
| ifm 2.2 Single/Multi | `0xF1`,`0xD0` | 6 | 4 | ✅ |

### 8.3 Passo-a-passo de comissionamento

1. **Subir a ferramenta**: `python serve.py` (ou `--sim` para ensaiar). Abrir a aba GSD.
2. **Garantir o GSD** `IFM_0E75.gsd` na biblioteca (upload se necessário).
3. **Abrir o GSD** e marcar o módulo **Class 2 Multiturn**. O preview deve mostrar
   `lê / escreve = 4 B / 4 B` e `cfg = f1`.
4. **Endereço**: setar `9` no campo do inspetor.
5. **"Parametrizar e ler"**. O controller entra em `generic`: `Set_Prm` → `Chk_Cfg` →
   `Data_Exchange`. Com os tamanhos batendo, em ~31 Hz aparece o painel de I/O verde.
6. **Conferir o gauge**: campo "passos/volta" = **8192** (default RM3007).

> **Sintoma do Singleturn por engano.** Na sessão de comissionamento, "entrada 09b0" = 2
> bytes indicava o módulo **Class 2 Singleturn** (`0xF0`, 2/2): `0x09B0` = 2480/8192 ≈ 109°,
> **perdendo a contagem de voltas**. Para multivolta completo é preciso o **Class 2
> Multiturn** (4 bytes).

### 8.4 Interpretação do valor (voltas + ângulo)

Os 4 bytes de posição são um inteiro big-endian de 32 bits. Com `spt = 8192`:

```
value   = parseInt(in_hex, 16)        # 32 bits
single  = value % 8192                # posição dentro da volta (0..8191)
turns   = value // 8192               # nº de voltas completas
angle   = single / 8192 * 360         # graus dentro da volta
```

Exemplo: `in_hex = 000209b0` → `value = 133552` (`0x000209B0`), `turns = 16`, `single = 2480`,
`angle ≈ 109°`. O gauge mostra o ponteiro em ~109°, `voltas 16`, `na volta 2480 / 8192`,
`posição 133552`, `bytes 000209b0`. Para o Singleturn (`09b0`, 2 bytes), o decode marca
`multiturn=false` e mostra só `na volta` (sem `voltas`).

### 8.5 A visualização

Reusa o `.gauge` estilo Baumer (`styles.css`), com o ponteiro animado (`transition:
transform .12s`). A decodificação roda **no cliente** (`decodePosition`), o que a torna um
primeiro passo concreto para a **Fase C** (perfis declarativos de decodificação): hoje o
"perfil" do RM3007 é o par (4 bytes big-endian, 8192 passos/volta) embutido na UI.

---

## 9. Limitações conhecidas e gotchas do pyprofibus

Estes são limites de **design do pyprofibus** que moldaram a ferramenta. Referências em
`.venv/.../pyprofibus/dp_master.py`.

### 9.1 `addSlave` rejeita `inputSize <= 0` (`dp_master.py:381-386`)

```python
if slaveDesc.inputSize <= 0:
    raise DpError("Slave %d: input_size=0 is currently not supported." % ...)
```

`inputSize` é o que o **mestre escreve**. Um módulo só-leitura (Class 1) tem `write==0` →
`inputSize==0` → rejeitado. Por isso `make_generic_slave_desc` tem o guard `write <= 0`,
que levanta um `GenericError` **claro** ("módulo só-leitura ... use Class 2 ou ifm") em vez
do erro críptico do pyprofibus.

### 9.2 DX nunca polla um escravo input-only (`dp_master.py:692`)

Mesmo se registrado, o loop de Data_Exchange só envia o `DpTelegram_DataExchange_Req`
quando há `toSlaveData` **e** `inputSize != 0`. Sem dados a escrever, **nenhum** request é
emitido — então um encoder só-de-leitura não pode ser pollado. É a razão técnica completa
de o RM3007 ter que rodar como **Class 2** (que escreve ≥1 byte).

### 9.3 Erros de Chk_Cfg/Set_Prm são invisíveis à API (`dp_master.py:364-365`)

```python
def __errorMsg(self, msg):
    print("DPM%d:  >ERROR<  %s" % (self.dpmClass, msg))   # só print, sem callback/exception/estado
```

A rejeição de `Chk_Cfg` (`"Slave 9 reports a faulty configuration (Chk_Cfg)"`) e o mismatch
de tamanho (`"received data size ... does not match"`) só vão para o **console**. E
`isConnected()` só é `True` em DX (`dp_master.py:296-301, 871-873`), de modo que um escravo
que rejeita o `Chk_Cfg` fica preso reiniciando, com `isConnected()` eternamente `False`.

**Como isso afeta a ferramenta (bug #5, ABERTO).** `GenericDpMaster.diag` retorna
`"conectando"` para sempre nessa situação (`generic.py:123`), então o **motivo real** da
falha (Chk_Cfg/tamanho) **não chega à UI** — fica só no terminal. Foi exatamente o buraco
de diagnóstico que tornou o comissionamento do RM3007 opaco; o usuário depurou pela saída
do console. **Próximo passo previsto:** capturar o `__errorMsg`/expor o fault e mostrá-lo no
diag da UI.

### 9.4 Outros gotchas relevantes

- **Teto de baud** — só 9600/19200 confiáveis no Pi 3 (Python puro + Linux não-RT). A UI
  marca os demais como "(best-effort)" e avisa, mas `BusSettings` os aceita
  (`RELIABLE_BAUDS` é só documental).
- **WS engole exceções** (`server.py`) — um erro de serialização ou de `send` é
  indistinguível de desconexão e fecha o socket sem log; depurar "o socket cai" é cego.
- **Três frames por tick, sem coalescing** — `encoder`+`bus`+`io` a ~15 Hz por conexão,
  sempre, mesmo sem mudança. Com **N** clientes são **3N** envios/ciclo (não há broadcast/diff).
- **`_io_working` zera fora do modo generic** — ao sair do generic, o último `in_hex`/
  `out_hex` é perdido (não há "congelar último estado").
- **`_io_error` persiste no diag** — um "saída hex inválida" sobrescreve o diag até o
  próximo `set_output` válido.
- **Modo `idle` congela o encoder** — `step()` só atualiza `_encoder_snap` no ramo
  `exchange`; não há ramo `idle`. Se a troca falhar ao iniciar (`_mode="idle"`,
  `bus.diag="erro ao iniciar: …"`), a aba Encoder continua mostrando a **última leitura
  congelada** em vez de indicar "sem dados".
- **Scan varre 0..126** — sem `addresses` explícito, `BusController` usa `range(127)` e
  `_begin_scan` exclui **apenas** o `master_addr`; logo os endereços `0` e `126` (default de
  escravo não-configurado) também são sondados.
- **`GenericPoller.step()` pode reportar `connected=True` com `diag="sem leitura"`** —
  `connected` vem direto de `source.connected` independentemente do staleness
  (`generic_poller.py:49,66`); os dois campos podem ficar incoerentes por um instante.

---

## 10. Referência de arquivos (mapa do repo)

### Domínio — `profibus_amg11/`

| Arquivo | Conhece pyprofibus? | Papel |
|---|---|---|
| `encoder.py` | não | `decode(2 bytes, cfg) -> EncoderReading` (puro; máscara → sentido → offset → ângulo) |
| `config.py` | não | `EncoderConfig` (frozen) + `load_config(yaml)` |
| `source.py` | não | Protocol `ReadingSource` (poll/set_offset/close) |
| `master.py` | sim | `Amg11Master` (1 escravo, decodifica) + `_chdir` + `build_scan_phy` |
| `generic.py` | sim | `GenericDpMaster` + `make_generic_slave_desc` (parametriza GSD em memória, inverte I/O) |
| `gsd_info.py` | sim | `parse_gsd`/`preview_params`/**`decode_cfg_io`** + serializadores |
| `scan.py` | sim | `StationType`/`Station`/`BusProbe`/`FdlBusProbe`/`SimBusProbe` (live list FDL) |

### App web — `web/`

| Arquivo | Papel |
|---|---|
| `controller.py` | `BusController` — dono único da serial; modos exchange/scanning/generic/idle |
| `server.py` | `create_app` (Flask + flask-sock); `/ws` (3 frames/tick); `handle_ws_message` |
| `snapshot.py` | `Snapshot`/`IoSnapshot` + `snapshot_to_dict`/`io_snapshot_to_dict`/`bus_snapshot_to_dict` |
| `scanner.py` | `BusScan`/`ScanState`/**`BusSnapshot`** (lógica de varredura pura) |
| `settings.py` | `BusSettings`/`SettingsStore`; `ALLOWED_BAUDS`/`RELIABLE_BAUDS` |
| `poller.py` | `EncoderPoller` — motor do modo exchange (Protocol `ExchangeEngine`) |
| `generic_poller.py` | `GenericPoller`/`ParamSpec`/`GenericSource` — motor do modo generic |
| `gsd_store.py` | `GsdStore` — persistência de `.gsd` com validação + path-safety |
| `gsd_api.py` | rotas HTTP `/api/gsd*` |

### Frontend — `web/static/`

`index.html` (importmap → `/vendor/*`), `app.js` (`useBusSocket`, `EncoderView`, `BusView`,
`GsdView`, `App`, `decodePosition`), `styles.css` (tokens, `.gauge`, abas, controles),
`vendor/` (Preact/hooks/htm + fontes Space Grotesk / JetBrains Mono).

### Entrypoints e config

- `serve.py` — `build_controller` (factories `make_exchange`/`make_probe`/`make_generic`) +
  `main` (porta 8600).
- `run.py` — CLI (`--scan`/`--once`/contínuo).
- `config/amg11.conf` — PHY (`/dev/serial0`, 19200), DP (master_class 1, addr 1),
  `[SLAVE_3]` AMG11 (addr 3, GSD `gsd/PB13DPV0.gsd`, in/out=2/2, `module_0 = 16 Bit Class 2
  Encoder`).
- `config/encoder.yaml` — `resolution_bits: 13`, `direction: cw`, `offset: 0`,
  `control_word: 0x0000`.
- `config/bus.json` — **runtime/gitignored** (baud + master_addr persistidos pela aba
  Barramento).
- `gsd/PB13DPV0.gsd` (Baumer AMG11, `0x059B`), `gsd/IFM_0E75.gsd` (IFM RN30xx/RM30xx,
  `0x0E75`).

### Contratos de comunicação (resumo)

**WebSocket `/ws`** — servidor → browser, 3 frames por tick (~15 Hz):

```json
{ "type":"reading", "angle_deg":90.0, "raw":2048, "raw_max":8191, "bytes_hex":"0800",
  "offset":0, "connected":true, "rate_hz":20.0, "diag":"OK", "ts":123.4 }
{ "type":"bus", "mode":"exchange", "diag":"ok", "settings":{"baud":19200,"master_addr":1},
  "scan":{"status":"idle","current_addr":null,"scanned":0,"total":0,"error":null,"found":[]} }
{ "type":"io", "active":true, "address":9, "connected":true, "diag":"OK",
  "in_hex":"000209b0", "out_hex":"00000000", "input_size":4, "output_size":4,
  "rate_hz":31.0, "ts":123.4 }
```

browser → servidor: `{"cmd":"zero"}`, `{"cmd":"clear_zero"}`, `{"cmd":"scan"}`,
`{"cmd":"apply_settings","baud":19200,"master_addr":1}`,
`{"cmd":"param_read","gsd":"IFM_0E75.gsd","address":9,"modules":["Class 2 Multiturn"]}`,
`{"cmd":"set_output","hex":"00000000"}`, `{"cmd":"stop_generic"}`.

### Testes — `tests/` (rodar `.venv/bin/python -m pytest -q` → **130 passed, 1 skipped**)

| Arquivo | Cobre |
|---|---|
| `test_encoder.py` | `decode` (sentido, offset, máscara 13-bit, len != 2) |
| `test_config.py` / `test_conf_load.py` | `EncoderConfig`/`load_config` e parse do `.conf` real |
| `test_source_fake.py` | `FakeSource` satisfaz `ReadingSource`; `set_offset` real |
| `test_poller.py` | `EncoderPoller.step()`: snapshot, zero, taxa, stale |
| `test_generic.py` | `GenericDpMaster`/`make_generic_slave_desc`: deriva+inverte; read-only levanta; Class 2 sim |
| `test_generic_poller.py` | `GenericPoller`: in_hex, rate, set_output, stale, stop |
| `test_snapshot.py` | `Snapshot`/`IoSnapshot`/`BusSnapshot` + `*_to_dict` |
| `test_settings.py` | `BusSettings`/`SettingsStore` (validação, round-trip) |
| `test_scan.py` | `StationType.from_fc`, `FdlBusProbe` (transceiver fake) |
| `test_scanner.py` | `BusScan` passo-a-passo (FakeProbe, FakeClock) |
| `test_controller.py` | modos (exchange/scanning/generic/idle), troca de dono, apply, offset, param/set_output/stop |
| `test_server.py` | rotas + `handle_ws_message` (incl. caminho generic) |
| `test_gsd_info.py` | `parse_gsd`/`preview_params`/`decode_cfg_io` nas 2 GSDs reais |
| `test_gsd_store.py` | save valida/rejeita/overwrite, path-safety |
| `test_gsd_api.py` | upload/list/get/preview, 400/404/409/413, X-Filename |
| `test_integration_sim.py` | e2e sim: exchange → scan acha addr 3 → retoma |
| `test_master_sim.py` / `test_master_overrides.py` | master no dummy + overrides baud/addr |
| `test_cli_sim.py` | CLI no `--sim` (`--once`, `--scan`) |
| `test_frontend_assets.py` | vendor presente, sem emoji/Inter, abas/GSD/comandos, aviso honesto de baud |

`tests/fakes.py` traz o `FakeSource`; outros fakes (`FakeProbe`, `FakeEngine`,
`FakeGenericEngine`, etc.) são locais a cada arquivo. O 1 skip é
`test_build_scan_phy_uses_given_baud` (precisa de porta serial real).

---

## 11. Roadmap e próximos passos

Fundação: **v1** (dashboard do encoder + zerar).

- **A — Explorador de barramento** ✅ — `BusController` (dono único, modos), live list FDL,
  controles de baud/endereço persistidos.
- **B — Parametrizar qualquer escravo** ✅:
  - **B1 — Gestão/inspeção de GSD + preview** ✅ — upload HTTP, inspeção, preview offline de
    `Chk_Cfg`/`Set_Prm` + tamanhos.
  - **B2 — Parametrizar ao vivo + I/O cru + visualização** ✅ — modo `generic`,
    `GenericDpMaster`/`GenericPoller`, `IoSnapshot`, aba GSD com parametrização, I/O cru e
    **gauge** decodificado (validado no RM3007).
- **C — Perfis declarativos de decodificação** ⏳ (não iniciado) — transformar o I/O cru em
  grandeza de engenharia por um perfil de device; o `decode` do AMG11 e o `decodePosition`
  do RM3007 viram "só mais um perfil". O `decodePosition` no cliente é o primeiro passo.

### Itens abertos (prioridade)

1. **Bug #5 — diagnóstico de Chk_Cfg na UI.** Capturar o `__errorMsg`/expor o fault do
   pyprofibus e mostrar o motivo real da rejeição (`Chk_Cfg`/tamanho) no diag, em vez de
   `"conectando"` eterno. É o gap que tornou o RM3007 opaco.
2. **Suporte a Class 1 input-only.** Patch no DX do pyprofibus para enviar um poll vazio a
   escravos `inputSize==0` (precisa validar no hardware) — permitiria o perfil "correto" do
   RM3007 sem os 4 bytes de saída zerados.
3. **Fase C.** Perfis declarativos (spec/plano ainda não escritos).
4. **Commit do trabalho de B2** + esta atualização de documentação (branch
   `feat/web-dashboard-v1`).

Specs e planos detalhados em `docs/superpowers/specs/` e `docs/superpowers/plans/`
(5 specs + 5 planos, fases A → B1 → B2).

---

## 12. Glossário PROFIBUS

- **DP / DPM1** — Decentralized Periphery; mestre classe 1 (troca cíclica de I/O).
- **DPV0 / DPV1** — DPV0 = troca cíclica básica; DPV1 = acesso acíclico (não usado aqui).
- **GSD** — arquivo-texto que descreve um escravo (ident, módulos, parâmetros, timings).
- **Ident_Number** — identificador do tipo de dispositivo; tem que bater na parametrização
  (AMG11 `0x059B`; IFM `0x0E75`).
- **FDL** — camada 2 (enlace). *Request-FDL-Status* é o que usamos para o *live list*.
- **Set_Prm / Chk_Cfg / Data_Exchange** — parametrizar → checar config → trocar I/O.
- **Cfg byte / config byte** — byte identificador do módulo (direção + unidade + tamanho),
  decodificado por `decode_cfg_io`.
- **inputSize/outputSize (pyprofibus)** — **ótica do escravo**: `inputSize` = o mestre
  escreve; `outputSize` = o mestre lê (invertido da intuição).
- **Live list** — conjunto de estações que respondem no barramento.
- **PHY** — camada física. Aqui, serial RS485 via UART do Pi (`/dev/serial0`).
- **MaxTSDR** — atraso máximo de resposta da estação, por baud (vem do GSD).
- **Watchdog** — se o mestre some, o escravo cai para um estado seguro após o timeout.
- **Singleturn / Multiturn** — posição dentro de uma volta vs. posição absoluta com
  contagem de voltas (RM3007: 8192 passos/volta, 4096 voltas, 32 bits de posição multivolta).
- **Control word** — os bytes que o mestre escreve por ciclo (no AMG11, 2 B; no RM3007
  Class 2, 4 B zerados = sem preset).
