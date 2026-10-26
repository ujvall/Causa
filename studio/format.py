"""Readable presentation of a program's output for the Studio console.

The runtime's text is never changed: it is parsed by the output formats of
language-specification §8.3–§8.6 (show, explain, whatif, impact) and laid out as
labelled blocks: explanations as a tree, what-ifs as an aligned before/after
table, impacts as labelled lists. A line that does not match a known format is
shown exactly as printed. The console's Raw switch shows the original text.
"""

from __future__ import annotations

import re

Span = tuple[str, str | None]  # (text, style); styles are console tags
Line = list[Span]

LABEL_WIDTH = 10
INDENT = " " * LABEL_WIDTH
_TREE = re.compile(r"^((?:  )+)(\w+) = (.*?)  \[(input|let)(?:: (.*?))?(, see above)?\]$")
_SUMMARY = {"direct dependencies": "direct deps", "transitive dependencies": "all deps", "inputs": "inputs",
            "intermediates": "intermediates"}
KEY_WIDTH = 15
_OUTCOME = re.compile(r"^  (\w+): (.*?) -> (.*?)(?:  \((override|unchanged)\))?$")
_SHOW = re.compile(r"^(\w+) = (.*)$")


def label(text: str, style: str) -> Span:
    return (text.ljust(LABEL_WIDTH), style)


def blocks(stdout: str) -> list[list[str]]:
    """Split output into statements: a statement's first line is not indented."""
    out: list[list[str]] = []
    for line in stdout.splitlines():
        if line.startswith("  ") and out:
            out[-1].append(line)
        else:
            out.append([line])
    return out


def format_output(stdout: str) -> list[Line]:
    lines: list[Line] = []
    previous_show = False
    for block in blocks(stdout):
        head = block[0]
        if head.startswith("explain ") and len(block) > 1:
            formatted = _explain(head[8:], block[1:])
        elif head.startswith("whatif ") and len(block) > 1:
            formatted = _whatif(head[7:], block[1:])
        elif head.startswith("impact ") and len(block) == 3:
            formatted = _impact(head[7:], block[1:])
        elif (m := _SHOW.match(head)) and len(block) == 1:
            formatted = [[label("show", "label-show"), (m.group(1), "name"), (" = ", "muted"), (m.group(2), "value")]]
        else:
            formatted = None
        if formatted is None:  # unknown shape: exactly as printed
            formatted = [[(line, "out")] for line in block]
        is_show = formatted[0][0][1] == "label-show"
        if lines and not (is_show and previous_show):  # a blank line between statements; shows stay together
            lines.append([])
        lines.extend(formatted)
        previous_show = is_show
    return lines


def _explain(name: str, body: list[str]) -> Line | None:
    nodes, summary = [], []
    for line in body:
        if m := _TREE.match(line):
            depth = len(m.group(1)) // 2 - 1
            nodes.append((depth, m.group(2), m.group(3), m.group(4), m.group(5), bool(m.group(6))))
        elif ": " in line and line[2:].split(": ", 1)[0] in _SUMMARY:
            key, values = line[2:].split(": ", 1)
            summary.append((_SUMMARY[key], values))
        else:
            return None
    if not nodes or len(summary) != 4:
        return None
    prefixes = _tree_prefixes([d for d, *_ in nodes])
    width = max(len(p) + len(n) + 3 + len(v) for p, (_, n, v, *_) in zip(prefixes, nodes))
    out: list[Line] = [[label("explain", "label-explain"), (name, "name")]]
    for prefix, (depth, binding, value, kind, source, seen) in zip(prefixes, nodes):
        pad = " " * (width - len(prefix) - len(binding) - 3 - len(value) + 3)
        if kind == "input":
            how: Span = ("input" + (" · see above" if seen else ""), "muted")
        elif seen:
            how = ("let · see above", "muted")
        else:
            how = (source or "", "expr")
        out.append([(INDENT + prefix, "tree"), (binding, "name"), (" = ", "muted"), (value, "value"), (pad, None),
                    how])
    for key, values in summary:
        out.append([(INDENT + key.ljust(KEY_WIDTH), "muted"), (values, "faint" if values == "(none)" else "names")])
    return out


