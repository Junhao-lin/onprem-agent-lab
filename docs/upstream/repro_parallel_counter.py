"""Reproduce the LiteLLM max_parallel_requests counter drift (issue draft:
docs/upstream/litellm-parallel-counter.md).

    python -I docs/upstream/repro_parallel_counter.py

Repo-specific harness: it needs this repo's running compose stack (LiteLLM proxy
on 127.0.0.1:$LITELLM_PORT, Redis as limiter store, aliases chat-default /
embed-default) and reads the master key from .env. Only masked keys are printed.

Two scenarios, each on its own disposable key (models=["chat-default"],
max_parallel_requests=2, alias pytest-tmp-repro-<scenario>-<ts>):
  A  requests for a model the key may not use -> 401; then the impact on the limit
  B  malformed request -> 400; then the impact on the limit
The counter is read straight from Redis,
    {api_key:<sha256(key)>}:max_parallel_requests
after polling until two consecutive reads agree (failure callbacks are async),
together with its TTL.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.gpu.yml",
           "--profile", "platform", "--profile", "monitoring"]
PREFIX = "pytest-tmp-repro-"   # swept by the test suite if ever left behind


def load_env() -> dict[str, str]:
    env = {}
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


ENV = load_env()
BASE = f"http://127.0.0.1:{ENV.get('LITELLM_PORT', '4000')}"
MASTER = ENV["LITELLM_MASTER_KEY"]
CHAT_OK = {"model": "chat-default", "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}


def call(path: str, key: str, body: dict | None = None, method: str = "POST") -> tuple[int, dict]:
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def redis(*args: str) -> str:
    return subprocess.run([*COMPOSE, "exec", "-T", "redis", "redis-cli", *args], cwd=REPO,
                          capture_output=True, text=True, encoding="utf-8").stdout.strip()


def counter_key(key: str) -> str:
    return "{api_key:%s}:max_parallel_requests" % hashlib.sha256(key.encode()).hexdigest()


def counter(key: str, settle_s: float = 5.0) -> tuple[str, str]:
    """(value, ttl) once two consecutive reads 0.3 s apart agree, or after settle_s."""
    k, deadline = counter_key(key), time.monotonic() + settle_s
    prev = redis("get", k) or "(nil)"
    while time.monotonic() < deadline:
        time.sleep(0.3)
        cur = redis("get", k) or "(nil)"
        if cur == prev:
            break
        prev = cur
    return prev, redis("ttl", k)


def step(label: str, status, key: str) -> str:
    value, ttl = counter(key)
    print(f"{label:<62} HTTP {status if status is not None else '-':<4} counter = {value:<5} ttl = {ttl}s")
    return value


def hold_streams(key: str, n: int) -> list[int]:
    """Open n long streaming requests one after another, each held open until its
    first content token, so all accepted ones are in flight at once; then drain."""
    body = json.dumps({"model": "chat-default", "stream": True, "max_tokens": 200,
                       "messages": [{"role": "user", "content": "請詳細介紹網路攝影機的十個功能。"}]}).encode()
    held, statuses = [], []
    try:
        for _ in range(n):
            req = urllib.request.Request(BASE + "/v1/chat/completions", method="POST", data=body)
            req.add_header("Authorization", f"Bearer {key}")
            req.add_header("Content-Type", "application/json")
            try:
                resp = urllib.request.urlopen(req, timeout=120)
            except urllib.error.HTTPError as e:
                statuses.append(e.code)
                continue
            statuses.append(resp.status)
            held.append(resp)
            for raw in resp:                     # wait until it is really generating
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("data:") and line != "data: [DONE]" and \
                        (json.loads(line[5:]).get("choices") or [{}])[0].get("delta", {}).get("content"):
                    break
    finally:
        for resp in held:
            for _ in resp:
                pass
            resp.close()
    return statuses


class TempKey:
    """Disposable key; deletion is verified, failure is reported (never raised)."""

    def __init__(self, scenario: str):
        self.alias = f"{PREFIX}{scenario}-{int(time.time() * 1000)}"
        self.key = None

    def __enter__(self) -> "TempKey":
        try:
            status, body = call("/key/generate", MASTER, {
                "key_alias": self.alias, "models": ["chat-default"], "max_parallel_requests": 2})
            if status != 200:
                raise RuntimeError(f"/key/generate failed: HTTP {status}")
            self.key = body["key"]
        except BaseException:
            self.delete()
            raise
        print(f"key {self.alias} (sk-…{self.key[-4:]}): models=['chat-default'], max_parallel_requests=2")
        return self

    def delete(self) -> bool:
        try:
            call("/key/delete", MASTER, {"key_aliases": [self.alias]})
            status, body = call("/key/list?" + urllib.parse.urlencode({"key_alias": self.alias}),
                                MASTER, method="GET")
            return status == 200 and body.get("keys") == []
        except Exception:
            return False

    def __exit__(self, *exc) -> None:
        if not self.delete():
            print(f"WARNING: temporary key {self.alias} may still exist; delete it via /key/delete",
                  file=sys.stderr)


def scenario_a() -> None:
    print("\n=== A: requests for a model the key is not allowed to use (401) ===")
    with TempKey("a") as k:
        step("A0. fresh key", None, k.key)
        s, _ = call("/v1/chat/completions", k.key, CHAT_OK)
        step("A1. allowed chat completion (expect 0)", s, k.key)
        for i in range(2):
            s, _ = call("/v1/embeddings", k.key, {"model": "embed-default", "input": "t"})
            step(f"A2.{i + 1} /v1/embeddings, model not allowed -> 401 (expect 0)", s, k.key)
        s, _ = call("/v1/chat/completions", k.key, {**CHAT_OK, "model": "embed-default"})
        step("A3. /v1/chat/completions, model not allowed -> 401 (expect 0)", s, k.key)
        print("A4. impact: open 3 concurrent streams on this key (limit 2)")
        print(f"    statuses: {hold_streams(k.key, 3)}  (a correct limiter answers the 3rd with 429)")
        step("A5. after the streams finished", None, k.key)


def scenario_b() -> None:
    print("\n=== B: malformed request rejected in a pre-call hook (400) ===")
    with TempKey("b") as k:
        step("B0. fresh key", None, k.key)
        s, _ = call("/v1/chat/completions", k.key, CHAT_OK)
        step("B1. allowed chat completion (expect 0)", s, k.key)
        for i in range(2):
            s, _ = call("/v1/chat/completions", k.key, {**CHAT_OK, "messages": ["not-an-object"]})
            step(f"B2.{i + 1} messages is a list of strings -> 400 (expect 0)", s, k.key)
        s, _ = call("/v1/chat/completions", k.key, CHAT_OK)
        step("B3. impact: one allowed chat, nothing in flight (expect 200)", s, k.key)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"run {time.strftime('%Y-%m-%d %H:%M:%S')} against {BASE}")
    status, health = call("/health/readiness", MASTER, method="GET")
    print(f"litellm version: {health.get('litellm_version', '?')}")
    scenario_a()
    scenario_b()
    return 0


if __name__ == "__main__":
    sys.exit(main())
