"""Semantic analysis tests (language-specification §5-§8, §9.2, §10)."""

import unittest

from causa.astnodes import BinaryOp, LetDecl, LiteralType, WhatIfStmt
from causa.diagnostics import CausaError
from causa.frontend import check
from causa.semantic import BindingKind, CausaType, SemanticProgram

INT, FLOAT, BOOL = CausaType.INT, CausaType.FLOAT, CausaType.BOOL


def lines(*src: str) -> str:
    return "\n".join(src) + "\n"


class Base(unittest.TestCase):
    def assertError(self, source: str, code: str, line: int, column: int) -> None:
        with self.assertRaises(CausaError) as cm:
            check(source)
        self.assertEqual((cm.exception.code, cm.exception.line, cm.exception.column), (code, line, column))

    def let_type(self, expr: str, prefix: str = "input i = 1\ninput f = 0.5\ninput b = true\n") -> CausaType:
        sem = check(f"{prefix}let r = {expr}\n")
        return sem.symbols["r"].type


class SymbolTableTests(Base):
    def test_symbols_in_declaration_order(self) -> None:
        sem = check(lines("input price = 100", "input rate = 0.5", "let a = price * rate", "let ok = a > 1.0"))
        self.assertEqual(list(sem.symbols), ["price", "rate", "a", "ok"])
        self.assertEqual([s.index for s in sem.symbols.values()], [0, 1, 2, 3])
        self.assertEqual([s.kind for s in sem.symbols.values()],
                         [BindingKind.INPUT, BindingKind.INPUT, BindingKind.LET, BindingKind.LET])
        self.assertEqual([s.type for s in sem.symbols.values()], [INT, FLOAT, FLOAT, BOOL])

    def test_input_types_from_literal_form(self) -> None:
        sem = check(lines("input a = 0", "input b = 0.0", "input c = false", "input d = -3", "input e = -0.0"))
        self.assertEqual([s.type for s in sem.symbols.values()], [INT, FLOAT, BOOL, INT, FLOAT])

    def test_direct_and_transitive_dependencies(self) -> None:
        sem = check(lines("input a = 1", "input b = 2", "let c = b + a + b", "let d = c * 2", "let e = 7"))
        self.assertEqual(sem.symbols["c"].direct_deps, ("b", "a"))  # first appearance, unique
        self.assertEqual(sem.symbols["d"].direct_deps, ("c",))
        self.assertEqual(sem.symbols["d"].transitive_deps, frozenset({"a", "b", "c"}))
        self.assertEqual(sem.symbols["e"].transitive_deps, frozenset())
        self.assertEqual(sem.symbols["a"].direct_deps, ())

    def test_visible_counts(self) -> None:
        sem = check(lines("input x = 1", "show x", "let y = x", "impact x"))
        self.assertEqual(sem.visible, (0, 1, 1, 2))

    def test_ast_not_modified(self) -> None:
        sem = check(lines("input t = 0.5", "let u = t * 2", "whatif t = 1 show u"))
        stmt = sem.program.statements[2]
        assert isinstance(stmt, WhatIfStmt)
        self.assertEqual((stmt.value.type, stmt.value.value), (LiteralType.INT, 1))
        override = sem.overrides[2]
        self.assertIs(override.literal, stmt.value)
        self.assertEqual((override.type, override.value, override.promoted), (FLOAT, 1.0, True))
        self.assertIs(type(override.value), float)

    def test_expression_types_recorded(self) -> None:
        sem = check(lines("input i = 1", "let r = i / 2 > 0.5"))
        let = sem.program.statements[1]
        assert isinstance(let, LetDecl) and isinstance(let.value, BinaryOp)
        self.assertIs(sem.type_of(let.value), BOOL)
        self.assertIs(sem.type_of(let.value.left), FLOAT)
        self.assertIsInstance(sem, SemanticProgram)


