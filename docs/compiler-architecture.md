# CAUSA Compiler Architecture — Version 1

Status: **Phase 1 design contract, implemented in Phases 2–8.** Interfaces below define what each stage must provide; internal data structures were refined in later phases as long as these contracts hold, and each "Implemented" section records the actual interface. *(Phase 9: the original status line said that no stage was implemented yet.)* Language semantics are defined in [language-specification.md](language-specification.md); this document never redefines them.

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

AST node set (one per grammar construct; implemented in `causa/astnodes.py`): `Program(statements)`, `InputDecl(name, value)`, `LetDecl(name, value, source_text)`, `ShowStmt(name)`, `ExplainStmt(name)`, `WhatIfStmt(overrides, target)` with `overrides` a tuple of one or more `OverrideClause(name, value)` in statement order (`target` is absent for the full-report form; revision 3, D24), `ImpactStmt(name)`, `AssertStmt(condition, source_text)`, `Name(text)` for every binding-name argument, `Literal(type, value)`, `NameRef(name)`, `UnaryOp(op, operand)`, `BinaryOp(op, left, right)`. Every node has a span; operator nodes also record the operator token's span (for E401 and runtime error locations). Parentheses produce no node; a parenthesized expression's span is widened to include its parentheses. *(Phase 2: the revision 1 list lacked the `whatif` target and the `Name` node.)*

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
| `whatif(overrides, target, visible)` | one or more (input anchor, literal) pairs in statement order, optional target anchor | each value already has its input's type (promoted if needed); inputs are distinct; `target` is absent for the full form and depends on at least one overridden input; `visible` = number of bindings declared before the statement *(several overrides: revision 3)* |
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
| Steps | `Def(node)`, `Show(anchor, line)`, `Explain(anchor, line)`, `Impact(anchor, visible, line)`, `WhatIf(overrides, target, visible, line)` with `overrides` a tuple of `OverrideValue(input, value, value_type, source_value, promoted, value_line, value_column)` in statement order, `Assert(root, source_text, refs, line, column)` |
| `whatif` values | each `OverrideValue.value` is normalized to the input's type; `source_value` and `value_line`/`value_column` keep the literal as written (for reports and later diagnostics); `promoted` records int-to-float promotion. Promotion creates no node |
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

* Removing, merging, or folding `input` or `bind` nodes. Inputs are override points and must remain runtime values (this is what lets launch arguments set them at run time, §6.6). Unused lets are not removed: their evaluation can raise observable runtime errors.
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

Names are proposed; later phases may refine signatures without changing behavior. **The implemented interface (Phase 5) is in §6.4 and `causa/runtime/causa_runtime.h`; where they differ from the sketch below, §6.4 is authoritative.**

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
void causa_whatif(const causa_override *overrides, int override_count,
                  int target_binding /* -1 for full form */, int visible);  /* revision 3 */
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

### 6.4 Implemented C backend (Phase 5)

`causa/codegen.py` provides `generate_c(module, standalone=False) -> CProgram(source, runtime_calls)`. It validates its input and emits one C99 translation unit. `causa.frontend.compile_to_c(text, source_file)` runs parse → semantic analysis → Causal IR → optimizer → C, and `py -3.11 -m causa emit-c FILE [-o OUT.c] [--standalone]` prints or writes the result. No C compiler is invoked. To build the output: `cc -std=c99 -I causa/runtime OUT.c` (add `-lm` where required).

**Generated file layout**

| Section | Content |
|---|---|
| `#define CAUSA_NODE_SLOTS` | highest node ID + 1; the size of a value environment (retired IDs keep unused slots) |
| `enum { CAUSA_BINDING_<name> = <index> }` | one constant per binding, in declaration order. CAUSA names are `[A-Za-z_][A-Za-z0-9_]*`, so the prefix always yields a valid C identifier that is never a C keyword and never collides with runtime symbols |
| `causa_eval_node` | one `case` per live IR node, computing `env[id]` from its operands |
| metadata tables | `causa_nodes`, `causa_bindings` (with per-binding `deps`, `refs` and `dependents` arrays), `causa_asserts`, and `CAUSA_PROGRAM` (§6.2) |
| `main` (omitted when `CAUSA_NO_MAIN` is defined) | the IR steps in order: `if (causa_eval_node(id, env, &err)) causa_runtime_error(&err);` for every `def`, and one runtime call per action |

