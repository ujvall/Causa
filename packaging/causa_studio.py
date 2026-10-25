"""Entry point for the packaged CAUSA Studio (PyInstaller runs this file as a script)."""

import sys

from studio.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
