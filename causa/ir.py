"""Causal IR: data structures, builder, provenance and validation
(compiler-architecture §3-§4).

Canonical edge direction: a node's `operands` are the nodes it uses
(user -> used). Reverse relations (dependents) are derived indexes only.
"""

from __future__ import annotations

import enum
import heapq
from dataclasses import dataclass, field
from typing import Union

from .astnodes import (
    AssertStmt, BinaryOp, BinaryOperator, ExplainStmt, Expr, ImpactStmt, InputDecl, LetDecl,
    Literal, NameRef, ShowStmt, UnaryOp, UnaryOperator, WhatIfStmt,
)
from .semantic import (
    BOOL, FLOAT, INT, LITERAL_TYPES, BindingKind, CausaType, SemanticProgram,
    binary_signature, referenced_names,
)


class NodeKind(enum.Enum):
    INPUT = "input"
    CONST = "const"
    OP = "op"
    BIND = "bind"


class Opcode(enum.Enum):
    ADD = "add"
    SUB = "sub"
    MUL = "mul"
    DIV = "div"
    NEG = "neg"
    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"
    AND = "and"
    OR = "or"
    NOT = "not"
    ITOF = "itof"


_BINARY_OPCODES = {
    BinaryOperator.ADD: Opcode.ADD, BinaryOperator.SUB: Opcode.SUB, BinaryOperator.MUL: Opcode.MUL,
    BinaryOperator.DIV: Opcode.DIV, BinaryOperator.EQ: Opcode.EQ, BinaryOperator.NE: Opcode.NE,
    BinaryOperator.LT: Opcode.LT, BinaryOperator.LE: Opcode.LE, BinaryOperator.GT: Opcode.GT,
    BinaryOperator.GE: Opcode.GE, BinaryOperator.AND: Opcode.AND, BinaryOperator.OR: Opcode.OR,
}
_UNARY_OPCODES = {UnaryOperator.NEG: Opcode.NEG, UnaryOperator.NOT: Opcode.NOT}

Value = Union[int, float, bool]


# ---- nodes and steps -------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Node:
    id: int
    kind: NodeKind
    type: CausaType
    operands: tuple[int, ...]  # direct dependency edges: this node uses these
    line: int
    column: int
    owner: str  # binding name, or "assert#K" for the K-th assert (0-based)
    opcode: Opcode | None = None  # op nodes
    name: str | None = None  # input and bind nodes
    value: Value | None = None  # const value; input default
    source_text: str | None = None  # bind nodes


@dataclass(frozen=True, slots=True)
class Def:
    node: int


@dataclass(frozen=True, slots=True)
class Show:
    anchor: int
    line: int


@dataclass(frozen=True, slots=True)
class Explain:
    anchor: int
    line: int


@dataclass(frozen=True, slots=True)
class Impact:
    anchor: int
    visible: int  # number of bindings declared before the statement
    line: int


@dataclass(frozen=True, slots=True)
class WhatIf:
    input: int  # input anchor
    value: Value  # normalized to the input's type (promoted if needed)
    value_type: CausaType
    source_value: Value  # literal as written (after its sign)
    promoted: bool
    target: int | None  # bind anchor for the targeted form, None for the full form
    visible: int
    line: int
    value_line: int  # location of the override literal
    value_column: int


@dataclass(frozen=True, slots=True)
class Assert:
    root: int  # node computing the condition
    source_text: str
    refs: tuple[int, ...]  # anchors referenced, first appearance order
    line: int
    column: int


Step = Union[Def, Show, Explain, Impact, WhatIf, Assert]


# ---- provenance (binding-level graph, §4) ----------------------------------

@dataclass(frozen=True, slots=True)
class BindingInfo:
    name: str
    kind: BindingKind
    type: CausaType
    anchor: int
    index: int  # declaration index
    line: int
    column: int
    source_text: str | None  # lets only
    direct_deps: tuple[str, ...]  # declaration order
    references: tuple[str, ...]  # same set, first-appearance order in the expression


