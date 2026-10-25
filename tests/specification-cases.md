# CAUSA Specification Test Cases — Version 1 (revision 2)

**These are specification test cases, not test results.** No compiler exists yet; nothing below has been executed. Each case states the outcome a conforming implementation must produce. Later phases should turn these into automated tests.

Conventions:

* `⏎` separates source lines. Every program is otherwise exactly as written (single spaces, no trailing whitespace, ends with a newline unless stated).
* **Compile errors** give `code @ line:column` (language-specification §9.2). Message wording is not tested.
* **Output** lists stdout lines separated by ` / `; `··` denotes two spaces of indentation. Unless stated otherwise, stderr is empty and exit status is 0.
* `F` stands for the source file name in diagnostics.
* Spec references: LS = [language-specification.md](../docs/language-specification.md), CA = [compiler-architecture.md](../docs/compiler-architecture.md), D = [semantic-decisions.md](../docs/semantic-decisions.md).
* Cases marked **(rev 2)** were added or changed in revision 2; the M-series (§6b) and E36 changed in revision 3 (Phase 7); the L-series (§6c) was added in revision 4 (Phase 8) and is run by [test_launch.py](test_launch.py).

**Automated coverage (Phases 2–7).** Every case in §§1–9, including the revision 3 M-series (§6b), is automated. [test_spec_cases.py](test_spec_cases.py) runs each program through the lexer, parser, semantic analysis and Causal IR; lexical, syntax and semantic errors (E1xx–E4xx) are checked by code and location. Every case that compiles (V, X, W, P01–P04, H, T, M01–M07, M20, I and R cases, and the example-file cases V22, V23, X08, W13, T09, I05) is compiled to C, built with the runtime library and executed by [test_runtime.py](test_runtime.py), which compares stdout, stderr and exit status exactly with the expected outcome; a test fails if any such case lacks an expected outcome. These execution tests need a C compiler and are skipped (not failed) without one. IR cases: IR01–IR03 by [test_ir.py](test_ir.py); IR04–IR07 (structure) by [test_optimizer.py](test_optimizer.py), with their runtime outputs (W01, R02) covered end to end; IR08 by building every runtime case from unoptimized IR and requiring identical output; IR09 and IR11 by an instrumented harness in [test_runtime.py](test_runtime.py) that records which nodes a `whatif` re-evaluates and compares the base environment bit for bit. IR10 is covered only in part: [test_ir.py](test_ir.py) checks that the `whatif` action carries the promoted `float` value, but no test asserts the absence of an `itof` node for the override.

## 1. Valid programs and basic semantics

| ID | Program | Expected | Ref |
|---|---|---|---|
| V01 | *(empty file)* | no output | LS §4 |
| V02 | `# only a comment⏎⏎` | no output | LS §3.2 |
| V03 | `input x = 2⏎let y = x * 3⏎show y` | `y = 6` | LS §8.3 |
| V04 | V03 without a final newline | `y = 6` | LS §3.1 |
| V05 | V03 with CR LF line endings | `y = 6` | LS §3.1 |
| V06 | `input a = 1⏎input b = 0.5⏎let c = a + b⏎show c` | `c = 1.5` | LS §6.3 |
| V07 | `let q = 7 / 2⏎let r = 6 / 3⏎show q⏎show r` | `q = 3.5 / r = 2.0` | LS §6.4 |
| V08 | `let x = 1 + 2 * 3⏎let y = (1 + 2) * 3⏎show x⏎show y` | `x = 7 / y = 9` | LS §6.2 |
| V09 | `let x = 10 - 3 - 2⏎let y = 8 / 2 / 2⏎show x⏎show y` | `x = 5 / y = 2.0` | LS §6.2 |
| V10 | `let x = -2 * 3⏎let y = - -4⏎show x⏎show y` | `x = -6 / y = 4` | LS §6.2 |
| V11 | `let b = not 1 > 2⏎show b` | `b = true` | LS §6.2 |
| V12 | `let b = true or false and false⏎show b` | `b = true` | LS §6.2 |
| V13 | `let b = 1 == 1.0⏎let c = 0.1 + 0.2 == 0.3⏎show b⏎show c` | `b = true / c = false` | LS §5.3 |
| V14 | `input big = 1.0e16⏎input small = 0.00001⏎let s = 0.1 + 0.2⏎show big⏎show small⏎show s` | `big = 1e+16 / small = 1e-05 / s = 0.30000000000000004` | LS §8.2 |
| V15 | `input z = -0.0⏎let e = z == 0.0⏎show z⏎show e` | `z = -0.0 / e = true` | LS §5.3 |
| V16 | `input t = -5⏎show t` | `t = -5` | LS §5.4 |
| V17 | `input x = 3⏎assert x > 0⏎show x` | `x = 3` | LS §8.7 |
| V18 | `input Price = 1⏎input price = 2⏎show Price` | `Price = 1` | LS §3.3 |
| V19 | `input showing = 1⏎show showing` | `showing = 1` (maximal munch) | LS §3.3 |
| V20 | `input a = 1⏎input b = 2⏎show a` | `a = 1` (unused input allowed) | LS §7.3 |
| V21 | `input d = 0.20⏎show d` | `d = 0.2` | LS §8.2 |
| V22 | [examples/minimal.cau](../examples/minimal.cau) | `y = 6` | |
| V23 | [examples/pricing.cau](../examples/pricing.cau) | exactly the stdout in LS §12; exit 0 **(rev 2)** | LS §12 |
| V24 | `input rate = 0⏎show rate` | `rate = 0` (`int`: literal-based typing retained) **(rev 2)** | D02 |

