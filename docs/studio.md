# CAUSA Studio

CAUSA Studio is a desktop application for writing, running and exploring CAUSA programs: a source editor, an integrated console, the program's dependency graph, and panels for `explain`, `impact` and `whatif`. Everything it shows comes from the CAUSA compiler and runtime in this repository; Studio has no CAUSA semantics of its own.

## Launch

From the repository root:

```bash
py -3.11 -m studio
```

This opens the window with an unsaved copy of [examples/pricing.cau](../examples/pricing.cau); saving it asks for a new location, so the repository's example is never overwritten. To open a file directly, pass it: `py -3.11 -m studio path/to/program.cau`. On Windows, `pyw -3.11 -m studio` starts it without a console window.

## Prerequisites

| Requirement | Why | Verified with |
|---|---|---|
| Python 3.11+ with Tk (included in the python.org Windows installer) | runs Studio and the compiler | CPython 3.11.9, Tk 8.6.12, Windows 11 |
| A C compiler: `$CAUSA_CC`, else `gcc`, `clang` or `cc` on `PATH` | builds the generated C, as for the command-line workflow | GCC 16.1.0 (MSYS2 UCRT64) |

There is nothing to install: Studio uses only the Python standard library. Without a C compiler, Studio still opens, checks programs and draws the dependency graph; Run, Explain, Impact and What-if report that no C compiler was found.

## Using Studio

| Area | What it does |
|---|---|
| Toolbar and menus | New (Ctrl+N), Open (Ctrl+O), Save (Ctrl+S), Save As (Ctrl+Shift+S), Run (F5 or Ctrl+Enter), Stop (Shift+F5), Clear console (Ctrl+L), tabs Ctrl+1 to Ctrl+4. The file name shows a ● when there are unsaved changes; closing or opening another file asks before discarding them. |
| Editor | Line numbers, highlighting of CAUSA keywords, reserved words, declared names, literals, operators and comments; auto-indentation, Tab / Shift+Tab, toggle comment (Ctrl+/), undo and redo. The program is checked by the real front end shortly after you stop typing: the first error is underlined at its line and column, and the status bar shows its code (for example `✕ E401 at 2:19`). |
| Console | Each Run shows the program's output as one labelled block per statement: `show` values, `explain` as a tree with each let's expression beside it and the dependency lists below, `what-if` as an aligned table of original → counterfactual values (overrides and unchanged values marked), and `impact` as labelled lists. Then come diagnostics (`error  R101  line 14, column 22  division by zero`, assertion failures with the values involved), the exit code with its meaning (0 success, 1 assertion failed, 2 runtime error, 3 invalid launch arguments) and the time spent compiling, building with the C compiler and running. Click a diagnostic to jump to its location. **Raw output** shows exactly what the compiler and program printed, for the whole history. Output that does not match a known format is always shown as printed. Explain, Impact and What-if requests add one summary line each. The console keeps its history across runs and files until you press Clear. |
| Graph | Every binding of the program, from the compiler's provenance. Arrows point from a dependency to the binding that uses it. Click a binding to highlight everything it depends on (cyan) and everything it affects (orange); the selection is shared with the Explain and Impact panels. Drag to pan, scroll to move. |
| Explain | Choose a binding and press Explain: the panel shows its provenance from the compiler (kind, type, declaring line, expression, direct dependencies and dependents, inputs) and the output of `explain NAME` printed by the runtime. |
| Impact | Choose a binding and press Show impact: the direct and all affected bindings printed by `impact NAME`, also highlighted in the graph. |
| What-if | Choose one or more inputs, enter new values and press Run what-if. The runtime evaluates `whatif a = …, b = …` in a separate counterfactual environment and the table lists every binding it re-evaluated with its original and counterfactual value (`override`, `changed`, `same value`, `failed`, `unavailable`). Values are checked with CAUSA's literal rules; type errors such as a float for an `int` input are reported by the compiler (E403), a repeated input as E305. |

When the source changes after an Explain, Impact or What-if result, the panel says the result is out of date.

## How it works