@dataclass(frozen=True)
class Provenance:
    bindings: tuple[BindingInfo, ...]  # declaration order
    by_name: dict[str, BindingInfo] = field(init=False, compare=False, repr=False)
    direct_dependents: dict[str, tuple[str, ...]] = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        by_name = {b.name: b for b in self.bindings}
        dependents: dict[str, list[str]] = {b.name: [] for b in self.bindings}
        for b in self.bindings:  # declaration order, so each list is ordered too
            for dep in b.direct_deps:
                dependents[dep].append(b.name)
        object.__setattr__(self, "by_name", by_name)
        object.__setattr__(self, "direct_dependents", {k: tuple(v) for k, v in dependents.items()})

    def transitive_deps(self, name: str) -> tuple[str, ...]:
        return self._closure(name, lambda n: self.by_name[n].direct_deps)

    def all_dependents(self, name: str) -> tuple[str, ...]:
        return self._closure(name, lambda n: self.direct_dependents[n])

    def _closure(self, start: str, step) -> tuple[str, ...]:
        seen: set[str] = set()
        stack = list(step(start))
        while stack:
            n = stack.pop()
            if n not in seen:
                seen.add(n)
                stack.extend(step(n))
        return tuple(sorted(seen, key=lambda n: self.by_name[n].index))


@dataclass(frozen=True)
class IRModule:
    source_file: str
    nodes: tuple[Node, ...]  # ascending ID
    steps: tuple[Step, ...]
    bindings: dict[str, int]  # name -> anchor node ID, declaration order
    provenance: Provenance

    def node(self, node_id: int) -> Node:
        return self._index()[node_id]

    def _index(self) -> dict[int, Node]:
        return {n.id: n for n in self.nodes}


# ---- builder ----------------------------------------------------------------

def build_ir(sem: SemanticProgram, source_file: str = "<source>") -> IRModule:
    """Lower a checked program to unoptimized Causal IR (CA §3.3 ID order)."""
    builder = _Builder(sem)
    for index, statement in enumerate(sem.program.statements):
        builder.statement(index, statement)
    nodes = tuple(builder.nodes)
    provenance = derive_provenance(nodes, builder.anchors, sem)
    return IRModule(source_file, nodes, tuple(builder.steps), dict(builder.anchors), provenance)


class _Builder:
    def __init__(self, sem: SemanticProgram) -> None:
        self.sem = sem
        self.nodes: list[Node] = []
        self.steps: list[Step] = []
        self.anchors: dict[str, int] = {}
        self.owner = ""
        self.asserts = 0

    def _new(self, kind: NodeKind, type_: CausaType, operands: tuple[int, ...], line: int, column: int,
             **extra: object) -> int:
        node_id = len(self.nodes)
        self.nodes.append(Node(node_id, kind, type_, operands, line, column, self.owner, **extra))  # type: ignore[arg-type]
        self.steps.append(Def(node_id))
        return node_id

    def statement(self, index: int, stmt: object) -> None:
        match stmt:
            case InputDecl(name, value):
                self.owner = name.text
                self.anchors[name.text] = self._new(
                    NodeKind.INPUT, LITERAL_TYPES[value.type], (), name.span.line, name.span.column,
                    name=name.text, value=value.value)
            case LetDecl(name, value, source_text):
                self.owner = name.text
                root = self._lower(value)
                self.anchors[name.text] = self._new(
                    NodeKind.BIND, self.sem.type_of(value), (root,), name.span.line, name.span.column,
                    name=name.text, source_text=source_text)
            case ShowStmt(name, span):
                self.steps.append(Show(self.anchors[name.text], span.line))
            case ExplainStmt(name, span):
                self.steps.append(Explain(self.anchors[name.text], span.line))
            case ImpactStmt(name, span):
                self.steps.append(Impact(self.anchors[name.text], self.sem.visible[index], span.line))
            case WhatIfStmt(name, value, target, span):
                override = self.sem.overrides[index]
                self.steps.append(WhatIf(
                    self.anchors[name.text], override.value, override.type, value.value, override.promoted,
                    self.anchors[target.text] if target else None, self.sem.visible[index], span.line,
                    value.span.line, value.span.column))
            case AssertStmt(condition, source_text, span):
                self.owner = f"assert#{self.asserts}"
                self.asserts += 1
                root = self._lower(condition)
                refs = tuple(self.anchors[n] for n in referenced_names(condition))
                self.steps.append(Assert(root, source_text, refs, span.line, span.column))
            case _:
                raise TypeError(f"not a statement: {stmt!r}")

    def _lower(self, expr: Expr) -> int:
        """Post-order: left, right, itof(left), itof(right), op."""
        match expr:
            case Literal(literal_type, value, span):
                return self._new(NodeKind.CONST, LITERAL_TYPES[literal_type], (), span.line, span.column, value=value)
            case NameRef(name):
                return self.anchors[name]  # references create no node
            case UnaryOp(op, operand, op_span):
                o = self._lower(operand)
                return self._new(NodeKind.OP, self.sem.type_of(expr), (o,), op_span.line, op_span.column,
                                 opcode=_UNARY_OPCODES[op])
            case BinaryOp(op, left, right, op_span):
                lt, rt = self.sem.type_of(left), self.sem.type_of(right)
                signature = binary_signature(op, lt, rt)
                assert signature is not None, "semantic analysis accepted an ill-typed operator"
                operand_type, result_type = signature
                lhs, rhs = self._lower(left), self._lower(right)
                if lt is not operand_type:
                    lhs = self._itof(lhs, left)
                if rt is not operand_type:
                    rhs = self._itof(rhs, right)
                return self._new(NodeKind.OP, result_type, (lhs, rhs), op_span.line, op_span.column,
                                 opcode=_BINARY_OPCODES[op])
        raise TypeError(f"not an expression: {expr!r}")

    def _itof(self, node_id: int, operand: Expr) -> int:
        return self._new(NodeKind.OP, FLOAT, (node_id,), operand.span.line, operand.span.column, opcode=Opcode.ITOF)


