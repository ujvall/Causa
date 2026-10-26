"""The integrated console: build steps, program output, diagnostics and exit status,
kept across runs and files until the user clears it.

Each entry is a block that renders itself either formatted (studio.format lays
the runtime's output out as labelled blocks) or raw (exactly what the compiler
and the program printed); the Raw output switch redraws the whole history."""

from __future__ import annotations

import itertools
import time
import tkinter as tk
from tkinter import ttk

from . import theme
from .format import Line

MAX_LINES = 20000
MAX_BLOCKS = 300


class Console(ttk.Frame):
    def __init__(self, master: tk.Misc, fonts: theme.Fonts, on_location=None) -> None:
        super().__init__(master, style="Surface.TFrame")
        self.on_location = on_location  # called with (line, column) when a diagnostic is clicked
        bar = ttk.Frame(self, style="Bar.TFrame")
        ttk.Label(bar, text="CONSOLE", style="Bar.TLabel", font=fonts.heading, padding=(12, 6)).pack(side="left")
        ttk.Button(bar, text="Clear", style="Tool.TButton", command=self.clear, takefocus=False).pack(side="right")
        self.raw = tk.BooleanVar(self, value=False)
        ttk.Checkbutton(bar, text="Raw output", variable=self.raw, style="Bar.TCheckbutton", takefocus=False,
                        command=self.redraw).pack(side="right", padx=(0, 6))
        bar.pack(fill="x")
        body = ttk.Frame(self, style="Surface.TFrame")
        self.text = tk.Text(body, wrap="none", state="disabled", padx=14, pady=10, cursor="arrow", spacing1=1, height=8,
                            spacing3=1, **theme.text_options(fonts, font=fonts.mono_small))
        bar_y = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        bar_x = ttk.Scrollbar(body, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=bar_y.set, xscrollcommand=bar_x.set)
        bar_y.pack(side="right", fill="y")
        bar_x.pack(side="bottom", fill="x")
        self.text.pack(side="left", fill="both", expand=True)
        body.pack(fill="both", expand=True)
        bold = fonts.mono_small.copy()
        bold.configure(weight="bold")
        italic = fonts.mono_small.copy()
        italic.configure(slant="italic")
        colors = {"out": theme.TEXT, "info": theme.MUTED, "ok": theme.GREEN, "warn": theme.YELLOW,
                  "compile": theme.RED, "runtime": theme.ORANGE, "time": theme.FAINT, "name": theme.ACCENT,
                  "value": theme.ORANGE, "expr": theme.CYAN, "muted": theme.MUTED, "faint": theme.FAINT,
                  "names": theme.TEXT, "tree": theme.FAINT, "override": theme.YELLOW, "changed": theme.GREEN,
                  "failed": theme.RED, "error": theme.RED, "error-code": theme.RED}
        for tag, color in colors.items():
            self.text.tag_configure(tag, foreground=color)
        for tag, color in (("label-show", theme.GREEN), ("label-explain", theme.PURPLE),
                           ("label-whatif", theme.YELLOW), ("label-impact", theme.CYAN), ("label-error", theme.RED)):
            self.text.tag_configure(tag, foreground=color, font=bold)
        self.text.tag_configure("error-code", font=bold)
        self.text.tag_configure("expr", font=italic)
        self.text.tag_configure("head", foreground=theme.ACCENT, font=bold)
        self.text.tag_configure("rule", foreground=theme.BORDER)
        self.text.tag_configure("link", underline=True)
        self._links = itertools.count()
        self._blocks: list = []

    # ---- blocks ------------------------------------------------------------------
    def add(self, render) -> None:
        """Append a block: render(console, raw) writes it in the current mode."""
        self._blocks.append(render)
        del self._blocks[:-MAX_BLOCKS]
        render(self, self.raw.get())

    def redraw(self) -> None:
        self._erase()
        for render in self._blocks:
            render(self, self.raw.get())

    def clear(self) -> None:
        self._blocks = []
        self._erase()

    def _erase(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    # ---- writing -----------------------------------------------------------------
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

    def spans(self, spans: Line, location: tuple[int, int] | None = None) -> None:
        """One line made of styled spans; with a location, clicking it moves the editor cursor there."""
        extra = (self._link_tag(*location),) if location else ()
        for text, style in spans:
            self.write(text, *((style,) if style else ()), *extra)
        self.write("\n", *extra)

    def heading(self, text: str, stamp: str | None = None) -> None:
        if self.text.index("end-1c") != "1.0":
            self.write("\n")
        self.write("▶  ", "head")
        self.write(text, "head")
        self.write("   " + (stamp or time.strftime("%H:%M:%S")) + "\n", "time")
        self.write("─" * 72 + "\n", "rule")

    def location(self, text: str, line: int, column: int, *tags: str) -> None:
        """A diagnostic line as printed; clicking it moves the editor cursor to (line, column)."""
        self.write(text + "\n", *tags, "link", self._link_tag(line, column))

    def _link_tag(self, line: int, column: int) -> str:
        tag = f"link{next(self._links)}"
        self.text.tag_bind(tag, "<Button-1>", lambda e: self.on_location and self.on_location(line, column))
        self.text.tag_bind(tag, "<Enter>", lambda e: self.text.configure(cursor="hand2"))
        self.text.tag_bind(tag, "<Leave>", lambda e: self.text.configure(cursor="arrow"))
        return tag

    def contents(self) -> str:
        return self.text.get("1.0", "end-1c")
