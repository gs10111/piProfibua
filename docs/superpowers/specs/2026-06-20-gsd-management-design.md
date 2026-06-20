# Design — Gestão e inspeção de GSD (offline) + preview de parametrização

**Data:** 2026-06-20
**Status:** Aprovado para implementação (decisões no recomendado, por delegação do usuário)
**Fase:** sub-projeto **B1** de **A → B → C** (B = parametrizar qualquer escravo)
(B foi decomposto: **B1** = gestão/inspeção de GSD + preview offline · **B2** = parametrizar ao vivo + I/O cru)

## 1. Objetivo

Dar ao comissionador a **biblioteca de GSDs**: enviar o `.gsd` de qualquer
dispositivo pela web, guardá-lo, inspecioná-lo (fabricante, modelo, ident,
módulos, MaxTSDR) e **pré-visualizar a parametrização** — escolher módulo(s) e ver
os bytes de `Chk_Cfg` (config) e `Set_Prm` (user prm) + o ident number que seriam
enviados. **Tudo offline**, sem tocar no barramento. É a fundação de B2, que
efetivamente envia esses bytes e alcança o Data_Exchange.

## 2. Escopo

**Dentro:**
- Upload de `.gsd` por **HTTP** (não WebSocket), validado por parse na chegada,
  armazenado em `gsd/`.
- Listagem dos GSDs guardados (com resumo).
- Inspeção de um GSD: fabricante, modelo, revisão, ident (0xXXXX), order number,
  `Modular_Station`, `DPV1_Slave`, módulos disponíveis (nome + config bytes +
  preset), MaxTSDR por baud.
- **Preview de parametrização (dry-run):** dada a escolha de módulo(s), computar
  ident + **cfg bytes** (`getCfgDataElements`) + **user_prm bytes**
  (`getUserPrmData`) — exatamente o que um `Set_Prm`/`Chk_Cfg` enviaria. Puro.
- Frontend: nova aba **GSD** (upload + lista + inspetor + preview).

**Fora (B2/C ou nunca):**
- Enviar de fato `Set_Prm`/`Chk_Cfg`, alcançar Data_Exchange, ler/escrever I/O →
  **B2** (novo modo no `BusController`).
- Decodificar I/O em grandeza de engenharia → **C** (perfis).
- Derivar tamanho de entrada/saída a partir dos cfg bytes → **B2** (o pyprofibus
  já deriva isso no DX; em B1 mostramos os bytes crus, não os tamanhos).
- Persistir a seleção de módulos/parametrização por dispositivo → **B2**.
- Baud acima do teto do Pi não-RT continua valendo e documentado (herdado de A).

## 3. Verdade técnica (aterrada no fonte e nas GSDs reais)

- **`GsdInterp.fromBytes(data, filename)`** (herdado de `GsdParser`) decodifica
  `latin_1` e faz parse — ideal para upload HTTP (sem caminho/arquivo temporário).
- Campos via `getField(...)`: `Vendor_Name`, `Model_Name`, `Revision`,
  `Ident_Number`, `OrderNumber`, `Module` (lista; cada `module.name`,
  `module.getField("Preset")`, `module.configBytes`), `isModular()`, `isDPV1()`.
- Preview: `clearConfiguredModules()` → `setConfiguredModule(nome)` →
  `getCfgDataElements()` (lista de `DpCfgDataElement`, cada um com `getDU()` →
  bytes) + `getUserPrmData()` (bytes) + `getIdentNumber()` + `getMaxTSDR(baud)`.
- **Validado com as 2 GSDs reais do repo:**
  - `gsd/PB13DPV0.gsd` → Baumer, ident **0x059B**, modular, módulos "16 Bit Class
    2/1 Encoder"; preview de "16 Bit Class 2 Encoder" → cfg `f0`, user_prm
    `000a0000200000002000...`, MaxTSDR@19200 `60`.
  - `gsd/IFM_0E75.gsd` → ifm, ident **0x0E75**, modular, 8 módulos (single/multiturn).
- **Dispositivos modulares têm cfg vazio até escolher um módulo** — por isso o
  preview com seleção de módulo é o que dá valor.

