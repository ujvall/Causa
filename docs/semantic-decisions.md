# CAUSA Semantic Decision Log — Version 1

Each entry: **Decision** (chosen behavior), **Rationale**, **Alternatives** considered, **Implications** for later phases. Section references point to [language-specification.md](language-specification.md) (LS) and [compiler-architecture.md](compiler-architecture.md) (CA).

---

### D01 — One statement per line, newline-terminated
* **Decision:** Statements are terminated by line ends; no semicolons, no line continuation.
* **Rationale:** Every statement starts with a distinct keyword, so newline termination keeps the grammar LL(1) with no terminator ambiguity. Source text of an expression is always on one line, which simplifies `explain` output.
* **Alternatives:** semicolons; free-form layout; continuation inside parentheses.
* **Implications:** The lexer emits `NEWLINE` tokens and synthesizes a final one. Long expressions must be split into several `let`s (which also makes explanations more informative). Continuation can be added later without breaking programs.

### D02 — Input types inferred from the literal form
* **Decision:** `input` has no type annotation; `100` is `int`, `100.0` is `float`, `true` is `bool`. Initializers must be a single literal value (optionally negated).
* **Rationale:** One consistent policy with no new syntax. The literal's form already is an unambiguous type annotation. Literal-only initializers keep inputs as leaves of the graph.
* **Alternatives:** mandatory annotations (`input price: int = 100`); optional annotations; initializer expressions.
* **Implications:** `input rate = 0` is an `int`, so `whatif rate = 0.5` is rejected (E403). The compiler should suggest writing `0.0`. Annotations can be added later; `int`, `float`, `bool` are reserved for that.
* **Revision 2:** reviewed and retained. No annotations in version 1.

### D03 — Declaration before use; single namespace; no redeclaration
* **Decision:** Names are visible only on lines after their declaration; all bindings share one scope; redeclaration is E302.
* **Rationale:** Makes the dependency graph acyclic by construction (no cycle check needed), makes declaration order a topological order, and gives one obvious resolution rule for every statement, including `whatif` and `impact`.
* **Alternatives:** order-independent declarations with cycle detection; shadowing.
* **Implications:** Semantic analysis is a single pass. Self-reference and forward references are both E301.

### D04 — Three types, one implicit conversion
* **Decision:** `int` (64-bit), `float` (binary64), `bool`. Only int-to-float promotion in mixed arithmetic/comparison. No truthiness.
* **Rationale:** Small, predictable, maps directly to C types.
* **Alternatives:** single numeric type; arbitrary-precision integers; decimal floats.
* **Implications:** IR makes every promotion an explicit `itof` node. Mixed comparisons of large integers (> 2^53) can be inexact; documented, not an error.

### D05 — `/` is always true division producing `float`
* **Decision:** `7 / 2` is `3.5`; `6 / 3` is `2.0`. `//` and `%` are deferred.
* **Rationale:** The motivating domain (pricing, ratios) expects true division; a single meaning avoids the C/Python mismatch in integer division and modulo of negative numbers.
* **Alternatives:** C-style truncating integer division; Python-style `//` and `%`.
* **Implications:** Code generator always emits `div` on promoted operands.

### D06 — Infinity and NaN are not values; overflow is an error
* **Decision:** Division by zero (R101), integer overflow (R102), and non-finite float results (R103) are runtime errors. In base execution they terminate the program; inside `whatif` they are reported as hypothetical outcomes (D16).
* **Rationale:** Keeps `==` reflexive, keeps output formatting total, and avoids C undefined behavior on signed overflow. Produces explicit diagnostics instead of silently propagating `inf`/`nan` through explanations.
* **Alternatives:** IEEE semantics with `inf`/`nan` values; wrapping integers.
* **Implications:** Generated C must check before every `int` add/sub/mul/neg and every `div`, and check `isfinite` after float operations.

### D07 — Runtime errors are never compile-time errors
* **Decision:** `1 / 0` compiles and fails at run time. The compiler may warn but must not reject.
* **Rationale:** One rule; avoids making the language definition depend on how much constant evaluation the compiler performs.
* **Alternatives:** reject divisions by literal zero.
* **Implications:** The optimizer must not fold operations that would fail (CA §5).

### D08 — Strict evaluation, no short-circuit
* **Decision:** Both operands of `and`/`or` are always evaluated; all lets are evaluated eagerly, even unused ones.
* **Rationale:** Dependencies are static and structural; evaluating every node keeps "what was computed" equal to "what the graph says". Without conditionals there is no practical need for laziness.
* **Alternatives:** short-circuit operators (would make the set of evaluated nodes value-dependent).
* **Implications:** `false and 1 / 0 > 0` raises R101. Revisit together with conditionals (see risk R2 in README).
* **Revision 2:** reviewed and retained. Under `whatif`, strictness means `false and x / d > 0` is a *failed* outcome when `d` is hypothetically 0 (D16).

