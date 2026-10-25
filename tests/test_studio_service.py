"""CAUSA Studio service layer (studio/service.py): file handling, query programs,
value validation, the dependency graph, process handling and end-to-end runs
through the real compiler, C compiler and runtime."""

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from causa.frontend import compile_to_ir, read_source
from studio.service import (Cancelled, Graph, Job, Runner, Session, binding_statement, check_literal,
                            parse_impact_report, parse_whatif_report, query_source, read_file,
                            runtime_diagnostics, whatif_statement, write_file)
from test_codegen import CC

ROOT = Path(__file__).resolve().parent.parent
PRICING = read_file(ROOT / "examples" / "pricing.cau")
SPEC_OUTPUT = (ROOT / "docs" / "language-specification.md").read_text(encoding="utf-8") \
    .split("Required stdout")[1].split("```")[1].lstrip("\n")


def pricing_graph() -> Graph:
    return Graph.from_module(compile_to_ir(PRICING, "pricing.cau"))


def alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class FileTests(unittest.TestCase):
    def test_save_and_reopen_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.cau"
            text = "# naïve comment\ninput x = 1\nlet y = x * 2\nshow y\n"
            write_file(path, text)
            self.assertEqual(path.read_bytes(), text.encode("utf-8"))  # LF line ends, UTF-8
            self.assertEqual(read_file(path), text)

    def test_crlf_files_are_normalized_for_editing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "w.cau"
            path.write_bytes(b"input x = 1\r\nshow x\r\n")
            self.assertEqual(read_file(path), "input x = 1\nshow x\n")
            self.assertEqual(path.read_bytes(), b"input x = 1\r\nshow x\r\n")  # reading never rewrites

    def test_invalid_utf8_is_a_causa_error(self) -> None:
        from causa.diagnostics import CausaError
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.cau"
            path.write_bytes(b"input x = 1\n\xff\n")
            with self.assertRaises(CausaError) as cm:
                read_file(path)
            self.assertEqual((cm.exception.code, cm.exception.line), ("E101", 2))


class QueryProgramTests(unittest.TestCase):
    def test_declarations_keep_their_lines(self) -> None:
        q = query_source(PRICING, ["explain total"])
        original, query = PRICING.split("\n"), q.split("\n")
        for number, line in enumerate(original, start=1):
            if line.startswith(("input ", "let ")):
                self.assertEqual(query[number - 1], line, number)
            elif line.startswith(("show", "explain", "whatif", "impact", "assert")):
                self.assertEqual(query[number - 1], "", number)
        self.assertTrue(q.endswith("\nexplain total\n"))
        compile_to_ir(q)  # still a valid program

    def test_source_without_final_newline(self) -> None:
        self.assertEqual(query_source("input x = 1\nshow x", ["impact x"]), "input x = 1\nimpact x\n")

    def test_values_must_be_single_literals(self) -> None:
        for good in ("160", "-2.5", "0.5", "true", "false", " 7 ", "1.0e3"):
            self.assertEqual(check_literal(good), good.strip())
        for bad in ("", "  ", "abc", "1 + 2", "1\nexplain total", "1\rshow x", "1 show total", "1, price = 2",
                    "# x", "007", "1 2"):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                check_literal(bad)

    def test_statements_are_built_only_from_known_names(self) -> None:
        g = pricing_graph()
        self.assertEqual(binding_statement(g, "explain", "total"), "explain total")
        self.assertEqual(binding_statement(g, "impact", "price"), "impact price")
        self.assertEqual(whatif_statement(g, [("price", "160"), ("discount", " 0.5")]),
                         "whatif price = 160, discount = 0.5")
        for verb, name in (("explain", "nope"), ("impact", "total; rm"), ("show", "total")):
            with self.assertRaises(ValueError):
                binding_statement(g, verb, name)
        for overrides in ([], [("total", "1")], [("missing", "1")], [("price", "1\nexplain total")]):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                whatif_statement(g, overrides)


