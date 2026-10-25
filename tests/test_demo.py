"""Executes docs/demonstration.md: every bash command in it is run (with build/
redirected to a temporary directory and gcc given the strict warning flags), and
every command followed by an output block and "Exit status **N**" must print
exactly that output (stdout, then stderr) and exit with N."""

import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_codegen import CC

ROOT = Path(__file__).resolve().parent.parent
DOC = (ROOT / "docs" / "demonstration.md").read_text(encoding="utf-8")
BLOCK = re.compile(r"```bash\n(.*?)```(?:\n\n```text\n(.*?)```\n\nExit status \*\*(\d)\*\*)?", re.DOTALL)
STRICT = ["-Wall", "-Wextra", "-Wpedantic", "-Werror"]


@unittest.skipUnless(CC, "no C compiler found (set CAUSA_CC to enable)")
class DemonstrationTests(unittest.TestCase):
    def test_demonstration_commands(self) -> None:
        blocks = BLOCK.findall(DOC)
        self.assertEqual(sum(1 for _, out, _ in blocks if out), 9)
        with tempfile.TemporaryDirectory() as tmp:
            for commands, expected, status in blocks:
                for line in commands.splitlines():
                    if line == "mkdir -p build":
                        continue
                    argv = [re.sub(r"^\./build/|^build/", lambda _: tmp + "/", a) for a in shlex.split(line)]
                    if argv[:2] == ["py", "-3.11"]:
                        argv = [sys.executable, *argv[2:]]
                    elif argv[0] == "gcc":
                        argv = [CC, *STRICT, *argv[1:]]
                    with self.subTest(command=line):
                        r = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=120)
                        got = (r.stdout + r.stderr).decode("utf-8").replace("examples\\", "examples/")
                        if argv[0] == sys.executable:  # compiler text output uses the platform's line ends
                            got = got.replace("\r\n", "\n")
                        if expected:
                            self.assertEqual((got, r.returncode), (expected, int(status)))
                        else:
                            self.assertEqual(r.returncode, 0, got)


if __name__ == "__main__":
    unittest.main()