### D09 — `show`, `explain`, `impact` take a binding name, not an expression
* **Decision:** Their argument is an identifier.
* **Rationale:** Every reported item then has a name, a declaration, and an identity in the provenance graph; output format is unambiguous.
* **Alternatives:** arbitrary expressions with anonymous nodes.
* **Implications:** Users write `let x = …` before `show x`. Easy to extend later.
* **Revision 2:** reviewed and retained. The `whatif … show TARGET` form (D12) follows the same rule: its target is a binding name.

### D10 — Output format and determinism
* **Decision:** Values print in a fixed format; floats use shortest round-trip representation identical to Python's `repr`. Fixed line formats for every statement.
* **Rationale:** Byte-exact expected output is required for end-to-end testing and for cross-checking the C runtime against a Python reference.
* **Alternatives:** `printf("%g")` (loses precision, ambiguous), fixed decimals.
* **Implications:** The C runtime must implement shortest round-trip formatting (e.g. try increasing precision with `%.*e` until `strtod` round-trips, then lay out per LS §8.2). Unresolved implementation risk R1.

### D11 — `explain` is binding-level, structural, and identity-based
* **Decision:** Explanations show bindings (inputs and lets) with values and source text; constants appear only inside source text; shared dependencies are expanded once and later marked `see above`; bindings are never merged by value.
* **Rationale:** Source-level names are what a programmer understands; operation-level detail is captured by the source text. Expand-once keeps output linear in program size.
* **Alternatives:** operation-level explanation trees; full re-expansion of shared subtrees (exponential for diamonds); value-based deduplication (incorrect provenance).
* **Implications:** The IR keeps explicit `bind` nodes and per-binding source text (CA §3.2).

### D12 — `whatif` full report, plus an optional targeted form *(revised in revision 2)*
* **Decision:** `whatif x = v` prints the override and every visible let that transitively depends on `x`, in declaration order, marking unchanged ones `(unchanged)` (bit identity). `whatif x = v show T` prints only the outcome line for `T` (base value and hypothetical outcome). Both forms coexist (LS §8.5.3).
* **Rationale:** The full report distinguishes "depends on" from "changed", which the language must not conflate. In larger programs the full report is noisy when only one result matters; the targeted form answers that question directly. Reusing the `show` keyword avoids a new keyword and reads naturally.
* **Alternatives:** full report only (revision 1); targeted only; a new keyword such as `for` or `report`; allowing several targets.
* **Implications:** Grammar adds optional `whatif_target`. The header echoes the target. Runtime may restrict evaluation to the target's upstream part of the cone (CA §6.3). Several targets per statement are deferred. Fully backward compatible with revision 1 programs.

### D23 — A `whatif` target must depend on the overridden input *(new in revision 2)*
* **Decision:** In `whatif x = v show T`, `T` must be a visible let that transitively depends on `x`; otherwise E304 (LS §8.5.1). Inputs, including `x` itself, are never valid targets.
* **Rationale:** The dependency graph is static, so whether `T` can be affected is known at compile time. A non-dependent target always reports base = hypothetical, so the statement can only be a mistake; rejecting it is consistent with how CAUSA treats other statically decidable errors. The set of valid targets is exactly `impact x`'s "all dependents", which ties the three operations together. Dependence is structural, so a dependent target whose value does not change (`x * 0`) is valid and reports `(unchanged)` — the rule never claims numeric change.
* **Alternatives:** allow any visible binding and print `(independent)`; allow any binding silently.
* **Implications:** Semantic analysis needs the binding-level graph (already built for IR provenance) before reporting E304; it can be computed incrementally in the same pass, because dependencies are always earlier declarations. Editing a program so that `T` no longer depends on `x` turns the `whatif` into a compile error, which is intended. For future multi-override `whatif`, the rule generalizes to "depends on at least one overridden input".

### D13 — `whatif` isolation by separate environment
* **Decision:** Each `whatif` builds a fresh environment from the base environment and discards it. The base is never written.
* **Rationale:** Guarantees no counterfactual can affect later statements or other counterfactuals.
* **Alternatives:** scoped mutation with rollback (fragile under errors).
* **Implications:** Runtime passes the base array as `const`; tests check later `show`s and consecutive `whatif`s.

### D14 — `whatif` sees only bindings declared before it
* **Decision:** Uses the same visibility rule as every other statement.
* **Rationale:** Uniform name resolution; the statement executes at its position in the program.
* **Alternatives:** whole-program visibility for `whatif`.
* **Implications:** Placing `whatif` at the end of a program reports everything. Tests cover a `let` declared after a `whatif`.

