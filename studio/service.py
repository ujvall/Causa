"""CAUSA Studio service layer: everything the user interface needs, with no Tk code.

The compiler runs in-process through its documented API (causa.frontend,
causa.optimizer, causa.codegen), so Studio and `python -m causa` can never
disagree about the language. The C compiler and the generated program run as
child processes built from argument lists (never a shell string), on worker
threads; a Job can cancel the process tree it is running.

explain, impact and whatif requests from the panels are answered by the real
runtime: query_source() keeps the program's input and let declarations on their
original lines, blanks every other statement, and appends one generated
statement whose parts were validated against the program and the CAUSA parser.
"""

from __future__ import annotations

import itertools
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from causa.astnodes import InputDecl, LetDecl
from causa.codegen import RUNTIME_DIR, RUNTIME_SOURCE, generate_c
from causa.diagnostics import CausaError
from causa.frontend import compile_to_ir
from causa.ir import IRModule
from causa.lexer import decode_source
from causa.optimizer import optimize
from causa.parser import parse

EXIT_MEANING = {0: "success", 1: "assertion failed", 2: "runtime error", 3: "invalid launch arguments"}
EXE_SUFFIX = ".exe" if os.name == "nt" else ""


# ---- models ------------------------------------------------------------------

@dataclass(frozen=True)
class Diagnostic:
    kind: str  # "compile", "runtime", "assertion", "argument", "build", "internal"
    message: str  # the full text as printed by the compiler or the program
    line: int | None = None
    column: int | None = None
    code: str | None = None


@dataclass(frozen=True)
class Binding:
    name: str
    kind: str  # "input" | "let"
    type: str  # "int" | "float" | "bool"
    line: int
    column: int
    source_text: str | None  # the let's expression as written; None for inputs
    deps: tuple[str, ...]  # direct dependencies, declaration order
    dependents: tuple[str, ...]  # direct dependents, declaration order


@dataclass(frozen=True)
class Graph:
    """The program's binding-level dependency graph, straight from the IR provenance.
    An edge (a, b) means b depends on a: values flow from a to b."""
    bindings: tuple[Binding, ...]
    upstream: dict[str, tuple[str, ...]]  # transitive dependencies
    downstream: dict[str, tuple[str, ...]]  # transitive dependents

    @staticmethod
    def from_module(module: IRModule) -> Graph:
        prov = module.provenance
        bindings = tuple(Binding(b.name, b.kind.value, b.type.value, b.line, b.column, b.source_text,
                                 b.direct_deps, prov.direct_dependents[b.name]) for b in prov.bindings)
        return Graph(bindings, {b.name: prov.transitive_deps(b.name) for b in bindings},
                     {b.name: prov.all_dependents(b.name) for b in bindings})

    @property
    def edges(self) -> list[tuple[str, str]]:
        return [(dep, b.name) for b in self.bindings for dep in b.deps]

    def binding(self, name: str) -> Binding | None:
        return next((b for b in self.bindings if b.name == name), None)

    @property
    def inputs(self) -> list[Binding]:
        return [b for b in self.bindings if b.kind == "input"]


@dataclass
class Outcome:
    """Result of one request. stage is where it ended: "compile", "build", "run" or "cancelled"."""
    stage: str
    ok: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)  # stage -> seconds
    graph: Graph | None = None


# ---- toolchain and processes ---------------------------------------------------

def find_c_compiler() -> str | None:
    """The same search as the test suite: $CAUSA_CC, else gcc, clang or cc on PATH."""
    for name in (os.environ.get("CAUSA_CC"), "gcc", "clang", "cc"):
        if name and (path := shutil.which(name)):
            return path
    return None