def anchor_deps(nodes_by_id: dict[int, Node], anchor: Node) -> set[int]:
    """Anchors reached from a bind node by walking operands, stopping at anchors (CA §4)."""
    found: set[int] = set()
    stack = list(anchor.operands)
    while stack:
        node = nodes_by_id[stack.pop()]
        if node.kind in (NodeKind.INPUT, NodeKind.BIND):
            found.add(node.id)
        else:
            stack.extend(node.operands)
    return found


def derive_provenance(nodes: tuple[Node, ...], anchors: dict[str, int], sem: SemanticProgram) -> Provenance:
    by_id = {n.id: n for n in nodes}
    names = {node_id: name for name, node_id in anchors.items()}
    infos = []
    for index, (name, anchor_id) in enumerate(anchors.items()):
        anchor = by_id[anchor_id]
        deps = sorted(anchor_deps(by_id, anchor))  # anchor IDs follow declaration order
        symbol = sem.symbols[name]
        infos.append(BindingInfo(
            name, symbol.kind, anchor.type, anchor_id, index, anchor.line, anchor.column,
            anchor.source_text, tuple(names[d] for d in deps), symbol.direct_deps))
    return Provenance(tuple(infos))


# ---- ordering and validation ------------------------------------------------

class IRValidationError(Exception):
    """An internal compiler error: the IR violates an invariant. Never a user diagnostic."""


def topological_order(module: IRModule) -> tuple[int, ...]:
    """Kahn's algorithm, smallest ready ID first: deterministic."""
    users: dict[int, list[int]] = {n.id: [] for n in module.nodes}
    pending = {n.id: len(set(n.operands)) for n in module.nodes}
    for n in module.nodes:
        for o in set(n.operands):
            users[o].append(n.id)
    ready = [i for i, count in pending.items() if count == 0]
    heapq.heapify(ready)
    order: list[int] = []
    while ready:
        i = heapq.heappop(ready)
        order.append(i)
        for u in users[i]:
            pending[u] -= 1
            if pending[u] == 0:
                heapq.heappush(ready, u)
    if len(order) != len(module.nodes):
        raise IRValidationError("node graph has a cycle")
    return tuple(order)


_ARITH = {Opcode.ADD, Opcode.SUB, Opcode.MUL}
_CMP = {Opcode.EQ, Opcode.NE, Opcode.LT, Opcode.LE, Opcode.GT, Opcode.GE}


def _check_op(node: Node, operand_types: list[CausaType]) -> str | None:
    """Return a problem description if an op node's types are inconsistent."""
    op, t = node.opcode, node.type
    if op is Opcode.ITOF:
        return None if operand_types == [INT] and t is FLOAT else "itof must convert int to float"
    if op is Opcode.NEG:
        return None if len(operand_types) == 1 and operand_types[0] in (INT, FLOAT) and t is operand_types[0] else "bad neg"
    if op is Opcode.NOT:
        return None if operand_types == [BOOL] and t is BOOL else "bad not"
    if len(operand_types) != 2 or operand_types[0] is not operand_types[1]:
        return "binary operands must have exactly the same type"
    ot = operand_types[0]
    if op in _ARITH:
        return None if ot in (INT, FLOAT) and t is ot else "bad arithmetic types"
    if op is Opcode.DIV:
        return None if ot is FLOAT and t is FLOAT else "div operands and result must be float"
    if op in _CMP:
        ok = t is BOOL and (ot in (INT, FLOAT) or (ot is BOOL and op in (Opcode.EQ, Opcode.NE)))
        return None if ok else "bad comparison types"
    if op in (Opcode.AND, Opcode.OR):
        return None if ot is BOOL and t is BOOL else "bad boolean types"
    return "unknown opcode"


