"""Inspeção de GSD e preview de parametrização (wrap de GsdInterp, puro)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from pyprofibus.gsd.interp import GsdInterp
from pyprofibus.gsd.parser import GsdError

BAUDS = (9600, 19200, 45450, 93750, 187500, 500000, 1500000)


class GsdInfoError(Exception):
    pass


@dataclass(frozen=True)
class ModuleInfo:
    name: str
    config_hex: str
    preset: bool


@dataclass(frozen=True)
class GsdSummary:
    filename: str
    vendor: str
    model: str
    revision: str
    ident: Optional[int]
    order: str
    modular: bool
    dpv1: bool
    modules: Tuple[ModuleInfo, ...]
    max_tsdr: dict


@dataclass(frozen=True)
class ParamPreview:
    ident: Optional[int]
    modules: Tuple[str, ...]
    cfg_hex: str
    user_prm_hex: str


def _interp(data, filename):
    try:
        return GsdInterp.fromBytes(bytes(data), filename=filename)
    except GsdError as e:
        raise GsdInfoError(str(e))
    except Exception as e:
        raise GsdInfoError("GSD inválido: %s" % e)


def _module_config_hex(mod):
    cb = getattr(mod, "configBytes", b"") or b""
    return bytes(cb).hex()


def parse_gsd(data, filename) -> GsdSummary:
    g = _interp(data, filename)
    ident = g.getField("Ident_Number")
    if ident is None:
        # Todo GSD de escravo DP declara Ident_Number; sem ele não é um GSD válido.
        raise GsdInfoError("GSD sem Ident_Number (não parece um GSD válido)")
    mods = tuple(
        ModuleInfo(name=m.name, config_hex=_module_config_hex(m),
                   preset=bool(m.getField("Preset", False)))
        for m in g.getField("Module", [])
    )
    tsdr = {}
    for b in BAUDS:
        try:
            tsdr[b] = g.getMaxTSDR(b)
        except GsdError:
            tsdr[b] = None
    return GsdSummary(
        filename=filename,
        vendor=g.getField("Vendor_Name", "") or "",
        model=g.getField("Model_Name", "") or "",
        revision=str(g.getField("Revision", "") or ""),
        ident=ident,
        order=str(g.getField("OrderNumber", "") or ""),
        modular=bool(g.isModular()),
        dpv1=bool(g.isDPV1()),
        modules=mods,
        max_tsdr=tsdr,
    )


def preview_params(data, module_names) -> ParamPreview:
    g = _interp(data, "<preview>")
    chosen = list(module_names or [])
    if chosen:
        g.clearConfiguredModules()
        for name in chosen:
            try:
                g.setConfiguredModule(name)
            except GsdError as e:
                raise GsdInfoError(str(e))
    try:
        cfg = bytearray()
        for e in g.getCfgDataElements():
            cfg += bytes(e.getDU())
        prm = g.getUserPrmData()
        ident = g.getIdentNumber()
    except GsdError as e:
        raise GsdInfoError(str(e))
    return ParamPreview(ident=ident, modules=tuple(chosen),
                        cfg_hex=bytes(cfg).hex(), user_prm_hex=bytes(prm).hex())


def _ident_hex(ident):
    return ("0x%04X" % ident) if ident is not None else None


def module_to_dict(m):
    return {"name": m.name, "config_hex": m.config_hex, "preset": m.preset}


def summary_to_dict(s):
    return {
        "filename": s.filename, "vendor": s.vendor, "model": s.model,
        "revision": s.revision, "ident": s.ident, "ident_hex": _ident_hex(s.ident),
        "order": s.order, "modular": s.modular, "dpv1": s.dpv1,
        "modules": [module_to_dict(m) for m in s.modules],
        "max_tsdr": {str(k): v for k, v in s.max_tsdr.items()},
    }


def preview_to_dict(p):
    return {
        "ident": p.ident, "ident_hex": _ident_hex(p.ident),
        "modules": list(p.modules), "cfg_hex": p.cfg_hex,
        "user_prm_hex": p.user_prm_hex,
    }
