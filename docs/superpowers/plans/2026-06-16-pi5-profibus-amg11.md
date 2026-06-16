# Mestre PROFIBUS-DP para encoder Baumer AMG 11 — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer um Raspberry Pi 5 ser mestre PROFIBUS-DP (DPM1) e ler a posição do encoder absoluto Baumer AMG 11 P 13 via USB-RS485 com a biblioteca pyprofibus, entregando CLI + biblioteca, com modo de simulação para dev sem hardware.

**Architecture:** Caminho A — um arquivo `.conf` do pyprofibus aponta para o GSD da Baumer (`PB13DPV0.gsd`); o `GsdInterp` gera os telegramas Set_Prm/Chk_Cfg. Uma camada fina em Python (`profibus_amg11/`) decodifica os 2 bytes de posição, gerencia o loop cíclico de `Data_Exchange` e expõe CLI. Módulo **Classe 2 (`0xF0`)** é obrigatório porque o pyprofibus rejeita `input_size=0`: o mestre escreve 2 B de palavra de controle (`setMasterOutData`) e lê 2 B de posição (`getMasterInData`).

**Tech Stack:** Python 3.12, pyprofibus, pyserial, PyYAML, pytest.

**Referência de design:** `docs/superpowers/specs/2026-06-16-pi5-profibus-amg11-design.md`

---

## Notas de ambiente (ler antes de começar)

- O repositório do projeto já existe em `~/repos/pi5-profibus-amg11/` com git inicializado e uma venv em `.venv/` (pyprofibus + pyserial já instalados).
- **Ative a venv** antes de qualquer comando Python/pytest:
  ```bash
  cd ~/repos/pi5-profibus-amg11 && . .venv/bin/activate
  ```
- O GSD original está em `~/repos/PB13DPV0.gsd` (será copiado para `gsd/` na Task 1).
- Esta máquina de dev é x86_64 sem RS485 → tudo é validado no **modo sim** (PHY dummy). O hardware real só existe no Pi5.
- Fatos do GSD usados no plano: `Ident_Number=0x059B`; módulo Classe 2 = `"16 Bit Class 2 Encoder "` config `0xF0`; resolução 13 bit (8192 passos/volta), singleturn.

---

## Task 1: Esqueleto do projeto

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `profibus_amg11/__init__.py`
- Create: `gsd/PB13DPV0.gsd` (cópia de `~/repos/PB13DPV0.gsd`)

- [ ] **Step 1: Criar `requirements.txt`**

```
pyprofibus
pyserial>=3.5
PyYAML>=6.0
```

- [ ] **Step 2: Criar `requirements-dev.txt`**

```
-r requirements.txt
pytest>=7.0
```

- [ ] **Step 3: Criar `pyproject.toml`** (deixa o pacote flat importável pelo pytest)

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 4: Criar `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 5: Criar o pacote `profibus_amg11/__init__.py`**

```python
"""Mestre PROFIBUS-DP para o encoder absoluto Baumer AMG 11 P 13."""

__version__ = "0.1.0"
```

- [ ] **Step 6: Copiar o GSD para dentro do projeto**

Run:
```bash
mkdir -p gsd && cp ~/repos/PB13DPV0.gsd gsd/PB13DPV0.gsd && ls -l gsd/
```
Expected: `gsd/PB13DPV0.gsd` listado (~5 KB).

- [ ] **Step 7: Garantir o pytest na venv**

Run:
```bash
. .venv/bin/activate && pip install -q -r requirements-dev.txt && pytest --version
```
Expected: imprime a versão do pytest sem erro.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt requirements-dev.txt pyproject.toml .gitignore profibus_amg11/__init__.py gsd/PB13DPV0.gsd
git commit -m "chore: esqueleto do projeto + GSD Baumer + deps"
```

---

## Task 2: Decodificação do encoder (`encoder.py`)

Função pura, sem dependências de hardware. É o coração testável.

**Files:**
- Create: `profibus_amg11/encoder.py`
- Test: `tests/test_encoder.py`

- [ ] **Step 1: Escrever o teste que falha**