def validate_ir(module: IRModule) -> None:
    """Check every Causal IR invariant; raise IRValidationError on the first violation."""
    def fail(message: str) -> None:
        raise IRValidationError(message)

    by_id: dict[int, Node] = {}
    for node in module.nodes:
        if by_id and node.id <= node_before.id:  # noqa: F821 (set at loop end)
            fail(f"n{node.id}: node IDs must be unique and ascending")
        for o in node.operands:
            if o not in by_id:
                fail(f"n{node.id}: operand n{o} is undefined or not earlier (edges must point to earlier nodes)")
        types = [by_id[o].type for o in node.operands]
        if node.kind in (NodeKind.INPUT, NodeKind.CONST):
            if node.operands:
                fail(f"n{node.id}: {node.kind.value} nodes have no operands")
            expected = {bool: BOOL, int: INT, float: FLOAT}.get(type(node.value))
            if expected is not node.type:
                fail(f"n{node.id}: value {node.value!r} does not have type {node.type.value}")
        elif node.kind is NodeKind.BIND:
            if len(node.operands) != 1 or types[0] is not node.type:
                fail(f"n{node.id}: bind needs exactly one operand of its own type")
            if node.owner != node.name or node.source_text is None:
                fail(f"n{node.id}: bind must be owned by its binding and keep its source text")
        else:
            problem = _check_op(node, types)
            if problem:
                fail(f"n{node.id}: {problem}")
        by_id[node.id] = node
        node_before = node

    # bindings: distinct identities, anchors are input/bind nodes of that name
    anchor_ids = list(module.bindings.values())
    if len(set(anchor_ids)) != len(anchor_ids):
        fail("two bindings share an anchor node")
    for name, anchor_id in module.bindings.items():
        anchor = by_id.get(anchor_id)
        if anchor is None or anchor.kind not in (NodeKind.INPUT, NodeKind.BIND) or anchor.name != name:
            fail(f"binding '{name}' does not anchor on its own input/bind node")
    for node in module.nodes:
        if node.kind in (NodeKind.INPUT, NodeKind.BIND) and module.bindings.get(node.name or "") != node.id:
            fail(f"n{node.id}: input/bind node is not a registered binding")
    if anchor_ids != sorted(anchor_ids):
        fail("bindings are not in declaration order")

    # provenance: matches the node graph, deps are earlier declarations
    prov = module.provenance
    if [b.name for b in prov.bindings] != list(module.bindings):
        fail("provenance bindings differ from module bindings")
    for b in prov.bindings:
        anchor = by_id[b.anchor]
        if b.anchor != module.bindings[b.name] or b.type is not anchor.type:
            fail(f"provenance for '{b.name}' does not match its anchor")
        if (b.kind is BindingKind.INPUT) != (anchor.kind is NodeKind.INPUT):
            fail(f"'{b.name}': input bindings must anchor on input nodes (inputs are never folded)")
        derived = sorted(anchor_deps(by_id, anchor)) if anchor.kind is NodeKind.BIND else []
        if [module.bindings[d] for d in b.direct_deps] != derived:
            fail(f"provenance deps of '{b.name}' differ from the node graph")
        if set(b.references) != set(b.direct_deps):
            fail(f"'{b.name}': expression references differ from direct dependencies")
        if any(prov.by_name[d].index >= b.index for d in b.direct_deps):
            fail(f"'{b.name}' depends on a binding that is not declared earlier")

    # deterministic topological order = ascending IDs
    order = topological_order(module)
    if list(order) != [n.id for n in module.nodes]:
        fail("ascending node IDs are not the deterministic topological order")

    # steps: every node defined once in order; actions use defined entities
    defined: list[int] = []
    for step in module.steps:
        if isinstance(step, Def):
            if step.node not in by_id or (defined and step.node <= defined[-1]):
                fail(f"def n{step.node} is unknown, repeated or out of order")
            defined.append(step.node)
            continue
        done = set(defined)
        visible = sum(1 for a in anchor_ids if a in done)
        if isinstance(step, (Show, Explain, Impact)):
            if step.anchor not in done or step.anchor not in anchor_ids:
                fail(f"{type(step).__name__.lower()} refers to an undefined binding")
            if isinstance(step, Impact) and step.visible != visible:
                fail("impact visibility count is wrong")
        elif isinstance(step, WhatIf):
            node = by_id.get(step.input)
            if step.input not in done or node is None or node.kind is not NodeKind.INPUT:
                fail("whatif must override a defined input")
            assert node is not None
            value_type = {bool: BOOL, int: INT, float: FLOAT}.get(type(step.value))
            if step.value_type is not node.type or value_type is not node.type or step.visible != visible:
                fail("whatif value type or visibility is wrong")
            if step.target is not None:
                target = by_id.get(step.target)
                if (step.target not in done or target is None or target.kind is not NodeKind.BIND
                        or node.name not in prov.transitive_deps(target.name or "")):
                    fail("whatif target must be a defined let that transitively depends on the input")
        elif isinstance(step, Assert):
            if step.root not in done or by_id[step.root].type is not BOOL:
                fail("assert condition must be a defined bool node")
            if any(r not in done or r not in anchor_ids for r in step.refs):
                fail("assert refs must be defined bindings")
    if defined != [n.id for n in module.nodes]:
        fail("steps do not define every node exactly once")