## 4. Arquitetura (em camadas, SOLID)

```
 frontend Preact ──HTTP /api/gsd*──▶ web/server.py (Flask)
   aba "GSD"                            │ usa
                                        ▼
                                 web/gsd_store.py · GsdStore   (app: armazenamento)
                                        │ valida via
                                        ▼
                          profibus_amg11/gsd_info.py           (domínio: wrap GsdInterp)
                          parse_gsd / preview_params (puros)
```

A telemetria ao vivo (WebSocket `/ws`, encoder + barramento) **não muda**: GSD é
CRUD HTTP comum, separado do streaming.

**SRP — cada unidade:**
- **`profibus_amg11/gsd_info.py`** (domínio; única dependência de `GsdInterp`):
  - `ModuleInfo` (frozen: `name`, `config_hex`, `preset`).
  - `GsdSummary` (frozen: `filename`, `vendor`, `model`, `revision`, `ident`,
    `order`, `modular`, `dpv1`, `modules: tuple[ModuleInfo,...]`,
    `max_tsdr: dict[int,int|None]`).
  - `ParamPreview` (frozen: `ident`, `modules: tuple[str,...]`, `cfg_hex`,
    `user_prm_hex`).
  - `parse_gsd(data: bytes, filename: str) -> GsdSummary` (puro; levanta
    `GsdInfoError` se não parsear).
  - `preview_params(data: bytes, module_names: list[str]) -> ParamPreview`
    (puro; `clearConfiguredModules` + `setConfiguredModule` por nome). Se
    `module_names` vazio: usa os módulos configurados por default do GSD.
  - `to_dict` (puros) para o contrato JSON.
- **`web/gsd_store.py`** (app):
  - `GsdStore(directory)`: `list() -> list[str]` (só `*.gsd`), `save(filename,
    data: bytes) -> GsdSummary` (valida via `parse_gsd`; rejeita inválido e
    nome inseguro), `read(name) -> bytes`, `summary(name) -> GsdSummary`.
  - **Segurança de caminho:** nome saneado (só basename, só `[\w.-]`, sufixo
    `.gsd`); rejeita traversal. Testado.
- **`web/gsd_api.py`** (app; handlers puros + registro):
  - `register_gsd_routes(app, store)` adiciona as rotas REST.
  - Handlers finos chamam `store`/`gsd_info` e devolvem JSON; erros → 400/404 com
    `{"error": ...}`. Testáveis via Flask test-client.
- **`web/server.py`:** `create_app(controller, gsd_store=None)` — registra as rotas
  GSD se `gsd_store` for dado. WS inalterado.
- **`serve.py`:** monta `GsdStore(ROOT/"gsd")` e passa ao `create_app`.
- **`web/static/`:** aba GSD (upload, lista, inspetor, preview).

### Estrutura de arquivos (novos vs editados)
```
profibus_amg11/
  gsd_info.py        # parse_gsd, preview_params, dataclasses + to_dict   [novo]
web/
  gsd_store.py       # GsdStore (list/save/read/summary, path-safety)     [novo]
  gsd_api.py         # register_gsd_routes + handlers                     [novo]
  server.py          # create_app(controller, gsd_store=None)            [edição]
  static/
    app.js           # + aba GSD (upload/lista/inspetor/preview)         [edição]
    styles.css       # estilos da aba GSD                                [edição]
serve.py             # monta GsdStore                                    [edição]
tests/
  test_gsd_info.py       # parse + preview das 2 GSDs reais
  test_gsd_store.py      # save valida, list, read, traversal (tmp_path)
  test_gsd_api.py        # upload/list/get/preview via test-client
  test_frontend_assets.py  # + asserções da aba GSD                      [edição]
```

## 5. Contrato HTTP (`/api/gsd`)

- `GET /api/gsd` → `{"gsds": [ <GsdSummary dict>, ... ]}` (resumo de cada arquivo).
- `POST /api/gsd` (corpo: arquivo `multipart/form-data` campo `file`, **ou** bytes
  crus com header `X-Filename`) → valida + salva → `200 {<GsdSummary>}`; parse
  falha → `400 {"error": ...}`; nome inseguro → `400`.