## 2. Explain

| ID | Program | Expected stdout | Ref |
|---|---|---|---|
| X01 | `input p = 7⏎explain p` | `explain p / ··p = 7  [input] / ··direct dependencies: (none) / ··transitive dependencies: (none) / ··inputs: (none) / ··intermediates: (none)` | LS §8.4 |
| X02 | `let c = 5⏎explain c` | `explain c / ··c = 5  [let: 5] /` four `(none)` lists | constants are not dependencies |
| X03 | `input x = 3⏎let sq = x * x⏎explain sq` | `explain sq / ··sq = 9  [let: x * x] / ····x = 3  [input] / ··direct dependencies: x / ··transitive dependencies: x / ··inputs: x / ··intermediates: (none)` | repeated reference listed once |
| X04 | `input a = 2⏎let p = a + a⏎let q = a * 2⏎let r = p + q⏎explain r` | `explain r / ··r = 8  [let: p + q] / ····p = 4  [let: a + a] / ······a = 2  [input] / ····q = 4  [let: a * 2] / ······a = 2  [input, see above] / ··direct dependencies: p, q / ··transitive dependencies: a, p, q / ··inputs: a / ··intermediates: p, q` | equal values stay distinct; shared input expanded once |
| X05 | `input a = 1⏎let b = a + 1⏎let c = b * 2⏎let d = b + c⏎explain d` | `explain d / ··d = 6  [let: b + c] / ····b = 2  [let: a + 1] / ······a = 1  [input] / ····c = 4  [let: b * 2] / ······b = 2  [let, see above] / ··direct dependencies: b, c / ··transitive dependencies: a, b, c / ··inputs: a / ··intermediates: b, c` | shared let not re-expanded |
| X06 | `input x = 1⏎let y = x⏎explain y` | tree: `··y = 1  [let: x] / ····x = 1  [input]`; direct: `x` | alias binding |
| X07 | `input x = 1⏎let y = x   +  1⏎explain y` | tree root: `··y = 2  [let: x   +  1]` | source text verbatim |
| X08 | [examples/pricing.cau](../examples/pricing.cau) `explain total` | as in LS §12 | tree order vs declaration order |

## 3. Whatif — full form, values and isolation

