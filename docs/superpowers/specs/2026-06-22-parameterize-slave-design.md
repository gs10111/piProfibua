# Design — Parametrizar qualquer escravo ao vivo + I/O cru (B2)

**Data:** 2026-06-22
**Status:** Aprovado para implementação (decisões no recomendado, por delegação do usuário)
**Fase:** sub-projeto **B2** de **A → B → C** (B = parametrizar qualquer escravo)
(B1 = gestão/inspeção de GSD + preview ✅ · **B2** = parametrizar ao vivo + I/O cru)

## 1. Objetivo

Pegar um escravo **descoberto** na varredura (ex.: o RM3007 da ifm no endereço 9) e,
a partir do **GSD dele + módulo(s) escolhidos + endereço + tamanhos de I/O**,
**parametrizá-lo ao vivo** (`Set_Prm` → `Chk_Cfg`) até o **Data_Exchange**, então
**ler os bytes de entrada crus** e **escrever os bytes de saída crus**. Sem decodificar
em engenharia (isso é a fase C) — é o "ler/escrever qualquer escravo".

Validável contra o **Baumer** (addr 3, já funciona pelo `run.py`) e o **RM3007**
(addr 9, GSD `IFM_0E75.gsd` já no projeto).

## 2. Escopo

**Dentro:**
- `GenericDpMaster`: monta um mestre DP de **um escravo genérico** a partir de um GSD
  **em memória** (bytes) + endereço + módulos + tamanhos in/out; roda o `Data_Exchange`;
  expõe **entrada crua** (`getMasterInData`) e **saída crua** (`setMasterOutData`).
- Novo **modo `generic`** no `BusController` (dono único da serial): pausa a troca do
  encoder, parametriza o alvo, troca dados; "Parar" volta ao encoder.
- WebSocket: novo tipo `io` (entrada/saída cruas, estado, diag) + comandos
  `param_read` / `set_output` / `stop_generic`.
- Frontend: na aba **GSD**, após escolher módulo, campos de **endereço** e **tamanho
  de entrada/saída** + botão **"Parametrizar e ler"**; painel ao vivo com input cru,
  campo de output cru e **"Parar"**.

**Fora (C ou nunca):**
- **Decodificar** o I/O em grandeza de engenharia (graus, etc.) → **C** (perfis).
- **Derivar automaticamente** os tamanhos de I/O do GSD → **futuro** (o formato de
  identificador especial, ex.: `0xF0` do Baumer, é trabalhoso; reimplementar errado é
  pior que pedir o tamanho). Nesta fase os tamanhos são **manuais** (o preview mostra os
  cfg bytes para ajudar), igual o `amg11.conf` já faz hoje.
- Múltiplos escravos simultâneos (um alvo por vez).
- Acesso acíclico DPV1.

## 3. Verdade técnica (aterrada no fonte do pyprofibus)

- **Construir o escravo é genérico:** `DpSlaveDesc(slaveConf)` lê `gsd.getIdentNumber()`,
  `addr`, `inputSize`, `outputSize`; depois `setCfgDataElements(gsd.getCfgDataElements())`,
  `setUserPrmData(gsd.getUserPrmData())`, `setSyncMode/Freeze/GroupMask/Watchdog`. É
  exatamente o que o `_SlaveConf.makeDpSlaveDesc()` faz — replicamos com um **slaveConf
  genérico** (objeto leve com `gsd/addr/inputSize/outputSize/name/index/diagPeriod/...`).
- **Mestre sem .conf de escravo:** `conf.makeDPM()` cria o `DPM1` (PHY + mestre) **sem
  escravos**; os escravos entram por `addSlave(slaveDesc)`. Então reusamos o `.conf` só
  para a **PHY** (dev serial, baud) e adicionamos o nosso `slaveDesc` genérico.
- **I/O ao vivo:** por ciclo, `slaveDesc.setMasterOutData(out)`, `master.run()`, e
  `slaveDesc.getMasterInData()` devolve os bytes de entrada (ou `None`). `isConnected()`
  diz se chegou ao Data_Exchange.
- **Tamanhos:** `inputSize`/`outputSize` (0..246) governam o tamanho do DX. Precisam
  bater com o módulo/escravo — por isso são entrada do usuário nesta fase.
- **Chegar ao DX depende de bater** ident + cfg + prm + tamanhos. Se não bater, o escravo
  rejeita (diag DP "faulty parameterization/configuration"); a ferramenta **mostra o
  diag**, não trava.

