"""Ask Codex for a read-only review and save its reply as UTF-8.

    python -I scripts/overnight/run_codex.py <item> <prompt-file>

Runs `codex exec --sandbox read-only -c model_reasoning_effort="medium" <prompt>`
from the repo root and writes:
  reports/raw/<item>/codex-prompt.md   the exact prompt
  reports/raw/<item>/codex-last.md     Codex's final message
  reports/raw/<item>/codex.log         full stdout + stderr (progress, commands run)

Stops Codex after 15 minutes. Nothing Codex produces is written into the repo
unredacted: its final message goes to a temp file outside the repo first, and
every value of a .env variable (quotes and inline comments stripped) plus any
`sk-...` token is redacted before the repo copy is written. The temp file is
removed in all cases, including timeout.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TIMEOUT_S = 15 * 60
# Masking lives in scripts/rawlog.py (shared by every raw-evidence writer).
sys.path.insert(0, str(REPO / "scripts"))
from rawlog import redact, secret_values, write_raw  # noqa: E402,F401


def codex_exe() -> str:
    found = shutil.which("codex")
    if found:
        return found
    standalone = Path.home() / ".codex/packages/standalone/current/bin/codex.exe"
    if standalone.exists():
        return str(standalone)
    raise SystemExit("codex CLI not found")


def main() -> int:
    item, prompt_file = sys.argv[1], Path(sys.argv[2])
    prompt = prompt_file.read_text(encoding="utf-8")
    raw = REPO / "reports/raw" / item
    raw.mkdir(parents=True, exist_ok=True)
    write_raw(raw / "codex-prompt.md", prompt)
    last = raw / "codex-last.md"
    if last.exists():
        last.unlink()

    fd, tmp_name = tempfile.mkstemp(prefix="codex-last-", suffix=".md")
    os.close(fd)
    tmp_last = Path(tmp_name)
    cmd = [codex_exe(), "exec", "--sandbox", "read-only",
           "-c", 'model_reasoning_effort="medium"',
           "--output-last-message", str(tmp_last), prompt]
    started = time.monotonic()
    status = "ok"
    try:
        try:
            proc = subprocess.run(cmd, cwd=REPO, stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_S,
                                  env={**os.environ, "NO_COLOR": "1"})
            out, rc = proc.stdout + "\n--- stderr ---\n" + proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as e:
            status = "timeout"
            parts = [p if isinstance(p, str) else (p or b"").decode("utf-8", "replace")
                     for p in (e.stdout, e.stderr)]
            out, rc = f"{parts[0]}\n--- stderr ---\n{parts[1]}", -1
        reply = tmp_last.read_text(encoding="utf-8") if tmp_last.stat().st_size else ""
    finally:
        tmp_last.unlink(missing_ok=True)
    elapsed = time.monotonic() - started

    secrets = secret_values()
    hits_log = write_raw(raw / "codex.log",
                         f"# codex exec ({status}, exit {rc}, {elapsed:.0f}s)\n\n{out}", secrets)
    hits_last = write_raw(last, reply, secrets) if reply else 0
    print(f"codex {status}, exit {rc}, {elapsed:.0f}s; reply: {bool(reply)}; "
          f"redacted {hits_log + hits_last} occurrence(s)")
    return 0 if status == "ok" and rc == 0 and reply else 1


if __name__ == "__main__":
    sys.exit(main())
