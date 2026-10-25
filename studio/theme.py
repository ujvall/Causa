"""CAUSA Studio's dark theme: colors, fonts and ttk styles."""

from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

BG = "#0d0f14"
SURFACE = "#13161d"
RAISED = "#1a1e27"
HOVER = "#222735"
BORDER = "#262b37"
SELECT = "#2a3550"
CURRENT_LINE = "#171b24"
TEXT = "#d5d9e2"
MUTED = "#808899"
FAINT = "#4b5265"
ACCENT = "#7aa2f7"
GREEN = "#9ece6a"
YELLOW = "#e0af68"
RED = "#f7768e"
PURPLE = "#bb9af7"
CYAN = "#7dcfff"
ORANGE = "#ff9e64"
ERROR_BG = "#3b1f2a"


def _pick(root: tk.Misc, families: tuple[str, ...], fallback: str) -> str:
    available = set(tkfont.families(root))
    return next((f for f in families if f in available), fallback)


class Fonts:
    def __init__(self, root: tk.Misc) -> None:
        mono = _pick(root, ("Cascadia Mono", "Cascadia Code", "Consolas", "Menlo", "DejaVu Sans Mono"), "Courier")
        ui = _pick(root, ("Segoe UI Variable Text", "Segoe UI", "Helvetica Neue", "DejaVu Sans"), "Helvetica")
        self.mono = tkfont.Font(root, family=mono, size=10)
        self.mono_small = tkfont.Font(root, family=mono, size=9)
        self.ui = tkfont.Font(root, family=ui, size=9)
        self.ui_bold = tkfont.Font(root, family=ui, size=9, weight="bold")
        self.ui_small = tkfont.Font(root, family=ui, size=8)
        self.brand = tkfont.Font(root, family=ui, size=11, weight="bold")
        self.heading = tkfont.Font(root, family=ui, size=8, weight="bold")


