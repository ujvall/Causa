"""Capture genuine CAUSA Studio screenshots by driving the real application window.

Run from the repository root under a virtual or real display, with a Python that has Tk:

    xvfb-run -a -s "-screen 0 2400x1350x24" python3.12 presentation/capture_studio.py

Needs ImageMagick's `import` on PATH. Writes PNGs to presentation/assets/. Nothing in
Studio is modified; the script only calls the same methods the application's own UI tests use.
"""

import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent / "assets"
OUT.mkdir(exist_ok=True)

from studio.app import StudioApp  # noqa: E402

root = tk.Tk()
app = StudioApp(root)


def pump(condition, timeout=90.0):
    end = time.time() + timeout
    while not condition():
        root.update()
        time.sleep(0.02)
        if time.time() > end:
            raise SystemExit("timed out")
    root.update()


def settle(seconds=0.6):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def shot(name):
    settle()
    root.update_idletasks()
    geometry = f"{root.winfo_width()}x{root.winfo_height()}+{root.winfo_rootx()}+{root.winfo_rooty()}"
    subprocess.run(["import", "-window", "root", "-crop", geometry, "+repage", str(OUT / name)], check=True)


def status(panel):
    return str(panel.status.cget("text"))


pump(lambda: app.graph is not None)
app.run()
pump(lambda: app.last_run is not None)
app.select_binding("total")
app.tabs.select(0)
main = app.tabs.master  # the horizontal pane: give the graph room so every column is visible
settle()
main.sashpos(0, int(root.winfo_width() * 0.36))
app.graph_view.canvas.xview_moveto(0)
app.graph_view.canvas.yview_moveto(0)
shot("studio_graph.png")
main.sashpos(0, int(root.winfo_width() * 0.5))

app.explain.choice.set("total")
app.explain.run()
pump(lambda: status(app.explain).startswith(("From the runtime", "explain total did not")))
app.tabs.select(1)
shot("studio_explain.png")

app.impact.choice.set("discount")
app.impact.run()
pump(lambda: status(app.impact).startswith(("From the runtime", "impact discount did not")))
app.tabs.select(2)
shot("studio_impact.png")

app.whatif.rows[0][1].set("price")
app.whatif.rows[0][2].delete(0, "end")
app.whatif.rows[0][2].insert(0, "150")
app.whatif.run()
pump(lambda: status(app.whatif).startswith(("From the runtime", "whatif")))
app.tabs.select(3)
shot("studio_whatif.png")

app.dirty = False
app.quit()
print("captured:", sorted(p.name for p in OUT.glob("studio_*.png")))