- `GET /api/gsd/<name>` → `{<GsdSummary>}`; ausente → `404`.
- `POST /api/gsd/<name>/preview` (corpo JSON `{"modules": ["<nome>", ...]}`) →
  `{<ParamPreview>}`; módulo inexistente → `400 {"error": ...}`.

`GsdSummary` dict: `{filename, vendor, model, revision, ident, ident_hex, order,
modular, dpv1, modules:[{name, config_hex, preset}], max_tsdr:{"19200":60, ...}}`.
`ParamPreview` dict: `{ident, ident_hex, modules:[...], cfg_hex, user_prm_hex}`.

## 6. Frontend (aba "GSD", mesma stack vendorizada)

- Terceira aba **GSD** (além de Encoder / Barramento).
- **Upload:** `<input type=file accept=".gsd">` + botão **Enviar** → `POST /api/gsd`
  (multipart). Erro de parse mostra mensagem clara.
- **Lista:** tabela dos GSDs guardados (modelo · ident · módulos). Clicar abre o
  inspetor.
- **Inspetor:** fabricante/modelo/revisão/ident, modular/DPV1, MaxTSDR; lista de
  módulos com um seletor (escolher módulo(s)).
- **Preview:** ao escolher módulo(s), chama `POST .../preview` e mostra **ident +
  cfg bytes (hex) + user_prm (hex)** — "o que a parametrização enviaria". Numerais
  em mono.
- Princípios v1/A mantidos: tema escuro, acento único, **sem emoji**, AA, foco
  visível, copy direta.

## 7. Tratamento de erros

- Upload de arquivo que não parseia → 400 com a mensagem do `GsdError`, **nada é
  salvo**. Servidor de pé.
- Nome de arquivo inseguro (traversal, sem `.gsd`) → 400, não grava.
- `GET`/`preview` de GSD inexistente → 404.
- Preview com módulo inexistente → 400 (mensagem do `GsdError`).
- O diretório `gsd/` é criado se não existir.

## 8. Testes (TDD, sem test-smells)

- **`gsd_info`**: `parse_gsd` das 2 GSDs reais → ident/modular/módulos corretos
  (0x059B/Baumer, 0x0E75/ifm). `preview_params` do AMG11 com "16 Bit Class 2
  Encoder" → `cfg_hex == "f0"`, `user_prm_hex` começa com `000a`, ident 0x059B.
  Módulo inexistente → `GsdInfoError`. `to_dict` puro.
- **`GsdStore`** (`tmp_path`): `save` de bytes válidos → arquivo gravado + summary;
  `save` de lixo → erro, nada gravado; `list` retorna só `.gsd`; `read` round-trip;
  nome com `../` ou sem `.gsd` → rejeitado.
- **`gsd_api`** (test-client): `POST` multipart válido → 200 + summary; inválido →
  400; `GET /api/gsd` lista; `GET /api/gsd/<name>` → summary; `POST preview` →
  cfg/prm. Usa um `GsdStore` apontando p/ `tmp_path`.
- **frontend assets**: aba "GSD" e upload presentes; sem emoji; sem Inter.
- **Os testes de A/v1 seguem verdes** (WS e BusController intactos; `create_app`
  ganha um parâmetro **opcional** `gsd_store`).

## 9. Dependências novas

Nenhuma. Flask já lida com upload multipart. Sem libs novas. As GSDs vivem em
`gsd/` (já versionado parcialmente; uploads de runtime do usuário **não** entram no
git — ver §10).

## 10. Versionamento de `gsd/`

As 2 GSDs de referência (`PB13DPV0.gsd`, `IFM_0E75.gsd`) ficam versionadas (fixtures
de teste). Uploads futuros do usuário em produção são estado de runtime; para não
poluir o git, o `.gitignore` ignora `gsd/*.gsd` **exceto** essas duas
(`!gsd/PB13DPV0.gsd`, `!gsd/IFM_0E75.gsd`).
