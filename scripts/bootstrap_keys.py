"""Create or update per-app LiteLLM virtual keys from infra/litellm/virtual-keys.toml.

Idempotent:
  - key in .env is valid for its alias   -> update limits in place (key unchanged)
  - key missing / invalid / --rotate     -> delete any key with that alias,
                                            generate a new one, write it to .env

Key values are only ever written to .env (git-ignored) and printed masked.
Stdlib only (Python 3.11+).

Usage:
    python scripts/bootstrap_keys.py            # apply
    python scripts/bootstrap_keys.py --rotate   # force new keys
    LITELLM_URL=http://host:4000 python scripts/bootstrap_keys.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENV_FILE = REPO / ".env"
KEYS_FILE = REPO / "infra" / "litellm" / "virtual-keys.toml"
LIMIT_FIELDS = ("models", "rpm_limit", "tpm_limit", "max_parallel_requests")


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def set_env_var(path: Path, name: str, value: str) -> None:
    """Replace NAME=... in place (or append), preserving all other lines."""
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"^{re.escape(name)}=.*$", re.MULTILINE)
    line = f"{name}={value}"
    if pattern.search(text):
        text = pattern.sub(lambda _: line, text, count=1)
    else:
        text = text.rstrip("\n") + f"\n{line}\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def mask(key: str) -> str:
    return f"{key[:3]}…{key[-4:]}" if len(key) > 8 else "***"


class Gateway:
    def __init__(self, base: str, master_key: str):
        self.base = base.rstrip("/")
        self.master_key = master_key

    def request(self, method: str, path: str, body: dict | None = None,
                query: dict | None = None, bearer: str | None = None) -> tuple[int, dict]:
        """Keys only ever travel in the Authorization header (or a JSON body), never in
        the URL: LiteLLM's access log records the full request line."""
        url = self.base + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        req = urllib.request.Request(url, method=method)
        req.add_header("Authorization", f"Bearer {bearer or self.master_key}")
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, data=data, timeout=30) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except json.JSONDecodeError:
                return e.code, {}

    def key_info(self, key: str) -> dict | None:
        # Without ?key=, /key/info describes the key that authenticated the call.
        status, body = self.request("GET", "/key/info", bearer=key)
        return body.get("info") if status == 200 else None

    def alias_exists(self, alias: str) -> bool:
        status, body = self.request("GET", "/key/list", query={"key_alias": alias})
        if status != 200:
            raise RuntimeError(f"/key/list failed ({status}): {body}")
        return bool(body.get("keys"))


def apply_key(gw: Gateway, alias: str, spec: dict, env: dict[str, str], rotate: bool) -> str:
    env_var = spec["env_var"]
    limits = {f: spec[f] for f in LIMIT_FIELDS}
    metadata = {"app": alias, "description": spec.get("description", ""),
                "managed_by": "scripts/bootstrap_keys.py"}
    current = env.get(env_var, "")

    if current and not rotate:
        info = gw.key_info(current)
        if info and info.get("key_alias") == alias:
            status, body = gw.request("POST", "/key/update",
                                      body={"key": current, **limits, "metadata": metadata})
            if status != 200:
                raise RuntimeError(f"[{alias}] /key/update failed ({status}): {body}")
            return f"updated  {alias:<18} key={mask(current)} {limits}"

    # No usable local key: remove orphans with this alias so it stays unique.
    if gw.alias_exists(alias):
        status, body = gw.request("POST", "/key/delete", body={"key_aliases": [alias]})
        if status != 200:
            raise RuntimeError(f"[{alias}] /key/delete failed ({status}): {body}")

    status, body = gw.request("POST", "/key/generate",
                              body={"key_alias": alias, **limits, "metadata": metadata})
    if status != 200 or not body.get("key"):
        raise RuntimeError(f"[{alias}] /key/generate failed ({status}): {body}")
    new_key = body["key"]
    set_env_var(ENV_FILE, env_var, new_key)
    env[env_var] = new_key
    return f"created  {alias:<18} key={mask(new_key)} -> .env:{env_var} {limits}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rotate", action="store_true", help="force new keys for all apps")
    args = parser.parse_args()

    if not ENV_FILE.exists():
        print("ERROR: .env not found; copy .env.example first", file=sys.stderr)
        return 2
    env = load_env(ENV_FILE)
    master = env.get("LITELLM_MASTER_KEY", "")
    if not master.startswith("sk-") or "change-me" in master:
        print("ERROR: LITELLM_MASTER_KEY is not set in .env", file=sys.stderr)
        return 2

    base = os.environ.get("LITELLM_URL", f"http://127.0.0.1:{env.get('LITELLM_PORT', '4000')}")
    gw = Gateway(base, master)
    specs = tomllib.loads(KEYS_FILE.read_text(encoding="utf-8"))["keys"]

    failed = False
    for alias, spec in specs.items():
        try:
            print(apply_key(gw, alias, spec, env, args.rotate))
        except (RuntimeError, urllib.error.URLError) as e:
            print(f"ERROR    {e}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
