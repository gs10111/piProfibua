# profibus-amg11 — mestre PROFIBUS-DP no Raspberry Pi 3

Raspberry Pi 3 como **mestre PROFIBUS-DP (DPM1)** lendo a posição de um encoder
absoluto **Baumer (Hübner) AMG 11 P 13 Z0**, com a biblioteca **pyprofibus**.
A camada física é um **módulo conversor RS485↔TTL ligado direto na UART de GPIO**
do Pi (TX/RX/VCC/GND). Entrega CLI + biblioteca, com modo de simulação.

> A pasta ainda se chama `pi5-profibus-amg11` por legado; o alvo agora é o **Pi 3**.

## Arquitetura

- `.conf` do pyprofibus (`config/amg11.conf`) → aponta para o GSD `gsd/PB13DPV0.gsd`.
  PHY serial em **`/dev/serial0`** (UART de hardware do Pi).
- Módulo **Classe 2 (`0xF0`)**: o mestre escreve 2 B (palavra de controle) e lê 2 B
  (posição 16-bit, 13 bits significativos = 8192 passos/volta, singleturn).
- `config/encoder.yaml`: parâmetros de decodificação (resolução, sentido, offset, control_word).
- `profibus_amg11/`: `encoder.py` (decode puro), `config.py`, `master.py` (loop DP).
- `run.py`: CLI.

## Fiação (Pi 3 ↔ módulo RS485-TTL ↔ encoder)

Lado TTL (Pi GPIO ↔ módulo). Os nomes dos pinos do módulo variam; ligue por função:

| Pi 3 (pino físico) | Módulo RS485-TTL |
|---|---|
| TXD0 = GPIO14 (pino 8) | entrada de dados → `DI` (ou `RXD`) |
| RXD0 = GPIO15 (pino 10) | saída de dados → `RO` (ou `TXD`) |
| **3V3** (pino 1) | `VCC` — ver alerta de nível abaixo |
| GND (pino 6/9/…) | `GND` |

Lado RS485 (módulo ↔ encoder):

| Módulo RS485 | Encoder AMG 11 |
|---|---|
| `A` / `D+` | PROFIBUS A (verde) |
| `B` / `D-` | PROFIBUS B (vermelho) |
| `GND` | GND / blindagem |

- Endereço do escravo = **3**, nas **chaves físicas** do encoder
  (GSD: `Set_Slave_Add_supp=0` → não dá para setar pelo barramento).
- **Terminação PROFIBUS** (390/220/390 Ω) nas duas pontas do barramento.

### ⚠️ Alerta 1 — nível lógico 3,3 V (pode queimar o Pi)

O MAX485 "clássico" é peça de **5 V**: a saída `RO` (que vai para o **RXD do Pi**)
chega a ~5 V, e o **GPIO do Pi não é tolerante a 5 V**. Isso pode **danificar o Pi**.
Use uma das opções:
- um transceiver **3,3 V** (MAX3485 / SP3485 / módulo "auto" 3V3) alimentado em **3V3**; ou
- um conversor de nível na linha `RO → RXD` (ou um divisor resistivo só nessa linha).

Alimentar um MAX485 em 3V3 **não** resolve (ele precisa de ≥4,75 V para operar).

### ⚠️ Alerta 2 — direção TX/RX (meio-duplex)

PROFIBUS é half-duplex: o mestre **transmite e depois solta o barramento** para
**receber** a resposta do encoder. Pela via do `.conf`, o pyprofibus **não** controla
direção por RTS — ele assume um módulo de **auto-direção**.

- **Módulo auto-direção (4 fios TX/RX/VCC/GND, sem `DE`/`RE`):** funciona direto. ✅
- **MAX485 comum (tem pinos `DE` e `RE`):** com só TX/RX/VCC/GND ligados, ele fica
  **preso transmitindo e nunca recebe** → você vê timeout/sem leitura. Conserte com
  um módulo auto-direção (recomendado) ou peça que eu habilite o caminho
  experimental de RS485-mode (RTS em GPIO + `useRS485Class`), que depende de suporte
  no driver da UART do Pi.

