"""Parser and AST unit tests (grammar.ebnf §2-§3)."""

import unittest
from pathlib import Path

from causa.astnodes import (
    AssertStmt, BinaryOp, BinaryOperator, ExplainStmt, ImpactStmt, InputDecl, LetDecl,
    Literal, LiteralType, Name, NameRef, OverrideClause, ShowStmt, Span, UnaryOp, UnaryOperator,
    WhatIfStmt, dump,
)
from causa.diagnostics import CausaError
from causa.parser import parse, parse_file

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def expr(source: str) -> str:
    """Dump of the expression in `let e = <source>`."""
    return dump(parse(f"let e = {source}\n")).removeprefix("(let e ").removesuffix(")")


class PrecedenceTests(unittest.TestCase):
    CASES = [
        ("1 + 2 * 3", "(+ 1 (* 2 3))"),
        ("(1 + 2) * 3", "(* (+ 1 2) 3)"),
        ("10 - 3 - 2", "(- (- 10 3) 2)"),
        ("8 / 2 / 2", "(/ (/ 8 2) 2)"),
        ("a * b / c", "(/ (* a b) c)"),
        ("a - b + c", "(+ (- a b) c)"),
        ("-a * b", "(* (neg a) b)"),
        ("- -4", "(neg (neg 4))"),
        ("-(a + b)", "(neg (+ a b))"),
        ("a - -b", "(- a (neg b))"),
        ("a + b < c * d", "(< (+ a b) (* c d))"),
        ("not a == b", "(not (== a b))"),
        ("not not a", "(not (not a))"),
        ("not 1 > 2", "(not (> 1 2))"),
        ("a or b and c", "(or a (and b c))"),
        ("a and b or c", "(or (and a b) c)"),
        ("true or false and false", "(or true (and false false))"),
        ("a or b or c", "(or (or a b) c)"),
        ("a and b and c", "(and (and a b) c)"),
        ("not a and b", "(and (not a) b)"),
        ("a < b and b <= c", "(and (< a b) (<= b c))"),
        ("(a < b) == c", "(== (< a b) c)"),
        ("a != b", "(!= a b)"),
        ("a >= b", "(>= a b)"),
        ("a > -1.5", "(> a (neg 1.5))"),
        ("((x))", "x"),
    ]

    def test_cases(self) -> None:
        for source, expected in self.CASES:
            with self.subTest(source=source):
                self.assertEqual(expr(source), expected)


