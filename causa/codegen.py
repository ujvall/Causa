"""C code generator (compiler-architecture §6, §6.4).

Consumes validated (normally optimized) Causal IR and emits one deterministic
C99 translation unit containing:

* `causa_eval_node`: one `case` per IR node, computing `env[id]` from its
  operands with checked arithmetic from `causa_runtime.h`;
* metadata tables (`CAUSA_PROGRAM`): nodes, bindings with their direct
  dependencies, first-appearance references and dependents, and asserts;
* `main`: the IR steps in order -- evaluate each node, call the runtime for
  each action.

Each IR node is its own C statement on already-computed values, so C operator
precedence never matters and `and`/`or` stay strict (both operand nodes are
evaluated before the operator node).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .ir import (
    Assert, Def, Explain, Impact, IRModule, Node, NodeKind, Opcode, Show, Step, Value, WhatIf,
    format_value, validate_ir,
)
from .semantic import BOOL, FLOAT, INT, BindingKind, CausaType

RUNTIME_DIR = Path(__file__).resolve().parent / "runtime"
RUNTIME_SOURCE = RUNTIME_DIR / "causa_runtime.c"
INT64_MIN = -(2**63)

_MEMBER = {INT: "i", FLOAT: "f", BOOL: "b"}
_C_TYPE = {INT: "CAUSA_TYPE_INT", FLOAT: "CAUSA_TYPE_FLOAT", BOOL: "CAUSA_TYPE_BOOL"}
_C_NODE_KIND = {NodeKind.INPUT: "CAUSA_NODE_INPUT", NodeKind.CONST: "CAUSA_NODE_CONST",
                NodeKind.OP: "CAUSA_NODE_OP", NodeKind.BIND: "CAUSA_NODE_BIND"}
_CHECKED = {  # (opcode, operand type) -> checked helper
    (Opcode.ADD, INT): "causa_add_i64", (Opcode.SUB, INT): "causa_sub_i64",
    (Opcode.MUL, INT): "causa_mul_i64", (Opcode.ADD, FLOAT): "causa_add_f64",
    (Opcode.SUB, FLOAT): "causa_sub_f64", (Opcode.MUL, FLOAT): "causa_mul_f64",
    (Opcode.DIV, FLOAT): "causa_div_f64",
}
_C_OPERATOR = {Opcode.EQ: "==", Opcode.NE: "!=", Opcode.LT: "<", Opcode.LE: "<=", Opcode.GT: ">",
               Opcode.GE: ">=", Opcode.AND: "&&", Opcode.OR: "||"}
# Runtime library functions per action (declared in causa_runtime.h, defined in causa_runtime.c).
RUNTIME_FUNCTIONS = {Show: "causa_show", Explain: "causa_explain", WhatIf: "causa_whatif",
                     Impact: "causa_impact", Assert: "causa_assert"}


class CodegenError(Exception):
    """The backend cannot produce the requested output (not a CAUSA language error)."""


@dataclass(frozen=True)
class CProgram:
    source: str
    # Runtime library functions the program calls, in first-use order, with the
    # source line of each first use. Empty: causa_runtime.h alone suffices.
    runtime_calls: tuple[tuple[str, int], ...]

    @property
    def standalone(self) -> bool:
        return not self.runtime_calls


def binding_identifier(name: str) -> str:
    """C enum constant for a binding. CAUSA names are [A-Za-z_][A-Za-z0-9_]*, the
    prefix makes them valid, keyword-free and outside the runtime's namespace
    (the runtime never declares CAUSA_BINDING_*)."""
    return f"CAUSA_BINDING_{name}"


def c_string(text: str) -> str:
    out = []
    for ch in text:
        if ch in '\\"':
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\n")
        elif " " <= ch <= "~":
            out.append(ch)
        else:  # outside printable ASCII: exact UTF-8 bytes as octal escapes
            out.extend(f"\\{b:03o}" for b in ch.encode("utf-8"))
    return '"' + "".join(out) + '"'


def _comment(text: str) -> str:
    return text.replace("*/", "* /")


def c_literal(value: Value, type_: CausaType) -> str:
    if type_ is BOOL:
        return "true" if value else "false"
    if type_ is INT:
        return "INT64_MIN" if value == INT64_MIN else f"INT64_C({value})"
    # Hexadecimal float literals are exact: no decimal rounding by the C compiler.
    return f"{float(value).hex()} /* {format_value(value)} */"


def generate_c(module: IRModule, standalone: bool = False) -> CProgram:
    """Emit C for a module. With standalone=True, reject programs that need the
    runtime library (causa_runtime.c) instead of emitting calls to it."""
    validate_ir(module)
    runtime_calls: dict[str, int] = {}
    for step in module.steps:
        function = RUNTIME_FUNCTIONS.get(type(step))  # type: ignore[arg-type]
        if function:
            runtime_calls.setdefault(function, step.line)  # type: ignore[union-attr]
    calls = tuple(runtime_calls.items())
    if standalone and calls:
        uses = ", ".join(f"{f.removeprefix('causa_')} (line {line})" for f, line in calls)
        raise CodegenError(f"cannot emit a standalone program: the CAUSA runtime library "
                           f"(causa_runtime.c) is required by {uses}")
    return CProgram(_Emitter(module, calls).emit(), calls)


class _Emitter:
    def __init__(self, module: IRModule, calls: tuple[tuple[str, int], ...]) -> None:
        self.m = module
        self.calls = calls
        self.nodes = module._index()
        self.index = {b.name: b.index for b in module.provenance.bindings}
        self.binding_of_anchor = {b.anchor: b for b in module.provenance.bindings}
        self.asserts = [s for s in module.steps if isinstance(s, Assert)]
        self.owner_of_assert = {f"assert#{k}": k for k in range(len(self.asserts))}

    def emit(self) -> str:
        parts = [self._header(), self._enum(), self._evaluator(), self._metadata(), self._main()]
        return "\n".join(parts)

    # ---- sections -----------------------------------------------------------

    def _header(self) -> str:
        if self.calls:
            build = (f" * Uses the CAUSA runtime library: {', '.join(f for f, _ in self.calls)}.\n"
                     " * Build: cc -std=c99 -I <causa/runtime> <this file> <causa/runtime>/causa_runtime.c -lm\n")
        else:
            build = (" * Standalone: needs only causa_runtime.h (no runtime library).\n"
                     " * Build: cc -std=c99 -I <causa/runtime> <this file> -lm\n")
        return (f"/* Generated by the CAUSA compiler from {_comment(self.m.source_file)}. Do not edit.\n"
                f"{build} */\n"
                '#include "causa_runtime.h"\n\n'
                f"#define CAUSA_NODE_SLOTS {max(self.nodes) + 1 if self.nodes else 1} /* highest node ID + 1 */\n")

    def _enum(self) -> str:
        if not self.m.provenance.bindings:
            return "/* no bindings */\n"
        lines = ["/* Binding indices, declaration order. */", "enum {"]
        lines += [f"    {binding_identifier(b.name)} = {b.index}," for b in self.m.provenance.bindings]
        return "\n".join(lines + ["};", ""])

    def _evaluator(self) -> str:
        lines = ["int causa_eval_node(int node_id, causa_value *env, causa_error *err)", "{",
                 "    (void)env; /* unused when the program has no nodes */",
                 "    (void)err;", "    switch (node_id) {"]
        for node in self.m.nodes:
            lines.append(f"    case {node.id}: /* {self._describe(node)} */")
            lines += [f"        {s}" for s in self._compute(node)]
        lines += ["    default:", "        err->code = CAUSA_INTERNAL_ERROR;",
                  "        err->line = 0;", "        err->column = 0;",
                  "        return CAUSA_INTERNAL_ERROR;", "    }", "}", ""]
        return "\n".join(lines)

    def _describe(self, node: Node) -> str:
        what = f"op {node.opcode.value}" if node.opcode else node.kind.value
        name = f" {node.name}" if node.name else ""
        text = f": {node.source_text}" if node.source_text else ""
        return _comment(f"n{node.id} {what}{name}{text} @{node.line}:{node.column} owner {node.owner}")

    def _compute(self, node: Node) -> list[str]:
        out = f"env[{node.id}].{_MEMBER[node.type]}"
        if node.kind in (NodeKind.INPUT, NodeKind.CONST):
            return [f"{out} = {c_literal(node.value, node.type)};", "return CAUSA_OK;"]  # type: ignore[arg-type]
        if node.kind is NodeKind.BIND:
            return [f"env[{node.id}] = env[{node.operands[0]}];", "return CAUSA_OK;"]
        args = [f"env[{o}].{_MEMBER[self.nodes[o].type]}" for o in node.operands]
        op = node.opcode
        operand_type = self.nodes[node.operands[0]].type
        helper = _CHECKED.get((op, operand_type))  # type: ignore[arg-type]
        if helper:
            return [f"return causa_check({helper}({args[0]}, {args[1]}, &{out}), "
                    f"{node.line}, {node.column}, err);"]
        if op is Opcode.NEG and node.type is INT:
            return [f"return causa_check(causa_neg_i64({args[0]}, &{out}), {node.line}, {node.column}, err);"]
        if op is Opcode.NEG:
            expr = f"-{args[0]}"  # float negation cannot fail
        elif op is Opcode.NOT:
            expr = f"!{args[0]}"
        elif op is Opcode.ITOF:
            expr = f"(double){args[0]}"
        elif op in _C_OPERATOR:
            expr = f"{args[0]} {_C_OPERATOR[op]} {args[1]}"  # operands already evaluated: strict
        else:
            raise CodegenError(f"no C translation for n{node.id} ({op})")
        return [f"{out} = {expr};", "return CAUSA_OK;"]

    def _metadata(self) -> str:
        prov = self.m.provenance
        lines = ["/* ---- metadata for the runtime (explain, whatif, impact, diagnostics) ---- */"]

        def int_array(name: str, items: list[str]) -> str:
            if not items:
                return "NULL"
            lines.append(f"static const int {name}[] = {{ {', '.join(items)} }};")
            return name

        binding_rows = []
        for b in prov.bindings:
            ids = lambda names: [binding_identifier(n) for n in names]  # noqa: E731
            deps = int_array(f"causa_b{b.index}_deps", ids(b.direct_deps))
            refs = int_array(f"causa_b{b.index}_refs", ids(b.references))
            users = prov.direct_dependents[b.name]
            dependents = int_array(f"causa_b{b.index}_dependents", ids(users))
            kind = "CAUSA_KIND_INPUT" if b.kind is BindingKind.INPUT else "CAUSA_KIND_LET"
            text = c_string(b.source_text) if b.source_text is not None else "NULL"
            binding_rows.append(
                f"    {{ {c_string(b.name)}, {kind}, {_C_TYPE[b.type]}, {b.anchor}, {b.line}, {b.column}, "
                f"{text}, {len(b.direct_deps)}, {deps}, {len(b.references)}, {refs}, "
                f"{len(users)}, {dependents} }},")

        assert_rows = []
        for k, a in enumerate(self.asserts):
            refs = int_array(f"causa_a{k}_refs", [binding_identifier(self.binding_of_anchor[r].name) for r in a.refs])
            assert_rows.append(f"    {{ {a.line}, {a.column}, {c_string(a.source_text)}, {a.root}, "
                               f"{len(a.refs)}, {refs} }},")

        nodes_ref = bindings_ref = asserts_ref = "NULL"  # C has no zero-length arrays
        if self.m.nodes:
            lines += ["", "static const causa_node_info causa_nodes[] = {",
                      "    /* id, kind, type, owner, line, column, operand_count, operands */"]
            for n in self.m.nodes:
                owner = (binding_identifier(n.owner) if n.owner in self.index
                         else f"CAUSA_ASSERT_OWNER({self.owner_of_assert[n.owner]})")
                operands = list(n.operands) + [-1] * (2 - len(n.operands))
                lines.append(f"    {{ {n.id}, {_C_NODE_KIND[n.kind]}, {_C_TYPE[n.type]}, {owner}, {n.line}, "
                             f"{n.column}, {len(n.operands)}, {{ {operands[0]}, {operands[1]} }} }},")
            lines.append("};")
            nodes_ref = "causa_nodes"

        if binding_rows:
            lines += ["", "static const causa_binding_info causa_bindings[] = {",
                      "    /* name, kind, type, anchor, line, column, source_text, deps, refs, dependents */"]
            lines += binding_rows + ["};"]
            bindings_ref = "causa_bindings"
        if assert_rows:
            lines += ["", "static const causa_assert_info causa_asserts[] = {",
                      "    /* line, column, source_text, root, refs */"]
            lines += assert_rows + ["};"]
            asserts_ref = "causa_asserts"
        lines += ["", "const causa_program_info CAUSA_PROGRAM = {",
                  f"    {c_string(self.m.source_file)}, CAUSA_NODE_SLOTS,",
                  f"    {len(self.m.nodes)}, {nodes_ref},",
                  f"    {len(prov.bindings)}, {bindings_ref},",
                  f"    {len(self.asserts)}, {asserts_ref}", "};", ""]
        return "\n".join(lines)

    def _main(self) -> str:
        lines = ["#ifndef CAUSA_NO_MAIN", "int main(void)", "{",
                 "    static causa_value env[CAUSA_NODE_SLOTS];", "    causa_error err;", "",
                 "    causa_init();"]
        assert_index = 0
        for step in self.m.steps:
            lines.append(f"    {self._step(step, assert_index)}")
            if isinstance(step, Assert):
                assert_index += 1
        lines += ["    (void)env;", "    (void)err;", "    return 0;", "}", "#endif", ""]
        return "\n".join(lines)

    def _binding(self, anchor: int) -> str:
        return binding_identifier(self.binding_of_anchor[anchor].name)

    def _step(self, step: Step, assert_index: int) -> str:
        if isinstance(step, Def):
            return f"if (causa_eval_node({step.node}, env, &err)) causa_runtime_error(&err);"
        if isinstance(step, Show):
            return f"causa_show(env, {self._binding(step.anchor)}); /* line {step.line} */"
        if isinstance(step, Explain):
            return f"causa_explain(env, {self._binding(step.anchor)}); /* line {step.line} */"
        if isinstance(step, Impact):
            return f"causa_impact(env, {self._binding(step.anchor)}, {step.visible}); /* line {step.line} */"
        if isinstance(step, WhatIf):
            value = f"(causa_value){{ .{_MEMBER[step.value_type]} = {c_literal(step.value, step.value_type)} }}"
            target = self._binding(step.target) if step.target is not None else "CAUSA_NO_TARGET"
            return (f"causa_whatif(env, {self._binding(step.input)}, {value}, {target}, {step.visible});"
                    f" /* line {step.line} */")
        if isinstance(step, Assert):
            return (f"causa_assert(env, {assert_index}, env[{step.root}].b);"
                    f" /* line {step.line}: {_comment(step.source_text)} */")
        raise CodegenError(f"no C translation for step {step!r}")
