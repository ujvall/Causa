"""The source editor: a tk.Text (the widget IDLE is built on) with line numbers,
CAUSA syntax highlighting, auto-indentation and diagnostic marks."""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk

from causa.lexer import KEYWORDS, RESERVED

from . import theme

INDENT = "    "
# One alternative per CAUSA token class (LS §3); a comment runs to the end of the line.
_TOKEN = re.compile(r"(?P<comment>#.*)|(?P<word>[A-Za-z_][A-Za-z0-9_]*)"
                    r"|(?P<number>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|(?P<op>==|!=|<=|>=|[-+*/=<>(),])")
_LITERAL_WORDS = {"true", "false"}
_WORD_OPERATORS = {"and", "or", "not"}


def classify(line: str) -> list[tuple[str, int, int]]:
    """(tag, start, end) for each highlighted token of one source line."""
    out, previous = [], None
    for m in _TOKEN.finditer(line):
        kind, start, end = m.lastgroup, m.start(), m.end()
        if kind == "word":
            word = m.group()
            if word in _LITERAL_WORDS:
                kind = "literal"
            elif word in _WORD_OPERATORS:
                kind = "op"
            elif word in KEYWORDS:
                kind = "keyword"
            elif word in RESERVED:
                kind = "reserved"
            elif previous in ("input", "let"):
                kind = "definition"
            else:
                kind = None
            previous = word
        else:
            previous = None
            kind = "literal" if kind == "number" else kind
        if kind:
            out.append((kind, start, end))
    return out