**Type mapping.** `int` → `int64_t` (`<stdint.h>`, literals `INT64_C(n)`, and `INT64_MIN` for −2^63, which has no literal form); `float` → `double`, with literals emitted as exact hexadecimal floating constants (`0x1.999999999999ap-4 /* 0.1 */`) so no decimal rounding happens in the C compiler; `bool` → `bool` (`<stdbool.h>`). Values live in `causa_value`, an untagged union `{ int64_t i; double f; bool b; }`. Every node's static type is in the metadata, so no tag is stored.

**Operations and safety.** Every IR node becomes its own C statement on operand values that were already computed, so C operator precedence never matters and `and`/`or` stay strict: both operand nodes were evaluated (and may already have failed) before the operator node.

| IR operation | C |
|---|---|
| int `add`/`sub`/`mul`, int `neg` | `causa_add_i64`, `causa_sub_i64`, `causa_mul_i64`, `causa_neg_i64`: overflow is detected *before* computing (R102), so no signed-overflow undefined behavior occurs |
| float `add`/`sub`/`mul` | `causa_add_f64` etc.: IEEE result, rejected if not finite (R103) |
| `div` (always float) | `causa_div_f64`: zero divisor, including `-0.0` → R101; non-finite result → R103 |
| float `neg`, `not`, comparisons, `and`, `or`, `itof` | plain C expressions; they cannot fail. `itof` is an explicit `(double)` cast |
| `bind` | `env[bind] = env[root]` |
| `input`, `const` | the literal, as above |

A failing helper returns its code, and `causa_check` records the operator's source line and column. Base execution then calls `causa_runtime_error`, which prints `FILE:LINE:COLUMN: runtime error[CODE]: DESCRIPTION` (language-specification §9.3) and exits with status 2. The header requires 64-bit IEEE doubles evaluated in double precision (`FLT_EVAL_METHOD == 0`, checked at compile time) and the default round-to-nearest mode.

**Refinements to the §6.3 sketch.** (1) `causa_value` is untagged (types come from the metadata). (2) Every runtime call takes the base environment explicitly as `const causa_value *env`. (3) `causa_runtime_error` takes `const causa_error *`. (4) Checked arithmetic, `causa_check` and `causa_runtime_error` are implemented now, as `static inline` functions in `causa_runtime.h`. (5) `causa_assert(env, assert_index, ok)` receives the condition value; its source text, location and referenced bindings are in `causa_asserts`. (6) *(Revision 3.)* `causa_whatif(env, overrides, count, target, visible)` receives the overrides as a C99 compound-literal array of `causa_override { input, value }` in statement order, for example `causa_whatif(env, (const causa_override[]){ { CAUSA_BINDING_price, { .i = INT64_C(160) } }, { CAUSA_BINDING_discount, { .f = 0x1.0000000000000p-1 /* 0.5 */ } } }, 2, CAUSA_BINDING_total, 11);`. A one-override `whatif` passes a one-element array. (7) *(Revision 4.)* `main` is `int main(int argc, char **argv)` and calls `causa_configure(argc, argv)` right after `causa_init()`, before the first statement; an input node's case is `env[id] = causa_input_value(CAUSA_BINDING_name, (causa_value){ .i = INT64_C(100) });`, i.e. the launch value if one was given, otherwise the source literal (§6.6).

**Standalone vs. runtime-library programs.** A program whose statements are only `input` and `let` needs nothing but `causa_runtime.h`. `show`, `explain`, `whatif`, `impact` and `assert` compile into calls to `causa_show`, `causa_explain`, `causa_whatif`, `causa_impact` and `causa_assert`, which are defined in `causa_runtime.c` (§6.5); such programs are built together with that file. The generator never drops these statements: `CProgram.runtime_calls` lists them, `emit-c` prints a note with the build inputs, and `--standalone` (or `generate_c(..., standalone=True)`) rejects such programs with an error (exit status 3). Every generated `main` first calls `causa_init()`, which on Windows switches stdout and stderr to binary mode so that lines end in a single `\n` as language-specification §9.1 requires.

