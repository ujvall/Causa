"""Optimizer tests (compiler-architecture §5)."""

import re
import unittest
from dataclasses import replace
from pathlib import Path

from causa.diagnostics import CausaError
from causa.frontend import compile_optimized, compile_to_ir, read_source
from causa.ir import (
    Assert, Def, IRModule, IRValidationError, Node, NodeKind, Opcode, WhatIf, format_ir, format_node,
    validate_ir,
)
from causa.optimizer import OptimizationResult, format_log, optimize
from causa.semantic import CausaType

ROOT = Path(__file__).resolve().parent.parent
INT, FLOAT, BOOL = CausaType.INT, CausaType.FLOAT, CausaType.BOOL


def src(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def opt(*lines: str) -> OptimizationResult:
    return compile_optimized(src(*lines))


def root_of(module: IRModule, name: str) -> Node:
    """The node a let binding's bind node points to."""
    bind = module.node(module.bindings[name])
    return module.node(bind.operands[0])


def actions(log, kind: str) -> list[int]:
    return [r.node for r in log if r.action == kind]


class ConstantFoldingTests(unittest.TestCase):
    def assertFolded(self, expr: str, type_: CausaType, value: object) -> None:
        result = opt(f"let r = {expr}")
        node = root_of(result.module, "r")
        self.assertIs(node.kind, NodeKind.CONST, expr)
        self.assertIs(node.type, type_, expr)
        self.assertEqual(repr(node.value), repr(value), expr)  # exact value and Python type
        self.assertEqual([n.kind for n in result.module.nodes], [NodeKind.CONST, NodeKind.BIND])

    def test_integer_arithmetic(self) -> None:
        for expr, value in [("2 + 3", 5), ("10 * 4", 40), ("7 - 9", -2), ("2 + 3 * 4", 14),
                            ("(2 + 3) * 4", 20), ("-5", -5), ("- -5", 5), ("-(2 * 3)", -6),
                            ("9223372036854775806 + 1", 9223372036854775807),
                            ("-9223372036854775807 - 1", -9223372036854775808)]:
            self.assertFolded(expr, INT, value)

    def test_float_arithmetic(self) -> None:
        for expr, value in [("0.5 * 4.0", 2.0), ("0.1 + 0.2", 0.30000000000000004), ("1.5 - 2.5", -1.0),
                            ("-0.0", -0.0), ("0.0 - 0.0", 0.0), ("1.0e308 * 1.0", 1e308),
                            ("1.0e-300 * 1.0e-300", 0.0)]:
            self.assertFolded(expr, FLOAT, value)

    def test_division_is_float(self) -> None:
        for expr, value in [("7 / 2", 3.5), ("6 / 3", 2.0), ("1 / 3", 1 / 3), ("-1 / 4", -0.25)]:
            self.assertFolded(expr, FLOAT, value)

    def test_mixed_int_and_float(self) -> None:
        for expr, value in [("1 + 0.5", 1.5), ("2 * 0.25", 0.5), ("3 - 1.0", 2.0),
                            ("9007199254740993 * 1.0", 9007199254740992.0)]:
            self.assertFolded(expr, FLOAT, value)

    def test_comparisons(self) -> None:
        for expr, value in [("1 < 2", True), ("2 <= 1", False), ("1 == 1.0", True), ("0.0 == -0.0", True),
                            ("0.1 + 0.2 == 0.3", False), ("3 > 2.5", True), ("1 != 1", False),
                            ("true == false", False), ("true != false", True), ("2 >= 2", True)]:
            self.assertFolded(expr, BOOL, value)

    def test_boolean_operations(self) -> None:
        for expr, value in [("true and false", False), ("true or false", True), ("not true", False),
                            ("not 1 > 2", True), ("1 < 2 and not false", True), ("false or false", False)]:
            self.assertFolded(expr, BOOL, value)

    def test_fold_keeps_id_location_and_owner(self) -> None:
        before = compile_to_ir(src("input x = 1", "let r = x + 2 * 3"))
        after = optimize(before).module
        mul = next(n for n in before.nodes if n.opcode is Opcode.MUL)
        folded = after.node(mul.id)
        self.assertEqual((folded.kind, folded.value, folded.line, folded.column, folded.owner),
                         (NodeKind.CONST, 6, mul.line, mul.column, "r"))
        add = root_of(after, "r")
        self.assertEqual((add.opcode, add.operands), (Opcode.ADD, (after.bindings["x"], mul.id)))

    def test_spec_case_ir06(self) -> None:
        result = opt("input x = 1", "let y = x * (2 + 3)", "explain y")
        m = result.module
        y = m.node(m.bindings["y"])
        self.assertEqual(y.source_text, "x * (2 + 3)")  # explain still prints the source
        mul = m.node(y.operands[0])
        self.assertEqual(mul.opcode, Opcode.MUL)
        self.assertEqual((m.node(mul.operands[1]).kind, m.node(mul.operands[1]).value), (NodeKind.CONST, 5))
        self.assertEqual([str(r) for r in result.log][0], "fold n3: 2 + 3 -> 5 -- all operands are constants and evaluation cannot fail")

    def test_architecture_document_folding_example(self) -> None:
        doc = (ROOT / "docs" / "compiler-architecture.md").read_text(encoding="utf-8")
        section = doc.split("### 3.6 Illustrative IR")[1]
        source = re.findall(r"```\n(.*?)```", section, re.DOTALL)[0]
        folded_line = re.search(r"After constant folding.*?```\n(n\d+ .*?)\n```", section, re.DOTALL)
        assert folded_line is not None
        result = compile_optimized(source)
        self.assertEqual(format_node(result.module.node(3)), folded_line.group(1))
        self.assertNotIn(2, [n.id for n in result.module.nodes])  # n2 is retired
        self.assertEqual([str(r) for r in result.log], [
            "fold n3: itof 1 -> 1.0 -- all operands are constants and evaluation cannot fail",
            "remove n2: const node -- no remaining users",
        ])


class RuntimeSafetyTests(unittest.TestCase):
    def assertNotFolded(self, expr: str, opcode: Opcode, code: str, line: int = 1, column: int = 0) -> None:
        result = opt(f"let r = {expr}")
        node = root_of(result.module, "r")
        self.assertIs(node.kind, NodeKind.OP, expr)
        self.assertIs(node.opcode, opcode, expr)
        skip = [r for r in result.log if r.action == "skip" and r.node == node.id]
        self.assertEqual(len(skip), 1, expr)
        self.assertTrue(skip[0].reason.startswith(code), skip[0].reason)
        if column:
            self.assertEqual((node.line, node.column), (line, column))  # error location preserved

    def test_division_by_zero(self) -> None:
        self.assertNotFolded("1 / 0", Opcode.DIV, "R101", 1, 11)
        self.assertNotFolded("1.0 / 0.0", Opcode.DIV, "R101", 1, 13)  # spec case IR07
        self.assertNotFolded("1 / -0.0", Opcode.DIV, "R101")
        self.assertNotFolded("5 / (2 - 2)", Opcode.DIV, "R101")

    def test_integer_overflow(self) -> None:
        self.assertNotFolded("9223372036854775807 + 1", Opcode.ADD, "R102")
        self.assertNotFolded("-9223372036854775807 - 2", Opcode.SUB, "R102")
        self.assertNotFolded("4611686018427387904 * 2", Opcode.MUL, "R102")
        self.assertNotFolded("-(-9223372036854775807 - 1)", Opcode.NEG, "R102")

    def test_non_finite_float(self) -> None:
        self.assertNotFolded("1.0e308 * 10.0", Opcode.MUL, "R103")
        self.assertNotFolded("1.0e308 + 1.0e308", Opcode.ADD, "R103")
        self.assertNotFolded("1.0e308 / 0.5", Opcode.DIV, "R103")
        self.assertNotFolded("-1.0e308 - 1.0e308", Opcode.SUB, "R103")

    def test_failing_operation_blocks_folding_above_it(self) -> None:
        # Strict and/or: the failing division must still be evaluated at run time.
        m = opt("let r = false and 1 / 0 > 0").module
        self.assertEqual([n.opcode for n in m.nodes if n.kind is NodeKind.OP],
                         [Opcode.DIV, Opcode.GT, Opcode.AND])
        m = opt("let r = 1 / 0 * 0").module
        self.assertIs(root_of(m, "r").opcode, Opcode.MUL)

    def test_strict_and_or_never_drop_an_operand(self) -> None:
        m = opt("input d = 0", "let r = false and 1 / d > 0", "let s = true or d > 0").module
        self.assertEqual(root_of(m, "r").opcode, Opcode.AND)
        self.assertEqual(root_of(m, "s").opcode, Opcode.OR)
        self.assertEqual(m.provenance.by_name["r"].direct_deps, ("d",))

    def test_skip_is_stable(self) -> None:
        first = opt("let q = 1.0 / 0.0")
        second = optimize(first.module)
        self.assertEqual(second.module, first.module)
        self.assertEqual([r for r in second.log if r.action != "skip"], [])


class NoUnsupportedRewriteTests(unittest.TestCase):
    """Algebraic identities that drop a binding reference are forbidden (CA §5)."""

    def test_identities_are_left_alone(self) -> None:
        exprs = ["x * 0", "x - x", "x + 0", "x * 1", "x / 1", "-(-x)", "0 * x",
                 "b or true", "b and false", "not not b", "b == b", "x == x"]
        for expr in exprs:
            with self.subTest(expr=expr):
                before = compile_to_ir(src("input x = 3", "input b = true", f"let r = {expr}"))
                result = optimize(before)
                # At most a literal is promoted (x / 1 folds itof 1 -> 1.0); no node that
                # references x or b is folded, merged or removed.
                self.assertEqual(result.module.provenance.by_name["r"].direct_deps,
                                 before.provenance.by_name["r"].direct_deps)
                self.assertEqual([r.action for r in result.log if r.action == "cse"], [])
                for r in result.log:
                    self.assertIs(before.node(r.node).kind, NodeKind.CONST if r.action == "remove" else NodeKind.OP)
                    self.assertFalse(set(before.node(r.node).operands) & set(before.bindings.values()))
                self.assertIs(root_of(result.module, "r").kind, NodeKind.OP)

    def test_dependencies_survive_x_times_zero_and_x_minus_x(self) -> None:
        m = opt("input x = 3", "let y = x * 0", "let w = x - x").module
        self.assertEqual(m.provenance.by_name["y"].direct_deps, ("x",))
        self.assertEqual(m.provenance.by_name["w"].direct_deps, ("x",))
        self.assertEqual(m.provenance.all_dependents("x"), ("y", "w"))
        w = root_of(m, "w")
        self.assertEqual((w.opcode, w.operands), (Opcode.SUB, (m.bindings["x"], m.bindings["x"])))


class InvariantTests(unittest.TestCase):
    PROGRAM = src("input x = 3", "input rate = 0.5", "let p = x + 1", "let q = x + 1",
                  "let y = x * 0", "let s = (x + 2) * (x + 2) + rate * (1 - 0.5)",
                  "show s", "explain y", "impact x", "whatif x = 7 show y", "whatif rate = 1",
                  "assert s >= 0", "assert 1 < 2")

    def setUp(self) -> None:
        self.before = compile_to_ir(self.PROGRAM)
        self.result = optimize(self.before)
        self.after = self.result.module

    def test_inputs_remain_inputs(self) -> None:
        for name in ("x", "rate"):
            node = self.after.node(self.after.bindings[name])
            self.assertEqual(node, self.before.node(self.before.bindings[name]))
            self.assertIs(node.kind, NodeKind.INPUT)
        self.assertFalse(any(n.kind is NodeKind.CONST and n.value == 3 and n.owner != "s"
                             for n in self.after.nodes))

    def test_binding_identities_names_and_text(self) -> None:
        self.assertEqual(self.after.bindings, self.before.bindings)
        self.assertIs(self.after.provenance, self.before.provenance)
        for name, anchor in self.before.bindings.items():
            a, b = self.before.node(anchor), self.after.node(anchor)
            self.assertEqual((b.kind, b.name, b.type, b.line, b.column, b.source_text, b.owner),
                             (a.kind, a.name, a.type, a.line, a.column, a.source_text, a.owner))

    def test_identical_expressions_in_distinct_bindings_are_not_merged(self) -> None:
        p, q = root_of(self.after, "p"), root_of(self.after, "q")  # spec case IR05
        self.assertNotEqual(p.id, q.id)
        self.assertEqual((p.owner, q.owner), ("p", "q"))
        self.assertNotEqual(self.after.bindings["p"], self.after.bindings["q"])
        self.assertNotIn("cse", [r.action for r in self.result.log if r.node in (p.id, q.id)])

    def test_cse_within_one_binding(self) -> None:
        s = root_of(self.after, "s")
        itof = self.after.node(s.operands[0])  # int product promoted for the float add
        self.assertEqual(itof.opcode, Opcode.ITOF)
        mul = self.after.node(itof.operands[0])
        self.assertEqual(mul.opcode, Opcode.MUL)
        self.assertEqual(mul.operands[0], mul.operands[1])  # (x + 2) computed once
        self.assertEqual([str(r) for r in self.result.log if r.action == "cse"], [
            "cse n13: replaced by n11 -- identical const node with the same owner 's'",  # second literal 2
            "cse n14: replaced by n12 -- identical op node with the same owner 's'",  # second x + 2
            # 1 - 0.5 folds to 0.5, identical to the literal 0.5 const in the same binding
            "cse n19: replaced by n17 -- identical const node with the same owner 's'",
        ])

    def test_actions_preserved(self) -> None:
        old = [s for s in self.before.steps if not isinstance(s, Def)]
        new = [s for s in self.after.steps if not isinstance(s, Def)]
        self.assertEqual([type(s) for s in new], [type(s) for s in old])
        for a, b in zip(old, new):
            if isinstance(a, Assert):
                assert isinstance(b, Assert)
                self.assertEqual((b.source_text, b.refs, b.line, b.column), (a.source_text, a.refs, a.line, a.column))
            else:
                self.assertEqual(a, b)

    def test_folded_assert_condition(self) -> None:
        last = self.after.steps[-1]
        assert isinstance(last, Assert)
        root = self.after.node(last.root)
        self.assertEqual((root.kind, root.value, root.owner), (NodeKind.CONST, True, "assert#1"))

    def test_targeted_whatif_still_valid(self) -> None:
        whatifs = [s for s in self.after.steps if isinstance(s, WhatIf)]
        self.assertEqual(whatifs[0].target, self.after.bindings["y"])
        self.assertIn("x", self.after.provenance.transitive_deps("y"))
        (override,) = whatifs[1].overrides
        self.assertEqual((override.value, override.value_type, override.promoted), (1.0, FLOAT, True))

    def test_several_overrides_survive_optimization(self) -> None:
        before = compile_to_ir(src("input a = 1", "input b = 0.5", "let y = b * (2 + 3) + a",
                                   "whatif b = 2, a = 7 show y"))
        after = optimize(before).module
        old = [s for s in before.steps if isinstance(s, WhatIf)]
        new = [s for s in after.steps if isinstance(s, WhatIf)]
        self.assertEqual(new, old)  # overrides, order, promotion and target untouched
        self.assertEqual([o.input for o in new[0].overrides], [after.bindings["b"], after.bindings["a"]])

    def test_explain_and_impact_information_unchanged(self) -> None:
        for name in self.before.bindings:
            self.assertEqual(self.after.provenance.transitive_deps(name), self.before.provenance.transitive_deps(name))
            self.assertEqual(self.after.provenance.all_dependents(name), self.before.provenance.all_dependents(name))
            self.assertEqual(self.after.provenance.by_name[name].references,
                             self.before.provenance.by_name[name].references)

    def test_optimized_ir_validates_and_steps_follow_nodes(self) -> None:
        validate_ir(self.after)
        defs = [s.node for s in self.after.steps if isinstance(s, Def)]
        self.assertEqual(defs, [n.id for n in self.after.nodes])
        self.assertLess(len(self.after.nodes), len(self.before.nodes))

    def test_deterministic_and_idempotent(self) -> None:
        again = optimize(compile_to_ir(self.PROGRAM))
        self.assertEqual(again.module, self.after)
        self.assertEqual(again.log, self.result.log)
        second = optimize(self.after)
        self.assertEqual(second.module, self.after)
        self.assertEqual([r for r in second.log if r.action != "skip"], [])
        self.assertEqual(format_ir(second.module, optimized=True), format_ir(self.after, optimized=True))


class GuardTests(unittest.TestCase):
    def test_rejects_invalid_input_ir(self) -> None:
        m = compile_to_ir(src("input x = 1", "let y = x + 1"))
        broken = replace(m, bindings={"x": m.bindings["x"]})
        with self.assertRaises(IRValidationError):
            optimize(broken)

    def test_diagnostics_unchanged_through_optimizing_pipeline(self) -> None:
        for text, expected in [("let x = 1 +", ("E201", 1, 12)), ("let x = 007", ("E102", 1, 9)),
                               ("let x = 1 + true", ("E401", 1, 11)),
                               ("input x = 1\nwhatif x = 5 show x", ("E304", 2, 19))]:
            with self.subTest(text=text):
                with self.assertRaises(CausaError) as cm:
                    compile_optimized(text)
                self.assertEqual((cm.exception.code, cm.exception.line, cm.exception.column), expected)


class ExampleTests(unittest.TestCase):
    def test_pricing(self) -> None:
        text = read_source(ROOT / "examples" / "pricing.cau")
        before = compile_to_ir(text)
        result = optimize(before)
        self.assertEqual([str(r) for r in result.log], [
            "fold n12: itof 1 -> 1.0 -- all operands are constants and evaluation cannot fail",
            "fold n28: itof 0 -> 0.0 -- all operands are constants and evaluation cannot fail",
            "remove n11: const node -- no remaining users",
            "remove n27: const node -- no remaining users",
        ])
        p = result.module.provenance
        self.assertEqual(p.all_dependents("price"), ("savings", "subtotal", "total", "expensive", "per_unit", "bulk"))
        self.assertEqual(p.by_name["total"].direct_deps, ("tax", "fee", "subtotal"))
        div = next(n for n in result.module.nodes if n.opcode is Opcode.DIV)
        self.assertEqual((div.line, div.column), (14, 22))  # LS §12 hypothetical-error location

    def test_minimal_has_nothing_to_fold(self) -> None:
        text = read_source(ROOT / "examples" / "minimal.cau")
        result = compile_optimized(text)
        self.assertEqual(result.log, ())
        self.assertEqual(result.module, compile_to_ir(text))
        self.assertEqual(format_log(result.log), "  (no changes)")

    def test_invalid_example_still_rejected(self) -> None:
        with self.assertRaises(CausaError) as cm:
            compile_optimized(read_source(ROOT / "examples" / "invalid-type-error.cau"))
        self.assertEqual((cm.exception.code, cm.exception.line, cm.exception.column), ("E401", 8, 19))


if __name__ == "__main__":
    unittest.main()
