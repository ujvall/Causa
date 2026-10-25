"""Syntax-level checks for every program in tests/specification-cases.md.

Each case is exercised at the stage implemented so far (lexer + parser):

* OK          - the program must tokenize and parse.
* sem(CODE)   - the program must parse. Compile-time CODEs (E3xx/E4xx) are
                checked by test_front_end_cases via SEMANTIC_ERRORS; runtime
                CODEs (Rxxx, assertion failures) are NOT checked yet.
* (code, line, column) - a lexical/syntax error that must be reported now.

`⏎` separates lines exactly as in the specification document. Every program
ends with a newline unless listed in NO_FINAL_NEWLINE.
"""

import re
import unittest
from pathlib import Path

from causa.diagnostics import CausaError
from causa.frontend import compile_to_ir, read_source
from causa.parser import parse, parse_file

ROOT = Path(__file__).resolve().parent.parent
OK = "ok"


def sem(code: str) -> tuple[str, str]:
    return ("sem", code)


CASES: dict[str, tuple[str, object]] = {
    # §1 valid programs
    "V01": ("", OK),
    "V02": ("# only a comment⏎⏎", OK),
    "V03": ("input x = 2⏎let y = x * 3⏎show y", OK),
    "V04": ("input x = 2⏎let y = x * 3⏎show y", OK),
    "V05": ("input x = 2\r\nlet y = x * 3\r\nshow y", OK),
    "V06": ("input a = 1⏎input b = 0.5⏎let c = a + b⏎show c", OK),
    "V07": ("let q = 7 / 2⏎let r = 6 / 3⏎show q⏎show r", OK),
    "V08": ("let x = 1 + 2 * 3⏎let y = (1 + 2) * 3⏎show x⏎show y", OK),
    "V09": ("let x = 10 - 3 - 2⏎let y = 8 / 2 / 2⏎show x⏎show y", OK),
    "V10": ("let x = -2 * 3⏎let y = - -4⏎show x⏎show y", OK),
    "V11": ("let b = not 1 > 2⏎show b", OK),
    "V12": ("let b = true or false and false⏎show b", OK),
    "V13": ("let b = 1 == 1.0⏎let c = 0.1 + 0.2 == 0.3⏎show b⏎show c", OK),
    "V14": ("input big = 1.0e16⏎input small = 0.00001⏎let s = 0.1 + 0.2⏎show big⏎show small⏎show s", OK),
    "V15": ("input z = -0.0⏎let e = z == 0.0⏎show z⏎show e", OK),
    "V16": ("input t = -5⏎show t", OK),
    "V17": ("input x = 3⏎assert x > 0⏎show x", OK),
    "V18": ("input Price = 1⏎input price = 2⏎show Price", OK),
    "V19": ("input showing = 1⏎show showing", OK),
    "V20": ("input a = 1⏎input b = 2⏎show a", OK),
    "V21": ("input d = 0.20⏎show d", OK),
    "V24": ("input rate = 0⏎show rate", OK),
    # §2 explain
    "X01": ("input p = 7⏎explain p", OK),
    "X02": ("let c = 5⏎explain c", OK),
    "X03": ("input x = 3⏎let sq = x * x⏎explain sq", OK),
    "X04": ("input a = 2⏎let p = a + a⏎let q = a * 2⏎let r = p + q⏎explain r", OK),
    "X05": ("input a = 1⏎let b = a + 1⏎let c = b * 2⏎let d = b + c⏎explain d", OK),
    "X06": ("input x = 1⏎let y = x⏎explain y", OK),
    "X07": ("input x = 1⏎let y = x   +  1⏎explain y", OK),
    # §3 whatif full form
    "W01": ("input x = 3⏎let z = x * 0⏎whatif x = 7", OK),
    "W02": ("input a = 1⏎input b = 2⏎let c = b * 2⏎whatif a = 5", OK),
    "W03": ("input x = 1⏎let y = x + 1⏎whatif x = 10⏎show y", OK),
    "W04": ("input x = 1⏎input k = 2⏎let y = x * k⏎whatif x = 10⏎whatif k = 3", OK),
    "W05": ("input x = 1⏎let a = x + 1⏎whatif x = 2⏎let b = x + 2⏎show b", OK),
    "W06": ("input x = 4⏎let y = x * 2⏎whatif x = 4", OK),
    "W07": ("input t = 5⏎let u = t * 2⏎whatif t = -1", OK),
    "W08": ("input member = true⏎let pays = not member⏎whatif member = false", OK),
    "W09": ("input a = 1⏎input b = 2⏎let s = a + b⏎let t = b * 3⏎whatif a = 10", OK),
    "W10": ("input z = 0.0⏎let w = z * 1.0⏎whatif z = -0.0", OK),
    "W11": ("input d = 0.20⏎whatif d = 0.5", OK),
    "W12": ("input a = 1⏎let b = a * 2⏎let c = 7⏎let d = b + c⏎whatif a = 2", OK),
    # §4 override promotion
    "P01": ("input d = 0.25⏎let h = d * 2⏎whatif d = 1", OK),
    "P02": ("input d = 0.5⏎whatif d = -3", OK),
    "P03": ("input r = 2.0⏎let s = r * 3⏎whatif r = 2", OK),
    "P04": ("input f = 0.5⏎whatif f = 9007199254740993", OK),
    "P05": ("input n = 5⏎whatif n = 5.0", sem("E403")),
    "P06": ("input n = 5⏎whatif n = -2.5", sem("E403")),
    "P07": ("input b = true⏎whatif b = 1", sem("E403")),
    "P08": ("input f = 0.5⏎whatif f = true", sem("E403")),
    "P09": ("input i = 1⏎whatif i = false", sem("E403")),
    "P10": ("input f = 0.5⏎whatif f = 9223372036854775808", ("E103", 2, 12)),
    "P11": ("input p = 100⏎whatif p = 1.5", sem("E403")),
    # §5 hypothetical runtime errors (runtime behavior; syntax only here)
    "H01": ("input d = 2⏎let q = 10 / d⏎show q⏎whatif d = 0", OK),
    "H02": ("input d = 2⏎let q = 10 / d⏎let r = q + 1⏎let s = r * 2⏎whatif d = 0", OK),
    "H03": ("input d = 2⏎let q = 10 / d⏎whatif d = 0⏎show q⏎whatif d = 5", OK),
    "H04": ("input d = 2⏎let q = 10 / d⏎let w = d + 1⏎whatif d = 0", OK),
    "H05": ("input n = 1⏎let m = n * 9223372036854775807⏎whatif n = 2", OK),
    "H06": ("input f = 1.0⏎let g = f * 1.0e308⏎whatif f = 10.0", OK),
    "H07": ("input d = 1⏎let a = 1 / d⏎let b = 2 / d⏎let c = b + a⏎whatif d = 0", OK),
    "H08": ("input d = 1⏎let ok = false and 1 / d > 0⏎whatif d = 0", OK),
    "H09": ("input d = 2⏎let q = 10 / d⏎whatif d = 0⏎assert q > 0⏎show q", OK),
    "H10": ("input d = 2⏎let q = 10 / d⏎whatif d = 0⏎let z = q / 0", sem("R101")),
    "H11": ("input d = 0⏎let q = 1 / d", sem("R101")),
    # §6 targeted whatif
    "T01": ("input x = 1⏎let y = x + 1⏎let z = y * 2⏎whatif x = 5 show z", OK),
    "T02": ("input x = 1⏎let y = x + 1⏎whatif x = 5 show y", OK),
    "T03": ("input x = 3⏎let z = x * 0⏎whatif x = 7 show z", OK),
    "T04": ("input x = 1⏎let y = x + 1⏎whatif x = 5 show y⏎show y", OK),
    "T05": ("input d = 2⏎let q = 10 / d⏎let r = q + 1⏎whatif d = 0 show r", OK),
    "T06": ("input d = 2⏎let q = 10 / d⏎whatif d = 0 show q", OK),
    "T07": ("input d = 2⏎let q = 10 / d⏎let w = d + 1⏎whatif d = 0 show w", OK),
    "T08": ("input d = 0.25⏎let h = d * 2⏎whatif d = 1 show h", OK),
    "T10": ("input x = 1⏎input k = 2⏎let y = k * 2⏎whatif x = 5 show y", sem("E304")),
    "T11": ("input x = 1⏎whatif x = 5 show x", sem("E304")),
    "T12": ("input x = 1⏎input k = 2⏎whatif x = 5 show k", sem("E304")),
    "T13": ("input x = 1⏎whatif x = 5 show y⏎let y = x", sem("E301")),
    "T14": ("input x = 1⏎whatif x = 5 show nothing", sem("E301")),
    "T15": ("input x = 1⏎whatif x = 5 show", ("E201", 2, 18)),
    "T16": ("input x = 1⏎let y = x⏎let z = x⏎whatif x = 5 show y z", ("E201", 4, 21)),
    "T17": ("input x = 1⏎let y = x⏎whatif x = 5 show y + 1", ("E201", 3, 21)),
    "T18": ("input x = 1⏎let y = x⏎whatif x = 1 + 1 show y", ("E203", 3, 14)),
    "T19": ("input x = 1⏎let y = x⏎whatif x = 5 show let", ("E201", 3, 19)),
    "T20": ("input x = 1⏎let y = x⏎whatif x = 5 explain y", ("E203", 3, 14)),
    # §6b several overrides (revision 3)
    "M01": ("input a = 1⏎input b = 2⏎let s = a + b⏎whatif a = 10, b = 20", OK),
    "M02": ("input a = 1⏎input b = 2⏎let x = a * 2⏎let y = b * 2⏎let z = x + y⏎whatif b = 5, a = 3", OK),
    "M03": ("input a = 1⏎input b = 2⏎let y = b * 2⏎whatif a = 5, b = 3 show y", OK),
    "M04": ("input f = 0.5⏎input i = 1⏎let r = f * i⏎whatif f = 2, i = 3", OK),
    "M05": ("input d = 2⏎input k = 1⏎let q = 10 / d⏎let r = q * k⏎let w = k * 0⏎whatif d = 0, k = 5", OK),
    "M06": ("input a = 1⏎input b = 2⏎let s = a + b⏎whatif a = 10, b = 20⏎whatif b = 7⏎show s", OK),
    "M07": ("input a = 1⏎input b = 2⏎whatif a = 1, b = 2", OK),
    "M08": ("input a = 1⏎whatif a = 1, a = 2", sem("E305")),
    "M09": ("input a = 1⏎input b = 2⏎input c = 3⏎let y = c * 2⏎whatif a = 1, b = 2 show y", sem("E304")),
    "M10": ("input a = 1⏎let b = a⏎whatif a = 2, b = 3", sem("E303")),
    "M11": ("input a = 1⏎input f = 0.5⏎whatif a = 2, f = true", sem("E403")),
    "M12": ("input a = 1⏎whatif a = 2, z = 3", sem("E301")),
    "M13": ("input a = 1⏎whatif a = 2,", ("E201", 2, 14)),
    "M14": ("input a = 1⏎input b = 2⏎whatif a = 2, show b", ("E201", 3, 15)),
    "M15": ("input a = 1⏎input b = 2⏎whatif a = 2 b = 3", ("E203", 3, 14)),
    "M16": ("let x = 1, 2", ("E201", 1, 10)),
    "M17": ("input a = 1, b = 2", ("E203", 1, 12)),
    "M18": ("input x = 1⏎show x, x", ("E201", 2, 7)),
    "M19": ("input a = 1⏎let b = a⏎whatif a = 2.5, b = 3", sem("E403")),
    "M20": ("input x = 3⏎input y = 4⏎let z = x * 0 + y * 0⏎whatif x = 7, y = 9 show z", OK),
    # §7 impact
    "I01": ("input a = 1⏎impact a", OK),
    "I02": ("input x = 1⏎let a = x⏎impact x⏎let b = x", OK),
    "I03": ("input x = 3⏎let z = x * 0⏎impact x", OK),
    "I04": ("input a = 1⏎let b = a + 1⏎let c = b * 2⏎let d = c + a⏎impact b", OK),
    "I06": ("input d = 2⏎let q = 10 / d⏎whatif d = 0⏎impact d", OK),
    "I07": ("input x = 1⏎input k = 2⏎let y = k * 2⏎impact x", OK),
    # §8 compile-time errors
    "E01": ("let y = x", sem("E301")),
    "E02": ("let a = b + 1⏎input b = 2", sem("E301")),
    "E03": ("let x = x + 1", sem("E301")),
    "E04": ("input a = 1⏎input a = 2", sem("E302")),
    "E05": ("input a = 1⏎let a = 2", sem("E302")),
    "E06": ("let y = 1⏎let y = y + 1", sem("E302")),
    "E07": ("let x = 1 + true", sem("E401")),
    "E08": ("let x = not 1", sem("E401")),
    "E09": ("let x = 1 and true", sem("E401")),
    "E10": ("let x = true < false", sem("E401")),
    "E11": ("let x = true == 1", sem("E401")),
    "E12": ("let x = -true", sem("E401")),
    "E13": ("assert 1", sem("E402")),
    "E16": ("input a = 1⏎let b = a⏎whatif b = 2", sem("E303")),
    "E17": ("whatif z = 1", sem("E301")),
    "E18": ("input price = 100⏎whatif price = 100 + 1", ("E203", 2, 20)),
    "E19": ("input x = 1 + 2", ("E203", 1, 13)),
    "E20": ("input x = 1⏎input y = x", ("E203", 2, 11)),
    "E21": ("input y = -true", ("E203", 1, 12)),
    "E22": ("let b = 1 < 2 < 3", ("E202", 1, 15)),
    "E23": ("let x = 1 < 2 == true", ("E202", 1, 15)),
    "E24": ("let x = 1 +", ("E201", 1, 12)),
    "E25": ("let x = (1 + 2", ("E201", 1, 15)),
    "E26": ("let show = 1", ("E201", 1, 5)),
    "E27": ("let if = 1", ("E201", 1, 5)),
    "E28": ("let a = 1 let b = 2", ("E201", 1, 11)),
    "E29": ("input x = 1⏎show x + 1", ("E201", 2, 8)),
    "E30": ("explain nothing", sem("E301")),
    "E31": ("let x = 1 $ 2", ("E101", 1, 11)),
    "E32": ("let x = !true", ("E101", 1, 9)),
    "E33": ("let x = 1 % 2", ("E101", 1, 11)),
    "E34": ("let x = .5", ("E101", 1, 9)),
    "E35": ("let café = 1", ("E101", 1, 8)),
    "E37": ("let x = 007", ("E102", 1, 9)),
    "E38": ("let x = 1.", ("E102", 1, 9)),
    "E39": ("let x = 123abc", ("E102", 1, 9)),
    "E40": ("let x = 1e5", ("E102", 1, 9)),
    "E41": ("let x = 9223372036854775808", ("E103", 1, 9)),
    "E42": ("let x = 1.0e400", ("E104", 1, 9)),
    "E44": ("input x = 1⏎explain x + 1", ("E201", 2, 11)),
    "E45": ("input x = 1⏎impact x * 2", ("E201", 2, 10)),
    "E46": ("input x: float = 1", ("E101", 1, 8)),
    "E47": ("let x = if true then 1 else 2", ("E201", 1, 9)),
    # §9 runtime errors and assertions (runtime behavior; syntax only here)
    "R01": ("input d = 0⏎let q = 1 / d", sem("R101")),
    "R02": ("let q = 1.0 / 0.0", sem("R101")),
    "R03": ("input big = 9223372036854775807⏎let o = big + 1", sem("R102")),
    "R04": ("input f = 1.0e308⏎let g = f * 10.0", sem("R103")),
    "R05": ("input m = -9223372036854775807⏎let n = m - 1⏎let p = -n", sem("R102")),
    "R06": ("input a = 1⏎show a⏎let z = a / 0", sem("R101")),
    "R07": ("input d = 0⏎let unused = 1 / d", sem("R101")),
    "R08": ("let b = false and 1 / 0 > 0", sem("R101")),
    "R09": ("input z = 0⏎let a = 1 / z + 9223372036854775807 * 2", sem("R101")),
    "R11": ("input x = 5⏎let y = x - 10⏎assert y >= 0⏎show y", sem("assertion failure")),
    "R12": ("input x = 1⏎assert x > 0⏎whatif x = -5", OK),
}

