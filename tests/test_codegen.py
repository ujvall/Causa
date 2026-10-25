"""C code generator tests (compiler-architecture §6.4).

Static tests always run. Tests marked "needs a C compiler" compile and run the
generated C; they use $CAUSA_CC, else gcc, clang or cc from PATH, and are
skipped (never failed) when none is available.
"""

import contextlib
import io
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from causa.__main__ import main
from causa.codegen import RUNTIME_DIR, CodegenError, binding_identifier, c_literal, c_string, generate_c
from causa.frontend import compile_optimized, compile_to_c, read_source
from causa.ir import Def, IRValidationError
from causa.semantic import CausaType
from test_spec_cases import CASES, SEMANTIC_ERRORS, source_of

ROOT = Path(__file__).resolve().parent.parent
INT, FLOAT, BOOL = CausaType.INT, CausaType.FLOAT, CausaType.BOOL
CC = os.environ.get("CAUSA_CC") or shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
CFLAGS = ["-std=c99", "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-I", str(RUNTIME_DIR)]
needs_cc = unittest.skipUnless(CC, "no C compiler found (set CAUSA_CC to enable)")


def src(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def c_of(*lines: str) -> str:
    return compile_to_c(src(*lines), "t.cau").source


def case_body(c: str, node_id: int) -> str:
    match = re.search(rf"    case {node_id}: .*?\n((?:        .*\n)+)", c)
    assert match, f"no case {node_id}"
    return match.group(1)


class LiteralAndIdentifierTests(unittest.TestCase):
    def test_literals(self) -> None:
        self.assertEqual(c_literal(100, INT), "INT64_C(100)")
        self.assertEqual(c_literal(-5, INT), "INT64_C(-5)")
        self.assertEqual(c_literal(-(2**63), INT), "INT64_MIN")  # -9223372036854775808LL is not a valid literal
        self.assertEqual(c_literal(True, BOOL), "true")
        self.assertEqual(c_literal(False, BOOL), "false")
        self.assertEqual(c_literal(0.1, FLOAT), "0x1.999999999999ap-4 /* 0.1 */")  # exact, no decimal rounding
        self.assertEqual(c_literal(-0.0, FLOAT), "-0x0.0p+0 /* -0.0 */")
        self.assertEqual(c_literal(1e308, FLOAT), "0x1.1ccf385ebc8a0p+1023 /* 1e+308 */")

    def test_c_strings(self) -> None:
        self.assertEqual(c_string(r"C:\dir\a.cau"), r'"C:\\dir\\a.cau"')
        self.assertEqual(c_string('say "hi"'), r'"say \"hi\""')
        self.assertEqual(c_string("café"), r'"caf\303\251"')

    def test_binding_identifiers_avoid_keywords_and_runtime_names(self) -> None:
        names = ["return", "double", "main", "env", "err", "causa_show", "CAUSA_PROGRAM", "_x", "Price", "price"]
        c = c_of(*[f"input {n} = 1" for n in names])
        for i, n in enumerate(names):
            self.assertIn(f"    {binding_identifier(n)} = {i},", c)
        self.assertEqual(len(set(map(binding_identifier, names))), len(names))  # case-sensitive, unique


class TranslationTests(unittest.TestCase):
    def test_type_mapping_of_inputs(self) -> None:
        c = c_of("input i = 100", "input f = 0.25", "input b = true", "input n = -0.0")
        # the launch value if one was given (LS §9.5), else the source literal
        self.assertIn("env[0] = causa_input_value(CAUSA_BINDING_i, (causa_value){ .i = INT64_C(100) });",
                      case_body(c, 0))
        self.assertIn("env[1] = causa_input_value(CAUSA_BINDING_f, "
                      "(causa_value){ .f = 0x1.0000000000000p-2 /* 0.25 */ });", case_body(c, 1))
        self.assertIn("env[2] = causa_input_value(CAUSA_BINDING_b, (causa_value){ .b = true });", case_body(c, 2))
        self.assertIn("env[3] = causa_input_value(CAUSA_BINDING_n, "
                      "(causa_value){ .f = -0x0.0p+0 /* -0.0 */ });", case_body(c, 3))

    def test_operations(self) -> None:
        c = c_of("input i = 1", "input f = 0.5", "input b = true",
                 "let r1 = i + i", "let r2 = i - i", "let r3 = i * i", "let r4 = -i",
                 "let r5 = f + f", "let r6 = f / f", "let r7 = -f", "let r8 = i / i",
                 "let r9 = i < f", "let r10 = b and b", "let r11 = b or not b", "let r12 = b == b")
        expected = [  # checked helpers carry the operator's source location
            "return causa_check(causa_add_i64(env[0].i, env[0].i, &env[3].i), 4, 12, err);",
            "return causa_check(causa_sub_i64(env[0].i, env[0].i, &env[5].i), 5, 12, err);",
            "return causa_check(causa_mul_i64(env[0].i, env[0].i, &env[7].i), 6, 12, err);",
            "return causa_check(causa_neg_i64(env[0].i, &env[9].i), 7, 10, err);",
            "return causa_check(causa_add_f64(env[1].f, env[1].f, &env[11].f), 8, 12, err);",
            "return causa_check(causa_div_f64(env[1].f, env[1].f, &env[13].f), 9, 12, err);",
            "env[15].f = -env[1].f;",
            # i / i: both operands promoted; the optimizer merged the two identical itof nodes
            "env[17].f = (double)env[0].i;",
            "return causa_check(causa_div_f64(env[17].f, env[17].f, &env[19].f), 11, 12, err);",
            "env[21].f = (double)env[0].i;",
            "env[22].b = env[21].f < env[1].f;",
            "env[24].b = env[2].b && env[2].b;",  # operand nodes already evaluated: strict
            "env[26].b = !env[2].b;",
            "env[27].b = env[2].b || env[26].b;",
            "env[29].b = env[2].b == env[2].b;",
        ]
        for line in expected:
            self.assertIn(f"        {line}\n", c)

    def test_bind_and_const_nodes(self) -> None:
        c = c_of("input x = 1", "let y = x", "let k = 7")
        self.assertIn("env[1] = env[0];", case_body(c, 1))
        self.assertIn("env[2].i = INT64_C(7);", case_body(c, 2))
        self.assertIn("/* n3 bind k: 7 @3:5 owner k */", c)

    def test_folded_and_unfolded_runtime_errors(self) -> None:
        c = c_of("let q = 1 / 0", "let o = 9223372036854775807 + 1", "let k = 2 + 3")
        self.assertIn("causa_div_f64(env[2].f, env[3].f, &env[4].f), 1, 11, err)", c)  # not folded: R101 kept
        self.assertIn("causa_add_i64(env[6].i, env[7].i, &env[8].i), 2, 29, err)", c)  # not folded: R102 kept
        self.assertIn("env[12].i = INT64_C(5);", c)  # 2 + 3 folded by the optimizer

    def test_evaluation_follows_ir_steps(self) -> None:
        text = src("input x = 1", "show x", "let y = x + 1", "show y", "assert y > 1")
        module = compile_optimized(text).module
        c = generate_c(module).source
        main_body = c.split("int main(int argc, char **argv)")[1]
        expected = []
        for step in module.steps:
            if isinstance(step, Def):
                expected.append(f"causa_eval_node({step.node}, env, &err)")
            else:
                expected.append(type(step).__name__.lower())
        tokens = re.findall(r"(causa_eval_node\(\d+, env, &err\))|causa_(show|explain|whatif|impact|assert)\(", main_body)
        self.assertEqual([a or b for a, b in tokens], expected)

    def test_distinct_bindings_with_identical_expressions(self) -> None:
        c = c_of("input a = 1", "let p = a + 1", "let q = a + 1")
        self.assertIn("    CAUSA_BINDING_p = 1,", c)
        self.assertIn("    CAUSA_BINDING_q = 2,", c)
        self.assertEqual(len(re.findall(r"causa_add_i64\(env\[0\]\.i", c)), 2)
        self.assertIn('{ "p", CAUSA_KIND_LET, CAUSA_TYPE_INT, 3,', c)
        self.assertIn('{ "q", CAUSA_KIND_LET, CAUSA_TYPE_INT, 6,', c)

    def test_deterministic(self) -> None:
        text = read_source(ROOT / "examples" / "pricing.cau")
        self.assertEqual(compile_to_c(text, "p.cau").source, compile_to_c(text, "p.cau").source)

    def test_rejects_invalid_ir(self) -> None:
        module = compile_optimized(src("input x = 1", "let y = x")).module
        with self.assertRaises(IRValidationError):
            generate_c(replace(module, bindings={}))


class MetadataTests(unittest.TestCase):
    def test_dependencies_survive_x_times_zero(self) -> None:
        c = c_of("input x = 3", "let y = x * 0", "let w = x - x", "let s = w + y")
        self.assertIn("static const int causa_b1_deps[] = { CAUSA_BINDING_x };", c)
        self.assertIn("static const int causa_b2_deps[] = { CAUSA_BINDING_x };", c)
        self.assertIn("static const int causa_b0_dependents[] = { CAUSA_BINDING_y, CAUSA_BINDING_w };", c)
        # deps in declaration order, refs in first-appearance order (explain children)
        self.assertIn("static const int causa_b3_deps[] = { CAUSA_BINDING_y, CAUSA_BINDING_w };", c)
        self.assertIn("static const int causa_b3_refs[] = { CAUSA_BINDING_w, CAUSA_BINDING_y };", c)

    def test_pricing_binding_rows(self) -> None:
        c = compile_to_c(read_source(ROOT / "examples" / "pricing.cau"), "examples/pricing.cau").source
        self.assertIn('{ "price", CAUSA_KIND_INPUT, CAUSA_TYPE_INT, 0, 4, 7, NULL, 0, NULL, 0, NULL, '
                      '2, causa_b0_dependents },', c)
        self.assertIn('{ "total", CAUSA_KIND_LET, CAUSA_TYPE_FLOAT, 17, 12, 5, "subtotal * (1 + tax) + fee", '
                      '3, causa_b7_deps, 3, causa_b7_refs, 2, causa_b7_dependents },', c)
        self.assertIn("static const int causa_b7_deps[] = { CAUSA_BINDING_tax, CAUSA_BINDING_fee, "
                      "CAUSA_BINDING_subtotal };", c)
        self.assertIn('    "examples/pricing.cau", CAUSA_NODE_SLOTS,', c)
        self.assertIn("CAUSA_NODE_OP, CAUSA_TYPE_FLOAT, CAUSA_BINDING_per_unit, 14, 22, 2,", c)  # the LS §12 division

    def test_node_table_lists_live_nodes_only(self) -> None:
        result = compile_optimized(src("input x = 1", "let y = x * (2 + 3)"))
        c = generate_c(result.module).source
        rows = re.findall(r"^    \{ (\d+), CAUSA_NODE_", c, re.MULTILINE)
        self.assertEqual([int(r) for r in rows], [n.id for n in result.module.nodes])
        self.assertIn("#define CAUSA_NODE_SLOTS 6", c)  # IDs 0..5, retired 1 and 2 still have slots

    def test_asserts(self) -> None:
        c = c_of("input x = 1", "assert x > 0", "assert true")
        self.assertIn('    { 2, 1, "x > 0", 2, 1, causa_a0_refs },', c)  # root n2 = (x > 0)
        self.assertIn('    { 3, 1, "true", 3, 0, NULL },', c)
        self.assertIn("causa_assert(env, 0, env[2].b); /* line 2: x > 0 */", c)
        self.assertIn("causa_assert(env, 1, env[3].b); /* line 3: true */", c)
        self.assertIn("CAUSA_ASSERT_OWNER(0)", c)

    def test_empty_program(self) -> None:
        program = compile_to_c("", "empty.cau")
        self.assertTrue(program.standalone)
        self.assertIn("0, NULL,", program.source)


class RuntimeInterfaceTests(unittest.TestCase):
    def test_action_calls(self) -> None:
        program = compile_to_c(src("input t = 0.5", "let u = t * 2", "show u", "explain t", "impact t",
                                   "whatif t = 1 show u", "whatif t = 0.25"), "t.cau")
        c = program.source
        self.assertIn("causa_show(env, CAUSA_BINDING_u); /* line 3 */", c)
        self.assertIn("causa_explain(env, CAUSA_BINDING_t); /* line 4 */", c)
        self.assertIn("causa_impact(env, CAUSA_BINDING_t, 2); /* line 5 */", c)
        self.assertIn("causa_whatif(env, (const causa_override[]){ { CAUSA_BINDING_t, "
                      "{ .f = 0x1.0000000000000p+0 /* 1.0 */ } } }, 1, CAUSA_BINDING_u, 2); /* line 6 */", c)
        self.assertIn("causa_whatif(env, (const causa_override[]){ { CAUSA_BINDING_t, "
                      "{ .f = 0x1.0000000000000p-2 /* 0.25 */ } } }, 1, CAUSA_NO_TARGET, 2); /* line 7 */", c)
        self.assertEqual(program.runtime_calls, (("causa_show", 3), ("causa_explain", 4), ("causa_impact", 5),
                                                 ("causa_whatif", 6)))
        self.assertFalse(program.standalone)
        self.assertIn(" * Uses the CAUSA runtime library: causa_show, causa_explain, causa_impact, causa_whatif.\n", c)
        self.assertIn("causa_runtime.c -lm\n", c)
        # stream setup comes before any evaluation or output
        main_body = c.split("int main(int argc, char **argv)")[1]
        self.assertLess(main_body.index("causa_init();"), main_body.index("causa_eval_node("))
        # launch arguments are validated after stream setup and before the first statement
        self.assertLess(main_body.index("causa_init();"), main_body.index("causa_configure(argc, argv);"))
        self.assertLess(main_body.index("causa_configure(argc, argv);"), main_body.index("causa_eval_node("))

    def test_several_overrides_call(self) -> None:
        c = compile_to_c(src("input p = 100", "input d = 0.25", "input m = true", "let y = p * d",
                             "whatif d = 1, p = -5, m = false show y"), "t.cau").source
        # one compound-literal array in statement order; promotion already applied to d
        self.assertIn("causa_whatif(env, (const causa_override[]){ "
                      "{ CAUSA_BINDING_d, { .f = 0x1.0000000000000p+0 /* 1.0 */ } }, "
                      "{ CAUSA_BINDING_p, { .i = INT64_C(-5) } }, "
                      "{ CAUSA_BINDING_m, { .b = false } } }, 3, CAUSA_BINDING_y, 4); /* line 5 */", c)

    def test_runtime_functions_are_declared_in_header(self) -> None:
        header = (RUNTIME_DIR / "causa_runtime.h").read_text(encoding="utf-8")
        for name in ("causa_show", "causa_explain", "causa_impact", "causa_whatif", "causa_assert"):
            self.assertRegex(header, rf"\nvoid {name}\(const causa_value \*env, ")

    def test_standalone_rejects_runtime_features(self) -> None:
        for statement, name in [("show x", "show"), ("explain x", "explain"), ("impact x", "impact"),
                                ("whatif x = 2", "whatif"), ("assert x > 0", "assert")]:
            with self.subTest(statement=statement):
                with self.assertRaises(CodegenError) as cm:
                    compile_to_c(src("input x = 1", statement), standalone=True)
                self.assertIn(f"{name} (line 2)", str(cm.exception))
                self.assertIn("runtime library (causa_runtime.c)", str(cm.exception))

    def test_standalone_accepts_inputs_and_lets(self) -> None:
        program = compile_to_c(src("input x = 1", "let y = x / 0"), standalone=True)
        self.assertTrue(program.standalone)
        self.assertIn("Standalone: needs only causa_runtime.h", program.source)


class CliTests(unittest.TestCase):
    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main(list(argv))
            except SystemExit as exc:
                code = int(exc.code or 0)
        return code, out.getvalue(), err.getvalue()

    def test_emit_c_to_stdout_with_note(self) -> None:
        code, out, err = self.run_cli("emit-c", str(ROOT / "examples" / "minimal.cau"))
        self.assertEqual(code, 0)
        self.assertIn("int causa_eval_node(", out)
        self.assertIn("causa: note:", err)
        self.assertIn("causa_show (line 5)", err)

    def test_emit_c_to_file_and_standalone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "p.cau"
            source.write_text("input x = 1\nlet y = x + 1\n", encoding="utf-8")
            out_file = Path(tmp) / "p.c"
            code, out, err = self.run_cli("emit-c", str(source), "-o", str(out_file), "--standalone")
            self.assertEqual((code, out, err), (0, "", ""))
            self.assertIn("causa_add_i64", out_file.read_text(encoding="utf-8"))

    def test_standalone_failure_exit_code(self) -> None:
        code, out, err = self.run_cli("emit-c", str(ROOT / "examples" / "pricing.cau"), "--standalone")
        self.assertEqual((code, out), (3, ""))
        self.assertIn("causa: error: cannot emit a standalone program", err)

    def test_errors_and_misuse(self) -> None:
        code, _, err = self.run_cli("emit-c", str(ROOT / "examples" / "invalid-type-error.cau"))
        self.assertEqual(code, 1)
        self.assertIn(":8:19: error[E401]", err)
        code, _, _ = self.run_cli("ir", str(ROOT / "examples" / "minimal.cau"), "--standalone")
        self.assertEqual(code, 2)


# ---- tests that compile and run generated C ---------------------------------

HARNESS = r"""
#define CAUSA_NO_MAIN
#include "prog.c"
#include <inttypes.h>
int main(void)
{
    static causa_value env[CAUSA_NODE_SLOTS];
    causa_error err;
    int i;
    for (i = 0; i < CAUSA_PROGRAM.node_count; i++) {
        if (causa_eval_node(CAUSA_PROGRAM.nodes[i].id, env, &err)) {
            printf("ERR R%d %d:%d\n", err.code, err.line, err.column);
            return 0;
        }
    }
    for (i = 0; i < CAUSA_PROGRAM.binding_count; i++) {
        const causa_binding_info *b = &CAUSA_PROGRAM.bindings[i];
        const causa_value *v = &env[b->anchor];
        if (b->type == CAUSA_TYPE_INT) printf("%s=%" PRId64 "\n", b->name, v->i);
        else if (b->type == CAUSA_TYPE_FLOAT) printf("%s=%a\n", b->name, v->f);
        else printf("%s=%s\n", b->name, v->b ? "true" : "false");
    }
    return 0;
}
"""


def compile_and_run(c_source: str, harness: bool) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "prog.c").write_text(c_source, encoding="utf-8")
        main_file = d / "prog.c"
        if harness:
            main_file = d / "harness.c"
            main_file.write_text(HARNESS, encoding="utf-8")
        exe = d / "prog.exe"
        build = subprocess.run([CC, *CFLAGS, str(main_file), "-o", str(exe), "-lm"], capture_output=True, text=True)
        if build.returncode != 0:
            raise AssertionError(f"C compilation failed:\n{build.stderr}\n{build.stdout}")
        return subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)


