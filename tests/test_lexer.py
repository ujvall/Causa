"""Lexer unit tests (grammar.ebnf §1, language-specification §3)."""

import unittest

from causa.diagnostics import CausaError
from causa.lexer import Token, TokenKind as K, decode_source, tokenize


def kinds(text: str) -> list[K]:
    return [t.kind for t in tokenize(text)]


class TokenStructureTests(unittest.TestCase):
    def test_statement_tokens_with_positions(self) -> None:
        toks = tokenize("let total = price * (1 - discount)\n")
        self.assertEqual(
            [(t.kind, t.lexeme, t.line, t.column) for t in toks],
            [
                (K.LET, "let", 1, 1), (K.IDENT, "total", 1, 5), (K.ASSIGN, "=", 1, 11),
                (K.IDENT, "price", 1, 13), (K.STAR, "*", 1, 19), (K.LPAREN, "(", 1, 21),
                (K.INT, "1", 1, 22), (K.MINUS, "-", 1, 24), (K.IDENT, "discount", 1, 26),
                (K.RPAREN, ")", 1, 34), (K.NEWLINE, "\n", 1, 35), (K.EOF, "", 2, 1),
            ],
        )

    def test_offsets_slice_source(self) -> None:
        text = "input  price = 100\n"
        for t in tokenize(text):
            self.assertEqual(text[t.offset : t.end_offset], t.lexeme)

    def test_every_keyword(self) -> None:
        words = "input let show explain whatif impact assert and or not true false"
        self.assertEqual(
            kinds(words)[:-2],
            [K.INPUT, K.LET, K.SHOW, K.EXPLAIN, K.WHATIF, K.IMPACT, K.ASSERT,
             K.AND, K.OR, K.NOT, K.TRUE, K.FALSE],
        )

    def test_every_reserved_word(self) -> None:
        self.assertEqual(kinds("if then else int float bool")[:-2],
                         [K.IF, K.THEN, K.ELSE, K.KW_INT, K.KW_FLOAT, K.KW_BOOL])

    def test_identifiers_maximal_munch_and_case(self) -> None:
        toks = tokenize("showing Show _x x_1 letter iff")
        self.assertTrue(all(t.kind is K.IDENT for t in toks[:-2]))
        self.assertEqual([t.lexeme for t in toks[:-2]], ["showing", "Show", "_x", "x_1", "letter", "iff"])

    def test_every_operator(self) -> None:
        self.assertEqual(
            kinds("== != <= >= < > + - * / = ( )")[:-2],
            [K.EQ, K.NE, K.LE, K.GE, K.LT, K.GT, K.PLUS, K.MINUS, K.STAR, K.SLASH,
             K.ASSIGN, K.LPAREN, K.RPAREN],
        )

    def test_longest_match_without_spaces(self) -> None:
        self.assertEqual(kinds("a==b<=c")[:-2], [K.IDENT, K.EQ, K.IDENT, K.LE, K.IDENT])
        self.assertEqual(kinds("x=-1")[:-2], [K.IDENT, K.ASSIGN, K.MINUS, K.INT])
        self.assertEqual(kinds("a= =b")[:-2], [K.IDENT, K.ASSIGN, K.ASSIGN, K.IDENT])


class LiteralTests(unittest.TestCase):
    def value(self, text: str) -> Token:
        return tokenize(text)[0]

    def test_integers(self) -> None:
        for text, value in [("0", 0), ("42", 42), ("9223372036854775807", 2**63 - 1)]:
            tok = self.value(text)
            self.assertIs(tok.kind, K.INT)
            self.assertEqual(tok.value, value)

    def test_floats(self) -> None:
        cases = [("0.25", 0.25), ("3.0", 3.0), ("1.5e3", 1500.0), ("2.0E-4", 2.0e-4),
                 ("1.0e+2", 100.0), ("0.20", 0.2), ("1.0e16", 1e16)]
        for text, value in cases:
            tok = self.value(text)
            self.assertIs(tok.kind, K.FLOAT, text)
            self.assertEqual(tok.value, value, text)

    def test_float_underflow_is_valid(self) -> None:
        self.assertEqual(self.value("1.0e-400").value, 0.0)

    def test_literals_are_unsigned(self) -> None:
        self.assertEqual(kinds("-5")[:-2], [K.MINUS, K.INT])


