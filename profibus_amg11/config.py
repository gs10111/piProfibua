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
