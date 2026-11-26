"""Draft verification for task 1.5 (per-app virtual keys + limits). Never prints secrets.

Uses temporary keys (alias prefix "verify-tmp-") with tiny limits to prove the
gateway enforces rpm / tpm / parallel limits, then deletes them. App keys are
only read, not modified. To be rewritten as pytest in task 1.7.

    python -I tests/platform/_drafts/verify_1_5.py
"""
import concurrent.futures as cf
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parents[3]
TMP_PREFIX = "verify-tmp-"

env = {}
for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k] = v
BASE = f"http://127.0.0.1:{env.get('LITELLM_PORT', '4000')}"
MASTER = env["LITELLM_MASTER_KEY"]
SPECS = tomllib.loads((REPO / "infra/litellm/virtual-keys.toml").read_text(encoding="utf-8"))["keys"]
results = []


def call(method, path, key=MASTER, body=None, query=None, timeout=120):
    url = BASE + path + ("?" + urllib.parse.urlencode(query) if query else "")
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {key}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw[:1] in (b"{", b"[") else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw[:200].decode(errors="replace")}


def check(name, ok, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def chat(key, max_tokens=1, content="hi"):
    return call("POST", "/v1/chat/completions", key=key, body={
        "model": "chat-default", "max_tokens": max_tokens, "temperature": 0,
        "messages": [{"role": "user", "content": content}]})


def tmp_key(name, **limits):
    s, b = call("POST", "/key/generate", body={
        "key_alias": TMP_PREFIX + name, "models": ["chat-default"], **limits})
    assert s == 200, (s, b)
    return b["key"]


def err_msg(body):
    e = body.get("error", body)
    return str(e.get("message", e) if isinstance(e, dict) else e)[:90]


try:
    # --- 1. app keys match limits-as-code, aliases unique -----------------
    for alias, spec in SPECS.items():
        key = env.get(spec["env_var"], "")
        s, b = call("GET", "/key/info", query={"key": key})
        info = b.get("info", {}) if s == 200 else {}
        got = {f: info.get(f) for f in ("models", "rpm_limit", "tpm_limit", "max_parallel_requests")}
        want = {f: spec[f] for f in got}
        check(f"{alias}: limits match virtual-keys.toml", info.get("key_alias") == alias and got == want, str(got))
        s, b = call("GET", "/key/list", query={"key_alias": alias})
        check(f"{alias}: alias is unique", s == 200 and len(b.get("keys", [])) == 1, f"count={len(b.get('keys', []))}")

    # --- 2. model allow-lists ---------------------------------------------
    rag, agent = env["SUPPORT_RAG_LLM_KEY"], env["ONBOARDING_AGENT_LLM_KEY"]
    s, _ = chat(rag)
    check("support-rag -> chat-default 200", s == 200, f"got {s}")
    s, b = call("POST", "/v1/embeddings", key=rag, body={"model": "embed-default", "input": "test"})
    check("support-rag -> embed-default 200", s == 200, f"got {s}")
    s, _ = chat(agent)
    check("onboarding-agent -> chat-default 200", s == 200, f"got {s}")
    s, b = call("POST", "/v1/embeddings", key=agent, body={"model": "embed-default", "input": "test"})
    check("onboarding-agent -> embed-default denied", s in (401, 403), f"got {s}: {err_msg(b)}")
    s, b = call("GET", "/v1/models", key=agent)
    ids = sorted(m["id"] for m in b.get("data", []))
    check("onboarding-agent /v1/models shows only allowed", ids == ["chat-default"], str(ids))

    # --- 3. rpm limit -----------------------------------------------------
    k = tmp_key("rpm", rpm_limit=2)
    codes = [chat(k)[0] for _ in range(3)]
    check("rpm_limit=2: 3rd request -> 429", codes[:2] == [200, 200] and codes[2] == 429, str(codes))

    # --- 4. tpm limit -----------------------------------------------------
    k = tmp_key("tpm", tpm_limit=60)
    codes = []
    for _ in range(4):
        s, b = chat(k, max_tokens=30, content="用三句話介紹網路攝影機")
        codes.append(s)
        if s == 429:
            break
    check("tpm_limit=60: blocked once tokens exceed budget", codes[0] == 200 and codes[-1] == 429, str(codes))

    # --- 5. max_parallel_requests -----------------------------------------
    k = tmp_key("parallel", max_parallel_requests=1)
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        codes = sorted(pool.map(lambda _: chat(k, max_tokens=64, content="寫一段 50 字的產品介紹")[0], range(4)))
    check("max_parallel_requests=1: concurrent extras -> 429",
          200 in codes and 429 in codes, str(codes))

    # --- 6. limiter state lives in Redis; responses NOT cached ------------
    req = urllib.request.Request(BASE + "/health/readiness")
    with urllib.request.urlopen(req, timeout=10) as r:
        cache = json.loads(r.read()).get("cache")
    check("readiness reports cache=redis", cache == "redis", f"cache={cache}")

    def raw_chat(key):
        req = urllib.request.Request(BASE + "/v1/chat/completions", method="POST", data=json.dumps({
            "model": "chat-default", "max_tokens": 5, "temperature": 0,
            "messages": [{"role": "user", "content": "cache probe"}]}).encode())
        req.add_header("Authorization", f"Bearer {key}")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())["id"], r.headers.get("x-litellm-cache-hit")
    (id1, hit1), (id2, hit2) = raw_chat(rag), raw_chat(rag)
    check("identical requests not served from cache (default_off)",
          id1 != id2 and str(hit2).lower() != "true", f"ids_differ={id1 != id2} cache_hit={hit2}")

    out = subprocess.run(["docker", "compose", "exec", "-T", "redis", "redis-cli", "dbsize"],
                         cwd=REPO, capture_output=True, text=True).stdout.strip()
    check("rate-limit counters present in Redis", out.isdigit() and int(out) > 0, f"dbsize={out}")

    # --- 7. bootstrap: orphan alias replaced, rerun is idempotent ---------
    spec = importlib.util.spec_from_file_location("bootstrap_keys", REPO / "scripts/bootstrap_keys.py")
    bk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bk)
    with tempfile.TemporaryDirectory() as td:
        fake_env = Path(td) / ".env"
        fake_env.write_text("OTHER=keep\nTMP_KEY=\n", encoding="utf-8")
        bk.ENV_FILE = fake_env
        alias = TMP_PREFIX + "orphan"
        call("POST", "/key/generate", body={"key_alias": alias, "models": ["chat-default"]})  # value discarded
        gw = bk.Gateway(BASE, MASTER)
        sp = {"env_var": "TMP_KEY", "models": ["chat-default"], "rpm_limit": 5,
              "tpm_limit": 500, "max_parallel_requests": 1}
        e = bk.load_env(fake_env)
        r1 = bk.apply_key(gw, alias, sp, e, rotate=False)
        k1 = bk.load_env(fake_env)["TMP_KEY"]
        r2 = bk.apply_key(gw, alias, sp, bk.load_env(fake_env), rotate=False)
        k2 = bk.load_env(fake_env)["TMP_KEY"]
        s, b = call("GET", "/key/list", query={"key_alias": alias})
        check("bootstrap replaces orphan alias, then updates in place",
              r1.startswith("created") and r2.startswith("updated") and k1 == k2
              and len(b.get("keys", [])) == 1 and bk.load_env(fake_env)["OTHER"] == "keep",
              f"run1={r1.split()[0]} run2={r2.split()[0]} same_key={k1 == k2} alias_count={len(b.get('keys', []))}")
finally:
    s, b = call("GET", "/key/list", query={"size": 100, "return_full_object": "true"})
    tmp = [x["key_alias"] for x in b.get("keys", []) if str(x.get("key_alias", "")).startswith(TMP_PREFIX)]
    if tmp:
        call("POST", "/key/delete", body={"key_aliases": tmp})
    print(f"cleanup: deleted {len(tmp)} temp keys")

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