### D15 — Overrides apply to inputs only; int literals promote to float inputs *(revised in revision 2)*
* **Decision:** The overridden name must be an input (E303). The literal must have the input's type, except that an integer literal overriding a `float` input is promoted at compile time to the nearest `float` (`whatif tax = 1` gives `1.0`). All other mismatches remain E403: float literal for an `int` input, any number for a `bool` input, `true`/`false` for a numeric input.
* **Rationale:** Revision 1 required exact types, which made `whatif rate = 1` fail for `input rate = 0.5` for no useful reason. Int-to-float promotion is already the language's single implicit conversion (D04), so allowing it here adds no new kind of conversion. The reverse direction (float to int) would lose information and stays rejected. Inputs are the only externally changeable values; intervening on a computed value is a different operation with different semantics.
* **Alternatives:** exact types only (revision 1); allow any numeric conversion; allow overriding lets (do-style interventions).
* **Implications:** Semantic analysis converts the override literal when needed; the IR stores the already-promoted `float` value, so no `itof` node is created and the dependency graph is unchanged. The `whatif` header prints the promoted value (`1.0`) so the user sees what was evaluated. Literal range checks (E103) apply before promotion; integers above 2^53 may round. Overriding lets remains deferred. Resolves README risk R3.

### D16 — Hypothetical runtime errors are reported, not fatal *(revised in revision 2)*
* **Decision:** During `whatif` evaluation each let in the dependency cone has one of three outcomes: a **value**; **failed** (its evaluation raised R101–R103), shown as `error[CODE] at LINE:COLUMN (DESCRIPTION)`; or **unavailable** (a direct dependency failed or is unavailable; not evaluated), shown as `unavailable (depends on CAUSE)` where `CAUSE` is the earliest-declared failed binding among its transitive dependencies. The program does not terminate, nothing is written to stderr, and the exit status is unaffected. Base-execution runtime errors still terminate with status 2 (LS §8.5.2–§8.5.4).
* **Rationale:** A hypothetical that fails is a meaningful answer ("with zero units, the per-unit cost is undefined"), not a defect in the program. Terminating — the revision 1 rule — let a question about a hypothetical world destroy the real execution, contradicting isolation. Marking dependents unavailable instead of evaluating them avoids inventing values. Naming the earliest failed cause is deterministic and points to the root problem.
* **Alternatives:** terminate (revision 1); propagate a special error value through operators (would need error-aware arithmetic in every node and blur failed vs. dependent-on-failed); omit failed bindings from the report.
* **Implications:** The runtime's node evaluator must report errors to its caller instead of exiting (CA §6.3); base execution then exits, `whatif` records the outcome. Outcomes live only in the counterfactual state and are discarded. Error codes and fixed descriptions (LS §6.6) become part of stdout and therefore normative. Resolves README risk R4.

### D17 — `impact` is a static forward query on an explicit binding
* **Decision:** `impact NAME` lists direct and all dependents of `NAME` (input or let) among visible bindings. It does not reference earlier `whatif` statements and makes no claim of value change.
* **Rationale:** The original sketch `impact total` was ambiguous (dependents of `total`? or inputs affecting `total`? or relative to the last `whatif`?). Hidden "most recent whatif" state is non-declarative and makes a statement's meaning depend on unrelated lines. The backward query is already `explain`. Making `impact` the forward query gives three distinct operations: backward (`explain`), forward static (`impact`), forward with values (`whatif`).
* **Alternatives:** `impact` relative to the most recent `whatif`; `impact` listing the inputs of a binding.
* **Implications:** `impact total` remains valid syntax but reports what depends on `total` (often nothing); the pricing example uses `impact price`.
* **Revision 2:** reviewed and retained. `impact X` lists every visible let that depends on `X` directly or transitively and never implies numeric change. For an input `X`, its "all dependents" list is exactly the set of valid `whatif X = … show T` targets (D23).

### D18 — Assertions check only the base environment
* **Decision:** `assert` is evaluated once at its position; failure prints the condition and the values of referenced bindings to stderr and exits with status 1. Not re-checked during `whatif`.
* **Rationale:** Keeps `whatif` a pure query with a single well-defined report.
* **Alternatives:** re-check assertions under every counterfactual and report violations.
* **Implications:** Counterfactual assertion checking is deferred. Assert expression nodes are owned by the assert and excluded from `whatif` re-evaluation.

### D19 — Explicit `bind` nodes and a frozen provenance graph in the IR
* **Decision:** Each `let` gets a `bind` node; the binding-level graph is computed before optimization, stored, and re-verified after optimization.
* **Rationale:** Separates source-level identity from computation, allows the optimizer to rewrite operations freely within a binding, and turns "optimizations preserve explanations" into a mechanically checked invariant.
* **Alternatives:** annotate root op nodes with binding names (fails for `let a = x` aliases and merged expressions).
* **Implications:** IR verification failure is an internal compiler error.

