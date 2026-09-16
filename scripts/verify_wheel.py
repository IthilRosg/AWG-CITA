"""Build an isolated wheel and verify AWG CITA package data is usable."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def python_in(environment: Path) -> Path:
    return environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def console_in(environment: Path) -> Path:
    return environment / ("Scripts/awg-cita.exe" if sys.platform == "win32" else "bin/awg-cita")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="awg-cita-wheel-") as temporary:
        work = Path(temporary)
        dist = work / "dist"
        subprocess.run([sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--wheel-dir", str(dist)], cwd=ROOT, check=True)
        wheel = next(dist.glob("awg_cita-*.whl"))
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
        required = {"awg_cita/static/sector-console.css", "awg_cita/static/sector-console.js"}
        if not required <= names:
            raise RuntimeError("wheel is missing static assets")
        environment = work / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        interpreter = python_in(environment)
        subprocess.run([str(interpreter), "-m", "pip", "install", "--no-index", "--find-links", str(dist), "awg-cita"], check=True)
        subprocess.run([str(interpreter), "-c", "import awg_cita.app"], check=True)
        subprocess.run([str(console_in(environment)), "--help"], check=True, stdout=subprocess.DEVNULL)
    print("wheel_package_data=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
