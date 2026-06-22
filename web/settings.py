"""Configurações de barramento (baud + endereço do mestre) com persistência."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# Conjunto padrão PROFIBUS oferecido na UI.
ALLOWED_BAUDS = (9600, 19200, 45450, 93750, 187500, 500000, 1500000)
# Bauds confiáveis no Pi não-RT via pyprofibus; o resto é best-effort.
RELIABLE_BAUDS = (9600, 19200)


@dataclass(frozen=True)
class BusSettings:
    baud: int = 19200
    master_addr: int = 1

    def __post_init__(self):
        if self.baud not in ALLOWED_BAUDS:
            raise ValueError("baud %r não permitido" % (self.baud,))
        if not (1 <= self.master_addr <= 126):
            raise ValueError("master_addr deve estar entre 1 e 126")


class SettingsStore:
    """Lê/grava BusSettings num JSON. Ausência ou valor inválido cai no default."""

    def __init__(self, path):
        self._path = Path(path)

    def load(self, defaults: BusSettings) -> BusSettings:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return BusSettings(baud=int(data["baud"]),
                               master_addr=int(data["master_addr"]))
        except (FileNotFoundError, ValueError, TypeError, KeyError):
            return defaults

    def save(self, settings: BusSettings) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"baud": settings.baud,
                        "master_addr": settings.master_addr}),
            encoding="utf-8")
