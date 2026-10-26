"""CAUSA Studio main window: file handling, the Run/Stop workflow and the wiring
between the editor, console, graph and panels. Compiler work goes through
service.Session on worker threads (service.Runner); this module only reacts to results."""

from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from causa.diagnostics import CausaError

from . import theme
from .console import Console
from .editor import CodeEditor
from .format import format_output, format_stderr
from .graph import GraphView
from .panels import ExplainPanel, ImpactPanel, WhatIfPanel
from .service import (EXIT_MEANING, Outcome, Runner, Session, binding_statement, python_description, read_file,
                      whatif_statement, write_file)

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "pricing.cau"
QUERY_CHANNELS = ("explain", "impact", "whatif")
CHECK_DELAY_MS = 350


def _ms(seconds: float) -> str:
    return f"{seconds * 1000:.0f} ms" if seconds < 10 else f"{seconds:.1f} s"


class StudioApp:
    def __init__(self, root: tk.Tk, path: str | Path | None = None, session: Session | None = None) -> None:
        self.root = root
        self.fonts = theme.apply(root)
        self.session = session or Session()
        self.runner = Runner()
        self.path: Path | None = None
        self.name = "untitled.cau"
        self.example = False
        self.dirty = False
        self.version = 0  # incremented on every edit; results remember the version they were made from
        self.graph = None
        self.pending: dict[int, tuple[int, str]] = {}  # request id -> (source version, label)
        self._check_after: str | None = None
        self._poll_after: str | None = None
        self.last_run: Outcome | None = None
        self._build()
        self._icon()
        self.console.add(lambda c, raw: c.line("Press ▶ Run (F5) to compile and run the program.", "info"))
        root.protocol("WM_DELETE_WINDOW", self.quit)
        theme.dark_title_bar(root)
        if path:
            self.open(Path(path), confirm=False)
        else:
            self.open_example(confirm=False)
        self._poll()

    # ---- layout ----------------------------------------------------------------
    def _build(self) -> None:
        root = self.root
        root.title("CAUSA Studio")
        width, height = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{int(width * 0.86)}x{int(height * 0.86)}+{int(width * 0.07)}+{int(height * 0.04)}")
        root.minsize(980, 620)
        self._menu()

        header = ttk.Frame(root, style="Bar.TFrame", padding=(14, 6))
        ttk.Label(header, text="◆  CAUSA Studio", style="Brand.TLabel").pack(side="left", padx=(0, 18))
        for text, command in (("New", self.new), ("Open…", self.open), ("Save", self.save)):
            ttk.Button(header, text=text, style="Tool.TButton", command=command, takefocus=False).pack(side="left")
        ttk.Separator(header, orient="vertical").pack(side="left", fill="y", padx=12, pady=4)
        self.run_button = ttk.Button(header, text="▶  Run", style="Run.TButton", command=self.run, takefocus=False)
        self.run_button.pack(side="left")
        self.stop_button = ttk.Button(header, text="■  Stop", style="Stop.TButton", command=self.stop,
                                      takefocus=False)
        self.stop_button.pack(side="left", padx=6)
        self.stop_button.state(["disabled"])
        self.file_label = ttk.Label(header, text="", style="File.TLabel")
        self.file_label.pack(side="right")
        header.pack(fill="x")

        status = ttk.Frame(root, style="Bar.TFrame")
        version = self.session.compiler_version()
        self.toolchain_label = ttk.Label(
            status, style="Status.TLabel" if version else "StatusBad.TLabel",
            text=f"{python_description()}  ·  {version}" if version else
            f"{python_description()}  ·  No C compiler found: programs cannot be built (set CAUSA_CC or add gcc to PATH)")
        self.toolchain_label.pack(side="left")
        self.cursor_label = ttk.Label(status, text="Ln 1, Col 1", style="Status.TLabel")
        self.cursor_label.pack(side="right")
        self.exec_label = ttk.Label(status, text="Idle", style="Status.TLabel")
        self.exec_label.pack(side="right")
        self.check_label = ttk.Label(status, text="", style="Status.TLabel")
        self.check_label.pack(side="right")
        status.pack(side="bottom", fill="x")

        main = ttk.Panedwindow(root, orient="horizontal")
        left = ttk.Panedwindow(main, orient="vertical")
        self.editor = CodeEditor(left, self.fonts, on_change=self._edited,
                                 on_cursor=lambda l, c: self.cursor_label.configure(text=f"Ln {l}, Col {c}"))
        self.console = Console(left, self.fonts, on_location=self.goto)
        left.add(self.editor, weight=1)
        left.add(self.console, weight=1)
        self.tabs = ttk.Notebook(main)
        self.graph_view = GraphView(self.tabs, self.fonts, on_select=self.select_binding)
        self.explain = ExplainPanel(self.tabs, self.fonts, self.query, self.select_binding, self.goto)
        self.impact = ImpactPanel(self.tabs, self.fonts, self.query, self.select_binding)
        self.whatif = WhatIfPanel(self.tabs, self.fonts, self.query)
        for panel, title in ((self.graph_view, "Graph"), (self.explain, "Explain"), (self.impact, "Impact"),
                             (self.whatif, "What-if")):
            self.tabs.add(panel, text=title)
        main.add(left, weight=1)
        main.add(self.tabs, weight=1)
        main.pack(fill="both", expand=True)

        shortcuts = {"<Control-n>": self.new, "<Control-o>": self.open, "<Control-s>": self.save,
                     "<Control-S>": self.save_as, "<Control-Shift-s>": self.save_as, "<F5>": self.run,
                     "<Control-Return>": self.run, "<Shift-F5>": self.stop, "<Control-l>": self.console.clear}
        for key in range(1, 5):
            shortcuts[f"<Control-Key-{key}>"] = lambda k=key: self.tabs.select(k - 1)
        for sequence, command in shortcuts.items():
            handler = lambda e, c=command: (c(), "break")[1]
            root.bind(sequence, handler)
            self.editor.text.bind(sequence, handler)  # before the Text class bindings (Ctrl+O opens a line)

    def _menu(self) -> None:
        bar = tk.Menu(self.root, tearoff=False)
        file = tk.Menu(bar, tearoff=False)
        file.add_command(label="New", accelerator="Ctrl+N", command=self.new)
        file.add_command(label="Open…", accelerator="Ctrl+O", command=self.open)
        file.add_command(label="Open Example (pricing.cau)", command=self.open_example)
        file.add_separator()
        file.add_command(label="Save", accelerator="Ctrl+S", command=self.save)
        file.add_command(label="Save As…", accelerator="Ctrl+Shift+S", command=self.save_as)
        file.add_separator()
        file.add_command(label="Exit", command=self.quit)
        edit = tk.Menu(bar, tearoff=False)
        for item in (("Undo", "Ctrl+Z", "<<Undo>>"), ("Redo", "Ctrl+Y", "<<Redo>>"), None,
                     ("Cut", "Ctrl+X", "<<Cut>>"), ("Copy", "Ctrl+C", "<<Copy>>"), ("Paste", "Ctrl+V", "<<Paste>>"),
                     None, ("Select All", "Ctrl+A", "<<SelectAll>>")):
            if item is None:
                edit.add_separator()
            else:
                label, accel, event = item
                edit.add_command(label=label, accelerator=accel,
                                 command=lambda ev=event: self.editor.text.event_generate(ev))
        edit.add_command(label="Toggle Comment", accelerator="Ctrl+/",
                         command=lambda: self.editor._toggle_comment(None))
        run = tk.Menu(bar, tearoff=False)
        run.add_command(label="Run", accelerator="F5", command=self.run)
        run.add_command(label="Stop", accelerator="Shift+F5", command=self.stop)
        run.add_separator()
        run.add_command(label="Clear Console", accelerator="Ctrl+L", command=lambda: self.console.clear())
        view = tk.Menu(bar, tearoff=False)
        for i, title in enumerate(("Graph", "Explain", "Impact", "What-if"), start=1):
            view.add_command(label=title, accelerator=f"Ctrl+{i}", command=lambda i=i: self.tabs.select(i - 1))
        help_menu = tk.Menu(bar, tearoff=False)
        help_menu.add_command(label="About CAUSA Studio", command=self.about)
        for label, menu in (("File", file), ("Edit", edit), ("Run", run), ("View", view), ("Help", help_menu)):
            bar.add_cascade(label=label, menu=menu)
        self.root.configure(menu=bar)

    def _icon(self) -> None:
        size = 32
        image = tk.PhotoImage(master=self.root, width=size, height=size)
        for y in range(size):
            half = size // 2 - abs(y - size // 2 + 0.5)
            if half > 0:
                start, end = int(size / 2 - half), int(size / 2 + half)
                image.put(theme.ACCENT, to=(start, y, end, y + 1))
        self.root.iconphoto(True, image)
        self._icon_image = image

    # ---- files -----------------------------------------------------------------
    def _set_document(self, text: str, path: Path | None, name: str, example: bool = False) -> None:
        self.path, self.name, self.example = path, name, example
        self.editor.set_text(text)
        self.dirty = False
        self.version += 1
        self.last_run = None
        self._update_title()
        self._schedule_check(0)

    def _update_title(self) -> None:
        label = f"{self.name} (example, unsaved copy)" if self.example else str(self.path or self.name)
        self.file_label.configure(text=("●  " if self.dirty else "") + label,
                                  foreground=theme.YELLOW if self.dirty else theme.TEXT)
        self.root.title(f"{'● ' if self.dirty else ''}{self.name} — CAUSA Studio")

    def confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel("CAUSA Studio", f"Save changes to {self.name}?", parent=self.root)
        if answer is None:
            return False
        return self.save() if answer else True

    def new(self) -> None:
        if self.confirm_discard():
            self._set_document("", None, "untitled.cau")

    def open(self, path: Path | None = None, confirm: bool = True) -> bool:
        if confirm and not self.confirm_discard():
            return False
        if path is None:
            chosen = filedialog.askopenfilename(parent=self.root, title="Open CAUSA program",
                                                filetypes=[("CAUSA programs", "*.cau"), ("All files", "*.*")])
            if not chosen:
                return False
            path = Path(chosen)
        try:
            text = read_file(path)
        except (OSError, CausaError) as err:
            messagebox.showerror("CAUSA Studio", f"Cannot open {path}:\n{getattr(err, 'strerror', None) or err}",
                                 parent=self.root)
            return False
        self._set_document(text, path.resolve(), path.name)
        return True

    def open_example(self, confirm: bool = True) -> None:
        if confirm and not self.confirm_discard():
            return
        try:
            text = read_file(EXAMPLE)
        except OSError:
            self._set_document("", None, "untitled.cau")
            return
        self._set_document(text, None, EXAMPLE.name, example=True)  # saving asks for a new location

    def save(self) -> bool:
        if self.path is None:
            return self.save_as()
        return self._write(self.path)

    def save_as(self) -> bool:
        chosen = filedialog.asksaveasfilename(parent=self.root, title="Save CAUSA program", defaultextension=".cau",
                                              initialfile=self.name,
                                              filetypes=[("CAUSA programs", "*.cau"), ("All files", "*.*")])
        return bool(chosen) and self._write(Path(chosen))

    def _write(self, path: Path) -> bool:
        try:
            write_file(path, self.editor.get_text())
        except OSError as err:
            messagebox.showerror("CAUSA Studio", f"Cannot save {path}:\n{err.strerror}", parent=self.root)
            return False
        self.path, self.name, self.example, self.dirty = path.resolve(), path.name, False, False
        self._update_title()
        self._schedule_check(0)  # diagnostics name the file
        return True

    def quit(self) -> None:
        if not self.confirm_discard():
            return
        self.runner.cancel()
        self.session.close()
        # Cancel on the widget that scheduled each callback (tkinter tracks them per widget).
        for widget, after in ((self.root, self._check_after), (self.root, self._poll_after),
                              (self.editor, self.editor._highlight_after)):
            if after:
                widget.after_cancel(after)
        self._check_after = self._poll_after = self.editor._highlight_after = None
        self.root.update_idletasks()  # run ttk's pending idle work before the interpreter goes away
        self.root.destroy()

    # ---- editing and live checking ---------------------------------------------------
    def _edited(self) -> None:
        self.version += 1
        if not self.dirty:
            self.dirty = True
            self._update_title()
        for panel in (self.explain, self.impact, self.whatif):
            panel.mark_stale()
        self._schedule_check(CHECK_DELAY_MS)

    def _schedule_check(self, delay: int) -> None:
        if self._check_after:
            self.root.after_cancel(self._check_after)
        self._check_after = self.root.after(delay, self._check)

    def _check(self) -> None:
        self._check_after = None
        self.check_label.configure(text="Checking…", style="StatusBusy.TLabel")
        # Worker threads must not hold references to Tk objects: pass the session, not self.
        request = self.runner.submit("check", lambda job, session, text, name: session.analyze(text, name),
                                     self.session, self.editor.get_text(), self.name)
        self.pending[request] = (self.version, "check")

    def _show_check(self, outcome: Outcome) -> None:
        self.editor.clear_errors()
        if outcome.ok:
            self.check_label.configure(text="✓ No errors", style="StatusOk.TLabel")
            self._set_graph(outcome.graph)
            return
        d = outcome.diagnostics[0]
        if d.line:
            self.editor.mark_error(d.line, d.column)
        summary = f"✕ {d.code} at {d.line}:{d.column}: {d.message.split(': ', 2)[-1]}" if d.code else "✕ error"
        self.check_label.configure(text=summary if len(summary) < 90 else summary[:89] + "…",
                                   style="StatusBad.TLabel")
        if self.graph is None:
            self.graph_view.show_message(f"The program has an error:\n{d.message}", error=True)

    def _set_graph(self, graph) -> None:
        if graph is None or graph == self.graph:
            return
        self.graph = graph
        self.graph_view.set_graph(graph)
        for panel in (self.explain, self.impact, self.whatif):
            panel.set_graph(graph)
        if self.graph_view.selected:
            self.select_binding(self.graph_view.selected)

    def goto(self, line: int, column: int) -> None:
        self.editor.goto(line, column)

    def select_binding(self, name: str | None) -> None:
        if self.graph_view.selected != name:
            self.graph_view.select(name, notify=False, reveal=True)
        if name:
            self.explain.set_selected(name)
            self.impact.set_selected(name)

    # ---- run, stop and queries ---------------------------------------------------
    def run(self) -> None:
        if self.runner.busy("run"):
            return
        title, stamp = f"Run  {self.name}", time.strftime("%H:%M:%S")
        self.console.add(lambda c, raw: c.heading(title, stamp))
        self._set_exec("Building and running…", "StatusBusy.TLabel")
        request = self.runner.submit("run", self.session.run, self.editor.get_text(), self.name)
        self.pending[request] = (self.version, "run")
        self.stop_button.state(["!disabled"])
        self.run_button.state(["disabled"])

    def stop(self) -> None:
        if any(self.runner.busy(c) for c in ("run", *QUERY_CHANNELS)):
            self.runner.cancel("run", *QUERY_CHANNELS)
            self._set_exec("Stopping…", "StatusBusy.TLabel")

    def query(self, verb: str, payload) -> None:
        """Start an explain/impact/whatif request; payload is a binding name or a list of overrides."""
        panel = {"explain": self.explain, "impact": self.impact, "whatif": self.whatif}[verb]
        if self.graph is None:
            panel.status.configure(text="Fix the program's errors first.", foreground=theme.RED)
            return
        try:
            statement = (whatif_statement(self.graph, payload) if verb == "whatif"
                         else binding_statement(self.graph, verb, payload))
        except ValueError as err:
            panel.status.configure(text=str(err), foreground=theme.RED)
            return
        if verb == "impact":
            self.select_binding(payload)
        request = self.runner.submit(verb, self.session.query, self.editor.get_text(), self.name, statement)
        self.pending[request] = (self.version, payload if verb != "whatif" else statement)
        self.stop_button.state(["!disabled"])

    def _set_exec(self, text: str, style: str = "Status.TLabel") -> None:
        self.exec_label.configure(text=text, style=style)

    def _poll(self) -> None:
        for channel, request, outcome in self.runner.poll():
            version, label = self.pending.pop(request, (None, ""))
            if channel == "check":
                if version == self.version:  # an older check finished after a newer edit: ignore it
                    self._show_check(outcome)
            elif channel == "run":
                self._show_run(outcome)
            else:
                panel = {"explain": self.explain, "impact": self.impact, "whatif": self.whatif}[channel]
                panel.show(label, outcome)
                self._log_query(channel, label, outcome)
                if version != self.version:
                    panel.mark_stale()
        if not any(self.runner.busy(c) for c in ("run", *QUERY_CHANNELS)):
            self.stop_button.state(["disabled"])
        if not self.runner.busy("run"):
            self.run_button.state(["!disabled"])
        self._poll_after = self.root.after(40, self._poll)

    def _log_query(self, verb: str, label: str, outcome: Outcome) -> None:
        text = label if verb == "whatif" else f"{verb} {label}"
        status = ("stopped" if outcome.stage == "cancelled" else f"exit {outcome.exit_code}"
                  if outcome.stage == "run" else f"{outcome.stage} failed")
        line = [("◆  ", "muted"), (text, "name" if outcome.ok else "warn"),
                (f"   {self._panel_names[verb]} panel  ·  {status}  ·  {self._timings(outcome)}", "time")]
        self.console.add(lambda c, raw: (c.write("\n"), c.spans(line)))

    _panel_names = {"explain": "Explain", "impact": "Impact", "whatif": "What-if"}

    @staticmethod
    def _timings(outcome: Outcome) -> str:
        names = {"compile": "compile", "build": "C build", "run": "run"}
        return "  ·  ".join(f"{names[k]} {_ms(v)}" for k, v in outcome.timings.items())

    def _show_run(self, outcome: Outcome) -> None:
        self.last_run = outcome
        self.editor.clear_errors()
        if outcome.graph is not None:
            self._set_graph(outcome.graph)
        for d in outcome.diagnostics:
            if d.line:
                self.editor.mark_error(d.line, d.column)
        code = outcome.exit_code
        meaning = EXIT_MEANING.get(code, "unexpected status")
        status = {"compile": ("Compile error", "StatusBad.TLabel"), "build": ("Build failed", "StatusBad.TLabel"),
                  "cancelled": ("Stopped", "Status.TLabel")}.get(
            outcome.stage, (f"Exit {code}: {meaning}", "StatusOk.TLabel" if code == 0 else "StatusBad.TLabel"))
        self._set_exec(*status)
        timings = self._timings(outcome)
        self.console.add(lambda c, raw: self._render_run(c, raw, outcome, timings))

    @staticmethod
    def _render_run(c: Console, raw: bool, outcome: Outcome, timings: str) -> None:
        """One run's result: formatted, or exactly as printed (raw)."""
        if outcome.stage == "compile":
            for d in outcome.diagnostics:
                if raw or not d.line:
                    c.location(d.message, d.line, d.column, "compile") if d.line else c.line(d.message, "compile")
                else:
                    spans, where = format_stderr(d.message)[0]
                    c.spans(spans, where)
            c.line("✕ Compile error: no program was built." if raw else "\n✕  compile error · no program was built",
                   "compile")
        elif outcome.stage == "build":
            for d in outcome.diagnostics:
                c.line(d.message, "warn")
            if outcome.stderr:
                c.line(outcome.stderr.rstrip(), "info")
        elif outcome.stage == "cancelled":
            c.line("■ Stopped. The build or the program was terminated.", "warn")
        elif raw:
            if outcome.stdout:
                c.write(outcome.stdout, "out")
            located = {d.message: d for d in outcome.diagnostics if d.line}
            for line in outcome.stderr.splitlines():
                d = located.get(line)
                c.location(line, d.line, d.column, "runtime") if d else c.line(line, "runtime")
        else:
            for spans in format_output(outcome.stdout):
                c.spans(spans)
            if outcome.stderr:
                if outcome.stdout:
                    c.write("\n")
                for spans, where in format_stderr(outcome.stderr):
                    c.spans(spans, where)
        if outcome.stage == "run":
            code = outcome.exit_code
            meaning = EXIT_MEANING.get(code, "unexpected status")
            if raw:
                c.line(f"■ Exit code {code} ({meaning})", "ok" if code == 0 else "runtime")
            else:
                c.write("\n")
                c.spans([("✓  " if code == 0 else "✕  ", "ok" if code == 0 else "error"),
                         (f"exit {code} · {meaning}", "ok" if code == 0 else "error")])
        if timings:
            c.line(timings, "time")

    def about(self) -> None:
        messagebox.showinfo("About CAUSA Studio",
                            "CAUSA Studio\nA desktop environment for the CAUSA language.\n\n"
                            f"{python_description()}\nC compiler: {self.session.compiler_version() or 'not found'}\n\n"
                            "Programs are compiled by the CAUSA compiler in this repository and run by the CAUSA "
                            "runtime. Everything runs locally.", parent=self.root)
