"""Build a Windows desktop bundle of CAUSA Studio with PyInstaller.

    py -3.11 -m pip install pyinstaller     (once, preferably in a virtual environment)
    py -3.11 packaging/build_windows.py

Output: dist/CAUSA Studio/CAUSA Studio.exe, a folder bundle that includes Python,
Tk, the compiler, the C runtime sources and the example program. Building and
running CAUSA programs still needs a C compiler (gcc) on PATH or in CAUSA_CC.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    data = [(ROOT / "causa" / "runtime" / "causa_runtime.h", "causa/runtime"),
            (ROOT / "causa" / "runtime" / "causa_runtime.c", "causa/runtime"),
            (ROOT / "examples" / "pricing.cau", "examples")]
    argv = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", "CAUSA Studio",
            "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build" / "pyinstaller"),
            "--specpath", str(ROOT / "build" / "pyinstaller"), "--paths", str(ROOT)]
    for source, target in data:
        argv += ["--add-data", f"{source}{os.pathsep}{target}"]
    argv.append(str(ROOT / "packaging" / "causa_studio.py"))
    return subprocess.run(argv, cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
