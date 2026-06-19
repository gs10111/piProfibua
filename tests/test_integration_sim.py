"""Integração em sim: BusController real (Amg11Master dummy + SimBusProbe).

Exercita o caminho completo sem hardware nem WebSocket: troca -> scan ->
encontra o escravo simulado -> retoma a troca.
"""
from pathlib import Path

from serve import build_controller, default_slave_addr

ROOT = Path(__file__).resolve().parent.parent
CONF = str(ROOT / "config" / "amg11.conf")
ENC = str(ROOT / "config" / "encoder.yaml")


def test_sim_controller_scans_and_finds_slave(tmp_path):
    slave = default_slave_addr(CONF)
    assert slave is not None
    ctrl = build_controller(CONF, ENC, sim=True, bus_json=tmp_path / "bus.json",
                            addresses=[0, slave, slave + 1])
    try:
        ctrl.step()                                  # troca
        assert ctrl.bus_snapshot().mode == "exchange"
        ctrl.scan()
        # drena o scan até terminar (poucos endereços)
        for _ in range(20):
            ctrl.step()
            if ctrl.bus_snapshot().scan_state.status == "done":
                break
        bs = ctrl.bus_snapshot()
        assert bs.scan_state.status == "done"
        assert slave in [s.addr for s in bs.scan_state.found]
        # retomou a troca após o scan
        ctrl.step()
        assert ctrl.bus_snapshot().mode == "exchange"
    finally:
        ctrl.stop()
