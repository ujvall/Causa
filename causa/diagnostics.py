"""Compile-time diagnostics (language-specification §9.2)."""

from __future__ import annotations


class CausaError(Exception):
    """A compile-time error. The code and location are normative; the message is not."""

    def __init__(self, code: str, message: str, line: int, column: int) -> None:
        super().__init__(f"{line}:{column}: error[{code}]: {message}")
        self.code = code
        self.message = message
        self.line = line
        self.column = column

    def format(self, filename: str) -> str:
        return f"{filename}:{self.line}:{self.column}: error[{self.code}]: {self.message}"