def check_against_program(module: IRModule, sem: SemanticProgram) -> None:
    """Direct dependencies must equal the names each let's AST expression references."""
    for stmt in sem.program.statements:
        if isinstance(stmt, LetDecl):
            info = module.provenance.by_name[stmt.name.text]
            if info.references != referenced_names(stmt.value):
                raise IRValidationError(f"'{stmt.name.text}': dependencies differ from its AST expression")


# ---- text form (matches compiler-architecture §3.6) -------------------------

def format_value(value: Value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return repr(value)


def format_node(node: Node) -> str:
    kind = f"op {node.opcode.value}" if node.opcode else node.kind.value
    operands = ", ".join(f"n{o}" for o in node.operands)
    if node.kind is NodeKind.INPUT:
        extra = f"name={node.name} default={format_value(node.value)}"  # type: ignore[arg-type]
    elif node.kind is NodeKind.CONST:
        extra = f"value={format_value(node.value)}"  # type: ignore[arg-type]
    elif node.kind is NodeKind.BIND:
        extra = f'name={node.name} source_text="{node.source_text}"'
    else:
        extra = ""
    line = (f"{'n' + str(node.id):<4}= {kind:<14}{operands:<16}{node.type.value:<8}"
            f"{f'{node.line}:{node.column}':<8}{node.owner:<11}{extra}")
    return line.rstrip()


def format_step(step: Step, module: IRModule) -> str:
    def ref(anchor: int) -> str:
        return f"n{anchor} ({module.node(anchor).name})"

    match step:
        case Def(node):
            return f"def n{node}"
        case Show(anchor):
            return f"show {ref(anchor)}"
        case Explain(anchor):
            return f"explain {ref(anchor)}"
        case Impact(anchor, visible):
            return f"impact {ref(anchor)} visible={visible}"
        case WhatIf():
            promoted = f" (promoted from {format_value(step.source_value)})" if step.promoted else ""
            target = f" show {ref(step.target)}" if step.target is not None else ""
            return (f"whatif {ref(step.input)} = {format_value(step.value)}{promoted}{target} "
                    f"visible={step.visible}")
        case Assert(root, source_text, refs):
            return f'assert n{root} "{source_text}" refs=[{", ".join(f"n{r}" for r in refs)}]'
    raise TypeError(step)


def format_ir(module: IRModule, optimized: bool = False) -> str:
    state = "optimized" if optimized else "unoptimized"
    lines = [f"; Causal IR ({state}) for {module.source_file}",
             "; id   kind/opcode  operands        type    loc     owner      extra"]
    lines += [format_node(n) for n in module.nodes]
    lines += ["", "steps:"] + [f"  {format_step(s, module)}" for s in module.steps]
    lines += ["", "bindings: " + ", ".join(f"{k} -> n{v}" for k, v in module.bindings.items())]
    lines += ["", "provenance (direct dependencies, declaration order):"]
    for b in module.provenance.bindings:
        deps = ", ".join(b.direct_deps) or "(none)"
        lines.append(f"  {b.name}: {b.kind.value} {b.type.value} -> {deps}")
    return "\n".join(lines)
