# CAUSA Language Specification — Version 1

Status: **language version 1, specification revision 4** (revision 3, Phase 7: several overrides per `whatif`; revision 4, Phase 8: launch arguments, §9.5). This document is the contract the compiler and runtime implement; the [README](../README.md) records what is implemented and how it is tested. Changes in revisions 2, 3 and 4 are recorded in [semantic-decisions.md](semantic-decisions.md) (revision log at the end).

The formal grammar is in [grammar.ebnf](grammar.ebnf). Where this document and the grammar disagree, that is a specification bug and must be fixed in both.

Keywords used in requirements: **must** / **must not** are mandatory; **may** is permitted but not required.

---

## 1. Purpose and philosophy

CAUSA is a small declarative language for numeric and logical computations whose **computational dependencies are a first-class part of the program**. A CAUSA program declares inputs, derives immutable values from them, and can ask the language itself:

* how a value was derived (`explain`),
* what values would be under a hypothetical input (`whatif`),
* which values depend on a given binding (`impact`).

Design principles:

1. **Declarative and acyclic.** Every value is defined once, from values defined before it. There is no mutation and no looping, so the dependency structure of a program is a finite directed acyclic graph that the compiler knows completely.
2. **Static and small type system.** Three types (`int`, `float`, `bool`), all types known at compile time, one implicit conversion.
3. **Determinism.** A given program run with the same launch arguments (§9.5) produces exactly one output, byte for byte, on every conforming implementation.
4. **Explanations are about computation, not the world.** CAUSA tracks which computed values were used to compute which others. It does not establish real-world causation; a dependency between `price` and `total` means only that the program computes `total` from `price`.

## 2. Program at a glance

```
# Pricing model
input price = 100
input discount = 0.25
input tax = 0.125
input fee = 4

let savings = price * discount
let subtotal = price - savings
let total = subtotal * (1 + tax) + fee

show total
assert total >= 0
explain total
whatif price = 160
whatif discount = 0.5 show total
impact price
```

A complete version with its exact expected output is in §12 and [../examples/pricing.cau](../examples/pricing.cau).

---

## 3. Lexical structure

### 3.1 Encoding and lines

* Source files use the extension `.cau` and are encoded in UTF-8. A leading UTF-8 byte-order mark is permitted and ignored.
* Non-ASCII characters are permitted only inside comments; anywhere else they are an invalid character (E101).
* A line ends with LF (`\n`) or CR LF (`\r\n`). A CR not followed by LF is an invalid character (E101).
* Each statement occupies exactly one line. There is no line continuation, including inside parentheses.

### 3.2 Whitespace and comments

* Space and horizontal tab separate tokens and are otherwise insignificant.
* `#` begins a comment that extends to the end of the line. Comments are discarded.

### 3.3 Identifiers

* Form: `[A-Za-z_][A-Za-z0-9_]*`. ASCII only. Case-sensitive (`Price` and `price` are different names).
* No length limit is imposed by the language.
* Tokens are formed by maximal munch: `showing` is one identifier.

### 3.4 Keywords and reserved words

Keywords (each has documented behavior in this specification):

| Keyword | Meaning | Section |
|---|---|---|
| `input` | declare an input | §7.1 |
| `let` | declare a computed binding | §7.2 |
| `show` | print a binding's value; also introduces the target of a targeted `whatif` | §8.3, §8.5 |
| `explain` | print a binding's derivation | §8.4 |
| `whatif` | evaluate under a hypothetical input | §8.5 |
| `impact` | list a binding's dependents | §8.6 |
| `assert` | check a boolean condition | §8.7 |
| `and`, `or`, `not` | boolean operators | §6 |
| `true`, `false` | boolean literals | §3.5 |

Reserved words (no behavior in version 1; using them as names is a syntax error E201): `if`, `then`, `else`, `int`, `float`, `bool`.

### 3.5 Literals

| Kind | Syntax | Examples | Invalid |
|---|---|---|---|
| Integer | `0` or a non-zero digit followed by digits | `0`, `42`, `100` | `007` (E102) |
| Float | integer part, `.`, one or more digits, optional exponent `e`/`E` with optional sign | `0.25`, `3.0`, `1.5e3`, `2.0E-4` | `1.` `.5` `1e5` `00.5` |
| Boolean | `true`, `false` | | |

