"""Typed AST for CAUSA (compiler-architecture §2.2).

Spans are 1-based; `end_column` is exclusive. Every statement is on one line,
but spans keep both lines for generality.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True, slots=True)
class Span:
    line: int
    column: int
    end_line: int
    end_column: int

    def cover(self, other: Span) -> Span:
        """Span from the start of self to the end of other."""
        return Span(self.line, self.column, other.end_line, other.end_column)


class LiteralType(enum.Enum):
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"


class UnaryOperator(enum.Enum):
    NEG = "-"
    NOT = "not"


class BinaryOperator(enum.Enum):
    OR = "or"
    AND = "and"
    EQ = "=="
    NE = "!="
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="
    ADD = "+"
    SUB = "-"
    MUL = "*"
    DIV = "/"


# ---- expressions -----------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Literal:
    type: LiteralType
    value: int | float | bool
    span: Span


@dataclass(frozen=True, slots=True)
class NameRef:
    name: str
    span: Span


@dataclass(frozen=True, slots=True)
class UnaryOp:
    op: UnaryOperator
    operand: Expr
    op_span: Span
    span: Span


@dataclass(frozen=True, slots=True)
class BinaryOp:
    op: BinaryOperator
    left: Expr
    right: Expr
    op_span: Span
    span: Span


Expr = Union[Literal, NameRef, UnaryOp, BinaryOp]


# ---- statements ------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Name:
    """A binding name used as a declaration or statement argument."""
    text: str
    span: Span


@dataclass(frozen=True, slots=True)
class InputDecl:
    name: Name
    value: Literal  # literal_value: sign already applied
    span: Span


@dataclass(frozen=True, slots=True)
class LetDecl:
    name: Name
    value: Expr
    source_text: str  # expression exactly as written, first to last token
    span: Span


@dataclass(frozen=True, slots=True)
class ShowStmt:
    name: Name
    span: Span


@dataclass(frozen=True, slots=True)
class ExplainStmt:
    name: Name
    span: Span


@dataclass(frozen=True, slots=True)
class ImpactStmt:
    name: Name
    span: Span


@dataclass(frozen=True, slots=True)
class WhatIfStmt:
    name: Name
    value: Literal  # as written; promotion is a semantic step
    target: Name | None  # None for the full-report form
    span: Span


@dataclass(frozen=True, slots=True)
class AssertStmt:
    condition: Expr
    source_text: str
    span: Span


Statement = Union[InputDecl, LetDecl, ShowStmt, ExplainStmt, ImpactStmt, WhatIfStmt, AssertStmt]


@dataclass(frozen=True, slots=True)
class Program:
    statements: tuple[Statement, ...]


# ---- debugging dump --------------------------------------------------------

def dump(node: Program | Statement | Expr) -> str:
    """S-expression rendering, one statement per line. Used by the CLI and tests."""
    match node:
        case Program(statements):
            return "\n".join(dump(s) for s in statements)
        case InputDecl(name, value):
            return f"(input {name.text} {dump(value)})"
        case LetDecl(name, value):
            return f"(let {name.text} {dump(value)})"
        case ShowStmt(name):
            return f"(show {name.text})"
        case ExplainStmt(name):
            return f"(explain {name.text})"
        case ImpactStmt(name):
            return f"(impact {name.text})"
        case WhatIfStmt(name, value, target):
            suffix = f" show {target.text}" if target else ""
            return f"(whatif {name.text} {dump(value)}{suffix})"
        case AssertStmt(condition):
            return f"(assert {dump(condition)})"
        case Literal(LiteralType.BOOL, value):
            return "true" if value else "false"
        case Literal(_, value):
            return repr(value)
        case NameRef(name):
            return name
        case UnaryOp(UnaryOperator.NEG, operand):
            return f"(neg {dump(operand)})"
        case UnaryOp(op, operand):
            return f"({op.value} {dump(operand)})"
        case BinaryOp(op, left, right):
            return f"({op.value} {dump(left)} {dump(right)})"
    raise TypeError(f"not an AST node: {node!r}")