class LineStructureTests(unittest.TestCase):
    def test_empty_file(self) -> None:
        self.assertEqual(kinds(""), [K.EOF])

    def test_blank_lines_are_significant(self) -> None:
        self.assertEqual(kinds("\n\nshow x\n\n"),
                         [K.NEWLINE, K.NEWLINE, K.SHOW, K.IDENT, K.NEWLINE, K.NEWLINE, K.EOF])

    def test_final_newline_synthesized(self) -> None:
        toks = tokenize("show x")
        self.assertEqual([t.kind for t in toks], [K.SHOW, K.IDENT, K.NEWLINE, K.EOF])
        self.assertEqual((toks[2].line, toks[2].column, toks[2].lexeme), (1, 7, ""))

    def test_no_extra_newline_when_file_ends_with_one(self) -> None:
        self.assertEqual(kinds("show x\n"), [K.SHOW, K.IDENT, K.NEWLINE, K.EOF])

    def test_crlf_is_one_newline(self) -> None:
        toks = tokenize("show x\r\nshow y\r\n")
        self.assertEqual([t.kind for t in toks],
                         [K.SHOW, K.IDENT, K.NEWLINE, K.SHOW, K.IDENT, K.NEWLINE, K.EOF])
        self.assertEqual((toks[3].line, toks[3].column), (2, 1))
        self.assertEqual(toks[2].lexeme, "\r\n")

    def test_comments_are_discarded_but_newline_kept(self) -> None:
        toks = tokenize("show x  # café ✓\n# whole line\n")
        self.assertEqual([t.kind for t in toks], [K.SHOW, K.IDENT, K.NEWLINE, K.NEWLINE, K.EOF])
        self.assertEqual(toks[2].column, 17)

    def test_comment_only_file_without_newline(self) -> None:
        self.assertEqual(kinds("# note"), [K.NEWLINE, K.EOF])

    def test_tab_is_one_column(self) -> None:
        toks = tokenize("\tshow\tx")
        self.assertEqual([(t.lexeme, t.column) for t in toks[:2]], [("show", 2), ("x", 7)])

    def test_bom_ignored_and_not_counted(self) -> None:
        toks = tokenize("﻿show x\n")
        self.assertEqual((toks[0].kind, toks[0].column), (K.SHOW, 1))
        self.assertEqual(kinds("﻿"), [K.EOF])

    def test_non_ascii_column_counts_code_points(self) -> None:
        # 'é' is two UTF-8 bytes but one column.
        with self.assertRaises(CausaError) as cm:
            tokenize("# é\nlet é = 1\n")
        self.assertEqual((cm.exception.line, cm.exception.column), (2, 5))


class LexicalErrorTests(unittest.TestCase):
    CASES = [
        # (source, code, line, column)
        ("let x = 1 $ 2", "E101", 1, 11),
        ("let x = !true", "E101", 1, 9),
        ("let x = 1 % 2", "E101", 1, 11),
        ("let x = .5", "E101", 1, 9),
        ("let café = 1", "E101", 1, 8),
        ("input x: float = 1", "E101", 1, 8),
        ("whatif a = 1, b = 2", "E101", 1, 13),
        ("let x = 1 ^ 2", "E101", 1, 11),
        ("let x = 1 ** 2", "E101", 1, 11),
        ("let x = 7 // 2", "E101", 1, 11),
        ("show x\rshow y", "E101", 1, 7),
        ("let x = 007", "E102", 1, 9),
        ("let x = 00.5", "E102", 1, 9),
        ("let x = 1.", "E102", 1, 9),
        ("let x = 1..2", "E102", 1, 9),
        ("let x = 1.5.2", "E102", 1, 9),
        ("let x = 123abc", "E102", 1, 9),
        ("let x = 1e5", "E102", 1, 9),
        ("let x = 1.5e", "E102", 1, 9),
        ("let x = 1.5e+", "E102", 1, 9),
        ("let x = 1.5e3x", "E102", 1, 9),
        ("let x = 0x1F", "E102", 1, 9),
        ("let x = 9223372036854775808", "E103", 1, 9),
        ("let x = " + "9" * 5000, "E103", 1, 9),
        ("let x = 1.0e400", "E104", 1, 9),
    ]

    def test_cases(self) -> None:
        for source, code, line, column in self.CASES:
            with self.subTest(source=source[:40]):
                with self.assertRaises(CausaError) as cm:
                    tokenize(source)
                self.assertEqual((cm.exception.code, cm.exception.line, cm.exception.column),
                                 (code, line, column))

    def test_invalid_utf8(self) -> None:
        with self.assertRaises(CausaError) as cm:
            decode_source(b"show x\nlet y\xff = 1\n")
        self.assertEqual((cm.exception.code, cm.exception.line, cm.exception.column), ("E101", 2, 6))

    def test_diagnostic_format(self) -> None:
        with self.assertRaises(CausaError) as cm:
            tokenize("let x = 007")
        self.assertTrue(cm.exception.format("a.cau").startswith("a.cau:1:9: error[E102]: "))


if __name__ == "__main__":
    unittest.main()