* Literals are unsigned. In expressions, `-` is the unary minus operator (§6). In `input` initializers and `whatif` overrides, a leading `-` is part of the literal value (§5.4).
* `1e5` (no point) is not a float literal: it lexes as the integer `1` immediately followed by the letter `e`, which is malformed (E102).
* A numeric literal immediately followed by a letter, digit, `_`, or `.` that does not continue the literal is malformed (E102): `123abc`, `1.5.2`.
* An integer literal greater than 9223372036854775807 (2^63 − 1) is out of range (E103). Consequently −2^63 cannot be written as a literal (it can be computed).
* A float literal whose value rounds to infinity is out of range (E104). A float literal that underflows rounds to the nearest representable value (possibly zero) and is valid.

### 3.6 Operators and punctuation

`+ - * / == != < <= > >= = ( ) ,`

Longest match applies (`<=` is one token). A lone `!` is an invalid character (E101). `%`, `//`, `**` and all other characters are invalid in version 1 (E101). The comma separates the overrides of a `whatif` (§8.5) and is valid nowhere else; elsewhere it is an unexpected token (E201). *(Revision 3: the comma was previously an invalid character, E101.)*

---

## 4. Program structure

A program is a sequence of lines; each line is empty or contains exactly one statement (grammar: `program`, `line`). An empty file is a valid program that produces no output.

There is exactly one scope: the program. All names (inputs and `let` bindings) share one namespace.

---

## 5. Types and values

### 5.1 Types

| Type | Values | Representation |
|---|---|---|
| `int` | integers in [−2^63, 2^63 − 1] | two's-complement 64-bit |
| `float` | finite IEEE 754 binary64 values, including −0.0 | binary64 |
| `bool` | `true`, `false` | |

* Infinity and NaN are **not** values of `float`. Any operation that would produce one is a runtime error (§6.6). Therefore every `float` value is finite and `==` is reflexive.
* There is no type syntax in version 1. Every binding's type is determined statically: inputs from their literal (§7.1), lets from their expression (§6).

### 5.2 Implicit conversion

Exactly one implicit conversion exists: **int-to-float promotion**, converting an `int` to the nearest `float` (round-half-to-even). For |n| > 2^53 the conversion may be inexact; that is defined behavior. It is applied in exactly two places:

1. the arithmetic and comparison operators listed in §6.3, to an `int` operand when the other operand is `float` (or both, for `/`);
2. a `whatif` override (§8.5): an integer `literal_value` overriding a `float` input is promoted at compile time.

No other implicit conversion exists. In particular: no `bool`↔number conversion, no truthiness (`assert 1` is a type error), and no float-to-int conversion (a float literal cannot override an `int` input).

### 5.3 Equality

* `int == int`: mathematical equality.
* Mixed `int`/`float`: the `int` is promoted (§5.2), then compared as floats.
* `float == float`: IEEE 754 equality. `0.0 == -0.0` is `true`. There is no epsilon; `0.1 + 0.2 == 0.3` is `false`.
* `bool == bool`: identity.
* `bool` compared with a number: type error (E401).

### 5.4 Literal values

`literal_value` (grammar) is used only by `input` and `whatif`. Its type is determined by its form: integer literal → `int`, float literal → `float`, `true`/`false` → `bool`. A leading `-` negates the numeric value at compile time (`-0.0` is negative zero; `-0` is the `int` 0). The range rule of §3.5 applies to the unsigned digits.

---

## 6. Expressions

### 6.1 Forms

An expression is a literal, a name referring to a previously declared binding, a parenthesized expression, a unary operation, or a binary operation.

### 6.2 Precedence and associativity

From lowest to highest:

| Level | Operators | Associativity |
|---|---|---|
| 1 | `or` | left |
| 2 | `and` | left |
| 3 | `not` (prefix) | — |
| 4 | `==` `!=` `<` `<=` `>` `>=` | **non-associative** |
| 5 | `+` `-` (binary) | left |
| 6 | `*` `/` | left |
| 7 | `-` (unary) | — |
| 8 | literal, name, `( … )` | — |

So `not a == b` means `not (a == b)`; `-a * b` means `(-a) * b`; `a - b - c` means `(a - b) - c`. A comparison operand cannot itself be an unparenthesized comparison: `a < b < c` is a syntax error (E202). `(a < b) == c` is valid if `c` is `bool`.

### 6.3 Operator typing

`num` denotes `int` or `float`.

| Operator | Operand types | Result type |
|---|---|---|
| `+` `-` `*` | `int`, `int` | `int` |
| `+` `-` `*` | `num`, `num` with at least one `float` | `float` (int operand promoted) |
| `/` | `num`, `num` | `float` (both operands promoted if `int`) — **always** true division |
| unary `-` | `int` / `float` | same as operand |
| `<` `<=` `>` `>=` | `num`, `num` | `bool` (mixed operands compared as `float`) |
| `==` `!=` | `num`, `num` | `bool` (mixed operands compared as `float`) |
| `==` `!=` | `bool`, `bool` | `bool` |
| `and` `or` | `bool`, `bool` | `bool` |
| `not` | `bool` | `bool` |

