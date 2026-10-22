"""Front-end pipeline: source text -> checked program -> validated Causal IR.

Parsing and semantic analysis are interleaved statement by statement, so the
first error in source order is reported whichever stage detects it (LS §9.2).
"""

from __future__ import annotations

from pathlib import Path

from .codegen import CProgram, generate_c
from .ir import IRModule, build_ir, check_against_program, validate_ir
from .optimizer import OptimizationResult, optimize
from .lexer import decode_source
from .parser import Parser
from .semantic import SemanticProgram, analyze


def read_source(path: str | Path) -> str:
    return decode_source(Path(path).read_bytes())


def check(text: str) -> SemanticProgram:
    return analyze(Parser(text).iter_statements())


def compile_to_ir(text: str, source_file: str = "<source>") -> IRModule:
    sem = check(text)
    module = build_ir(sem, source_file)
    validate_ir(module)
    check_against_program(module, sem)
    return module


def compile_optimized(text: str, source_file: str = "<source>") -> OptimizationResult:
    """compile_to_ir followed by the optimizer (which re-validates its output)."""
    return optimize(compile_to_ir(text, source_file))


def compile_to_c(text: str, source_file: str = "<source>", standalone: bool = False) -> CProgram:
    """Front end, optimizer and C code generator (the generator re-validates the IR)."""
    return generate_c(compile_optimized(text, source_file).module, standalone=standalone)
