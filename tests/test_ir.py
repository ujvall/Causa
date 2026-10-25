"""Causal IR construction and validation tests (compiler-architecture §3-§4)."""

import re
import unittest
from dataclasses import replace
from pathlib import Path

from causa.frontend import check, compile_to_ir, read_source
from causa.ir import (
    Assert, Def, Explain, Impact, IRModule, IRValidationError, NodeKind, Opcode, OverrideValue, Provenance,
    Show, WhatIf, build_ir, check_against_program, format_node, topological_order, validate_ir,
)
from causa.semantic import CausaType

ROOT = Path(__file__).resolve().parent.parent
INT, FLOAT, BOOL = CausaType.INT, CausaType.FLOAT, CausaType.BOOL


def ir(*src: str) -> IRModule:
    return compile_to_ir("\n".join(src) + "\n")


class ArchitectureDocumentTests(unittest.TestCase):
    """The IR must match the illustrative IR in compiler-architecture §3.6."""

    def setUp(self) -> None:
        doc = (ROOT / "docs" / "compiler-architecture.md").read_text(encoding="utf-8")
        section = doc.split("### 3.6 Illustrative IR")[1].split("After constant folding")[0]
        blocks = re.findall(r"```\n(.*?)```", section, re.DOTALL)
        self.source, self.ir_block = blocks[0], blocks[1]
        self.section = section
        self.module = compile_to_ir(self.source)

    def test_node_table_matches_exactly(self) -> None:
        expected = [line for line in self.ir_block.splitlines() if re.match(r"n\d+ ", line)]
        self.assertEqual([format_node(n) for n in self.module.nodes], expected)

    def test_steps_and_bindings_lines(self) -> None:
        steps = ", ".join(f"def n{s.node}" for s in self.module.steps if isinstance(s, Def))
        bindings = ", ".join(f"{k} -> n{v}" for k, v in self.module.bindings.items())
        self.assertIn(f"steps: {steps}\n", self.ir_block)
        self.assertIn(f"bindings: {bindings}\n", self.ir_block)

    def test_edge_list(self) -> None:
        edges_text = re.search(r"`(n\d+→n\d+(?:, n\d+→n\d+)*)`", self.section)
        assert edges_text is not None
        expected = [tuple(map(int, e)) for e in re.findall(r"n(\d+)→n(\d+)", edges_text.group(1))]
        actual = [(n.id, o) for n in self.module.nodes for o in n.operands]
        self.assertEqual(actual, expected)

    def test_binding_level_graph(self) -> None:
        self.assertEqual(self.module.provenance.by_name["total"].direct_deps, ("price", "discount"))
        self.assertNotIn(2, self.module.bindings.values())  # the constant is not a binding


