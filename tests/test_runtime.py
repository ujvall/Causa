"""End-to-end runtime tests (compiler-architecture §6.5, language-specification §8-§9).

Every program goes through the whole pipeline: front end, optimizer, C code
generator, a C compiler (with causa_runtime.c), and execution; stdout, stderr
and exit status are compared exactly. A C compiler is taken from $CAUSA_CC,
else gcc, clang or cc on PATH; without one these tests are skipped.
"""

import math
import os
import random
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from causa.codegen import RUNTIME_DIR, RUNTIME_SOURCE, generate_c
from causa.frontend import compile_to_c, compile_to_ir, read_source
from test_codegen import CC
from test_spec_cases import CASES, FILE_CASES, SEMANTIC_ERRORS, source_of

ROOT = Path(__file__).resolve().parent.parent
CFLAGS = ["-std=c99", "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-I", str(RUNTIME_DIR)]


def out(text: str) -> str:
    """Spec notation: ' / ' separates lines, '··' is two spaces of indentation."""
    return "".join(line.replace("··", "  ") + "\n" for line in text.split(" / ")) if text else ""


def err(text: str) -> str:
    return out(text)


DIV0 = "error[R101] at 2:12 (division by zero)"
H01_REPORT = f"whatif d = 0 / ··d: 2 -> 0  (override) / ··q: 5.0 -> {DIV0}"
NONE4 = "··direct dependencies: (none) / ··transitive dependencies: (none) / ··inputs: (none) / ··intermediates: (none)"

