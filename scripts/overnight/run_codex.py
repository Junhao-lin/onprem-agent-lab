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
# Any other sk- token is shown in the project-wide mask format (sk-…last4,
# the format the project owner specified for key output; see README security notes).
SK_TOKEN = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")
SECRET_NAME = re.compile(r"(PASSWORD|KEY|SALT|SECRET|TOKEN)", re.I)
# Values too generic to redact without mangling prose (ports, model names, ...).
NOT_SECRET_VARS = re.compile(r"(_PORT|_USER|_DB|_MODEL|_RETENTION|NUM_PARALLEL|MAX_LOADED_MODELS|KEEP_ALIVE)$")


def codex_exe() -> str:
    found = shutil.which("codex")
    if found:
        return found
    standalone = Path.home() / ".codex/packages/standalone/current/bin/codex.exe"
    if standalone.exists():
        return str(standalone)
    raise SystemExit("codex CLI not found")


def parse_env_value(raw: str) -> str:
    v = raw.strip()
    if v[:1] in "\"'" and v[-1:] == v[:1] and len(v) >= 2:
        return v[1:-1]
    return re.split(r"\s+#", v, maxsplit=1)[0].strip()


def secret_values() -> list[str]:
    """Every non-trivial .env value except clearly public settings; longest first
    so a value containing another is replaced whole."""
    vals = set()
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().removeprefix("export ").strip()
        v = parse_env_value(v)
        if not v or NOT_SECRET_VARS.search(k):
            continue
        # Sensitive names are redacted at any length; other values only when
        # long enough not to collide with ordinary words.
        if SECRET_NAME.search(k) or len(v) >= 4:
            vals.add(v)
    return sorted(vals, key=len, reverse=True)


def redact(text: str, secrets: list[str]) -> tuple[str, int]:
    hits = 0
    for s in secrets:
        if s in text:
            hits += text.count(s)
            text = text.replace(s, "[REDACTED]")
    text, n = SK_TOKEN.subn(lambda m: f"sk-…{m.group()[-4:]}", text)
    return text, hits + n


def main() -> int:
    item, prompt_file = sys.argv[1], Path(sys.argv[2])
    prompt = prompt_file.read_text(encoding="utf-8")
    raw = REPO / "reports/raw" / item
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "codex-prompt.md").write_text(prompt, encoding="utf-8", newline="\n")
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
    log, hits_log = redact(out, secrets)
    (raw / "codex.log").write_text(
        f"# codex exec ({status}, exit {rc}, {elapsed:.0f}s)\n\n{log}", encoding="utf-8", newline="\n")
    hits_last = 0
    if reply:
        reply, hits_last = redact(reply, secrets)
        last.write_text(reply, encoding="utf-8", newline="\n")
    print(f"codex {status}, exit {rc}, {elapsed:.0f}s; reply: {bool(reply)}; "
          f"redacted {hits_log + hits_last} occurrence(s)")
    return 0 if status == "ok" and rc == 0 and reply else 1


if __name__ == "__main__":
    sys.exit(main())
