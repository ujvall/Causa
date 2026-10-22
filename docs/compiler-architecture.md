# CAUSA Compiler Architecture — Version 1

Status: **Phase 1 design contract.** No stage described here is implemented yet. Interfaces below define what each stage must provide; internal data structures may be refined in later phases as long as these contracts hold. Language semantics are defined in [language-specification.md](language-specification.md); this document never redefines them.

---

## 1. Pipeline

```
CAUSA source (.cau)
    -> Lexer                 tokens
    -> Parser                AST
    -> Semantic analysis     annotated AST (names resolved, types assigned)
    -> IR builder            Causal IR (unoptimized) + frozen provenance graph
    -> Optimizer             Causal IR (optimized), verified against provenance
    -> C code generator      generated C source
    -> System C compiler     executable (generated C + CAUSA runtime C source)
```

The CAUSA compiler (written in Python 3.11+, standard library only) performs every step up to and including C generation itself. No parser generator, `eval`, `ast` module, or external compiler framework is used for CAUSA source. The system C compiler is used only to translate generated C into machine code.

Errors from any frontend stage stop the pipeline before IR construction; no C is generated for an invalid program.

## 2. Stage responsibilities and interfaces

### 2.1 Lexer

* **Input:** source bytes and file name.
* **Output:** sequence of tokens `(kind, lexeme, line, column)` ending with `EOF`; kinds: `IDENT`, `INT`, `FLOAT`, each keyword, each reserved word, each operator, `NEWLINE`, `EOF`. Tokens also carry character offsets so that the parser can recover exact source text.
* **Laziness (clarified in Phase 2):** the parser consumes tokens on demand from a generator rather than from a fully built list. Language-specification §9.2 requires the first error *in source order*; if the whole file were lexed first, a lexical error on a later line would hide an earlier syntax error. With on-demand lexing the parser only ever holds the current token, so whichever error occurs first in the source is reported. `tokenize()` still returns a complete list for tools and tests.
* **Responsibilities:** UTF-8 decoding, BOM skipping, line terminator handling, comment removal, maximal munch, literal validation and conversion (E101–E104), synthesizing a final `NEWLINE`. Literal values are converted here: `int` via exact integer parsing; `float` via correctly rounded decimal-to-binary64 conversion.

### 2.2 Parser

* **Input:** token list. **Output:** AST.
* Hand-written recursive descent, one function per grammar rule of [grammar.ebnf](grammar.ebnf). The grammar is LL(1) at statement level (each statement starts with a distinct keyword) and in expressions (precedence climbing by rule).
* Produces E201–E203.
* Every AST node carries a source span (start line/column, end line/column). Each `let` and `assert` keeps its expression's **source text** (the exact characters between its first and last token), required by `explain` and assertion diagnostics.

AST node set (one per grammar construct; implemented in `causa/astnodes.py`): `Program(statements)`, `InputDecl(name, value)`, `LetDecl(name, value, source_text)`, `ShowStmt(name)`, `ExplainStmt(name)`, `WhatIfStmt(name, value, target)` (`target` is absent for the full-report form), `ImpactStmt(name)`, `AssertStmt(condition, source_text)`, `Name(text)` for every binding-name argument, `Literal(type, value)`, `NameRef(name)`, `UnaryOp(op, operand)`, `BinaryOp(op, left, right)`. Every node has a span; operator nodes also record the operator token's span (for E401 and runtime error locations). Parentheses produce no node; a parenthesized expression's span is widened to include its parentheses. *(Phase 2: the revision 1 list lacked the `whatif` target and the `Name` node.)*

### 2.3 Semantic analysis

* **Input:** AST. **Output:** AST annotated with resolved binding references and a static type on every expression node; a symbol table `name -> (kind, type, declaration index, location)`.
* Single pass in source order, adding each declaration to the table after its expression is checked. This alone enforces declaration-before-use and rejects self-reference (E301), and detects E302, E303.
* Type checking per language-specification §6.3 (E401, E402, E403). Marks operands that need int-to-float promotion. Converts an integer `whatif` override for a `float` input to its `float` value (language-specification §8.5.1).
* Maintains each binding's set of transitive dependencies as declarations are added (each is the union of its direct dependencies and their sets, all of which are earlier). Uses it to check `whatif` targets (E304).

