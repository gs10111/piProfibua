# CONTEXTO COMPLETO — pi5-profibus-amg11 (super-contexto de continuidade)

> Documento de continuidade pensado para **colar em outro chat** e retomar o trabalho sem perder nada.
> Otimizado para uma IA assistente: denso, factual, com caminhos absolutos e referencias `arquivo:linha`.
> Data de geracao: 2026-06-23. Idioma: PT-BR. Publico: engenheiro de automacao/embarcados + IA assistente.

---

## 1. TL;DR DO ESTADO ATUAL

Comissionamos um **encoder absoluto MULTIVOLTA IFM RM3007** (RMK0025-E24/E, `IFM_0E75.gsd`, ident `0x0E75`) no endereco PROFIBUS **9**, que falhava no **Chk_Cfg**. A causa-raiz foi uma cadeia de tres bugs no caminho de parametrizacao generica (B2): (1) tamanhos de I/O passados sem inverter para a convencao escravo-centrica do pyprofibus; (2) buffer de saida `_out` mal-dimensionado fazendo o primeiro `poll()` lancar `DpError` antes de publicar o `IoSnapshot` (painel nunca aparecia); (3) erros de parametrizacao invisiveis na aba GSD. Apos corrigir 1-3, o RM3007 **chegou ao Data_Exchange** (status verde, ~31 Hz, lendo). Ainda diagnosticamos uma **limitacao de design do pyprofibus** (Class 1 so-leitura nao roda — item 4, contornada por Class 2) e um **bug ainda ABERTO** (item 5: rejeicoes de Chk_Cfg/Set_Prm so vao para `print()` no console, nunca a UI). Por fim, adicionamos uma **visualizacao estilo Baumer** para o RM3007 na aba GSD (item 6, feita).

- **Codigo:** `/home/ubuntu/repos/pi5-profibus-amg11`
- **Branch:** `feat/web-dashboard-v1`
- **Mudancas NAO COMMITADAS** (working tree sujo). Os fixes 1-6 desta sessao **ainda nao foram commitados**. Commits anteriores vao ate `4447620 fix(review): dono unico no scan-durante-generic...` (mais 3 commits placeholder "resenha": `292c8b1`, `7d15182`, `4849042`).
- **Suite de testes:** `130 passed, 1 skipped` (o skip e `test_build_scan_phy_uses_given_baud`, por falta de porta serial real no ambiente).
- **Atencao de ambiente:** `pyprofibus` NAO esta instalado neste ambiente de doc (import falha); valores de mascaras `DpCfgDataElement.ID_*/LEN_*` e `FdlTelegram.FC_*` foram lidos do source da `.venv` quando necessario (ver secao 4 e dossie pyprofibus).

---

## 2. O QUE O PROJETO E + ROADMAP

**Projeto:** mestre **PROFIBUS-DP (DPM1)** rodando num **Raspberry Pi 3** via **pyprofibus** (Python puro), lendo um encoder absoluto **Baumer AMG 11 P 13** (13 bit singleturn, `0x059B`). A pasta mantem o prefixo `pi5-` por legado; o hardware real e Pi 3 + UART GPIO (`/dev/serial0`) + RS485-TTL **auto-direcao** (a via `.conf` do pyprofibus nao faz controle DE/RE por RTS).

**Teto de baud:** em Linux nao-RT (Python puro), so **9600 e 19200** sao confiaveis (`RELIABLE_BAUDS` em `web/settings.py:11`); os demais bauds de `ALLOWED_BAUDS` sao best-effort/UI.

**Duas faces:**
- **CLI** `run.py` (porta de testes em campo; flags `--sim`, `--scan`, `--once`, `--hz`, etc.).
- **Ferramenta web** `serve.py` (porta **8600**): Flask + flask-sock + Preact (htm, sem build). Tres abas: **Encoder**, **Barramento**, **GSD**.

**Arquitetura em camadas** (fronteiras como `Protocol`, DIP total):
```
Frontend (Preact vendorizado, web/static/) 
   -> Transporte (web/server.py: Flask + flask-sock, WS /ws ~15 Hz)
      -> Servico (web/controller.py: BusController = DONO UNICO DA SERIAL, 1 thread)
         -> Dominio (profibus_amg11/: unica camada que conhece pyprofibus)
```

**BusController** e o dono-unico-da-serial: uma thread (`_loop`) que so repete `step()`; a web enfileira comandos e le snapshots imutaveis (`frozen=True`) publicados sob lock. Modos: `exchange` (encoder AMG11), `scanning` (varredura FDL live-list), `generic` (parametrizacao de escravo generico via GSD — B2), `idle` (falha de abertura).

