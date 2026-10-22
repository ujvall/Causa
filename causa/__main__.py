"""Command-line driver for the implemented compiler stages (Phases 2-5).

    py -3.11 -m causa tokens FILE   token stream
    py -3.11 -m causa parse FILE    AST as S-expressions
    py -3.11 -m causa check FILE    parse + semantic analysis
    py -3.11 -m causa ir FILE       validated, unoptimized Causal IR
    py -3.11 -m causa optimize FILE optimized Causal IR and the optimization log
    py -3.11 -m causa emit-c FILE [-o OUT.c] [--standalone]
                                    generated C (stdout unless -o is given)

None of these execute a CAUSA program, and no C compiler is invoked. Generated
C for a program using show/explain/whatif/impact/assert calls runtime library
functions that are not implemented yet (Phase 6); a note says so on stderr, and
--standalone turns that into an error instead.
Exit status: 0 success, 1 CAUSA diagnostic (printed to stderr), 2 file not
readable or writable, 3 the backend cannot produce the requested output.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .astnodes import dump
from .diagnostics import CausaError
from .codegen import RUNTIME_DIR, CodegenError
from .frontend import check, compile_optimized, compile_to_c, compile_to_ir
from .ir import format_ir
from .optimizer import format_log
from .lexer import decode_source, tokenize
from .parser import parse
from .semantic import BindingKind


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="causa", description="CAUSA compiler front end (no backend yet).")
    ap.add_argument("command", choices=["tokens", "parse", "check", "ir", "optimize", "emit-c"])
    ap.add_argument("file", type=Path)
    ap.add_argument("-o", "--output", type=Path, help="emit-c: write the C source to this file")
    ap.add_argument("--standalone", action="store_true",
                    help="emit-c: fail if the program needs the (not yet implemented) runtime library")
    args = ap.parse_args(argv)
    if args.command != "emit-c" and (args.output or args.standalone):
        ap.error("-o/--output and --standalone apply only to emit-c")

    try:
        data = args.file.read_bytes()
    except OSError as exc:
        print(f"causa: cannot read {args.file}: {exc.strerror}", file=sys.stderr)
        return 2
    try:
        text = decode_source(data)
        if args.command == "tokens":
            for t in tokenize(text):
                print(f"{t.line}:{t.column}\t{t.kind.name}\t{t.lexeme!r}")
        elif args.command == "parse":
            print(dump(parse(text)))
        elif args.command == "check":
            sem = check(text)
            inputs = sum(s.kind is BindingKind.INPUT for s in sem.symbols.values())
            print(f"{args.file}: semantic check passed: {inputs} inputs, "
                  f"{len(sem.symbols) - inputs} lets, {len(sem.program.statements)} statements "
                  f"(not executed)")
        elif args.command == "ir":
            print(format_ir(compile_to_ir(text, str(args.file))))
        elif args.command == "emit-c":
            program = compile_to_c(text, str(args.file), standalone=args.standalone)
            if args.output:
                try:
                    args.output.write_text(program.source, encoding="utf-8", newline="\n")
                except OSError as exc:
                    print(f"causa: cannot write {args.output}: {exc.strerror}", file=sys.stderr)
                    return 2
            else:
                sys.stdout.write(program.source)
            if program.runtime_calls:
                uses = ", ".join(f"{name} (line {line})" for name, line in program.runtime_calls)
                print(f"causa: note: the generated C calls runtime library functions that are not "
                      f"implemented yet (Phase 6): {uses}. It compiles against {RUNTIME_DIR / 'causa_runtime.h'} "
                      f"but cannot be linked into an executable yet.", file=sys.stderr)
        else:
            result = compile_optimized(text, str(args.file))
            print(format_ir(result.module, optimized=True))
            print()
            print("optimizations:")
            print(format_log(result.log))
    except CausaError as err:
        print(err.format(str(args.file)), file=sys.stderr)
        return 1
    except CodegenError as err:
        print(f"causa: error: {err}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