**Implemented interface (Phase 3, `causa/semantic.py`).** `analyze(statements) -> SemanticProgram` accepts a `Program` or the parser's statement iterator and raises the first `CausaError`. `SemanticProgram` holds the unmodified AST (`program`), `symbols` (name → `Symbol(name, kind, type, index, declaration, direct_deps, transitive_deps)`, in declaration order), `visible` (per statement, the number of bindings declared before it), `overrides` (statement index → `Override(literal, type, value, promoted)`, where `literal` is the untouched AST node and `value` is normalized) and per-expression static types (`type_of(expr)`). The typing rules live in `binary_signature` / `unary_signature`, which the IR builder reuses to place `itof` nodes. `causa/frontend.py` runs the pipeline: `check(text)` interleaves parsing and analysis one statement at a time, so the first error in source order is reported whichever stage finds it; `compile_to_ir(text)` additionally builds and validates the IR.

### 2.4 IR builder

* **Input:** annotated AST. **Output:** Causal IR (§3) and its provenance graph (§4).
* **Implemented (Phase 3, `causa/ir.py`):** `build_ir(semantic_program, source_file) -> IRModule`; `validate_ir(module)` checks every invariant of §3–§4 and raises `IRValidationError`, an internal compiler error that is never shown as a user diagnostic; `check_against_program(module, semantic_program)` checks that each let's direct dependencies equal the names its AST expression references; `topological_order(module)` returns the deterministic order (Kahn's algorithm, smallest ready ID first); `format_ir(module)` prints the textual form of §3.6.

### 2.5 Optimizer

* **Input/Output:** Causal IR. Must satisfy §5. Ends with a verification pass. The optimizer may be a no-op; correctness never depends on it.

### 2.6 C code generator

* **Input:** optimized Causal IR. **Output:** one C99 source file.
* Emits: value storage for every node, one evaluation routine per node (or equivalent), the static metadata tables of §6.2, and a `main` that executes the IR step list in order by calling into the runtime for actions. Source text, names and file name are emitted as escaped C string literals.
* Generated C must be deterministic: same Causal IR, same C text.

### 2.7 System C compiler and runtime

* The runtime is a C99 source file (`causa_runtime.c` / `.h`) shipped with the compiler, compiled together with the generated file. It depends only on the C standard library (including `<math.h>`; linking `-lm` where required).
* Locating and invoking the system C compiler (e.g. `cc`, `gcc`, `clang`, MSVC `cl`) is a driver concern for a later phase. A `--emit-c` mode that stops after generation is planned so the pipeline is testable without a C compiler.

---

## 3. Causal IR contract

Causal IR is a typed, straight-line, single-assignment graph IR. Each value-producing node is computed exactly once in the base execution, and its dependencies are explicit operand references.

### 3.1 Module

A Causal IR module contains:

1. `source_file`: the file name used in diagnostics.
2. `nodes`: table of nodes indexed by node ID.
3. `steps`: an ordered list, each either `def(node_id)` or an action (§3.4). This is the execution order.
4. `bindings`: map from binding name to its anchor node ID (input or bind node).
5. `provenance`: the frozen binding-level dependency graph (§4).

### 3.2 Nodes

Every node has:

| Field | Meaning |
|---|---|
| `id` | stable node ID `n0, n1, …` |
| `kind` | `input`, `const`, `op`, or `bind` |
| `type` | `int`, `float` or `bool` |
| `operands` | ordered list of node IDs (direct dependency edges) |
| `loc` | source line and column (§3.5) |
| `owner` | the binding or assert action whose source construct created the node |

Kind-specific fields:

| Kind | Fields | Operands | Meaning |
|---|---|---|---|
| `input` | `name`, `default` (literal value) | none | an input binding; override point for `whatif` |
| `const` | `value` | none | literal constant |
| `op` | `opcode` | 1 or 2 | primitive operation |
| `bind` | `name`, `source_text` | exactly 1 | a `let` binding: its value is its operand's value |

Opcodes: `add sub mul div neg` (arithmetic), `eq ne lt le gt ge` (comparison), `and or not` (boolean), `itof` (int-to-float promotion). Every `op` node's operand types already match exactly; implicit promotion is always an explicit `itof` node, so code generation never re-derives typing rules. `div` operands are always `float`.

**Why `bind` nodes exist.** A `let`'s value is computed by its expression's root node, but source-level bindings need their own identity: `let a = x` creates no operation, and `let p = a + a` / `let q = a + a` must stay distinct bindings for `explain` even if their operations are merged. The `bind` node is the source-level anchor that `explain`, `whatif` and `impact` refer to.

### 3.3 Node IDs and topological order

* IDs are assigned by the IR builder in creation order using a fixed traversal: statements in source order; within an expression, post-order — left operand, right operand, then any `itof` for the left operand, then any `itof` for the right operand, then the operation; then the statement's `bind` node.
* A name reference creates no node; it uses the referenced binding's anchor ID.
* **Stability:** compiling the same source text always yields the same IDs. IDs are not stable across edits to the source; nothing may persist them across compilations.
* **Topological invariant:** every operand ID is smaller than the ID of the node using it. Ascending ID order is therefore a valid evaluation order, and it matches source order.
* The optimizer never renumbers a surviving node, and never reuses a removed ID.

### 3.4 Steps and actions

`steps` interleaves node definitions with actions in source order. Actions:

| Action | Operands | Notes |
|---|---|---|
| `show(anchor)` | binding anchor | |
| `explain(anchor)` | binding anchor | |
| `whatif(input_node, value, target, visible)` | input anchor, literal, optional target anchor | `value` already has the input's type (promoted if needed); `target` is absent for the full form; `visible` = number of bindings declared before the statement |
| `impact(anchor, visible)` | binding anchor | |
| `assert(root, source_text, refs, loc)` | expression root node; anchors referenced in the expression | |

Every node referenced by an action is defined by an earlier step. Visibility is expressed by declaration index; because IDs follow source order, "visible" is equivalent to "anchor ID less than the next node ID to be assigned when the statement is reached".

### 3.5 Source locations

* `input` and `bind` nodes: the declared name's token.
* `const`: the literal token.
* `op` (except `itof`): the operator token (runtime errors are reported here).
* `itof`: the operand it converts.

### 3.6 Illustrative IR

Source:

```
input price = 100
input discount = 0.20
let total = price * (1 - discount)
```

Unoptimized Causal IR (the textual form is illustrative; only the information content is normative):

```
; id   kind/opcode  operands        type    loc     owner      extra
n0  = input                         int     1:7     price      name=price default=100
n1  = input                         float   2:7     discount   name=discount default=0.2
n2  = const                         int     3:22    total      value=1
n3  = op itof       n2              float   3:22    total
n4  = op sub        n3, n1          float   3:24    total
n5  = op itof       n0              float   3:13    total
n6  = op mul        n5, n4          float   3:19    total
n7  = bind          n6              float   3:5     total      name=total source_text="price * (1 - discount)"

steps: def n0, def n1, def n2, def n3, def n4, def n5, def n6, def n7
bindings: price -> n0, discount -> n1, total -> n7
```

Node-level dependency edges (n → m means "n uses m"):
`n3→n2, n4→n3, n4→n1, n5→n0, n6→n5, n6→n4, n7→n6`.

Checks against the language semantics:

* `1 - discount` is `int - float`, so the `1` is promoted (`n3`) and the result is `float`. `price * (…)` is `int * float`, so `price` is promoted (`n5`). Both promotions follow §5.2 / §6.3 of the specification.
* Every operand ID is smaller than its user: n0…n7 is a topological order.
* Binding-level graph (§4): from `n7`, following operands until an anchor is reached, gives `{n0, n1}`, i.e. `total → price`, `total → discount`. The constant `n2` is not a binding and is not a dependency.
* Base values: n0=100, n1=0.2, n2=1, n3=1.0, n4=0.8, n5=100.0, n6=80.0, n7=80.0, so `show total` would print `total = 80.0`. Note `discount` was written `0.20` but its value prints as `0.2`.

After constant folding (§5), `n2` and `n3` collapse into a single constant with the surviving ID `n3`; `n2` is retired:

```
n3  = const                         float   3:22    total      value=1.0
```

The binding-level graph is unchanged, and `explain total` still prints `price * (1 - discount)` because it uses `source_text`, not the folded operations.

`py -3.11 -m causa ir FILE` prints this textual form for any program, and `tests/test_ir.py` checks that the IR built for the source above reproduces the node table, `steps`, `bindings` and edge list in this section exactly.

### 3.7 Implemented schema (Phase 3)

`causa/ir.py` implements §3.1–§3.5 with these concrete choices, which the contract left open:

| Element | Implementation |
|---|---|
| Module | `IRModule(source_file, nodes, steps, bindings, provenance)`; `nodes` is a tuple in ascending ID order |
| Node | `Node(id, kind, type, operands, line, column, owner, opcode, name, value, source_text)`; `value` is the const value or the input default |
| Owner of assert nodes | `"assert#K"` for the K-th `assert` statement (0-based). `#` cannot occur in a binding name, so owners never collide |
| Steps | `Def(node)`, `Show(anchor, line)`, `Explain(anchor, line)`, `Impact(anchor, visible, line)`, `WhatIf(input, value, value_type, source_value, promoted, target, visible, line, value_line, value_column)`, `Assert(root, source_text, refs, line, column)` |
| `whatif` value | `value` is normalized to the input's type; `source_value` and `value_line`/`value_column` keep the literal as written (for reports and later diagnostics); `promoted` records int-to-float promotion. Promotion creates no node |
| `assert` on a bare name | `root` is the binding's anchor; no node is created |
| Provenance | `Provenance(bindings)` of `BindingInfo(name, kind, type, anchor, index, line, column, source_text, direct_deps, references)`. `direct_deps` is in declaration order; `references` is the same set in first-appearance order (the order `explain` uses for children) |
| Reverse direction | `Provenance.direct_dependents` and `all_dependents()` are derived indexes; the canonical edges are always operand lists (user → used) |

---

## 4. Provenance graph (binding-level dependency graph)

The source-level graph defined in language-specification §11 is derived from the IR:

* Vertices: the anchors (`input` and `bind` nodes).
* For each `bind` node *B*: direct dependencies = the anchors reached by walking *B*'s operands downward, stopping at (and collecting) each anchor reached. Inputs have none.
* Edge direction: *B* → *A* means *B* depends directly on *A* (same direction as node operand edges).
* Dependents are the reverse relation.

The IR builder computes this graph from the **unoptimized** IR and stores it as `provenance`, together with each binding's name, kind, type, declaration index, location and source text. `explain`, `whatif`'s report set, and `impact` are defined entirely in terms of `provenance` and binding values, never in terms of individual `op` nodes.

## 5. Optimization requirements

Allowed:

* **Constant folding** of an operation whose operands are all `const` nodes, when evaluating it raises no runtime error. Folding `1 / 0` is forbidden: the runtime error is observable behavior and must occur at its original position.
* **Common-subexpression elimination** of identical `op`/`const` nodes **with the same owner** only.
* **Removal** of `op`/`const` nodes that no longer have users after the above.

Forbidden:

* Removing, merging, or folding `input` or `bind` nodes. Inputs are override points and must remain runtime values (this also keeps launch-time overrides possible later). Unused lets are not removed: their evaluation can raise observable runtime errors.
* Any rewrite that removes a reference to an anchor, even when algebraically valid (`x * 0 → 0`, `x - x → 0`, `b or true → true`). Such rewrites remove dependency edges.
* Reordering a node definition across an action, or reordering two operations that can raise runtime errors. Stdout, stderr and exit status must be identical with and without optimization.
* Changing any binding's `source_text`, `loc`, name, type, or declaration index.

