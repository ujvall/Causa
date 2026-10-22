# CAUSA

**A Compiler for Explainable and Counterfactual Programming**

CAUSA is a small declarative programming language, and a compiler for it written from scratch, in which the computational dependencies of a program are a first-class language feature. A CAUSA program can explain how a value was derived, evaluate the program under hypothetical inputs without disturbing the original results, and list which values depend on a given input.

```
input price = 100
input discount = 0.25

let savings = price * discount
let total = price - savings

show total            # total = 75.0
explain total         # derivation tree with values and source expressions
whatif price = 160    # every dependent value, before and after
whatif price = 160 show total   # just one result, before and after
impact price          # which bindings depend on price
```

CAUSA tracks *computational* dependencies: how a program computes values from other values. It does not model or establish real-world causation.

## Core idea

* **Declarative and acyclic.** Inputs and immutable `let` bindings, each defined from earlier ones. The dependency structure is a DAG known at compile time.
* **Causal IR.** The compiler lowers programs to a custom intermediate representation with stable node IDs, explicit dependency edges, source locations and a binding-level provenance graph that optimizations are verified not to change.
* **Compiled, not interpreted.** The compiler (Python 3.11+, standard library only) generates C; a system C compiler builds an executable linked with the small CAUSA runtime, which records values and implements `explain`, `whatif` and `impact`.

## Version 1 scope

| Included | Deferred |
|---|---|
| `input`, `let`, `show`, `explain`, `whatif` (one override, optional `show` target), `impact`, `assert` | conditionals, loops, functions, recursion, mutation, runtime-supplied inputs |
| types `int`, `float`, `bool`; arithmetic, comparison, boolean operators | strings, collections, type annotations, `%` `//` `**` |
| static type checking, declaration-before-use | multiple overrides per `whatif`, launch-time input overrides |

