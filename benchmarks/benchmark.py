"""Reproducible CAUSA evaluation (docs/evaluation.md).

    py -3.11 benchmarks/benchmark.py [--repeat N] [--cc gcc]

Measures, for each workload: front end (lex, parse, semantic analysis, Causal
IR), optimizer and C generation time in-process; C compile time at -O0 and -O2;
executable wall time (process start to exit, after one untimed run). Each timing is repeated and
reported as median [min-max]. Also reports IR node counts with and without the
optimizer, and checks that both builds print identical bytes. Counts the IR
nodes all whatif statements re-evaluate, with a build whose causa_eval_node is
wrapped by a counter (the technique of tests/test_runtime.py), and lists the
lets each whatif re-evaluates according to the IR provenance. Standard library only.
"""

from __future__ import annotations

import argparse
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from causa.codegen import RUNTIME_DIR, RUNTIME_SOURCE, generate_c  # noqa: E402
from causa.frontend import compile_to_ir, read_source  # noqa: E402
from causa.ir import WhatIf  # noqa: E402
from causa.optimizer import optimize  # noqa: E402

CFLAGS = ["-std=c99", "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-I", str(RUNTIME_DIR)]


# Generated main keeps calling the original function (renamed by the macro); the
# runtime library, compiled separately, calls the counting wrapper during whatif.
COUNTER = r"""
#define causa_eval_node causa_eval_node_generated
#include "prog.c"
#undef causa_eval_node
static long causa_bench_calls;
static void causa_bench_report(void) { fprintf(stderr, "whatif node evaluations: %ld\n", causa_bench_calls); }
int causa_eval_node(int node_id, causa_value *env, causa_error *err);
int causa_eval_node(int node_id, causa_value *env, causa_error *err)
{
    if (causa_bench_calls++ == 0) atexit(causa_bench_report);
    return causa_eval_node_generated(node_id, env, err);
}
"""


def chain(n: int) -> str:
    """A dependency chain of n lets: every whatif on x0 re-evaluates all of them."""
    lets = [f"let x{i} = x{i - 1} + 1" for i in range(1, n + 1)]
    return "\n".join(["input x0 = 1", *lets, f"show x{n}", "whatif x0 = 2", f"whatif x0 = 3 show x{n}"]) + "\n"


def fan(n: int) -> str:
    """n lets split between two inputs, with constant subexpressions for the optimizer:
    a whatif on one input re-evaluates only its half."""
    lets = [f"let y{i} = {'a' if i % 2 else 'b'} * (2 + 3) + {i}" for i in range(n)]
    return "\n".join(["input a = 1", "input b = 2.5", *lets, f"show y{n - 1}", "whatif a = 7",
                      "whatif a = 7, b = 0.5 show y0"]) + "\n"


WORKLOADS = {
    "pricing.cau": read_source(ROOT / "examples" / "pricing.cau"),
    "chain-100": chain(100),
    "chain-1000": chain(1000),
    "fan-1000": fan(1000),
}


def timed(fn, repeat: int):
    times, result = [], None
    for _ in range(repeat):
        start = time.perf_counter()
        result = fn()
        times.append(time.perf_counter() - start)
    return result, times


def fmt(times: list[float]) -> str:
    ms = [t * 1000 for t in times]
    return f"{statistics.median(ms):.1f} [{min(ms):.1f}-{max(ms):.1f}]"


def cones(module) -> list[str]:
    prov = module.provenance
    names = {b.anchor: b.name for b in prov.bindings}
    lets = sum(b.kind.value == "let" for b in prov.bindings)
    out = []
    for step in module.steps:
        if isinstance(step, WhatIf):
            cone = set()
            for o in step.overrides:
                cone |= set(prov.all_dependents(names[o.input]))
            over = ", ".join(names[o.input] for o in step.overrides)
            out.append(f"line {step.line} ({over}): {len(cone)} of {lets} lets")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--cc", default=os.environ.get("CAUSA_CC", "gcc"))
    args = ap.parse_args()
    r = args.repeat
    cc_version = subprocess.run([args.cc, "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    print(f"Machine: {platform.platform()}, {platform.processor() or platform.machine()}, {os.cpu_count()} logical CPUs")
    print(f"Python {platform.python_version()}; {cc_version}; repeat={r}; times in ms, median [min-max]\n")

    rows, notes = [], []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        runtime_obj = work / "rt.o"
        subprocess.run([args.cc, *CFLAGS, "-O2", "-c", str(RUNTIME_SOURCE), "-o", str(runtime_obj)], check=True)
        for name, text in WORKLOADS.items():
            lines = text.count("\n")
            module, t_front = timed(lambda: compile_to_ir(text, "F"), r)
            optimized, t_opt = timed(lambda: optimize(module), r)
            program, t_gen = timed(lambda: generate_c(optimized.module), r)
            unopt_c = generate_c(module).source
            builds = {}
            for label, source in (("opt", program.source), ("unopt", unopt_c)):
                c_file = work / f"{name}-{label}.c"
                c_file.write_text(source, encoding="utf-8")
                for level in ("-O0", "-O2"):
                    exe = work / f"{name}-{label}{level}.exe"
                    cmd = [args.cc, *CFLAGS, level, str(c_file), str(runtime_obj), "-o", str(exe), "-lm"]
                    _, t_cc = timed(lambda: subprocess.run(cmd, check=True, capture_output=True), r if label == "opt" else 1)
                    builds[label, level] = (exe, t_cc)
            outputs = {}
            for key, (exe, _) in builds.items():
                # untimed first run: on Windows the first start of a new .exe is slowed by a security scan
                subprocess.run([str(exe)], capture_output=True)
                res, t_run = timed(lambda: subprocess.run([str(exe)], capture_output=True), r)
                outputs[key] = (res.stdout, res.stderr, res.returncode, t_run)
            same = len({o[:3] for o in outputs.values()}) == 1
            (work / "prog.c").write_text(program.source, encoding="utf-8")
            (work / "counter.c").write_text(COUNTER, encoding="utf-8")
            counter_exe = work / f"{name}-counter.exe"
            subprocess.run([args.cc, *CFLAGS, str(work / "counter.c"), str(runtime_obj), "-o", str(counter_exe), "-lm"],
                           check=True)
            counted = subprocess.run([str(counter_exe)], capture_output=True, text=True).stderr
            whatif_evals = int(counted.rsplit(":", 1)[1]) if "whatif node evaluations" in counted else 0
            rows.append((name, lines, len(module.nodes), len(optimized.module.nodes), len(optimized.log), whatif_evals,
                         fmt(t_front), fmt(t_opt), fmt(t_gen), fmt(builds["opt", "-O0"][1]),
                         fmt(builds["opt", "-O2"][1]), fmt(outputs["opt", "-O2"][3]),
                         fmt(outputs["unopt", "-O2"][3]), "yes" if same else "NO"))
            notes += [f"{name} whatif cone, {c}" for c in cones(optimized.module)]

    head = ("workload", "source lines", "IR nodes", "after opt", "rewrites", "whatif node evals", "front end", "optimizer",
            "C gen", "cc -O0", "cc -O2", "run (opt IR, -O2)", "run (unopt IR, -O2)", "same output")
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for row in rows:
        print("| " + " | ".join(map(str, row)) + " |")
    print()
    for n in notes:
        print(f"* {n}")
    return 0 if all(row[-1] == "yes" for row in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