| ID | Program | Expected stdout | Ref |
|---|---|---|---|
| W01 | `input x = 3⏎let z = x * 0⏎whatif x = 7` | `whatif x = 7 / ··x: 3 -> 7  (override) / ··z: 0 -> 0  (unchanged)` | dependent ≠ changed |
| W02 | `input a = 1⏎input b = 2⏎let c = b * 2⏎whatif a = 5` | `whatif a = 5 / ··a: 1 -> 5  (override) / ··(no dependent bindings)` | LS §8.5.3 |
| W03 | `input x = 1⏎let y = x + 1⏎whatif x = 10⏎show y` | `whatif x = 10 / ··x: 1 -> 10  (override) / ··y: 2 -> 11 / y = 2` | base not mutated |
| W04 | `input x = 1⏎input k = 2⏎let y = x * k⏎whatif x = 10⏎whatif k = 3` | `whatif x = 10 / ··x: 1 -> 10  (override) / ··y: 2 -> 20 / whatif k = 3 / ··k: 2 -> 3  (override) / ··y: 2 -> 3` | overrides do not accumulate |
| W05 | `input x = 1⏎let a = x + 1⏎whatif x = 2⏎let b = x + 2⏎show b` | `whatif x = 2 / ··x: 1 -> 2  (override) / ··a: 2 -> 3 / b = 3` | only earlier bindings visible |
| W06 | `input x = 4⏎let y = x * 2⏎whatif x = 4` | `whatif x = 4 / ··x: 4 -> 4  (override) / ··y: 8 -> 8  (unchanged)` | same-value override |
| W07 | `input t = 5⏎let u = t * 2⏎whatif t = -1` | `whatif t = -1 / ··t: 5 -> -1  (override) / ··u: 10 -> -2` | negative literal |
| W08 | `input member = true⏎let pays = not member⏎whatif member = false` | `whatif member = false / ··member: true -> false  (override) / ··pays: false -> true` | bool input |
| W09 | `input a = 1⏎input b = 2⏎let s = a + b⏎let t = b * 3⏎whatif a = 10` | `whatif a = 10 / ··a: 1 -> 10  (override) / ··s: 3 -> 12` | non-dependents not listed |
| W10 | `input z = 0.0⏎let w = z * 1.0⏎whatif z = -0.0` | `whatif z = -0.0 / ··z: 0.0 -> -0.0  (override) / ··w: 0.0 -> -0.0` | bit identity: changed |
| W11 | `input d = 0.20⏎whatif d = 0.5` | `whatif d = 0.5 / ··d: 0.2 -> 0.5  (override) / ··(no dependent bindings)` | value formatting in header |
| W12 | `input a = 1⏎let b = a * 2⏎let c = 7⏎let d = b + c⏎whatif a = 2` | `whatif a = 2 / ··a: 1 -> 2  (override) / ··b: 2 -> 4 / ··d: 9 -> 11` | `c` reused, not listed |
| W13 | [examples/pricing.cau](../examples/pricing.cau) | all four `whatif` reports and the final `show` lines as in LS §12 | isolation |

## 4. Whatif — override promotion (D15, rev 2)

| ID | Program | Expected | Ref |
|---|---|---|---|
| P01 | `input d = 0.25⏎let h = d * 2⏎whatif d = 1` | `whatif d = 1.0 / ··d: 0.25 -> 1.0  (override) / ··h: 0.5 -> 2.0` | int → float promotion |
| P02 | `input d = 0.5⏎whatif d = -3` | `whatif d = -3.0 / ··d: 0.5 -> -3.0  (override) / ··(no dependent bindings)` | negative int promoted |
| P03 | `input r = 2.0⏎let s = r * 3⏎whatif r = 2` | `whatif r = 2.0 / ··r: 2.0 -> 2.0  (override) / ··s: 6.0 -> 6.0  (unchanged)` | promoted value equals base |
| P04 | `input f = 0.5⏎whatif f = 9007199254740993` | `whatif f = 9007199254740992.0 / ··f: 0.5 -> 9007199254740992.0  (override) / ··(no dependent bindings)` | rounding above 2^53 is defined |
| P05 | `input n = 5⏎whatif n = 5.0` | E403 @ 2:12 | no float → int |
| P06 | `input n = 5⏎whatif n = -2.5` | E403 @ 2:12 (at the `-`) | |
| P07 | `input b = true⏎whatif b = 1` | E403 @ 2:12 | no number → bool |
| P08 | `input f = 0.5⏎whatif f = true` | E403 @ 2:12 | no bool → number |
| P09 | `input i = 1⏎whatif i = false` | E403 @ 2:12 | |
| P10 | `input f = 0.5⏎whatif f = 9223372036854775808` | E103 @ 2:12 | range check before promotion |
| P11 | `input p = 100⏎whatif p = 1.5` | E403 @ 2:12 | |

## 5. Whatif — hypothetical runtime errors (D16, rev 2)