Any other combination is a type error **E401**, reported at the operator token. Examples: `1 + true`, `-true`, `not 1`, `1 and true`, `true < false`, `true == 1`.

Integer division (`//`), modulo (`%`), and exponentiation are not part of version 1.

### 6.4 Arithmetic semantics

* `int` `+ - *` and unary `-`: exact two's-complement arithmetic; if the mathematical result is outside the `int` range it is a runtime error **R102** (no wrap-around).
* `float` operations: IEEE 754 binary64, round-to-nearest-even.
* `/`: true division of the (promoted) operands. `7 / 2` is `3.5`; `6 / 3` is `2.0`.
* Division by zero (divisor equal to `0` or `0.0` or `-0.0`, for any operand types) is runtime error **R101**.
* A `float` result that is infinite or NaN is runtime error **R103**.

### 6.5 Evaluation order and strictness

* Evaluation is **strict**: every operand of every operator is evaluated, including both operands of `and` and `or` (no short-circuit). `false and 1 / 0 > 0` raises R101.
* Operands are evaluated left to right. Since evaluation has no side effects other than runtime errors, the only observable consequence is which runtime error is reported if more than one could occur: the first in left-to-right, innermost-first (post-order) order.

### 6.6 Runtime errors

Each runtime error has a code and a fixed short description:

| Code | Description |
|---|---|
| R101 | `division by zero` |
| R102 | `integer overflow` |
| R103 | `non-finite float result` |

A runtime error raised during **base execution** terminates the program immediately (§9.3); output already produced remains. A runtime error raised during **hypothetical evaluation** inside a `whatif` does not terminate the program; it becomes part of the `whatif` report (§8.5).

Runtime errors are never detected at compile time, even when an operand is a literal (`1 / 0` compiles and fails when executed). The compiler **may** emit a warning but **must not** reject the program.

---

## 7. Declarations and name resolution

### 7.1 `input`

```
input NAME = literal_value
```

* Declares an input binding: an externally changeable value and an **override point** for `whatif`.
* **Type policy: the type is inferred from the literal's form** (§5.4). There are no annotations. `input rate = 0` is an `int`; write `input rate = 0.0` for a `float`.
* The initializer must be exactly one `literal_value`. Any other expression (`input x = 1 + 2`, `input y = x`) is error **E203**.
* The literal is the input's **base value** — the value used in ordinary execution — unless the program is started with `--set NAME=VALUE` for that input (§9.5, revision 4), in which case the launch value is the base value. Inputs cannot change during execution; within a run, the only way to vary an input is a hypothetical `whatif`.

### 7.2 `let`

```
let NAME = expression
```

* Declares an immutable computed binding. Its type is the static type of the expression.
* A binding is never reassigned. Declaring the same name again is error **E302**.

### 7.3 Name resolution and ordering

* **Declaration before use.** A name may be referenced only by statements that appear on a later line than its declaration. Referencing a name that is not declared earlier — whether it is never declared, declared later (forward reference), or is the binding being declared (`let x = x + 1`) — is error **E301**.
* **Unique names.** Each name is declared at most once in the program across inputs and lets (E302). Keywords and reserved words cannot be names (E201).
* **No shadowing**: there is one scope.
* **Acyclicity follows by construction**: every dependency points to an earlier declaration, so the dependency graph (§11) is acyclic and declaration order is a valid topological order.
* Unused inputs and unused lets are permitted. No warning is required.

---

## 8. Statements and execution

### 8.1 Execution model

A compiled program executes its statements **once, in source order**, against the **base environment** *E*, a map from declared names to values.

| Statement | Effect |
|---|---|
| `input x = v` | *E*[x] := v |
| `let x = e` | *E*[x] := eval(e, *E*) — eagerly, even if x is never used |
| `show`, `explain`, `impact` | print to stdout; *E* unchanged |
| `whatif` | build, report on, and discard a separate counterfactual environment; *E* unchanged |
| `assert` | check a condition in *E*; *E* unchanged |

Because names are resolved to earlier declarations only, every name a statement references already has a value in *E* when the statement executes. *E* is append-only: once a name has a value, that value never changes.

The **visible bindings** of a statement are the bindings declared on earlier lines. `whatif` and `impact` report only visible bindings.

### 8.2 Value formatting

All value output uses this format:

* `int`: decimal, with a leading `-` if negative. `-5`, `0`, `100`.
* `bool`: `true` or `false`.
* `float`: the shortest decimal digit string that converts back to exactly the same binary64 value (ties broken toward the digit string closest to the exact value). Let *x* be the decimal exponent of its first significant digit.
  * If −4 ≤ *x* < 16: positional notation with at least one digit after the point: `88.375`, `75.0`, `0.0001`, `-0.0`.
  * Otherwise: scientific notation `d[.ddd]e±XX`, exponent sign always present, at least two exponent digits: `1e+16`, `1.5e+16`, `1e-05`.
  * This is exactly the string produced by Python 3's `repr()` for a finite `float`, which serves as the reference oracle for tests.

### 8.3 `show`

```
show NAME
```

Prints one line to stdout: `NAME = VALUE`, with the value from *E*. `NAME` must be a visible binding (E301). `show` takes a name, not an expression; to show an expression, bind it with `let` first.

### 8.4 `explain`

```
explain NAME
```

Prints the derivation of a visible binding from the recorded dependency graph (§11) and the base environment. Output (stdout), every line after the header indented two spaces:

```
explain NAME
  <derivation tree>
  direct dependencies: <list>
  transitive dependencies: <list>
  inputs: <list>
  intermediates: <list>
```

**Derivation tree.** Pre-order, starting at `NAME`, each level indented two further spaces. Each node line is:

* input, first occurrence: `NAME = VALUE  [input]`
* let, first occurrence: `NAME = VALUE  [let: SOURCE]`, followed by its children
* any binding already printed earlier in this tree: `NAME = VALUE  [input, see above]` or `NAME = VALUE  [let, see above]`, with no children

`SOURCE` is the let's expression exactly as written in the source file, from its first to its last token (internal whitespace preserved). The children of a let are the distinct bindings its expression references directly, in order of first appearance in the expression. A binding referenced several times in one expression (`x * x`) appears once.

**Summary lists.** Names separated by `, `, in declaration order; `(none)` if empty.

* *Direct dependencies*: bindings referenced in `NAME`'s own expression.
* *Transitive dependencies*: all bindings reachable from `NAME` through dependency edges (includes direct ones; excludes `NAME` itself).
* *Inputs*: transitive dependencies that are inputs.
* *Intermediates*: transitive dependencies that are lets.

**Rules.**

* Constants (literals) are part of `SOURCE` but are not dependencies: they are not bindings and cannot be overridden.
* Explanations are keyed by **binding identity, never by value**. Two bindings with equal values computed differently (e.g. `let p = a + a` and `let q = a * 2`) are distinct entries; the explanation never merges or substitutes one for the other.
* Explaining an input prints its single node line and four `(none)` lists.
* Shared dependencies are expanded once (the first time in pre-order), so output size is linear in the number of bindings.

### 8.5 `whatif`

```
whatif NAME = literal_value                                  full form
whatif NAME = literal_value show TARGET                      targeted form
whatif NAME1 = literal_value, NAME2 = literal_value, ...     several overrides (either form)
```

Evaluates the program's visible bindings under hypothetical values for one or more inputs, without affecting the program's own execution. A statement contains one or more **overrides** separated by commas *(several overrides: revision 3)*. All of them are applied together before anything is re-evaluated.

#### 8.5.1 Static checks

The checks run override by override in source order, then on the target, so the first error in source order is reported (§9.2).

| Check | Error |
|---|---|
| each `NAME` is a visible binding | E301 at `NAME` |
| each `NAME` is an input, not a let | E303 at `NAME` |
| no input is overridden twice in one statement (`whatif a = 1, a = 2`) | E305 at the repeated `NAME` |
| each override is exactly one `literal_value`, followed by `,`, `show` or end of line | E203 at the first offending token |
| each override's type is its input's type, or the override is an `int` literal and the input is `float` | E403 at the override value |
| (targeted) `TARGET` is a visible binding | E301 at `TARGET` |
| (targeted) `TARGET` is a let that transitively depends on at least one overridden input | E304 at `TARGET` |

**Override typing.** Permitted combinations:

| Input type | Override literal | Result |
|---|---|---|
| `int` | integer | accepted |
| `float` | float | accepted |
| `float` | integer | accepted; promoted at compile time to the nearest `float` (§5.2): `1` → `1.0`, `-3` → `-3.0` |
| `bool` | `true` / `false` | accepted |
| `int` | float | E403 (no float-to-int conversion) |
| `int` / `float` | `true` / `false` | E403 |
| `bool` | integer or float | E403 |

The **override value** is the literal after any promotion. Promotion happens once, at compile time; it is not an operation in the dependency graph.