NO_FINAL_NEWLINE = {"V01", "V04"}

# Cases whose program is an example file.
FILE_CASES = {
    "V22": "minimal.cau",
    "V23": "pricing.cau", "X08": "pricing.cau", "W13": "pricing.cau",
    "T09": "pricing.cau", "I05": "pricing.cau",
    "E43": "invalid-type-error.cau",  # semantic E401 @ 8:19
}

# Withdrawn in revision 2 (see specification-cases.md); IR cases need Phase 3+.
NOT_APPLICABLE = {"E14", "E15", "R10", "E36"}  # E36: moved to M07 in revision 3


# Locations of semantic errors, from specification-cases.md (checked from Phase 3).
SEMANTIC_ERRORS: dict[str, tuple[str, int, int]] = {
    "P05": ("E403", 2, 12), "P06": ("E403", 2, 12), "P07": ("E403", 2, 12),
    "P08": ("E403", 2, 12), "P09": ("E403", 2, 12), "P11": ("E403", 2, 12),
    "T10": ("E304", 4, 19), "T11": ("E304", 2, 19), "T12": ("E304", 3, 19),
    "T13": ("E301", 2, 19), "T14": ("E301", 2, 19),
    "E01": ("E301", 1, 9), "E02": ("E301", 1, 9), "E03": ("E301", 1, 9),
    "E04": ("E302", 2, 7), "E05": ("E302", 2, 5), "E06": ("E302", 2, 5),
    "E07": ("E401", 1, 11), "E08": ("E401", 1, 9), "E09": ("E401", 1, 11),
    "E10": ("E401", 1, 14), "E11": ("E401", 1, 14), "E12": ("E401", 1, 9),
    "E13": ("E402", 1, 8), "E16": ("E303", 3, 8), "E17": ("E301", 1, 8),
    "E30": ("E301", 1, 9),
    "M08": ("E305", 2, 15), "M09": ("E304", 5, 26), "M10": ("E303", 3, 15),
    "M11": ("E403", 3, 19), "M12": ("E301", 2, 15), "M19": ("E403", 3, 12),
}
FILE_SEMANTIC_ERRORS = {"E43": ("E401", 8, 19)}