| ID | Program | Expected | Ref |
|---|---|---|---|
| H01 | `input d = 2⏎let q = 10 / d⏎show q⏎whatif d = 0` | `q = 5.0 / whatif d = 0 / ··d: 2 -> 0  (override) / ··q: 5.0 -> error[R101] at 2:12 (division by zero)`; stderr empty; exit 0 | not fatal |
| H02 | `input d = 2⏎let q = 10 / d⏎let r = q + 1⏎let s = r * 2⏎whatif d = 0` | `whatif d = 0 / ··d: 2 -> 0  (override) / ··q: 5.0 -> error[R101] at 2:12 (division by zero) / ··r: 6.0 -> unavailable (depends on q) / ··s: 12.0 -> unavailable (depends on q)` | transitive unavailability names root cause |
| H03 | `input d = 2⏎let q = 10 / d⏎whatif d = 0⏎show q⏎whatif d = 5` | `whatif d = 0 / ··d: 2 -> 0  (override) / ··q: 5.0 -> error[R101] at 2:12 (division by zero) / q = 5.0 / whatif d = 5 / ··d: 2 -> 5  (override) / ··q: 5.0 -> 2.0` | base and later whatifs unaffected |
| H04 | `input d = 2⏎let q = 10 / d⏎let w = d + 1⏎whatif d = 0` | `whatif d = 0 / ··d: 2 -> 0  (override) / ··q: 5.0 -> error[R101] at 2:12 (division by zero) / ··w: 3 -> 1` | independent cone members still evaluated |
| H05 | `input n = 1⏎let m = n * 9223372036854775807⏎whatif n = 2` | `… / ··m: 9223372036854775807 -> error[R102] at 2:11 (integer overflow)` | R102 |
| H06 | `input f = 1.0⏎let g = f * 1.0e308⏎whatif f = 10.0` | `… / ··g: 1e+308 -> error[R103] at 2:11 (non-finite float result)` | R103 |
| H07 | `input d = 1⏎let a = 1 / d⏎let b = 2 / d⏎let c = b + a⏎whatif d = 0` | `whatif d = 0 / ··d: 1 -> 0  (override) / ··a: 1.0 -> error[R101] at 2:11 (division by zero) / ··b: 2.0 -> error[R101] at 3:11 (division by zero) / ··c: 3.0 -> unavailable (depends on a)` | cause = earliest-declared failed binding, not first in expression |
| H08 | `input d = 1⏎let ok = false and 1 / d > 0⏎whatif d = 0` | `… / ··ok: false -> error[R101] at 2:22 (division by zero)` | strict `and` retained (D08) |
| H09 | `input d = 2⏎let q = 10 / d⏎whatif d = 0⏎assert q > 0⏎show q` | whatif report as H01 (without the `show`), then `q = 5.0`; exit 0 | assertion sees base value |
| H10 | `input d = 2⏎let q = 10 / d⏎whatif d = 0⏎let z = q / 0` | whatif report as in H03's first report; then stderr `F:4:11: runtime error[R101]: division by zero`; exit 2 | base errors are still fatal |
| H11 | `input d = 0⏎let q = 1 / d` | stderr `F:2:11: runtime error[R101]: division by zero`; exit 2 (program never reaches a `whatif`) | base error unchanged |

## 6. Whatif — targeted form (D12, D23, rev 2)

| ID | Program | Expected | Ref |
|---|---|---|---|
| T01 | `input x = 1⏎let y = x + 1⏎let z = y * 2⏎whatif x = 5 show z` | `whatif x = 5 show z / ··z: 4 -> 12` | transitive target |
| T02 | `input x = 1⏎let y = x + 1⏎whatif x = 5 show y` | `whatif x = 5 show y / ··y: 2 -> 6` | direct target |
| T03 | `input x = 3⏎let z = x * 0⏎whatif x = 7 show z` | `whatif x = 7 show z / ··z: 0 -> 0  (unchanged)` | structural dependence suffices |
| T04 | `input x = 1⏎let y = x + 1⏎whatif x = 5 show y⏎show y` | `whatif x = 5 show y / ··y: 2 -> 6 / y = 2` | isolation |
| T05 | `input d = 2⏎let q = 10 / d⏎let r = q + 1⏎whatif d = 0 show r` | `whatif d = 0 show r / ··r: 6.0 -> unavailable (depends on q)` | |
| T06 | `input d = 2⏎let q = 10 / d⏎whatif d = 0 show q` | `whatif d = 0 show q / ··q: 5.0 -> error[R101] at 2:12 (division by zero)` | |
| T07 | `input d = 2⏎let q = 10 / d⏎let w = d + 1⏎whatif d = 0 show w` | `whatif d = 0 show w / ··w: 3 -> 1` | failure outside target's dependencies not observable |
| T08 | `input d = 0.25⏎let h = d * 2⏎whatif d = 1 show h` | `whatif d = 1.0 show h / ··h: 0.5 -> 2.0` | promotion + target |
| T09 | [examples/pricing.cau](../examples/pricing.cau) | `whatif discount = 0.5 show total` and `whatif tax = 1.0 show total` reports as in LS §12 | |
| T10 | `input x = 1⏎input k = 2⏎let y = k * 2⏎whatif x = 5 show y` | E304 @ 4:19 | target independent of override |
| T11 | `input x = 1⏎whatif x = 5 show x` | E304 @ 2:19 | overridden input is not a target |
| T12 | `input x = 1⏎input k = 2⏎whatif x = 5 show k` | E304 @ 3:19 | inputs are never targets |
| T13 | `input x = 1⏎whatif x = 5 show y⏎let y = x` | E301 @ 2:19 | target must be visible |
| T14 | `input x = 1⏎whatif x = 5 show nothing` | E301 @ 2:19 | |
| T15 | `input x = 1⏎whatif x = 5 show` | E201 @ 2:18 | missing target name |
| T16 | `input x = 1⏎let y = x⏎let z = x⏎whatif x = 5 show y z` | E201 @ 4:21 | one target only |
| T17 | `input x = 1⏎let y = x⏎whatif x = 5 show y + 1` | E201 @ 3:21 | target is a name |
| T18 | `input x = 1⏎let y = x⏎whatif x = 1 + 1 show y` | E203 @ 3:14 | override still a literal |
| T19 | `input x = 1⏎let y = x⏎whatif x = 5 show let` | E201 @ 3:19 | keyword as target |
| T20 | `input x = 1⏎let y = x⏎whatif x = 5 explain y` | E203 @ 3:14 | only `show` may follow the override |