class CodeEditor(ttk.Frame):
    def __init__(self, master: tk.Misc, fonts: theme.Fonts, on_change=None, on_cursor=None) -> None:
        super().__init__(master, style="Surface.TFrame")
        self.fonts = fonts
        self.on_change = on_change
        self.on_cursor = on_cursor
        self.gutter = tk.Canvas(self, width=52, background=theme.SURFACE, highlightthickness=0, borderwidth=0)
        self.text = tk.Text(self, wrap="none", undo=True, maxundo=-1, autoseparators=True, padx=10, pady=8, height=8,
                            spacing1=2, spacing3=2, tabs=(fonts.mono.measure(INDENT),),
                            **theme.text_options(fonts))
        ybar = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        xbar = ttk.Scrollbar(self, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=lambda *a: (ybar.set(*a), self._draw_gutter()),
                            xscrollcommand=xbar.set)
        self.gutter.grid(row=0, column=0, sticky="ns")
        self.text.grid(row=0, column=1, sticky="nsew")
        ybar.grid(row=0, column=2, sticky="ns")
        xbar.grid(row=1, column=1, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        italic = fonts.mono.copy()
        italic.configure(slant="italic")
        bold = fonts.mono.copy()
        bold.configure(weight="bold")
        t = self.text
        t.tag_configure("currentline", background=theme.CURRENT_LINE)
        t.tag_configure("keyword", foreground=theme.PURPLE, font=bold)
        t.tag_configure("reserved", foreground=theme.RED)
        t.tag_configure("definition", foreground=theme.ACCENT)
        t.tag_configure("literal", foreground=theme.ORANGE)
        t.tag_configure("op", foreground=theme.CYAN)
        t.tag_configure("comment", foreground=theme.FAINT, font=italic)
        t.tag_configure("errorline", background=theme.ERROR_BG)
        t.tag_configure("error", underline=True, foreground=theme.RED)
        t.tag_lower("currentline")
        t.tag_raise("error")
        t.tag_raise("sel")

        t.bind("<<Modified>>", self._modified)
        t.bind("<Return>", self._newline)
        t.bind("<Tab>", self._indent)
        t.bind("<Shift-Tab>", self._dedent)
        t.bind("<Control-slash>", self._toggle_comment)
        t.bind("<Control-y>", lambda e: (self._redo(), "break")[1])
        t.bind("<Control-Shift-Z>", lambda e: (self._redo(), "break")[1])
        t.bind("<Control-a>", lambda e: (t.tag_add("sel", "1.0", "end-1c"), "break")[1])
        for event in ("<KeyRelease>", "<ButtonRelease-1>", "<FocusIn>"):
            t.bind(event, self._cursor_moved, add="+")
        self.bind("<Configure>", lambda e: self._draw_gutter())
        self._highlight_after: str | None = None

    # ---- content -----------------------------------------------------------
    def get_text(self) -> str:
        return self.text.get("1.0", "end-1c")

    def set_text(self, text: str) -> None:
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.text.edit_reset()
        self.text.edit_modified(False)
        self.text.mark_set("insert", "1.0")
        self.text.see("1.0")
        self.clear_errors()
        self.highlight()
        self._cursor_moved()

    def highlight(self) -> None:
        self._highlight_after = None
        t = self.text
        for tag in ("keyword", "reserved", "definition", "literal", "op", "comment"):
            t.tag_remove(tag, "1.0", "end")
        for number, line in enumerate(self.get_text().split("\n"), start=1):
            for tag, start, end in classify(line):
                t.tag_add(tag, f"{number}.{start}", f"{number}.{end}")

    # ---- diagnostics -------------------------------------------------------
    def clear_errors(self) -> None:
        self.text.tag_remove("error", "1.0", "end")
        self.text.tag_remove("errorline", "1.0", "end")

    def mark_error(self, line: int, column: int) -> None:
        """Underline the token at a diagnostic's location (1-based line and column)."""
        start = f"{line}.{max(column - 1, 0)}"
        end = self.text.index(f"{start} wordend")
        if self.text.compare(end, "==", start) or self.text.get(start) in ("", "\n"):
            end = f"{start}+1c"
        self.text.tag_add("errorline", f"{line}.0", f"{line}.0+1line")
        self.text.tag_add("error", start, end)

    def goto(self, line: int, column: int = 1) -> None:
        index = f"{line}.{max(column - 1, 0)}"
        self.text.mark_set("insert", index)
        self.text.see(index)
        self.text.focus_set()
        self._cursor_moved()

    # ---- editing behaviour ---------------------------------------------------
    def _modified(self, _event=None) -> None:
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        if self._highlight_after:
            self.after_cancel(self._highlight_after)
        self._highlight_after = self.after(60, self.highlight)
        self._draw_gutter()
        if self.on_change:
            self.on_change()

    def _newline(self, _event) -> str:
        t = self.text
        line = t.get("insert linestart", "insert")
        indent = line[: len(line) - len(line.lstrip(" \t"))]
        t.edit_separator()
        if t.tag_ranges("sel"):
            t.delete("sel.first", "sel.last")
        t.insert("insert", "\n" + indent)
        t.see("insert")
        return "break"

    def _selected_lines(self) -> range | None:
        if not self.text.tag_ranges("sel"):
            return None
        first = int(self.text.index("sel.first").split(".")[0])
        last_index = self.text.index("sel.last")
        last = int(last_index.split(".")[0]) - (last_index.endswith(".0") and last_index != self.text.index("sel.first"))
        return range(first, last + 1)

    def _indent(self, _event) -> str:
        lines = self._selected_lines()
        self.text.edit_separator()
        if lines is None:
            self.text.insert("insert", INDENT)
        else:
            for n in lines:
                self.text.insert(f"{n}.0", INDENT)
        return "break"

    def _dedent(self, _event) -> str:
        lines = self._selected_lines() or [int(self.text.index("insert").split(".")[0])]
        self.text.edit_separator()
        for n in lines:
            line = self.text.get(f"{n}.0", f"{n}.end")
            count = len(line) - len(line.lstrip(" ")[:]) if line.startswith(" ") else 0
            if count:
                self.text.delete(f"{n}.0", f"{n}.{min(count, len(INDENT))}")
        return "break"

    def _toggle_comment(self, _event) -> str:
        lines = self._selected_lines() or [int(self.text.index("insert").split(".")[0])]
        texts = [self.text.get(f"{n}.0", f"{n}.end") for n in lines]
        uncomment = all(t.lstrip().startswith("#") or not t.strip() for t in texts)
        self.text.edit_separator()
        for n, line in zip(lines, texts):
            if uncomment:
                i = line.find("#")
                if i >= 0:
                    width = 2 if line[i + 1: i + 2] == " " else 1
                    self.text.delete(f"{n}.{i}", f"{n}.{i + width}")
            elif line.strip():
                self.text.insert(f"{n}.0", "# ")
        return "break"

    def _redo(self) -> None:
        try:
            self.text.edit_redo()
        except tk.TclError:
            pass

    def _cursor_moved(self, _event=None) -> None:
        t = self.text
        t.tag_remove("currentline", "1.0", "end")
        t.tag_add("currentline", "insert linestart", "insert linestart+1line")
        if self.on_cursor:
            line, column = t.index("insert").split(".")
            self.on_cursor(int(line), int(column) + 1)

    def _draw_gutter(self) -> None:
        g, t = self.gutter, self.text
        g.delete("all")
        width = max(52, self.fonts.mono_small.measure("0" * len(t.index("end-1c").split(".")[0])) + 24)
        g.configure(width=width)
        current = t.index("insert").split(".")[0]
        error_lines = {t.index(r).split(".")[0] for r in t.tag_ranges("errorline")[::2]}
        index = t.index("@0,0")
        while True:
            info = t.dlineinfo(index)
            if info is None:
                break
            number = index.split(".")[0]
            color = theme.RED if number in error_lines else theme.TEXT if number == current else theme.FAINT
            g.create_text(width - 12, info[1] + info[3] / 2, anchor="e", text=number, fill=color,
                          font=self.fonts.mono_small)
            next_index = t.index(f"{index}+1line")
            if next_index == index:
                break
            index = next_index
