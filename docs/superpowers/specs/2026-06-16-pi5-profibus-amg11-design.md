# Design — Mestre PROFIBUS-DP no Raspberry Pi 5 para encoder Baumer AMG 11

**Data:** 2026-06-16
**Autor:** Mateus Nascimento (com Claude)
**Status:** Aprovado para implementação

## 1. Objetivo

Fazer um Raspberry Pi 5 atuar como **mestre PROFIBUS-DP (classe 1, DPM1)** e ler
ciclicamente a posição de um encoder absoluto **Baumer (Hübner) AMG 11 P 13 Z0**
via um conversor USB-RS485, usando a biblioteca **pyprofibus** (mestre em Python
puro). Entregável: uma CLI + biblioteca reutilizável que lê a posição e a expõe
em console/log, com modo de simulação para desenvolver sem hardware.

## 2. Hardware alvo

| Item | Definição |
|---|---|
| Mestre | Raspberry Pi 5 (Linux não-RT) |
| PHY | Conversor **USB-RS485 com auto-direção** (FTDI/CH340) → `/dev/ttyUSB0`. Sem toggle de RTS; a direção TX/RX é resolvida no hardware do conversor. |
| Escravo | Baumer AMG 11 P 13 Z0, encoder absoluto PROFIBUS-DP |
| Endereço escravo | **3**, fixado nas chaves físicas (DIP/rotary) do encoder. O GSD declara `Set_Slave_Add_supp = 0` → **não é possível** setar o endereço pelo barramento. |
| Endereço mestre | 1 |
| Baud | **19200** como ponto de partida (encoder faz auto-baud, 9.6k–12M). |
| Terminação | Resistores de terminação PROFIBUS (390/220/390 Ω) nas pontas do barramento. |

## 3. Fatos extraídos do GSD (`PB13DPV0.gsd`)

Fonte: `~/repos/PB13DPV0.gsd` (Baumer group / Baumer Hübner, modelo `xMG_HEAG`,
perfil Encoder V1.1).

- `Ident_Number = 0x059B` — validado pelo mestre na parametrização.
- `DP_Encoder_class = 2`, perfil 1.1.
- **Módulos disponíveis:**
  - `"16 Bit Class 1 Encoder"` config `0xD0` → **2 bytes de entrada** (posição
    16-bit), sem saída.
  - `"16 Bit Class 2 Encoder"` config `0xF0` → **2 bytes in + 2 bytes out**
    (palavra de controle/preset/scaling).
- `User_Prm_Data_Len = 0x12` (18 bytes). Default do GSD:
  `00 0A 00 00 20 00 00 00 20 00 00 00 00 00 00 00 00 00`.
  - Byte 1 = `0x0A` → Code sequence=CW(0), Class 2 functionality=Enable(1),
    Commissioning diag=No(0), Scaling=Enable(1).
  - Measuring units per rev = `0x2000` = **8192 = 2¹³** (13 bit singleturn).
  - Total measuring range = `0x2000` = 8192 → **singleturn** (faixa total = 1 volta).
- Bauds suportados: 9.6k, 19.2k, 93.75k, 187.5k, 500k, 1.5M, 3M, 6M, 12M; auto-baud.
- `Freeze_Mode_supp = 1`, `Sync_Mode_supp = 1`.

**Conclusão:** a posição é transmitida como **Unsigned16 big-endian**, 13 bits
significativos (0–8191), singleturn. Sem contagem de multivoltas neste modelo.

## 4. Arquitetura

Abordagem **A** (escolhida): arquivo `.conf` do pyprofibus aponta para o GSD; o
parser/`GsdInterp` do pyprofibus gera os telegramas de parametrização e
configuração a partir do GSD. Por cima fica uma camada fina em Python para
decodificar os bytes, logar e simular.

```
pi5-profibus-amg11/
├── README.md                 # fiação RS485, deploy no Pi5, troubleshooting
├── requirements.txt          # pyprofibus, pyserial
├── config/
│   ├── amg11.conf            # conf do mestre pyprofibus (PHY, addr, baud, slave→GSD)
│   └── encoder.yaml          # resolução (13 bit), módulo (class1|class2), offset, sentido
├── gsd/
│   └── PB13DPV0.gsd          # cópia do GSD da Baumer
├── src/profibus_amg11/
│   ├── __init__.py
│   ├── master.py             # carrega conf, monta DPM1, roda o loop cíclico
│   ├── encoder.py            # decodifica bytes → posição/ângulo (EncoderReading)
│   └── config.py             # lê/valida encoder.yaml
├── run.py                    # CLI: --conf, --sim, --once, --hz, --verbose
└── scripts/
    ├── setup_pi5.sh          # grupo dialout + latency_timer do FTDI = 1 ms
    └── 99-rs485.rules        # udev: nome estável /dev/profibus0 (opcional)
```