def source_of(case_id: str, program: str) -> str:
    text = program.replace("⏎", "\n")
    if case_id not in NO_FINAL_NEWLINE:
        text += "\r\n" if "\r\n" in text else "\n"
    return text


class SpecificationCaseTests(unittest.TestCase):
    def test_inline_cases(self) -> None:
        for case_id, (program, expected) in CASES.items():
            with self.subTest(case=case_id):
                text = source_of(case_id, program)
                if expected == OK or (isinstance(expected, tuple) and expected[0] == "sem"):
                    parse(text)
                else:
                    with self.assertRaises(CausaError) as cm:
                        parse(text)
                    err = cm.exception
                    self.assertEqual((err.code, err.line, err.column), expected)

    def test_file_cases(self) -> None:
        for case_id, name in FILE_CASES.items():
            with self.subTest(case=case_id):
                self.assertTrue(parse_file(ROOT / "examples" / name).statements)

    def test_front_end_cases(self) -> None:
        """Parse + semantic analysis + validated IR. Runtime and output
        expectations are checked by test_runtime.py."""
        for case_id, (program, expected) in CASES.items():
            with self.subTest(case=case_id):
                text = source_of(case_id, program)
                error = SEMANTIC_ERRORS.get(case_id)
                if error is None and isinstance(expected, tuple) and expected[0] != "sem":
                    error = expected  # lexical/syntax error: unchanged by later stages
                if error is None:
                    compile_to_ir(text)
                else:
                    with self.assertRaises(CausaError) as cm:
                        compile_to_ir(text)
                    err = cm.exception
                    self.assertEqual((err.code, err.line, err.column), error)

    def test_front_end_file_cases(self) -> None:
        for case_id, name in FILE_CASES.items():
            with self.subTest(case=case_id):
                text = read_source(ROOT / "examples" / name)
                if case_id in FILE_SEMANTIC_ERRORS:
                    with self.assertRaises(CausaError) as cm:
                        compile_to_ir(text)
                    err = cm.exception
                    self.assertEqual((err.code, err.line, err.column), FILE_SEMANTIC_ERRORS[case_id])
                else:
                    compile_to_ir(text)

    def test_semantic_table_covers_every_sem_compile_error(self) -> None:
        compile_codes = {cid for cid, (_, exp) in CASES.items()
                         if isinstance(exp, tuple) and exp[0] == "sem" and exp[1].startswith("E")}
        self.assertEqual(compile_codes, set(SEMANTIC_ERRORS))
        for cid, (code, _, _) in SEMANTIC_ERRORS.items():
            self.assertEqual(CASES[cid][1], sem(code), cid)

    def test_every_specification_case_is_accounted_for(self) -> None:
        doc = (ROOT / "tests" / "specification-cases.md").read_text(encoding="utf-8")
        ids = set(re.findall(r"^\| ([VXWPHTIERM]\d\d) \|", doc, re.MULTILINE))
        covered = set(CASES) | set(FILE_CASES) | NOT_APPLICABLE
        self.assertEqual(ids - covered, set(), "specification cases missing from this table")
        self.assertEqual(covered - ids, set(), "table lists cases not in the specification")


if __name__ == "__main__":
    unittest.main()
