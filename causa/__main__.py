"""Command-line harness for the implemented front end (Phases 2-3).

    py -3.11 -m causa tokens FILE   token stream
    py -3.11 -m causa parse FILE    AST as S-expressions
    py -3.11 -m causa check FILE    parse + semantic analysis
    py -3.11 -m causa ir FILE       validated, unoptimized Causal IR

None of these execute a CAUSA program: no code generator or runtime exists yet.
Exit status: 0 success, 1 CAUSA diagnostic (printed to stderr), 2 file not readable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .astnodes import dump
from .diagnostics import CausaError
from .frontend import check, compile_to_ir
from .ir import format_ir
from .lexer import decode_source, tokenize
from .parser import parse
from .semantic import BindingKind


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="causa", description="CAUSA compiler front end (no backend yet).")
    ap.add_argument("command", choices=["tokens", "parse", "check", "ir"])
    ap.add_argument("file", type=Path)
    args = ap.parse_args(argv)

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
        else:
            print(format_ir(compile_to_ir(text, str(args.file))))
    except CausaError as err:
        print(err.format(str(args.file)), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
