"""The integrated console: build steps, program output, diagnostics and exit status,
kept across runs and files until the user clears it."""

from __future__ import annotations

import itertools
import time
import tkinter as tk
from tkinter import ttk

from . import theme

MAX_LINES = 20000


class Console(ttk.Frame):
    def __init__(self, master: tk.Misc, fonts: theme.Fonts, on_location=None) -> None:
        super().__init__(master, style="Surface.TFrame")
        self.on_location = on_location  # called with (line, column) when a diagnostic is clicked
        bar = ttk.Frame(self, style="Bar.TFrame")
        ttk.Label(bar, text="CONSOLE", style="Bar.TLabel", font=fonts.heading, padding=(12, 6)).pack(side="left")
        self.summary = ttk.Label(bar, text="", style="Bar.TLabel", font=fonts.ui_small)
        self.summary.pack(side="left")
        ttk.Button(bar, text="Clear", style="Tool.TButton", command=self.clear, takefocus=False).pack(side="right")
        bar.pack(fill="x")
        body = ttk.Frame(self, style="Surface.TFrame")
        self.text = tk.Text(body, wrap="word", state="disabled", padx=12, pady=8, cursor="arrow",
                            **theme.text_options(fonts, font=fonts.mono_small))
        bar_y = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=bar_y.set)
        bar_y.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        body.pack(fill="both", expand=True)
        bold = fonts.mono_small.copy()
        bold.configure(weight="bold")
        for tag, color in (("out", theme.TEXT), ("info", theme.MUTED), ("ok", theme.GREEN), ("warn", theme.YELLOW),
                           ("compile", theme.RED), ("runtime", theme.ORANGE), ("time", theme.FAINT)):
            self.text.tag_configure(tag, foreground=color)
        self.text.tag_configure("head", foreground=theme.ACCENT, font=bold, spacing1=10)
        self.text.tag_configure("link", underline=True)
        self.text.bind("<Control-c>", lambda e: None)  # read-only, but copying works
        self._links = itertools.count()

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        self.summary.configure(text="")

    def write(self, text: str, *tags: str) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", text, tags)
        lines = int(self.text.index("end-1c").split(".")[0])
        if lines > MAX_LINES:
            self.text.delete("1.0", f"{lines - MAX_LINES}.0")
        self.text.configure(state="disabled")
        self.text.see("end")

    def line(self, text: str = "", *tags: str) -> None:
        self.write(text + "\n", *tags)

    def heading(self, text: str) -> None:
        if self.text.index("end-1c") != "1.0":
            self.write("\n")
        self.write(text, "head")
        self.write("   " + time.strftime("%H:%M:%S") + "\n", "time")

    def location(self, text: str, line: int, column: int, *tags: str) -> None:
        """A diagnostic line; clicking it moves the editor cursor to (line, column)."""
        tag = f"link{next(self._links)}"
        self.text.tag_bind(tag, "<Button-1>", lambda e: self.on_location and self.on_location(line, column))
        self.text.tag_bind(tag, "<Enter>", lambda e: self.text.configure(cursor="hand2"))
        self.text.tag_bind(tag, "<Leave>", lambda e: self.text.configure(cursor="arrow"))
        self.write(text + "\n", *tags, "link", tag)

    def contents(self) -> str:
        return self.text.get("1.0", "end-1c")