| Module | Responsibility |
|---|---|
| [studio/service.py](../studio/service.py) | No user interface code. Runs the compiler in-process through its API (`compile_to_ir`, `optimize`, `generate_c`), builds with the C compiler and runs the program as child processes created from argument lists (never a shell string), on worker threads. Holds the result and diagnostic models, the dependency graph (from the IR provenance) and process cancellation. |
| [studio/app.py](../studio/app.py) | Window, menus, files, Run/Stop, and routing of results to the views. |
| [studio/editor.py](../studio/editor.py), [console.py](../studio/console.py), [graph.py](../studio/graph.py), [panels.py](../studio/panels.py), [theme.py](../studio/theme.py) | The editor, console, graph view, Explain/Impact/What-if panels and the dark theme. |
| [studio/format.py](../studio/format.py) | Lays the runtime's output out for the console by parsing the output formats of language-specification §8.3–§8.6; never changes names, values or messages. |

* **Framework: Tkinter.** It ships with Python, so Studio adds no dependency and calls the existing compiler directly, with no server, network port or second backend. Its `Text` widget (the editor component IDLE is built on) provides undo, tags for highlighting and diagnostics, and fast editing; its `Canvas` draws the graph.
* **Explain, Impact and What-if use the real runtime.** For each request Studio builds a query program: the current source with every `input` and `let` declaration on its original line, every other statement blanked (so runtime error locations still match the editor), plus one generated statement such as `whatif price = 160, discount = 0.5`. Binding names must be bindings of the program, and each value must parse as a single CAUSA literal, so no other code can be injected. The query program is compiled, built and run exactly like a normal program. Because the query runs the declarations only, a `whatif` from the panel sees every binding and the program's own `show`, `assert` and other statements do not run.
* **Responsiveness and stale results.** Each kind of request (run, check, explain, impact, whatif) keeps only its newest request: starting a new one cancels the previous one, and a result that is no longer the newest is discarded.
* **Stop** kills the C compiler or the program together with every process it started (`taskkill /T` on Windows, a process group elsewhere). The compiler's front end runs in-process for a few milliseconds on typical programs and cannot be interrupted midway; a stopped request's result is discarded.
* **Temporary files** go to one `causa-studio-*` directory under the system temporary directory, created on first build and removed when Studio closes. Studio never writes to a source file unless you save it.

## Packaging for Windows

[packaging/build_windows.py](../packaging/build_windows.py) builds a folder bundle with PyInstaller (a build-time tool, not a dependency of Studio):

```bash
py -3.11 -m pip install pyinstaller
```

```bash
py -3.11 packaging/build_windows.py
```

The result is `dist/CAUSA Studio/CAUSA Studio.exe` (about 27 MB, including Python, Tk, the compiler, the C runtime sources and the example). It still needs a C compiler on `PATH` or in `CAUSA_CC` to build programs. Verified: built with PyInstaller 6.22.3 in a virtual environment, launched, and ran `pricing.cau` from its window. `dist/` and `build/` are ignored by Git.

## Tests

[tests/test_studio_format.py](../tests/test_studio_format.py) checks the console layout and that no name, value or error code of any specification program's output is lost. [tests/test_studio_service.py](../tests/test_studio_service.py) covers file loading and saving, query programs and value validation, graph edges and their direction, report parsing, argument passing without a shell, cancellation of a whole process tree, stale-result handling, a missing or unstartable C compiler, and end-to-end runs (output identical to language-specification §12, compile, runtime and assertion errors with locations, several what-if overrides, E403/E305 from the compiler, cancellation). [tests/test_studio_ui.py](../tests/test_studio_ui.py) drives the real window: start-up, highlighting, Run, a compile error's location, a runtime failure followed by a successful run, save and reopen, graph highlighting, the three panels, rejection of an invalid value, stale results, and Stop. Both run with the rest of the suite:

```bash
py -3.11 -m unittest discover -s tests -v
```

## Limitations

* Tested on Windows 11 only (Python 3.11.9, Tk 8.6.12, GCC 16.1.0, a 125% display scale). Linux and macOS should work with Tk and a C compiler but have not been tried.
* One file at a time; there are no editor tabs.
* Launch values (`--set`) cannot be entered in Studio; the What-if panel covers hypothetical inputs.
* Explain, Impact and What-if each build a small program with the C compiler, which takes about 0.3–0.6 s on the test machine.
* Graphs with more than 4,000 bindings are not drawn (the panels still work). Graph nodes show names and types, not values.
* There is no find/replace and no autocompletion in the editor.
* A Studio process that is killed (rather than closed) leaves its temporary directory behind.