class ConstructionTests(unittest.TestCase):
    def test_node_kinds_and_anchors(self) -> None:
        m = ir("input a = 1", "let b = a", "let c = 5", "let d = a + c")
        kinds = [(n.id, n.kind, n.name) for n in m.nodes]
        self.assertEqual(kinds, [
            (0, NodeKind.INPUT, "a"),
            (1, NodeKind.BIND, "b"),  # alias: no op node, bind uses the input directly
            (2, NodeKind.CONST, None), (3, NodeKind.BIND, "c"),
            (4, NodeKind.OP, None), (5, NodeKind.BIND, "d"),
        ])
        self.assertEqual(m.bindings, {"a": 0, "b": 1, "c": 3, "d": 5})
        self.assertEqual(m.nodes[1].operands, (0,))
        self.assertEqual(m.nodes[4].operands, (0, 3))  # references use anchors

    def test_equivalent_lets_stay_distinct(self) -> None:
        m = ir("input a = 2", "let p = a + 1", "let q = a + 1", "let r = a * 2", "let s = a + a")
        anchors = [m.bindings[n] for n in "pqrs"]
        self.assertEqual(len(set(anchors)), 4)
        self.assertEqual(m.nodes[m.bindings["p"]].source_text, m.nodes[m.bindings["q"]].source_text)
        self.assertNotEqual(m.nodes[m.bindings["p"]].operands, m.nodes[m.bindings["q"]].operands)

    def test_inputs_are_not_folded(self) -> None:
        m = ir("input x = 3", "let z = x * 0")
        x = m.nodes[m.bindings["x"]]
        self.assertEqual((x.kind, x.value), (NodeKind.INPUT, 3))
        self.assertEqual(m.provenance.by_name["z"].direct_deps, ("x",))
        self.assertFalse(any(n.kind is NodeKind.CONST and n.value == 3 for n in m.nodes))

    def test_promotions_are_explicit(self) -> None:
        m = ir("input i = 1", "let q = i / 2", "let c = i < 1.5", "let e = i == i")
        ops = [(n.opcode, tuple(m.nodes[o].type for o in n.operands), n.type)
               for n in m.nodes if n.kind is NodeKind.OP]
        self.assertEqual(ops, [
            (Opcode.ITOF, (INT,), FLOAT), (Opcode.ITOF, (INT,), FLOAT), (Opcode.DIV, (FLOAT, FLOAT), FLOAT),
            (Opcode.ITOF, (INT,), FLOAT), (Opcode.LT, (FLOAT, FLOAT), BOOL),
            (Opcode.EQ, (INT, INT), BOOL),
        ])

    def test_unary_and_boolean_opcodes(self) -> None:
        m = ir("input b = true", "input n = 2", "let r = not b or b and -n > 0")
        self.assertEqual([n.opcode for n in m.nodes if n.kind is NodeKind.OP],
                         [Opcode.NOT, Opcode.NEG, Opcode.GT, Opcode.AND, Opcode.OR])

    def test_source_locations_and_text(self) -> None:
        m = ir("input x = 1", "let   y = (x   +  2) * 3")
        y = m.nodes[m.bindings["y"]]
        self.assertEqual((y.line, y.column, y.source_text), (2, 7, "(x   +  2) * 3"))
        add = next(n for n in m.nodes if n.opcode is Opcode.ADD)
        self.assertEqual((add.line, add.column), (2, 16))
        const2 = next(n for n in m.nodes if n.kind is NodeKind.CONST and n.value == 2)
        self.assertEqual((const2.line, const2.column), (2, 19))

    def test_owners(self) -> None:
        m = ir("input x = 1", "let y = x + 1", "assert y > 0", "assert x < 5")
        self.assertEqual([n.owner for n in m.nodes],
                         ["x", "y", "y", "y", "assert#0", "assert#0", "assert#1", "assert#1"])

    def test_actions(self) -> None:
        m = ir("input t = 0.5", "let u = t * 2", "show u", "explain t", "impact t",
               "whatif t = 1 show u", "whatif t = 0.25", "assert u >= 0")
        actions = [s for s in m.steps if not isinstance(s, Def)]
        u, t = m.bindings["u"], m.bindings["t"]
        self.assertEqual(actions[0], Show(u, 3))
        self.assertEqual(actions[1], Explain(t, 4))
        self.assertEqual(actions[2], Impact(t, 2, 5))
        w = actions[3]
        assert isinstance(w, WhatIf)
        self.assertEqual((w.target, w.visible, w.line), (u, 2, 6))
        (o,) = w.overrides
        self.assertEqual(o, OverrideValue(t, 1.0, FLOAT, 1, True, 6, 12))
        self.assertIs(type(o.value), float)
        full = actions[4]
        assert isinstance(full, WhatIf)
        self.assertIsNone(full.target)
        a = actions[5]
        assert isinstance(a, Assert)
        self.assertEqual((a.source_text, a.refs, a.line, a.column), ("u >= 0", (u,), 8, 1))
        self.assertIs(m.nodes[a.root].type, BOOL)

    def test_assert_on_bare_name_uses_anchor(self) -> None:
        m = ir("input ok = true", "assert ok")
        a = m.steps[-1]
        assert isinstance(a, Assert)
        self.assertEqual(a.root, m.bindings["ok"])

    def test_steps_interleave_in_source_order(self) -> None:
        m = ir("input x = 1", "show x", "let y = x + 1", "show y")
        self.assertEqual([type(s).__name__ for s in m.steps], ["Def", "Show", "Def", "Def", "Def", "Show"])

    def test_ids_are_deterministic(self) -> None:
        source = read_source(ROOT / "examples" / "pricing.cau")
        self.assertEqual(compile_to_ir(source), compile_to_ir(source))


class ProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.m = compile_to_ir(read_source(ROOT / "examples" / "pricing.cau"))
        self.p = self.m.provenance

    def test_direct_dependencies_declaration_order(self) -> None:
        self.assertEqual(self.p.by_name["total"].direct_deps, ("tax", "fee", "subtotal"))
        self.assertEqual(self.p.by_name["total"].references, ("subtotal", "tax", "fee"))
        self.assertEqual(self.p.by_name["price"].direct_deps, ())

    def test_transitive_and_dependents_match_spec_section_12(self) -> None:
        self.assertEqual(self.p.transitive_deps("total"),
                         ("price", "discount", "tax", "fee", "savings", "subtotal"))
        self.assertEqual(self.p.direct_dependents["price"], ("savings", "subtotal"))
        self.assertEqual(self.p.all_dependents("price"),
                         ("savings", "subtotal", "total", "expensive", "per_unit", "bulk"))
        self.assertEqual(self.p.direct_dependents["discount"], ("savings",))
        self.assertEqual(self.p.direct_dependents["total"], ("expensive", "per_unit"))
        self.assertEqual(self.p.all_dependents("total"), ("expensive", "per_unit", "bulk"))

    def test_edge_direction(self) -> None:
        # Canonical: a node lists what it uses; the dependents index is derived.
        subtotal = self.m.nodes[self.m.bindings["subtotal"]]
        self.assertTrue(all(o < subtotal.id for o in subtotal.operands))
        for name, users in self.p.direct_dependents.items():
            for user in users:
                self.assertIn(name, self.p.by_name[user].direct_deps)

    def test_dependency_without_value_change(self) -> None:
        p = ir("input x = 3", "let z = x * 0", "let w = x - x").provenance
        self.assertEqual(p.all_dependents("x"), ("z", "w"))


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.m = ir("input x = 1", "input k = 2.0", "let y = x * k", "let z = y + 1.0",
                    "show z", "whatif x = 5 show z", "impact x", "assert z > 0")

    def assertInvalid(self, module: IRModule, fragment: str) -> None:
        with self.assertRaises(IRValidationError) as cm:
            validate_ir(module)
        self.assertIn(fragment, str(cm.exception))

    def replace_node(self, node_id: int, **changes: object) -> IRModule:
        nodes = tuple(replace(n, **changes) if n.id == node_id else n for n in self.m.nodes)
        return replace(self.m, nodes=nodes)

    def test_valid_module_passes(self) -> None:
        validate_ir(self.m)
        self.assertEqual(topological_order(self.m), tuple(n.id for n in self.m.nodes))

    def test_all_examples_validate(self) -> None:
        for name in ("minimal.cau", "pricing.cau"):
            with self.subTest(name=name):
                module = compile_to_ir(read_source(ROOT / "examples" / name))
                validate_ir(module)

    def test_forward_or_dangling_operand(self) -> None:
        y = self.m.bindings["y"]
        self.assertInvalid(self.replace_node(y, operands=(y + 1,)), "undefined or not earlier")
        self.assertInvalid(self.replace_node(y, operands=(99,)), "undefined or not earlier")

    def test_type_mismatch(self) -> None:
        mul = next(n for n in self.m.nodes if n.opcode is Opcode.MUL)
        self.assertInvalid(self.replace_node(mul.id, type=INT), "bad arithmetic")

    def test_folded_input(self) -> None:
        x = self.m.bindings["x"]
        self.assertInvalid(self.replace_node(x, kind=NodeKind.CONST, name=None), "does not anchor on its own input")

    def test_duplicate_binding_identity(self) -> None:
        bindings = dict(self.m.bindings, z=self.m.bindings["y"])
        self.assertInvalid(replace(self.m, bindings=bindings), "share an anchor")

    def test_provenance_mismatch(self) -> None:
        infos = list(self.m.provenance.bindings)
        z = self.m.provenance.by_name["z"]
        infos[z.index] = replace(z, direct_deps=("x",), references=("x",))
        self.assertInvalid(replace(self.m, provenance=Provenance(tuple(infos))), "differ from the node graph")

    def test_dependency_on_later_declaration(self) -> None:
        infos = list(self.m.provenance.bindings)
        x = self.m.provenance.by_name["x"]
        infos[x.index] = replace(x, direct_deps=("y",), references=("y",))
        self.assertInvalid(replace(self.m, provenance=Provenance(tuple(infos))), "differ from the node graph")

    def test_cycle_detected(self) -> None:
        y = self.m.bindings["y"]
        z = self.m.bindings["z"]
        # Reorder so that the table is not ascending and contains a cycle y <-> z.
        nodes = list(self.m.nodes)
        nodes[y] = replace(nodes[y], operands=(z,))
        with self.assertRaises(IRValidationError):
            topological_order(replace(self.m, nodes=tuple(nodes)))
        with self.assertRaises(IRValidationError):
            validate_ir(replace(self.m, nodes=tuple(nodes)))

    def test_bad_whatif_target(self) -> None:
        steps = tuple(replace(s, target=self.m.bindings["x"]) if isinstance(s, WhatIf) else s
                      for s in self.m.steps)
        self.assertInvalid(replace(self.m, steps=steps), "whatif target")

    def test_whatif_value_type(self) -> None:
        steps = tuple(replace(s, overrides=(replace(s.overrides[0], value=5.0),)) if isinstance(s, WhatIf) else s
                      for s in self.m.steps)
        self.assertInvalid(replace(self.m, steps=steps), "whatif value type")

    def with_overrides(self, *overrides: OverrideValue, target: int | None = None) -> IRModule:
        steps = tuple(replace(s, overrides=overrides, target=target) if isinstance(s, WhatIf) else s
                      for s in self.m.steps)
        return replace(self.m, steps=steps)

    def test_several_overrides(self) -> None:
        x, k, z = self.m.bindings["x"], self.m.bindings["k"], self.m.bindings["z"]
        ox = OverrideValue(x, 5, INT, 5, False, 6, 12)
        ok = OverrideValue(k, 3.0, FLOAT, 3, True, 6, 19)
        validate_ir(self.with_overrides(ox, ok, target=z))  # valid: both distinct inputs
        self.assertInvalid(self.with_overrides(ox, ox), "same input more than once")
        self.assertInvalid(self.with_overrides(), "at least one override")
        self.assertInvalid(self.with_overrides(ox, replace(ok, input=z)), "defined input")

    def test_target_must_depend_on_some_overridden_input(self) -> None:
        m = ir("input a = 1", "input b = 2", "let y = b * 2", "whatif a = 5, b = 3 show y")
        validate_ir(m)
        (w,) = [s for s in m.steps if isinstance(s, WhatIf)]
        self.assertEqual([o.input for o in w.overrides], [m.bindings["a"], m.bindings["b"]])  # statement order
        only_a = replace(m, steps=tuple(replace(s, overrides=s.overrides[:1]) if isinstance(s, WhatIf) else s
                                        for s in m.steps))
        with self.assertRaises(IRValidationError):
            validate_ir(only_a)

    def test_action_before_definition(self) -> None:
        steps = list(self.m.steps)
        show = next(i for i, s in enumerate(steps) if isinstance(s, Show))
        steps.insert(0, steps.pop(show))
        self.assertInvalid(replace(self.m, steps=tuple(steps)), "undefined binding")

    def test_missing_def(self) -> None:
        steps = tuple(s for s in self.m.steps if s != Def(0))
        self.assertInvalid(replace(self.m, steps=steps), "")

    def test_wrong_visibility(self) -> None:
        steps = tuple(replace(s, visible=0) if isinstance(s, Impact) else s for s in self.m.steps)
        self.assertInvalid(replace(self.m, steps=steps), "visibility")

    def test_ast_cross_check(self) -> None:
        sem = check("input a = 1\nlet b = a + 1\n")
        module = build_ir(sem)
        check_against_program(module, sem)
        b = module.provenance.by_name["b"]
        bad = replace(module, provenance=Provenance((module.provenance.bindings[0],
                                                     replace(b, references=()))))
        with self.assertRaises(IRValidationError):
            check_against_program(bad, sem)


if __name__ == "__main__":
    unittest.main()