## 6b. Whatif — several overrides (D24, rev 3)

| ID | Program | Expected | Ref |
|---|---|---|---|
| M01 | `input a = 1⏎input b = 2⏎let s = a + b⏎whatif a = 10, b = 20` | `whatif a = 10, b = 20 / ··a: 1 -> 10  (override) / ··b: 2 -> 20  (override) / ··s: 3 -> 30` | both overrides applied together |
| M02 | `input a = 1⏎input b = 2⏎let x = a * 2⏎let y = b * 2⏎let z = x + y⏎whatif b = 5, a = 3` | `whatif b = 5, a = 3 / ··b: 2 -> 5  (override) / ··a: 1 -> 3  (override) / ··x: 2 -> 6 / ··y: 4 -> 10 / ··z: 6 -> 16` | header and override lines in statement order; union cone in declaration order |
| M03 | `input a = 1⏎input b = 2⏎let y = b * 2⏎whatif a = 5, b = 3 show y` | `whatif a = 5, b = 3 show y / ··y: 4 -> 6` | target depends on one of the overridden inputs |
| M04 | `input f = 0.5⏎input i = 1⏎let r = f * i⏎whatif f = 2, i = 3` | `whatif f = 2.0, i = 3 / ··f: 0.5 -> 2.0  (override) / ··i: 1 -> 3  (override) / ··r: 0.5 -> 6.0` | promotion per override |
| M05 | `input d = 2⏎input k = 1⏎let q = 10 / d⏎let r = q * k⏎let w = k * 0⏎whatif d = 0, k = 5` | `whatif d = 0, k = 5 / ··d: 2 -> 0  (override) / ··k: 1 -> 5  (override) / ··q: 5.0 -> error[R101] at 3:12 (division by zero) / ··r: 5.0 -> unavailable (depends on q) / ··w: 0 -> 0  (unchanged)`; exit 0 | failed, unavailable and unchanged outcomes |
| M06 | `input a = 1⏎input b = 2⏎let s = a + b⏎whatif a = 10, b = 20⏎whatif b = 7⏎show s` | M01's report, then `whatif b = 7 / ··b: 2 -> 7  (override) / ··s: 3 -> 8 / s = 3` | overrides do not accumulate |
| M07 | `input a = 1⏎input b = 2⏎whatif a = 1, b = 2` | `whatif a = 1, b = 2 / ··a: 1 -> 1  (override) / ··b: 2 -> 2  (override) / ··(no dependent bindings)` | former E36 |
| M08 | `input a = 1⏎whatif a = 1, a = 2` | E305 @ 2:15 | same input twice |
| M09 | `input a = 1⏎input b = 2⏎input c = 3⏎let y = c * 2⏎whatif a = 1, b = 2 show y` | E304 @ 5:26 | target depends on no overridden input |
| M10 | `input a = 1⏎let b = a⏎whatif a = 2, b = 3` | E303 @ 3:15 | second override is a let |
| M11 | `input a = 1⏎input f = 0.5⏎whatif a = 2, f = true` | E403 @ 3:19 | second override's type |
| M12 | `input a = 1⏎whatif a = 2, z = 3` | E301 @ 2:15 | second override undeclared |
| M13 | `input a = 1⏎whatif a = 2,` | E201 @ 2:14 | trailing comma |
| M14 | `input a = 1⏎input b = 2⏎whatif a = 2, show b` | E201 @ 3:15 | missing override after comma |
| M15 | `input a = 1⏎input b = 2⏎whatif a = 2 b = 3` | E203 @ 3:14 | missing comma |
| M16 | `let x = 1, 2` | E201 @ 1:10 | comma outside whatif (was E101) |
| M17 | `input a = 1, b = 2` | E203 @ 1:12 | input initializer followed by a comma |
| M18 | `input x = 1⏎show x, x` | E201 @ 2:7 | one name per show |
| M19 | `input a = 1⏎let b = a⏎whatif a = 2.5, b = 3` | E403 @ 3:12 | first error in source order |
| M20 | `input x = 3⏎input y = 4⏎let z = x * 0 + y * 0⏎whatif x = 7, y = 9 show z` | `whatif x = 7, y = 9 show z / ··z: 0 -> 0  (unchanged)` | structural dependence, not numeric change |