**Target rule.** The target of a targeted `whatif` must be a visible `let` that depends, directly or transitively, on at least one overridden input — equivalently, a name listed under `all dependents` by `impact NAME` at the same position for at least one overridden `NAME`. A target that is an input (including an overridden one) or a let that depends on none of the overridden inputs is rejected with E304: its hypothetical value would always equal its base value, so the statement can only be a mistake, and the dependency graph decides this at compile time.

#### 8.5.2 Evaluation

Let *E* be the base environment at this statement, *V* the visible bindings, and *C* the **dependency cone** of the statement: the visible lets that transitively depend on at least one overridden input (the union of the overridden inputs' cones).

1. Construct a fresh counterfactual environment *E′*: every visible binding outside *C* has its value from *E*; for every override, *E′*[NAME] := its override value. All overrides are in place before step 2, so a let depending on several overridden inputs sees all of their hypothetical values.
2. For each let *b* in *C*, in declaration order, determine its **hypothetical outcome**:
   * **unavailable** — if any direct dependency of *b* is *failed* or *unavailable*. *b* is not evaluated. Its **cause** is the earliest-declared failed binding among *b*'s transitive dependencies.
   * otherwise evaluate *b*'s expression under *E′* (strict, §6.5):
     * **value** *v* — evaluation succeeds; *E′*[b] := *v*.
     * **failed** with runtime error *R* at line:column *L*:*C* — evaluation raises *R* (the first error in evaluation order, §6.5). Evaluation of *b* stops; nothing is stored.
3. Print the report (§8.5.3).
4. Discard *E′* and all outcomes.

Because evaluation is pure, lets outside *C* have the same value in *E′* as in *E*; implementations **may** (and are intended to) reuse those values instead of recomputing them. The reported result must equal full re-evaluation of all visible lets. Only lets in *C* can fail, because all others already succeeded in *E*.

#### 8.5.3 Report

Both forms write only to stdout. Every line after the header is indented two spaces.

**Header.** `whatif NAME = VALUE` (full form) or `whatif NAME = VALUE show TARGET` (targeted form), where `VALUE` is the formatted override value after promotion: `whatif tax = 1 show total` prints the header `whatif tax = 1.0 show total`. With several overrides, the `NAME = VALUE` pairs appear in statement order separated by `, `: `whatif price = 160, discount = 0.5 show total`.

**Outcome lines.** `NAME: BASE -> RESULT` where `BASE` is the value in *E* and `RESULT` is:

| Outcome | `RESULT` |
|---|---|
| value, identical to base | `NEW  (unchanged)` |
| value, different | `NEW` |
| failed | `error[CODE] at LINE:COLUMN (DESCRIPTION)` — code, location of the failing operator, and the fixed description from §6.6 |
| unavailable | `unavailable (depends on CAUSE)` |

A value is *unchanged* if it is identical to the base value (same type and same bits; equivalently, the same formatted string). Hence `0.0 -> -0.0` is reported as changed.

**Full form.** After the header:

1. `  NAME: BASE -> VALUE  (override)` for each override, in statement order (an override equal to the base value is still marked `(override)`);
2. one outcome line for every let in *C*, in declaration order, including unchanged ones; or `  (no dependent bindings)` if *C* is empty.

**Targeted form.** After the header, exactly one outcome line, for `TARGET`. Outcomes of other bindings are not reported. Bindings that are neither `TARGET` nor among its transitive dependencies cannot affect the line; an implementation may skip evaluating them, and a failure in one of them is not observable.

#### 8.5.4 Isolation guarantees

* *E* is never modified by a `whatif`. *E′* and the outcomes are separate and are discarded at the end of the statement.
* Each `whatif` starts from *E*: overrides never accumulate, and a later `whatif` does not see an earlier one's override or failures.
* A hypothetical runtime error (a *failed* outcome) does not terminate the program, writes nothing to stderr, and does not change the exit status. Execution continues with the next statement.
* Assertions are not re-checked under a `whatif` (§8.7).

**Compatibility.** Several overrides were added in revision 3 exactly as revision 2 had pre-planned them: all overrides are applied in step 1, *C* is the union of their cones, and a target must depend on at least one overridden input. A statement with one override behaves, and prints, exactly as before.

### 8.6 `impact`

```
impact NAME
```

A forward dependency query. Reports which visible lets depend, directly or transitively, on `NAME` according to the **static dependency graph**. It performs no evaluation and makes **no claim that any value would change** for a particular input change — a binding can depend on `NAME` without its value changing (see `x * 0`, §11). Use `whatif` to see actual values.

`NAME` may be any visible binding (input or let). Output (stdout):

```
impact NAME
  direct dependents: <list>
  all dependents: <list>
```

* *Direct dependents*: visible lets whose own expression references `NAME`.
* *All dependents*: visible lets reachable from `NAME` against the direction of dependency edges (includes direct dependents).
* Lists are in declaration order, `, `-separated, `(none)` if empty.

`impact` takes an explicit binding and never refers to a previous `whatif`; it has no hidden state. For an input `NAME`, `all dependents` is exactly the cone *C* of §8.5 and exactly the set of valid targets for `whatif NAME = … show TARGET` at the same position.

### 8.7 `assert`

```
assert expression
```

* The expression must have type `bool` (**E402**).
* It is evaluated in *E* when the statement executes. Runtime errors during evaluation are base-execution runtime errors (§9.3).
* If `true`: no output; execution continues.
* If `false`: the program prints an assertion diagnostic to stderr (§9.3) and terminates with exit status 1. Later statements do not execute.
* Assertions check the base environment only. They are not re-evaluated inside `whatif`.

---

## 9. Output, diagnostics and exit status

### 9.1 Streams

`show`, `explain`, `whatif` and `impact` write to stdout, each line terminated by `\n`. Assertion failures and base-execution runtime errors write to stderr. There is no other output.

### 9.2 Compile-time diagnostics

Every compile-time error is reported as

```
FILE:LINE:COLUMN: error[CODE]: MESSAGE
```

Lines and columns are 1-based; columns count Unicode code points; a tab counts as one column. The **code and location are normative**; message wording is not. If any error is reported, no output program is produced. The compiler must report the first error in source order and may report additional errors.

Error locations: E101 at the offending character; E102–E104 at the first character of the literal; syntax errors at the unexpected token (a `NEWLINE` token is located at the line terminator, i.e. the column after the line's last character); E301 at the name reference; E302 at the second declaration's name; E303 and E305 at the overridden name; E304 at the target name; E403 at the first token of the override value (its `-` if present); E401 at the operator token; E402 at the first token of the assertion expression.

### 9.3 Runtime diagnostics (base execution only)

```
FILE:LINE:COLUMN: runtime error[CODE]: DESCRIPTION
```

The location is the operator that failed. Hypothetical runtime errors inside `whatif` never produce this diagnostic (§8.5.4).

```
FILE:LINE:COLUMN: assertion failed: SOURCE
  NAME = VALUE                           (one line per binding referenced in SOURCE)
```

The location is the `assert` keyword; `SOURCE` is the assertion expression as written; bindings are listed in order of first appearance, each once.

### 9.4 Exit status of a compiled program

| Status | Meaning |
|---|---|
| 0 | all statements executed (including any `whatif` with failed or unavailable outcomes) |
| 1 | an assertion failed |
| 2 | a runtime error occurred during base execution |
| 3 | invalid launch arguments (§9.5); no statement was executed *(revision 4)* |

---

### 9.5 Launch arguments *(revision 4)*

A compiled program accepts **launch arguments** that set inputs' base values before the first statement runs:

```
./pricing                                  # every input keeps its source value
./pricing --set price=150                  # price starts at 150
./pricing --set price=150 --set tax=0.2    # several inputs, any order
```

* The only accepted argument is `--set NAME=VALUE` (two arguments: `--set`, then `NAME=VALUE` with no spaces). It may be repeated, once per input. There are no other options and no positional arguments.
* `NAME` must be an input declared in the program. `VALUE` must be a `literal_value` (§5.4) written as one token: `true`, `false`, or an optional `-` followed by an integer or float literal with the rules of §3.5 (no leading zeros, digits on both sides of the point, an exponent only after a point). Its type must fit the input exactly as for a `whatif` override (§8.5.1): an integer literal may set a `float` input and is promoted to the nearest `float`; any other mismatch is rejected.
* An input that is not set keeps its source literal. Inputs remain immutable once execution starts.
* **All arguments are validated before the first statement runs.** If any is invalid, the program prints one diagnostic for the first invalid argument (in argument order) to stderr, prints nothing to stdout, and exits with status 3. Otherwise all launch values are applied together.
* The launch values become the inputs' values in the base environment *E* (§8.1). `show`, `explain`, `impact`, `assert` and runtime errors behave as if the source literals had been those values; `whatif` reports them as its `BASE` values and still evaluates in a separate environment (§8.5.4). A valid launch value that makes a computation fail produces an ordinary runtime error (§9.3, exit status 2), not an argument error.
* With no arguments, a program behaves and prints exactly as before revision 4. Repeated runs with the same source and the same arguments produce identical output; arguments are the only external input (no environment variables, no locale).

Diagnostic format, on stderr:

```
FILE: argument error[CODE]: MESSAGE
```

| Code | Condition | Corresponds to |
|---|---|---|
| A101 | an argument other than `--set` (unknown option or positional argument) | — |
| A102 | `--set` is the last argument, or its operand is not `NAME=VALUE` with a non-empty name and value | — |
| A103 | `NAME` is not a declared binding | E301 |
| A104 | `NAME` is a `let`, not an input | E303 |
| A105 | the same input is set more than once | E305 |
| A106 | `VALUE` is not a literal (`007`, `1e5`, `+5`, `0x10`, `nan`, `inf`, `True`, ` 1`, …) | E101, E102, E203 |
| A107 | `VALUE`'s type does not fit the input (a float for an `int`, a number for a `bool`, a bool for a number) | E403 |
| A108 | an integer literal whose magnitude exceeds 2^63 − 1 | E103 |
| A109 | a float literal that rounds to infinity | E104 |

For one argument, the checks run in this order: A102, A103, A104, A105, then the value (A106, A108, A109, then A107).

## 10. Error catalogue

| Code | Phase | Condition |
|---|---|---|
| E101 | lexical | invalid character (includes non-ASCII outside comments, lone CR, `!`, `%`, `.` not in a float) |
| E102 | lexical | malformed numeric literal (leading zero, `1.`, missing exponent digits, literal followed by identifier character or `.`) |
| E103 | lexical | integer literal exceeds 2^63 − 1 |
| E104 | lexical | float literal rounds to infinity |
| E201 | syntax | unexpected token (includes keyword/reserved word used as a name, two statements on one line, missing operand, unbalanced parentheses, `show`/`explain`/`impact` or a `whatif` target `show` followed by a non-name, anything after a `whatif` target, a `,` outside a `whatif`, a `,` not followed by an override) |
| E202 | syntax | chained comparison |
| E203 | syntax | `input` initializer is not exactly one `literal_value` followed by end of line; a `whatif` override is not exactly one `literal_value` followed by `,`, `show` or end of line |
| E301 | name | name not declared on an earlier line |
| E302 | name | name already declared |
| E303 | name | `whatif` override target is a `let`, not an input |
| E304 | dependency | `whatif` report target is not a let that transitively depends on at least one overridden input |
| E305 | name | the same input is overridden more than once in one `whatif` (revision 3) |
| E401 | type | operator applied to unsupported operand types |
| E402 | type | `assert` condition is not `bool` |
| E403 | type | `whatif` override type is incompatible with the input's type (§8.5.1) |
| R101 | runtime | division by zero |
| R102 | runtime | integer overflow |
| R103 | runtime | float result is infinite or NaN |
| A101–A109 | launch | invalid launch argument; see §9.5 *(revision 4)* |

---

## 11. Dependency model

Definitions used by `explain`, `whatif` and `impact`:

* A **binding** is an input or a let.
* **Dependency edge.** *B* → *A* ("B depends directly on A") iff *A* is a binding referenced in *B*'s expression. Inputs have no outgoing edges. Edges always point from a later declaration to an earlier one. Literals are not bindings and have no edges.
* **Direct dependencies** of *B*: { *A* | *B* → *A* }.
* **Transitive dependencies** of *B*: all *A* reachable from *B* by one or more edges.
* **Direct dependents** of *A*: { *B* | *B* → *A* }. **All dependents**: all *B* from which *A* is reachable.
* **Inputs / intermediates** of *B*: its transitive dependencies that are inputs / lets.

The graph is **structural**: it is determined by the source text, not by values. `let z = x * 0` depends on `x` even though no value of `x` changes `z`. Consequently:

* `impact` reports structural dependents ("may be affected").
* `whatif` reports structural dependents together with their hypothetical outcomes, distinguishing changed, `(unchanged)`, failed and unavailable.
* The `whatif` target rule (E304) is decided by the same structural graph: `whatif x = 7 show z` is valid for `let z = x * 0`, and reports `(unchanged)`.
* Compiler optimizations must never remove an edge (see [compiler-architecture.md](compiler-architecture.md) §5).

This graph records how the program computes values. It is not a causal model of any real-world system.

---

## 12. Worked example

Source: [../examples/pricing.cau](../examples/pricing.cau), reproduced exactly (line numbers matter for the error location in the output):

```
# Pricing model demonstrating show, assert, explain, whatif and impact.
# The exact expected output is given in docs/language-specification.md §12.

input price = 100
input discount = 0.25
input tax = 0.125
input fee = 4
input units = 4

let savings = price * discount
let subtotal = price - savings
let total = subtotal * (1 + tax) + fee
let expensive = total > 50.0
let per_unit = total / units
let bulk = per_unit < 30.0

show total
assert total >= 0

# Backward: how was total derived?
explain total

# Hypothetical inputs. Each whatif starts from the original inputs.
whatif price = 160
whatif discount = 0.5 show total
whatif tax = 1 show total          # int literal promoted: tax is a float input
whatif price = 160, discount = 0.5 show total   # several overrides, applied together
whatif units = 0                   # hypothetical division by zero is reported, not fatal

# Forward, static: which bindings depend on a given binding?
impact price
impact discount
impact total

# The original values are unaffected by the whatif statements above.
show total
show per_unit
```

Required stdout (exit status 0, no stderr):

```
total = 88.375
explain total
  total = 88.375  [let: subtotal * (1 + tax) + fee]
    subtotal = 75.0  [let: price - savings]
      price = 100  [input]
      savings = 25.0  [let: price * discount]
        price = 100  [input, see above]
        discount = 0.25  [input]
    tax = 0.125  [input]
    fee = 4  [input]
  direct dependencies: tax, fee, subtotal
  transitive dependencies: price, discount, tax, fee, savings, subtotal
  inputs: price, discount, tax, fee
  intermediates: savings, subtotal
whatif price = 160
  price: 100 -> 160  (override)
  savings: 25.0 -> 40.0
  subtotal: 75.0 -> 120.0
  total: 88.375 -> 139.0
  expensive: true -> true  (unchanged)
  per_unit: 22.09375 -> 34.75
  bulk: true -> false
whatif discount = 0.5 show total
  total: 88.375 -> 60.25
whatif tax = 1.0 show total
  total: 88.375 -> 154.0
whatif price = 160, discount = 0.5 show total
  total: 88.375 -> 94.0
whatif units = 0
  units: 4 -> 0  (override)
  per_unit: 22.09375 -> error[R101] at 14:22 (division by zero)
  bulk: true -> unavailable (depends on per_unit)
impact price
  direct dependents: savings, subtotal
  all dependents: savings, subtotal, total, expensive, per_unit, bulk
impact discount
  direct dependents: savings
  all dependents: savings, subtotal, total, expensive, per_unit, bulk
impact total
  direct dependents: expensive, per_unit
  all dependents: expensive, per_unit, bulk
total = 88.375
per_unit = 22.09375
```

Notes:

* The tree lists `total`'s children in order of appearance (`subtotal`, `tax`, `fee`) while summary lists use declaration order (`tax`, `fee`, `subtotal`).
* `expensive` depends on `price` but does not change (`(unchanged)`); `bulk` does change.
* `whatif tax = 1` is accepted because `tax` is a `float` input; the header shows the promoted value `1.0`.
* `whatif price = 160, discount = 0.5` applies both overrides before re-evaluating, so `total` uses both hypothetical values (savings 80.0, subtotal 80.0, total 94.0); neither override alone gives this result.
* `whatif units = 0` fails hypothetically in `per_unit` (line 14, the `/` at column 22); `bulk` is unavailable. The program continues and exits with status 0.
* Each `whatif` starts from the base environment, and the final `show` statements print base values, demonstrating isolation.
* All values in this example are exactly representable in binary64.

---

## 13. Deferred features (not in version 1)

The following are explicitly **not** part of version 1. Programs using them are rejected with the error listed, and no implementation phase should assume them.

| Feature | Version 1 behavior | Note |
|---|---|---|
| Conditionals (`if … then … else`) | `if`/`then`/`else` reserved (E201) | Requires a decision between static (all-branch) and dynamic (taken-branch) dependencies; unresolved |
| Loops, recursion, mutable variables | no syntax | would break the acyclic model |
| Mutable inputs; inputs from the environment, files or stdin | not available | launch arguments (`--set`, §9.5) were added in revision 4; inputs remain immutable during a run |
| Launch-argument conveniences (`--help`, listing inputs, a `--` separator, several errors per run, marking launch-set inputs in `explain`) | not available | deferred in revision 4 |
| User-defined functions | no syntax | |
| Strings, collections | no syntax | |
| Type annotations | `int`/`float`/`bool` reserved (E201) | literal-based inference retained (D02) |
| `%`, `//`, `**`, math functions | E101 | `%` sign semantics differ between C and Python; deferred to avoid a trap |
| Several targets per `whatif` | E201 after the first target | |
| `whatif` on a `let` (intervening on an intermediate) | E303 | |
| `explain` inside a counterfactual | not available | |
| Re-checking assertions under `whatif` | not performed | |
| `show`/`explain`/`impact` of an arbitrary expression | E201 | bind with `let` first (D09) |
| Short-circuit `and`/`or` | strict evaluation | (D08) |
| Line continuation, multi-line statements | not available | |
| Unicode identifiers | E101 | |
| Modules, imports | no syntax | |
