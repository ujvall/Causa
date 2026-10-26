"""CAUSA Studio's console formatting (studio/format.py): the runtime's output laid out
as labelled blocks, without losing or changing any information."""

import re
import unittest
from pathlib import Path

from studio.format import _tree_prefixes, format_output, format_stderr
from test_runtime import EXPECTED

ROOT = Path(__file__).resolve().parent.parent
SPEC_OUTPUT = (ROOT / "docs" / "language-specification.md").read_text(encoding="utf-8") \
    .split("Required stdout")[1].split("```")[1].lstrip("\n")
# words that only label the raw format and are replaced by the console's own labels
FORMAT_WORDS = {"explain", "whatif", "impact", "show", "input", "let", "see", "above", "override", "unchanged",
                "direct", "dependencies", "transitive", "dependents", "all", "inputs", "intermediates", "no",
                "dependent", "bindings"}


def text(lines) -> list[str]:
    return ["".join(t for t, _ in line) for line in lines]


class FormatOutputTests(unittest.TestCase):
    def test_pricing_layout(self) -> None:
        lines = text(format_output(SPEC_OUTPUT))
        self.assertEqual(lines[0], "show      total = 88.375")
        start = lines.index("explain   total")
        self.assertEqual([l.rstrip() for l in lines[start + 1: start + 13]], [
            "          total = 88.375                subtotal * (1 + tax) + fee",
            "          ├── subtotal = 75.0           price - savings",
            "          │   ├── price = 100           input",
            "          │   └── savings = 25.0        price * discount",
            "          │       ├── price = 100       input · see above",
            "          │       └── discount = 0.25   input",
            "          ├── tax = 0.125               input",
            "          └── fee = 4                   input",
            "          direct deps    tax, fee, subtotal",
            "          all deps       price, discount, tax, fee, savings, subtotal",
            "          inputs         price, discount, tax, fee",
            "          intermediates  savings, subtotal"])
        start = lines.index("what-if   price = 160")
        self.assertEqual(lines[start + 1: start + 4], [
            "          binding    original    what-if",
            "          price      100       → 160    override",
            "          savings    25.0      → 40.0"])
        self.assertIn("          expensive  true      → true   same value", lines)
        self.assertIn("what-if   discount = 0.5   showing total", lines)
        self.assertIn("          per_unit  22.09375  → error[R101] at 14:22 (division by zero)", lines)
        self.assertIn("          bulk      true      → unavailable (depends on per_unit)", lines)
        start = lines.index("impact    price")
        self.assertEqual(lines[start + 1: start + 3], [
            "          direct         savings, subtotal",
            "          all affected   savings, subtotal, total, expensive, per_unit, bulk"])
        self.assertEqual(lines[-2:], ["show      total = 88.375", "show      per_unit = 22.09375"])  # kept together

    def test_blank_line_between_statements(self) -> None:
        lines = text(format_output("a = 1\nb = 2\nimpact a\n  direct dependents: (none)\n  all dependents: (none)\n"))
        self.assertEqual(lines, ["show      a = 1", "show      b = 2", "", "impact    a",
                                 "          direct         (none)", "          all affected   (none)"])

    def test_explain_of_an_input(self) -> None:
        raw = ("explain x\n  x = 2  [input]\n  direct dependencies: (none)\n  transitive dependencies: (none)\n"
               "  inputs: (none)\n  intermediates: (none)\n")
        self.assertEqual([l.rstrip() for l in text(format_output(raw))][:3],
                         ["explain   x", "          x = 2   input", "          direct deps    (none)"])

    def test_whatif_without_dependents(self) -> None:
        lines = text(format_output("whatif x = 5\n  x: 2 -> 5  (override)\n  (no dependent bindings)\n"))
        self.assertEqual(lines, ["what-if   x = 5", "          binding  original    what-if",
                                 "          x        2         → 5   override",
                                 "          no bindings depend on the overridden inputs"])

    def test_unknown_text_is_shown_exactly(self) -> None:
        raw = "hello world\n  indented\nexplain y\n  not a tree line\n"
        self.assertEqual(text(format_output(raw)), ["hello world", "  indented", "", "explain y", "  not a tree line"])

    def test_tree_prefixes(self) -> None:
        self.assertEqual(_tree_prefixes([0, 1, 2, 2, 3, 1]),
                         ["", "├── ", "│   ├── ", "│   └── ", "│       └── ", "└── "])
        self.assertEqual(_tree_prefixes([0]), [""])

    def test_no_information_is_lost(self) -> None:
        """Every name, value and error code of every specification program's output
        appears in the formatted text."""
        word = re.compile(r"error\[\w+\]|[\w.\-]+")
        for case_id, (stdout, _, _) in [*EXPECTED.items(), ("§12", (SPEC_OUTPUT, "", 0))]:
            formatted = "\n".join(text(format_output(stdout)))
            with self.subTest(case=case_id):
                for token in word.findall(stdout):
                    if token not in FORMAT_WORDS and token not in ("-",):
                        self.assertIn(token, formatted)


class FormatStderrTests(unittest.TestCase):
    def test_diagnostics(self) -> None:
        stderr = ("p.cau:14:22: runtime error[R101]: division by zero\n"
                  "p.cau:18:1: assertion failed: total >= 0\n  total = -80.375\n"
                  "p.cau:2:19: error[E401]: operator '+' requires numeric operands, found int and bool\n"
                  "something else\n")
        out = format_stderr(stderr)
        self.assertEqual([("".join(t for t, _ in spans), where) for spans, where in out], [
            ("error     R101  line 14, column 22   division by zero", (14, 22)),
            ("assert    failed  line 18   total >= 0", (18, 1)),
            ("          total = -80.375", None),
            ("error     E401  line 2, column 19   operator '+' requires numeric operands, found int and bool", (2, 19)),
            ("something else", None)])


if __name__ == "__main__":
    unittest.main()