`tests/test_encoder.py`:
```python
import pytest

from profibus_amg11.encoder import decode, EncoderReading
from profibus_amg11.config import EncoderConfig


def cfg(**kw):
    base = dict(resolution_bits=13, direction="cw", offset=0, control_word=0x0000)
    base.update(kw)
    return EncoderConfig(**base)


@pytest.mark.parametrize("raw16, expected_deg", [
    (0x0000, 0.0),
    (0x0800, 90.0),     # 2048 / 8192 * 360
    (0x1000, 180.0),    # 4096 / 8192 * 360
    (0x1800, 270.0),    # 6144 / 8192 * 360
])
def test_decode_cw_angles(raw16, expected_deg):
    data = raw16.to_bytes(2, "big")
    r = decode(data, cfg())
    assert isinstance(r, EncoderReading)
    assert r.raw == (raw16 & 0x1FFF)
    assert r.angle_deg == pytest.approx(expected_deg, abs=1e-6)


def test_decode_masks_to_13_bits():
    # bits acima do 13o (0xE000) devem ser ignorados
    r = decode((0xE800).to_bytes(2, "big"), cfg())
    assert r.raw == 0x0800
    assert r.angle_deg == pytest.approx(90.0)


def test_decode_ccw_mirrors_angle():
    r = decode((0x0800).to_bytes(2, "big"), cfg(direction="ccw"))
    assert r.raw == 0x1800           # 8192 - 2048
    assert r.angle_deg == pytest.approx(270.0)


def test_decode_offset_zeroes_reference():
    r = decode((0x0800).to_bytes(2, "big"), cfg(offset=0x0800))
    assert r.raw == 0
    assert r.angle_deg == pytest.approx(0.0)


def test_decode_offset_wraps():
    r = decode((0x0000).to_bytes(2, "big"), cfg(offset=0x0800))
    assert r.raw == 0x1800           # (0 - 2048) mod 8192
    assert r.angle_deg == pytest.approx(270.0)


def test_decode_rejects_wrong_length():
    with pytest.raises(ValueError):
        decode(b"\x00", cfg())
    with pytest.raises(ValueError):
        decode(b"\x00\x00\x00", cfg())
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `pytest tests/test_encoder.py -v`
Expected: FAIL com `ModuleNotFoundError`/`ImportError` em `profibus_amg11.encoder` (e em `config`, criada na Task 3 — ok, ainda falha aqui).

- [ ] **Step 3: Implementação mínima**

`profibus_amg11/encoder.py`:
```python
"""Decodificação dos bytes de posição do encoder AMG 11 (função pura)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EncoderReading:
    raw: int          # posição 0..(2**bits - 1), já com sentido e offset aplicados
    angle_deg: float  # 0.0 .. 360.0
    bytes_hex: str    # bytes crus recebidos, em hex (debug)


def decode(data, cfg) -> EncoderReading:
    """Converte 2 bytes big-endian (Unsigned16) numa EncoderReading.

    cfg: EncoderConfig com resolution_bits, direction ('cw'|'ccw') e offset.
    """
    if len(data) != 2:
        raise ValueError("esperados 2 bytes de posição, recebidos %d" % len(data))

    raw16 = (data[0] << 8) | data[1]            # Unsigned16 big-endian
    period = 1 << cfg.resolution_bits            # 8192 para 13 bit
    mask = period - 1
    raw = raw16 & mask                           # só os bits significativos

    if cfg.direction == "ccw":
        raw = (period - raw) & mask              # espelha o sentido

    raw = (raw - cfg.offset) & mask              # referência de zero por software

    angle = raw / period * 360.0
    return EncoderReading(raw=raw, angle_deg=angle, bytes_hex=bytes(data).hex())
```

- [ ] **Step 4: Rodar e confirmar (vai falhar só por falta de `config.py`)**

Run: `pytest tests/test_encoder.py -v`
Expected: ainda FAIL no import de `profibus_amg11.config` (criado na Task 3). Isso é esperado; o `encoder.py` em si está pronto. Prossiga para a Task 3 e volte a rodar.

- [ ] **Step 5: Commit**

```bash
git add profibus_amg11/encoder.py tests/test_encoder.py
git commit -m "feat: decode() de posicao 13-bit do encoder (TDD)"
```

---

## Task 3: Configuração do encoder (`config.py`)

**Files:**
- Create: `profibus_amg11/config.py`
- Create: `config/encoder.yaml`
- Test: `tests/test_config.py`

- [ ] **Step 1: Escrever o teste que falha**

`tests/test_config.py`:
```python
import pytest

from profibus_amg11.config import EncoderConfig, load_config


def test_defaults():
    c = EncoderConfig()
    assert c.resolution_bits == 13
    assert c.direction == "cw"
    assert c.offset == 0
    assert c.control_word == 0x0000


def test_rejects_bad_direction():
    with pytest.raises(ValueError):
        EncoderConfig(direction="up")


def test_rejects_offset_out_of_range():
    with pytest.raises(ValueError):
        EncoderConfig(resolution_bits=13, offset=8192)   # max valido = 8191


def test_rejects_bad_resolution():
    with pytest.raises(ValueError):
        EncoderConfig(resolution_bits=0)
    with pytest.raises(ValueError):
        EncoderConfig(resolution_bits=17)


def test_rejects_control_word_out_of_range():
    with pytest.raises(ValueError):
        EncoderConfig(control_word=0x10000)


def test_load_from_yaml(tmp_path):
    p = tmp_path / "enc.yaml"
    p.write_text(
        "resolution_bits: 13\n"
        "direction: ccw\n"
        "offset: 100\n"
        "control_word: 0x0000\n"
    )
    c = load_config(str(p))
    assert c.direction == "ccw"
    assert c.offset == 100
    assert c.control_word == 0


def test_load_empty_yaml_uses_defaults(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("")
    c = load_config(str(p))
    assert c == EncoderConfig()
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `pytest tests/test_config.py -v`
Expected: FAIL com `ImportError` em `profibus_amg11.config`.

- [ ] **Step 3: Implementação mínima**

`profibus_amg11/config.py`:
```python
"""Carregamento e validação do encoder.yaml."""

from __future__ import annotations

from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class EncoderConfig:
    resolution_bits: int = 13
    direction: str = "cw"          # "cw" | "ccw"
    offset: int = 0                # referencia de zero por software (0..2**bits-1)
    control_word: int = 0x0000     # palavra mestre->escravo enviada por ciclo

    def __post_init__(self):
        if not (1 <= self.resolution_bits <= 16):
            raise ValueError("resolution_bits deve estar entre 1 e 16")
        if self.direction not in ("cw", "ccw"):
            raise ValueError("direction deve ser 'cw' ou 'ccw'")
        mask = (1 << self.resolution_bits) - 1
        if not (0 <= self.offset <= mask):
            raise ValueError("offset deve estar entre 0 e %d" % mask)
        if not (0 <= self.control_word <= 0xFFFF):
            raise ValueError("control_word deve estar entre 0 e 0xFFFF")


def load_config(path) -> EncoderConfig:
    with open(path, "r", encoding="utf-8") as fd:
        data = yaml.safe_load(fd) or {}
    return EncoderConfig(**data)
```

- [ ] **Step 4: Criar `config/encoder.yaml`**

```yaml
# Encoder Baumer (Hubner) AMG 11 P 13 — parametros de decodificacao por software.
resolution_bits: 13      # singleturn: 8192 passos por volta (2^13)
direction: cw            # cw | ccw
offset: 0                # zero por software (0..8191), subtraido da posicao crua
control_word: 0x0000     # palavra mestre->escravo por ciclo (ver caveat no README)
```

- [ ] **Step 5: Rodar config + encoder juntos**

Run: `pytest tests/test_config.py tests/test_encoder.py -v`
Expected: PASS em todos (agora que `config.py` existe, os testes do encoder da Task 2 também passam).

- [ ] **Step 6: Commit**

```bash
git add profibus_amg11/config.py config/encoder.yaml tests/test_config.py
git commit -m "feat: EncoderConfig + encoder.yaml (TDD)"
```

---

## Task 4: Arquivo de configuração do mestre + carga do GSD

Valida que o `.conf` carrega no pyprofibus e produz o `DpSlaveDesc` correto (ident, tamanhos), com o módulo Classe 2.

**Files:**
- Create: `config/amg11.conf`
- Test: `tests/test_conf_load.py`

- [ ] **Step 1: Criar `config/amg11.conf`**

```ini
[PROFIBUS]
debug = 1

[PHY]
type = serial
dev = /dev/ttyUSB0
baud = 19200
rtscts = False
dsrdtr = False

[DP]
master_class = 1
master_addr = 1

[SLAVE_3]
name = AMG11
addr = 3
gsd = gsd/PB13DPV0.gsd
sync_mode = False
freeze_mode = False
group_mask = 1
watchdog_ms = 1000
input_size = 2
output_size = 2
diag_period = 0
module_0 = "16 Bit Class 2 Encoder"
```

> **Nota:** o caminho `gsd = gsd/PB13DPV0.gsd` é relativo à raiz do projeto. O pyprofibus resolve o GSD em relação ao diretório de trabalho atual; por isso o teste (e o `Amg11Master` na Task 5) faz `chdir` para a raiz do projeto antes de chamar `PbConf.fromFile`.

- [ ] **Step 2: Escrever o teste que falha**

`tests/test_conf_load.py`:
```python
import os
from pathlib import Path

import pytest

from pyprofibus import PbConf

ROOT = Path(__file__).resolve().parent.parent
CONF = ROOT / "config" / "amg11.conf"


@pytest.fixture
def in_project_root():
    old = os.getcwd()
    os.chdir(ROOT)
    try:
        yield
    finally:
        os.chdir(old)


def test_conf_loads_master_and_slave(in_project_root):
    conf = PbConf.fromFile(str(CONF))
    assert conf.dpMasterClass == 1
    assert conf.dpMasterAddr == 1
    assert conf.phyType == "serial"
    assert conf.phyBaud == 19200
    assert len(conf.slaveConfs) == 1

    slaveConf = conf.slaveConfs[0]
    assert slaveConf.addr == 3
    assert slaveConf.inputSize == 2
    assert slaveConf.outputSize == 2


def test_slave_desc_has_baumer_ident(in_project_root):
    conf = PbConf.fromFile(str(CONF))
    slaveDesc = conf.slaveConfs[0].makeDpSlaveDesc()
    assert slaveDesc.identNumber == 0x059B   # Baumer AMG/HMG/HEAG 13 bit
    assert slaveDesc.slaveAddr == 3


def test_class2_module_yields_cfg_elements(in_project_root):
    # O modulo Classe 2 (0xF0) deve produzir exatamente 1 elemento de config.
    conf = PbConf.fromFile(str(CONF))
    elems = conf.slaveConfs[0].gsd.getCfgDataElements()
    assert len(elems) == 1
    # DpCfgDataElement.identifier = primeiro byte de config do modulo (0xF0).
    assert elems[0].identifier == 0xF0
```

- [ ] **Step 3: Rodar e confirmar que falha**

Run: `pytest tests/test_conf_load.py -v`
Expected: FAIL — o arquivo `config/amg11.conf` ainda não existe / não casa. Se o módulo não casar, o erro será `Module '...' not found in GSD`.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `pytest tests/test_conf_load.py -v`
Expected: PASS nos 3 testes.

- [ ] **Step 5: Commit**

```bash
git add config/amg11.conf tests/test_conf_load.py
git commit -m "feat: amg11.conf + carga do GSD (modulo Classe 2, ident 0x059B)"
```

---

## Task 5: Mestre e loop cíclico (`master.py`)

Encapsula o pyprofibus: monta o DPM1, registra o escravo, roda `Data_Exchange` e decodifica. Testado no **modo sim** (PHY dummy), sem hardware.

**Files:**
- Create: `profibus_amg11/master.py`
- Test: `tests/test_master_sim.py`

- [ ] **Step 1: Escrever o teste que falha**

`tests/test_master_sim.py`:
```python
from pathlib import Path

import pytest

from profibus_amg11.config import EncoderConfig
from profibus_amg11.master import Amg11Master

ROOT = Path(__file__).resolve().parent.parent
CONF = str(ROOT / "config" / "amg11.conf")


def test_sim_reads_known_position():
    # O PHY dummy responde ao Data_Exchange com (control_word XOR 0xFFFF).
    # control_word=0xFFFF -> dummy devolve 0x0000 -> raw 0, angulo 0.
    cfg = EncoderConfig(control_word=0xFFFF)
    m = Amg11Master(CONF, cfg, sim=True)
    try:
        r = m.read_once(timeout=5.0)
    finally:
        m.close()
    assert r.raw == 0
    assert r.angle_deg == pytest.approx(0.0)


def test_sim_reads_other_position():
    # control_word=0xF000 -> dummy devolve 0x0FFF -> raw 0x0FFF (4095).
    cfg = EncoderConfig(control_word=0xF000)
    m = Amg11Master(CONF, cfg, sim=True)
    try:
        r = m.read_once(timeout=5.0)
    finally:
        m.close()
    assert r.raw == 0x0FFF
    assert r.angle_deg == pytest.approx(4095 / 8192 * 360.0)


def test_sim_run_callback_then_stop():
    cfg = EncoderConfig(control_word=0xFFFF)
    m = Amg11Master(CONF, cfg, sim=True)
    seen = []

    def cb(reading):
        seen.append(reading)
        if len(seen) >= 3:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        m.run(cb, hz=200.0)
    assert len(seen) >= 3
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `pytest tests/test_master_sim.py -v`
Expected: FAIL com `ImportError` em `profibus_amg11.master`.

- [ ] **Step 3: Implementação mínima**

`profibus_amg11/master.py`:
```python
"""Mestre PROFIBUS-DP (DPM1) para o encoder AMG 11, sobre pyprofibus."""

from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path

from pyprofibus import PbConf

from profibus_amg11.encoder import decode


@contextlib.contextmanager
def _chdir(path):
    old = os.getcwd()
    os.chdir(str(path))
    try:
        yield
    finally:
        os.chdir(old)


class Amg11Master:
    """Mestre de 1 escravo (o encoder) com loop de Data_Exchange.

    conf_path: caminho do .conf do pyprofibus (em config/, com gsd relativo a raiz).
    encoder_cfg: EncoderConfig (resolucao, sentido, offset, control_word).
    sim: se True, usa o PHY dummy (sem RS485) para rodar sem hardware.
    """

    def __init__(self, conf_path, encoder_cfg, sim=False):
        self.encoder_cfg = encoder_cfg
        self._out = bytearray(encoder_cfg.control_word.to_bytes(2, "big"))

        conf_path = Path(conf_path).resolve()
        project_root = conf_path.parent.parent  # config/ -> raiz
        with _chdir(project_root):
            conf = PbConf.fromFile(str(conf_path))
            if sim:
                conf.phyType = "dummyslave"
            self.master = conf.makeDPM()

        self.slave = conf.slaveConfs[0].makeDpSlaveDesc()
        self.master.addSlave(self.slave)
        self.master.initialize()

    def poll(self):
        """Roda um passo da maquina de estados. Retorna EncoderReading ou None."""
        # Re-arma a palavra de saida a cada ciclo para sustentar o Data_Exchange.
        self.slave.setMasterOutData(bytearray(self._out))
        handled = self.master.run()
        if handled is self.slave:
            data = self.slave.getMasterInData()
            if data is not None:
                return decode(bytes(data), self.encoder_cfg)
        return None

    def read_once(self, timeout=5.0):
        """Bloqueia ate a primeira leitura valida ou estoura timeout (segundos)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            reading = self.poll()
            if reading is not None:
                return reading
        raise TimeoutError("sem leitura do escravo em %.1fs" % timeout)

    def run(self, callback, hz=20.0):
        """Loop continuo: chama callback(EncoderReading) a cada leitura valida."""
        period = 1.0 / hz
        while True:
            start = time.monotonic()
            reading = self.poll()
            if reading is not None:
                callback(reading)
            slack = period - (time.monotonic() - start)
            if slack > 0:
                time.sleep(slack)

    def close(self):
        with contextlib.suppress(Exception):
            self.master.destroy()
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `pytest tests/test_master_sim.py -v`
Expected: PASS nos 3 testes. (Se `read_once` der timeout, rode com `-s` e o debug do pyprofibus para ver a maquina de estados; o dummy deve alcancar `Data_Exchange`.)

