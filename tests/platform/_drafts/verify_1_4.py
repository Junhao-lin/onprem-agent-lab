"""Draft verification for task 1.4 (LiteLLM gateway). Never prints secrets.

To be rewritten as pytest in task 1.7. Run from anywhere:
    python -I tests/platform/_drafts/verify_1_4.py
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # Windows console defaults to cp950

REPO = Path(__file__).resolve().parents[3]
env = {}
for line in open(REPO / ".env", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k] = v
BASE = f"http://127.0.0.1:{env.get('LITELLM_PORT', '4000')}"
MASTER = env["LITELLM_MASTER_KEY"]
results = []


def call(method, path, key=None, body=None, timeout=120):
    req = urllib.request.Request(BASE + path, method=method)
    if key is not None:
        req.add_header("Authorization", f"Bearer {key}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def check(name, ok, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def psql(sql):
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql",
         "-U", env["POSTGRES_USER"], "-d", env["POSTGRES_DB"], "-tAc", sql],
        cwd=REPO, capture_output=True, text=True)
    return out.stdout.strip()


# 1. readiness: DB + cache
s, b = call("GET", "/health/readiness")
r = json.loads(b)
check("readiness 200 & db connected", s == 200 and r.get("db") == "connected",
      f"status={r.get('status')} db={r.get('db')} cache={r.get('cache')} version={r.get('litellm_version')}")

# 2. auth enforced
s, _ = call("GET", "/v1/models")
check("no key -> 401", s == 401, f"got {s}")
s, _ = call("GET", "/v1/models", key="sk-wrong-key")
check("wrong key -> 401", s in (400, 401), f"got {s}")

# 3. model aliases exposed
s, b = call("GET", "/v1/models", key=MASTER)
ids = sorted(m["id"] for m in json.loads(b)["data"]) if s == 200 else []
check("models = chat-default, embed-default", ids == ["chat-default", "embed-default"], str(ids))

# 4. chat through gateway
before = psql('select count(*) from "LiteLLM_SpendLogs"') or "0"
s, b = call("POST", "/v1/chat/completions", key=MASTER, body={
    "model": "chat-default", "temperature": 0, "max_tokens": 30,
    "messages": [{"role": "user", "content": "用一句繁體中文說：你好"}]})
r = json.loads(b) if s == 200 else {}
check("chat-default 200 with usage", s == 200 and r.get("usage", {}).get("total_tokens", 0) > 0,
      f"status={s} reply={r.get('choices', [{}])[0].get('message', {}).get('content', '')!r} usage={r.get('usage', {}).get('total_tokens')}")

# 5. streaming through gateway
req = urllib.request.Request(BASE + "/v1/chat/completions", method="POST",
                             data=json.dumps({"model": "chat-default", "stream": True, "max_tokens": 20,
                                              "messages": [{"role": "user", "content": "數到五"}]}).encode())
req.add_header("Authorization", f"Bearer {MASTER}")
req.add_header("Content-Type", "application/json")
t0 = time.perf_counter(); ttft = None; chunks = 0; done = False
with urllib.request.urlopen(req, timeout=120) as resp:
    for raw in resp:
        line = raw.decode().strip()
        if not line.startswith("data:"):
            continue
        if line == "data: [DONE]":
            done = True
            break
        delta = json.loads(line[5:])["choices"][0]["delta"].get("content")
        if delta:
            chunks += 1
            ttft = ttft or (time.perf_counter() - t0)
check("streaming SSE works", done and chunks > 1, f"chunks={chunks} ttft={ttft:.3f}s" if ttft else "")

# 6. embeddings through gateway
s, b = call("POST", "/v1/embeddings", key=MASTER, body={"model": "embed-default", "input": "攝影機夜視功能"})
dim = len(json.loads(b)["data"][0]["embedding"]) if s == 200 else 0
check("embed-default 200, dim 1024", s == 200 and dim == 1024, f"status={s} dim={dim}")

# 7. spend logs persisted to Postgres (written async in batches)
after = before
for _ in range(15):
    after = psql('select count(*) from "LiteLLM_SpendLogs"') or "0"
    if int(after) > int(before):
        break
    time.sleep(2)
check("spend logs written to Postgres", int(after) > int(before), f"{before} -> {after}")

# 8. port binding: 127.0.0.1 only
out = subprocess.run(["docker", "compose", "port", "litellm", "4000"], cwd=REPO,
                     capture_output=True, text=True).stdout.strip()
check("4000 bound to 127.0.0.1 only", out.startswith("127.0.0.1:"), out)

# 9. no secrets in tracked config
cfg = (REPO / "infra" / "litellm" / "config.yaml").read_text(encoding="utf-8")
leaked = [k for k in ("LITELLM_MASTER_KEY", "LITELLM_SALT_KEY", "POSTGRES_PASSWORD", "REDIS_PASSWORD")
          if env.get(k) and env[k] in cfg]
check("no secret values in config.yaml", not leaked, ",".join(leaked))

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
