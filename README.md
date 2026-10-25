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
| `input`, `let`, `show`, `explain`, `whatif` (one or more overrides, optional `show` target), `impact`, `assert` | conditionals, loops, functions, recursion, mutation |
| types `int`, `float`, `bool`; arithmetic, comparison, boolean operators | strings, collections, type annotations, `%` `//` `**` |
| static type checking, declaration-before-use | several targets per `whatif` |
| launch-time input values (`--set NAME=VALUE`) | inputs from environment variables, files or stdin; mutable inputs |

Full list: [language-specification.md §13](docs/language-specification.md#13-deferred-features-not-in-version-1).

## Current phase

**Phase 9 — release readiness.** A verified [getting-started guide](#getting-started), a [demonstration](docs/demonstration.md) whose shell commands and outputs are executed by the tests, and a reproducible [evaluation](docs/evaluation.md). No language changes.

**Phase 8 — launch arguments.** A compiled program can set inputs when it starts: `./pricing --set price=150 --set tax=0.2` ([language-specification §9.5](docs/language-specification.md), decision D25). Values follow the source literal rules, including int-to-float promotion. Invalid arguments are rejected before anything runs, with `argument error[A101–A109]` on stderr and exit status 3. Run without arguments, every program behaves and prints exactly as before.

**Phase 7 — several overrides per `whatif`.** A hypothetical can now change several inputs at once, all applied together before anything is recomputed: `whatif price = 160, discount = 0.5 show total` ([language-specification §8.5](docs/language-specification.md), decision D24). A repeated input is rejected (E305), and a target must depend on at least one overridden input (E304). One-override statements behave and print exactly as before.

**Phase 6 — runtime.** CAUSA programs compile end to end: the compiler checks a `.cau` program, lowers it to Causal IR, optimizes it while preserving every source-level binding and dependency, and generates C. A C compiler then builds that C together with the CAUSA runtime library into an executable. Every statement of language version 1 runs (`show`, `explain`, `whatif` in both forms, `impact`, `assert`, and runtime errors R101–R103), and the output of every runtime case in [tests/specification-cases.md](tests/specification-cases.md) is checked byte for byte by automated tests.

This is a first implementation for a university compiler project, not a production system. It has been tested end to end only with GCC on Windows (MSYS2 UCRT64), and it relies on the C library rounding `printf`/`strtod` correctly (see risk R1). The deferred language features of [language-specification §13](docs/language-specification.md#13-deferred-features-not-in-version-1) remain unsupported.

| Stage | Status |
|---|---|
| Lexer (`causa/lexer.py`) | implemented and tested |
| Parser and AST (`causa/parser.py`, `causa/astnodes.py`) | implemented and tested |
| Semantic analysis (`causa/semantic.py`): names, types, `whatif` overrides and targets (E301–E304, E401–E403) | implemented and tested |
| Causal IR (`causa/ir.py`): nodes, actions, provenance graph, validator | implemented and tested |
| Optimizer (`causa/optimizer.py`): constant folding, same-binding common-subexpression elimination, removal of dead constants; never folds anything that could raise a runtime error | implemented and tested |
| C code generation (`causa/codegen.py`, `causa/runtime/causa_runtime.h`): deterministic C99 with checked 64-bit integer and IEEE float arithmetic, exact float literals, and metadata tables for the runtime | implemented and tested |
| Runtime library (`causa/runtime/causa_runtime.c`): value formatting identical to Python's `repr` for floats, `show`, `explain`, `whatif` (isolated counterfactual environments, failed and unavailable outcomes), `impact`, assertion diagnostics | implemented and tested end to end |

## Getting started

### Prerequisites

| Tool | Needed for | Verified with |
|---|---|---|
| Python 3.11 or later, standard library only | the compiler and the tests | CPython 3.11.9 on Windows 11 |
| A C99 compiler | building and running generated programs; the C half of the tests | GCC 16.1.0, MSYS2 UCRT64, on Windows 11 |
| Git | cloning | |

There is nothing to install: no packages, no build system. The compiler runs from the repository root as `python -m causa`. On Windows the Python launcher is `py -3.11`, used below; elsewhere use your Python 3.11+ interpreter (for example `python3.11`). The compiler never runs the C compiler itself.

### Clone and check

```bash
git clone https://github.com/ujvall/Causa.git
```

```bash
cd Causa
```

```bash
py -3.11 -m causa check examples/pricing.cau
```

This prints `examples/pricing.cau: semantic check passed: 5 inputs, 6 lets, 24 statements (not executed)` (Windows prints the path as `examples\pricing.cau`).

### Compile and run a program

Generate C, build it together with the runtime library, and run it. `build/` is ignored by Git:

```bash
mkdir -p build
```

```bash
py -3.11 -m causa emit-c examples/pricing.cau -o build/pricing.c
```

```bash
gcc -std=c99 -I causa/runtime build/pricing.c causa/runtime/causa_runtime.c -o build/pricing -lm
```

```bash
./build/pricing
```

The executable prints exactly the output in [language-specification §12](docs/language-specification.md#12-worked-example). In Windows PowerShell, use `mkdir build -Force` and run `.\build\pricing.exe`. The generated C also compiles warning-free with `-Wall -Wextra -Wpedantic -Werror`, which the tests check.

**Header-only programs.** A program with only `input` and `let` statements needs just `causa_runtime.h`. `--standalone` confirms this, and fails with exit status 3 for a program that needs the runtime library:

```bash
py -3.11 -m causa emit-c examples/unit-price.cau --standalone -o build/unit-price.c
```

```bash
gcc -std=c99 -I causa/runtime build/unit-price.c -o build/unit-price -lm
```

**Setting inputs at launch.** Every compiled program accepts repeated `--set NAME=VALUE` options that replace input values before anything runs ([language-specification §9.5](docs/language-specification.md)):

```bash
./build/pricing --set price=150 --set discount=0.3
```

`VALUE` is written like a CAUSA literal (`150`, `0.3`, `-2.5`, `true`); an integer is accepted for a `float` input. Inputs not mentioned keep their source values. An invalid argument stops the program before any output with `FILE: argument error[A1xx]: …`.

A guided tour of every feature, with the exact output of each command, is in [docs/demonstration.md](docs/demonstration.md).

### Run the tests

```bash
py -3.11 -m unittest discover -s tests
```

The tests use only the standard library's `unittest` and take about 2–3 minutes on the machine above. They find a C compiler through `$CAUSA_CC`, else `gcc`, `clang` or `cc` on `PATH`; without one, the tests that build C are skipped, not failed. With GCC, none are skipped.

### Exit statuses

| Program | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| `python -m causa …` | success | CAUSA diagnostic (`FILE:LINE:COLUMN: error[CODE]: …`) | usage error, or a file cannot be read or written | `--standalone` on a program that needs the runtime library |
| a compiled program | success, including `whatif`s with failed outcomes | an assertion failed | a runtime error (R101–R103) | invalid `--set` arguments (A101–A109); nothing ran |

All diagnostics go to stderr. Compiled programs end every line with `\n`, on Windows too; the compiler's own messages use the platform's line ends.

### Common errors

| Symptom | Cause |
|---|---|
| `causa: error: argument command: invalid choice: 'examples/pricing.cau'` | the command (`check`, `emit-c`, …) is missing before the file name |
| `causa: cannot write build/pricing.c: No such file or directory` | the output directory does not exist; create `build/` first |
| `fatal error: causa_runtime.h: No such file or directory` | `-I causa/runtime` is missing from the C compiler command |
| `collect2: error: ld returned 1 exit status` | `causa/runtime/causa_runtime.c` is missing from the C compiler command for a program that uses `show`, `explain`, `whatif`, `impact` or `assert` (`emit-c` prints a note listing them) |
| `argument error[A107]` | a launch value of the wrong type, for example `--set price=1.5` for an `int` input |

### Portability

* Verified: Windows 11 with Python 3.11.9 and MSYS2 UCRT64 GCC 16.1.0, in Git Bash and Windows PowerShell 5.1; the full test suite passes with no skips. The compiler-only tests (no C compiler present) also pass with Python 3.14 on Ubuntu 26.04 under WSL.
* Not verified: building and running generated C on Linux or macOS, Clang, MSVC, and other C libraries. The generated C is standard C99, and the runtime has a Windows-only branch for binary output. Float formatting depends on a correctly rounded `printf`/`strtod` (risk R1), which the tests check.

## Compiler commands

| Command | Output |
|---|---|
| `tokens FILE` | one token per line (`LINE:COLUMN KIND LEXEME`) |
| `parse FILE` | the AST as S-expressions |
| `check FILE` | parse and semantic analysis; reports success or the first diagnostic |
| `ir FILE` | the validated, unoptimized Causal IR: node table, steps, bindings and binding-level dependencies |
| `optimize FILE` | the optimized Causal IR and a log of every fold, refused fold (`skip`), merge and removal |
| `emit-c FILE [-o OUT.c] [--standalone]` | generated C on stdout or in `OUT.c`. Prints a note with the build inputs when the program uses the runtime library; `--standalone` rejects such programs instead |

Diagnostics use the format `FILE:LINE:COLUMN: error[CODE]: MESSAGE`; for example `check examples/invalid-type-error.cau` reports `E401` at 8:19. The compilation API is `causa.frontend.check(text)`, `compile_to_ir(text, source_file)`, `compile_optimized(text, source_file)` and `compile_to_c(text, source_file, standalone=False)`.

## Testing

The tests cover tokens, AST structure, operator precedence, all compile-time errors with their locations, semantic typing and dependency rules, IR construction and every IR invariant (including deliberately corrupted IR), the IR and folding examples in [compiler-architecture §3.6](docs/compiler-architecture.md), the optimizer's folding results, runtime-error safety (no folding of division by zero, overflow or non-finite results), preserved dependencies (`x * 0`, `x - x`), determinism and idempotence, and the generated C (exact text of each translation, metadata, runtime calls, `--standalone`). When a C compiler is found, the tests also:

* compile every valid specification program warning-free with `-std=c99 -Wall -Wextra -Wpedantic -Werror`;
* build and run every runtime specification case and compare stdout, stderr and exit status exactly ([tests/test_runtime.py](tests/test_runtime.py)), including the full §12 example;
* check float formatting against Python's `repr` on 35,000 values;
* run additional regression programs (isolation across repeated `whatif`s, strict `or` inside a `whatif`, `impact` over multiple paths, equal-valued bindings in `explain`, assertion diagnostics, integer extremes);
* check that corrupted metadata tables and invalid `whatif` requests are rejected before any output, and (on Windows) that `explain` handles a 2,000-level dependency chain in a 64 KiB stack;
* run launch-argument cases L01–L21, check that `--set` gives the same result as editing the source, and compare the C literal parser with the Python lexer on about 12,000 strings ([tests/test_launch.py](tests/test_launch.py));
* run every shell command in [docs/demonstration.md](docs/demonstration.md) and compare its output ([tests/test_demo.py](tests/test_demo.py)).

## Evaluation

[docs/evaluation.md](docs/evaluation.md) reports compile times, C build times, run times, the optimizer's effect and `whatif` recomputation counts, measured with [benchmarks/benchmark.py](benchmarks/benchmark.py):

```bash
py -3.11 benchmarks/benchmark.py
```

Possible next steps: a single `build`/`run` command that invokes the C compiler, testing other compilers and C libraries (Clang, MSVC, glibc), and the deferred language features.

## Documents

| Document | Contents |
|---|---|
| [docs/language-specification.md](docs/language-specification.md) | syntax, types, semantics of every construct, output format, errors |
| [docs/grammar.ebnf](docs/grammar.ebnf) | formal lexical and syntactic grammar |
| [docs/compiler-architecture.md](docs/compiler-architecture.md) | pipeline, stage interfaces, Causal IR contract, runtime boundary |
| [docs/semantic-decisions.md](docs/semantic-decisions.md) | decision log with rationale and alternatives |
| [docs/demonstration.md](docs/demonstration.md) | guided demonstration with exact outputs |
| [docs/evaluation.md](docs/evaluation.md) | measurements and how to reproduce them |
| [tests/specification-cases.md](tests/specification-cases.md) | specification test cases with expected outcomes |
| [examples/](examples/) | `minimal.cau`, `pricing.cau` (the demonstration program), `unit-price.cau` (header-only build), `invalid-type-error.cau` (intentionally invalid) |
| [causa/](causa/) | compiler package: `lexer.py`, `parser.py`, `astnodes.py`, `semantic.py`, `ir.py`, `optimizer.py`, `codegen.py`, `frontend.py`, `diagnostics.py`, CLI in `__main__.py`; runtime in `runtime/causa_runtime.h` and `runtime/causa_runtime.c` |
| [tests/](tests/) | `test_lexer.py`, `test_parser.py`, `test_semantic.py`, `test_ir.py`, `test_optimizer.py`, `test_codegen.py`, `test_runtime.py`, `test_launch.py`, `test_demo.py`, `test_spec_cases.py` |
| [benchmarks/benchmark.py](benchmarks/benchmark.py) | evaluation script |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Git workflow and sole-contributor rules |

## Known design risks

* **R1 — Float formatting in C.** *Implemented in Phase 6* ([compiler-architecture §6.5](docs/compiler-architecture.md)): precision search with `printf("%e")` and `strtod`, plus a neighbour check for powers of two. It matches Python's `repr` on every value tested (35,000 per test run; 364,457 during development). Residual risk: correctness depends on the C library's `printf` and `strtod` being correctly rounded, which has been verified only with MSYS2 UCRT64 GCC on Windows. The formatting test detects a non-conforming library.
* **R2 — Conditionals.** Deferred because the dependency semantics are unresolved: static (both branches) vs dynamic (taken branch only) dependencies give different `explain`/`impact` answers. Strict `and`/`or` (D08) will need revisiting at the same time.
* **R3 — Exact override typing.** *Resolved in revision 2 (D15):* integer literals now promote for `float` inputs.
* **R4 — Counterfactual errors terminate.** *Resolved in revision 2 (D16):* hypothetical errors are reported as `error[…]` / `unavailable` outcomes and the program continues. Residual risk: error codes, locations and descriptions are now part of stdout, so they must be implemented identically in the runtime and any reference oracle.
* **R5 — C toolchain.** `causa` does not invoke a C compiler; the user runs one (see [Getting started](#getting-started)). Only MSYS2 UCRT64 GCC on Windows has been verified; MSVC, Clang and Linux/macOS toolchains are untested.
* **R6 — Inputs are only changeable through `whatif`.** *Resolved in revision 4 (D25):* `--set NAME=VALUE` sets inputs at launch. Residual risk: the C literal parser must keep agreeing with the Python lexer; a differential test checks this.
* **R7 — Static `whatif` target rule (D23).** A targeted `whatif` whose target stops depending on the input after a source edit becomes a compile error (E304). Intended, but it makes `whatif` statements sensitive to refactoring; the alternative (report `(independent)`) remains available if this proves too strict.
