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
