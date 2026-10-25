"""Explain, Impact and What-if panels. Each asks the application to run one real
CAUSA statement (explain / impact / whatif) and shows what the runtime printed;
nothing here evaluates CAUSA itself."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme
from .service import Graph, Outcome, check_literal, parse_impact_report, parse_whatif_report


def _output_text(master: tk.Misc, fonts: theme.Fonts, height: int = 10) -> tk.Text:
    text = tk.Text(master, height=height, wrap="none", state="disabled", padx=10, pady=8,
                   **theme.text_options(fonts, font=fonts.mono_small, background=theme.BG))
    text.tag_configure("muted", foreground=theme.MUTED)
    text.tag_configure("error", foreground=theme.RED)
    return text


def _set(text: tk.Text, content: str, tag: str | None = None) -> None:
    text.configure(state="normal")
    text.delete("1.0", "end")
    text.insert("1.0", content, (tag,) if tag else ())
    text.configure(state="disabled")


def outcome_problem(outcome: Outcome) -> str | None:
    """A readable reason why a query produced no report, or None."""
    if outcome.stage == "cancelled":
        return "Stopped."
    if outcome.diagnostics and not (outcome.stage == "run" and outcome.exit_code == 0):
        return "\n".join(d.message for d in outcome.diagnostics) + ("\n" + outcome.stderr if outcome.stderr
                                                                    and outcome.stage == "build" else "")
    if outcome.stage == "run" and outcome.exit_code != 0:
        return outcome.stderr.strip() or f"The program exited with status {outcome.exit_code}."
    return None


class QueryPanel(ttk.Frame):
    """Shared parts: a binding chooser, an action button and a status line."""

    verb = ""
    button_text = ""
    kinds = ("input", "let")

    def __init__(self, master: tk.Misc, fonts: theme.Fonts, request, select) -> None:
        super().__init__(master, style="Surface.TFrame", padding=14)
        self.fonts = fonts
        self.request = request  # request(verb, payload) -> starts a real query
        self.select = select  # select(name): make this the selected binding everywhere
        self.graph: Graph | None = None
        row = ttk.Frame(self, style="Surface.TFrame")
        ttk.Label(row, text="Binding", style="SurfaceMuted.TLabel").pack(side="left", padx=(0, 8))
        self.choice = ttk.Combobox(row, state="readonly", width=24, font=fonts.mono_small)
        self.choice.pack(side="left")
        self.choice.bind("<<ComboboxSelected>>", lambda e: self.select(self.choice.get()))
        self.button = ttk.Button(row, text=self.button_text, style="Accent.TButton", command=self.run)
        self.button.pack(side="left", padx=8)
        row.pack(fill="x")
        self.status = ttk.Label(self, text="", style="SurfaceMuted.TLabel", font=fonts.ui_small)
        self.status.pack(fill="x", pady=(8, 6))

    def set_graph(self, graph: Graph | None) -> None:
        self.graph = graph
        names = [b.name for b in graph.bindings if b.kind in self.kinds] if graph else []
        self.choice.configure(values=names)
        if self.choice.get() not in names:
            self.choice.set(names[0] if names else "")
        self.button.state(["!disabled"] if names else ["disabled"])
        self.binding_changed()

    def set_selected(self, name: str | None) -> None:
        if name and self.graph and name in self.choice.cget("values"):
            self.choice.set(name)
            self.binding_changed()

    def binding_changed(self) -> None:
        pass

    def run(self) -> None:
        name = self.choice.get()
        if name:
            self.status.configure(text=f"Running {self.verb} {name} …", foreground=theme.YELLOW)
            self.request(self.verb, name)

    def mark_stale(self) -> None:
        if str(self.status.cget("text")).startswith("From the "):
            self.status.configure(text="The source changed since this result. Run it again to refresh.",
                                  foreground=theme.YELLOW)

    def done(self, label: str) -> None:
        self.status.configure(text=f"From the runtime, for {label}.", foreground=theme.MUTED)


class ExplainPanel(QueryPanel):
    verb, button_text = "explain", "Explain"

    def __init__(self, master, fonts, request, select, goto) -> None:
        super().__init__(master, fonts, request, select)
        self.goto = goto
        ttk.Label(self, text="PROVENANCE  (from the compiler)", style="Heading.TLabel",
                  background=theme.SURFACE).pack(anchor="w")
        self.details = ttk.Frame(self, style="Surface.TFrame", padding=(0, 6, 0, 12))
        self.details.pack(fill="x")
        ttk.Label(self, text="EXPLANATION  (printed by the CAUSA runtime)", style="Heading.TLabel",
                  background=theme.SURFACE).pack(anchor="w")
        self.output = _output_text(self, fonts, height=14)
        self.output.pack(fill="both", expand=True, pady=(6, 0))
        _set(self.output, "Choose a binding and press Explain.", "muted")

    def binding_changed(self) -> None:
        for child in self.details.winfo_children():
            child.destroy()
        b = self.graph.binding(self.choice.get()) if self.graph else None
        if b is None:
            return
        rows = [("Kind", f"{b.kind} · {b.type}"),
                ("Declared", f"line {b.line}"),
                ("Expression", b.source_text or "(input literal)"),
                ("Depends on", ", ".join(b.deps) or "—"),
                ("Used by", ", ".join(b.dependents) or "—"),
                ("All inputs", ", ".join(n for n in self.graph.upstream[b.name]
                                          if self.graph.binding(n).kind == "input") or "—")]
        for r, (key, value) in enumerate(rows):
            ttk.Label(self.details, text=key, style="SurfaceMuted.TLabel", font=self.fonts.ui_small).grid(
                row=r, column=0, sticky="nw", padx=(0, 14), pady=1)
            label = ttk.Label(self.details, text=value, style="Surface.TLabel", font=self.fonts.mono_small,
                              wraplength=420)
            label.grid(row=r, column=1, sticky="w", pady=1)
            if key == "Declared":
                label.configure(foreground=theme.ACCENT, cursor="hand2")
                label.bind("<Button-1>", lambda e, line=b.line, col=b.column: self.goto(line, col))

    def show(self, name: str, outcome: Outcome) -> None:
        problem = outcome_problem(outcome)
        if problem:
            _set(self.output, problem, "error")
            self.status.configure(text=f"explain {name} did not complete.", foreground=theme.RED)
        else:
            _set(self.output, outcome.stdout)
            self.done(f"explain {name}")


class ImpactPanel(QueryPanel):
    verb, button_text = "impact", "Show impact"

    def __init__(self, master, fonts, request, select) -> None:
        super().__init__(master, fonts, request, select)
        lists = ttk.Frame(self, style="Surface.TFrame")
        self.direct = self._list(lists, "DIRECT DEPENDENTS", 0)
        self.every = self._list(lists, "ALL AFFECTED BINDINGS", 1)
        lists.columnconfigure((0, 1), weight=1, uniform="lists")
        lists.rowconfigure(1, weight=1)
        lists.pack(fill="both", expand=True)
        ttk.Label(self, text="RUNTIME OUTPUT", style="Heading.TLabel", background=theme.SURFACE).pack(
            anchor="w", pady=(10, 0))
        self.output = _output_text(self, fonts, height=4)
        self.output.pack(fill="x", pady=(6, 0))
        ttk.Label(self, text="Affected bindings are highlighted in orange in the Graph tab. Select one to explore it.",
                  style="SurfaceMuted.TLabel", font=fonts.ui_small).pack(anchor="w", pady=(8, 0))

    def _list(self, master, title: str, column: int) -> tk.Listbox:
        ttk.Label(master, text=title, style="Heading.TLabel", background=theme.SURFACE).grid(
            row=0, column=column, sticky="w", pady=(0, 4))
        box = tk.Listbox(master, activestyle="none", borderwidth=0, highlightthickness=0, font=self.fonts.mono_small,
                         background=theme.BG, foreground=theme.TEXT, selectbackground=theme.SELECT, height=8)
        box.grid(row=1, column=column, sticky="nsew", padx=(0, 8 if column == 0 else 0))
        box.bind("<<ListboxSelect>>", lambda e: box.curselection() and self.select(box.get(box.curselection()[0])))
        return box

    def show(self, name: str, outcome: Outcome) -> None:
        for box in (self.direct, self.every):
            box.delete(0, "end")
        problem = outcome_problem(outcome)
        if problem:
            _set(self.output, problem, "error")
            self.status.configure(text=f"impact {name} did not complete.", foreground=theme.RED)
            return
        direct, every = parse_impact_report(outcome.stdout)
        for box, names in ((self.direct, direct), (self.every, every)):
            for n in names or ["(none)"]:
                box.insert("end", n)
        _set(self.output, outcome.stdout)
        self.done(f"impact {name}")


class WhatIfPanel(ttk.Frame):
    """Several inputs can be overridden together; the runtime evaluates them in an
    isolated counterfactual environment (LS §8.5), so the program's own results never change."""

    def __init__(self, master: tk.Misc, fonts: theme.Fonts, request) -> None:
        super().__init__(master, style="Surface.TFrame", padding=14)
        self.fonts = fonts
        self.request = request
        self.graph: Graph | None = None
        ttk.Label(self, text="Each what-if runs in a separate counterfactual environment. The program's own "
                             "values are not changed.", style="Banner.TLabel", font=fonts.ui_small,
                  wraplength=560).pack(fill="x", pady=(0, 10))
        self.rows_frame = ttk.Frame(self, style="Surface.TFrame")
        self.rows_frame.pack(fill="x")
        self.rows: list[tuple[ttk.Frame, ttk.Combobox, ttk.Entry, ttk.Label]] = []
        actions = ttk.Frame(self, style="Surface.TFrame")
        self.add_button = ttk.Button(actions, text="+ Add input", command=self.add_row)
        self.add_button.pack(side="left")
        self.run_button = ttk.Button(actions, text="Run what-if", style="Accent.TButton", command=self.run)
        self.run_button.pack(side="left", padx=8)
        actions.pack(fill="x", pady=(6, 4))
        self.status = ttk.Label(self, text="", style="SurfaceMuted.TLabel", font=fonts.ui_small)
        self.status.pack(fill="x", pady=(4, 6))
        columns = ("original", "counterfactual", "note")
        self.table = ttk.Treeview(self, columns=columns, show="tree headings", height=9, selectmode="none")
        self.table.heading("#0", text="Binding", anchor="w")
        self.table.heading("original", text="Original", anchor="w")
        self.table.heading("counterfactual", text="Counterfactual", anchor="w")
        self.table.heading("note", text="", anchor="w")
        self.table.column("#0", width=140, stretch=False)
        self.table.column("note", width=110, stretch=False)
        for tag, color in (("override", theme.YELLOW), ("changed", theme.ACCENT), ("same_value", theme.MUTED),
                           ("failed", theme.RED), ("unavailable", theme.RED)):
            self.table.tag_configure(tag, foreground=color)
        self.table.pack(fill="both", expand=True)
        ttk.Label(self, text="RUNTIME OUTPUT", style="Heading.TLabel", background=theme.SURFACE).pack(
            anchor="w", pady=(10, 0))
        self.output = _output_text(self, fonts, height=5)
        self.output.pack(fill="x", pady=(6, 0))
        self.add_row()

    def set_graph(self, graph: Graph | None) -> None:
        self.graph = graph
        names = [b.name for b in graph.inputs] if graph else []
        for _, combo, _, _ in self.rows:
            combo.configure(values=names)
            if combo.get() not in names:
                combo.set(names[0] if names else "")
            self._update_hint(combo)
        self.run_button.state(["!disabled"] if names else ["disabled"])

    def add_row(self) -> None:
        frame = ttk.Frame(self.rows_frame, style="Surface.TFrame")
        names = [b.name for b in self.graph.inputs] if self.graph else []
        used = {r[1].get() for r in self.rows}
        combo = ttk.Combobox(frame, state="readonly", width=18, values=names, font=self.fonts.mono_small)
        combo.set(next((n for n in names if n not in used), names[0] if names else ""))
        entry = ttk.Entry(frame, width=16, font=self.fonts.mono_small)
        hint = ttk.Label(frame, text="", style="SurfaceMuted.TLabel", font=self.fonts.ui_small)
        remove = ttk.Button(frame, text="✕", width=3, command=lambda: self.remove_row(frame))
        ttk.Label(frame, text="whatif" if not self.rows else "     ,", style="SurfaceMuted.TLabel",
                  font=self.fonts.mono_small, width=7).pack(side="left")
        combo.pack(side="left")
        ttk.Label(frame, text="=", style="SurfaceMuted.TLabel", font=self.fonts.mono_small).pack(side="left", padx=6)
        entry.pack(side="left")
        remove.pack(side="left", padx=6)
        hint.pack(side="left", padx=4)
        combo.bind("<<ComboboxSelected>>", lambda e: self._update_hint(combo))
        entry.bind("<Return>", lambda e: self.run())
        frame.pack(fill="x", pady=2)
        self.rows.append((frame, combo, entry, hint))
        self._update_hint(combo)
        entry.focus_set()

    def remove_row(self, frame: ttk.Frame) -> None:
        if len(self.rows) == 1:
            return
        self.rows = [r for r in self.rows if r[0] is not frame]
        frame.destroy()

    def _update_hint(self, combo: ttk.Combobox) -> None:
        row = next(r for r in self.rows if r[1] is combo)
        b = self.graph.binding(combo.get()) if self.graph else None
        row[3].configure(text=f"{b.type} input, source value at line {b.line}" if b else "")

    def overrides(self) -> list[tuple[str, str]]:
        return [(combo.get(), entry.get()) for _, combo, entry, _ in self.rows]

    def run(self) -> None:
        overrides = self.overrides()
        for name, value in overrides:
            try:
                check_literal(value)
            except ValueError as err:
                self.status.configure(text=f"{name}: {err}", foreground=theme.RED)
                return
        self.status.configure(text="Running the counterfactual …", foreground=theme.YELLOW)
        self.request("whatif", overrides)

    def mark_stale(self) -> None:
        if str(self.status.cget("text")).startswith("From the "):
            self.status.configure(text="The source changed since this result. Run it again to refresh.",
                                  foreground=theme.YELLOW)

    def show(self, statement: str, outcome: Outcome) -> None:
        self.table.delete(*self.table.get_children())
        problem = outcome_problem(outcome)
        if problem:
            _set(self.output, problem, "error")
            self.status.configure(text=f"{statement} did not complete.", foreground=theme.RED)
            return
        rows = parse_whatif_report(outcome.stdout)
        for name, before, after, note in rows:
            self.table.insert("", "end", text=name, values=(before, after, note), tags=(note.replace(" ", "_"),))
        recomputed = sum(note != "override" for *_, note in rows)
        _set(self.output, outcome.stdout)
        self.status.configure(text=f"From the runtime, for {statement}: {recomputed} dependent binding(s) "
                                   f"re-evaluated in an isolated environment.", foreground=theme.MUTED)
