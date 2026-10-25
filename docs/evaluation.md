# CAUSA Evaluation

Measurements of the compiler and the generated programs, taken with [benchmarks/benchmark.py](../benchmarks/benchmark.py) (standard library only). They describe one machine on one day. They show where time goes and how the pieces scale; they are not a performance claim.

## How to reproduce

From the repository root, with Python 3.11+ and a C compiler (`--cc`, else `$CAUSA_CC`, else `gcc`):

```bash
py -3.11 benchmarks/benchmark.py --repeat 5
```

The script prints the machine description and a Markdown table like the one below. It exits with status 1 if the optimized and unoptimized builds of any workload print different output.

## Method

| Item | How |
|---|---|
| Front end | `compile_to_ir`: lexing, parsing, semantic analysis, Causal IR construction and validation, in-process |
| Optimizer, C gen | `optimize(module)`, `generate_c(module)`, in-process |
| cc -O0, cc -O2 | wall time of one `gcc -std=c99 -Wall -Wextra -Wpedantic -Werror` run on the generated C, linking a runtime object compiled once beforehand |
| run | wall time of the executable from process start to exit, output captured, after one untimed run (on Windows the first start of a new `.exe` was 0.5–1 s slower, apparently a security scan) |
| same output | stdout, stderr and exit status identical for four builds: optimized and unoptimized Causal IR, each at `-O0` and `-O2` |
| whatif node evaluations | **measured**: a separate build of the optimized program in which `causa_eval_node` is wrapped by a counter (the technique of the IR09/IR11 harness in `tests/test_runtime.py`). The generated `main` calls the unwrapped function, so base execution is not counted; the runtime library calls the wrapper, so the count is every IR node re-evaluated by all `whatif` statements of the program together |
| whatif cone | **derived**: the lets each `whatif` re-evaluates, computed from the IR provenance using the runtime's rule (compiler-architecture §6.5: every visible let in the union of the overridden inputs' dependency cones) |

Every timing is repeated `--repeat` times (5 below) and reported as median [min–max] in milliseconds. Five runs give a rough spread, not statistical significance.

Workloads:

| Workload | Program |
|---|---|
| `pricing.cau` | [examples/pricing.cau](../examples/pricing.cau), the demonstration program |
| `chain-N` | `input x0 = 1`, then N lets `let xi = x(i-1) + 1`, `show xN`, a full-report `whatif x0 = 2` and a targeted `whatif x0 = 3 show xN`: every let depends on the input |
| `fan-N` | inputs `a` (int) and `b` (float), N lets `let yi = a * (2 + 3) + i` or `b * (2 + 3) + i`, alternating; `whatif a = 7` and `whatif a = 7, b = 0.5 show y0`. Half the lets depend on each input, and every `(2 + 3)` can be folded |

## Results

Machine: Windows 11 (build 26300), AMD Family 25 Model 68 (8 logical CPUs). Python 3.11.9; GCC 16.1.0 (MSYS2 UCRT64). Measured 2026-10-25, repeat = 5. Workload sizes: 6, 100, 1,000 and 1,000 lets.

| Workload | Source lines | IR nodes | After optimizer | Rewrites | whatif node evaluations | Front end | Optimizer | C gen | cc -O0 | cc -O2 | Run (optimized IR, -O2) | Run (unoptimized IR, -O2) | Same output |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pricing.cau | 37 | 30 | 28 | 4 | 80 | 1.2 [1.0–1.6] | 0.5 [0.5–0.8] | 0.4 [0.3–0.5] | 366 [325–413] | 451 [439–533] | 23.9 [22.0–34.9] | 24.3 [22.0–31.0] | yes |
| chain-100 | 104 | 301 | 301 | 0 | 600 | 7.4 [6.8–10.8] | 4.3 [4.0–4.6] | 2.7 [2.3–3.2] | 438 [410–443] | 846 [816–958] | 24.8 [22.9–31.0] | 25.4 [22.3–35.0] | yes |
| chain-1000 | 1004 | 3001 | 3001 | 0 | 6000 | 102 [96–116] | 51.6 [50.0–55.6] | 32.7 [29.4–34.8] | 1651 [1567–2028] | 5769 [5531–7621] | 27.8 [26.4–30.1] | 25.8 [24.6–26.9] | yes |
| fan-1000 | 1005 | 8002 | 5001 | 5001 | 7498 | 177 [150–196] | 129 [118–145] | 56.0 [50.9–72.3] | 2667 [2350–2774] | 10561 [10356–10791] | 28.8 [27.6–29.8] | 29.8 [29.3–31.3] | yes |