**Verification pass (mandatory).** After optimization, the compiler re-derives the binding-level graph from the optimized IR and checks it is identical to `provenance`, and checks the topological invariant. A mismatch is an internal compiler error, never a silent change.

### 5.1 Implemented optimizer (Phase 4)

`causa/optimizer.py` provides `optimize(module) -> OptimizationResult(module, log)`. It validates its input, makes one pass over the nodes in ascending ID order, and validates its output. `causa.frontend.compile_optimized(text)` runs the whole pipeline, and `py -3.11 -m causa optimize FILE` prints the optimized IR followed by the log. The unoptimized IR (`compile_to_ir`, `causa ir`) is unchanged.

| Transformation | When it applies | Safety constraint |
|---|---|---|
| **Constant folding** | an `op` node whose operands are all `const` nodes | Evaluated with CAUSA semantics. `int` results are computed exactly and must lie in [−2^63, 2^63 − 1] (else R102). `float` operations use IEEE binary64 round-to-nearest-even, which Python floats implement exactly for `+ - * /` and int-to-float conversion, and the result must be finite (else R103). A zero divisor (including `-0.0`) is never folded (R101). When folding would hide a runtime error the node is left in place, keeping its location, and a `skip` entry records the reason. `and`/`or` are folded only when *both* operands are constants, so strict evaluation is never shortened. |
| **Common-subexpression elimination** | an `op`/`const` node identical to an earlier node with the **same owner** (same kind, type, opcode, operands, and value compared by `repr`, so `0.0` and `-0.0` stay distinct) | Never across owners, so two bindings with the same expression stay separate. All of an owner's nodes lie between the same two actions, so no evaluation moves across an action. A removed duplicate fails only if the surviving earlier node fails first, at an earlier location, so the reported runtime error cannot change. |
| **Removal** | CSE duplicates; `const` nodes left with no users after folding | Only constants (which cannot fail) and duplicates are removed. `input` and `bind` nodes and unused lets are never removed. |

Details:

* A folded node keeps its ID, owner and location (the operator's location, or for a folded `itof` the operand's), as in the §3.6 example. Removed IDs are retired, never reused, and their `def` steps are dropped.
* The optimizer never looks through a binding reference, because a reference operand is an `input` or `bind` node, never a `const`. Identities such as `x * 0`, `x - x`, `x * 1` and `b or true` are therefore never rewritten, and every edge to an anchor survives.
* **Two linked representations.** `provenance` (the binding-level graph, built from the unoptimized IR) is carried over unchanged: the optimized module holds the same object. The optimized node graph is what later code generation will consume. `explain`, `impact` and the `whatif` report set read only `provenance`, binding values and `source_text`. The verification pass re-derives the binding-level graph from the optimized nodes and requires it to equal `provenance`. The optimizer also checks that bindings, anchor nodes (apart from their operand) and every action are unchanged. A bind or assert operand may be redirected, for example when a folded root equals an earlier constant of the same owner.
* **Log.** Each entry is `fold`, `skip`, `cse` or `remove`, with the node, the values involved and the justification, in a deterministic order (folds, skips and CSE in node order, then removals).
* **Idempotence.** Running `optimize` on its own output returns an equal module; the second log contains only the same `skip` entries.

## 6. Code generation and runtime boundary

### 6.1 Division of responsibility

| Concern | Compiler (Python) | Generated C | Runtime (C) |
|---|---|---|---|
| Parsing, types, names, IR, provenance | ✓ | | |
| Base evaluation of nodes in topological order | | ✓ | |
| Runtime checks (R101–R103) | | ✓ (detects, returns status) | base execution: reports and exits; `whatif`: records outcome |
| Value formatting (§8.2) | | | ✓ |
| `show`, `explain`, `impact` output | | calls | ✓ (from metadata tables) |
| `whatif` evaluation and report | | provides node evaluator | ✓ orchestrates |
| Assertion diagnostics | | evaluates condition | ✓ reports and exits |