**Roadmap A -> B -> C:**

| Fase | O que e | Status |
|---|---|---|
| **A** | Explorador de barramento: scan live-list 0..126 via FDL Request-FDL-Status; tipo de estacao + tempo de resposta; baud/master_addr persistidos em `config/bus.json` | **FEITO** (commitado) |
| **B1** | Gestao/inspecao de GSD offline: upload HTTP validado por parse, listar/inspecionar (vendor/modelo/ident/modulos/MaxTSDR), preview de parametrizacao (Chk_Cfg/Set_Prm/ident sem tocar no barramento) | **FEITO** (commitado) |
| **B2** | Parametrizar qualquer escravo ao vivo: `GenericDpMaster` monta DP-master de 1 escravo generico do GSD em memoria; modo `generic`; roda Data_Exchange, le input cru / escreve output cru (sem decode) | **FEITO no git**, mas os **fixes desta sessao (RM3007) NAO estao commitados**. (DOCUMENTACAO.md foi reescrita nesta sessao e ja descreve B2 + RM3007.) |
| **C** | Perfis declarativos de decodificacao (I/O cru -> grandeza de engenharia; o decode do AMG11 vira "so mais um perfil") | **NAO INICIADO** (o `decodePosition()` no cliente, item 6, e um primeiro passo) |

---

## 3. SAGA RM3007 — AUDITORIA COMPLETA (6 ITENS)

**Problema original:** o RM3007 no addr 9, parametrizado pela aba GSD (B2), falhava no **Chk_Cfg** e nunca chegava ao Data_Exchange. No "Cenario 1" do usuario o painel de I/O **nem aparecia** ("0 bytes de saida, painel nao aparece"). A depuracao foi cega porque o motivo real so sai no stdout do pyprofibus (ver item 5).

**Especificacao do RM3007 (RMK0025-E24/E):** 8192 passos/volta (13 bits) x 4096 voltas (12 bits) = 25 bits totais; **posicao multivolta = 4 bytes (32 bits)**.

### Item 1 — [BUG, CORRIGIDO] Tamanhos de I/O manuais e invertidos

- **Sintoma:** Chk_Cfg falha por mismatch de tamanho/modulo. Em modulos **simetricos** (Class 2 = 4/4) "funcionava por acaso"; com tamanho/modulo assimetrico dava mismatch.
- **Causa-raiz:** o B2 pedia campos "Entrada/Saida" (bytes) na UI com rotulos **mestre-centricos** (intuitivos: entrada=leitura=posicao, saida=escrita=preset) e os passava **direto** aos campos do `DpSlaveDesc`. Mas o pyprofibus e **ESCRAVO-CENTRICO**:
  - `slaveDesc.inputSize` = bytes que o **MESTRE ESCREVE** (master->slave; ex.: preset/controle). Evidencia: `dp_master.py:843-855` (`_setToSlaveData` exige `len(data) == inputSize`).
  - `slaveDesc.outputSize` = bytes que o **MESTRE LE** (slave->master; ex.: posicao). Evidencia: `dp_master.py:829-839` (dado recebido checado contra `outputSize`).
  - Passar os rotulos mestre-centricos sem inverter trocava o mapeamento silenciosamente.
- **Solucao:** derivar os tamanhos do **byte de config do modulo** (`gsd_info.decode_cfg_io`, que devolve `(read, write)` na otica do mestre) e **inverter na unica fronteira** (`make_generic_slave_desc`): `_GenericSlaveConf(input_size=write, output_size=read)`. Os campos manuais de I/O foram **removidos** da UI e do `ParamSpec`.
- **Onde:** `profibus_amg11/generic.py:54-61` (inversao), `profibus_amg11/gsd_info.py:18` (`decode_cfg_io`).

### Item 2 — [BUG, CORRIGIDO] Buffer de saida mal-dimensionado (o painel nunca aparecia)

- **Sintoma:** "Cenario 1": modulo so-leitura/assimetrico -> `IoSnapshot` ficava `active=False` -> painel de I/O **nunca aparecia**.
- **Causa-raiz:** `GenericDpMaster.__init__` tinha `self._out = bytearray(output_size)`. No esquema manual antigo, `output_size` era o tamanho de **LEITURA**. Quando leitura != escrita, o buffer master-out nao casava com `inputSize` -> `setMasterOutData` lancava `DpError` no **PRIMEIRO** poll (`dp_master.py:847-853`) -> a excecao subia por `controller.step()` **ANTES** de `_publish_io()` -> `IoSnapshot` ficava `active=False`.
- **Solucao:** derivar tamanhos do **desc construido** e dimensionar `self._out = bytearray(self.output_size)` com `output_size` = tamanho de **escrita** = `slave.inputSize`. Em `GenericDpMaster`, depois da construcao desfaz o cruzamento e expoe `self.input_size = slave.outputSize` (mestre LE) / `self.output_size = slave.inputSize` (mestre ESCREVE) — `generic.py:94-96`.
- **Onde:** `profibus_amg11/generic.py:94-96` (re-exposicao mestre-centrica + dimensionamento do `_out`).

