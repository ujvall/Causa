"""Dependency graph view: bindings from the IR provenance, laid out in columns by
dependency depth. Arrows point from a dependency to the binding that uses it
(the direction values flow). Selecting a binding highlights its transitive
dependencies (upstream) and dependents (downstream)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme
from .service import Graph

NODE_W, NODE_H, COL_GAP, ROW_GAP, MARGIN = 140, 42, 70, 14, 28
MAX_DRAWN = 4000  # bindings; beyond this the canvas would stop being responsive


def layout(graph: Graph) -> dict[str, tuple[int, int]]:
    """(column, row) per binding: the column is the longest dependency path from an
    input; rows follow declaration order. Declarations come before use, so one pass suffices."""
    depth: dict[str, int] = {}
    rows: dict[int, int] = {}
    out = {}
    for b in graph.bindings:
        depth[b.name] = 1 + max((depth[d] for d in b.deps), default=-1)
        column = depth[b.name]
        out[b.name] = (column, rows.get(column, 0))
        rows[column] = rows.get(column, 0) + 1
    return out


class GraphView(ttk.Frame):
    def __init__(self, master: tk.Misc, fonts: theme.Fonts, on_select=None) -> None:
        super().__init__(master, style="Surface.TFrame")
        self.fonts = fonts
        self.on_select = on_select
        self.scale = self.winfo_fpixels("1i") / 96  # layout sizes are given for 96 DPI
        legend = ttk.Frame(self, style="Surface.TFrame", padding=(12, 8))
        for color, label in ((theme.GREEN, "input"), (theme.ACCENT, "let"), (theme.CYAN, "upstream (depends on)"),
                             (theme.ORANGE, "downstream (affected)")):
            swatch = tk.Canvas(legend, width=10, height=10, background=theme.SURFACE, highlightthickness=0)
            swatch.create_rectangle(1, 1, 9, 9, outline=color, width=2)
            swatch.pack(side="left", padx=(0, 4))
            ttk.Label(legend, text=label, style="SurfaceMuted.TLabel", font=fonts.ui_small).pack(side="left",
                                                                                              padx=(0, 14))
        self.caption = ttk.Label(legend, text="", style="SurfaceMuted.TLabel", font=fonts.ui_small)
        self.caption.pack(side="right")
        legend.pack(fill="x")
        body = ttk.Frame(self, style="Surface.TFrame")
        self.canvas = tk.Canvas(body, background=theme.SURFACE, highlightthickness=0, borderwidth=0)
        ybar = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        xbar = ttk.Scrollbar(body, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        body.pack(fill="both", expand=True)
        c = self.canvas
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", lambda e: c.scan_dragto(e.x, e.y, gain=1))
        c.bind("<MouseWheel>", lambda e: c.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        c.bind("<Shift-MouseWheel>", lambda e: c.xview_scroll(-1 if e.delta > 0 else 1, "units"))
        c.bind("<Configure>", lambda e: self._place_message())
        self.graph: Graph | None = None
        self.selected: str | None = None
        self._nodes: dict[str, tuple[int, int, int]] = {}  # name -> (rectangle, name text, detail text)
        self._edges: list[tuple[str, str, int]] = []
        self._message: int | None = None
        self.show_message("Run or open a program to see its dependency graph.")

    # ---- states ----------------------------------------------------------------
    def show_message(self, text: str, error: bool = False) -> None:
        self.graph, self.selected = None, None
        self.canvas.delete("all")
        self._nodes, self._edges = {}, []
        self._message = self.canvas.create_text(0, 0, text=text, fill=theme.RED if error else theme.MUTED,
                                                font=self.fonts.ui, justify="center", width=360)
        self.caption.configure(text="")
        self.canvas.configure(scrollregion=(0, 0, 0, 0))
        self._place_message()

    def _place_message(self) -> None:
        if self._message is not None:
            self.canvas.coords(self._message, self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2)

    def set_graph(self, graph: Graph) -> None:
        if not graph.bindings:
            self.show_message("This program declares no bindings yet.")
            return
        if len(graph.bindings) > MAX_DRAWN:
            self.show_message(f"{len(graph.bindings)} bindings: too many to draw responsively.\n"
                              "Explain, Impact and What-if still work.")
            return
        keep = self.selected if graph.binding(self.selected or "") else None
        c = self.canvas
        c.delete("all")
        self._message = None
        self.graph, self._nodes, self._edges = graph, {}, []
        s = self.scale
        node_w, node_h, margin = NODE_W * s, NODE_H * s, MARGIN * s
        position = {}
        for name, (column, row) in layout(graph).items():
            x = margin + column * (NODE_W + COL_GAP) * s
            y = margin + row * (NODE_H + ROW_GAP) * s
            position[name] = (x, y)
        for dep, name in graph.edges:
            (x1, y1), (x2, y2) = position[dep], position[name]
            x1, y1, x2, y2 = x1 + node_w, y1 + node_h / 2, x2, y2 + node_h / 2
            bend = max(COL_GAP * s / 2, (x2 - x1) / 3)
            edge = c.create_line(x1, y1, x1 + bend, y1, x2 - bend, y2, x2, y2, smooth=True, arrow="last",
                                 arrowshape=(8, 9, 3), fill=theme.BORDER, width=1.5)
            self._edges.append((dep, name, edge))
        for b in graph.bindings:
            x, y = position[b.name]
            tag = f"node:{b.name}"
            rect = c.create_rectangle(x, y, x + node_w, y + node_h, fill=theme.RAISED, outline=theme.BORDER,
                                      width=1.5, tags=(tag, "node"))
            label = c.create_text(x + 10 * s, y + 14 * s, anchor="w", text=_fit(b.name, 16), fill=theme.TEXT,
                                  font=self.fonts.mono_small, tags=(tag, "node"))
            detail = c.create_text(x + 10 * s, y + 30 * s, anchor="w", text=f"{b.kind} · {b.type}",
                                   fill=theme.MUTED, font=self.fonts.ui_small, tags=(tag, "node"))
            self._nodes[b.name] = (rect, label, detail)
        box = c.bbox("all")
        c.configure(scrollregion=(0, 0, box[2] + margin, box[3] + margin))
        lets = sum(b.kind == "let" for b in graph.bindings)
        counts = ((len(graph.bindings) - lets, "input"), (lets, "let"), (len(self._edges), "edge"))
        self.caption.configure(text=" · ".join(f"{n} {word}{'' if n == 1 else 's'}" for n, word in counts))
        self.select(keep, notify=False)

    # ---- selection -------------------------------------------------------------
    def select(self, name: str | None, notify: bool = True, reveal: bool = False) -> None:
        if self.graph is None:
            return
        if name is not None and name not in self._nodes:
            name = None
        self.selected = name
        up = set(self.graph.upstream[name]) if name else set()
        down = set(self.graph.downstream[name]) if name else set()
        c = self.canvas
        for b in self.graph.bindings:
            rect, label, detail = self._nodes[b.name]
            base = theme.GREEN if b.kind == "input" else theme.ACCENT
            if name is None:
                outline, width, fg = (base if b.kind == "input" else theme.BORDER), 1.5, theme.TEXT
                c.itemconfigure(rect, fill=theme.RAISED)
            elif b.name == name:
                outline, width, fg = base, 3, theme.TEXT
                c.itemconfigure(rect, fill=theme.SELECT)
            elif b.name in up:
                outline, width, fg = theme.CYAN, 2, theme.TEXT
                c.itemconfigure(rect, fill=theme.RAISED)
            elif b.name in down:
                outline, width, fg = theme.ORANGE, 2, theme.TEXT
                c.itemconfigure(rect, fill=theme.RAISED)
            else:
                outline, width, fg = theme.BORDER, 1, theme.FAINT
                c.itemconfigure(rect, fill=theme.SURFACE)
            c.itemconfigure(rect, outline=outline, width=width)
            c.itemconfigure(label, fill=fg)
        for dep, user, edge in self._edges:
            if name and user in up | {name} and dep in up:
                color, width = theme.CYAN, 2
            elif name and dep in down | {name} and user in down:
                color, width = theme.ORANGE, 2
            else:
                color, width = (theme.BORDER if name else "#3a4152"), 1.5
            c.itemconfigure(edge, fill=color, width=width)
        if reveal and name:
            self.reveal(name)
        if notify and self.on_select:
            self.on_select(name)

    def reveal(self, name: str) -> None:
        x1, y1, x2, y2 = self.canvas.coords(self._nodes[name][0])
        region = [float(v) for v in str(self.canvas.cget("scrollregion")).split()]
        if region and region[2] > 0:
            self.canvas.xview_moveto(max(0.0, (x1 - 40) / region[2]))
            self.canvas.yview_moveto(max(0.0, (y1 - 40) / region[3]))

    def _press(self, event) -> None:
        c = self.canvas
        c.scan_mark(event.x, event.y)
        x, y = c.canvasx(event.x), c.canvasy(event.y)
        for item in c.find_overlapping(x, y, x, y):
            for tag in c.gettags(item):
                if tag.startswith("node:"):
                    self.select(tag[5:])
                    return


def _fit(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"
