# CAUSA Demonstration

A ten-minute walkthrough of CAUSA's distinctive features on one small business scenario, [examples/pricing.cau](../examples/pricing.cau): a product with a price, a discount, tax, a fixed fee and a number of units. Every shell (`bash`) command and output below is executed and compared byte for byte by [tests/test_demo.py](../tests/test_demo.py) (stdout followed by stderr, and the exit status).

Setup is in the [README](../README.md#getting-started). Commands are for Git Bash or another POSIX shell, run from the repository root; PowerShell equivalents are at the end. On Windows, diagnostics print the file name as `examples\pricing.cau`; this page writes `examples/pricing.cau`.

## The program

```
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
```

followed by `show`, `assert`, `explain`, five `whatif` statements and three `impact` statements (see the file for comments).

## 1. Compile

```bash
py -3.11 -m causa check examples/pricing.cau
```

```text
examples/pricing.cau: semantic check passed: 5 inputs, 6 lets, 24 statements (not executed)
```

Exit status **0**. Types are inferred from literals and checked before any code is generated. Then generate C and build it with the runtime library:

```bash
mkdir -p build
py -3.11 -m causa emit-c examples/pricing.cau -o build/pricing.c
gcc -std=c99 -I causa/runtime build/pricing.c causa/runtime/causa_runtime.c -o build/pricing -lm
```

`emit-c` prints a note on stderr listing the runtime functions the program uses. `build/` is ignored by Git.

## 2. Run: show, explain, whatif, impact

```bash
./build/pricing
```

```text
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

Exit status **0**. This is exactly language-specification §12. What to point out:

| Output | Statement | Feature |
|---|---|---|
| `total = 88.375` | `show total` | typed values; `int` and `float` print differently (`100` vs `25.0`) |
| *(nothing)* | `assert total >= 0` | assertions are silent when they hold |
| `explain total` tree | `explain total` | **backward** explanation: each value with its source expression; `see above` marks a shared input |
| `whatif price = 160` | full report | **counterfactual**: only `price`'s dependency cone is recomputed, in a separate environment; `(unchanged)` marks values that did not move |
| `whatif discount = 0.5 show total` | targeted form | one result, before and after |
| `whatif tax = 1.0` | `whatif tax = 1` | the integer literal was promoted because `tax` is a `float` input |
| `whatif price = 160, discount = 0.5` | several overrides | applied together before anything is recomputed (94.0, not the sum of the two separate effects) |
| `error[R101]` / `unavailable` | `whatif units = 0` | a hypothetical failure is reported, not fatal; values depending on it are `unavailable` |
| `impact price` | `impact` | **forward** dependency propagation, known statically |
| last two lines | `show` again | the real values were never changed by any `whatif` |

## 3. Change assumptions at launch

Inputs keep their source values unless the program is started with `--set NAME=VALUE` (repeatable). Every statement, including each `whatif`'s "before" values, sees the launch values:

```bash
./build/pricing --set price=150 --set discount=0.3
```

```text
total = 122.125
explain total
  total = 122.125  [let: subtotal * (1 + tax) + fee]
    subtotal = 105.0  [let: price - savings]
      price = 150  [input]
      savings = 45.0  [let: price * discount]
        price = 150  [input, see above]
        discount = 0.3  [input]
    tax = 0.125  [input]
    fee = 4  [input]
  direct dependencies: tax, fee, subtotal
  transitive dependencies: price, discount, tax, fee, savings, subtotal
  inputs: price, discount, tax, fee
  intermediates: savings, subtotal
whatif price = 160
  price: 150 -> 160  (override)
  savings: 45.0 -> 48.0
  subtotal: 105.0 -> 112.0
  total: 122.125 -> 130.0
  expensive: true -> true  (unchanged)
  per_unit: 30.53125 -> 32.5
  bulk: false -> false  (unchanged)
whatif discount = 0.5 show total
  total: 122.125 -> 88.375
whatif tax = 1.0 show total
  total: 122.125 -> 214.0
whatif price = 160, discount = 0.5 show total
  total: 122.125 -> 94.0
whatif units = 0
  units: 4 -> 0  (override)
  per_unit: 30.53125 -> error[R101] at 14:22 (division by zero)
  bulk: false -> unavailable (depends on per_unit)
impact price
  direct dependents: savings, subtotal
  all dependents: savings, subtotal, total, expensive, per_unit, bulk
impact discount
  direct dependents: savings
  all dependents: savings, subtotal, total, expensive, per_unit, bulk
impact total
  direct dependents: expensive, per_unit
  all dependents: expensive, per_unit, bulk
total = 122.125
per_unit = 30.53125
```

Exit status **0**. No recompilation was needed. Launch values follow the source literal rules, so a bad value is rejected before anything runs, with nothing on stdout:

```bash
./build/pricing --set price=1.5
```

```text
examples/pricing.cau: argument error[A107]: cannot set int input 'price' to the float value '1.5'
```

Exit status **3**.

```bash
./build/pricing --set total=1
```

```text
examples/pricing.cau: argument error[A104]: 'total' is a let binding; only inputs can be set
```

Exit status **3**.

## 4. Failures in the real computation

A launch value that makes a computation fail is an ordinary runtime error, reported at the operator (line 14, column 22 is the `/` of `total / units`):

```bash
./build/pricing --set units=0
```

```text
examples/pricing.cau:14:22: runtime error[R101]: division by zero
```

Exit status **2**. Compare with `whatif units = 0` in section 2, where the same failure was only hypothetical. A negative price makes the assertion fail after the first `show`:

```bash
./build/pricing --set price=-100
```

```text
total = -80.375
examples/pricing.cau:18:1: assertion failed: total >= 0
  total = -80.375
```

Exit status **1**.

## 5. Errors caught at compile time

[examples/invalid-type-error.cau](../examples/invalid-type-error.cau) adds an `int` to a `bool`; no C is generated:

```bash
py -3.11 -m causa check examples/invalid-type-error.cau
```

```text
examples/invalid-type-error.cau:8:19: error[E401]: operator '+' requires numeric operands, found int and bool
```

Exit status **1**.

## 6. Header-only build

[examples/unit-price.cau](../examples/unit-price.cau) has only `input` and `let` statements, so it needs no runtime library: `--standalone` checks this, and the C compiler needs only the header. It prints nothing; its exit status is the result.

```bash
py -3.11 -m causa emit-c examples/unit-price.cau --standalone -o build/unit-price.c
gcc -std=c99 -I causa/runtime build/unit-price.c -o build/unit-price -lm
```

```bash
./build/unit-price --set units=0
```

```text
examples/unit-price.cau:8:22: runtime error[R101]: division by zero
```

Exit status **2**. Without arguments it exits with status 0. `--standalone` on `pricing.cau` fails with exit status 3, because that program needs `causa_runtime.c`.

## PowerShell

The same steps in Windows PowerShell (checked by hand with Windows PowerShell 5.1; not run by the tests):

```powershell
mkdir build -Force
py -3.11 -m causa emit-c examples/pricing.cau -o build/pricing.c
gcc -std=c99 -I causa/runtime build/pricing.c causa/runtime/causa_runtime.c -o build/pricing -lm
.\build\pricing.exe --set price=150 --set discount=0.3
```

`$LASTEXITCODE` holds the exit status.