### Item 3 — [BUG, CORRIGIDO] Erros de parametrizacao invisiveis na aba GSD

- **Sintoma:** falha de build do `make_generic` ia so para o diag do **Barramento** (outra aba); na aba GSD "nao acontecia nada".
- **Causa-raiz:** o erro de construcao do escravo generico era refletido em `bus.diag` mas a aba GSD nao o lia.
- **Solucao:** espelhar o erro de parametrizacao na aba GSD via `paramErr = bus.diag` quando contem a palavra "parametrizar" (`web/static/app.js:168`); + aviso proativo de modulo so-leitura (`readonly`, `app.js:166`) + botao "Parametrizar e ler" desabilitado (`app.js:210-213`).

### Item 4 — [LIMITACAO DA LIB, DIAGNOSTICADO + CONTORNADO] Class 1 (so-leitura) NAO roda no pyprofibus

- **Contexto:** o perfil **correto** do RM3007 e **Class 1 Multiturn** (le 4 bytes de posicao, escreve 0). Mas:
  1. `DPM1.addSlave` **rejeita `inputSize <= 0`** -> `DpError("input_size=0 is currently not supported.")` (`dp_master.py:381-386`). Como `inputSize` = mestre-escreve, um modulo so-leitura tem `inputSize==0` e e rejeitado.
  2. Ainda que registrado, `__runSlave_dataExchange` **nunca envia** o `Data_Exchange_Req` quando `inputSize == 0` (`dp_master.py:692`): so envia se houver `toSlaveData` E `inputSize != 0` (`dp_master.py:691-701`). Sem request, o escravo nunca responde com a posicao -> impossivel pollar so-leitura.
- **Conclusao:** e **limitacao de DESIGN do pyprofibus**, nao do encoder nem do PROFIBUS.
- **Solucao/contorno:** usar **Class 2 Multiturn** (le 4, **escreve 4**) — le a **MESMA** posicao multivolta de 32 bits; os 4 bytes de saida vao **zerados** (control word 0 = sem preset). Adicionado `GenericError` claro ("modulo so-leitura ... use Class 2 ou ifm") em vez do erro criptico, e aviso na UI explicando que Class 1 e o perfil correto mas nao suportado.
- **Onde:** guard `write <= 0` em `profibus_amg11/generic.py:54-58`; aviso `readonly` na UI `web/static/app.js:215-217`.

### Item 5 — [BUG, IDENTIFICADO, NAO CORRIGIDO — ABERTO] Rejeicoes de Chk_Cfg/Set_Prm/tamanho nunca chegam a UI

- **Sintoma:** depuracao cega — o motivo real ("Slave 9 reports a faulty configuration (Chk_Cfg)" / "received data size ... does not match") so aparece no **console**. O usuario depurou pela saida do terminal.
- **Causa-raiz (cadeia no pyprofibus):**
  - `__errorMsg` **so faz `print()`** (sem excecao/callback/flag): `dp_master.py:364-365`.
  - O `cfgFault` e reportado so via esse `print` + incremento de `faultDeb`: `dp_master.py:566-570`.
  - `isConnected()` so e `True` quando `dxCycleRunning` (`dp_master.py:296-301`, `871-873`); numa rejeicao de Chk_Cfg o escravo fica preso em `WDXRDY -> INIT -> ...` (`needsNewPrmCfg()`, `dp.py:382-385` + `dp_master.py:605-607`) e **nunca** atinge `dxCycleRunning=True`.
  - Logo, no nosso lado: `GenericDpMaster.diag` retorna "conectando" **para sempre** (`generic.py:123`), pois `connected` fica `False` (`generic.py:116`).
- **Estado:** ABERTO. Ofereci capturar o erro do pyprofibus e mostrar no diag; o usuario seguiu adiante (encoder conectou apos os fixes 1-3). Ver esboco de abordagem na secao 7(b).

### Item 6 — [FEATURE, FEITA] Visualizacao estilo Baumer para o RM3007

