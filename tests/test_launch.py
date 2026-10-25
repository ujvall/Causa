"""Launch-argument tests (language-specification §9.5, decision D25).

Each program is compiled to C, built with a C compiler and executed with the
arguments under test; stdout, stderr and exit status are checked. A compiler is
taken from $CAUSA_CC, else gcc, clang or cc on PATH; without one these tests
are skipped. Spec cases L01-L21 are in tests/specification-cases.md §6c.
"""

import math
import os
import random
import re
import struct
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from causa.codegen import RUNTIME_DIR, RUNTIME_SOURCE, generate_c
from causa.diagnostics import CausaError
from causa.frontend import compile_to_c, compile_to_ir, read_source
from causa.parser import parse
from test_codegen import CC
from test_runtime import EXPECTED
from test_spec_cases import CASES, source_of

ROOT = Path(__file__).resolve().parent.parent
CFLAGS = ["-std=c99", "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-I", str(RUNTIME_DIR)]
PRICING = read_source(ROOT / "examples" / "pricing.cau")


def lines(*src: str) -> str:
    return "\n".join(src) + "\n"


def out(text: str) -> str:
    """Spec notation: ' / ' separates lines, '··' is two spaces of indentation."""
    return "".join(line.replace("··", "  ") + "\n" for line in text.split(" / ")) if text else ""


def S(*argv: str) -> tuple[str, ...]:
    return argv


PROGRAMS: dict[str, tuple[str, str]] = {  # name -> (C source, build mode: "runtime" | "header")
    "pricing": (compile_to_c(PRICING, "examples/pricing.cau").source, "runtime"),
    "pricing150": (compile_to_c(PRICING.replace("input price = 100", "input price = 150"),
                                "examples/pricing.cau").source, "runtime"),
    "sum": (compile_to_c(lines("input a = 1", "input b = 2", "let s = a + b", "show s"), "F").source, "runtime"),
    "f": (compile_to_c(lines("input f = 0.5", "show f"), "F").source, "runtime"),
    "n": (compile_to_c(lines("input n = 5", "show n"), "F").source, "runtime"),
    "m": (compile_to_c(lines("input m = true", "show m"), "F").source, "runtime"),
    "a": (compile_to_c(lines("input a = 1", "show a"), "F").source, "runtime"),
    "xs": (compile_to_c(lines("input x = 1", "let s = x + 1", "show s"), "F").source, "runtime"),
    "x": (compile_to_c(lines("input x = 1", "show x"), "F").source, "runtime"),
    "whatif": (compile_to_c(lines("input x = 1", "let y = x + 1", "whatif x = 10", "show y"), "F").source, "runtime"),
    "div": (compile_to_c(lines("input d = 2", "let q = 10 / d"), "F").source, "runtime"),
    "assert": (compile_to_c(lines("input x = 5", "assert x > 0"), "F").source, "runtime"),
    "zero": (compile_to_c(lines("input x = 3", "let z = x * 0 + x", "show z"), "F").source, "runtime"),
    "zero-unoptimized": (generate_c(compile_to_ir(lines("input x = 3", "let z = x * 0 + x", "show z"), "F")).source,
                         "runtime"),
    "header-only": (compile_to_c(lines("input d = 1", "let q = 10 / d"), "F", standalone=True).source, "header"),
}

DIV0 = "F:2:12: runtime error[R101]: division by zero\n"