class NameResolutionTests(Base):
    def test_errors(self) -> None:
        cases = [
            ("let y = x", "E301", 1, 9),
            ("let a = b + 1\ninput b = 2", "E301", 1, 9),  # forward reference
            ("let x = x + 1", "E301", 1, 9),  # self reference
            ("input a = 1\ninput a = 2", "E302", 2, 7),
            ("input a = 1\nlet a = 2", "E302", 2, 5),
            ("let y = 1\nlet y = y + 1", "E302", 2, 5),  # E302 before the expression
            ("show nothing", "E301", 1, 6),
            ("explain nothing", "E301", 1, 9),
            ("impact nothing", "E301", 1, 8),
            ("show y\nlet y = 1", "E301", 1, 6),
            ("impact y\ninput y = 1", "E301", 1, 8),
            ("input x = 1\nlet y = x + z", "E301", 2, 13),
        ]
        for source, code, line, column in cases:
            with self.subTest(source=source):
                self.assertError(source, code, line, column)

    def test_case_sensitive_names(self) -> None:
        self.assertError("input Price = 1\nshow price", "E301", 2, 6)
        check("input Price = 1\ninput price = 2\nshow Price\nshow price")

    def test_name_arguments_accept_inputs_and_lets(self) -> None:
        check(lines("input x = 1", "let y = x", "show x", "show y", "explain x", "explain y", "impact x", "impact y"))


class TypeCheckingTests(Base):
    def test_valid_types(self) -> None:
        cases = [
            ("i + i", INT), ("i - i", INT), ("i * i", INT), ("-i", INT),
            ("i + f", FLOAT), ("f * i", FLOAT), ("f - f", FLOAT), ("-f", FLOAT),
            ("i / i", FLOAT), ("7 / 2", FLOAT), ("f / i", FLOAT),
            ("i < f", BOOL), ("i <= i", BOOL), ("f > 1", BOOL), ("i >= 2.0", BOOL),
            ("i == f", BOOL), ("i != i", BOOL), ("b == true", BOOL), ("b != b", BOOL),
            ("b and b", BOOL), ("b or false", BOOL), ("not b", BOOL), ("not i > 1", BOOL),
            ("(i < 1) == b", BOOL), ("i", INT), ("2.5", FLOAT), ("true", BOOL),
            ("-(i + f)", FLOAT), ("i * (1 - f)", FLOAT),
        ]
        for expr, expected in cases:
            with self.subTest(expr=expr):
                self.assertIs(self.let_type(expr), expected)

    def test_operator_type_errors(self) -> None:
        prefix = "input i = 1\ninput f = 0.5\ninput b = true\n"
        cases = [  # (expression, column of the offending operator in "let r = ...")
            ("i + b", 11), ("b - 1", 11), ("b * b", 11), ("f / b", 11),
            ("-b", 9), ("not i", 9), ("not 1.5", 9),
            ("i and b", 11), ("b or 1", 11), ("i or i", 11),
            ("b < b", 11), ("b <= true", 11), ("b > 0", 11), ("i >= b", 11),
            ("b == 1", 11), ("1.0 != false", 13),
        ]
        for expr, column in cases:
            with self.subTest(expr=expr):
                self.assertError(prefix + f"let r = {expr}\n", "E401", 4, column)

    def test_assertions(self) -> None:
        check("input x = 1\nassert x > 0\nassert true\nassert not (x == 2)\n")
        self.assertError("assert 1", "E402", 1, 8)
        self.assertError("input x = 0.5\nassert x", "E402", 2, 8)
        self.assertError("input x = 1\nassert x + 1", "E402", 2, 8)
        self.assertError("input x = 1\nassert (x)", "E402", 2, 8)  # span includes '('

    def test_first_error_inside_one_statement(self) -> None:
        # Post-order: an ill-typed operand is reported, not the operator using it.
        self.assertError("let x = true + (1 + false)", "E401", 1, 19)
        self.assertError("let x = true + nope", "E301", 1, 16)
        self.assertError("let x = nope + (1 + false)", "E301", 1, 9)
        self.assertError("assert 1 + true", "E401", 1, 10)  # not E402


