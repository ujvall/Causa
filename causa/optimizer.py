"""Causal IR optimizer (compiler-architecture §5).

Three transformations, applied in one pass in ascending node-ID order:

1. constant folding: an `op` node whose operands are all `const` nodes becomes
   a `const` node with the same ID, location and owner, but only if evaluating
   it cannot raise a runtime error (R101-R103);
2. common-subexpression elimination: an `op`/`const` node identical to an
   earlier node *with the same owner* is replaced by that node;
3. removal: CSE duplicates and `const` nodes left without users are removed.

`input` and `bind` nodes, provenance, binding identities, source text and
actions are never changed, so explain/whatif/impact see the same source-level
graph. No rewrite looks through a binding reference, so `x * 0`, `x - x` and
`b or true` are left untouched.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .ir import (
    Assert, Def, IRModule, IRValidationError, Node, NodeKind, Opcode, Value, format_value, validate_ir,
)
from .semantic import BOOL, FLOAT, INT

INT_MIN, INT_MAX = -(2**63), 2**63 - 1

_SYMBOLS = {
    Opcode.ADD: "+", Opcode.SUB: "-", Opcode.MUL: "*", Opcode.DIV: "/", Opcode.EQ: "==",
    Opcode.NE: "!=", Opcode.LT: "<", Opcode.LE: "<=", Opcode.GT: ">", Opcode.GE: ">=",
    Opcode.AND: "and", Opcode.OR: "or",
}


@dataclass(frozen=True, slots=True)
class Rewrite:
    """One optimizer decision. `action` is fold, skip, cse or remove."""
    action: str
    node: int
    detail: str
    reason: str

    def __str__(self) -> str:
        return f"{self.action} n{self.node}: {self.detail} -- {self.reason}"


@dataclass(frozen=True)
class OptimizationResult:
    module: IRModule
    log: tuple[Rewrite, ...]


class _Unsafe(Exception):
    """Folding would hide a runtime error; carries the error code and reason."""


def evaluate(node: Node, operands: list[Value]) -> Value:
    """Evaluate one op on constant operands with CAUSA semantics (LS §6.3-§6.4).

    Raises _Unsafe when the operation would raise a runtime error at run time.
    Python ints are exact, so int results are range-checked explicitly. Python
    floats are IEEE 754 binary64 with round-to-nearest-even for + - * / and
    int-to-float conversion, which is exactly CAUSA's float semantics; results
    are checked to be finite.
    """
    op = node.opcode
    if op is Opcode.ITOF:
        return float(operands[0])  # correctly rounded, half to even
    if op is Opcode.NOT:
        return not operands[0]
    if op is Opcode.NEG:
        result: Value = -operands[0]
    elif op in (Opcode.AND, Opcode.OR):
        a, b = operands  # both are constants: strict evaluation cannot fail
        return (a and b) if op is Opcode.AND else (a or b)
    elif op in (Opcode.EQ, Opcode.NE, Opcode.LT, Opcode.LE, Opcode.GT, Opcode.GE):
        a, b = operands  # same type; floats are finite, so IEEE comparison is total
        return {Opcode.EQ: a == b, Opcode.NE: a != b, Opcode.LT: a < b,
                Opcode.LE: a <= b, Opcode.GT: a > b, Opcode.GE: a >= b}[op]
    else:
        a, b = operands
        if op is Opcode.DIV:
            if b == 0:  # 0.0 and -0.0
                raise _Unsafe("R101: divisor is zero; division by zero must be raised at run time")
            try:
                result = a / b
            except ArithmeticError:
                raise _Unsafe("R103: result is not a finite float") from None
        else:
            result = {Opcode.ADD: a + b, Opcode.SUB: a - b, Opcode.MUL: a * b}[op]  # type: ignore[index]
    if node.type is INT:
        if not INT_MIN <= result <= INT_MAX:  # type: ignore[operator]
            raise _Unsafe("R102: result is outside the 64-bit int range")
    elif not math.isfinite(result):  # type: ignore[arg-type]
        raise _Unsafe("R103: result is not a finite float")
    return result


def _describe(node: Node, operands: list[Value]) -> str:
    args = [format_value(v) for v in operands]
    op = node.opcode
    assert op is not None
    if op is Opcode.ITOF:
        return f"itof {args[0]}"
    if op is Opcode.NEG:
        return f"neg {args[0]}"
    if op is Opcode.NOT:
        return f"not {args[0]}"
    return f"{args[0]} {_SYMBOLS[op]} {args[1]}"


def _key(node: Node) -> tuple[object, ...]:
    # repr distinguishes 0.0 from -0.0 (which compare equal) and 1 from True.
    return (node.kind, node.type, node.opcode, node.operands, repr(node.value))


def optimize(module: IRModule) -> OptimizationResult:
    """Optimize a validated module. Raises IRValidationError if the input or
    output violates an IR invariant (an internal compiler error)."""
    validate_ir(module)
    log: list[Rewrite] = []
    nodes: dict[int, Node] = {}  # surviving nodes, ascending ID
    alias: dict[int, int] = {}  # CSE: removed node -> surviving equivalent
    seen: dict[tuple[object, ...], int] = {}

    for original in module.nodes:
        node = replace(original, operands=tuple(alias.get(o, o) for o in original.operands))

        if node.kind is NodeKind.OP and all(nodes[o].kind is NodeKind.CONST for o in node.operands):
            values = [nodes[o].value for o in node.operands]  # type: ignore[misc]
            detail = _describe(node, values)  # type: ignore[arg-type]
            try:
                value = evaluate(node, values)  # type: ignore[arg-type]
            except _Unsafe as unsafe:
                log.append(Rewrite("skip", node.id, f"{detail} at {node.line}:{node.column}", str(unsafe)))
            else:
                node = Node(node.id, NodeKind.CONST, node.type, (), node.line, node.column, node.owner,
                            value=value)
                log.append(Rewrite("fold", node.id, f"{detail} -> {format_value(value)}",
                                   "all operands are constants and evaluation cannot fail"))

        if node.kind in (NodeKind.OP, NodeKind.CONST):
            key = (node.owner,) + _key(node)
            if key in seen:
                alias[node.id] = seen[key]
                log.append(Rewrite("cse", node.id, f"replaced by n{seen[key]}",
                                   f"identical {node.kind.value} node with the same owner '{node.owner}'"))
                continue
            seen[key] = node.id
        nodes[node.id] = node

    steps = []
    for step in module.steps:
        if isinstance(step, Assert):
            step = replace(step, root=alias.get(step.root, step.root))
        steps.append(step)

    # Remove consts that lost all users (operands of folded nodes). Only consts
    # are removed besides CSE duplicates: a const cannot raise a runtime error.
    used = {o for n in nodes.values() for o in n.operands}
    used |= {s.root for s in steps if isinstance(s, Assert)}
    for node_id in sorted(nodes):
        if nodes[node_id].kind is NodeKind.CONST and node_id not in used:
            del nodes[node_id]
            log.append(Rewrite("remove", node_id, "const node", "no remaining users"))
    live = set(nodes)
    steps = [s for s in steps if not isinstance(s, Def) or s.node in live]

    result = replace(module, nodes=tuple(nodes.values()), steps=tuple(steps))
    validate_ir(result)  # re-derives the binding-level graph and compares it with provenance
    _check_preserved(module, result)
    return OptimizationResult(result, tuple(log))


def _check_preserved(before: IRModule, after: IRModule) -> None:
    """Source-level identity must be untouched: anchors, actions and provenance."""
    if after.provenance is not before.provenance or after.bindings != before.bindings:
        raise IRValidationError("optimizer changed bindings or provenance")
    old, new = before._index(), after._index()
    for anchor_id in before.bindings.values():
        a, b = old[anchor_id], new.get(anchor_id)
        if b is None or replace(a, operands=()) != replace(b, operands=()):
            raise IRValidationError(f"optimizer changed anchor node n{anchor_id}")
    actions = [s for s in before.steps if not isinstance(s, Def)]
    kept = [s for s in after.steps if not isinstance(s, Def)]
    if [type(s) for s in actions] != [type(s) for s in kept]:
        raise IRValidationError("optimizer added, removed or reordered an action")
    for a, b in zip(actions, kept):
        if isinstance(a, Assert) and isinstance(b, Assert):
            a = replace(a, root=0)
            b = replace(b, root=0)
        if a != b:
            raise IRValidationError("optimizer changed an action")
    if any(n.kind in (NodeKind.INPUT, NodeKind.BIND) for n in old.values() if n.id not in new):
        raise IRValidationError("optimizer removed an input or bind node")


def format_log(log: tuple[Rewrite, ...]) -> str:
    return "\n".join(f"  {r}" for r in log) if log else "  (no changes)"