class GraphTests(unittest.TestCase):
    def test_edges_point_from_dependency_to_dependent(self) -> None:
        g = pricing_graph()
        edges = set(g.edges)
        self.assertIn(("price", "savings"), edges)
        self.assertIn(("savings", "subtotal"), edges)
        self.assertNotIn(("savings", "price"), edges)
        expected = {(dep, b.name) for b in compile_to_ir(PRICING).provenance.bindings for dep in b.direct_deps}
        self.assertEqual(edges, expected)

    def test_upstream_and_downstream_come_from_provenance(self) -> None:
        g = pricing_graph()
        self.assertEqual(g.upstream["subtotal"], ("price", "discount", "savings"))
        self.assertEqual(g.downstream["total"], ("expensive", "per_unit", "bulk"))
        self.assertEqual([b.name for b in g.inputs], ["price", "discount", "tax", "fee", "units"])

    def test_source_dependencies_survive_optimization(self) -> None:
        g = Graph.from_module(compile_to_ir("input x = 3\nlet y = x * 0\nlet w = x - x\n"))
        self.assertEqual(set(g.edges), {("x", "y"), ("x", "w")})  # x * 0 still depends on x

    def test_layout_columns_follow_dependency_depth(self) -> None:
        from studio.graph import layout
        positions = layout(pricing_graph())
        self.assertEqual(positions["price"][0], 0)
        self.assertEqual(positions["savings"][0], 1)
        self.assertEqual(positions["bulk"][0], 5)
        for dep, name in pricing_graph().edges:
            self.assertLess(positions[dep][0], positions[name][0])


class ReportParsingTests(unittest.TestCase):
    def test_whatif_rows(self) -> None:
        report = ("whatif units = 0\n  units: 4 -> 0  (override)\n"
                  "  per_unit: 22.09375 -> error[R101] at 14:22 (division by zero)\n"
                  "  bulk: true -> unavailable (depends on per_unit)\n  total: 1.0 -> 2.0\n  x: 1 -> 1  (unchanged)\n")
        self.assertEqual(parse_whatif_report(report), [
            ("units", "4", "0", "override"),
            ("per_unit", "22.09375", "error[R101] at 14:22 (division by zero)", "failed"),
            ("bulk", "true", "unavailable (depends on per_unit)", "unavailable"),
            ("total", "1.0", "2.0", "changed"), ("x", "1", "1", "same value")])

    def test_impact_lists(self) -> None:
        report = "impact total\n  direct dependents: expensive, per_unit\n  all dependents: expensive, per_unit, bulk\n"
        self.assertEqual(parse_impact_report(report), (["expensive", "per_unit"], ["expensive", "per_unit", "bulk"]))

    def test_runtime_diagnostics_are_located(self) -> None:
        stderr = ("my file.cau:14:22: runtime error[R101]: division by zero\n"
                  "my file.cau:18:1: assertion failed: total >= 0\n  total = -1.0\n"
                  "my file.cau: argument error[A106]: 'x' is not a valid value for input 'units'\n")
        found = [(d.kind, d.line, d.column, d.code) for d in runtime_diagnostics(stderr, "my file.cau")]
        self.assertEqual(found, [("runtime", 14, 22, "R101"), ("assertion", 18, 1, None), ("argument", None, None,
                                                                                            "A106")])


class ProcessTests(unittest.TestCase):
    def test_arguments_are_passed_without_a_shell(self) -> None:
        tricky = ['a b', '"quoted"', "& echo injected", "$(whoami)", "%PATH%", "x;y|z"]
        code, out, _, _ = Job().run([sys.executable, "-c", "import sys; print(repr(sys.argv[1:]))", *tricky])
        self.assertEqual(code, 0)
        self.assertEqual(out.decode().strip(), repr(tricky))

    def test_cancel_before_start_runs_nothing(self) -> None:
        job = Job()
        job.cancel()
        with self.assertRaises(Cancelled):
            job.run([sys.executable, "-c", "raise SystemExit(5)"])

    def test_cancel_kills_the_whole_process_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "child.pid"
            script = ("import subprocess, sys, time\n"
                      "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
                      f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
                      "time.sleep(120)\n")
            job, errors = Job(), []

            def work() -> None:
                try:
                    job.run([sys.executable, "-c", script])
                except Cancelled:
                    errors.append("cancelled")

            thread = threading.Thread(target=work)
            thread.start()
            deadline = time.time() + 30
            while not (pid_file.exists() and pid_file.read_text()):
                self.assertLess(time.time(), deadline, "child never started")
                time.sleep(0.05)
            child = int(pid_file.read_text())
            self.assertTrue(alive(child))
            job.cancel()
            thread.join(30)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, ["cancelled"])
            deadline = time.time() + 10
            while alive(child) and time.time() < deadline:
                time.sleep(0.05)
            self.assertFalse(alive(child), "grandchild process survived cancellation")