### 6.2 Metadata emitted into the executable

Static, read-only tables generated by the compiler:

* Per node: kind, type, opcode, operands, source line/column.
* Per binding: name, kind, type, anchor node ID, declaration index, source text.
* Provenance: direct dependencies per binding (and/or direct dependents), in declaration order.
* Source file name.

### 6.3 Runtime interface (contract)

Names are proposed; Phase 4 may refine signatures without changing behavior.

```
/* values: one tagged value per node */
typedef struct { causa_type type; union { int64_t i; double f; int b; } as; } causa_value;

/* a runtime error: code (R101..R103) and failing operator location */
typedef struct { int code; int line; int col; } causa_error;

/* provided by generated code */
extern const causa_program_info CAUSA_PROGRAM;          /* metadata tables */
/* compute env[node_id] from env[operands]; returns 0 on success,
   or nonzero and fills *err; never exits, never writes other slots */
int causa_eval_node(int node_id, causa_value *env, causa_error *err);

/* provided by the runtime */
void causa_show(int binding);
void causa_explain(int binding);
void causa_impact(int binding, int visible);
void causa_whatif(int input_binding, causa_value v,
                  int target_binding /* -1 for full form */, int visible);
void causa_assert(int ok, int assert_index);            /* exits with status 1 if !ok */
void causa_runtime_error(causa_error err);              /* base execution only; exits with status 2 */
```

Behavioral contract:

* **Value recording.** The base environment is an array of values indexed by node ID, written once per node in topological order during base execution. After a node is written it is never written again.
* **Base execution errors.** When `causa_eval_node` returns an error during base execution, generated code calls `causa_runtime_error`, which prints the diagnostic of language-specification §9.3 and exits with status 2.
* **`explain`** reads only metadata and base values; it walks provenance as specified in language-specification §8.4.
* **`impact`** reads only metadata (provenance restricted to visible bindings).
* **`whatif`** (language-specification §8.5):
  1. Allocates a separate counterfactual value array, initialized from the base array, and a per-binding outcome array (`value` / `failed` + `causa_error` / `unavailable` + cause binding). Writes the override into the input's slot.
  2. Visits the visible lets in the forward cone of the input in declaration order. In targeted form it may restrict this to lets that are the target or among its transitive dependencies. For each let: if a direct dependency is failed or unavailable, mark it unavailable with the earliest-declared failed cause; otherwise call `causa_eval_node` for the let's owned nodes in ascending ID order, stopping at the first error and marking the let failed.
  3. Nodes outside the cone keep their copied base values (reuse of valid cached results). Nodes owned by `assert` actions are never re-evaluated.
  4. Prints the report, then frees both arrays.
  * Isolation: the base array is passed only as read-only (`const`) data and is never written by `causa_whatif`; `causa_runtime_error` is never called during a `whatif`; nothing is written to stderr; the function always returns normally.
* All output is produced through the runtime's formatter so that every value prints per language-specification §8.2.

## 7. Dependency tracking model (summary)

* Dependencies are **static and structural**, computed at compile time from source references, and embedded as metadata. The executable does not discover dependencies at run time; it records **values**.
* Edge direction everywhere (node operands, provenance, documentation): *user* → *used*.
* `explain` = backward traversal from a binding; `impact` = forward (reverse-edge) traversal; `whatif` = forward traversal plus re-evaluation.
* These dependencies describe computation only, not real-world causation.

## 8. Testing strategy for later phases

Each stage is testable in isolation: lexer (token lists), parser (AST dumps), semantic analysis (error codes and locations), IR (textual IR dumps, invariants of §3.3 and §5), C generation (`--emit-c` compiles), and end-to-end (stdout/stderr/exit status). Expected outcomes are listed in [../tests/specification-cases.md](../tests/specification-cases.md).
