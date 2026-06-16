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
│   └── encoder.yaml          # resolução (13 bit), offset, sentido, control_word
├── gsd/
│   └── PB13DPV0.gsd          # cópia do GSD da Baumer
├── profibus_amg11/           # pacote flat (sem src/, roda no Pi sem install)
│   ├── __init__.py
│   ├── master.py             # carrega conf, monta DPM1, roda o loop cíclico
│   ├── encoder.py            # decodifica bytes → posição/ângulo (EncoderReading)
│   └── config.py             # lê/valida encoder.yaml
├── tests/                    # pytest (test_config, test_encoder, test_conf_load, test_master_sim)
├── run.py                    # CLI: --conf, --sim, --once, --hz, --verbose
└── scripts/
    ├── setup_pi5.sh          # grupo dialout + latency_timer do FTDI = 1 ms
    └── 99-rs485.rules        # udev: nome estável /dev/profibus0 (opcional)
```

### Componentes

- **`config.py`** — carrega `encoder.yaml` num dataclass `EncoderConfig`
  (`resolution_bits=13`, `direction="cw"`, `offset=0`, `control_word=0x0000`).
  Responsabilidade única: ler/validar config. Depende só de PyYAML/stdlib.
- **`encoder.py`** — função pura `decode(data: bytes, cfg) -> EncoderReading`.
  Converte 2 bytes big-endian em `raw` (0–8191), aplica sentido e offset, calcula
  `angle_deg = raw / 2**bits * 360`. Sem efeitos colaterais → testável isolado.
- **`master.py`** — `Amg11Master`: usa `PbConf.fromFile()` para montar o `DPM1`
  e o `DpSlaveDesc` (addr 3, GSD), chama `initialize()`, registra o escravo e
  roda o loop. A cada ciclo escreve a palavra de controle (`setMasterOutData`,
  2 B) e lê a posição (`getMasterInData`, 2 B). Expõe `read_once()` e
  `run(callback, hz)`. Encapsula a máquina de estados DP do pyprofibus.
- **`run.py`** — CLI fina: parseia args, instancia `Amg11Master`, imprime leituras.

### Fluxo de dados

```
encoder (addr 3) --RS485--> USB-RS485 --/dev/ttyUSB0--> pyprofibus PHY serial
   -> DPM1 Data_Exchange (cíclico) -> 2 bytes -> encoder.decode() -> EncoderReading
   -> callback (print/log)
```

### Módulo: Classe 2 (`0xF0`) — exigido pela lib

**Restrição descoberta na implementação:** `DpMaster.addSlave()` do pyprofibus
rejeita `input_size <= 0` (`"input_size=0 is currently not supported"`), e o ciclo
de `Data_Exchange` só dispara enviando dados mestre→escravo. Logo o módulo
**Classe 1 (`0xD0`, só leitura, sem saída) não é utilizável** com o pyprofibus.
Usamos o módulo **Classe 2 (`0xF0`)**.

Mapeamento na lib (perspectiva do escravo, invertida em relação ao mestre):

| pyprofibus | Direção | Conteúdo | Tamanho |
|---|---|---|---|
| `output_size` | escravo→mestre (mestre **lê**, `getMasterInData`) | **posição** 16-bit | 2 B |
| `input_size`  | mestre→escravo (mestre **escreve**, `setMasterOutData`) | **palavra de controle** | 2 B |

O `User_Prm_Data` (18 B do GSD: `00 0A …`) já vem com Class 2 functionality e
scaling habilitados, casando com o módulo `0xF0`. O `GsdInterp` casa o nome do
módulo por fuzzy match, então `module_0 = "16 Bit Class 2 Encoder"` resolve.

**Caveat da palavra de controle:** o mestre precisa enviar 2 B de saída a cada
ciclo só para sustentar o `Data_Exchange`. O default é `control_word = 0x0000`
(convenção de "sem comando"). A semântica exata desses 2 bytes no perfil do
encoder Baumer (preset/scaling) **deve ser confirmada no manual** antes do uso em
campo — há tarefa dedicada no plano para validar que a posição acompanha o eixo e
não fica travada em zero.

## 5. Modo de simulação (dev sem hardware)

`run.py --sim` usa o **PHY dummy** (`CpPhyDummySlave`) do pyprofibus para rodar todo
o loop do mestre nesta bancada x86 (sem RS485). Permite validar parsing do GSD,
máquina de estados DP, decodificação e CLI antes de tocar no Pi5. O dummy responde
ao `Data_Exchange` ecoando os bytes de saída do mestre **XOR 0xFF** (truncado/pad
para `output_size`), então a posição simulada = `control_word XOR 0xFFFF`. O teste
de integração injeta um valor conhecido por esse mecanismo e confere a leitura
ponta-a-ponta.

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
- **Palavra de controle (mestre→escravo):** pyprofibus obriga `input_size>=1`, então
  enviamos 2 B por ciclo (default `0x0000`). Confirmar no manual Baumer que esse valor
  não dispara preset/scaling indevido — validação em campo no plano (posição deve
  acompanhar o eixo, não travar em zero).

## 10. Fora de escopo (YAGNI)

- Dashboard web / MQTT / CSV (escopo é CLI + biblioteca).
- Multivoltas (modelo é singleturn 13-bit).
- Múltiplos escravos no barramento (1 encoder).
- DPV1 (acesso acíclico) — o GSD é DPV0.

## 11. Atualização 2026-06-16 — mudança de escopo (Pi 3 + UART de GPIO)

Após a implementação, o hardware-alvo mudou. As decisões de software (caminho A,
GSD, módulo Classe 2, decode 13-bit, modo sim) **permanecem**; muda só a camada
física e a placa:

- **Placa: Pi 5 → Raspberry Pi 3.** No Pi3 a UART de GPIO padrão é a *mini-UART*
  (`ttyS0`), com baud instável (atrelado ao clock do core). Solução no
  `scripts/setup_pi3.sh`: `dtoverlay=disable-bt` + `enable_uart=1` + remover o
  console serial → a **PL011** (`ttyAMA0`) estável passa a responder por
  `/dev/serial0`.
- **PHY: USB-RS485 → módulo RS485↔TTL na UART de GPIO.** `config/amg11.conf`:
  `dev = /dev/serial0`. Some o setup de FTDI/`latency_timer`/udev (era específico de
  USB); entram a config da UART e os dois alertas de hardware abaixo.
- **Alerta de nível 3,3 V:** o GPIO do Pi não é tolerante a 5 V; um MAX485 (5 V)
  pode danificar o RXD. Usar transceiver **3,3 V** (MAX3485/SP3485) ou level shifter
  na linha `RO→RXD`.
- **Direção meio-duplex:** a via `.conf` do pyprofibus não controla `DE/RE` por RTS
  (instancia `CpPhySerial` sem `useRS485Class`). Exige **módulo auto-direção**; um
  MAX485 comum só com 4 fios transmite e nunca recebe. Caminho RS485-mode (RTS +
  `useRS485Class`) fica como opção futura, dependente de suporte no driver da UART.

Os arquivos `scripts/setup_pi5.sh` e `scripts/99-rs485.rules` (USB/FTDI) foram
substituídos por `scripts/setup_pi3.sh`. Os testes não dependem de `dev`, então a
suíte (23) segue verde.