- **Pedido:** "faca uma visualizacao igual ao do baumer para o rm3007".
- **Feito:** mostrador estilo Baumer no painel de I/O da aba GSD (reusa o CSS `.gauge`). Funcao cliente `decodePosition(hex, stepsPerTurn)` decodifica bytes big-endian em `{value, single, stepsPerTurn, turns, angle, multiturn}` (`web/static/app.js:12-24`). Mostra dial + ponteiro + graus + linhas: **voltas** (so multivolta), **na volta** (single/spt), **posicao** (value), **bytes** (hex). Campo "passos/volta" (default 8192 = RM3007).
- **Verificado:** `09b0` -> 109 graus / 0 voltas / single; `000209b0` -> 109 graus / 16 voltas / multi.
- **Onde:** `web/static/app.js:12-24` (`decodePosition`), `app.js:223-260` (painel io + gauge).

**DESFECHO:** apos fixes 1-3, RM3007 chegou ao Data_Exchange (verde, ~31 Hz, diag OK, lendo). O usuario reportou "entrada `09b0`" = 2 bytes -> estava num modulo **SINGLETURN** (Class 2 Singleturn `0xF0` = 2/2). `0x09B0 = 2480/8192 ~ 109 graus`, perdendo a contagem de voltas. Para multivolta completo: selecionar **Class 2 Multiturn** (`0xF1`, 4 bytes).

---

## 4. CONHECIMENTO-CHAVE (para nao reaprender)

### 4.1 Convencao ESCRAVO-CENTRICA do pyprofibus (a peca mais sutil)

| Termo pyprofibus | Direcao | Significado pratico (encoder) | Evidencia |
|---|---|---|---|
| `slaveDesc.inputSize` | **mestre ESCREVE** (master->slave) | preset / control word | `dp_master.py:843-855` |
| `slaveDesc.outputSize` | **mestre LE** (slave->master) | posicao | `dp_master.py:829-839` |

Regra de ouro: a **verdade do tamanho** vive em `gsd_info.decode_cfg_io`, que devolve `(read, write)` **na otica do MESTRE** (`read`=mestre le=posicao; `write`=mestre escreve=preset). A inversao para a convencao escravo-centrica acontece em **uma unica fronteira**: `make_generic_slave_desc` faz `_GenericSlaveConf(input_size=write, output_size=read)` (`generic.py:54-61`). Depois `GenericDpMaster` **desfaz** o cruzamento para reexpor `input_size`/`output_size` na otica do mestre, intuitiva para a UI (`generic.py:94-96`). **Trocar esses pares quebra silenciosamente as direcoes de I/O.**

Guard critico: `DpSlaveDesc`/`DPM1.addSlave` exige que o mestre escreva >=1 byte. Modulos so-leitura (`write==0`) **nao rodam** -> levantamos `GenericError` orientando a escolher Class 2/ifm (`generic.py:54-58`).

### 4.2 Decode do byte de config (`decode_cfg_io`, `gsd_info.py:18-59`)

Formato do byte identificador (mascaras reais em `pyprofibus/dp.py:520-541`):

- `0x80` = consistencia (`ID_CON_WHOLE`); `0x40` = word(2B)/byte (`ID_LEN_WORDS`); nibble baixo (`ID_LEN_MASK=0x0F`) = **(nº de unidades - 1)** no **formato geral** (dai o `+1`).
- Bits de direcao (formato geral): `0x10` = `ID_TYPE_IN` (entrada do escravo = mestre **escreve**), `0x20` = `ID_TYPE_OUT` (saida do escravo = mestre **le**). **CUIDADO com a nomenclatura:** no nosso `decode_cfg_io` o resultado e `(read, write)` na otica do MESTRE — entao `ID_TYPE_OUT` soma em `read`, `ID_TYPE_IN` soma em `write`.
- **Formato especial** (`(iden & 0x30) == 0x00`): o nibble baixo = **nº de length-bytes** que seguem (NAO a contagem). `ID_SPEC_IN=0x40`, `ID_SPEC_OUT=0x80`, `ID_SPEC_INOUT=0xC0`. **INOUT: vem write (saida) primeiro, depois read (entrada)** — `length[0:1]`=write, `length[1:2]`=read. Trocar a ordem inverte tudo.

Trecho geral (`gsd_info.py:53-59`):
```python
size = ((iden & E.ID_LEN_MASK) + 1) * (2 if iden & E.ID_LEN_WORDS else 1)
if iden & E.ID_TYPE_IN:  read  += size   # (otica do mestre, ver nota acima)
if iden & E.ID_TYPE_OUT: write += size
```

### 4.3 Tabela de modulos (read/write na otica do MESTRE)