## 4. Arquitetura (em camadas, SOLID — estende A/B1)

```
 frontend (aba GSD)
   "Parametrizar e ler" ──WS cmd param_read──┐
   painel I/O ao vivo  ◀──WS type "io"────────┤
                                              ▼
                                  web/server.py (Flask + flask-sock)
                                              │
                                  web/controller.py · BusController
                                   modos: exchange / scanning / generic / idle
                                              │ (factory injetada) make_generic(ParamSpec)
                                              ▼
                                  web/generic_poller.py · GenericPoller   (motor do modo generic)
                                              │ depende de (Protocol)
                                              ▼
                                  GenericSource ── GenericDpMaster (profibus_amg11/generic.py)
                                                    monta DPM + DpSlaveDesc do GSD em memória
```

**SRP — unidades novas/editadas:**
- **`profibus_amg11/generic.py`** (domínio; conhece pyprofibus):
  - `make_generic_slave_desc(gsd_bytes, address, modules, input_size, output_size) ->
    DpSlaveDesc` (parse do GSD, `clearConfiguredModules`+`setConfiguredModule`, monta o
    DpSlaveDesc como o `makeDpSlaveDesc`). Levanta `GenericError` em GSD/módulo inválido.
  - `GenericDpMaster(conf_path, gsd_bytes, address, modules, input_size, output_size,
    baud, master_addr, sim=False)`: monta `DPM1` (PHY do `.conf`, baud/addr override),
    `addSlave`, `initialize`. `poll() -> bytes | None` (re-arma a saída, roda um passo,
    devolve a entrada crua). `set_output(bytes)`, `connected -> bool`, `diag -> str`,
    `close()`. Implementa `GenericSource`.
- **`web/snapshot.py`** (edição): `IoSnapshot` (frozen: `active, address, connected,
  diag, in_hex, out_hex, input_size, output_size, rate_hz, ts`) +
  `io_snapshot_to_dict` (type=`io`) + `idle_io_snapshot()` (`active=False`).
- **`web/generic_poller.py`** (app): `GenericSource` (Protocol: `poll()->bytes|None`,
  `set_output(bytes)`, `connected`, `diag`, `close()`); `GenericPoller(source, address,
  input_size, output_size, now=...)` com `step()->IoSnapshot`, `snapshot()`,
  `set_output(bytes)`, `stop()`. Mesma disciplina do `EncoderPoller` (lógica em `step()`,
  relógio injetado, sem sleep nos testes).
- **`web/controller.py`** (edição): modo `generic` + `GenericEngine` (Protocol:
  `step()->IoSnapshot, snapshot(), set_output(bytes), stop()`); factory injetada
  `make_generic(ParamSpec) -> GenericEngine`; comandos `param_read(spec)`,
  `set_output(hex)`, `stop_generic()`; leitura `io_snapshot() -> IoSnapshot`.
  Transições: `param_read` → derruba o motor de exchange, `make_generic(spec)`, modo
  `generic`; `stop_generic` → fecha o generic, recria o exchange (preserva o zero). Erro
  ao montar o generic → `idle` + diag (servidor de pé).
- **`web/server.py`** (edição): `handle_ws_message` despacha `param_read` (passa o dict
  spec ao controller), `set_output`, `stop_generic`; o `/ws` envia também o `io_snapshot`
  por tick.
- **`serve.py`** (edição): `make_generic(spec)` lê o GSD do `GsdStore` (`spec.gsd` =
  nome), monta `GenericDpMaster` (sim conforme flag) e embrulha num `GenericPoller`.
- **`ParamSpec`** (frozen, em `web/generic_poller.py` ou `controller.py`): `gsd` (nome),
  `address`, `modules` (tuple), `input_size`, `output_size`.

### Estrutura de arquivos
```
profibus_amg11/
  generic.py            # make_generic_slave_desc + GenericDpMaster                 [novo]
web/
  generic_poller.py     # GenericSource(Protocol) + GenericPoller + ParamSpec       [novo]
  snapshot.py           # + IoSnapshot + io_snapshot_to_dict + idle_io_snapshot     [edição]
  controller.py         # + modo generic + GenericEngine + comandos                 [edição]
  server.py             # + comandos param_read/set_output/stop_generic + io no /ws [edição]
  static/app.js,css     # + "Parametrizar e ler" + painel I/O                       [edição]
serve.py                # + make_generic (lê GsdStore)                              [edição]
tests/
  test_generic.py            # make_generic_slave_desc com as 2 GSDs reais (sem bus)
  test_generic_poller.py     # GenericPoller com FakeGenericSource
  test_snapshot.py           # + io_snapshot_to_dict
  test_controller.py         # + modo generic (fakes)
  test_server.py             # + dispatch dos comandos novos
  test_frontend_assets.py    # + UI de parametrização
```

