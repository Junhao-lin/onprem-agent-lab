"""Ask Codex for a read-only review and save its reply as UTF-8.

    python -I scripts/overnight/run_codex.py <item> <prompt-file>

Runs `codex exec --sandbox read-only -c model_reasoning_effort="medium" <prompt>`
from the repo root and writes:
  reports/raw/<item>/codex-prompt.md   the exact prompt
  reports/raw/<item>/codex-last.md     Codex's final message
  reports/raw/<item>/codex.log         full stdout + stderr (progress, commands run)

Stops Codex after 15 minutes. Before anything is written, every secret value
from .env is redacted, so a reply that quotes a key never lands on disk.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TIMEOUT_S = 15 * 60
SECRET_VARS = ("PASSWORD", "KEY", "SALT", "SECRET", "TOKEN")


def codex_exe() -> str:
    found = shutil.which("codex")
    if found:
        return found
    standalone = Path.home() / ".codex/packages/standalone/current/bin/codex.exe"
    if standalone.exists():
        return str(standalone)
    raise SystemExit("codex CLI not found")


def secret_values() -> list[str]:
    vals = []
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            if any(s in k.upper() for s in SECRET_VARS) and len(v.strip()) >= 6:
                vals.append(v.strip())
    return vals


def redact(text: str, secrets: list[str]) -> tuple[str, int]:
    hits = 0
    for s in secrets:
        if s in text:
            hits += text.count(s)
            text = text.replace(s, "[REDACTED]")
    return text, hits


def main() -> int:
    item, prompt_file = sys.argv[1], Path(sys.argv[2])
    prompt = prompt_file.read_text(encoding="utf-8")
    raw = REPO / "reports/raw" / item
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "codex-prompt.md").write_text(prompt, encoding="utf-8", newline="\n")
    last = raw / "codex-last.md"
    if last.exists():
        last.unlink()

    cmd = [codex_exe(), "exec", "--sandbox", "read-only",
           "-c", 'model_reasoning_effort="medium"',
           "--output-last-message", str(last), prompt]
    started = time.monotonic()
    status = "ok"
    try:
        proc = subprocess.run(cmd, cwd=REPO, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_S,
                              env={**os.environ, "NO_COLOR": "1"})
        out, rc = proc.stdout + "\n--- stderr ---\n" + proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as e:
        status = "timeout"
        out = f"{e.stdout or ''}\n--- stderr ---\n{e.stderr or ''}"
        out = out if isinstance(out, str) else out.decode("utf-8", "replace")
        rc = -1
    elapsed = time.monotonic() - started

    secrets = secret_values()
    log, hits_log = redact(out, secrets)
    (raw / "codex.log").write_text(
        f"# codex exec ({status}, exit {rc}, {elapsed:.0f}s)\n\n{log}", encoding="utf-8", newline="\n")
    hits_last = 0
    if last.exists():
        text, hits_last = redact(last.read_text(encoding="utf-8"), secrets)
        last.write_text(text, encoding="utf-8", newline="\n")
    print(f"codex {status}, exit {rc}, {elapsed:.0f}s; reply: {last.exists()}; "
          f"redacted {hits_log + hits_last} secret occurrence(s)")
    return 0 if status == "ok" and rc == 0 and last.exists() else 1


if __name__ == "__main__":
    sys.exit(main())