class StatementStructureTests(unittest.TestCase):
    def test_input_decl(self) -> None:
        (stmt,) = parse("input price = 100\n").statements
        self.assertEqual(stmt, InputDecl(Name("price", Span(1, 7, 1, 12)),
                                         Literal(LiteralType.INT, 100, Span(1, 15, 1, 18)),
                                         Span(1, 1, 1, 18)))

    def test_input_literal_values(self) -> None:
        cases = [
            ("input x = -5", LiteralType.INT, -5),
            ("input x = - 5", LiteralType.INT, -5),
            ("input x = 0.25", LiteralType.FLOAT, 0.25),
            ("input x = -0", LiteralType.INT, 0),
            ("input x = true", LiteralType.BOOL, True),
            ("input x = false", LiteralType.BOOL, False),
        ]
        for source, type_, value in cases:
            with self.subTest(source=source):
                (stmt,) = parse(source).statements
                assert isinstance(stmt, InputDecl)
                self.assertIs(stmt.value.type, type_)
                self.assertEqual(stmt.value.value, value)
                self.assertIs(type(stmt.value.value), type(value))

    def test_negative_zero_float(self) -> None:
        (stmt,) = parse("input z = -0.0").statements
        assert isinstance(stmt, InputDecl)
        self.assertEqual(str(stmt.value.value), "-0.0")
        self.assertEqual(stmt.value.span, Span(1, 11, 1, 15))  # span includes the sign

    def test_let_decl_structure(self) -> None:
        (stmt,) = parse("let total = price * (1 - discount)\n").statements
        assert isinstance(stmt, LetDecl)
        self.assertEqual(stmt.name, Name("total", Span(1, 5, 1, 10)))
        self.assertEqual(stmt.source_text, "price * (1 - discount)")
        self.assertEqual(stmt.span, Span(1, 1, 1, 35))
        mul = stmt.value
        assert isinstance(mul, BinaryOp)
        self.assertIs(mul.op, BinaryOperator.MUL)
        self.assertEqual(mul.op_span, Span(1, 19, 1, 20))
        self.assertEqual(mul.left, NameRef("price", Span(1, 13, 1, 18)))
        sub = mul.right
        assert isinstance(sub, BinaryOp)
        self.assertIs(sub.op, BinaryOperator.SUB)
        self.assertEqual(sub.span, Span(1, 21, 1, 35))  # widened over the parentheses
        self.assertEqual(sub.op_span, Span(1, 24, 1, 25))
        self.assertEqual(sub.left, Literal(LiteralType.INT, 1, Span(1, 22, 1, 23)))

    def test_unary_nodes(self) -> None:
        (stmt,) = parse("let b = not -x > 0").statements
        assert isinstance(stmt, LetDecl)
        node = stmt.value
        assert isinstance(node, UnaryOp)
        self.assertIs(node.op, UnaryOperator.NOT)
        self.assertEqual(node.op_span, Span(1, 9, 1, 12))
        cmp = node.operand
        assert isinstance(cmp, BinaryOp) and isinstance(cmp.left, UnaryOp)
        self.assertIs(cmp.left.op, UnaryOperator.NEG)

    def test_source_text_is_verbatim(self) -> None:
        cases = [
            ("let y = x   +  1   # comment", "x   +  1"),
            ("let y = (x + 1)", "(x + 1)"),
            ("let y=x*2", "x*2"),
            ("let y = 5", "5"),
        ]
        for source, text in cases:
            with self.subTest(source=source):
                (stmt,) = parse(source).statements
                assert isinstance(stmt, LetDecl)
                self.assertEqual(stmt.source_text, text)

    def test_assert(self) -> None:
        (stmt,) = parse("assert total >= 0\n").statements
        assert isinstance(stmt, AssertStmt)
        self.assertEqual(stmt.source_text, "total >= 0")
        self.assertEqual(dump(stmt), "(assert (>= total 0))")
        self.assertEqual(stmt.span, Span(1, 1, 1, 18))

    def test_name_statements(self) -> None:
        for keyword, cls in [("show", ShowStmt), ("explain", ExplainStmt), ("impact", ImpactStmt)]:
            with self.subTest(keyword=keyword):
                (stmt,) = parse(f"{keyword} total\n").statements
                self.assertIsInstance(stmt, cls)
                assert isinstance(stmt, (ShowStmt, ExplainStmt, ImpactStmt))
                col = len(keyword) + 2
                self.assertEqual(stmt.name, Name("total", Span(1, col, 1, col + 5)))

    def test_whatif_full_form(self) -> None:
        (stmt,) = parse("whatif price = 160\n").statements
        assert isinstance(stmt, WhatIfStmt)
        (override,) = stmt.overrides
        self.assertEqual(override, OverrideClause(Name("price", Span(1, 8, 1, 13)),
                                                  Literal(LiteralType.INT, 160, Span(1, 16, 1, 19)),
                                                  Span(1, 8, 1, 19)))
        self.assertIsNone(stmt.target)
        self.assertEqual(stmt.span, Span(1, 1, 1, 19))

    def test_whatif_targeted_form(self) -> None:
        (stmt,) = parse("whatif tax = 1 show total\n").statements
        assert isinstance(stmt, WhatIfStmt)
        # The literal is kept as written; int-to-float promotion is semantic (D15).
        self.assertEqual(stmt.overrides[0].value.type, LiteralType.INT)
        self.assertEqual(stmt.target, Name("total", Span(1, 21, 1, 26)))
        self.assertEqual(stmt.span, Span(1, 1, 1, 26))
        self.assertEqual(dump(stmt), "(whatif tax 1 show total)")

    def test_whatif_several_overrides(self) -> None:
        (stmt,) = parse("whatif a = 1, b = -2.5, c = true show t\n").statements
        assert isinstance(stmt, WhatIfStmt)
        self.assertEqual([(o.name.text, o.value.type, o.value.value) for o in stmt.overrides],
                         [("a", LiteralType.INT, 1), ("b", LiteralType.FLOAT, -2.5), ("c", LiteralType.BOOL, True)])
        self.assertEqual([o.span for o in stmt.overrides],
                         [Span(1, 8, 1, 13), Span(1, 15, 1, 23), Span(1, 25, 1, 33)])
        self.assertEqual(stmt.target, Name("t", Span(1, 39, 1, 40)))
        self.assertEqual(dump(stmt), "(whatif a 1, b -2.5, c true show t)")
        self.assertEqual(dump(parse("whatif a = 1, b = 2")), "(whatif a 1, b 2)")

    def test_whatif_negative_and_bool_values(self) -> None:
        self.assertEqual(dump(parse("whatif t = -1")), "(whatif t -1)")
        self.assertEqual(dump(parse("whatif m = false show p")), "(whatif m false show p)")

    def test_empty_lines_and_comments_produce_no_statements(self) -> None:
        program = parse("\n# c\n\ninput x = 1\n\n\nshow x\n# end")
        self.assertEqual([type(s) for s in program.statements], [InputDecl, ShowStmt])
        self.assertEqual(program.statements[1].span.line, 7)

    def test_empty_program(self) -> None:
        self.assertEqual(parse("").statements, ())

    def test_crlf_and_no_trailing_newline(self) -> None:
        a = parse("input x = 2\nlet y = x * 3\nshow y\n")
        self.assertEqual(dump(parse("input x = 2\r\nlet y = x * 3\r\nshow y\r\n")), dump(a))
        self.assertEqual(dump(parse("input x = 2\nlet y = x * 3\nshow y")), dump(a))