### Componentes

- **`config.py`** — carrega `encoder.yaml` num dataclass `EncoderConfig`
  (`resolution_bits=13`, `module="class1"`, `direction="cw"`, `offset=0`).
  Responsabilidade única: ler/validar config. Depende só de PyYAML/stdlib.
- **`encoder.py`** — função pura `decode(data: bytes, cfg) -> EncoderReading`.
  Converte 2 bytes big-endian em `raw` (0–8191), aplica sentido e offset, calcula
  `angle_deg = raw / 2**bits * 360`. Sem efeitos colaterais → testável isolado.
- **`master.py`** — `Amg11Master`: usa `PbConf.fromFile()` para montar o `DpMaster`
  e o `DpSlaveDesc` (addr 3, GSD), ajusta o bit "Class 2 functionality" dos
  user-params conforme o módulo, chama `initialize()` e expõe `read_once()` e
  `run(callback, hz)`. Encapsula a máquina de estados DP do pyprofibus.
- **`run.py`** — CLI fina: parseia args, instancia `Amg11Master`, imprime leituras.

### Fluxo de dados

```
encoder (addr 3) --RS485--> USB-RS485 --/dev/ttyUSB0--> pyprofibus PHY serial
   -> DPM1 Data_Exchange (cíclico) -> 2 bytes -> encoder.decode() -> EncoderReading
   -> callback (print/log)
```

### Seleção de módulo (`encoder.yaml: module`)

- **`class1` (default, `0xD0`):** 2 B in, posição pura, sem bytes de saída.
  Alinhado a "começar simples". User-param com Class 2 functionality desabilitado.
- **`class2` (`0xF0`):** 2 B in + 2 B out. Habilita **preset/zero por software** e
  scaling pela palavra de controle. User-param com Class 2 functionality habilitado
  (defaults do GSD). Em leitura normal a palavra de saída fica em estado neutro
  (sem comando de preset).

## 5. Modo de simulação (dev sem hardware)

`run.py --sim` usa o **PHY dummy** do pyprofibus para rodar todo o loop do mestre
nesta bancada x86 (sem RS485). Permite validar parsing do GSD, decodificação e CLI
antes de tocar no Pi5. O dummy injeta bytes de posição configuráveis para exercitar
o `decode()`.

## 6. Setup no Pi5

`scripts/setup_pi5.sh`:
- adiciona o usuário ao grupo `dialout`;
- fixa `latency_timer = 1` (ms) do FTDI
  (`/sys/bus/usb-serial/devices/ttyUSB0/latency_timer`) — **crítico** para o timing
  PROFIBUS em Linux não-RT;
- instala (opcional) a regra udev `99-rs485.rules` dando nome estável `/dev/profibus0`.

## 7. Tratamento de erros e diagnóstico

- Perda de `Data_Exchange` / escravo mudo → log + tentativa de re-parametrização
  (a máquina de estados do pyprofibus reinicia o ciclo; o loop captura exceções e
  faz reconexão com backoff).
- Na conexão e em falhas, imprimir o **diagnóstico DP do escravo** (status flags,
  ident number) para depurar parametrização/config.
- Validação de tamanho dos dados de entrada (esperado 2 bytes) antes de decodificar.

## 8. Testes

- **Unitário (sem hardware):** `decode()` com vetores conhecidos
  (`0x0000→0°`, `0x0800→90°`, `0x1000→180°`, `0x1800→270°`), mais casos de
  sentido CCW (espelha o ângulo) e de `offset` (preset por software).
- **Integração (sim):** `run.py --sim --once` roda o mestre com PHY dummy e
  confirma uma leitura ponta-a-ponta.
- **Validação em campo (Pi5):** `run.py --once` com o encoder real; conferir que o
  ângulo acompanha o eixo e que o diagnóstico não acusa erro.

## 9. Caveats de engenharia (documentar no README)

- pyprofibus é mestre em **Python puro**; em Linux não-RT a confiabilidade de timing
  depende de **baud moderado + `latency_timer=1`**. Para o encoder em 19.2k–500k é
  tranquilo. Se um dia exigir 12 Mbit/s, o caminho é uma **PHY dedicada (FPGA)**.
- Endereço do escravo é **só por hardware** (GSD: `Set_Slave_Add_supp=0`).
- Conversor USB-RS485 deve ser de **auto-direção**; modelos que dependem de RTS
  adicionam latência e podem comprometer o timing.

## 10. Fora de escopo (YAGNI)

- Dashboard web / MQTT / CSV (escopo é CLI + biblioteca).
- Multivoltas (modelo é singleturn 13-bit).
- Múltiplos escravos no barramento (1 encoder).
- DPV1 (acesso acíclico) — o GSD é DPV0.