# case ID -> (stdout, stderr, exit status), transcribed from tests/specification-cases.md
EXPECTED: dict[str, tuple[str, str, int]] = {
    "V01": ("", "", 0), "V02": ("", "", 0),
    "V03": (out("y = 6"), "", 0), "V04": (out("y = 6"), "", 0), "V05": (out("y = 6"), "", 0),
    "V06": (out("c = 1.5"), "", 0),
    "V07": (out("q = 3.5 / r = 2.0"), "", 0),
    "V08": (out("x = 7 / y = 9"), "", 0),
    "V09": (out("x = 5 / y = 2.0"), "", 0),
    "V10": (out("x = -6 / y = 4"), "", 0),
    "V11": (out("b = true"), "", 0),
    "V12": (out("b = true"), "", 0),
    "V13": (out("b = true / c = false"), "", 0),
    "V14": (out("big = 1e+16 / small = 1e-05 / s = 0.30000000000000004"), "", 0),
    "V15": (out("z = -0.0 / e = true"), "", 0),
    "V16": (out("t = -5"), "", 0),
    "V17": (out("x = 3"), "", 0),
    "V18": (out("Price = 1"), "", 0),
    "V19": (out("showing = 1"), "", 0),
    "V20": (out("a = 1"), "", 0),
    "V21": (out("d = 0.2"), "", 0),
    "V24": (out("rate = 0"), "", 0),
    "X01": (out(f"explain p / ··p = 7  [input] / {NONE4}"), "", 0),
    "X02": (out(f"explain c / ··c = 5  [let: 5] / {NONE4}"), "", 0),
    "X03": (out("explain sq / ··sq = 9  [let: x * x] / ····x = 3  [input] / ··direct dependencies: x / "
                "··transitive dependencies: x / ··inputs: x / ··intermediates: (none)"), "", 0),
    "X04": (out("explain r / ··r = 8  [let: p + q] / ····p = 4  [let: a + a] / ······a = 2  [input] / "
                "····q = 4  [let: a * 2] / ······a = 2  [input, see above] / ··direct dependencies: p, q / "
                "··transitive dependencies: a, p, q / ··inputs: a / ··intermediates: p, q"), "", 0),
    "X05": (out("explain d / ··d = 6  [let: b + c] / ····b = 2  [let: a + 1] / ······a = 1  [input] / "
                "····c = 4  [let: b * 2] / ······b = 2  [let, see above] / ··direct dependencies: b, c / "
                "··transitive dependencies: a, b, c / ··inputs: a / ··intermediates: b, c"), "", 0),
    "X06": (out("explain y / ··y = 1  [let: x] / ····x = 1  [input] / ··direct dependencies: x / "
                "··transitive dependencies: x / ··inputs: x / ··intermediates: (none)"), "", 0),
    "X07": (out("explain y / ··y = 2  [let: x   +  1] / ····x = 1  [input] / ··direct dependencies: x / "
                "··transitive dependencies: x / ··inputs: x / ··intermediates: (none)"), "", 0),
    "W01": (out("whatif x = 7 / ··x: 3 -> 7  (override) / ··z: 0 -> 0  (unchanged)"), "", 0),
    "W02": (out("whatif a = 5 / ··a: 1 -> 5  (override) / ··(no dependent bindings)"), "", 0),
    "W03": (out("whatif x = 10 / ··x: 1 -> 10  (override) / ··y: 2 -> 11 / y = 2"), "", 0),
    "W04": (out("whatif x = 10 / ··x: 1 -> 10  (override) / ··y: 2 -> 20 / whatif k = 3 / "
                "··k: 2 -> 3  (override) / ··y: 2 -> 3"), "", 0),
    "W05": (out("whatif x = 2 / ··x: 1 -> 2  (override) / ··a: 2 -> 3 / b = 3"), "", 0),
    "W06": (out("whatif x = 4 / ··x: 4 -> 4  (override) / ··y: 8 -> 8  (unchanged)"), "", 0),
    "W07": (out("whatif t = -1 / ··t: 5 -> -1  (override) / ··u: 10 -> -2"), "", 0),
    "W08": (out("whatif member = false / ··member: true -> false  (override) / ··pays: false -> true"), "", 0),
    "W09": (out("whatif a = 10 / ··a: 1 -> 10  (override) / ··s: 3 -> 12"), "", 0),
    "W10": (out("whatif z = -0.0 / ··z: 0.0 -> -0.0  (override) / ··w: 0.0 -> -0.0"), "", 0),
    "W11": (out("whatif d = 0.5 / ··d: 0.2 -> 0.5  (override) / ··(no dependent bindings)"), "", 0),
    "W12": (out("whatif a = 2 / ··a: 1 -> 2  (override) / ··b: 2 -> 4 / ··d: 9 -> 11"), "", 0),
    "P01": (out("whatif d = 1.0 / ··d: 0.25 -> 1.0  (override) / ··h: 0.5 -> 2.0"), "", 0),
    "P02": (out("whatif d = -3.0 / ··d: 0.5 -> -3.0  (override) / ··(no dependent bindings)"), "", 0),
    "P03": (out("whatif r = 2.0 / ··r: 2.0 -> 2.0  (override) / ··s: 6.0 -> 6.0  (unchanged)"), "", 0),
    "P04": (out("whatif f = 9007199254740992.0 / ··f: 0.5 -> 9007199254740992.0  (override) / "
                "··(no dependent bindings)"), "", 0),
    "H01": (out(f"q = 5.0 / {H01_REPORT}"), "", 0),
    "H02": (out(f"whatif d = 0 / ··d: 2 -> 0  (override) / ··q: 5.0 -> {DIV0} / "
                "··r: 6.0 -> unavailable (depends on q) / ··s: 12.0 -> unavailable (depends on q)"), "", 0),
    "H03": (out(f"{H01_REPORT} / q = 5.0 / whatif d = 5 / ··d: 2 -> 5  (override) / ··q: 5.0 -> 2.0"), "", 0),
    "H04": (out(f"{H01_REPORT} / ··w: 3 -> 1"), "", 0),
    "H05": (out("whatif n = 2 / ··n: 1 -> 2  (override) / "
                "··m: 9223372036854775807 -> error[R102] at 2:11 (integer overflow)"), "", 0),
    "H06": (out("whatif f = 10.0 / ··f: 1.0 -> 10.0  (override) / "
                "··g: 1e+308 -> error[R103] at 2:11 (non-finite float result)"), "", 0),
    "H07": (out("whatif d = 0 / ··d: 1 -> 0  (override) / ··a: 1.0 -> error[R101] at 2:11 (division by zero) / "
                "··b: 2.0 -> error[R101] at 3:11 (division by zero) / ··c: 3.0 -> unavailable (depends on a)"), "", 0),
    "H08": (out("whatif d = 0 / ··d: 1 -> 0  (override) / ··ok: false -> error[R101] at 2:22 (division by zero)"),
            "", 0),
    "H09": (out(f"{H01_REPORT} / q = 5.0"), "", 0),
    "H10": (out(H01_REPORT), err("F:4:11: runtime error[R101]: division by zero"), 2),
    "H11": ("", err("F:2:11: runtime error[R101]: division by zero"), 2),
    "T01": (out("whatif x = 5 show z / ··z: 4 -> 12"), "", 0),
    "T02": (out("whatif x = 5 show y / ··y: 2 -> 6"), "", 0),
    "T03": (out("whatif x = 7 show z / ··z: 0 -> 0  (unchanged)"), "", 0),
    "T04": (out("whatif x = 5 show y / ··y: 2 -> 6 / y = 2"), "", 0),
    "T05": (out("whatif d = 0 show r / ··r: 6.0 -> unavailable (depends on q)"), "", 0),
    "T06": (out(f"whatif d = 0 show q / ··q: 5.0 -> {DIV0}"), "", 0),
    "T07": (out("whatif d = 0 show w / ··w: 3 -> 1"), "", 0),
    "T08": (out("whatif d = 1.0 show h / ··h: 0.5 -> 2.0"), "", 0),
    "I01": (out("impact a / ··direct dependents: (none) / ··all dependents: (none)"), "", 0),
    "I02": (out("impact x / ··direct dependents: a / ··all dependents: a"), "", 0),
    "I03": (out("impact x / ··direct dependents: z / ··all dependents: z"), "", 0),
    "I04": (out("impact b / ··direct dependents: c / ··all dependents: c, d"), "", 0),
    "I06": (out(f"{H01_REPORT} / impact d / ··direct dependents: q / ··all dependents: q"), "", 0),
    "I07": (out("impact x / ··direct dependents: (none) / ··all dependents: (none)"), "", 0),
    "R01": ("", err("F:2:11: runtime error[R101]: division by zero"), 2),
    "R02": ("", err("F:1:13: runtime error[R101]: division by zero"), 2),
    "R03": ("", err("F:2:13: runtime error[R102]: integer overflow"), 2),
    "R04": ("", err("F:2:11: runtime error[R103]: non-finite float result"), 2),
    "R05": ("", err("F:3:9: runtime error[R102]: integer overflow"), 2),
    "R06": (out("a = 1"), err("F:3:11: runtime error[R101]: division by zero"), 2),
    "R07": ("", err("F:2:16: runtime error[R101]: division by zero"), 2),
    "R08": ("", err("F:1:21: runtime error[R101]: division by zero"), 2),
    "R09": ("", err("F:2:11: runtime error[R101]: division by zero"), 2),
    "R11": ("", err("F:3:1: assertion failed: y >= 0 / ··y = -5"), 1),
    "R12": (out("whatif x = -5 / ··x: 1 -> -5  (override) / ··(no dependent bindings)"), "", 0),
}