Full list: [language-specification.md §13](docs/language-specification.md#13-deferred-features-not-in-version-1).

## Current phase

**Phase 5 — C code generation (implemented).** The compiler checks `.cau` programs, lowers them to Causal IR, optimizes that IR while preserving every source-level binding and dependency, and generates C. **The compiler is not complete.** Programs containing only `input` and `let` statements compile to complete C programs that run and report runtime errors (R101–R103) exactly as specified. `show`, `explain`, `whatif`, `impact` and `assert` compile to calls into the CAUSA runtime library, which is **not implemented yet** (Phase 6): such programs compile but cannot be linked into executables, and the compiler says so whenever it emits them.

| Stage | Status |
|---|---|
| Lexer (`causa/lexer.py`) | implemented and tested |
| Parser and AST (`causa/parser.py`, `causa/astnodes.py`) | implemented and tested |
| Semantic analysis (`causa/semantic.py`): names, types, `whatif` overrides and targets (E301–E304, E401–E403) | implemented and tested |
| Causal IR (`causa/ir.py`): nodes, actions, provenance graph, validator | implemented and tested |
| Optimizer (`causa/optimizer.py`): constant folding, same-binding common-subexpression elimination, removal of dead constants; never folds anything that could raise a runtime error | implemented and tested |
| C code generation (`causa/codegen.py`, `causa/runtime/causa_runtime.h`): deterministic C99 with checked 64-bit integer and IEEE float arithmetic, exact float literals, and metadata tables for the runtime | implemented and tested |
| CAUSA runtime library: value formatting, `show`, `explain`, `whatif`, `impact`, assertion diagnostics | **not yet implemented** (Phase 6) |

Requires Python 3.11+ and only the standard library. From the repository root:

```bash
py -3.11 -m causa check examples/pricing.cau
```

```bash
py -3.11 -m causa ir examples/pricing.cau
```

| Command | Output |
|---|---|
| `tokens FILE` | one token per line (`LINE:COLUMN KIND LEXEME`) |
| `parse FILE` | the AST as S-expressions |
| `check FILE` | parse and semantic analysis; reports success or the first diagnostic |
| `ir FILE` | the validated, unoptimized Causal IR: node table, steps, bindings and binding-level dependencies |
| `optimize FILE` | the optimized Causal IR and a log of every fold, refused fold (`skip`), merge and removal |
| `emit-c FILE [-o OUT.c] [--standalone]` | generated C on stdout or in `OUT.c`. Prints a note naming any statements that need the unimplemented runtime library; `--standalone` makes that an error |

To build generated C (no compiler is run by `causa` itself):

```bash
py -3.11 -m causa emit-c program.cau -o program.c --standalone
```

```bash
gcc -std=c99 -I causa/runtime program.c -o program
```

Diagnostics use the format `FILE:LINE:COLUMN: error[CODE]: MESSAGE`; for example `check examples/invalid-type-error.cau` reports `E401` at 8:19. The exit status is 0 on success, 1 on a CAUSA error, 2 if a file cannot be read or written, and 3 if the backend cannot produce the requested output (`--standalone` with runtime-library statements). The compilation API is `causa.frontend.check(text)`, `compile_to_ir(text, source_file)`, `compile_optimized(text, source_file)` and `compile_to_c(text, source_file, standalone=False)`.

Run the tests (standard-library `unittest`; no pytest needed):

```bash
py -3.11 -m unittest discover -s tests
```

The tests cover tokens, AST structure, operator precedence, all compile-time errors with their locations, semantic typing and dependency rules, IR construction and every IR invariant (including deliberately corrupted IR), the IR and folding examples in [compiler-architecture §3.6](docs/compiler-architecture.md), the optimizer's folding results, runtime-error safety (no folding of division by zero, overflow or non-finite results), preserved dependencies (`x * 0`, `x - x`), determinism and idempotence, and the generated C (exact text of each translation, metadata, runtime calls, `--standalone`). When a C compiler is found (`$CAUSA_CC`, else `gcc`/`clang`/`cc` on `PATH`), the tests also compile every valid specification program warning-free with `-std=c99 -Wall -Wextra -Wpedantic -Werror`, run generated programs to check values and overflow/division boundaries, and execute the specification's runtime-error cases. Without a compiler those tests are skipped, not failed. Every case in [tests/specification-cases.md](tests/specification-cases.md) is run through the front end. Runtime, assertion and output expectations in that document are **not yet tested**, because nothing executes programs yet.

Next phase: 6, the CAUSA runtime library (value formatting, `show`, `explain`, `whatif`, `impact`, assertion diagnostics) and end-to-end tests of complete programs.

## Documents

| Document | Contents |
|---|---|
| [docs/language-specification.md](docs/language-specification.md) | syntax, types, semantics of every construct, output format, errors |
| [docs/grammar.ebnf](docs/grammar.ebnf) | formal lexical and syntactic grammar |
| [docs/compiler-architecture.md](docs/compiler-architecture.md) | pipeline, stage interfaces, Causal IR contract, runtime boundary |
| [docs/semantic-decisions.md](docs/semantic-decisions.md) | decision log with rationale and alternatives |
| [tests/specification-cases.md](tests/specification-cases.md) | specification test cases with expected outcomes |
| [examples/](examples/) | `minimal.cau`, `pricing.cau`, `invalid-type-error.cau` (intentionally invalid) |
| [causa/](causa/) | compiler package: `lexer.py`, `parser.py`, `astnodes.py`, `semantic.py`, `ir.py`, `optimizer.py`, `codegen.py`, `frontend.py`, `diagnostics.py`, CLI in `__main__.py`; runtime header in `runtime/causa_runtime.h` |
| [tests/](tests/) | `test_lexer.py`, `test_parser.py`, `test_semantic.py`, `test_ir.py`, `test_optimizer.py`, `test_codegen.py`, `test_spec_cases.py` |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Git workflow and sole-contributor rules |

## Known design risks

* **R1 — Float formatting in C.** Output must match shortest round-trip formatting (Python `repr`). The C standard library has no direct equivalent; the runtime must search precisions and verify with `strtod`. Correct but needs careful testing.
* **R2 — Conditionals.** Deferred because the dependency semantics are unresolved: static (both branches) vs dynamic (taken branch only) dependencies give different `explain`/`impact` answers. Strict `and`/`or` (D08) will need revisiting at the same time.
* **R3 — Exact override typing.** *Resolved in revision 2 (D15):* integer literals now promote for `float` inputs.
* **R4 — Counterfactual errors terminate.** *Resolved in revision 2 (D16):* hypothetical errors are reported as `error[…]` / `unavailable` outcomes and the program continues. Residual risk: error codes, locations and descriptions are now part of stdout, so they must be implemented identically in the runtime and any reference oracle.
* **R5 — C toolchain on Windows.** The driver must find a C compiler (MSVC, MinGW, clang); its exact behavior is not yet specified.
* **R6 — Inputs are only changeable through `whatif`.** Base input values are fixed in the source; launch-time overrides are deferred. The IR keeps inputs as runtime values so this can be added without redesign.
* **R7 — Static `whatif` target rule (D23).** A targeted `whatif` whose target stops depending on the input after a source edit becomes a compile error (E304). Intended, but it makes `whatif` statements sensitive to refactoring; the alternative (report `(independent)`) remains available if this proves too strict.
