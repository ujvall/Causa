"""Hand-written recursive-descent parser for CAUSA (grammar.ebnf §2-§3).

One method per grammar rule. Purely syntactic: name resolution, typing and
the whatif target rule (E301-E304, E401-E403) belong to semantic analysis.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Iterator

from .astnodes import (
    AssertStmt, BinaryOp, BinaryOperator, ExplainStmt, Expr, ImpactStmt, InputDecl,
    LetDecl, Literal, LiteralType, Name, NameRef, Program, ShowStmt, Span, Statement,
    UnaryOp, UnaryOperator, WhatIfStmt,
)
from .diagnostics import CausaError
from .lexer import KEYWORDS, RESERVED, Token, TokenKind, decode_source, iter_tokens

K = TokenKind

_COMPARISON = {
    K.EQ: BinaryOperator.EQ, K.NE: BinaryOperator.NE, K.LT: BinaryOperator.LT,
    K.LE: BinaryOperator.LE, K.GT: BinaryOperator.GT, K.GE: BinaryOperator.GE,
}
_ADDITIVE = {K.PLUS: BinaryOperator.ADD, K.MINUS: BinaryOperator.SUB}
_MULTIPLICATIVE = {K.STAR: BinaryOperator.MUL, K.SLASH: BinaryOperator.DIV}


def parse(text: str) -> Program:
    return Parser(text).parse_program()


def parse_file(path: str | Path) -> Program:
    return parse(decode_source(Path(path).read_bytes()))


def _span(first: Token, last: Token) -> Span:
    return Span(first.line, first.column, last.line, last.column + len(last.lexeme))


class Parser:
    def __init__(self, text: str) -> None:
        self._text = text
        self._tokens = iter_tokens(text)
        self._current = next(self._tokens)
        self._previous = self._current

    # ---- token helpers -------------------------------------------------

    def _advance(self) -> Token:
        token = self._current
        self._previous = token
        if token.kind is not K.EOF:
            self._current = next(self._tokens)
        return token

    def _at(self, kind: TokenKind) -> bool:
        return self._current.kind is kind

    def _error(self, code: str, message: str, token: Token | None = None) -> CausaError:
        token = token or self._current
        return CausaError(code, message, token.line, token.column)

    def _expect(self, kind: TokenKind, what: str) -> Token:
        if not self._at(kind):
            raise self._error("E201", f"expected {what}, found {self._current.describe()}")
        return self._advance()

    # ---- program and lines ---------------------------------------------

    def parse_program(self) -> Program:
        return Program(tuple(self.iter_statements()))

    def iter_statements(self) -> Iterator[Statement]:
        """Yield each statement once its line is complete, so a later stage can
        check it before later lines are parsed (first error in source order)."""
        while not self._at(K.EOF):
            if self._at(K.NEWLINE):
                self._advance()  # empty line
                continue
            statement = self._statement()
            if not self._at(K.NEWLINE):
                self._expect(K.NEWLINE, "end of line")  # raises E201
            yield statement  # before advancing: the next line is not lexed yet
            self._advance()

    def _statement(self) -> Statement:
        kind = self._current.kind
        if kind is K.INPUT:
            return self._input_decl()
        if kind is K.LET:
            return self._let_decl()
        if kind is K.SHOW:
            keyword = self._advance()
            name = self._name()
            return ShowStmt(name, _span(keyword, self._previous))
        if kind is K.EXPLAIN:
            keyword = self._advance()
            name = self._name()
            return ExplainStmt(name, _span(keyword, self._previous))
        if kind is K.IMPACT:
            keyword = self._advance()
            name = self._name()
            return ImpactStmt(name, _span(keyword, self._previous))
        if kind is K.WHATIF:
            return self._whatif_stmt()
        if kind is K.ASSERT:
            return self._assert_stmt()
        raise self._error("E201", f"expected a statement, found {self._current.describe()}")

    def _name(self) -> Name:
        token = self._current
        if token.kind is K.IDENT:
            self._advance()
            return Name(token.lexeme, _span(token, token))
        if token.lexeme in KEYWORDS or token.lexeme in RESERVED:
            raise self._error("E201", f"{token.describe()} cannot be used as a name")
        raise self._error("E201", f"expected a name, found {token.describe()}")

    # ---- declarations and statements -----------------------------------

    def _input_decl(self) -> InputDecl:
        keyword = self._advance()
        name = self._name()
        self._expect(K.ASSIGN, "'=' after the input name")
        value = self._literal_value("an input value")
        if not self._at(K.NEWLINE):
            raise self._error("E203", "an input value must be a single literal; expressions are not allowed")
        return InputDecl(name, value, _span(keyword, self._previous))

    def _let_decl(self) -> LetDecl:
        keyword = self._advance()
        name = self._name()
        self._expect(K.ASSIGN, "'=' after the binding name")
        value, source_text = self._expression_with_text()
        return LetDecl(name, value, source_text, _span(keyword, self._previous))

    def _whatif_stmt(self) -> WhatIfStmt:
        keyword = self._advance()
        name = self._name()
        self._expect(K.ASSIGN, "'=' after the input name")
        value = self._literal_value("a whatif override")
        target: Name | None = None
        if self._at(K.SHOW):
            self._advance()
            target = self._name()
        elif not self._at(K.NEWLINE):
            raise self._error(
                "E203", "a whatif override must be a single literal, optionally followed by 'show NAME'")
        return WhatIfStmt(name, value, target, _span(keyword, self._previous))

    def _assert_stmt(self) -> AssertStmt:
        keyword = self._advance()
        condition, source_text = self._expression_with_text()
        return AssertStmt(condition, source_text, _span(keyword, self._previous))

    def _literal_value(self, what: str) -> Literal:
        """literal_value = [ "-" ] ( INT | FLOAT ) | "true" | "false"  (errors are E203)"""
        first = self._current
        negative = self._at(K.MINUS)
        if negative:
            self._advance()
        token = self._current
        if token.kind is K.INT or token.kind is K.FLOAT:
            assert token.value is not None
            value: int | float | bool = -token.value if negative else token.value
            type_ = LiteralType.INT if token.kind is K.INT else LiteralType.FLOAT
        elif token.kind in (K.TRUE, K.FALSE) and not negative:
            value = token.kind is K.TRUE
            type_ = LiteralType.BOOL
        else:
            raise self._error("E203", f"{what} must be a literal, found {token.describe()}")
        self._advance()
        return Literal(type_, value, _span(first, token))

    # ---- expressions ---------------------------------------------------

    def _expression_with_text(self) -> tuple[Expr, str]:
        first = self._current
        expr = self._expression()
        return expr, self._text[first.offset : self._previous.end_offset]

    def _expression(self) -> Expr:
        return self._or_expr()

    def _or_expr(self) -> Expr:
        left = self._and_expr()
        while self._at(K.OR):
            op = self._advance()
            right = self._and_expr()
            left = BinaryOp(BinaryOperator.OR, left, right, _span(op, op), left.span.cover(right.span))
        return left

    def _and_expr(self) -> Expr:
        left = self._not_expr()
        while self._at(K.AND):
            op = self._advance()
            right = self._not_expr()
            left = BinaryOp(BinaryOperator.AND, left, right, _span(op, op), left.span.cover(right.span))
        return left

    def _not_expr(self) -> Expr:
        if self._at(K.NOT):
            op = self._advance()
            operand = self._not_expr()
            return UnaryOp(UnaryOperator.NOT, operand, _span(op, op), _span(op, op).cover(operand.span))
        return self._comparison()

    def _comparison(self) -> Expr:
        left = self._additive()
        if self._current.kind in _COMPARISON:
            op = self._advance()
            right = self._additive()
            left = BinaryOp(_COMPARISON[op.kind], left, right, _span(op, op), left.span.cover(right.span))
            if self._current.kind in _COMPARISON:
                raise self._error(
                    "E202", "comparisons cannot be chained; use parentheses or 'and'")
        return left

    def _additive(self) -> Expr:
        left = self._multiplicative()
        while self._current.kind in _ADDITIVE:
            op = self._advance()
            right = self._multiplicative()
            left = BinaryOp(_ADDITIVE[op.kind], left, right, _span(op, op), left.span.cover(right.span))
        return left

    def _multiplicative(self) -> Expr:
        left = self._unary()
        while self._current.kind in _MULTIPLICATIVE:
            op = self._advance()
            right = self._unary()
            left = BinaryOp(_MULTIPLICATIVE[op.kind], left, right, _span(op, op), left.span.cover(right.span))
        return left

    def _unary(self) -> Expr:
        if self._at(K.MINUS):
            op = self._advance()
            operand = self._unary()
            return UnaryOp(UnaryOperator.NEG, operand, _span(op, op), _span(op, op).cover(operand.span))
        return self._primary()

    def _primary(self) -> Expr:
        token = self._current
        if token.kind is K.INT or token.kind is K.FLOAT:
            self._advance()
            assert token.value is not None
            type_ = LiteralType.INT if token.kind is K.INT else LiteralType.FLOAT
            return Literal(type_, token.value, _span(token, token))
        if token.kind is K.TRUE or token.kind is K.FALSE:
            self._advance()
            return Literal(LiteralType.BOOL, token.kind is K.TRUE, _span(token, token))
        if token.kind is K.IDENT:
            self._advance()
            return NameRef(token.lexeme, _span(token, token))
        if token.kind is K.LPAREN:
            self._advance()
            inner = self._expression()
            close = self._expect(K.RPAREN, "')'")
            return replace(inner, span=_span(token, close))  # parentheses make no node
        raise self._error("E201", f"expected an expression, found {token.describe()}")