# Additional programs (not specification cases): name -> (source lines, stdout, stderr, status)
EXTRA: dict[str, tuple[tuple[str, ...], str, str, int]] = {
    "isolation-many-whatifs": (
        ("input x = 1", "input y = 2.5", "let s = x * y", "let ok = s > 2.0",
         "whatif x = 0", "show s", "whatif y = 0.0 show s", "whatif x = 4 show ok", "show s", "show ok"),
        out("whatif x = 0 / ··x: 1 -> 0  (override) / ··s: 2.5 -> 0.0 / ··ok: true -> false / s = 2.5 / "
            "whatif y = 0.0 show s / ··s: 2.5 -> 0.0 / whatif x = 4 show ok / ··ok: true -> true  (unchanged) / "
            "s = 2.5 / ok = true"), "", 0),
    "failed-then-successful-whatif": (
        ("input d = 4", "let q = 8 / d", "let r = q * 2.0", "whatif d = 0", "whatif d = 2", "explain r"),
        # explicit lines: the source text "8 / d" contains the ' / ' separator used by out()
        "whatif d = 0\n  d: 4 -> 0  (override)\n  q: 2.0 -> error[R101] at 2:11 (division by zero)\n"
        "  r: 4.0 -> unavailable (depends on q)\nwhatif d = 2\n  d: 4 -> 2  (override)\n  q: 2.0 -> 4.0\n"
        "  r: 4.0 -> 8.0\nexplain r\n  r = 4.0  [let: q * 2.0]\n    q = 2.0  [let: 8 / d]\n"
        "      d = 4  [input]\n  direct dependencies: q\n  transitive dependencies: d, q\n  inputs: d\n"
        "  intermediates: q\n", "", 0),
    "strict-or-in-whatif": (
        ("input d = 1", "let t = true or 1 / d > 0", "whatif d = 0 show t"),
        out("whatif d = 0 show t / ··t: true -> error[R101] at 2:19 (division by zero)"), "", 0),
    "impact-multiple-paths": (
        ("input a = 1", "input b = 2", "let c = a + b", "let d = a * a + c", "let e = d - d", "impact a", "impact c"),
        out("impact a / ··direct dependents: c, d / ··all dependents: c, d, e / "
            "impact c / ··direct dependents: d / ··all dependents: d, e"), "", 0),
    "explain-distinct-equal-bindings": (
        ("input a = 3", "let p = a + 1", "let q = a + 1", "let r = q - p", "explain r"),
        out("explain r / ··r = 0  [let: q - p] / ····q = 4  [let: a + 1] / ······a = 3  [input] / "
            "····p = 4  [let: a + 1] / ······a = 3  [input, see above] / ··direct dependencies: p, q / "
            "··transitive dependencies: a, p, q / ··inputs: a / ··intermediates: p, q"), "", 0),
    "assert-several-refs-after-output": (
        ("input f = 0.5", "input n = -2", "show f", "assert f > 1.0 or n * n == 5 or f > 2.0", "show n"),
        out("f = 0.5"), err("F:4:1: assertion failed: f > 1.0 or n * n == 5 or f > 2.0 / ··f = 0.5 / ··n = -2"), 1),
    "assert-passes-and-folded-condition": (
        ("input x = 1", "assert x > 0", "assert 1 < 2", "show x"), out("x = 1"), "", 0),
    "float-values": (
        ("input a = 1.0e16", "input b = 0.0001", "input c = 123456.789", "let d = a * 10.0", "let e = b / 10.0",
         "let f = 1.0 / 3.0", "let g = -c", "show a", "show b", "show c", "show d", "show e", "show f", "show g"),
        out("a = 1e+16 / b = 0.0001 / c = 123456.789 / d = 1e+17 / e = 1e-05 / f = 0.3333333333333333 / "
            "g = -123456.789"), "", 0),
    "int-extremes": (
        ("input m = -9223372036854775807", "let n = m - 1", "input p = 9223372036854775807", "show n", "show p"),
        out("n = -9223372036854775808 / p = 9223372036854775807"), "", 0),
}


