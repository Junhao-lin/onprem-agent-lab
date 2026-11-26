"""Run the full pytest suite and save its complete output as UTF-8.

    python -I scripts/overnight/run_pytest.py <item>      -> reports/raw/<item>/pytest.txt

Exit code is pytest's. Output is written by Python (not shell redirection) so
the file is always UTF-8 regardless of the console code page. Every .env secret
value (and any sk- token beyond its last 4 chars) is redacted before writing:
long tracebacks print function arguments, which can include keys.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_codex import redact, secret_values  # noqa: E402


def main() -> int:
    item = sys.argv[1]
    out = REPO / "reports/raw" / item / "pytest.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "uv", "run", "pytest", "-v", *sys.argv[2:]]
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    header = f"$ {' '.join(cmd[1:])}\n# started {started}, exit code {proc.returncode}\n\n"
    text, hits = redact(header + proc.stdout + proc.stderr, secret_values())
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"{out.relative_to(REPO)}: exit {proc.returncode}; redacted {hits}; "
          f"{proc.stdout.strip().splitlines()[-1]}")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