## 5. Modo `generic` no controlador (estende a máquina de A)

```
[exchange] ──param_read(spec)──▶ derruba exchange, make_generic(spec) ──▶ [generic]
   ▲                                                                          │
   └────────────────── stop_generic: fecha generic, recria exchange ◀────────┘
                                                                              │
   make_generic falha (GSD/módulo/serial) ─────────────▶ [idle] (diag; servidor de pé)
```
- `generic`: cada `step()` → `engine.step()` (um ciclo DX); publica `IoSnapshot`.
- `set_output(hex)`: valida hex (tamanho = `output_size`), encaminha ao engine.
- Invariante de dono único mantida: `generic`, `scanning` e `exchange` nunca compartilham
  a serial. Um scan durante o generic pausa o generic (mesma regra do encoder).

## 6. Contrato do WebSocket (adições)

**Servidor → browser** (novo tipo, por tick):
`{type:"io", active, address, connected, diag, in_hex, out_hex, input_size,
output_size, rate_hz, ts}`. Quando o modo não é `generic`: `active:false`.

**Browser → servidor:**
- `{cmd:"param_read", gsd:"<nome>", address:9, modules:["..."], input_size:2,
  output_size:0}`
- `{cmd:"set_output", hex:"00ff"}`
- `{cmd:"stop_generic"}`

## 7. Frontend (aba GSD, mesma stack)

Após selecionar um GSD e marcar módulo(s) (preview já mostra cfg/prm):
- Campos: **endereço** (1–126, default = ident/varredura), **tam. entrada** (0–246),
  **tam. saída** (0–246) — com dica "veja os cfg bytes do preview".
- Botão **"Parametrizar e ler"** → `param_read`. Enquanto ativo:
  - **Painel I/O ao vivo:** estado (conectando/conectado/erro + diag), **entrada (hex)**
    atualizando, **saída (hex)** com campo editável + "Enviar saída", e **"Parar"**
    (`stop_generic`). Numerais/hex em mono.
- Aviso honesto: "chegar ao Data_Exchange depende do GSD/módulo/tamanhos baterem com o
  escravo; se rejeitar, o diag aparece aqui."

## 8. Tratamento de erros

- GSD/módulo inválido, ou serial ausente → `make_generic` levanta; controller vai a
  `idle` com diag; servidor de pé; novo comando ainda funciona.
- Escravo rejeita parametrização (ident/cfg/prm/tamanho não batem) → fica `connected:false`
  com o diag DP; a UI mostra. (Re)tentar com outro módulo/tamanho.
- `set_output` com hex inválido ou de tamanho errado → ignorado + diag.
- Voltar de `generic` para `exchange` re-roda o startup DP do encoder (alguns segundos) —
  aceito e documentado (igual ao retorno de um scan).

## 9. Testes (TDD, sem test-smells)

- **`make_generic_slave_desc`** com as 2 GSDs reais (sem barramento): Baumer "16 Bit
  Class 2 Encoder" → `identNumber==0x059B`, `inputSize/outputSize` setados, cfg/prm
  telegramas populados; IFM com um módulo → `identNumber==0x0E75`; módulo inexistente →
  `GenericError`.
- **`GenericPoller`** com `FakeGenericSource` (bytes roteirizados, relógio injetado):
  `IoSnapshot` com `in_hex` correto, `connected/diag`, `rate_hz`; `set_output` encaminha;
  stale quando para de receber.
- **`io_snapshot_to_dict`**: contrato JSON puro (type=`io`).
- **`BusController`** (fakes): `param_read` derruba o exchange e entra em `generic`;
  `io_snapshot` reflete; `set_output` encaminha; `stop_generic` volta a `exchange`;
  `make_generic` falhando → `idle`.
- **`server.py`**: dispatch de `param_read`/`set_output`/`stop_generic`.
- **frontend assets**: "Parametrizar e ler", campos de tamanho, painel I/O; sem emoji;
  sem Inter.
- **Os testes de A/B1/v1 seguem verdes.**

## 10. Dependências novas

Nenhuma. `GenericDpMaster` usa o pyprofibus já presente. Sem libs novas.