def _build_and_run(job: tuple[str, str, Path, Path]) -> tuple[str, subprocess.CompletedProcess]:
    name, c_source, runtime_obj, work = job
    c_file, exe = work / f"{name}.c", work / f"{name}.exe"
    c_file.write_text(c_source, encoding="utf-8")
    build = subprocess.run([CC, *CFLAGS, str(c_file), str(runtime_obj), "-o", str(exe), "-lm"],
                           capture_output=True, text=True)
    if build.returncode != 0:
        return name, build  # reported by the test as a build failure
    return name, subprocess.run([str(exe)], capture_output=True, timeout=60)


@unittest.skipUnless(CC, "no C compiler found (set CAUSA_CC to enable)")
class EndToEndTests(unittest.TestCase):
    runs: dict[str, subprocess.CompletedProcess]

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        work = Path(cls._tmp.name)
        runtime_obj = work / "causa_runtime.o"
        build = subprocess.run([CC, *CFLAGS, "-c", str(RUNTIME_SOURCE), "-o", str(runtime_obj)],
                               capture_output=True, text=True)
        if build.returncode != 0:
            raise AssertionError(f"causa_runtime.c does not compile:\n{build.stderr}")
        jobs = [(case_id, compile_to_c(source_of(case_id, CASES[case_id][0]), "F").source, runtime_obj, work)
                for case_id in EXPECTED]
        # The same programs generated from unoptimized IR (spec case IR08).
        jobs += [(f"{case_id}-unoptimized", generate_c(compile_to_ir(source_of(case_id, CASES[case_id][0]), "F")).source,
                  runtime_obj, work) for case_id in EXPECTED]
        jobs += [(name, compile_to_c("\n".join(lines) + "\n", "F").source, runtime_obj, work)
                 for name, (lines, *_rest) in EXTRA.items()]
        for name in ("minimal.cau", "pricing.cau"):
            text = read_source(ROOT / "examples" / name)
            jobs.append((name, compile_to_c(text, f"examples/{name}").source, runtime_obj, work))
        jobs.append(("pricing-again", compile_to_c(read_source(ROOT / "examples" / "pricing.cau"),
                                                   "examples/pricing.cau").source, runtime_obj, work))
        with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
            cls.runs = dict(pool.map(_build_and_run, jobs))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def check(self, name: str, stdout: str, stderr: str, status: int) -> None:
        run = self.runs[name]
        if isinstance(run.stdout, str):  # a build failure
            self.fail(f"{name}: C build failed:\n{run.stderr}")
        self.assertNotIn(b"\r", run.stdout + run.stderr, "output lines must end in \\n only")
        self.assertEqual((run.stdout.decode("utf-8"), run.stderr.decode("utf-8"), run.returncode),
                         (stdout, stderr, status))

    def test_specification_cases(self) -> None:
        for case_id, expected in EXPECTED.items():
            with self.subTest(case=case_id):
                self.check(case_id, *expected)

    def test_optimization_does_not_change_behavior(self) -> None:
        """Spec case IR08: identical stdout, stderr and exit status with and without
        optimization, for every runtime case."""
        for case_id, expected in EXPECTED.items():
            with self.subTest(case=case_id):
                self.check(f"{case_id}-unoptimized", *expected)

    def test_every_runtime_case_is_covered(self) -> None:
        """Every specification case that passes the front end has an exact
        expected outcome here; compile-time error cases are tested elsewhere."""
        compile_errors = {cid for cid, (_, exp) in CASES.items()
                          if cid in SEMANTIC_ERRORS or (isinstance(exp, tuple) and exp[0] != "sem")}
        self.assertEqual(set(CASES) - compile_errors, set(EXPECTED))

    def test_pricing_matches_language_specification_section_12(self) -> None:
        doc = (ROOT / "docs" / "language-specification.md").read_text(encoding="utf-8")
        required = doc.split("Required stdout")[1].split("```")[1].lstrip("\n")
        for name in ("pricing.cau", "pricing-again"):  # X08, W13, T09, I05, V23; deterministic
            with self.subTest(run=name):
                self.check(name, required, "", 0)
        self.assertEqual(set(FILE_CASES) - {"V22", "E43"}, {"V23", "X08", "W13", "T09", "I05"})

    def test_minimal_example(self) -> None:  # V22
        self.check("minimal.cau", out("y = 6"), "", 0)

    def test_additional_programs(self) -> None:
        for name, (_lines, stdout, stderr, status) in EXTRA.items():
            with self.subTest(program=name):
                self.check(name, stdout, stderr, status)