def _popen_options() -> dict:
    if os.name == "nt":  # no console window flashes up for gcc or the program
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}  # own process group, so the whole tree can be killed


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill a child process and everything it started (gcc runs cc1, as, ld)."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
        subprocess.run([str(taskkill), "/F", "/T", "/PID", str(proc.pid)], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.poll() is None:
        proc.kill()


class Cancelled(Exception):
    pass


class Job:
    """One cancellable request. run() starts a child process; cancel() kills it,
    and any later run() of a cancelled job raises Cancelled without starting one."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self.cancelled = False

    def cancel(self) -> None:
        with self._lock:
            self.cancelled = True
            proc = self._proc
        if proc is not None:
            kill_tree(proc)

    def run(self, argv: list[str]) -> tuple[int, bytes, bytes, float]:
        with self._lock:
            if self.cancelled:
                raise Cancelled
            start = time.perf_counter()
            try:
                self._proc = proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                                     stderr=subprocess.PIPE, **_popen_options())
            except OSError as exc:  # name the program: Windows does not
                raise OSError(exc.errno, exc.strerror, argv[0]) from None
        try:
            out, err = proc.communicate()
        finally:
            with self._lock:
                self._proc = None
        if self.cancelled:
            raise Cancelled
        return proc.returncode, out, err, time.perf_counter() - start


# ---- source helpers -----------------------------------------------------------

def read_file(path: str | Path) -> str:
    """Read a .cau file for editing; line ends are normalized to \\n (saving writes \\n)."""
    return decode_source(Path(path).read_bytes()).replace("\r\n", "\n")


def write_file(path: str | Path, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8", newline="\n")


def query_source(text: str, statements: list[str]) -> str:
    """The program's declarations on their original lines (so diagnostics keep their
    locations), every other statement blanked, then the given statements."""
    lines = text.split("\n")
    for stmt in parse(text).statements:
        if not isinstance(stmt, (InputDecl, LetDecl)):
            if stmt.span.line != stmt.span.end_line:  # statements are one line each (LS §4)
                raise ValueError(f"statement at line {stmt.span.line} spans several lines")
            lines[stmt.span.line - 1] = ""
    body = "\n".join(lines)
    if not body.endswith("\n"):
        body += "\n"
    return body + "".join(s + "\n" for s in statements)


def check_literal(value: str) -> str:
    """A whatif value must be exactly one CAUSA literal (LS §3.5); the parser decides."""
    value = value.strip()
    if not value:
        raise ValueError("enter a value")
    if any(c in value for c in "\r\n\x0b\x0c\x85\u2028\u2029"):
        raise ValueError("a value must be on one line")
    try:
        (stmt,) = parse(f"input v = {value}\n").statements
    except CausaError as err:
        raise ValueError(f"'{value}' is not a CAUSA literal (error {err.code}: {err.message})") from None
    return value


def binding_statement(graph: Graph, verb: str, name: str) -> str:
    if verb not in ("explain", "impact"):
        raise ValueError(verb)
    if graph.binding(name) is None:
        raise ValueError(f"'{name}' is not a binding of this program")
    return f"{verb} {name}"


def whatif_statement(graph: Graph, overrides: list[tuple[str, str]]) -> str:
    if not overrides:
        raise ValueError("choose at least one input")
    parts = []
    for name, value in overrides:
        b = graph.binding(name)
        if b is None or b.kind != "input":
            raise ValueError(f"'{name}' is not an input of this program")
        parts.append(f"{name} = {check_literal(value)}")
    return "whatif " + ", ".join(parts)  # repeated inputs are left to the compiler (E305)


_WHATIF_ROW = re.compile(r"^  (\w+): (.*?) -> (.*?)(?:  \((override|unchanged)\))?$")


def parse_whatif_report(stdout: str) -> list[tuple[str, str, str, str]]:
    """Rows (binding, original, counterfactual, note) of a full whatif report (LS §8.5).
    Every row but the overrides was re-evaluated; note says how it came out:
    override, changed, same value, failed or unavailable."""
    rows = []
    for line in stdout.splitlines()[1:]:
        m = _WHATIF_ROW.match(line)
        if m:
            name, before, after, note = m.groups()
            if after.startswith(("error[", "unavailable")):
                note = "failed" if after.startswith("error[") else "unavailable"
            rows.append((name, before, after, {"unchanged": "same value", None: "changed"}.get(note, note)))
    return rows


def parse_impact_report(stdout: str) -> tuple[list[str], list[str]]:
    direct, every = [], []
    for line in stdout.splitlines():
        for prefix, target in (("  direct dependents:", direct), ("  all dependents:", every)):
            if line.startswith(prefix):
                rest = line[len(prefix):].strip()
                target.extend([] if rest in ("", "(none)") else [n.strip() for n in rest.split(",")])
    return direct, every


def runtime_diagnostics(stderr: str, filename: str) -> list[Diagnostic]:
    """Locate the program's runtime, assertion and argument diagnostics (LS §9.3, §9.5)."""
    located = re.compile(rf"^{re.escape(filename)}:(\d+):(\d+): (?:runtime error\[(R\d+)\]|assertion failed)")
    argument = re.compile(rf"^{re.escape(filename)}: argument error\[(A\d+)\]")
    out = []
    for line in stderr.splitlines():
        if m := located.match(line):
            kind = "runtime" if m.group(3) else "assertion"
            out.append(Diagnostic(kind, line, int(m.group(1)), int(m.group(2)), m.group(3)))
        elif m := argument.match(line):
            out.append(Diagnostic("argument", line, code=m.group(1)))
    return out