def values(*lines: str) -> dict[str, object]:
    run = compile_and_run(compile_to_c(src(*lines), "t.cau").source, harness=True)
    result: dict[str, object] = {}
    for line in run.stdout.splitlines():
        if line.startswith("ERR "):
            return {"ERR": line[4:]}
        name, value = line.split("=", 1)
        if value in ("true", "false"):
            result[name] = value == "true"
        elif "p" in value or "inf" in value or "nan" in value:
            result[name] = float.fromhex(value)
        else:
            result[name] = int(value)
    return result


@needs_cc
class CompileTests(unittest.TestCase):
    def test_every_valid_specification_program_compiles(self) -> None:
        """All programs that pass the front end compile to warning-free C99 (-c only:
        linking with causa_runtime.c and running is covered by test_runtime.py)."""
        sources = {case_id: source_of(case_id, program) for case_id, (program, expected) in CASES.items()
                   if case_id not in SEMANTIC_ERRORS and not (isinstance(expected, tuple) and expected[0] != "sem")}
        for name in ("minimal.cau", "pricing.cau"):
            sources[name] = read_source(ROOT / "examples" / name)
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for name, text in sources.items():
                c_file = Path(tmp) / f"{name}.c"
                c_file.write_text(compile_to_c(text, name).source, encoding="utf-8")
                files.append(str(c_file))
            # One compiler run for all files; a failure names the offending file.
            build = subprocess.run([CC, *CFLAGS, "-fsyntax-only", *files], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
        self.assertGreater(len(files), 80)

    def test_awkward_identifiers_compile(self) -> None:
        names = ["return", "double", "main", "env", "err", "causa_show", "CAUSA_PROGRAM", "_x", "Price", "price"]
        c = compile_to_c(src(*[f"input {n} = 1" for n in names], "let s = return + double + main + env + err"),
                         standalone=True).source
        run = compile_and_run(c, harness=False)
        self.assertEqual((run.returncode, run.stdout, run.stderr), (0, "", ""))


@needs_cc
class ExecutionTests(unittest.TestCase):
    """Run generated C and compare binding values with CAUSA semantics (inputs keep
    expressions out of the optimizer, so the C operations themselves are tested)."""

    def test_precedence_promotion_and_booleans(self) -> None:
        self.assertEqual(values(
            "input a = 7", "input b = 2", "input f = 0.5", "input t = true",
            "let p1 = a - b - 1", "let p2 = a - (b - 1)", "let p3 = -a * b", "let p4 = a + b * a",
            "let q = a / b", "let m = a + f", "let c = a < f", "let e = a == 7.0",
            "let l = t and not (a > b) or false", "let n = -f", "let o = (a + b) * (a + b)"),
            {"a": 7, "b": 2, "f": 0.5, "t": True, "p1": 4, "p2": 6, "p3": -14, "p4": 21, "q": 3.5, "m": 7.5,
             "c": False, "e": True, "l": False, "n": -0.5, "o": 81})

    def test_distinct_bindings_and_structural_dependencies(self) -> None:
        self.assertEqual(values("input a = 5", "let p = a + 1", "let q = a + 1", "let z = a * 0", "let w = a - a"),
                         {"a": 5, "p": 6, "q": 6, "z": 0, "w": 0})

    def test_int_to_float_rounding(self) -> None:
        self.assertEqual(values("input big = 9007199254740993", "let g = big + 0.0"),
                         {"big": 9007199254740993, "g": 9007199254740992.0})

    def test_negative_zero(self) -> None:
        result = values("input z = 0.0", "let n = -z", "let e = n == z")
        self.assertEqual(repr(result["n"]), "-0.0")
        self.assertIs(result["e"], True)

    def test_integer_overflow_boundaries(self) -> None:
        cases = [
            (("input m = 9223372036854775807", "let o = m + 1"), "R102 2:11"),
            (("input m = 9223372036854775806", "let o = m + 1"), None),
            (("input m = -9223372036854775807", "let o = m - 2"), "R102 2:11"),
            (("input m = -9223372036854775807", "let o = m - 1"), None),
            (("input m = 4611686018427387904", "let o = m * 2"), "R102 2:11"),
            (("input m = -4611686018427387904", "let o = m * 2"), None),  # exactly INT64_MIN
            (("input m = -4611686018427387904", "let o = m * -2"), "R102 2:11"),
            (("input m = 4611686018427387904", "let o = m * -2"), None),  # exactly INT64_MIN
            (("input m = 4611686018427387905", "let o = m * -2"), "R102 2:11"),
            (("input m = 0", "let o = m * -9223372036854775807"), None),
            (("input m = -1", "let o = m * -9223372036854775807"), None),
            (("input m = -9223372036854775807", "let n = m - 1", "let o = -n"), "R102 3:9"),
        ]
        for lines, error in cases:
            with self.subTest(lines=lines):
                result = values(*lines)
                if error:
                    self.assertEqual(result, {"ERR": error})
                else:
                    self.assertNotIn("ERR", result)

    def test_float_errors(self) -> None:
        self.assertEqual(values("input f = 1.0e308", "let g = f * 10.0"), {"ERR": "R103 2:11"})
        self.assertEqual(values("input z = -0.0", "let q = 1.0 / z"), {"ERR": "R101 2:13"})
        self.assertEqual(values("input d = 0", "let q = 1 / d"), {"ERR": "R101 2:11"})
        self.assertEqual(values("input f = 1.0e-308", "let q = 1.0e308 / f"), {"ERR": "R103 2:17"})

    def test_strict_and_evaluates_both_operands(self) -> None:
        self.assertEqual(values("input d = 0", "let b = false and 1 / d > 0"), {"ERR": "R101 2:21"})

    def test_specification_runtime_cases_execute(self) -> None:
        """Spec cases whose programs need no runtime library run end to end now."""
        for case_id in ("R01", "R02", "R03", "R04", "R05", "R07", "R08", "R09", "H11"):
            program, _ = CASES[case_id]
            with self.subTest(case=case_id):
                c = compile_to_c(source_of(case_id, program), "F", standalone=True).source
                run = compile_and_run(c, harness=False)
                expected = {
                    "R01": "F:2:11: runtime error[R101]: division by zero",
                    "R02": "F:1:13: runtime error[R101]: division by zero",
                    "R03": "F:2:13: runtime error[R102]: integer overflow",
                    "R04": "F:2:11: runtime error[R103]: non-finite float result",
                    "R05": "F:3:9: runtime error[R102]: integer overflow",
                    "R07": "F:2:16: runtime error[R101]: division by zero",
                    "R08": "F:1:21: runtime error[R101]: division by zero",
                    "R09": "F:2:11: runtime error[R101]: division by zero",
                    "H11": "F:2:11: runtime error[R101]: division by zero",
                }[case_id]
                self.assertEqual((run.returncode, run.stdout, run.stderr.strip()), (2, "", expected))

    def test_program_without_errors_exits_zero(self) -> None:
        c = compile_to_c(src("input x = 2", "let y = x * 3", "let z = y / 4"), standalone=True).source
        run = compile_and_run(c, harness=False)
        self.assertEqual((run.returncode, run.stdout, run.stderr), (0, "", ""))


if __name__ == "__main__":
    unittest.main()
