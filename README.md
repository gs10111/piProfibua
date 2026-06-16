# pi5-profibus-amg11

Raspberry Pi 5 como **mestre PROFIBUS-DP (DPM1)** lendo a posição de um encoder
absoluto **Baumer (Hübner) AMG 11 P 13 Z0** via conversor USB-RS485, com a
biblioteca **pyprofibus**. Entrega CLI + biblioteca, com modo de simulação.

## Arquitetura

- `.conf` do pyprofibus (`config/amg11.conf`) → aponta para o GSD `gsd/PB13DPV0.gsd`.
- Módulo **Classe 2 (`0xF0`)**: o mestre escreve 2 B (palavra de controle) e lê 2 B
  (posição 16-bit, 13 bits significativos = 8192 passos/volta, singleturn).
- `config/encoder.yaml`: parâmetros de decodificação (resolução, sentido, offset, control_word).
- `profibus_amg11/`: `encoder.py` (decode puro), `config.py`, `master.py` (loop DP).
- `run.py`: CLI.

## Fiação RS485

| Encoder AMG 11 | Conversor RS485 |
|---|---|
| PROFIBUS A (verde) | A / D+ |
| PROFIBUS B (vermelho) | B / D- |
| GND / blindagem | GND |

- Endereço do escravo = **3**, ajustado nas **chaves físicas** do encoder
  (o GSD declara `Set_Slave_Add_supp=0` → não há como setar pelo barramento).
- Use **terminação PROFIBUS** (390/220/390 Ω) nas duas pontas do barramento.
- O conversor deve ser de **auto-direção** (troca TX/RX em hardware).

## Instalação no Pi5

```bash
cd ~/repos/pi5-profibus-amg11
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
./scripts/setup_pi5.sh /dev/ttyUSB0   # dialout + latency_timer + udev
```

> **Nota:** após `setup_pi5.sh`, faça logout/login uma vez para o grupo `dialout` valer.

## Uso

```bash
# Sem hardware (PHY dummy), valida o pipeline:
python run.py --sim --once

# Com o encoder real:
python run.py --once             # uma leitura
python run.py --hz 50            # leitura continua a 50 Hz
python run.py -v                 # com debug do pyprofibus
```

Edite `config/encoder.yaml` para `direction`, `offset` (zero por software) e
`config/amg11.conf` para `dev`/`baud`/`addr`.
O `encoder.yaml` controla o pós-processamento por software (sentido, zero); o `amg11.conf` controla o enlace PROFIBUS (porta, baud, endereço).

## Baud rate

Começa em **19200** (chave `baud` em `config/amg11.conf`). O encoder faz auto-baud (9.6k–12M).
Suba gradualmente se o barramento estiver estável. Em Linux não-RT, baud moderado
+ `latency_timer=1` é o que garante o timing.

## ⚠️ Caveat: palavra de controle (mestre→escravo)

O pyprofibus exige `input_size>=1`, então o mestre envia **2 B por ciclo**
(`control_word`, default `0x0000`) só para sustentar o `Data_Exchange`. A semântica
desses 2 bytes no perfil do encoder Baumer (preset/scaling) **não está confirmada
neste projeto**. Siga o checklist abaixo na primeira ligação real.

## Checklist de validação em campo (Pi5 + encoder real)

1. [ ] Encoder no endereço 3 (chaves físicas), terminação nas pontas, A/B corretos.
2. [ ] `python run.py --once -v` conecta sem erro de diagnóstico
   (sem "faulty parameterization/configuration" no log).
3. [ ] Gire o eixo manualmente e rode `python run.py --hz 20`: o `angle` deve
   **acompanhar** o eixo e **não ficar travado em zero**.
4. [ ] Se a posição ficar presa/saltar para um valor fixo: a `control_word` pode
   estar disparando preset/scaling. Consulte o manual Baumer do perfil do encoder
   e ajuste `control_word` em `config/encoder.yaml`.
5. [ ] Confira o sentido: se aumentar o ângulo no sentido errado, troque
   `direction` em `config/encoder.yaml` para `ccw`.
6. [ ] Defina o zero: gire para a posição de referência e ajuste `offset` (ou
   leia o `raw` atual e use-o como `offset`).

## Testes

```bash
. .venv/bin/activate
pytest -v
```

## Limitações

- pyprofibus é mestre em Python puro; em Linux não-RT a confiabilidade depende de
  baud moderado + `latency_timer=1`. Para 12 Mbit/s, considere uma PHY FPGA.
- Singleturn 13-bit (sem multivoltas). Um escravo. DPV0 (sem acesso acíclico).