class SyntaxErrorTests(unittest.TestCase):
    CASES = [
        # statement level
        ("x = 1", "E201", 1, 1),
        ("= 1", "E201", 1, 1),
        ("let = 1", "E201", 1, 5),
        ("let x 1", "E201", 1, 7),
        ("let x =", "E201", 1, 8),
        ("let x = 1 2", "E201", 1, 11),
        ("let a = 1 let b = 2", "E201", 1, 11),
        ("let show = 1", "E201", 1, 5),
        ("let if = 1", "E201", 1, 5),
        ("input int = 1", "E201", 1, 7),
        ("show", "E201", 1, 5),
        ("show 1", "E201", 1, 6),
        ("show x y", "E201", 1, 8),
        ("explain x + 1", "E201", 1, 11),
        ("impact x * 2", "E201", 1, 10),
        ("assert", "E201", 1, 7),
        ("input x 5", "E201", 1, 9),
        ("whatif = 5", "E201", 1, 8),
        # expressions
        ("let x = 1 +", "E201", 1, 12),
        ("let x = (1 + 2", "E201", 1, 15),
        ("let x = 1 + 2)", "E201", 1, 14),
        ("let x = ()", "E201", 1, 10),
        ("let x = * 2", "E201", 1, 9),
        ("let x = 1 * * 2", "E201", 1, 13),
        ("let x = 1 == not true", "E201", 1, 14),
        ("let x = - not true", "E201", 1, 11),
        ("let x = if true then 1 else 2", "E201", 1, 9),
        ("let x = int", "E201", 1, 9),
        ("let b = 1 < 2 < 3", "E202", 1, 15),
        ("let b = 1 < 2 == true", "E202", 1, 15),
        ("let b = a == b != c", "E202", 1, 16),
        # literal_value positions (E203)
        ("input x = 1 + 2", "E203", 1, 13),
        ("input x = y", "E203", 1, 11),
        ("input x = -true", "E203", 1, 12),
        ("input x = (1)", "E203", 1, 11),
        ("input x =", "E203", 1, 10),
        ("input x = 1 2", "E203", 1, 13),
        ("whatif p = 100 + 1", "E203", 1, 16),
        ("whatif p = q", "E203", 1, 12),
        ("whatif x = 5 explain y", "E203", 1, 14),
        ("whatif x = -false", "E203", 1, 13),
        # whatif target (E201)
        ("whatif x = 5 show", "E201", 1, 18),
        ("whatif x = 5 show y z", "E201", 1, 21),
        ("whatif x = 5 show y + 1", "E201", 1, 21),
        ("whatif x = 5 show let", "E201", 1, 19),
        ("whatif x = 5 show 3", "E201", 1, 19),
        ("whatif x = 5 show y show z", "E201", 1, 21),
        # commas (revision 3): valid only between whatif overrides
        ("whatif a = 1,", "E201", 1, 14),
        ("whatif a = 1, show y", "E201", 1, 15),
        ("whatif a = 1,, b = 2", "E201", 1, 14),
        ("whatif a = 1 b = 2", "E203", 1, 14),
        ("whatif a = 1, b = 2 + 1", "E203", 1, 21),
        ("whatif a = 1, b = x", "E203", 1, 19),
        ("whatif a = 1, b = 2 show y, z", "E201", 1, 27),
        ("whatif , a = 1", "E201", 1, 8),
        ("let x = 1, 2", "E201", 1, 10),
        ("input a = 1, b = 2", "E203", 1, 12),
        ("show x, y", "E201", 1, 7),
        ("let x = (1, 2)", "E201", 1, 11),
    ]

    def test_cases(self) -> None:
        for source, code, line, column in self.CASES:
            with self.subTest(source=source):
                with self.assertRaises(CausaError) as cm:
                    parse(source)
                self.assertEqual((cm.exception.code, cm.exception.line, cm.exception.column),
                                 (code, line, column))

    def test_error_on_later_line(self) -> None:
        with self.assertRaises(CausaError) as cm:
            parse("input x = 1\n\nlet y = x +\nshow y\n")
        self.assertEqual((cm.exception.line, cm.exception.column), (3, 12))

    def test_first_error_in_source_order(self) -> None:
        # A syntax error on line 1 wins over a lexical error on line 2 (LS §9.2).
        with self.assertRaises(CausaError) as cm:
            parse("let x = 1 +\nlet y = 007\n")
        self.assertEqual((cm.exception.code, cm.exception.line), ("E201", 1))
        # ...and a lexical error before any syntax error wins too.
        with self.assertRaises(CausaError) as cm:
            parse("let x = 007 +\n")
        self.assertEqual(cm.exception.code, "E102")


