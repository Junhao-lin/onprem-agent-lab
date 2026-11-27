"""Masked writer for raw evidence (reports/raw/, loadtest results).

Every text file of raw output goes through `write_raw`, which redacts before writing:
  - every secret-looking .env value (names containing PASSWORD/KEY/SALT/SECRET/TOKEN,
    plus other non-public values of 4+ chars) -> [REDACTED]
  - any `sk-...` token -> the project mask format sk-…last4
Files are written as UTF-8 with LF line endings.

Library:
    from rawlog import write_raw
    write_raw(path, text)                      # returns the number of redactions

Shell pipelines (instead of `> file` / `tee`):
    some-command 2>&1 | python -I scripts/rawlog.py reports/raw/<item>/out.txt

tests/platform/test_repo_hygiene.py checks that writers use this module and that
nothing under reports/raw/ contains a secret.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENV_FILE = REPO / ".env"
SK_TOKEN = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")
SECRET_NAME = re.compile(r"(PASSWORD|KEY|SALT|SECRET|TOKEN)", re.I)
# Values too generic to redact without mangling prose (ports, model names, ...).
NOT_SECRET_VARS = re.compile(r"(_PORT|_USER|_DB|_MODEL|_RETENTION|NUM_PARALLEL|MAX_LOADED_MODELS|KEEP_ALIVE)$")


def parse_env_value(raw: str) -> str:
    v = raw.strip()
    if v[:1] in "\"'" and v[-1:] == v[:1] and len(v) >= 2:
        return v[1:-1]
    return re.split(r"\s+#", v, maxsplit=1)[0].strip()


def secret_values(env_file: Path = ENV_FILE) -> list[str]:
    """Every non-trivial .env value except clearly public settings; longest first
    so a value containing another is replaced whole. Missing .env -> []."""
    if not env_file.exists():
        return []
    vals = set()
    for line in env_file.read_text(encoding="utf-8").splitlines():
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


def redact(text: str, secrets: list[str] | None = None) -> tuple[str, int]:
    if secrets is None:
        secrets = secret_values()
    hits = 0
    for s in secrets:
        if s in text:
            hits += text.count(s)
            text = text.replace(s, "[REDACTED]")
    text, n = SK_TOKEN.subn(lambda m: f"sk-…{m.group()[-4:]}", text)
    return text, hits + n


def write_raw(path: Path | str, text: str, secrets: list[str] | None = None) -> int:
    """Redact `text`, then write it to `path` (UTF-8, LF, no trailing whitespace on any
    line, at most one newline at the end, so `git diff --check` stays clean).
    Returns redaction count."""
    path = Path(path)
    clean, hits = redact(text.replace("\r\n", "\n"), secrets)
    clean = "\n".join(line.rstrip(" \t") for line in clean.split("\n")).rstrip("\n")
    clean = clean + "\n" if clean else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(clean, encoding="utf-8", newline="\n")
    return hits


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: <command> | python -I scripts/rawlog.py OUTPUT_FILE", file=sys.stderr)
        return 2
    text = sys.stdin.buffer.read().decode("utf-8", "replace")
    hits = write_raw(argv[0], text)
    print(f"{argv[0]}: {len(text)} chars written, {hits} redaction(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