class RunnerTests(unittest.TestCase):
    def test_stale_results_are_dropped(self) -> None:
        runner, release = Runner(), threading.Event()

        def slow(job, value):
            release.wait(10)
            return value

        first = runner.submit("run", slow, "old")
        second = runner.submit("run", lambda job, value: value, "new")
        deadline, got = time.time() + 10, []
        while not got and time.time() < deadline:
            got = runner.poll()
            time.sleep(0.01)
        release.set()
        time.sleep(0.2)
        got += runner.poll()
        self.assertEqual([(c, r, o) for c, r, o in got], [("run", second, "new")])
        self.assertNotEqual(first, second)
        self.assertFalse(runner.busy("run"))

    def test_channels_are_independent(self) -> None:
        runner = Runner()
        runner.submit("explain", lambda job: "e")
        runner.submit("impact", lambda job: "i")
        deadline, got = time.time() + 10, []
        while len(got) < 2 and time.time() < deadline:
            got += runner.poll()
            time.sleep(0.01)
        self.assertEqual(sorted(o for _, _, o in got), ["e", "i"])

    def test_exceptions_become_internal_diagnostics(self) -> None:
        runner = Runner()
        runner.submit("run", lambda job: 1 / 0)
        deadline, got = time.time() + 10, []
        while not got and time.time() < deadline:
            got = runner.poll()
            time.sleep(0.01)
        self.assertEqual(got[0][2].diagnostics[0].kind, "internal")


class MissingCompilerTests(unittest.TestCase):
    def test_no_c_compiler(self) -> None:
        session = Session(cc="")
        try:
            outcome = session.run(Job(), PRICING, "pricing.cau")
        finally:
            session.close()
        self.assertEqual((outcome.stage, outcome.ok), ("build", False))
        self.assertIn("No C compiler found", outcome.diagnostics[0].message)
        self.assertIsNotNone(outcome.graph)  # the front end still works without a C compiler
        self.assertIsNone(session.compiler_version())
        self.assertIsNone(session._dir)  # nothing was built, so no temporary directory was created

    def test_c_compiler_that_cannot_start(self) -> None:
        session = Session(cc=str(Path(tempfile.gettempdir()) / "no-such-dir" / "gcc.exe"))
        try:
            outcome = session.run(Job(), PRICING, "pricing.cau")
        finally:
            session.close()
        self.assertEqual(outcome.stage, "build")
        self.assertIn("cannot start", outcome.diagnostics[0].message)

    def test_front_end_needs_no_c_compiler(self) -> None:
        session = Session(cc="")
        try:
            good = session.analyze(PRICING, "pricing.cau")
            bad = session.analyze("input x = 1\nlet y = x + true\n", "f.cau")
        finally:
            session.close()
        self.assertTrue(good.ok)
        self.assertEqual(len(good.graph.bindings), 11)
        d = bad.diagnostics[0]
        self.assertEqual((d.kind, d.code, d.line, d.column), ("compile", "E401", 2, 11))
        self.assertEqual(d.message, "f.cau:2:11: error[E401]: operator '+' requires numeric operands, "
                                    "found int and bool")