@unittest.skipUnless(CC, "no C compiler found (set CAUSA_CC to enable)")
class FloatFormattingTests(unittest.TestCase):
    """causa_format_value must print every finite double exactly as Python's repr."""

    HARNESS = r"""
#include "causa_runtime.h"
const causa_program_info CAUSA_PROGRAM = { "h", 1, 0, NULL, 0, NULL, 0, NULL };
int causa_eval_node(int id, causa_value *env, causa_error *err) { (void)id; (void)env; (void)err; return 0; }
int main(int argc, char **argv)
{
    char line[128], text[CAUSA_VALUE_BUFSIZE];
    FILE *f = fopen(argv[1], "r");
    (void)argc;
    causa_init();
    if (!f) return 3;
    while (fgets(line, sizeof line, f)) {
        causa_value v;
        v.f = strtod(line, NULL); /* hexadecimal input: exact */
        causa_format_value(CAUSA_TYPE_FLOAT, v, text, sizeof text);
        puts(text);
    }
    return 0;
}
"""

    @staticmethod
    def sample() -> list[float]:
        rng = random.Random(6)
        values = {0.0, -0.0, 5e-324, -5e-324, 2.2250738585072014e-308, 2.225073858507201e-308,
                  1.7976931348623157e308, -1.7976931348623157e308, 0.1, 0.2, 0.30000000000000004, 1 / 3,
                  2.0 ** 53, 2.0 ** 53 + 2, 9007199254740993.0, 1e15, 1e16, 9999999999999998.0, 1e-4,
                  9.999999999999999e-05, 1e-05, 123456789012345678.0, 88.375, 22.09375, 1e22, 1e23, 5e-324 * 3}
        for e in range(-1074, 1024):  # powers of two: asymmetric rounding intervals
            values.update({math.ldexp(1.0, e), -math.ldexp(1.0, e)})
        for k in range(-325, 309):  # around every decimal exponent and the positional/scientific switch
            for m in (1.0, 9.999999999999999, 5.0):
                v = float(f"{m}e{k}")
                if math.isfinite(v):
                    values.update({v, math.nextafter(v, 0.0), math.nextafter(v, math.inf)})
        while len(values) < 30000:  # random bit patterns
            v = struct.unpack("<d", rng.getrandbits(64).to_bytes(8, "little"))[0]
            if math.isfinite(v):
                values.add(v)
        values.update(round(rng.uniform(-1e7, 1e7), rng.randint(0, 9)) for _ in range(5000))
        return sorted(values, key=repr)

    def test_matches_python_repr(self) -> None:
        values = self.sample()
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "fmt.c").write_text(self.HARNESS, encoding="utf-8")
            (d / "values.txt").write_text("".join(v.hex() + "\n" for v in values), encoding="ascii")
            build = subprocess.run([CC, *CFLAGS, str(d / "fmt.c"), str(RUNTIME_SOURCE), "-o", str(d / "fmt.exe"),
                                    "-lm"], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(d / "fmt.exe"), str(d / "values.txt")], capture_output=True, timeout=120)
        got = run.stdout.decode("ascii").split("\n")[:-1]
        self.assertEqual(len(got), len(values))
        mismatches = [(repr(v), g) for v, g in zip(values, got) if repr(v) != g]
        self.assertEqual(mismatches[:10], [], f"{len(mismatches)} of {len(values)} values differ")
        self.assertGreaterEqual(len(values), 35000)
        # Round trip: every printed text converts back to exactly the original bits.
        self.assertEqual([float(t).hex() for t in got], [v.hex() for v in values])