class WhatIfTests(Base):
    def test_valid_overrides(self) -> None:
        sem = check(lines("input i = 1", "input f = 0.5", "input b = true",
                          "whatif i = 7", "whatif i = -7", "whatif f = 2.5", "whatif f = 3", "whatif f = -3",
                          "whatif b = false"))
        got = [(o.type, o.value, o.promoted) for o in sem.overrides.values()]
        self.assertEqual(got, [(INT, 7, False), (INT, -7, False), (FLOAT, 2.5, False),
                               (FLOAT, 3.0, True), (FLOAT, -3.0, True), (BOOL, False, False)])
        self.assertEqual(list(sem.overrides), [3, 4, 5, 6, 7, 8])

    def test_promotion_rounds_to_nearest_float(self) -> None:
        sem = check("input f = 0.5\nwhatif f = 9007199254740993\n")
        self.assertEqual(sem.overrides[1].value, 9007199254740992.0)

    def test_override_errors(self) -> None:
        cases = [
            ("input n = 5\nwhatif n = 5.0", "E403", 2, 12),
            ("input n = 5\nwhatif n = -2.5", "E403", 2, 12),
            ("input b = true\nwhatif b = 1", "E403", 2, 12),
            ("input b = true\nwhatif b = 1.0", "E403", 2, 12),
            ("input f = 0.5\nwhatif f = true", "E403", 2, 12),
            ("input i = 1\nwhatif i = false", "E403", 2, 12),
            ("input a = 1\nlet b = a\nwhatif b = 2", "E303", 3, 8),
            ("whatif z = 1", "E301", 1, 8),
            ("whatif z = 1\ninput z = 0", "E301", 1, 8),
        ]
        for source, code, line, column in cases:
            with self.subTest(source=source):
                self.assertError(source, code, line, column)

    def test_targets(self) -> None:
        check(lines("input x = 1", "let y = x + 1", "let z = y * 2", "whatif x = 5 show z", "whatif x = 5 show y"))
        # Structural dependence suffices even if the value can never change.
        check(lines("input x = 3", "let z = x * 0", "whatif x = 7 show z"))
        check(lines("input x = 1", "let y = x - x", "whatif x = 2 show y"))
        check(lines("input b = true", "let c = b or true", "whatif b = false show c"))

    def test_target_errors(self) -> None:
        cases = [
            ("input x = 1\ninput k = 2\nlet y = k * 2\nwhatif x = 5 show y", "E304", 4, 19),
            ("input x = 1\nwhatif x = 5 show x", "E304", 2, 19),
            ("input x = 1\ninput k = 2\nwhatif x = 5 show k", "E304", 3, 19),
            ("input x = 1\nlet c = 7\nwhatif x = 5 show c", "E304", 3, 19),
            ("input x = 1\nwhatif x = 5 show y\nlet y = x", "E301", 2, 19),
            ("input x = 1\nwhatif x = 5 show nothing", "E301", 2, 19),
        ]
        for source, code, line, column in cases:
            with self.subTest(source=source):
                self.assertError(source, code, line, column)

    def test_check_order_within_whatif(self) -> None:
        # name (E303) before value (E403) before target (E304)
        self.assertError("input a = 1\nlet b = a\nwhatif b = 2.5 show b", "E303", 3, 8)
        self.assertError("input a = 1\nlet b = 7\nwhatif a = 2.5 show b", "E403", 3, 12)


class OrderingAcrossStagesTests(Base):
    def test_semantic_error_before_later_syntax_error(self) -> None:
        self.assertError("let y = x\nlet z = 1 +\n", "E301", 1, 9)

    def test_semantic_error_before_later_lexical_error(self) -> None:
        self.assertError("let y = x\n007\n", "E301", 1, 9)

    def test_syntax_error_before_later_semantic_error(self) -> None:
        self.assertError("let z = 1 +\nlet y = x\n", "E201", 1, 12)

    def test_syntax_errors_are_not_reported_as_semantic(self) -> None:
        self.assertError("whatif x = 5 show", "E201", 1, 18)  # x undeclared, but syntax first
        self.assertError("input x = 1\nwhatif x = 1 + 1 show x", "E203", 2, 14)


if __name__ == "__main__":
    unittest.main()
