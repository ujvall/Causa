"""Semantic analysis (language-specification §5-§8, compiler-architecture §2.3).

`analyze` consumes statements in source order and returns a `SemanticProgram`
or raises the first `CausaError` (E301-E304, E401-E403). The AST is never
modified: types, overrides and dependencies are recorded alongside it.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Iterable

from .astnodes import (
    AssertStmt, BinaryOp, BinaryOperator, ExplainStmt, Expr, ImpactStmt, InputDecl,
    LetDecl, Literal, LiteralType, Name, NameRef, Program, ShowStmt, Statement, UnaryOp,
    UnaryOperator, WhatIfStmt,
)
from .diagnostics import CausaError


class CausaType(enum.Enum):
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"


class BindingKind(enum.Enum):
    INPUT = "input"
    LET = "let"


INT, FLOAT, BOOL = CausaType.INT, CausaType.FLOAT, CausaType.BOOL
_NUMERIC = (INT, FLOAT)
LITERAL_TYPES = {LiteralType.INT: INT, LiteralType.FLOAT: FLOAT, LiteralType.BOOL: BOOL}

_ARITHMETIC = {BinaryOperator.ADD, BinaryOperator.SUB, BinaryOperator.MUL}
_ORDERING = {BinaryOperator.LT, BinaryOperator.LE, BinaryOperator.GT, BinaryOperator.GE}
_EQUALITY = {BinaryOperator.EQ, BinaryOperator.NE}
_LOGICAL = {BinaryOperator.AND, BinaryOperator.OR}


# ---- typing rules (LS §6.3), shared with the IR builder -----------------------

def binary_signature(op: BinaryOperator, left: CausaType, right: CausaType) -> tuple[CausaType, CausaType] | None:
    """Return (operand type after promotion, result type), or None if ill-typed."""
    both_numeric = left in _NUMERIC and right in _NUMERIC
    common = INT if left is INT and right is INT else FLOAT
    if op in _ARITHMETIC and both_numeric:
        return common, common
    if op is BinaryOperator.DIV and both_numeric:
        return FLOAT, FLOAT  # always true division
    if op in _ORDERING and both_numeric:
        return common, BOOL
    if op in _EQUALITY:
        if both_numeric:
            return common, BOOL
        if left is BOOL and right is BOOL:
            return BOOL, BOOL
    if op in _LOGICAL and left is BOOL and right is BOOL:
        return BOOL, BOOL
    return None


def unary_signature(op: UnaryOperator, operand: CausaType) -> CausaType | None:
    if op is UnaryOperator.NEG and operand in _NUMERIC:
        return operand
    if op is UnaryOperator.NOT and operand is BOOL:
        return BOOL
    return None


def referenced_names(expr: Expr) -> tuple[str, ...]:
    """Distinct binding names referenced in `expr`, in order of first appearance."""
    seen: dict[str, None] = {}

    def walk(e: Expr) -> None:
        match e:
            case NameRef(name):
                seen.setdefault(name)
            case UnaryOp(_, operand):
                walk(operand)
            case BinaryOp(_, left, right):
                walk(left)
                walk(right)

    walk(expr)
    return tuple(seen)


# ---- semantic representation ---------------------------------------------------

@dataclass(frozen=True, slots=True)
class Symbol:
    name: str
    kind: BindingKind
    type: CausaType
    index: int  # declaration index, 0-based
    declaration: InputDecl | LetDecl
    direct_deps: tuple[str, ...]  # first-appearance order in the expression
    transitive_deps: frozenset[str]


@dataclass(frozen=True, slots=True)
class Override:
    """A validated whatif override. `literal` is the untouched AST node."""
    input: str  # the overridden input's name
    literal: Literal
    type: CausaType  # the input's type
    value: int | float | bool  # normalized: promoted to float if needed
    promoted: bool


@dataclass(frozen=True)
class SemanticProgram:
    program: Program
    symbols: dict[str, Symbol]  # insertion order = declaration order
    visible: tuple[int, ...]  # per statement: number of bindings declared before it
    overrides: dict[int, tuple[Override, ...]]  # statement index -> whatif overrides, statement order
    expr_types: dict[int, CausaType]  # id(expr node) -> static type

    def type_of(self, expr: Expr) -> CausaType:
        return self.expr_types[id(expr)]


def analyze(statements: Program | Iterable[Statement]) -> SemanticProgram:
    """Check statements in source order; raise the first CausaError found.

    Accepts a parsed Program or a statement iterator (Parser.iter_statements),
    so a semantic error is reported before a syntax error on a later line.
    """
    if isinstance(statements, Program):
        statements = statements.statements
    analyzer = _Analyzer()
    for statement in statements:
        analyzer.statement(statement)
    return SemanticProgram(
        Program(tuple(analyzer.statements)), analyzer.symbols, tuple(analyzer.visible),
        analyzer.overrides, analyzer.types,
    )


class _Analyzer:
    def __init__(self) -> None:
        self.symbols: dict[str, Symbol] = {}
        self.statements: list[Statement] = []
        self.visible: list[int] = []
        self.overrides: dict[int, tuple[Override, ...]] = {}
        self.types: dict[int, CausaType] = {}

    def statement(self, stmt: Statement) -> None:
        index = len(self.statements)
        self.visible.append(len(self.symbols))
        match stmt:
            case InputDecl(name, value):
                self._check_new(name)
                self._declare(name, BindingKind.INPUT, LITERAL_TYPES[value.type], stmt, ())
            case LetDecl(name, value):
                self._check_new(name)  # E302 is located before the expression
                type_ = self._expr(value)
                self._declare(name, BindingKind.LET, type_, stmt, referenced_names(value))
            case ShowStmt(name) | ExplainStmt(name) | ImpactStmt(name):
                self._lookup(name)
            case WhatIfStmt():
                self.overrides[index] = self._whatif(stmt)
            case AssertStmt(condition):
                if self._expr(condition) is not BOOL:
                    raise CausaError("E402", f"an assertion needs a bool condition, found {self.types[id(condition)].value}",
                                 condition.span.line, condition.span.column)
            case _:
                raise TypeError(f"not a statement: {stmt!r}")
        self.statements.append(stmt)

    # ---- names ---------------------------------------------------------------

    def _check_new(self, name: Name) -> None:
        if name.text in self.symbols:
            first = self.symbols[name.text].declaration.name.span
            raise CausaError("E302", f"'{name.text}' is already declared on line {first.line}",
                         name.span.line, name.span.column)

    def _declare(self, name: Name, kind: BindingKind, type_: CausaType,
                 declaration: InputDecl | LetDecl, direct: tuple[str, ...]) -> None:
        transitive = frozenset(direct).union(*(self.symbols[d].transitive_deps for d in direct))
        self.symbols[name.text] = Symbol(name.text, kind, type_, len(self.symbols),
                                         declaration, direct, transitive)

    def _lookup(self, name: Name | NameRef) -> Symbol:
        text = name.text if isinstance(name, Name) else name.name
        symbol = self.symbols.get(text)
        if symbol is None:
            raise CausaError("E301", f"'{text}' is not declared on an earlier line",
                         name.span.line, name.span.column)
        return symbol

    # ---- expressions (post-order: the first error found is the earliest) ------

    def _expr(self, expr: Expr) -> CausaType:
        match expr:
            case Literal(literal_type):
                type_ = LITERAL_TYPES[literal_type]
            case NameRef():
                type_ = self._lookup(expr).type
            case UnaryOp(op, operand, op_span):
                operand_type = self._expr(operand)
                result = unary_signature(op, operand_type)
                if result is None:
                    need = "a numeric operand" if op is UnaryOperator.NEG else "a bool operand"
                    raise CausaError("E401", f"operator '{op.value}' requires {need}, found {operand_type.value}",
                                 op_span.line, op_span.column)
                type_ = result
            case BinaryOp(op, left, right, op_span):
                lt, rt = self._expr(left), self._expr(right)
                signature = binary_signature(op, lt, rt)
                if signature is None:
                    raise CausaError("E401", f"operator '{op.value}' {_requirement(op)}, found {lt.value} and {rt.value}",
                                 op_span.line, op_span.column)
                type_ = signature[1]
            case _:
                raise TypeError(f"not an expression: {expr!r}")
        self.types[id(expr)] = type_
        return type_

    # ---- whatif (LS §8.5.1) ---------------------------------------------------

    def _whatif(self, stmt: WhatIfStmt) -> tuple[Override, ...]:
        """Check each override in source order (E301, E303, E305, E403), then the target."""
        overrides: list[Override] = []
        for clause in stmt.overrides:
            symbol = self._lookup(clause.name)
            span = clause.name.span
            if symbol.kind is not BindingKind.INPUT:
                raise CausaError("E303", f"'{symbol.name}' is a let binding; whatif can only override inputs",
                                 span.line, span.column)
            if any(o.input == symbol.name for o in overrides):
                raise CausaError("E305", f"input '{symbol.name}' is overridden more than once in this whatif",
                                 span.line, span.column)
            literal = clause.value
            literal_type = LITERAL_TYPES[literal.type]
            if literal_type is symbol.type:
                overrides.append(Override(symbol.name, literal, symbol.type, literal.value, promoted=False))
            elif literal_type is INT and symbol.type is FLOAT:
                overrides.append(Override(symbol.name, literal, FLOAT, float(literal.value), promoted=True))
            else:
                raise CausaError("E403", f"cannot override {symbol.type.value} input '{symbol.name}' "
                                         f"with a {literal_type.value} literal",
                                 literal.span.line, literal.span.column)
        if stmt.target is not None:
            target = self._lookup(stmt.target)
            names = [o.input for o in overrides]
            if target.kind is BindingKind.INPUT:
                reason = "is an input; a whatif target must be a let binding"
            elif not target.transitive_deps.intersection(names):
                reason = "does not depend on " + " or ".join(f"'{n}'" for n in names)
            else:
                reason = ""
            if reason:
                raise CausaError("E304", f"whatif target '{target.name}' {reason}",
                                 stmt.target.span.line, stmt.target.span.column)
        return tuple(overrides)


def _requirement(op: BinaryOperator) -> str:
    if op in _LOGICAL:
        return "requires bool operands"
    if op in _EQUALITY:
        return "requires two numeric or two bool operands"
    return "requires numeric operands"
