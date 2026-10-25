"""Lexer for CAUSA (grammar.ebnf §1, language-specification §3).

Tokens are produced lazily by `iter_tokens` so the parser reports the first
error in source order (compiler-architecture §2.1).
"""

from __future__ import annotations

import enum
import math
import string
from dataclasses import dataclass
from typing import Iterator

from .diagnostics import CausaError

INT_MAX = 2**63 - 1


class TokenKind(enum.Enum):
    IDENT = "identifier"
    INT = "integer literal"
    FLOAT = "float literal"
    # keywords
    INPUT = "input"
    LET = "let"
    SHOW = "show"
    EXPLAIN = "explain"
    WHATIF = "whatif"
    IMPACT = "impact"
    ASSERT = "assert"
    AND = "and"
    OR = "or"
    NOT = "not"
    TRUE = "true"
    FALSE = "false"
    # reserved words
    IF = "if"
    THEN = "then"
    ELSE = "else"
    KW_INT = "int"
    KW_FLOAT = "float"
    KW_BOOL = "bool"
    # operators and punctuation
    EQ = "=="
    NE = "!="
    LE = "<="
    GE = ">="
    LT = "<"
    GT = ">"
    PLUS = "+"
    MINUS = "-"
    STAR = "*"
    SLASH = "/"
    ASSIGN = "="
    LPAREN = "("
    RPAREN = ")"
    COMMA = ","  # separates whatif overrides (specification revision 3)
    # structure
    NEWLINE = "end of line"
    EOF = "end of file"


K = TokenKind
KEYWORDS: dict[str, TokenKind] = {
    k.value: k
    for k in (K.INPUT, K.LET, K.SHOW, K.EXPLAIN, K.WHATIF, K.IMPACT, K.ASSERT,
              K.AND, K.OR, K.NOT, K.TRUE, K.FALSE)
}
RESERVED: dict[str, TokenKind] = {
    k.value: k for k in (K.IF, K.THEN, K.ELSE, K.KW_INT, K.KW_FLOAT, K.KW_BOOL)
}
_TWO_CHAR = {"==": K.EQ, "!=": K.NE, "<=": K.LE, ">=": K.GE}
_ONE_CHAR = {"=": K.ASSIGN, "<": K.LT, ">": K.GT, "+": K.PLUS, "-": K.MINUS,
             "*": K.STAR, "/": K.SLASH, "(": K.LPAREN, ")": K.RPAREN,
             ",": K.COMMA}

_LETTERS = frozenset(string.ascii_letters + "_")
_DIGITS = frozenset(string.digits)
_IDENT_CHARS = _LETTERS | _DIGITS


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    lexeme: str
    line: int
    column: int
    offset: int  # character offset of the first character
    end_offset: int  # character offset just past the last character
    value: int | float | None = None  # parsed value of INT / FLOAT tokens

    def describe(self) -> str:
        if self.kind in (K.NEWLINE, K.EOF):
            return self.kind.value
        if self.kind is K.IDENT:
            return f"name '{self.lexeme}'"
        if self.kind in (K.INT, K.FLOAT):
            return f"{self.kind.value} '{self.lexeme}'"
        if self.lexeme in KEYWORDS:
            return f"keyword '{self.lexeme}'"
        if self.lexeme in RESERVED:
            return f"reserved word '{self.lexeme}'"
        return f"'{self.lexeme}'"


