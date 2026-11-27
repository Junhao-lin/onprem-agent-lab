"""Rotate POSTGRES_PASSWORD and REDIS_PASSWORD without ever printing them.

    python scripts/rotate_service_passwords.py

Order (each step stops the script on failure):
  1. Postgres: ALTER USER ... PASSWORD sent to psql over stdin (never argv), then
     .env is updated; the new password is verified over TCP (scram-sha-256 rule in
     pg_hba) and the old one must be rejected.
  2. Redis: .env is updated, the redis container is recreated so requirepass picks
     up the new value; the new password must answer PONG and the old one must fail.
  3. Dependent services (litellm) are recreated so they read the new values, and the
     script waits until every service is healthy.

Secrets travel only via stdin and .env. Output shows step names and outcomes only.
Volumes are never touched (no `down -v`).
"""
from __future__ import annotations

import json
import secrets
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bootstrap_keys import ENV_FILE, REPO, load_env, set_env_var  # noqa: E402

COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.gpu.yml",
           "--profile", "platform", "--profile", "monitoring"]
DEPENDENTS = ["litellm"]  # services whose environment embeds the passwords


def compose(*args: str, stdin: str | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    # stdin as bytes: text mode on Windows would turn LF into CRLF and the shell's
    # `read` would keep the CR as part of the password.
    r = subprocess.run([*COMPOSE, *args], cwd=REPO, capture_output=True, timeout=timeout,
                       input=stdin.encode("utf-8") if stdin is not None else None)
    return subprocess.CompletedProcess(r.args, r.returncode, r.stdout.decode("utf-8", "replace"),
                                       r.stderr.decode("utf-8", "replace"))


def new_secret() -> str:
    # URL-safe alphabet: valid inside DATABASE_URL and a SQL string literal as-is.
    return secrets.token_urlsafe(32)


def wait_healthy(services: list[str] | None = None, timeout: int = 300) -> None:
    deadline = time.time() + timeout
    while True:
        rows = [json.loads(l) for l in compose("ps", "--format", "json").stdout.splitlines() if l.strip()]
        rows = [r for r in rows if services is None or r["Service"] in services]
        bad = [r["Service"] for r in rows if r.get("Health") not in ("healthy", "")
               or r.get("State") != "running"]
        if rows and not bad:
            return
        if time.time() > deadline:
            raise SystemExit(f"timeout waiting for healthy: {bad}")
        time.sleep(3)


def pg_login_ok(password: str) -> bool:
    """Log in over TCP to the container's own address (not loopback, which is trust)."""
    script = ('IFS= read -r PGPASSWORD; export PGPASSWORD; '
              'psql -h "$(hostname -i | cut -d" " -f1)" -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
              '-w -tAc "select 1"')
    r = compose("exec", "-T", "postgres", "sh", "-c", script, stdin=password + "\n")
    return r.returncode == 0 and r.stdout.strip() == "1"


def redis_auth_ok(password: str) -> bool:
    script = 'IFS= read -r p; REDISCLI_AUTH="$p" redis-cli --no-auth-warning ping'
    r = compose("exec", "-T", "redis", "sh", "-c", script, stdin=password + "\n")
    return r.stdout.strip() == "PONG"


def rotate_postgres() -> None:
    env = load_env(ENV_FILE)
    old, user = env["POSTGRES_PASSWORD"], env["POSTGRES_USER"]
    new = new_secret()
    sql = f"ALTER USER \"{user}\" WITH PASSWORD '{new}';\n"
    r = compose("exec", "-T", "postgres", "sh", "-c",
                'psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"', stdin=sql)
    if r.returncode != 0:
        raise SystemExit(f"postgres: ALTER USER failed (exit {r.returncode})")
    set_env_var(ENV_FILE, "POSTGRES_PASSWORD", new)
    print("postgres: password changed in the database and written to .env")
    if not pg_login_ok(new):
        raise SystemExit("postgres: login with the NEW password failed")
    if pg_login_ok(old):
        raise SystemExit("postgres: the OLD password still works")
    print("postgres: verified - new password accepted, old password rejected (TCP, scram)")


def rotate_redis() -> None:
    old = load_env(ENV_FILE)["REDIS_PASSWORD"]
    set_env_var(ENV_FILE, "REDIS_PASSWORD", new_secret())
    print("redis: new password written to .env")
    r = compose("up", "-d", "--force-recreate", "redis")
    if r.returncode != 0:
        raise SystemExit(f"redis: recreate failed (exit {r.returncode})")
    wait_healthy(["redis"])
    if not redis_auth_ok(load_env(ENV_FILE)["REDIS_PASSWORD"]):
        raise SystemExit("redis: AUTH with the NEW password failed")
    if redis_auth_ok(old):
        raise SystemExit("redis: the OLD password still works")
    print("redis: recreated and healthy - new password accepted, old password rejected")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    wait_healthy()
    rotate_postgres()
    rotate_redis()
    r = compose("up", "-d", "--force-recreate", *DEPENDENTS)
    if r.returncode != 0:
        raise SystemExit(f"recreate {DEPENDENTS} failed (exit {r.returncode})")
    wait_healthy()
    print(f"recreated {DEPENDENTS}; all services healthy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
