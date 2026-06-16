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