`decode_cfg_io` decodificado para os GSDs reais:

| GSD / Modulo | cfg byte(s) | read (mestre LE) | write (mestre ESCREVE) | Roda no pyprofibus? |
|---|---|---|---|---|
| Baumer Class 2 Singleturn | `0xF0` | 2 | 2 | Sim |
| Baumer Class 1 Singleturn | `0xD0` | 2 | 0 | **Nao** (write=0) |
| **RM3007 Class 1 Singleturn** | `0xD0` | 2 | 0 | **Nao** (write=0) |
| **RM3007 Class 1 Multiturn** | `0xD1` | 4 | 0 | **Nao** (write=0) — perfil "correto" porem barrado |
| **RM3007 Class 2 Singleturn** | `0xF0` | 2 | 2 | Sim (mas perde voltas -> artefato `09b0`) |
| **RM3007 Class 2 Multiturn** | `0xF1` | **4** | **4** | **Sim — USAR ESTE** p/ multivolta completo |
| ifm 2.1 Single/Multi | `0xF1` | 4 | 4 | Sim |
| ifm 2.2 Single/Multi | `0xF1, 0xD0` | 6 | 4 | Sim |

GSD do RM3007: `gsd/IFM_0E75.gsd` (ident `0x0E75`, IFM RN30xx/RM30xx). GSD do Baumer: `gsd/PB13DPV0.gsd` (ident `0x059B`).

### 4.4 Por que Class 1 nao roda e por que Class 2 le a MESMA posicao

- **Class 1 nao roda:** `write==0` -> `addSlave` rejeita (`dp_master.py:381-386`) E o loop nunca manda Data_Exchange_Req sem `toSlaveData`/com `inputSize==0` (`dp_master.py:691-701`). Ver item 4 da saga.
- **Class 2 le a mesma posicao:** Class 2 Multiturn (`0xF1`) le os **mesmos 4 bytes** de posicao multivolta de 32 bits que a Class 1 Multiturn leria; a unica diferenca e que o mestre **tambem** escreve 4 bytes (control word). Mandando esses 4 bytes **zerados** (control word 0 = sem preset), a leitura e identica a Class 1 — apenas satisfazemos a exigencia `inputSize>=1` do pyprofibus.

### 4.5 Interpretacao do valor multivolta

Bytes crus big-endian (PROFIBUS, MSB primeiro). Para RM3007 com `spt = stepsPerTurn = 8192`:
```
value     = parseInt(hex, 16)                # 1..4 bytes, MSB primeiro
single    = ((value % spt) + spt) % spt      # posicao na volta (modulo seguro)
turns     = floor(value / spt)               # nº de voltas (so faz sentido com >=4 bytes)
angle     = (single / spt) * 360             # graus
multiturn = (hex.length/2) >= 4              # true com >=4 bytes
```
Exemplos verificados: `09b0` -> single, 0 voltas, 109 graus. `000209b0` -> multi, value=133552 (`0x000209B0`), floor(133552/8192) = 16 voltas, single = 133552 - 16*8192 = 2480, 109 graus. (`web/static/app.js:12-24`.)

---

## 5. MAPA DE ARQUIVOS ALTERADOS NESTA SESSAO

Todos os caminhos sao relativos a `/home/ubuntu/repos/pi5-profibus-amg11/`. **Nenhuma destas mudancas foi commitada ainda.**

| Arquivo | O que mudou |
|---|---|
| `profibus_amg11/gsd_info.py` | `decode_cfg_io` (parser canonico do byte cfg -> `(read, write)`); `ParamPreview.in_size`/`out_size`; `preview_params`/`preview_to_dict` passam a emitir os tamanhos derivados |
| `profibus_amg11/generic.py` | `make_generic_slave_desc(gsd_bytes, address, modules)` deriva tamanhos via `decode_cfg_io` + **inverte** (`input_size=write, output_size=read`) + **guard `write<=0`** levanta `GenericError("so-leitura...")`; `GenericDpMaster` deriva `input_size`/`output_size` do desc e dimensiona `self._out = bytearray(output_size)` |
| `web/generic_poller.py` | `ParamSpec` **sem** `input_size`/`output_size` (tamanhos vem do GSD, nao da UI) |
| `web/controller.py` | `_begin_generic` constroi `ParamSpec` **sem** tamanhos; `_do_set_output` valida hex contra `self._generic.snapshot().output_size` (derivado do GSD) antes de o poll lancar `DpError` |
| `serve.py` | `make_generic` deriva `src.input_size`/`src.output_size` do `GenericDpMaster` e passa ao `GenericPoller` |
| `web/static/app.js` | remove campos manuais de I/O; preview mostra "le/escreve" (`in_size`/`out_size`); aviso so-leitura (`readonly`) + botao desabilitado; `paramErr` espelha `bus.diag` na aba GSD; `decodePosition()`; gauge estilo Baumer + linhas + campo "passos/volta"; `GsdView` recebe `bus`; `App` passa `bus` |
| `tests/*` | testes de `decode_cfg_io`; derive+flip; read-only levanta `GenericError`; simulacao Class 2; `_io` com `output_size=2`; `_spec` sem tamanhos |