## 6c. Launch arguments (D25, rev 4)

Programs are compiled with source file name `F` and run with the arguments shown. Argument errors are checked by code: stderr is one line starting `F: argument error[CODE]: `, stdout is empty and the exit status is 3.

| ID | Program | Arguments | Expected |
|---|---|---|---|
| L01 | [examples/pricing.cau](../examples/pricing.cau) | *(none)* | byte-identical to LS §12, exit 0 |
| L02 | [examples/pricing.cau](../examples/pricing.cau) | `--set price=150` | identical to the same program with `input price = 150` run without arguments; first line `total = 130.5625`; `explain` shows `price = 150  [input]`; `whatif price = 160` shows `price: 150 -> 160  (override)` |
| L03 | `input a = 1⏎input b = 2⏎let s = a + b⏎show s` | `--set a=10 --set b=20`, and `--set b=20 --set a=10` | `s = 30` both times |
| L04 | `input f = 0.5⏎show f` | `--set f=2` | `f = 2.0` (promotion) |
| L05 | `input n = 5⏎show n` | `--set n=1.5` | A107 |
| L06 | `input m = true⏎show m` | `--set m=1`; `--set m=false` | A107; `m = false` |
| L07 | `input a = 1⏎show a` | `--set a=1 --set a=2` | A105 |
| L08 | `input x = 1⏎let s = x + 1⏎show s` | `--set prise=1`; `--set s=1` | A103; A104 |
| L09 | `input x = 1⏎show x` | `--set x=`; `--set x`; `--set =1`; `--set` | A102 each |
| L10 | `input x = 1⏎show x` | `x=007`, `x=1e5`, `x=+5`, `x=0x10`, `x=nan`, `x=inf`, `x=True` (each after `--set`) | A106 each |
| L11 | `input x = 1⏎show x` | `--set x=9223372036854775808`; `…=9223372036854775807`; `…=-9223372036854775807` | A108; `x = 9223372036854775807`; `x = -9223372036854775807` |
| L12 | `input f = 0.5⏎show f` | `--set f=1.0e400`; `--set f=1.0e-400` | A109; `f = 0.0` |
| L13 | `input x = 1⏎show x` | `--sett x=1`; `x=1`; `-s` | A101 each |
| L14 | `input x = 1⏎show x` | `--set x=2 --set bogus=1` | A103 and **no stdout** (nothing ran) |
| L15 | `input x = 1⏎let y = x + 1⏎whatif x = 10⏎show y` | `--set x=5` | `whatif x = 10 / ··x: 5 -> 10  (override) / ··y: 6 -> 11 / y = 6` |
| L16 | `input d = 2⏎let q = 10 / d` | `--set d=0` | stderr `F:2:12: runtime error[R101]: division by zero`, exit **2** (a runtime error, not an argument error) |
| L17 | `input x = 5⏎assert x > 0` | `--set x=-1` | stderr `F:2:1: assertion failed: x > 0` / `··x = -1`, exit 1 |
| L18 | `input x = 3⏎let z = x * 0 + x⏎show z` | `--set x=7` | `z = 7`, with and without optimization (inputs are never folded) |
| L19 | `input f = 0.5⏎show f` | `--set f=-0.0` | `f = -0.0` |
| L20 | `input d = 1⏎let q = 10 / d`, built with `causa_runtime.h` only | `--set d=0`; `--set d=5`; `--set d=x` | R101 at 2:12, exit 2; no output, exit 0; A106, exit 3 |
| L21 | [examples/pricing.cau](../examples/pricing.cau) | `--set price=150` twice | identical bytes |

## 7. Impact