### D20 — Inputs are never constant-folded
* **Decision:** Input nodes remain runtime values even though their base values are known at compile time.
* **Rationale:** The entire base execution is computable at compile time; without this rule an optimizer could fold the program to constants, erasing the override points that `whatif` requires.
* **Alternatives:** none acceptable.
* **Implications:** Leaves room for launch-time input overrides later without IR changes.

### D21 — Generated code targets C99 with a separate C runtime source
* **Decision:** One generated `.c` file plus `causa_runtime.c`/`.h`, standard library only.
* **Rationale:** Portable, inspectable, no third-party dependencies.
* **Alternatives:** emit the runtime inline into each output; target LLVM IR.
* **Implications:** Driver must locate a system C compiler (risk R5).

### D22 — Error codes are normative, messages are not
* **Decision:** Each diagnostic has a stable code and location; wording may change.
* **Rationale:** Tests assert on codes and locations, not prose.
* **Implications:** Test cases reference codes (tests/specification-cases.md).

---

## Revision log

### Revision 2 (2026-10-22) — before Phase 2

| Decision | Change |
|---|---|
| D02 | Reviewed, retained (literal-based input types, no annotations). |
| D08 | Reviewed, retained (strict `and`/`or`); note added on interaction with `whatif`. |
| D09 | Reviewed, retained (`show`/`explain`/`impact` take names). |
| D12 | Added targeted form `whatif x = v show T`; full form unchanged. |
| D15 | Integer literal overrides promote to `float` inputs; other mismatches still E403. |
| D16 | Hypothetical runtime errors become *failed* / *unavailable* outcomes; program continues. |
| D17 | Reviewed, retained; linked to the target rule. |
| D23 | New: `whatif` target must transitively depend on the overridden input (E304). |
| — | Conditionals, mutable or runtime-supplied inputs and all other deferred features remain out of version 1. |

Affected documents: grammar (`whatif_target`), language specification §3.4, §5.2, §6.6, §7.1, §8.5, §8.6, §9, §10, §11, §12, §13; compiler architecture §3.4, §6; examples/pricing.cau; tests/specification-cases.md. Dependency direction, Causal IR node model and invariants are unchanged.

### Phase 2 clarifications (2026-10-22) — found while implementing the lexer and parser

No language behavior changed. Three inconsistencies between documents were resolved in favor of the language specification:

| Issue | Resolution | Files |
|---|---|---|
| LS §3.6 and §13 say `**` and `//` are E101, but under the EBNF they lexed as two valid `*` / `/` tokens (giving E201). | The lexer rejects the exact sequences `**` and `//` with E101. `* *` with a space is still two tokens. | grammar.ebnf (comment), causa/lexer.py |
| CA §2.1 described lexing the whole file before parsing, which would report a lexical error on a later line before an earlier syntax error, contradicting LS §9.2 ("first error in source order"). | The parser pulls tokens lazily from a generator; `tokenize()` still returns a full list for tools. | compiler-architecture.md §2.1 |
| CA §2.2's AST node list predated revision 2 (no `whatif` target, no node for binding-name arguments). | Node list updated to the implemented AST. | compiler-architecture.md §2.2 |

### Phase 3 clarifications (2026-10-22) — found while implementing semantic analysis and the Causal IR

No language behavior changed and no error code was added.

| Issue | Resolution | Files |
|---|---|---|
| LS §9.2 requires the first error in source order, but running semantic analysis after the whole file is parsed would report a syntax error on line 5 before a semantic error on line 2. | Parsing and analysis are interleaved: the parser yields each statement once its line is complete (before the next line is lexed) and the analyzer checks it immediately. A statement is analyzed only after it parses, so a syntax error *within* one statement is reported even if an earlier column of that statement has a semantic problem (e.g. `whatif x = 5 show` with undeclared `x` gives E201). | causa/parser.py (`iter_statements`), causa/frontend.py |
| Within one expression, "source order" is ambiguous when an operator's operand is itself ill-typed (`true + (1 + false)`): the outer operator cannot be type-checked. | Expressions are checked in post-order and the first error stops analysis. An operator is never checked when an operand failed, so the reported error is always the earliest error that is actually determinable. Within a statement, checks follow source position: `let` name (E302) before its expression; `whatif` name (E301/E303), then value (E403), then target (E301/E304). | causa/semantic.py |
| CA §3 did not fix the owner name of assert-expression nodes, how a promoted override keeps its original literal, or the order of a binding's dependencies. | Recorded in compiler-architecture §3.7: owners `assert#K`; `WhatIf` keeps both `value` (normalized) and `source_value` plus literal location; provenance keeps `direct_deps` (declaration order) and `references` (first-appearance order). | compiler-architecture.md §3.7 |
| An IR invariant violation is a compiler bug, not a user error. | `validate_ir` raises `IRValidationError`, which is not a `CausaError` and is never formatted as a diagnostic. | causa/ir.py |