**Estado da suite:** `130 passed, 1 skipped`.

Rodar a suite:
```
cd /home/ubuntu/repos/pi5-profibus-amg11 && .venv/bin/python -m pytest -q
```
(Para so o total: `... 2>&1 | tail -5`.) O skip e `test_build_scan_phy_uses_given_baud` (sem porta serial real).

---

## 6. COMO VALIDAR / RODAR

### 6.1 Simulacao (sem hardware)

```
cd /home/ubuntu/repos/pi5-profibus-amg11

# CLI: leitura unica simulada
.venv/bin/python run.py --sim --once          # imprime raw/angle/bytes, returncode 0

# CLI: varredura simulada (acha o escravo do .conf, addr 3)
.venv/bin/python run.py --sim --scan          # saida contem addr=3 e "slave"

# Ferramenta web simulada (porta 8600)
.venv/bin/python serve.py --sim               # abrir http://localhost:8600
```

### 6.2 Hardware (Pi 3)

- `.conf` real: `config/amg11.conf` — PHY serial `/dev/serial0`, baud `19200`, DP master_addr `1`, `[SLAVE_3]` AMG11 addr 3 com `module_0 = 16 Bit Class 2 Encoder` (`0xF0`).
- `config/encoder.yaml`: `resolution_bits: 13`, `direction: cw`, `offset: 0`, `control_word: 0x0000`.
- Subir a web: `.venv/bin/python serve.py` (sem `--sim`). Abrir aba **GSD**, upload/selecionar `IFM_0E75.gsd`, escolher **Class 2 Multiturn**, endereco **9**, "Parametrizar e ler".

### 6.3 O que esperar (RM3007)

- Apos parametrizar com **Class 2 Multiturn** e o escravo aceitar Chk_Cfg/Set_Prm: status **verde**, ~**31 Hz**, `diag` OK, painel de I/O com gauge estilo Baumer.
- **Artefato a reconhecer:** "entrada `09b0`" = **2 bytes** = voce esta num modulo **Singleturn** (Class 2 `0xF0` = 2/2). `0x09B0 = 2480/8192 ~ 109 graus`, **sem contagem de voltas**. Para multivolta, trocar para **Class 2 Multiturn** (`0xF1`, **4 bytes**), entao `in_hex` tera 4 bytes (ex.: `000209b0` -> 16 voltas / 109 graus).
- Se **nao** chegar ao Data_Exchange: a UI dira "conectando" para sempre (bug item 5). O **motivo real** ("faulty configuration (Chk_Cfg)" / "received data size ... does not match") so estara no **stdout do `serve.py`** — olhar o terminal.

---

## 7. ITENS ABERTOS / PROXIMOS PASSOS (priorizados)

### (a) COMMITAR o trabalho desta sessao [PRIORIDADE 1]
Branch `feat/web-dashboard-v1`, working tree sujo. Commitar os fixes 1-6 (mapa na secao 5) + a atualizacao de docs. Sugestao de granularidade: um commit para o fix de tamanhos/inversao (itens 1-2), um para surfacing de erro na aba GSD (item 3) + guard so-leitura (item 4), um para a visualizacao (item 6), um para docs. Rodar `pytest -q` antes (`130 passed, 1 skipped`). Limpar/squashar os 3 commits "resenha" se apropriado.

### (b) BUG #5 — surfacing do motivo de Chk_Cfg na UI [PRIORIDADE 2]
O `pyprofibus.__errorMsg` so faz `print()` (`dp_master.py:364-365`). **Esboco de abordagem** (sem fork da lib, menos invasivo):
1. Capturar stdout do pyprofibus durante o `step()` do `GenericDpMaster` (redirecionar/`contextlib.redirect_stdout` num buffer) e extrair a ultima linha que contenha "ERROR" / "Chk_Cfg" / "does not match"; expor como `fault: Optional[str]` no `GenericDpMaster`.
2. Alternativa mais limpa: **monkeypatch** de `DpMaster.__errorMsg` (ou da instancia) para alem do `print` gravar numa fila/atributo consultavel; `GenericDpMaster.diag` passa a retornar esse fault quando `connected==False` por > N ciclos (em vez de "conectando" eterno, `generic.py:123`).
3. Propagar via `IoSnapshot.diag` -> ja existe o caminho `replace(snap, diag=self._io_error)` no controller (`controller.py:127-128`); reaproveitar para `fault`.
Beneficio: encerra a "depuracao cega". Risco: o nome `__errorMsg` e name-mangled (`_DpMaster__errorMsg`); o patch precisa usar o nome mangled.

