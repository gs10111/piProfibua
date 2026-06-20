"""Armazenamento de arquivos GSD com validação e segurança de caminho."""
from __future__ import annotations

import re
from pathlib import Path

from profibus_amg11.gsd_info import GsdInfoError, parse_gsd

_SAFE = re.compile(r"^[A-Za-z0-9._-]+\.gsd$", re.IGNORECASE)


class GsdStore:
    def __init__(self, directory):
        self._dir = Path(directory)

    def _safe(self, name):
        if "/" in name or "\\" in name or ".." in name or not _SAFE.match(name):
            raise GsdInfoError("nome de GSD inseguro: %r" % name)
        return name

    def list(self):
        if not self._dir.exists():
            return []
        return sorted(p.name for p in self._dir.iterdir()
                      if p.is_file() and p.suffix.lower() == ".gsd")

    def save(self, filename, data):
        name = self._safe(filename)
        summary = parse_gsd(data, name)        # valida; levanta GsdInfoError
        path = self._dir / name
        if path.exists():
            # Não sobrescreve em silêncio (protege fixtures e evita troca furtiva).
            raise FileExistsError(name)
        self._dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes(data))
        return summary

    def read(self, name):
        path = self._dir / self._safe(name)
        if not path.exists():
            raise FileNotFoundError(name)
        return path.read_bytes()

    def summary(self, name):
        return parse_gsd(self.read(name), self._safe(name))