def decode_source(data: bytes) -> str:
    """Decode UTF-8 source bytes; an invalid byte is an invalid character (E101)."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        prefix = data[: exc.start].decode("utf-8").removeprefix("﻿")
        line = prefix.count("\n") + 1
        column = len(prefix) - (prefix.rfind("\n") + 1) + 1
        raise CausaError("E101", "invalid UTF-8 byte", line, column) from None


def tokenize(text: str) -> list[Token]:
    return list(iter_tokens(text))


def iter_tokens(text: str) -> Iterator[Token]:
    start_of_text = 1 if text.startswith("﻿") else 0  # BOM is ignored
    n = len(text)
    i = start_of_text
    line = 1
    line_start = i

    def token(kind: TokenKind, start: int, end: int, value: int | float | None = None) -> Token:
        return Token(kind, text[start:end], line, start - line_start + 1, start, end, value)

    while i < n:
        c = text[i]
        column = i - line_start + 1

        if c == " " or c == "\t":
            i += 1
        elif c == "#":
            while i < n and text[i] not in "\r\n":
                i += 1
        elif c == "\n" or c == "\r":
            if c == "\r" and not text.startswith("\n", i + 1):
                raise CausaError("E101", "carriage return not followed by line feed", line, column)
            end = i + (1 if c == "\n" else 2)
            yield token(K.NEWLINE, i, end)
            i = end
            line += 1
            line_start = i
        elif c in _LETTERS:
            end = i + 1
            while end < n and text[end] in _IDENT_CHARS:
                end += 1
            word = text[i:end]
            yield token(KEYWORDS.get(word) or RESERVED.get(word) or K.IDENT, i, end)
            i = end
        elif c in _DIGITS:
            kind, end, value = _scan_number(text, i, line, column)
            yield token(kind, i, end, value)
            i = end
        elif text[i : i + 2] in ("**", "//"):
            raise CausaError("E101", f"operator '{text[i : i + 2]}' is not supported in version 1", line, column)
        elif text[i : i + 2] in _TWO_CHAR:
            yield token(_TWO_CHAR[text[i : i + 2]], i, i + 2)
            i += 2
        elif c in _ONE_CHAR:
            yield token(_ONE_CHAR[c], i, i + 1)
            i += 1
        else:
            raise CausaError("E101", _invalid_char_message(c), line, column)

    if n > start_of_text and text[-1] != "\n":
        yield token(K.NEWLINE, n, n)  # synthesized final line terminator
    yield token(K.EOF, n, n)


def _scan_number(text: str, start: int, line: int, column: int) -> tuple[TokenKind, int, int | float]:
    """Scan a numeric literal at `start`. All errors are located at the literal's start."""
    n = len(text)

    def fail(code: str, message: str) -> CausaError:
        return CausaError(code, message, line, column)

    i = start
    if text[i] == "0" and i + 1 < n and text[i + 1] in _DIGITS:
        raise fail("E102", "leading zeros are not allowed in number literals")
    while i < n and text[i] in _DIGITS:
        i += 1
    kind = K.INT
    if i < n and text[i] == ".":
        if not (i + 1 < n and text[i + 1] in _DIGITS):
            raise fail("E102", "a float literal needs at least one digit after '.'")
        kind = K.FLOAT
        i += 1
        while i < n and text[i] in _DIGITS:
            i += 1
        if i < n and text[i] in "eE":
            j = i + 1
            if j < n and text[j] in "+-":
                j += 1
            if not (j < n and text[j] in _DIGITS):
                raise fail("E102", "exponent has no digits")
            i = j
            while i < n and text[i] in _DIGITS:
                i += 1
    if i < n and (text[i] in _IDENT_CHARS or text[i] == "."):
        raise fail("E102", f"malformed number literal starting '{text[start : i + 1]}'")

    lexeme = text[start:i]
    if kind is K.INT:
        # The length check also keeps int() clear of Python's digit limit.
        if len(lexeme) > 19 or int(lexeme) > INT_MAX:
            raise fail("E103", "integer literal exceeds 9223372036854775807")
        return kind, i, int(lexeme)
    value = float(lexeme)  # correctly rounded decimal-to-binary64
    if math.isinf(value):
        raise fail("E104", "float literal is too large")
    return kind, i, value


def _invalid_char_message(c: str) -> str:
    if c == "!":
        return "invalid character '!'; use 'not' for negation or '!=' for inequality"
    if c == ".":
        return "invalid character '.'; a float literal needs a digit before '.'"
    if not c.isascii():
        return f"invalid character {c!r}; non-ASCII characters are allowed only in comments"
    return f"invalid character {c!r}"