# (case, program, arguments, expected): expected is (stdout, stderr, status), or ("ARG", code) for an
# argument error (stdout empty, one stderr line "F: argument error[CODE]: ...", status 3).
RUNS: list[tuple[str, str, tuple[str, ...], object]] = [
    ("L03", "sum", S("--set", "a=10", "--set", "b=20"), (out("s = 30"), "", 0)),
    ("L03", "sum", S("--set", "b=20", "--set", "a=10"), (out("s = 30"), "", 0)),
    ("L04", "f", S("--set", "f=2"), (out("f = 2.0"), "", 0)),
    ("L05", "n", S("--set", "n=1.5"), ("ARG", "A107")),
    ("L06", "m", S("--set", "m=1"), ("ARG", "A107")),
    ("L06", "m", S("--set", "m=false"), (out("m = false"), "", 0)),
    ("L07", "a", S("--set", "a=1", "--set", "a=2"), ("ARG", "A105")),
    ("L08", "xs", S("--set", "prise=1"), ("ARG", "A103")),
    ("L08", "xs", S("--set", "s=1"), ("ARG", "A104")),
    ("L09", "x", S("--set", "x="), ("ARG", "A102")),
    ("L09", "x", S("--set", "x"), ("ARG", "A102")),
    ("L09", "x", S("--set", "=1"), ("ARG", "A102")),
    ("L09", "x", S("--set"), ("ARG", "A102")),
    *[("L10", "x", S("--set", f"x={v}"), ("ARG", "A106")) for v in ("007", "1e5", "+5", "0x10", "nan", "inf", "True")],
    ("L11", "x", S("--set", "x=9223372036854775808"), ("ARG", "A108")),
    ("L11", "x", S("--set", "x=9223372036854775807"), (out("x = 9223372036854775807"), "", 0)),
    ("L11", "x", S("--set", "x=-9223372036854775807"), (out("x = -9223372036854775807"), "", 0)),
    ("L12", "f", S("--set", "f=1.0e400"), ("ARG", "A109")),
    ("L12", "f", S("--set", "f=1.0e-400"), (out("f = 0.0"), "", 0)),
    ("L13", "x", S("--sett", "x=1"), ("ARG", "A101")),
    ("L13", "x", S("x=1"), ("ARG", "A101")),
    ("L13", "x", S("-s"), ("ARG", "A101")),
    ("L14", "x", S("--set", "x=2", "--set", "bogus=1"), ("ARG", "A103")),
    ("L15", "whatif", S("--set", "x=5"),
     (out("whatif x = 10 / ··x: 5 -> 10  (override) / ··y: 6 -> 11 / y = 6"), "", 0)),
    ("L16", "div", S("--set", "d=0"), ("", DIV0, 2)),
    ("L17", "assert", S("--set", "x=-1"), ("", "F:2:1: assertion failed: x > 0\n  x = -1\n", 1)),
    ("L18", "zero", S("--set", "x=7"), (out("z = 7"), "", 0)),
    ("L18", "zero-unoptimized", S("--set", "x=7"), (out("z = 7"), "", 0)),
    ("L19", "f", S("--set", "f=-0.0"), (out("f = -0.0"), "", 0)),
    ("L20", "header-only", S("--set", "d=0"), ("", DIV0, 2)),
    ("L20", "header-only", S("--set", "d=5"), ("", "", 0)),
    ("L20", "header-only", S("--set", "d=x"), ("ARG", "A106")),
    # combinations not covered above: arguments are validated before anything runs
    ("extra", "sum", S("--set", "a=10", "--set", "b=1.5"), ("ARG", "A107")),
    ("extra", "sum", S("--set", "a=1", "--set", "b=2", "x"), ("ARG", "A101")),
    ("extra", "sum", S("--set=a=1"), ("ARG", "A101")),
    ("extra", "sum", S("--set", "a==1"), ("ARG", "A106")),
    ("extra", "sum", S("--set", "a=1", "--set", "a=x"), ("ARG", "A105")),  # duplicate found before the value
    ("extra", "f", S("--set", "f=99999999999999999999"), ("ARG", "A108")),  # range before type
    ("extra", "n", S("--set", "n=true"), ("ARG", "A107")),
]

LAUNCH_IDS = {f"L{i:02d}" for i in range(1, 22)}  # all specification L-cases, see test_specification_cases_present


def build(name: str, c_source: str, mode: str, runtime_obj: Path, work: Path) -> Path:
    c_file, exe = work / f"{name}.c", work / f"{name}.exe"
    c_file.write_text(c_source, encoding="utf-8")
    objects = [str(runtime_obj)] if mode == "runtime" else []
    result = subprocess.run([CC, *CFLAGS, str(c_file), *objects, "-o", str(exe), "-lm"], capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"{name}: C build failed:\n{result.stderr}")
    return exe


def run(exe: Path, args: tuple[str, ...]) -> tuple[str, str, int]:
    r = subprocess.run([str(exe), *args], capture_output=True, timeout=60)
    assert b"\r" not in r.stdout + r.stderr, "output lines must end in \\n only"
    return r.stdout.decode("utf-8"), r.stderr.decode("utf-8"), r.returncode