### (c) Class 1 input-only — patch no DX do pyprofibus [PRIORIDADE 3, requer hardware]
Para suportar o perfil **correto** (Class 1 Multiturn, so-leitura). **Esboco:** patch em `__runSlave_dataExchange` para enviar um `Data_Exchange_Req` **vazio** (du=b"") mesmo com `inputSize==0`, so para provocar a resposta de saida (leitura). Tambem relaxar o guard `addSlave` (`dp_master.py:381-386`) para aceitar `inputSize==0` quando `outputSize>0`. **Risco:** mexe na lib de terceiros; precisa **validar no hardware** (nem todo escravo aceita DX_Req vazio; pode violar o protocolo). Manter como fork/patch opcional, nao no caminho padrao. Por ora, o contorno Class 2 Multiturn resolve.

### (d) Fase C — perfis declarativos de decodificacao [PRIORIDADE 4]
Decodificar o I/O cru em grandeza de engenharia de forma declarativa; o `decode` do AMG11 vira "so mais um perfil". O `decodePosition()` no cliente (`app.js:12-24`) e um primeiro passo (decode no front). Falta spec/plano (criar em `docs/superpowers/specs/` e `docs/superpowers/plans/`).

### (e) Atualizar memorias e DOCUMENTACAO.md [PRIORIDADE 5]
- `docs/DOCUMENTACAO.md` JA FOI atualizada nesta sessao (904 linhas; B2 + RM3007 + visualizacao + gotchas + testes 130/1). Item resolvido — manter sincronizada em mudancas futuras.
- Criar/atualizar memoria do usuario sobre o RM3007 (vide `~/.claude/.../memory/`).

---

## 8. ARMADILHAS CONHECIDAS (GOTCHAS) PARA A PROXIMA SESSAO