@unittest.skipUnless(CC, "no C compiler found (set CAUSA_CC to enable)")
class InstrumentedWhatifTests(unittest.TestCase):
    """Spec cases IR09 and IR11, observed through an instrumented harness:
    causa_eval_node is wrapped to record which nodes a whatif re-evaluates, and
    the base environment is compared bit for bit before and after."""

    PROGRAM = ("input a = 1", "input d = 2", "let b = a * 2", "let c = 7", "let q = 10 / d", "let e = b + c")
    HARNESS = r"""
#define CAUSA_NO_MAIN
#define causa_eval_node causa_eval_node_generated
#include "prog.c"
#undef causa_eval_node
#include <string.h>
static int calls[CAUSA_NODE_SLOTS];
int causa_eval_node(int node_id, causa_value *env, causa_error *err);
int causa_eval_node(int node_id, causa_value *env, causa_error *err)
{
    calls[node_id]++;
    return causa_eval_node_generated(node_id, env, err);
}
static void report(const char *label)
{
    int i;
    printf("%s:", label);
    for (i = 0; i < CAUSA_NODE_SLOTS; i++) {
        if (calls[i] == 1) printf(" %d", i);
        else if (calls[i] > 1) printf(" %d*%d", i, calls[i]); /* evaluated more than once */
    }
    printf("\n");
    memset(calls, 0, sizeof calls);
}
int main(void)
{
    static causa_value env[CAUSA_NODE_SLOTS], before[CAUSA_NODE_SLOTS];
    causa_error err;
    int i;
    causa_init();
    for (i = 0; i < CAUSA_PROGRAM.node_count; i++)
        if (causa_eval_node(CAUSA_PROGRAM.nodes[i].id, env, &err)) return 9;
    report("EVAL-base"); /* validates the instrumentation itself */
    memcpy(before, env, sizeof env);
    causa_whatif(env, CAUSA_BINDING_a, (causa_value){ .i = 2 }, CAUSA_NO_TARGET, CAUSA_PROGRAM.binding_count);
    report("EVAL-a");
    causa_whatif(env, CAUSA_BINDING_d, (causa_value){ .i = 0 }, CAUSA_NO_TARGET, CAUSA_PROGRAM.binding_count);
    report("EVAL-d");
    printf("BASE %s\n", memcmp(before, env, sizeof env) == 0 ? "unchanged" : "CHANGED");
    return 0;
}
"""

    def test_cone_only_and_base_untouched(self) -> None:
        program = compile_to_c("\n".join(self.PROGRAM) + "\n", "F")
        module = compile_to_ir("\n".join(self.PROGRAM) + "\n")
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "prog.c").write_text(program.source, encoding="utf-8")
            (d / "harness.c").write_text(self.HARNESS, encoding="utf-8")
            build = subprocess.run([CC, *CFLAGS, str(d / "harness.c"), str(RUNTIME_SOURCE), "-o", str(d / "h.exe"),
                                    "-lm"], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(d / "h.exe")], capture_output=True, text=True, timeout=30)
        self.assertEqual((run.returncode, run.stderr), (0, ""))
        lines = run.stdout.splitlines()
        owned = {}  # binding -> node IDs it owns (the optimizer does not change ownership)
        for node in module.nodes:
            owned.setdefault(node.owner, []).append(node.id)
        def evaluated(label: str) -> list[int]:
            fields = next(l for l in lines if l.startswith(label + ":")).split()[1:]
            self.assertNotIn("*", "".join(fields), f"{label}: a node was evaluated more than once")
            return [int(x) for x in fields]

        optimized_ids = {int(m) for m in re.findall(r"case (\d+):", program.source)}
        # The counting wrapper sees every node exactly once during base evaluation.
        self.assertEqual(evaluated("EVAL-base"), sorted(optimized_ids))
        eval_a, eval_d = evaluated("EVAL-a"), evaluated("EVAL-d")
        # whatif a = 2: only b and e (the cone) are re-evaluated; c, q and the inputs are reused.
        self.assertEqual(eval_a, sorted(i for i in owned["b"] + owned["e"] if i in optimized_ids))
        # whatif d = 0: only q, and evaluation stops at its failing division, so
        # q's bind node is never evaluated (LS §8.5.2: nothing is stored).
        q_nodes = sorted(i for i in owned["q"] if i in optimized_ids)
        q_bind = module.bindings["q"]
        self.assertEqual(eval_d, [i for i in q_nodes if i != q_bind])
        self.assertNotIn(q_bind, eval_d)
        self.assertIn("  q: 5.0 -> error[R101] at 5:12 (division by zero)", lines)
        self.assertIn("BASE unchanged", lines)