# ---- session ------------------------------------------------------------------

class Session:
    """A private temporary build directory, created on first use, and the runtime
    library compiled once. close() removes that directory and nothing else."""

    def __init__(self, cc: str | None = None) -> None:
        self.cc = cc if cc is not None else find_c_compiler()
        self._dir: Path | None = None
        self._lock = threading.Lock()
        self._runtime_obj: Path | None = None
        self._ids = itertools.count(1)

    @property
    def dir(self) -> Path:
        with self._lock:
            if self._dir is None:
                self._dir = Path(tempfile.mkdtemp(prefix="causa-studio-"))
            return self._dir

    def close(self) -> None:
        with self._lock:
            if self._dir is not None:
                shutil.rmtree(self._dir, ignore_errors=True)

    def compiler_version(self) -> str | None:
        if not self.cc:
            return None
        try:
            r = subprocess.run([self.cc, "--version"], capture_output=True, text=True, timeout=30, **_popen_options())
        except (OSError, subprocess.TimeoutExpired):
            return None
        return (r.stdout.splitlines() or [self.cc])[0]

    def analyze(self, text: str, filename: str) -> Outcome:
        """Front end only: diagnostics and the dependency graph, no C compiler needed."""
        start = time.perf_counter()
        try:
            graph = Graph.from_module(compile_to_ir(text, filename))
        except CausaError as err:
            return Outcome("compile", False, diagnostics=[_compile_diagnostic(err, filename)],
                           timings={"compile": time.perf_counter() - start})
        return Outcome("compile", True, graph=graph, timings={"compile": time.perf_counter() - start})

    def run(self, job: Job, text: str, filename: str, args: tuple[str, ...] = ()) -> Outcome:
        """Compile, build and run the program as written."""
        return self._execute(job, text, filename, args)

    def query(self, job: Job, text: str, filename: str, statement: str) -> Outcome:
        """Run one explain/impact/whatif statement against the program's declarations."""
        try:
            source = query_source(text, [statement])
        except CausaError as err:
            return Outcome("compile", False, diagnostics=[_compile_diagnostic(err, filename)])
        return self._execute(job, source, filename, ())

    def _execute(self, job: Job, text: str, filename: str, args: tuple[str, ...]) -> Outcome:
        timings: dict[str, float] = {}
        start = time.perf_counter()
        try:
            module = compile_to_ir(text, filename)
            c_source = generate_c(optimize(module).module).source
        except CausaError as err:
            return Outcome("compile", False, diagnostics=[_compile_diagnostic(err, filename)],
                           timings={"compile": time.perf_counter() - start})
        except Exception as exc:  # IR validation or code generation: a compiler defect, never user error
            return Outcome("compile", False, diagnostics=[Diagnostic("internal", f"internal compiler error: {exc}")])
        timings["compile"] = time.perf_counter() - start
        result = Outcome("build", False, graph=Graph.from_module(module), timings=timings)
        if not self.cc:
            result.diagnostics.append(Diagnostic("build", "No C compiler found. Install GCC (for example MSYS2 "
                                                 "UCRT64) and put it on PATH, or set CAUSA_CC."))
            return result
        n = next(self._ids)
        c_file, exe = self.dir / f"program{n}.c", self.dir / f"program{n}{EXE_SUFFIX}"
        try:
            runtime_obj = self._runtime(job)
            c_file.write_text(c_source, encoding="utf-8")
            code, _, err, seconds = job.run([self.cc, "-std=c99", "-I", str(RUNTIME_DIR), str(c_file),
                                             str(runtime_obj), "-o", str(exe), "-lm"])
            timings["build"] = seconds
            if code != 0:
                result.stderr = err.decode("utf-8", "replace")
                result.diagnostics.append(Diagnostic("build", "the C compiler failed on the generated program"))
                return result
            code, out, err, seconds = job.run([str(exe), *args])
            timings["run"] = seconds
            result.stage, result.ok, result.exit_code = "run", code == 0, code
            result.stdout, result.stderr = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
            result.diagnostics.extend(runtime_diagnostics(result.stderr, filename))
            return result
        except Cancelled:
            result.stage = "cancelled"
            return result
        except OSError as exc:
            message = f"cannot start {exc.filename}: {exc.strerror}" if exc.filename else str(exc.strerror)
            result.diagnostics.append(Diagnostic("build", message))
            return result
        finally:
            for path in (c_file, exe):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _runtime(self, job: Job) -> Path:
        directory = self.dir
        with self._lock:
            if self._runtime_obj is None:
                obj = directory / "causa_runtime.o"
                code, _, err, _ = job.run([self.cc, "-std=c99", "-O2", "-I", str(RUNTIME_DIR), "-c",
                                           str(RUNTIME_SOURCE), "-o", str(obj)])
                if code != 0:
                    raise OSError(0, "cannot build causa_runtime.c: " + err.decode("utf-8", "replace").strip())
                self._runtime_obj = obj
            return self._runtime_obj