def apply(root: tk.Tk) -> Fonts:
    fonts = Fonts(root)
    root.configure(background=BG)
    root.option_add("*Font", fonts.ui)
    for widget in ("Menu", "Listbox"):
        root.option_add(f"*{widget}.background", RAISED)
        root.option_add(f"*{widget}.foreground", TEXT)
        root.option_add(f"*{widget}.selectBackground", SELECT)
        root.option_add(f"*{widget}.selectForeground", TEXT)
    root.option_add("*Menu.activeBackground", SELECT)
    root.option_add("*Menu.activeForeground", TEXT)
    root.option_add("*Menu.relief", "flat")
    root.option_add("*TCombobox*Listbox.background", RAISED)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", SELECT)

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=TEXT, fieldbackground=SURFACE, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, troughcolor=SURFACE, focuscolor=ACCENT,
                    selectbackground=SELECT, selectforeground=TEXT, insertcolor=TEXT, font=fonts.ui)
    style.configure("TFrame", background=BG)
    style.configure("Surface.TFrame", background=SURFACE)
    style.configure("Bar.TFrame", background=RAISED)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Surface.TLabel", background=SURFACE)
    style.configure("Bar.TLabel", background=RAISED, foreground=MUTED)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("SurfaceMuted.TLabel", background=SURFACE, foreground=MUTED)
    style.configure("Heading.TLabel", foreground=MUTED, font=fonts.heading)
    style.configure("Brand.TLabel", background=RAISED, foreground=TEXT, font=fonts.brand)
    style.configure("File.TLabel", background=RAISED, foreground=TEXT, font=fonts.ui)
    style.configure("Banner.TLabel", background="#1b2333", foreground=CYAN, padding=(10, 6))
    style.configure("Status.TLabel", background=RAISED, foreground=MUTED, font=fonts.ui_small, padding=(10, 3))
    style.configure("StatusOk.TLabel", background=RAISED, foreground=GREEN, font=fonts.ui_small, padding=(10, 3))
    style.configure("StatusBad.TLabel", background=RAISED, foreground=RED, font=fonts.ui_small, padding=(10, 3))
    style.configure("StatusBusy.TLabel", background=RAISED, foreground=YELLOW, font=fonts.ui_small, padding=(10, 3))

    style.configure("TButton", background=RAISED, foreground=TEXT, borderwidth=1, relief="flat", padding=(10, 4))
    style.map("TButton", background=[("disabled", BG), ("pressed", SELECT), ("active", HOVER)],
              foreground=[("disabled", FAINT)])
    style.configure("Tool.TButton", background=RAISED, bordercolor=RAISED, lightcolor=RAISED, darkcolor=RAISED,
                    padding=(10, 5))
    style.map("Tool.TButton", background=[("disabled", RAISED), ("pressed", SELECT), ("active", HOVER)],
              foreground=[("disabled", FAINT)])
    style.configure("Run.TButton", background="#24361f", foreground=GREEN, bordercolor="#2f4a27",
                    lightcolor="#24361f", darkcolor="#24361f", padding=(12, 5), font=fonts.ui_bold)
    style.map("Run.TButton", background=[("disabled", RAISED), ("pressed", "#2f4a27"), ("active", "#2c4426")],
              foreground=[("disabled", FAINT)])
    style.configure("Stop.TButton", background="#3a1f27", foreground=RED, bordercolor="#4d2833",
                    lightcolor="#3a1f27", darkcolor="#3a1f27", padding=(12, 5), font=fonts.ui_bold)
    style.map("Stop.TButton", background=[("disabled", RAISED), ("pressed", "#4d2833"), ("active", "#462531")],
              foreground=[("disabled", FAINT)], bordercolor=[("disabled", RAISED)])
    style.configure("Accent.TButton", background="#1f2a44", foreground=ACCENT, bordercolor="#2c3b60",
                    font=fonts.ui_bold)
    style.map("Accent.TButton", background=[("disabled", BG), ("pressed", "#2c3b60"), ("active", "#26345a")],
              foreground=[("disabled", FAINT)])

    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(8, 6, 8, 0))
    style.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(14, 6), borderwidth=0)
    style.map("TNotebook.Tab", background=[("selected", SURFACE)], foreground=[("selected", TEXT)],
              lightcolor=[("selected", SURFACE)], bordercolor=[("selected", BORDER)])
    style.configure("TPanedwindow", background=BORDER)
    style.configure("Sash", sashthickness=4, gripcount=0, background=BORDER)
    style.configure("TEntry", fieldbackground=SURFACE, foreground=TEXT, insertcolor=TEXT, padding=4)
    style.configure("TCombobox", fieldbackground=SURFACE, background=RAISED, foreground=TEXT, arrowcolor=MUTED,
                    padding=3)
    style.map("TCombobox", fieldbackground=[("readonly", SURFACE)], foreground=[("readonly", TEXT)],
              selectbackground=[("readonly", SURFACE)])
    style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=TEXT, rowheight=24,
                    borderwidth=0, font=fonts.mono_small)
    style.configure("Treeview.Heading", background=RAISED, foreground=MUTED, relief="flat", font=fonts.heading)
    style.map("Treeview", background=[("selected", SELECT)])
    for orient in ("Vertical", "Horizontal"):
        style.configure(f"{orient}.TScrollbar", background=RAISED, troughcolor=SURFACE, bordercolor=SURFACE,
                        arrowcolor=MUTED, lightcolor=RAISED, darkcolor=RAISED, gripcount=0)
        style.map(f"{orient}.TScrollbar", background=[("active", HOVER)])
    return fonts


def dark_title_bar(window: tk.Tk) -> None:
    """Ask Windows 10/11 for a dark title bar; silently does nothing elsewhere."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (newer, older builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value),
                                                          ctypes.sizeof(value)) == 0:
                break
    except (AttributeError, OSError):
        pass


def text_options(fonts: Fonts, **extra) -> dict:
    """Common options for the dark tk.Text widgets."""
    return {"background": SURFACE, "foreground": TEXT, "insertbackground": ACCENT, "selectbackground": SELECT,
            "selectforeground": TEXT, "borderwidth": 0, "highlightthickness": 0, "font": fonts.mono,
            "relief": "flat", **extra}