@unittest.skipUnless(CC, "no C compiler found (set CAUSA_CC to enable)")
class EndToEndTests(unittest.TestCase):
    """Real compiler, real GCC, real runtime."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = Session()

    @classmethod
    def tearDownClass(cls) -> None:
        directory = cls.session.dir
        cls.session.close()
        assert not directory.exists()

    def test_run_matches_the_specification(self) -> None:
        o = self.session.run(Job(), PRICING, "pricing.cau")
        self.assertEqual((o.stage, o.ok, o.exit_code, o.stderr), ("run", True, 0, ""))
        self.assertEqual(o.stdout, SPEC_OUTPUT)
        self.assertEqual(set(o.timings), {"compile", "build", "run"})
        # per-run files are removed; only the shared runtime object stays in the session directory
        self.assertEqual([p.name for p in self.session.dir.iterdir()], ["causa_runtime.o"])

    def test_compile_error_location(self) -> None:
        o = self.session.run(Job(), "input x = 1\nshow y\n", "f.cau")
        d = o.diagnostics[0]
        self.assertEqual((o.stage, d.code, d.line, d.column), ("compile", "E301", 2, 6))

    def test_syntax_error_location(self) -> None:
        o = self.session.run(Job(), "input x = 1\nlet y = (x + 1\n", "f.cau")
        self.assertEqual((o.stage, o.diagnostics[0].code, o.diagnostics[0].line), ("compile", "E201", 2))

    def test_runtime_error_and_exit_code(self) -> None:
        o = self.session.run(Job(), PRICING, "pricing.cau", ("--set", "units=0"))
        self.assertEqual((o.stage, o.ok, o.exit_code, o.stdout), ("run", False, 2, ""))
        d = o.diagnostics[0]
        self.assertEqual((d.kind, d.code, d.line, d.column), ("runtime", "R101", 14, 22))

    def test_assertion_failure(self) -> None:
        o = self.session.run(Job(), "input x = -1\nassert x > 0\n", "f.cau")
        self.assertEqual((o.exit_code, o.diagnostics[0].kind, o.diagnostics[0].line), (1, "assertion", 2))
        self.assertEqual(o.stderr, "f.cau:2:1: assertion failed: x > 0\n  x = -1\n")

    def test_multiple_whatif_overrides(self) -> None:
        g = pricing_graph()
        o = self.session.query(Job(), PRICING, "pricing.cau", whatif_statement(g, [("price", "160"),
                                                                                   ("discount", "0.5")]))
        self.assertEqual(o.exit_code, 0)
        rows = parse_whatif_report(o.stdout)
        self.assertEqual(rows[0], ("price", "100", "160", "override"))
        self.assertEqual(rows[1], ("discount", "0.25", "0.5", "override"))
        self.assertIn(("total", "88.375", "94.0", "changed"), rows)
        self.assertEqual({r[0] for r in rows[2:]}, set(g.downstream["price"]) | set(g.downstream["discount"]))

    def test_whatif_type_rules_come_from_the_compiler(self) -> None:
        g = pricing_graph()
        o = self.session.query(Job(), PRICING, "pricing.cau", whatif_statement(g, [("price", "1.5")]))
        self.assertEqual((o.stage, o.diagnostics[0].code), ("compile", "E403"))
        o = self.session.query(Job(), PRICING, "pricing.cau", whatif_statement(g, [("tax", "1")]))
        self.assertEqual(o.stdout.splitlines()[0], "whatif tax = 1.0")  # int promoted for a float input (D15)
        o = self.session.query(Job(), PRICING, "pricing.cau", whatif_statement(g, [("price", "1"), ("price", "2")]))
        self.assertEqual(o.diagnostics[0].code, "E305")

    def test_explain_and_impact_queries(self) -> None:
        o = self.session.query(Job(), PRICING, "pricing.cau", "explain total")
        self.assertEqual(o.stdout, SPEC_OUTPUT.split("whatif price = 160")[0].split("\n", 1)[1])
        o = self.session.query(Job(), PRICING, "pricing.cau", "impact discount")
        self.assertEqual(parse_impact_report(o.stdout)[0], ["savings"])

    def test_query_keeps_runtime_error_locations(self) -> None:
        source = "input d = 0\nshow d\nlet q = 10 / d\n"
        o = self.session.query(Job(), source, "f.cau", "explain q")
        self.assertEqual((o.exit_code, o.diagnostics[0].line, o.diagnostics[0].column), (2, 3, 12))

    def test_cancelled_run(self) -> None:
        job = Job()
        job.cancel()
        o = self.session.run(job, PRICING, "pricing.cau")
        self.assertEqual(o.stage, "cancelled")
        big = "input x0 = 1\n" + "".join(f"let x{i} = x{i - 1} + 1\n" for i in range(1, 3000)) + "show x2999\n"
        job, result = Job(), []
        thread = threading.Thread(target=lambda: result.append(self.session.run(job, big, "big.cau")))
        thread.start()
        time.sleep(0.5)  # the compile of 3,000 lets takes several seconds
        job.cancel()
        thread.join(60)
        self.assertEqual(result[0].stage, "cancelled")
        self.assertEqual(sorted(p.name for p in self.session.dir.iterdir()), ["causa_runtime.o"])


if __name__ == "__main__":
    unittest.main()