def _compile_diagnostic(err: CausaError, filename: str) -> Diagnostic:
    return Diagnostic("compile", err.format(filename), err.line, err.column, err.code)


# ---- background execution -----------------------------------------------------

class Runner:
    """Runs requests on worker threads. Each channel ("run", "check", "explain", ...)
    keeps only its newest request: submitting cancels the previous one, and poll()
    drops results of requests that are no longer the newest (stale results)."""

    def __init__(self) -> None:
        self._results: queue.Queue = queue.Queue()
        self._ids = itertools.count(1)
        self._latest: dict[str, int] = {}
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, channel: str, fn, *args) -> int:
        job = Job()
        with self._lock:
            request = next(self._ids)
            self._latest[channel] = request
            previous, self._jobs[channel] = self._jobs.get(channel), job
        if previous:
            previous.cancel()

        def work() -> None:
            try:
                outcome = fn(job, *args)
            except Exception as exc:  # never lose a request silently
                outcome = Outcome("compile", False, diagnostics=[Diagnostic("internal", f"internal error: {exc!r}")])
            self._results.put((channel, request, outcome))

        threading.Thread(target=work, daemon=True, name=f"causa-{channel}-{request}").start()
        return request

    def cancel(self, *channels: str) -> None:
        with self._lock:
            jobs = [j for c, j in self._jobs.items() if not channels or c in channels]
        for job in jobs:
            job.cancel()

    def busy(self, channel: str) -> bool:
        with self._lock:
            return channel in self._jobs

    def poll(self) -> list[tuple[str, int, Outcome]]:
        fresh = []
        while True:
            try:
                channel, request, outcome = self._results.get_nowait()
            except queue.Empty:
                return fresh
            with self._lock:
                if self._latest.get(channel) != request:
                    continue  # superseded by a newer request on the same channel
                self._jobs.pop(channel, None)
            fresh.append((channel, request, outcome))


def python_description() -> str:
    return f"Python {sys.version.split()[0]}"