Como saber qual você tem: se o módulo tem pinos **`DE`/`RE`**, é MAX485 comum.

## Setup no Pi 3

```bash
cd ~/repos/pi5-profibus-amg11
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
./scripts/setup_pi3.sh        # dialout + enable_uart + disable-bt + tira console serial
sudo reboot                   # necessario para liberar a PL011 nos GPIO
```

> O `setup_pi3.sh` desativa o Bluetooth para mapear a **PL011** (estável) nos
> GPIO 14/15, porque a *mini-UART* do Pi3 tem baud instável. Depois do reboot a
> porta é **`/dev/serial0` → `ttyAMA0`**. Confira: `ls -l /dev/serial0`.

## Uso

```bash
# Sem hardware (PHY dummy), valida o pipeline:
python run.py --sim --once

# Com o encoder real:
python run.py --once             # uma leitura
python run.py --hz 50            # leitura continua a 50 Hz
python run.py -v                 # com o trace do pyprofibus (diagnostico DP)
```

Edite `config/encoder.yaml` (sentido, zero por software) e `config/amg11.conf`
(`dev`/`baud`/`addr`). O `encoder.yaml` controla o pós-processamento por software;
o `amg11.conf` controla o enlace PROFIBUS.

## Baud rate

Começa em **19200** (chave `baud` em `config/amg11.conf`). O encoder faz auto-baud
(9.6k–12M). Suba gradualmente se o barramento estiver estável. Na UART de GPIO do
Pi3, prefira a **PL011** (via `disable-bt`); em Linux não-RT, baud moderado é o que
garante o timing.

## ⚠️ Caveat: palavra de controle (mestre→escravo)

O pyprofibus exige `input_size>=1`, então o mestre envia **2 B por ciclo**
(`control_word`, default `0x0000`) só para sustentar o `Data_Exchange`. A semântica
desses 2 bytes no perfil do encoder Baumer (preset/scaling) **não está confirmada
neste projeto**. Siga o checklist abaixo na primeira ligação real.

## Checklist de validação em campo (Pi 3 + encoder real)

1. [ ] Transceiver de **3,3 V** (ou level shifter na linha RO→RXD); módulo de
   **auto-direção** (sem `DE`/`RE`). Senão, ver os dois alertas de fiação acima.
2. [ ] `/dev/serial0` existe e aponta para `ttyAMA0` (`ls -l /dev/serial0`, pós-reboot).
3. [ ] Encoder no endereço 3 (chaves físicas), terminação nas pontas, A/B corretos.
4. [ ] `python run.py --once -v` conecta sem erro de diagnóstico
   (sem "faulty parameterization/configuration" no log).
5. [ ] Gire o eixo manualmente e rode `python run.py --hz 20`: o `angle` deve
   **acompanhar** o eixo e **não ficar travado em zero**.
6. [ ] Posição presa/travada em zero: ou a `control_word` dispara preset/scaling
   (cheque o manual Baumer e ajuste em `config/encoder.yaml`), ou o módulo é MAX485
   sem controle de direção (não recebe — troque por auto-direção).
7. [ ] Sentido errado: troque `direction` para `ccw` em `config/encoder.yaml`.
8. [ ] Zero: gire para a referência e ajuste `offset` (use o `raw` lido como offset).

## Testes

```bash
. .venv/bin/activate
pytest -v
```

## Limitações

- pyprofibus é mestre em Python puro; em Linux não-RT a confiabilidade depende de
  baud moderado e de uma UART estável (PL011, não a mini-UART). Para 12 Mbit/s,
  considere uma PHY dedicada (FPGA).
- A via `.conf` assume transceiver **auto-direção** (sem controle DE/RE por RTS).
- Singleturn 13-bit (sem multivoltas). Um escravo. DPV0 (sem acesso acíclico).
