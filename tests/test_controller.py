from profibus_amg11.scan import Station, StationType
from web.controller import BusController
from web.settings import BusSettings
from web.snapshot import IoSnapshot, Snapshot


def _snap(offset=0, connected=True):
    return Snapshot(angle_deg=0.0, raw=0, raw_max=8191, bytes_hex="",
                    offset=offset, connected=connected, rate_hz=0.0,
                    diag="OK", ts=0.0)


class FakeEngine:
    def __init__(self, offset=0):
        self._offset = offset
        self.zeroed = 0
        self.cleared = 0
        self.stopped = False

    def step(self):
        return _snap(offset=self._offset)

    def snapshot(self):
        return _snap(offset=self._offset)

    def zero(self):
        self.zeroed += 1

    def clear_zero(self):
        self.cleared += 1

    def stop(self):
        self.stopped = True


class FakeProbe:
    def __init__(self, hits):
        self._hits = hits
        self.closed = False

    def probe(self, addr):
        return self._hits.get(addr)

    def close(self):
        self.closed = True


def make_ctrl(**kw):
    made = {"exchange": [], "probe": []}

    def make_exchange(settings, offset):
        e = FakeEngine(offset=offset)
        made["exchange"].append((settings, offset, e))
        return e

    def make_probe(settings):
        p = kw.get("probe") or FakeProbe({})
        made["probe"].append((settings, p))
        return p

    saved = []
    ctrl = BusController(make_exchange, make_probe,
                         kw.get("settings", BusSettings(baud=19200, master_addr=1)),
                         addresses=kw.get("addresses", [1, 2, 3]),
                         on_settings_saved=saved.append)
    return ctrl, made, saved


def test_starts_in_exchange_and_updates_encoder():
    ctrl, made, _ = make_ctrl()
    ctrl.step()
    assert ctrl.bus_snapshot().mode == "exchange"
    assert ctrl.encoder_snapshot().connected is True
    assert len(made["exchange"]) == 1


def test_scan_pauses_exchange_runs_and_resumes():
    probe = FakeProbe({3: Station(3, StationType.SLAVE, 2.0)})
    ctrl, made, _ = make_ctrl(probe=probe, addresses=[1, 2, 3])
    first_engine = made["exchange"][0][2]
    ctrl.scan()
    ctrl.step()                                  # -> scanning, sonda addr 2
    assert first_engine.stopped is True
    assert ctrl.bus_snapshot().mode == "scanning"
    ctrl.step()                                  # sonda addr 3 (hit) -> done -> resume
    ctrl.step()                                  # exchange de novo
    bs = ctrl.bus_snapshot()
    assert bs.mode == "exchange"
    assert [s.addr for s in bs.scan_state.found] == [3]
    assert probe.closed is True
    assert len(made["exchange"]) == 2            # recriou o engine


def test_apply_settings_persists_and_rebuilds():
    ctrl, made, saved = make_ctrl()
    ctrl.apply_settings(9600, 4)
    ctrl.step()
    assert saved == [BusSettings(baud=9600, master_addr=4)]
    assert ctrl.bus_snapshot().settings == BusSettings(baud=9600, master_addr=4)
    assert made["exchange"][-1][0] == BusSettings(baud=9600, master_addr=4)


def test_apply_invalid_settings_rejected():
    ctrl, made, saved = make_ctrl()
    n = len(made["exchange"])
    ctrl.apply_settings(99999, 1)
    ctrl.step()
    assert saved == []
    assert "inválida" in ctrl.bus_snapshot().diag
    assert len(made["exchange"]) == n


def test_exchange_build_failure_goes_idle_without_crash():
    def boom(settings, offset):
        raise RuntimeError("sem serial")

    ctrl = BusController(boom, lambda s: FakeProbe({}), BusSettings(),
                         addresses=[1, 2])
    ctrl.step()
    assert ctrl.bus_snapshot().mode == "idle"
    assert "erro" in ctrl.bus_snapshot().diag


def test_zero_forwarded_to_engine():
    ctrl, made, _ = make_ctrl()
    ctrl.zero()
    ctrl.step()
    assert made["exchange"][0][2].zeroed == 1


def test_offset_preserved_across_rebuild():
    ctrl, made, _ = make_ctrl(probe=FakeProbe({}), addresses=[1, 2])
    made["exchange"][0][2]._offset = 1234
    ctrl.step()                                  # lê offset do engine
    ctrl.scan()
    ctrl.step()                                  # scanning addrs=[2] -> done -> rebuild
    ctrl.step()
    assert made["exchange"][-1][1] == 1234       # offset repassado ao novo engine