@unittest.skipUnless(CC, "no C compiler found (set CAUSA_CC to enable)")
class LaunchArgumentTests(unittest.TestCase):
    exes: dict[str, Path]

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.work = Path(cls._tmp.name)
        cls.runtime_obj = cls.work / "causa_runtime.o"
        b = subprocess.run([CC, *CFLAGS, "-c", str(RUNTIME_SOURCE), "-o", str(cls.runtime_obj)],
                           capture_output=True, text=True)
        if b.returncode != 0:
            raise AssertionError(b.stderr)
        with ThreadPoolExecutor(os.cpu_count() or 4) as pool:
            exes = pool.map(lambda item: build(item[0], item[1][0], item[1][1], cls.runtime_obj, cls.work),
                            PROGRAMS.items())
            cls.exes = dict(zip(PROGRAMS, exes))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def check(self, got: tuple[str, str, int], expected: object) -> None:
        if isinstance(expected, tuple) and expected[0] == "ARG":
            stdout, stderr, status = got
            self.assertEqual((stdout, status), ("", 3))
            self.assertRegex(stderr, rf"\AF: argument error\[{expected[1]}\]: [^\n]+\n\Z")
        else:
            self.assertEqual(got, expected)

    def test_specification_runs(self) -> None:
        for case, program, args, expected in RUNS:
            with self.subTest(case=case, program=program, args=" ".join(args)):
                self.check(run(self.exes[program], args), expected)

    def test_L01_no_arguments_is_unchanged(self) -> None:
        doc = (ROOT / "docs" / "language-specification.md").read_text(encoding="utf-8")
        required = doc.split("Required stdout")[1].split("```")[1].lstrip("\n")
        self.assertEqual(run(self.exes["pricing"], ()), (required, "", 0))

    def test_L02_launch_value_equals_edited_source(self) -> None:
        got = run(self.exes["pricing"], ("--set", "price=150"))
        self.assertEqual(got, run(self.exes["pricing150"], ()))
        stdout = got[0].splitlines()
        self.assertEqual(stdout[0], "total = 130.5625")
        self.assertIn("      price = 150  [input]", stdout)
        self.assertIn("  price: 150 -> 160  (override)", stdout)

    def test_L21_reproducible(self) -> None:
        args = ("--set", "price=150", "--set", "tax=0.2")
        self.assertEqual(run(self.exes["pricing"], args), run(self.exes["pricing"], args))

    def test_specification_cases_present(self) -> None:
        doc = (ROOT / "tests" / "specification-cases.md").read_text(encoding="utf-8")
        self.assertEqual(set(re.findall(r"^\| (L\d\d) \|", doc, re.MULTILINE)), LAUNCH_IDS)
        covered = {case for case, *_ in RUNS} | {"L01", "L02", "L21"}
        self.assertEqual(LAUNCH_IDS - covered, set())


def alternative(value: object) -> str:
    """A different CAUSA literal of the same type, for the equivalence oracle."""
    if isinstance(value, bool):
        return "false" if value else "true"
    if isinstance(value, int):
        return str(value - 3 if value > 2**63 - 10 else value + 3)
    v = float(value) * 2 + 0.5
    if not math.isfinite(v):
        v = float(value) / 2
    return f"{v:.17e}"


@unittest.skipUnless(CC, "no C compiler found (set CAUSA_CC to enable)")
class EquivalenceOracleTests(unittest.TestCase):
    """For every runtime specification program with inputs, running it with
    --set must give exactly the stdout, stderr and exit status of the same
    program with those input literals edited in the source."""

    def test_launch_values_match_edited_sources(self) -> None:
        jobs = []
        for case_id in EXPECTED:
            source = source_of(case_id, CASES[case_id][0])
            module = compile_to_ir(source, "F")
            inputs = [(b.name, module.node(b.anchor).value) for b in module.provenance.bindings
                      if b.kind.value == "input"]
            if not inputs:
                continue
            args, edited = [], source
            for name, value in inputs:
                text = alternative(value)
                args += ["--set", f"{name}={text}"]
                edited, count = re.subn(rf"(?m)^input {name} = .*$", f"input {name} = {text}", edited)
                self.assertEqual(count, 1, (case_id, name))
            jobs.append((case_id, source, edited, tuple(args)))
        self.assertGreater(len(jobs), 60)

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            runtime_obj = work / "causa_runtime.o"
            assert subprocess.run([CC, *CFLAGS, "-c", str(RUNTIME_SOURCE), "-o", str(runtime_obj)]).returncode == 0

            def one(job):
                case_id, source, edited, args = job
                launched = build(f"{case_id}-launch", compile_to_c(source, "F").source, "runtime", runtime_obj, work)
                literal = build(f"{case_id}-edited", compile_to_c(edited, "F").source, "runtime", runtime_obj, work)
                return case_id, args, run(launched, args), run(literal, ())

            with ThreadPoolExecutor(os.cpu_count() or 4) as pool:
                results = list(pool.map(one, jobs))
        for case_id, args, launched, literal in results:
            with self.subTest(case=case_id, args=" ".join(args)):
                self.assertEqual(launched, literal)


# ---- differential literal test: C causa_parse_literal vs the Python lexer -------

_ERROR_TO_LAUNCH = {"E101": "A106", "E102": "A106", "E201": "A106", "E203": "A106", "E103": "A108", "E104": "A109"}


def python_literal(text: str) -> tuple:
    """The compiler's verdict on `text` as an input's literal (the reference)."""
    try:
        (stmt,) = parse(f"input x = {text}\n").statements
    except CausaError as err:
        return ("ERR", _ERROR_TO_LAUNCH[err.code])
    literal = stmt.value
    if literal.type.value == "bool":
        return ("bool", bool(literal.value))
    if literal.type.value == "int":
        return ("int", int(literal.value))
    return ("float", struct.pack("<d", literal.value))


