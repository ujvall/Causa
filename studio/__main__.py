"""Launch CAUSA Studio:  py -3.11 -m studio [FILE.cau]"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if sys.platform == "win32":
        try:  # crisp text on high-DPI displays
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    import tkinter as tk

    from .app import StudioApp

    root = tk.Tk(className="CausaStudio")
    StudioApp(root, args[0] if args else None)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
