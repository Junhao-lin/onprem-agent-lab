"""Reproduce the LiteLLM max_parallel_requests counter drift (issue draft:
docs/upstream/litellm-parallel-counter.md).

    python -I docs/upstream/repro_parallel_counter.py

Needs this repo's running stack (LiteLLM proxy on 127.0.0.1:$LITELLM_PORT with
Redis). Creates one disposable key `pytest-tmp-repro-counter`
(models=["chat-default"], max_parallel_requests=2), deletes it at the end, and
prints only masked keys. Reads the counter straight from Redis:
    {api_key:<sha256(key)>}:max_parallel_requests
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.gpu.yml",
           "--profile", "platform", "--profile", "monitoring"]
ALIAS = "pytest-tmp-repro-counter"   # swept by the test suite if left behind


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


def counter(key: str) -> str:
    k = "{api_key:%s}:max_parallel_requests" % hashlib.sha256(key.encode()).hexdigest()
    out = subprocess.run([*COMPOSE, "exec", "-T", "redis", "redis-cli", "get", k], cwd=REPO,
                         capture_output=True, text=True, encoding="utf-8").stdout.strip()
    return out or "(nil)"


def step(label: str, status: int | None, key: str) -> None:
    time.sleep(0.5)   # failure callbacks run asynchronously after the response
    print(f"{label:<58} HTTP {status if status is not None else '-':<4} counter = {counter(key)}")


def hold_streams(key: str, n: int) -> list[int]:
    """Open n long streaming requests one after another, each held open until its
    first content token, so all n are in flight at the same time; then drain."""
    body = json.dumps({"model": "chat-default", "stream": True, "max_tokens": 200,
                       "messages": [{"role": "user", "content": "請詳細介紹網路攝影機的十個功能。"}]}).encode()
    held, statuses = [], []
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
        for raw in resp:                     # wait until it is really generating
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("data:") and line != "data: [DONE]" and \
                    (json.loads(line[5:]).get("choices") or [{}])[0].get("delta", {}).get("content"):
                break
        held.append(resp)
    for resp in held:
        for _ in resp:
            pass
        resp.close()
    return statuses


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    master = ENV["LITELLM_MASTER_KEY"]
    call("/key/delete", master, {"key_aliases": [ALIAS]})
    status, body = call("/key/generate", master, {
        "key_alias": ALIAS, "models": ["chat-default"], "max_parallel_requests": 2})
    if status != 200:
        print(f"/key/generate failed: HTTP {status}")
        return 1
    key = body["key"]
    print(f"key {ALIAS} (sk-…{key[-4:]}): models=['chat-default'], max_parallel_requests=2\n")
    chat = {"model": "chat-default", "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}
    try:
        step("0. fresh key", None, key)
        s, _ = call("/v1/chat/completions", key, chat)
        step("1. allowed chat completion (expect counter back to 0)", s, key)
        for i in range(3):
            s, _ = call("/v1/embeddings", key, {"model": "embed-default", "input": "t"})
            step(f"2.{i + 1} model not allowed for key -> 401 (expect unchanged)", s, key)
        s, _ = call("/v1/chat/completions", key,
                    {"model": "chat-default", "max_tokens": 1, "messages": ["not-an-object"]})
        step("3. malformed messages -> 400 (expect unchanged)", s, key)
        s, _ = call("/v1/chat/completions", key, chat)
        step("4. allowed chat completion again", s, key)
        print(f"\n5. impact: open 3 concurrent streams on a key limited to 2 (counter now {counter(key)})")
        statuses = hold_streams(key, 3)
        print(f"   statuses: {statuses}  (a correct limiter answers the 3rd with 429)")
        step("6. after the streams finished", None, key)
    finally:
        call("/key/delete", master, {"key_aliases": [ALIAS]})
    return 0


if __name__ == "__main__":
    sys.exit(main())