def build_and_run(files: dict[str, str], main: str, extra_flags: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    """Write `files` to a temporary directory, build `main` with the runtime, run it."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for name, text in files.items():
            (d / name).write_text(text, encoding="utf-8")
        build = subprocess.run([CC, *CFLAGS, str(d / main), str(RUNTIME_SOURCE), "-o", str(d / "p.exe"), "-lm",
                                *extra_flags], capture_output=True, text=True)
        if build.returncode != 0:
            raise AssertionError(f"C build failed:\n{build.stderr}")
        return subprocess.run([str(d / "p.exe")], capture_output=True, text=True, timeout=120)


@unittest.skipUnless(CC, "no C compiler found (set CAUSA_CC to enable)")
class MalformedMetadataTests(unittest.TestCase):
    """Corrupted generated tables must be rejected with an internal error before
    the runtime uses them (exit 2, nothing on stdout), never read blindly."""

    SOURCE = "input x = 1\nlet y = x + 1\nexplain y\n"
    LET_ROW = '{ "y", CAUSA_KIND_LET, CAUSA_TYPE_INT, 3, 2, 5, "x + 1",'
    CORRUPTIONS = [
        ("dependency index", "static const int causa_b1_deps[] = { CAUSA_BINDING_x };",
         "static const int causa_b1_deps[] = { 7 };", "F: internal error: malformed dependency metadata"),
        # Audit regressions: an invalid kind used to pass validation, after which explain
        # printed the NULL source text with %s; a NULL source file name was never checked.
        ("binding kind", LET_ROW, '{ "y", 7, CAUSA_TYPE_INT, 3, 2, 5, NULL,',
         "F: internal error: malformed binding metadata"),
        ("source file name", '    "F", CAUSA_NODE_SLOTS,', "    NULL, CAUSA_NODE_SLOTS,",
         "<unknown>: internal error: malformed program metadata"),
        ("binding name", LET_ROW, '{ NULL, CAUSA_KIND_LET, CAUSA_TYPE_INT, 3, 2, 5, "x + 1",',
         "F: internal error: malformed binding metadata"),
        ("anchor", LET_ROW, '{ "y", CAUSA_KIND_LET, CAUSA_TYPE_INT, 999, 2, 5, "x + 1",',
         "F: internal error: malformed binding metadata"),
        ("type tag", LET_ROW, '{ "y", CAUSA_KIND_LET, 9, 3, 2, 5, "x + 1",',
         "F: internal error: malformed binding metadata"),
    ]

    def test_corruptions_are_rejected(self) -> None:
        c = compile_to_c(self.SOURCE, "F").source
        for what, old, new, message in self.CORRUPTIONS:
            with self.subTest(corrupted=what):
                self.assertIn(old, c)
                run = build_and_run({"p.c": c.replace(old, new)}, "p.c")
                self.assertEqual((run.returncode, run.stdout, run.stderr), (2, "", message + "\n"))


@unittest.skipUnless(CC, "no C compiler found (set CAUSA_CC to enable)")
class WhatifRequestValidationTests(unittest.TestCase):
    """causa_whatif must reject an invalid request before printing anything.
    Audit regression: a target below CAUSA_NO_TARGET was silently treated as the
    full form, and a target outside the dependency cone was only detected after
    the header had been printed."""

    HARNESS = r"""
#define CAUSA_NO_MAIN
#include "prog.c"
int main(void)
{
    static causa_value env[CAUSA_NODE_SLOTS];
    causa_error err;
    int i;
    causa_init();
    for (i = 0; i < CAUSA_PROGRAM.node_count; i++)
        if (causa_eval_node(CAUSA_PROGRAM.nodes[i].id, env, &err)) return 9;
    causa_whatif(env, INPUT, (causa_value){ .i = 5 }, TARGET, VISIBLE);
    return 0;
}
"""

    def run_request(self, input_binding: str, target: str, visible: str) -> subprocess.CompletedProcess:
        c = compile_to_c("input x = 1\ninput k = 3\nlet y = x + 1\nwhatif x = 2\n", "F").source
        main = (self.HARNESS.replace("INPUT", input_binding).replace("TARGET", target)
                .replace("VISIBLE", visible))
        return build_and_run({"prog.c": c, "h.c": main}, "h.c")

    def test_invalid_requests(self) -> None:
        cases = [
            ("CAUSA_BINDING_x", "-5", "3", "invalid whatif request"),
            ("CAUSA_BINDING_x", "CAUSA_BINDING_k", "3", "whatif target does not depend on the input"),
            ("CAUSA_BINDING_x", "CAUSA_BINDING_y", "2", "invalid whatif request"),  # target not visible
            ("CAUSA_BINDING_k", "CAUSA_NO_TARGET", "1", "invalid whatif request"),  # input not visible
            ("CAUSA_BINDING_y", "CAUSA_NO_TARGET", "3", "invalid whatif request"),  # not an input
        ]
        for input_binding, target, visible, message in cases:
            with self.subTest(input=input_binding, target=target, visible=visible):
                run = self.run_request(input_binding, target, visible)
                self.assertEqual((run.returncode, run.stdout, run.stderr),
                                 (2, "", f"F: internal error: {message}\n"))

    def test_valid_requests_still_work(self) -> None:
        run = self.run_request("CAUSA_BINDING_x", "CAUSA_BINDING_y", "3")
        self.assertEqual((run.returncode, run.stdout, run.stderr), (0, "whatif x = 5 show y\n  y: 2 -> 6\n", ""))


@unittest.skipUnless(CC and sys.platform == "win32",
                     "needs a C compiler and the PE linker option --stack (Windows/MinGW)")
class DeepExplainTests(unittest.TestCase):
    """Audit regression: explain recursed once per dependency level and crashed
    with a stack overflow (STATUS_STACK_OVERFLOW) on a 20,000-binding chain.
    The executable is linked with a 64 KiB stack so that a recursive
    implementation overflows on this 2,000-level chain."""

    N = 2000

    def test_long_chain(self) -> None:
        n = self.N
        lines = ["input x0 = 1"] + [f"let x{i} = x{i - 1} + 1" for i in range(1, n)] + [f"explain x{n - 1}"]
        c = compile_to_c("\n".join(lines) + "\n", "F").source
        run = build_and_run({"p.c": c}, "p.c", ("-Wl,--stack,65536",))
        expected = [f"explain x{n - 1}"]
        for depth in range(n - 1):
            k = n - 1 - depth
            expected.append(f"{' ' * 2 * (depth + 1)}x{k} = {k + 1}  [let: x{k - 1} + 1]")
        expected.append(f"{' ' * 2 * n}x0 = 1  [input]")
        chain = ", ".join(f"x{i}" for i in range(n - 1))
        expected += [f"  direct dependencies: x{n - 2}", f"  transitive dependencies: {chain}", "  inputs: x0",
                     "  intermediates: " + ", ".join(f"x{i}" for i in range(1, n - 1))]
        self.assertEqual((run.returncode, run.stderr), (0, ""))
        self.assertEqual(run.stdout, "\n".join(expected) + "\n")


if __name__ == "__main__":
    unittest.main()