| ID | Program | Expected stdout | Ref |
|---|---|---|---|
| I01 | `input a = 1⏎impact a` | `impact a / ··direct dependents: (none) / ··all dependents: (none)` | LS §8.6 |
| I02 | `input x = 1⏎let a = x⏎impact x⏎let b = x` | `impact x / ··direct dependents: a / ··all dependents: a` | visibility |
| I03 | `input x = 3⏎let z = x * 0⏎impact x` | `impact x / ··direct dependents: z / ··all dependents: z` | structural, not numeric |
| I04 | `input a = 1⏎let b = a + 1⏎let c = b * 2⏎let d = c + a⏎impact b` | `impact b / ··direct dependents: c / ··all dependents: c, d` | impact on a let |
| I05 | [examples/pricing.cau](../examples/pricing.cau) | three `impact` reports as in LS §12 | |
| I06 | `input d = 2⏎let q = 10 / d⏎whatif d = 0⏎impact d` | whatif report as in H01 (without `show`), then `impact d / ··direct dependents: q / ··all dependents: q` | impact unaffected by a failed whatif; no hidden state **(rev 2)** |
| I07 | `input x = 1⏎input k = 2⏎let y = k * 2⏎impact x` | `impact x / ··direct dependents: (none) / ··all dependents: (none)` — consistent with T10 being E304 **(rev 2)** | D23 |

## 8. Compile-time errors

| ID | Program | Expected | Ref |
|---|---|---|---|
| E01 | `let y = x` | E301 @ 1:9 | undefined name |
| E02 | `let a = b + 1⏎input b = 2` | E301 @ 1:9 | forward reference |
| E03 | `let x = x + 1` | E301 @ 1:9 | self reference |
| E04 | `input a = 1⏎input a = 2` | E302 @ 2:7 | duplicate |
| E05 | `input a = 1⏎let a = 2` | E302 @ 2:5 | input/let share namespace |
| E06 | `let y = 1⏎let y = y + 1` | E302 @ 2:5 | no rebinding |
| E07 | `let x = 1 + true` | E401 @ 1:11 | |
| E08 | `let x = not 1` | E401 @ 1:9 | |
| E09 | `let x = 1 and true` | E401 @ 1:11 | |
| E10 | `let x = true < false` | E401 @ 1:14 | no ordering on bool |
| E11 | `let x = true == 1` | E401 @ 1:14 | |
| E12 | `let x = -true` | E401 @ 1:9 | |
| E13 | `assert 1` | E402 @ 1:8 | no truthiness |
| E14 | *(moved to P01 in rev 2: `whatif d = 1` for a float input is now valid)* | — | D15 |
| E15 | *(moved to P11 in rev 2)* | — | |
| E16 | `input a = 1⏎let b = a⏎whatif b = 2` | E303 @ 3:8 | override target must be input |
| E17 | `whatif z = 1` | E301 @ 1:8 | |
| E18 | `input price = 100⏎whatif price = 100 + 1` | E203 @ 2:20 | override must be a literal |
| E19 | `input x = 1 + 2` | E203 @ 1:13 | initializer must be a literal |
| E20 | `input x = 1⏎input y = x` | E203 @ 2:11 | |
| E21 | `input y = -true` | E203 @ 1:12 | |
| E22 | `let b = 1 < 2 < 3` | E202 @ 1:15 | chained comparison |
| E23 | `let x = 1 < 2 == true` | E202 @ 1:15 | |
| E24 | `let x = 1 +` | E201 @ 1:12 | missing operand |
| E25 | `let x = (1 + 2` | E201 @ 1:15 | unbalanced parenthesis |
| E26 | `let show = 1` | E201 @ 1:5 | keyword as name |
| E27 | `let if = 1` | E201 @ 1:5 | reserved word |
| E28 | `let a = 1 let b = 2` | E201 @ 1:11 | one statement per line |
| E29 | `input x = 1⏎show x + 1` | E201 @ 2:8 | show takes a name (D09) |
| E30 | `explain nothing` | E301 @ 1:9 | |
| E31 | `let x = 1 $ 2` | E101 @ 1:11 | |
| E32 | `let x = !true` | E101 @ 1:9 | lone `!` |
| E33 | `let x = 1 % 2` | E101 @ 1:11 | `%` deferred |
| E34 | `let x = .5` | E101 @ 1:9 | |
| E35 | `let café = 1` | E101 @ 1:8 | non-ASCII identifier |
| E36 | *(moved to M07 in rev 3: several overrides per `whatif` are valid)* | — | D24 |
| E37 | `let x = 007` | E102 @ 1:9 | leading zero |
| E38 | `let x = 1.` | E102 @ 1:9 | |
| E39 | `let x = 123abc` | E102 @ 1:9 | |
| E40 | `let x = 1e5` | E102 @ 1:9 | float needs a point |
| E41 | `let x = 9223372036854775808` | E103 @ 1:9 | |
| E42 | `let x = 1.0e400` | E104 @ 1:9 | |
| E43 | [examples/invalid-type-error.cau](../examples/invalid-type-error.cau) | E401 @ 8:19; no output program produced | |
| E44 | `input x = 1⏎explain x + 1` | E201 @ 2:11 | explain takes a name (D09) **(rev 2)** |
| E45 | `input x = 1⏎impact x * 2` | E201 @ 2:10 | impact takes a name (D09) **(rev 2)** |
| E46 | `input x: float = 1` | E101 @ 1:8 (`:` is not a CAUSA character) | no type annotations (D02) **(rev 2)** |
| E47 | `let x = if true then 1 else 2` | E201 @ 1:9 | conditionals deferred **(rev 2)** |