def _tree_prefixes(depths: list[int]) -> list[str]:
    """Box-drawing prefixes for a pre-order list of depths (the root has depth 0)."""
    prefixes, open_levels = [], []  # open_levels[d]: an ancestor at depth d still has siblings to come
    for i, depth in enumerate(depths):
        later = depths[i + 1:]
        last = next((d for d in later if d <= depth), -1) != depth
        del open_levels[depth:]
        if depth == 0:
            prefixes.append("")
        else:
            prefixes.append("".join("│   " if more else "    " for more in open_levels[1:depth])
                            + ("└── " if last else "├── "))
        open_levels.append(not last)
    return prefixes


def _whatif(header: str, body: list[str]) -> Line | None:
    target = None
    if " show " in header:
        header, target = header.rsplit(" show ", 1)
    # Full form: the override lines, then the dependent bindings or "(no dependent bindings)" (LS §8.5.3).
    no_dependents = body[-1:] == ["  (no dependent bindings)"]
    if no_dependents:
        body = body[:-1]
    rows = [m.groups() for line in body if (m := _OUTCOME.match(line))]
    if len(rows) != len(body):
        return None
    out: list[Line] = [[label("what-if", "label-whatif"), (header, "name")]
                       + ([("   showing ", "muted"), (target, "name")] if target else [])]
    if not rows:
        out.append([(INDENT + "no bindings depend on the overridden inputs", "faint")])
        return out
    name_w = max(len("binding"), *(len(r[0]) for r in rows)) + 2
    before_w = max(len("original"), *(len(r[1]) for r in rows)) + 1
    after_w = max((len(r[2]) for r in rows if r[3]), default=0) + 3  # only rows that carry a note
    if not target:  # the targeted form has a single row: no column titles needed
        out.append([(INDENT + "binding".ljust(name_w) + "original".ljust(before_w) + "   what-if", "faint")])
    for binding, before, after, note in rows:
        if note == "override":
            style, tag = "override", "override"
        elif note == "unchanged":
            style, tag = "faint", "same value"
        elif after.startswith(("error[", "unavailable")):
            style, tag = "failed", ""
        else:
            style, tag = "changed", ""
        dim = "faint" if note == "unchanged" else None
        out.append([(INDENT + binding.ljust(name_w), dim or "name"), (before.ljust(before_w), dim or "value"),
                    (" → ", "muted"), (after, style)]
                   + ([(" " * (after_w - len(after)) + tag, "faint" if dim else "muted")] if tag else []))
    if no_dependents:
        out.append([(INDENT + "no bindings depend on the overridden inputs", "faint")])
    return out


_DIAGNOSTIC = re.compile(r"^.*?:(\d+):(\d+): (?:(?:runtime )?error\[(\w+)\]: (.*)|assertion failed: (.*))$")
_ASSERT_BINDING = re.compile(r"^  (\w+) = (.*)$")


def format_stderr(stderr: str) -> list[tuple[Line, tuple[int, int] | None]]:
    """Compile errors, runtime errors and assertion failures (LS §9.2, §9.3) as labelled lines,
    each with its (line, column) so the console can link it to the editor."""
    out: list[tuple[Line, tuple[int, int] | None]] = []
    for text in stderr.splitlines():
        if m := _DIAGNOSTIC.match(text):
            line, column, code, message, condition = m.groups()
            where = f"line {line}, column {column}"
            if code:
                spans: Line = [label("error", "label-error"), (code, "error-code"), ("  ", None), (where, "link"),
                               ("   ", None), (message, "error")]
            else:
                spans = [label("assert", "label-error"), ("failed", "error-code"), ("  ", None), (f"line {line}", "link"),
                         ("   ", None), (condition, "expr")]
            out.append((spans, (int(line), int(column))))
        elif (m := _ASSERT_BINDING.match(text)) and out and out[-1][0][0][0].startswith("assert"):
            out.append(([(INDENT + m.group(1), "name"), (" = ", "muted"), (m.group(2), "value")], None))
        else:
            out.append(([(text, "error")], None))
    return out


def _impact(name: str, body: list[str]) -> Line | None:
    keys = {"  direct dependents: ": "direct", "  all dependents: ": "all affected"}
    out: list[Line] = [[label("impact", "label-impact"), (name, "name")]]
    for line, (prefix, key) in zip(body, keys.items()):
        if not line.startswith(prefix):
            return None
        values = line[len(prefix):]
        out.append([(INDENT + key.ljust(KEY_WIDTH), "muted"), (values, "faint" if values == "(none)" else "names")])
    return out