def corpus() -> list[str]:
    rng = random.Random(8)
    texts = {"0", "-0", "1", "-1", "007", "00", "01.5", "0.5", "-0.0", "0.0", "1.", ".5", "1e5", "1E5", "1.5e3",
             "1.5E-3", "1.5e+3", "1.5e", "1.5e+", "1.5e-", "1.5.2", "1..2", "1.5x", "+5", "--5", "-", "--", "0x10",
             "nan", "inf", "-inf", "NaN", "Infinity", "true", "false", "True", "FALSE", "-true", "tru", "truex",
             "_", "x", "1_000", "9223372036854775807", "9223372036854775808", "-9223372036854775807",
             "-9223372036854775808", "99999999999999999999", "123456789012345678901234567890", "1.0e308",
             "1.0e309", "1.0e400", "-1.0e400", "1.0e-400", "2.4703282292062328e-324", "1.7976931348623157e308",
             "1.7976931348623159e308", "1.0e99999999999999999999", "1.0e-99999999999999999999",
             "0.1", "0.30000000000000004", "123.456e-7", "4.9e-324", "5e-324", "1.0e00", "1.0e-0", "1(", ")",
             "1-2", "1+2", "1*2", "1=2", "=", "1,2", "1;"}
    alphabet = "0123456789.-+eE_xtrufalsTIn=,()"
    while len(texts) < 6000:
        texts.add("".join(rng.choice(alphabet) for _ in range(rng.randint(1, 10))))
    for _ in range(3000):  # well-formed values with random magnitudes
        texts.add(str(rng.randint(-(2**63) + 1, 2**63 - 1)))
        v = struct.unpack("<d", rng.getrandbits(64).to_bytes(8, "little"))[0]
        if math.isfinite(v):
            texts.add(f"{v:.{rng.randint(0, 17)}e}" if "." in f"{v:.1e}" else repr(v))
            texts.add(repr(v))
    return sorted(texts)


@unittest.skipUnless(CC, "no C compiler found (set CAUSA_CC to enable)")
class DifferentialLiteralTests(unittest.TestCase):
    HARNESS = r"""
#include "causa_runtime.h"
#include <inttypes.h>
const causa_program_info CAUSA_PROGRAM = { "h", 1, 0, NULL, 0, NULL, 0, NULL };
int causa_eval_node(int id, causa_value *env, causa_error *err) { (void)id; (void)env; (void)err; return 0; }
int main(int argc, char **argv)
{
    static char line[512];
    FILE *f = argc == 2 ? fopen(argv[1], "r") : NULL;
    causa_init();
    if (!f) return 4;
    while (fgets(line, sizeof line, f)) {
        int type = -1, code;
        causa_value v;
        line[strcspn(line, "\n")] = '\0';
        code = causa_parse_literal(line, &type, &v);
        if (code) printf("ERR A%d\n", code);
        else if (type == CAUSA_TYPE_INT) printf("int %" PRId64 "\n", v.i);
        else if (type == CAUSA_TYPE_FLOAT) printf("float %a\n", v.f);
        else printf("bool %s\n", v.b ? "true" : "false");
    }
    return 0;
}
"""

    def test_c_literal_parser_matches_python_lexer(self) -> None:
        texts = corpus()
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "h.c").write_text(self.HARNESS, encoding="utf-8")
            (d / "in.txt").write_text("".join(t + "\n" for t in texts), encoding="ascii")
            b = subprocess.run([CC, *CFLAGS, str(d / "h.c"), "-o", str(d / "h.exe"), "-lm"],
                               capture_output=True, text=True)
            self.assertEqual(b.returncode, 0, b.stderr)
            r = subprocess.run([str(d / "h.exe"), str(d / "in.txt")], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0)
        got = r.stdout.splitlines()
        self.assertEqual(len(got), len(texts))
        mismatches = []
        for text, line in zip(texts, got):
            kind, value = line.split(" ", 1)
            if kind == "ERR":
                c = ("ERR", value)
            elif kind == "int":
                c = ("int", int(value))
            elif kind == "float":
                c = ("float", struct.pack("<d", float.fromhex(value)))
            else:
                c = ("bool", value == "true")
            if c != python_literal(text):
                mismatches.append((text, c, python_literal(text)))
        self.assertEqual(mismatches[:10], [], f"{len(mismatches)} of {len(texts)} strings differ")
        accepted = sum(1 for line in got if not line.startswith("ERR"))
        self.assertGreater(accepted, 3000)  # the corpus exercises both acceptance and rejection
        self.assertGreater(len(got) - accepted, 3000)


if __name__ == "__main__":
    unittest.main()