class SemanticErrorsAreNotSyntaxErrorsTests(unittest.TestCase):
    """Programs that are syntactically valid but semantically invalid must parse."""

    PROGRAMS = [
        "let y = x",  # E301 undefined
        "let x = x + 1",  # E301 self reference
        "input a = 1\ninput a = 2",  # E302
        "input a = 1\nlet b = a\nwhatif b = 2",  # E303
        "input x = 1\ninput k = 2\nlet y = k * 2\nwhatif x = 5 show y",  # E304
        "input x = 1\nwhatif x = 5 show x",  # E304
        "input a = 1\nwhatif a = 1, a = 2",  # E305
        "input a = 1\ninput b = 2\ninput c = 3\nlet y = c\nwhatif a = 1, b = 2 show y",  # E304
        "let x = 1 + true",  # E401
        "let x = -true",  # E401
        "assert 1",  # E402
        "input n = 5\nwhatif n = 5.0",  # E403
        "input b = true\nwhatif b = 1",  # E403
        "let q = 1 / 0",  # runtime R101, never a compile error
    ]

    def test_parse_succeeds(self) -> None:
        for source in self.PROGRAMS:
            with self.subTest(source=source):
                self.assertTrue(parse(source).statements)


class ExampleFileTests(unittest.TestCase):
    def test_minimal(self) -> None:
        self.assertEqual(dump(parse_file(EXAMPLES / "minimal.cau")),
                         "(input x 2)\n(let y (* x 3))\n(show y)")

    def test_pricing(self) -> None:
        program = parse_file(EXAMPLES / "pricing.cau")
        self.assertEqual(len(program.statements), 24)
        lines = dump(program).splitlines()
        self.assertIn("(let total (+ (* subtotal (+ 1 tax)) fee))", lines)
        self.assertIn("(whatif discount 0.5 show total)", lines)
        self.assertIn("(whatif tax 1 show total)", lines)
        self.assertIn("(whatif units 0)", lines)
        self.assertIn("(whatif price 160, discount 0.5 show total)", lines)
        per_unit = program.statements[9]
        assert isinstance(per_unit, LetDecl)
        self.assertEqual(per_unit.name.text, "per_unit")
        assert isinstance(per_unit.value, BinaryOp)
        self.assertEqual(per_unit.value.op_span, Span(14, 22, 14, 23))  # LS §12 error location

    def test_invalid_example_is_syntactically_valid(self) -> None:
        # Its error (E401 @ 8:19) is semantic; the parser must accept it.
        program = parse_file(EXAMPLES / "invalid-type-error.cau")
        let = program.statements[2]
        assert isinstance(let, LetDecl) and isinstance(let.value, BinaryOp)
        self.assertEqual(let.value.op_span, Span(8, 19, 8, 20))


if __name__ == "__main__":
    unittest.main()