### 6.5 Implemented runtime library (Phase 6)

`causa/runtime/causa_runtime.c` implements the functions declared in `causa_runtime.h`. It is plain C99 that uses only the standard library and reads only the metadata tables and the base environment (always `const`). Build a program with:

```
cc -std=c99 -I causa/runtime program.c causa/runtime/causa_runtime.c -lm
```

| Function | Behavior (language-specification) |
|---|---|
| `causa_format_value` | §8.2. `int` via `PRId64`; `bool` as `true`/`false`; `float` as Python's `repr` (below) |
| `causa_show` | §8.3: `NAME = VALUE` on stdout |
| `causa_explain` | §8.4: pre-order tree, children in first-appearance order (`refs`), each binding expanded once and later lines marked `see above`, then the four summary lists in declaration order. Values are the base environment's; the tree uses the source-level metadata, never the optimized node graph |
| `causa_impact` | §8.6: direct dependents (the derived reverse index) and all dependents (one forward sweep over the canonical dependency edges), restricted to the `visible` bindings, in declaration order. No values are read |
| `causa_whatif` | §8.5: copies the base environment into a freshly allocated counterfactual environment, writes every (already promoted) override before re-evaluating anything, and visits the visible lets in the union of the overridden inputs' dependency cones in declaration order. Each is *unavailable* if a direct dependency failed or is unavailable (the cause is the earliest-declared failed binding), otherwise its owned nodes are re-evaluated with `causa_eval_node`, and the first error makes it *failed*. Nodes outside the cone keep their base values; assert-owned nodes are never re-evaluated. It prints the full or targeted report (one `(override)` line per override in statement order, `(override)`, `(unchanged)` by bit identity, `error[CODE] at L:C (DESCRIPTION)`, `unavailable (depends on NAME)`), frees everything, never writes stderr, and always returns |
| `causa_assert` | §8.7, §9.3: on `false`, flushes stdout, prints `FILE:LINE:COLUMN: assertion failed: SOURCE` and one `  NAME = VALUE` line per referenced binding to stderr, and exits with status 1 |

**Float formatting.** For a finite non-zero double, precisions p = 1…17 are tried in turn. `printf("%.*e")` yields the correctly rounded p-digit decimal, which is the nearest p-digit value. If it does not convert back to the same double with `strtod`, its two neighbours (±1 in the last digit) are tried, because the rounding interval of a power of two is asymmetric. The first candidate that converts back is the shortest round-trip representation, and among those of that length it is the closest to the exact value, which is the digit string Python's `repr` produces. The digits are then laid out per §8.2: positional notation for decimal exponents −4…15, otherwise `d[.ddd]e±XX`, and `0.0`/`-0.0` for zeros. Candidate strings are built without a decimal point, so the locale's radix character cannot affect the result. The method relies on the C library's `printf("%e")` and `strtod` being correctly rounded. `tests/test_runtime.py` checks this on every run against Python's `repr` for 35,000 values: all powers of two, values on both sides of every decimal exponent, subnormals, the extremes, and random bit patterns. During development a 364,457-value comparison found no difference. Removing the neighbour step makes the test fail, so that step is necessary.