1. **Inversao escravo-centrica.** A unica fronteira de inversao e `make_generic_slave_desc` (`generic.py:54-61`); a re-exposicao mestre-centrica e `generic.py:94-96`. Mexer em qualquer um sem mexer no outro quebra direcao de I/O silenciosamente.
2. **`_out = bytearray(output_size)` deve usar o tamanho de ESCRITA** (= `slave.inputSize`). Se voltar a usar o tamanho de leitura, o primeiro `poll()` lanca `DpError` antes do `_publish_io()` e o painel some (item 2 da saga).
3. **Bug #5 ainda ativo:** se o RM3007 (ou qualquer escravo) nao chegar ao DX, a UI dira "conectando" PARA SEMPRE; o motivo real so esta no **stdout do servidor**. Sempre olhar o terminal do `serve.py` ao depurar Chk_Cfg.
4. **`09b0` (2 bytes) = Singleturn, nao Multiturn.** Se aparecer 2 bytes, voce escolheu Class 2 Singleturn (`0xF0`); troque para Class 2 Multiturn (`0xF1`, 4 bytes).
5. **Class 1 nunca roda no pyprofibus** (write=0). Nao tente "consertar" escolhendo Class 1 Multiturn pela UI — o guard `generic.py:54-58` levanta `GenericError`. Use Class 2 Multiturn.
6. **`bus_snapshot_to_dict` e duck-typed** (`web/snapshot.py:71`); acessa `st.station_type.value`. Se `Station` mudar, quebra em runtime SO ao serializar — e o loop WS engole a excecao (`server.py:61-62`), fechando a conexao sem log. Depuracao de "o socket cai" e cega.
7. **WS engole TODA excecao e fecha** (`server.py:61-62`); um bug de serializacao e indistinguivel de desconexao. Nada e logado.
8. **`GenericPoller.step()` reporta `connected = source.connected` mesmo quando `diag` ja e "sem leitura"** (`generic_poller.py:49,66`) — pode ficar incoerente (connected=True + "sem leitura").
9. **`replace(snap, diag=self._io_error)` persiste o diag de erro** ate o proximo `set_output` valido ou `_begin_generic`/`_teardown_generic` (`controller.py:127-128`, `_io_error` limpo so em `_do_set_output` ok ou begin/teardown). Um "saida hex invalida" gruda no diag.
10. **`_chdir` (definido em `master.py:16`, reusado por `generic.py` e `build_scan_phy`)** roda todo `makeDPM`/`makePhy`/`PbConf.fromFile` com `cwd = conf_path.parent.parent` (premissa: `.conf` vive em `config/`, raiz 2 niveis acima). Se o `.conf` sair de `config/`, o GSD relativo nao resolve.
11. **Single-serial-owner:** so um PHY por serial. Nunca abrir scan e mestre simultaneamente. O `BusController` ja faz `_teardown_generic()`/`_teardown_engine()` nas transicoes; manter essa invariante.
12. **Re-armar saida por ciclo:** tanto `Amg11Master.poll` quanto `GenericDpMaster.poll` chamam `setMasterOutData(bytearray(self._out))` a cada passo para sustentar o Data_Exchange. Nao remover.
13. **`releaseBus()` antes de cada probe** (`scan.py:59-63`) e correcao de timing FDL essencial (`maxReplyLen=255` segura ~146 ms @19200). Nao tocar.
14. **`pyprofibus` nao esta instalado no ambiente de doc** — para inspecionar mascaras/estados, ler o source em `/home/ubuntu/repos/pi5-profibus-amg11/.venv/lib/python3.12/site-packages/pyprofibus/` (`dp.py`, `dp_master.py`, `conf.py`).
15. **DOCUMENTACAO.md ja foi atualizada nesta sessao** (904 linhas, B2 + RM3007 + visualizacao). Era defasada (B2 "em andamento", testes 106/1); agora reflete o estado atual (testes 130/1).
16. **Modo `idle` congela o encoder:** `controller.step()` so atualiza `_encoder_snap` no ramo `exchange` — nao ha ramo `idle`. Se a troca falha ao iniciar (`_mode="idle"`, `bus.diag="erro ao iniciar: ..."`), a aba Encoder mostra a ULTIMA leitura congelada, nao "sem dados". Depurar "a UI mostra leitura velha quando o encoder some" e cego por isso.
17. **Scan varre 0..126:** sem `addresses` explicito, `BusController` usa `range(127)` e `_begin_scan` exclui SO o `master_addr` — entao `0` e `126` (default de escravo nao-configurado) tambem sao sondados.
18. **3N envios/ciclo no WS:** `encoder`+`bus`+`io` sao enviados sempre (sem coalescing/diff); com N clientes sao 3N envios por tick (~15 Hz).
19. **`GsdStore._safe` e seguro mas sem `resolve()`:** a defesa contra path-traversal e o allowlist `_SAFE` (`^[A-Za-z0-9._-]+\.gsd$`) + checagens explicitas de `/`,`\`,`..` (`gsd_store.py:9,16-19`). Bloqueia traversal na pratica; so nao ha canonicalizacao final — manter o allowlist se mexer.

---

### Apendice — caminhos uteis (absolutos)

- Dominio: `/home/ubuntu/repos/pi5-profibus-amg11/profibus_amg11/{generic.py,gsd_info.py,master.py,encoder.py,config.py,source.py,scan.py}`
- Web: `/home/ubuntu/repos/pi5-profibus-amg11/web/{controller.py,server.py,snapshot.py,scanner.py,settings.py,generic_poller.py,poller.py,gsd_store.py,gsd_api.py}`
- Frontend: `/home/ubuntu/repos/pi5-profibus-amg11/web/static/{index.html,app.js,styles.css,vendor/}`
- Entrypoints: `/home/ubuntu/repos/pi5-profibus-amg11/{run.py,serve.py}`
- Config: `/home/ubuntu/repos/pi5-profibus-amg11/config/{amg11.conf,encoder.yaml}` (`config/bus.json` e runtime/gitignored, nao existe versionado)
- GSDs: `/home/ubuntu/repos/pi5-profibus-amg11/gsd/{PB13DPV0.gsd (Baumer 0x059B), IFM_0E75.gsd (IFM 0x0E75 = RM3007)}`
- Docs: `/home/ubuntu/repos/pi5-profibus-amg11/docs/{DOCUMENTACAO.md, CONTEXTO-COMPLETO.md (este), superpowers/specs/, superpowers/plans/}`
- pyprofibus (vendor): `/home/ubuntu/repos/pi5-profibus-amg11/.venv/lib/python3.12/site-packages/pyprofibus/{dp.py,dp_master.py,conf.py}`
- Testes: `/home/ubuntu/repos/pi5-profibus-amg11/tests/` (22 de teste + `fakes.py`)