- [ ] **Step 5: Rodar a suíte inteira**

Run: `pytest -v`
Expected: PASS em todos os testes (encoder, config, conf_load, master_sim).

- [ ] **Step 6: Commit**

```bash
git add profibus_amg11/master.py tests/test_master_sim.py
git commit -m "feat: Amg11Master com loop ciclico DP, testado em modo sim (TDD)"
```

---

## Task 6: CLI (`run.py`)

**Files:**
- Create: `run.py`
- Test: `tests/test_cli_sim.py`

- [ ] **Step 1: Escrever o teste que falha** (executa a CLI como subprocesso, em sim)

`tests/test_cli_sim.py`:
```python
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_cli_once_sim_prints_reading():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "run.py"), "--sim", "--once"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout + proc.stderr
    assert "angle" in out.lower()
    assert "raw" in out.lower()
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `pytest tests/test_cli_sim.py -v`
Expected: FAIL — `run.py` ainda não existe (returncode != 0).

- [ ] **Step 3: Implementação mínima**

`run.py`:
```python
#!/usr/bin/env python3
"""CLI do mestre PROFIBUS-DP para o encoder Baumer AMG 11."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from profibus_amg11.config import load_config
from profibus_amg11.master import Amg11Master

ROOT = Path(__file__).resolve().parent


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--conf", default=str(ROOT / "config" / "amg11.conf"),
                   help="arquivo .conf do pyprofibus")
    p.add_argument("--encoder", default=str(ROOT / "config" / "encoder.yaml"),
                   help="arquivo encoder.yaml")
    p.add_argument("--sim", action="store_true",
                   help="usa o PHY dummy (sem hardware RS485)")
    p.add_argument("--once", action="store_true",
                   help="le uma vez e sai")
    p.add_argument("--hz", type=float, default=20.0,
                   help="taxa de leitura no modo continuo")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="loga o debug do pyprofibus")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("amg11")

    cfg = load_config(args.encoder)
    master = Amg11Master(args.conf, cfg, sim=args.sim)

    if args.once:
        try:
            r = master.read_once()
        finally:
            master.close()
        log.info("raw=%d  angle=%.3f deg  bytes=%s", r.raw, r.angle_deg, r.bytes_hex)
        return 0

    def on_reading(r):
        log.info("raw=%5d  angle=%7.3f deg", r.raw, r.angle_deg)

    try:
        master.run(on_reading, hz=args.hz)
    except KeyboardInterrupt:
        log.info("encerrando")
    finally:
        master.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `pytest tests/test_cli_sim.py -v`
Expected: PASS. Verifique manualmente também:
```bash
. .venv/bin/activate && python run.py --sim --once
```
Expected: uma linha de log com `raw=...  angle=... deg`.

- [ ] **Step 5: Commit**

```bash
git add run.py tests/test_cli_sim.py
git commit -m "feat: CLI run.py (--sim/--once/--hz) com teste de subprocesso"
```

---

## Task 7: Scripts de setup do Pi5

Sem testes unitários (mexem em udev/sysfs do Pi). Validação é por revisão e execução manual no Pi5.

**Files:**
- Create: `scripts/99-rs485.rules`
- Create: `scripts/setup_pi5.sh`

- [ ] **Step 1: Criar a regra udev `scripts/99-rs485.rules`**

```
# Conversor USB-RS485 -> nome estavel /dev/profibus0 e latencia minima (PROFIBUS).
# FTDI (idVendor 0403). Para CH340, troque por ATTRS{idVendor}=="1a86".
SUBSYSTEM=="tty", ACTION=="add", ATTRS{idVendor}=="0403", SYMLINK+="profibus0"
# Reduz o buffer de latencia do chip FTDI para 1 ms (critico p/ timing DP).
ACTION=="add", SUBSYSTEM=="usb-serial", DRIVERS=="ftdi_sio", ATTR{latency_timer}="1"
```

- [ ] **Step 2: Criar `scripts/setup_pi5.sh`**

```bash
#!/usr/bin/env bash
# Prepara o Raspberry Pi 5 para rodar o mestre PROFIBUS via USB-RS485.
set -euo pipefail

DEV="${1:-/dev/ttyUSB0}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "[1/3] Adicionando $USER ao grupo dialout..."
sudo usermod -aG dialout "$USER"

echo "[2/3] Fixando latency_timer=1 para $DEV (se presente agora)..."
BASEDEV="$(basename "$DEV")"
LAT="/sys/bus/usb-serial/devices/${BASEDEV}/latency_timer"
if [ -e "$LAT" ]; then
    echo 1 | sudo tee "$LAT" >/dev/null
    echo "    latency_timer=$(cat "$LAT")"
else
    echo "    $DEV ausente agora; a regra udev aplica ao conectar."
fi

echo "[3/3] Instalando regra udev..."
sudo cp "$HERE/99-rs485.rules" /etc/udev/rules.d/99-rs485.rules
sudo udevadm control --reload-rules
sudo udevadm trigger

echo "OK. Faca logout/login para o grupo dialout ter efeito."
```

- [ ] **Step 3: Tornar executável e checar sintaxe**

Run:
```bash
chmod +x scripts/setup_pi5.sh && bash -n scripts/setup_pi5.sh && echo "sintaxe ok"
```
Expected: imprime `sintaxe ok` (sem erros de parse).

- [ ] **Step 4: Commit**

```bash
git add scripts/setup_pi5.sh scripts/99-rs485.rules
git commit -m "chore: scripts de setup do Pi5 (dialout, latency_timer, udev)"
```

---

## Task 8: README + checklist de validação em campo

**Files:**
- Create: `README.md`

- [ ] **Step 1: Criar `README.md`**

````markdown
# pi5-profibus-amg11

Raspberry Pi 5 como **mestre PROFIBUS-DP (DPM1)** lendo a posição de um encoder
absoluto **Baumer (Hübner) AMG 11 P 13 Z0** via conversor USB-RS485, com a
biblioteca **pyprofibus**. Entrega CLI + biblioteca, com modo de simulação.

## Arquitetura

- `.conf` do pyprofibus (`config/amg11.conf`) → aponta para o GSD `gsd/PB13DPV0.gsd`.
- Módulo **Classe 2 (`0xF0`)**: o mestre escreve 2 B (palavra de controle) e lê 2 B
  (posição 16-bit, 13 bits significativos = 8192 passos/volta, singleturn).
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
# faca logout/login (grupo dialout)
```

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

## Baud rate

Começa em **19200** (`config/amg11.conf`). O encoder faz auto-baud (9.6k–12M).
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
````

- [ ] **Step 2: Conferir a suíte completa antes de fechar**

Run: `pytest -v`
Expected: todos os testes PASS.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README (fiacao, deploy, uso, caveat e checklist de campo)"
```

---

## Resumo das verificações finais

- [ ] `pytest -v` → tudo verde (encoder, config, conf_load, master_sim, cli_sim).
- [ ] `python run.py --sim --once` → imprime uma leitura decodificada.
- [ ] Spec coberto: PHY serial auto-direção ✓ (Task 4 conf), GSD/ident 0x059B ✓
  (Task 4), módulo Classe 2 ✓ (Task 4/5), decode 13-bit ✓ (Task 2), sim ✓
  (Task 5), CLI ✓ (Task 6), setup Pi5 ✓ (Task 7), caveat control_word + checklist
  de campo ✓ (Task 8).
- [ ] **Validação real no Pi5** fica pendente de hardware — seguir o checklist do README.