## 9. Runtime errors and assertions (base execution)

| ID | Program | Expected | Ref |
|---|---|---|---|
| R01 | `input d = 0⏎let q = 1 / d` | stderr `F:2:11: runtime error[R101]: division by zero`; exit 2 | LS §6.4 |
| R02 | `let q = 1.0 / 0.0` | compiles; R101 @ 1:13 at run time; exit 2 | LS §6.6 |
| R03 | `input big = 9223372036854775807⏎let o = big + 1` | R102 @ 2:13; exit 2 | no wrap-around |
| R04 | `input f = 1.0e308⏎let g = f * 10.0` | R103 @ 2:11; exit 2 | no infinity |
| R05 | `input m = -9223372036854775807⏎let n = m - 1⏎let p = -n` | R102 @ 3:9; exit 2 | negation overflow |
| R06 | `input a = 1⏎show a⏎let z = a / 0` | stdout `a = 1`; R101 @ 3:11; exit 2 | prior output kept |
| R07 | `input d = 0⏎let unused = 1 / d` | R101 @ 2:16; exit 2 | unused lets evaluated |
| R08 | `let b = false and 1 / 0 > 0` | R101 @ 1:21; exit 2 | no short-circuit (D08) |
| R09 | `input z = 0⏎let a = 1 / z + 9223372036854775807 * 2` | R101 @ 2:11 (not R102); exit 2 | left-to-right post-order |
| R10 | *(replaced in rev 2 by H01: hypothetical errors are no longer fatal)* | — | D16 |
| R11 | `input x = 5⏎let y = x - 10⏎assert y >= 0⏎show y` | stdout empty; stderr `F:3:1: assertion failed: y >= 0` / `··y = -5`; exit 1 | LS §8.7 |
| R12 | `input x = 1⏎assert x > 0⏎whatif x = -5` | `whatif x = -5 / ··x: 1 -> -5  (override) / ··(no dependent bindings)`; exit 0 | asserts not re-checked |

## 10. IR and optimizer invariants (for Phase 3+)

| ID | Check | Expected | Ref |
|---|---|---|---|
| IR01 | Compile the same source twice | identical node IDs and IR dump | CA §3.3 |
| IR02 | Every IR node of every valid case | all operand IDs < node ID | CA §3.3 |
| IR03 | IR for the CA §3.6 source | matches the node table in CA §3.6 (before optimization) | CA §3.6 |
| IR04 | W01 with optimization enabled | `x * 0` not folded; provenance verification passes; W01 output unchanged | CA §5 |
| IR05 | `input a = 1⏎let p = a + 1⏎let q = a + 1⏎explain q` | two distinct `bind` nodes; explanation of `q` names `q`, not `p` | CA §5 |
| IR06 | `input x = 1⏎let y = x * (2 + 3)⏎explain y` | `2 + 3` may fold to `5`; explanation still shows `[let: x * (2 + 3)]`, `y = 5` | CA §5 |
| IR07 | R02 with optimization enabled | `1.0 / 0.0` not folded; R101 still at 1:13 | CA §5 |
| IR08 | Every case in §§1–9 | identical stdout, stderr, exit status with and without optimization | CA §5 |
| IR09 | W12 | runtime does not re-evaluate `c`'s nodes during `whatif` (observable only via instrumentation) | CA §6.3 |
| IR10 | P01 | the `whatif` action carries the `float` value `1.0`; no `itof` node is created for the override **(rev 2)** | D15 |
| IR11 | H03 | base value array is bit-identical before and after the failing `whatif` (instrumentation) **(rev 2)** | CA §6.3 |