**Defensive checks.** On first use the runtime validates the metadata. It checks the source file name; non-negative counts with non-`NULL` table pointers; node IDs strictly ascending and within `node_slots`; node owners naming an existing binding or assert; binding names non-`NULL`, kinds limited to input/let, type tags valid, anchors within `node_slots`, lets having source text and inputs having no dependencies; every dependency and reference pointing to an *earlier* binding (which makes the graph acyclic); dependents pointing to later bindings; and assert references in range. `causa_whatif` also rejects an invalid request (no overrides, a `NULL` override table, an overridden binding that is not an input, not yet visible or repeated, a target below `CAUSA_NO_TARGET`, not visible, or outside the input's dependency cone) *before* printing anything. A violation or an allocation failure prints `FILE: internal error: …` to stderr (with `<unknown>` if the file name itself is missing) and exits with status 2. Such a message is never mistaken for a CAUSA runtime error (`runtime error[Rxxx]`) or an assertion failure (exit status 1).

These checks catch inconsistent values in the tables, which is the failure mode of a buggy generator or hand-edited output. They cannot prove that a non-`NULL` pointer refers to readable memory, or that a string is NUL-terminated, so arbitrary memory corruption is outside the runtime's contract. A `refs` array is checked for count and range but not for being the same set as `deps`.

`explain` builds its tree with an explicit heap-allocated stack bounded by 1 + the total number of references, not with recursion, so dependency depth is limited only by memory. (A recursive version overflowed the default Windows stack at about 13,000 levels.)

**Windows streams.** `causa_init()` puts stdout and stderr in binary mode so that every line ends in exactly `\n` (language-specification §9.1). This is applied best-effort: if `_setmode` fails, output continues in text mode. ASCII output to a console is unaffected. Because the mode is process-wide, code that embeds a CAUSA program (by defining `CAUSA_NO_MAIN` and calling `causa_init`) changes the host's stdio mode. On other platforms the function does nothing; the Windows-only headers and calls are confined to `#ifdef _WIN32`.

### 6.6 Launch arguments (Phase 8)

`causa_runtime.h` implements language-specification §9.5 as `static inline` functions, so header-only programs (inputs and lets only) accept launch arguments too:

| Function | Role |
|---|---|
| `causa_configure(argc, argv)` | With no arguments, does nothing. Otherwise validates every `--set NAME=VALUE` against the `CAUSA_PROGRAM` binding table in argument order and stops at the first invalid one with `FILE: argument error[A1xx]: …` on stderr and exit status 3. Only after all arguments are valid does it publish the values, so the launch configuration is all-or-nothing |
| `causa_parse_literal(text, &type, &value)` | The LS §3.5 literal rules in C: `true`/`false`, or an optional `-` and an integer (magnitude checked against 2^63 − 1 digit by digit) or a float. Floats are converted with `strtod` from a digits-and-exponent string without a decimal point, so the locale cannot affect them, and infinity is rejected |
| `causa_input_value(binding, default)` | Called by each generated input case: the launch value if one was set, else the source literal. Programs built with `CAUSA_NO_MAIN` never call `causa_configure` and always get the source literals |

The launch values live in function-local static storage, are written once before execution, and are only read afterwards. `causa_whatif` never re-evaluates input nodes: it copies the base environment, which already holds the launch values, so `whatif` isolation is unchanged. `tests/test_launch.py` checks the C literal rules against the Python lexer on the same strings.

**Measured limits (Phase 6 audit).** On a chain of 20,000 dependent bindings: the Python front end took about 55 s, because semantic analysis stores each binding's full transitive dependency set (quadratic on a chain); GCC took about 250 s to compile the generated 20,000-case `switch`; and `explain` output is quadratic in depth, because language-specification §8.4 indents every level. `whatif` scans the node table once per binding in the cone (O(bindings × nodes)). None of these affect correctness. Programs of a few thousand bindings compile and run in seconds.

## 7. Dependency tracking model (summary)

* Dependencies are **static and structural**, computed at compile time from source references, and embedded as metadata. The executable does not discover dependencies at run time; it records **values**.
* Edge direction everywhere (node operands, provenance, documentation): *user* → *used*.
* `explain` = backward traversal from a binding; `impact` = forward (reverse-edge) traversal; `whatif` = forward traversal plus re-evaluation.
* These dependencies describe computation only, not real-world causation.

## 8. Testing strategy for later phases

Each stage is testable in isolation: lexer (token lists), parser (AST dumps), semantic analysis (error codes and locations), IR (textual IR dumps, invariants of §3.3 and §5), C generation (`--emit-c` compiles), and end-to-end (stdout/stderr/exit status). Expected outcomes are listed in [../tests/specification-cases.md](../tests/specification-cases.md).
