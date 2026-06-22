"""Inspeção de GSD e preview de parametrização (wrap de GsdInterp, puro)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from pyprofibus.dp import DpCfgDataElement
from pyprofibus.gsd.interp import GsdInterp
from pyprofibus.gsd.parser import GsdError

BAUDS = (9600, 19200, 45450, 93750, 187500, 500000, 1500000)


class GsdInfoError(Exception):
    pass


def decode_cfg_io(cfg_bytes) -> Tuple[int, int]:
    """Decodifica os bytes de Chk_Cfg -> (read, write) em bytes, na ótica do mestre.

    read  = bytes que o mestre LÊ do escravo (Eingang/DP-input; ex.: posição).
    write = bytes que o mestre ESCREVE no escravo (Ausgang/DP-output; ex.: preset).
    O byte identificador segue o formato geral do PROFIBUS-DP: bits de direção
    (in/out), word(2B)/byte e nibble baixo = nº de unidades - 1.
    """
    E = DpCfgDataElement
    data = bytes(cfg_bytes)
    read = write = 0
    i = 0
    while i < len(data):
        iden = data[i]
        if (iden & E.ID_TYPE_MASK) == E.ID_TYPE_SPEC:
            # formato especial: nibble baixo = nº de length bytes que seguem.
            nbytes = iden & E.ID_LEN_MASK
            spec = iden & E.ID_SPEC_MASK
            length = data[i + 1:i + 1 + nbytes]
            i += 1 + nbytes
            order = []  # (direção, byte de length); INOUT vem saída e depois entrada
            if spec == E.ID_SPEC_OUT:
                order = [("write", length[0:1])]
            elif spec == E.ID_SPEC_IN:
                order = [("read", length[0:1])]
            elif spec == E.ID_SPEC_INOUT:
                order = [("write", length[0:1]), ("read", length[1:2])]
            for kind, lb in order:
                if not lb:
                    continue
                size = (lb[0] & E.LEN_COUNT) * (2 if lb[0] & E.LEN_WORDS else 1)
                if kind == "read":
                    read += size
                else:
                    write += size
        else:
            size = ((iden & E.ID_LEN_MASK) + 1) * (2 if iden & E.ID_LEN_WORDS else 1)
            if iden & E.ID_TYPE_IN:
                read += size
            if iden & E.ID_TYPE_OUT:
                write += size
            i += 1
    return read, write


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
    in_size: int   # bytes que o mestre LÊ (posição)
    out_size: int  # bytes que o mestre ESCREVE (preset)


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
    in_size, out_size = decode_cfg_io(cfg)
    return ParamPreview(ident=ident, modules=tuple(chosen),
                        cfg_hex=bytes(cfg).hex(), user_prm_hex=bytes(prm).hex(),
                        in_size=in_size, out_size=out_size)


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
        "in_size": p.in_size, "out_size": p.out_size,
    }
