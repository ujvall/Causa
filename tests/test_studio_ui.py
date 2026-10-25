"""CAUSA Studio's principal workflows, driven through the real Tk window with the
real compiler, C compiler and runtime. Skipped when no display or no Tk is available."""

import gc
import tempfile
import time
import unittest
from pathlib import Path

from studio.service import read_file
from test_codegen import CC

ROOT = Path(__file__).resolve().parent.parent
SPEC_OUTPUT = (ROOT / "docs" / "language-specification.md").read_text(encoding="utf-8") \
    .split("Required stdout")[1].split("```")[1].lstrip("\n")

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.update_idletasks()
    _root.destroy()
    TK = True
except Exception:  # no Tk, or no display
    TK = False


@unittest.skipUnless(TK, "Tk is not available (no display?)")
class StudioWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        from studio.app import StudioApp
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = StudioApp(self.root)
        self.pump(lambda: self.app.graph is not None)

    def tearDown(self) -> None:
        self.app.dirty = False  # never show the save prompt in tests
        directory = self.app.session.dir
        self.app.quit()
        self.assertFalse(directory.exists())
        # Collect the destroyed window's Tk objects here, on the main thread: left to the
        # cyclic garbage collector, they could be freed on a worker thread, which Tcl forbids.
        self.app = self.root = None
        gc.collect()

    def pump(self, condition, timeout: float = 90.0) -> None:
        deadline = time.time() + timeout
        while not condition():
            self.root.update()
            time.sleep(0.01)
            if time.time() > deadline:
                self.fail("timed out waiting for the application")
        self.root.update()

    def status(self, panel) -> str:
        return str(panel.status.cget("text"))

    def replace_source(self, text: str) -> None:
        self.app.editor.text.delete("1.0", "end")
        self.app.editor.text.insert("1.0", text)
        self.root.update()

    def test_starts_with_the_pricing_example_as_an_unsaved_copy(self) -> None:
        self.assertEqual(self.app.editor.get_text(), read_file(ROOT / "examples" / "pricing.cau"))
        self.assertTrue(self.app.example)
        self.assertIsNone(self.app.path)  # Save asks for a location: the repository example is never overwritten
        self.assertEqual(len(self.app.graph.bindings), 11)
        self.assertEqual(self.app.graph_view.caption.cget("text"), "5 inputs · 6 lets · 11 edges")

    def test_syntax_highlighting_uses_causa_tokens(self) -> None:
        tags = self.app.editor.text.tag_names("4.0")  # "input price = 100"
        self.assertIn("keyword", tags)
        self.assertIn("definition", self.app.editor.text.tag_names("4.6"))
        self.assertIn("literal", self.app.editor.text.tag_names("4.14"))
        self.assertIn("comment", self.app.editor.text.tag_names("1.0"))

    @unittest.skipUnless(CC, "no C compiler")
    def test_run_shows_real_output_in_the_console(self) -> None:
        self.app.console.clear()
        self.app.run()
        self.pump(lambda: self.app.last_run is not None)
        text = self.app.console.contents()
        self.assertIn(SPEC_OUTPUT, text + "\n")
        self.assertIn("■ Exit code 0 (success)", text)
        self.assertRegex(text, r"compile \d+ ms  ·  C build \d+ ms  ·  run \d+ ms")
        self.assertEqual(self.app.exec_label.cget("text"), "Exit 0: success")

    def test_compile_error_is_located_in_the_editor(self) -> None:
        self.replace_source("input price = 100\nlet total = price + true\nshow total\n")
        self.pump(lambda: "✕" in str(self.app.check_label.cget("text")))
        self.assertTrue(str(self.app.check_label.cget("text")).startswith("✕ E401 at 2:19"))
        self.assertEqual(self.app.editor.text.tag_ranges("error")[0].string, "2.18")
        if CC:
            self.app.run()
            self.pump(lambda: self.app.last_run is not None)
            self.assertIn("pricing.cau:2:19: error[E401]", self.app.console.contents())
            self.assertIn("✕ Compile error: no program was built.", self.app.console.contents())

    @unittest.skipUnless(CC, "no C compiler")
    def test_runtime_failure_leaves_the_application_usable(self) -> None:
        self.replace_source("input d = 0\nlet q = 10 / d\nshow q\n")
        self.app.run()
        self.pump(lambda: self.app.last_run is not None)
        self.assertEqual(self.app.last_run.exit_code, 2)
        self.assertIn("pricing.cau:2:12: runtime error[R101]: division by zero", self.app.console.contents())
        self.assertIn("■ Exit code 2 (runtime error)", self.app.console.contents())
        self.assertEqual(self.app.editor.text.tag_ranges("error")[0].string, "2.11")
        self.app.last_run = None
        self.replace_source("input d = 4\nlet q = 10 / d\nshow q\n")
        self.app.run()
        self.pump(lambda: self.app.last_run is not None)
        self.assertEqual(self.app.last_run.stdout, "q = 2.5\n")

    def test_save_and_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "saved.cau"
            self.replace_source("input a = 2\nlet b = a * 3\nshow b\n")
            self.assertTrue(self.app.dirty)
            self.assertTrue(self.app._write(path))  # what Save As does after the dialog
            self.assertFalse(self.app.dirty)
            self.assertEqual(path.read_text(encoding="utf-8"), "input a = 2\nlet b = a * 3\nshow b\n")
            self.app.editor.text.insert("end", "show a\n")
            self.root.update()
            self.assertTrue(self.app.dirty)
            self.assertEqual(path.read_text(encoding="utf-8"), "input a = 2\nlet b = a * 3\nshow b\n")
            self.app.dirty = False
            self.assertTrue(self.app.open(path))
            self.assertEqual(self.app.editor.get_text(), "input a = 2\nlet b = a * 3\nshow b\n")
            self.assertEqual(self.app.path, path.resolve())
            self.assertTrue(self.app.save())  # a file with a path saves without a dialog
            self.pump(lambda: [b.name for b in self.app.graph.bindings] == ["a", "b"])

    def test_graph_selection_highlights_both_directions(self) -> None:
        view = self.app.graph_view
        view.select("subtotal")
        rect = lambda name: view.canvas.itemcget(view._nodes[name][0], "outline")
        from studio import theme
        self.assertEqual(rect("price"), theme.CYAN)  # upstream
        self.assertEqual(rect("savings"), theme.CYAN)
        self.assertEqual(rect("total"), theme.ORANGE)  # downstream
        self.assertEqual(rect("bulk"), theme.ORANGE)
        self.assertEqual(rect("tax"), theme.BORDER)  # unrelated
        self.assertEqual(self.app.explain.choice.get(), "subtotal")  # selection is shared with the panels

    @unittest.skipUnless(CC, "no C compiler")
    def test_explain_impact_and_whatif_panels(self) -> None:
        app = self.app
        app.explain.choice.set("total")
        app.explain.run()
        self.pump(lambda: self.status(app.explain).startswith(("From the runtime", "explain total did not")))
        explanation = app.explain.output.get("1.0", "end-1c")
        self.assertTrue(explanation.startswith("explain total\n  total = 88.375  [let: subtotal * (1 + tax) + fee]"))

        app.impact.choice.set("discount")
        app.impact.run()
        self.pump(lambda: self.status(app.impact).startswith(("From the runtime", "impact discount did not")))
        self.assertEqual(app.impact.direct.get(0, "end"), ("savings",))
        self.assertEqual(app.impact.every.get(0, "end"),
                         ("savings", "subtotal", "total", "expensive", "per_unit", "bulk"))
        self.assertEqual(app.graph_view.selected, "discount")

        rows = app.whatif.rows
        rows[0][1].set("price")
        rows[0][2].insert(0, "160")
        app.whatif.add_row()
        app.whatif.rows[1][1].set("discount")
        app.whatif.rows[1][2].insert(0, "0.5")
        app.whatif.run()
        self.pump(lambda: self.status(app.whatif).startswith(("From the runtime", "whatif")))
        table = {app.whatif.table.item(i, "text"): app.whatif.table.item(i, "values")
                 for i in app.whatif.table.get_children()}
        self.assertEqual(table["price"], ("100", "160", "override"))
        self.assertEqual(table["total"], ("88.375", "94.0", "changed"))
        self.assertEqual(table["bulk"], ("true", "true", "same value"))
        self.assertIn("6 dependent binding(s) re-evaluated", self.status(app.whatif))

        app.whatif.rows[0][2].delete(0, "end")
        app.whatif.rows[0][2].insert(0, "1.5")  # a float for an int input: the compiler's E403
        app.whatif.run()
        self.pump(lambda: "did not complete" in self.status(app.whatif))
        self.assertIn("error[E403]", app.whatif.output.get("1.0", "end-1c"))

    def test_invalid_whatif_value_is_rejected_before_running(self) -> None:
        self.app.whatif.rows[0][2].insert(0, "1\nexplain total")
        self.app.whatif.run()
        self.assertIn("one line", self.status(self.app.whatif))
        self.assertFalse(self.app.runner.busy("whatif"))

    @unittest.skipUnless(CC, "no C compiler")
    def test_results_are_marked_stale_after_an_edit(self) -> None:
        self.app.explain.run()
        self.pump(lambda: self.status(self.app.explain).startswith("From the runtime"))
        self.app.editor.text.insert("end", "# edited\n")
        self.root.update()
        self.assertIn("source changed", self.status(self.app.explain))

    @unittest.skipUnless(CC, "no C compiler")
    def test_stop_cancels_a_running_build(self) -> None:
        lines = ["input x0 = 1"] + [f"let x{i} = x{i - 1} + 1" for i in range(1, 2500)] + ["show x2499"]
        self.replace_source("\n".join(lines) + "\n")
        self.app.run()
        self.pump(lambda: self.app.runner.busy("run"))
        self.app.stop()
        self.pump(lambda: self.app.last_run is not None)
        self.assertEqual(self.app.last_run.stage, "cancelled")
        self.assertIn("■ Stopped.", self.app.console.contents())
        self.assertIn("disabled", self.app.stop_button.state())
        self.assertNotIn("disabled", self.app.run_button.state())


if __name__ == "__main__":
    unittest.main()