def test_apply_settings_during_scan_defers_rebuild_until_done():
    ctrl, made, saved = make_ctrl(probe=FakeProbe({}), addresses=[0, 1, 2, 3])
    n = len(made["exchange"])                     # 1 (engine inicial)
    ctrl.scan()
    ctrl.step()                                   # entra em scanning
    assert ctrl.bus_snapshot().mode == "scanning"
    ctrl.apply_settings(9600, 4)
    ctrl.step()                                   # ainda scanning: NÃO recria o engine
    bs = ctrl.bus_snapshot()
    assert bs.mode == "scanning"
    assert bs.settings == BusSettings(9600, 4)    # settings refletidos já
    assert saved == [BusSettings(9600, 4)]        # persistidos já
    assert len(made["exchange"]) == n             # sem rebuild durante o scan
    for _ in range(10):                           # termina o scan
        ctrl.step()
        if ctrl.bus_snapshot().mode == "exchange":
            break
    assert ctrl.bus_snapshot().mode == "exchange"
    assert made["exchange"][-1][0] == BusSettings(9600, 4)  # rebuild com settings novos


def test_apply_persistence_failure_still_applies_and_rebuilds():
    made = {"exchange": []}

    def make_exchange(settings, offset):
        e = FakeEngine(offset=offset)
        made["exchange"].append((settings, offset, e))
        return e

    def boom_save(_):
        raise OSError("disco cheio")

    ctrl = BusController(make_exchange, lambda s: FakeProbe({}), BusSettings(),
                         addresses=[1, 2], on_settings_saved=boom_save)
    ctrl.apply_settings(9600, 4)
    ctrl.step()
    bs = ctrl.bus_snapshot()
    assert bs.settings == BusSettings(9600, 4)               # aplicado em memória
    assert made["exchange"][-1][0] == BusSettings(9600, 4)   # rebuild aconteceu
    assert "salvar" in bs.diag                               # avisa a falha de persistência


def test_initial_offset_passed_to_first_engine():
    made = {"exchange": []}

    def make_exchange(settings, offset):
        e = FakeEngine(offset=offset)
        made["exchange"].append((settings, offset, e))
        return e

    BusController(make_exchange, lambda s: FakeProbe({}),
                  BusSettings(), initial_offset=777, addresses=[1, 2])
    assert made["exchange"][0][1] == 777


def _io(in_hex=""):
    return IoSnapshot(active=True, address=9, connected=True, diag="OK",
                      in_hex=in_hex, out_hex="", input_size=2, output_size=0,
                      rate_hz=0.0, ts=0.0)


class FakeGenericEngine:
    def __init__(self):
        self.out = None
        self.stopped = False

    def step(self):
        return _io(in_hex="abcd")

    def snapshot(self):
        return _io(in_hex="abcd")

    def set_output(self, data):
        self.out = bytes(data)

    def stop(self):
        self.stopped = True


def make_ctrl_generic():
    made = {"exchange": [], "generic": []}

    def make_exchange(s, o):
        e = FakeEngine(offset=o)
        made["exchange"].append(e)
        return e

    def make_generic(s, spec):
        g = FakeGenericEngine()
        made["generic"].append((spec, g))
        return g

    ctrl = BusController(make_exchange, lambda s: FakeProbe({}), BusSettings(),
                         addresses=[1, 2], make_generic=make_generic)
    return ctrl, made


def _spec():
    return {"gsd": "ifm.gsd", "address": 9, "modules": ["Class 2 Multiturn"],
            "input_size": 2, "output_size": 0}


def test_param_read_enters_generic():
    ctrl, made = make_ctrl_generic()
    enc = made["exchange"][0]
    ctrl.param_read(_spec())
    ctrl.step()
    assert enc.stopped is True
    assert ctrl.bus_snapshot().mode == "generic"
    assert ctrl.io_snapshot().in_hex == "abcd"
    assert made["generic"][-1][0].address == 9


def test_set_output_forwarded_in_generic():
    ctrl, made = make_ctrl_generic()
    ctrl.param_read(_spec())
    ctrl.step()
    ctrl.set_output("00ff")
    ctrl.step()
    assert made["generic"][-1][1].out == b"\x00\xff"


def test_stop_generic_returns_to_exchange():
    ctrl, made = make_ctrl_generic()
    ctrl.param_read(_spec())
    ctrl.step()
    g = made["generic"][-1][1]
    ctrl.stop_generic()
    ctrl.step()
    assert g.stopped is True and ctrl.bus_snapshot().mode == "exchange"
    assert ctrl.io_snapshot().active is False


def test_param_read_build_failure_goes_idle():
    def boom(s, spec):
        raise RuntimeError("sem GSD")

    ctrl = BusController(lambda s, o: FakeEngine(), lambda s: FakeProbe({}),
                         BusSettings(), addresses=[1, 2], make_generic=boom)
    ctrl.param_read(_spec())
    ctrl.step()
    assert ctrl.bus_snapshot().mode == "idle"
    assert "erro" in ctrl.bus_snapshot().diag