Times are in milliseconds. An earlier run the same day, before the counter was added, gave the same node counts and outputs with timings within roughly ±30% of these (`gcc -O2` on `fan-1000` up to 15.8 s), which shows how much wall-clock times vary between runs on this machine.

`whatif` re-evaluation per statement (derived, see Method):

| Workload | `whatif` | Lets re-evaluated |
|---|---|---|
| pricing.cau | `price = 160` | 6 of 6 |
| pricing.cau | `discount = 0.5 show total` | 6 of 6 |
| pricing.cau | `tax = 1 show total` | 4 of 6 |
| pricing.cau | `price = 160, discount = 0.5 show total` | 6 of 6 |
| pricing.cau | `units = 0` | 2 of 6 |
| chain-100, chain-1000 | both | all (100, 1000) |
| fan-1000 | `a = 7` | 500 of 1000 |
| fan-1000 | `a = 7, b = 0.5 show y0` | 1000 of 1000 |

## Observations

Measured:

* **The C compiler dominates build time.** For every workload, `gcc` took far longer than the whole CAUSA compiler: at 1,000 lets, the CAUSA stages together took about 0.2–0.4 s (medians), `gcc -O0` 1.7–2.7 s and `gcc -O2` 5.8–10.6 s. The generated C has one `switch` case per IR node, which `-O2` optimizes slowly.
* **Executables finish in about 24–30 ms** (medians) for every workload, which is close to the cost of starting a process on this machine. At this size the run times cannot show any difference between optimized and unoptimized IR, or between workloads.
* **The optimizer** folded the 1,000 `(2 + 3)` subexpressions and 1,000 integer-to-float conversions of constants in `fan-1000`, merged 3 duplicate subexpressions and removed 2,998 dead constants (8,002 → 5,001 nodes, 37% fewer); this cut neither run time nor `gcc` time measurably here. In `pricing.cau` it folded two integer-to-float conversions of constants (the `1` in `1 + tax` and the `0` in `total >= 0`) and removed the two constants they replaced (30 → 28 nodes; `py -3.11 -m causa optimize examples/pricing.cau` prints the log). The chains have nothing to fold.
* **Optimization never changed behavior:** all four builds of each workload printed identical stdout and stderr and exited with the same status.
* **`whatif` re-evaluates only the dependency cone.** The counted node evaluations agree with the derived cones: each chain let owns 3 nodes, and the two `whatif`s on `x0` re-evaluate all lets, giving 2 × 3 × N (600 and 6,000). In `fan-1000`, `whatif a = 7` covers half the lets and the two-override `whatif` all of them, 7,498 nodes in total, fewer than 2 × 5,001. `whatif units = 0` in `pricing.cau` touches 2 of 6 lets (`per_unit`, `bulk`).

Expected from the design (not measured here):

* Front-end time grows faster than linearly on long chains, because semantic analysis stores each binding's full transitive dependency set; compiler-architecture §6.5 ("Measured limits") reports about 55 s for a 20,000-let chain.
* Each `whatif` costs time proportional to the size of its cone times the number of IR nodes (the runtime scans the node table once per binding in the cone), so a whatif on a narrow cone stays cheap in a large program.
* `explain` output grows quadratically with chain depth, because every level is indented.

## Limitations

* One machine, one operating system, one C compiler, one session; no other compiler or C library was measured.
* Wall-clock timings include operating-system noise, and the run times are dominated by process start-up. A meaningful runtime comparison would need much larger programs or many statements per run.
* The node-evaluation counter covers all `whatif` statements of a program together; per-statement counts are derived from the IR, not measured. The counting build is separate from the timed builds and the production runtime has no counters.
* The workloads are synthetic apart from `pricing.cau`; real programs may have different shapes.
