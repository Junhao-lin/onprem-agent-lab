"""Per-app virtual keys and limits (task 1.5).

Limit enforcement is proven with disposable keys (tmp_key fixture) that have
tiny limits; the real app keys are only read, never modified.
"""
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request

import pytest

from conftest import REPO, TMP_PREFIX, load_env, mask, redis_cli

SPECS = tomllib.loads((REPO / "infra/litellm/virtual-keys.toml").read_text(encoding="utf-8"))["keys"]
LIMIT_FIELDS = ("models", "rpm_limit", "tpm_limit", "max_parallel_requests")


def load_bootstrap():
    spec = importlib.util.spec_from_file_location("bootstrap_keys", REPO / "scripts/bootstrap_keys.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("alias", SPECS)
def test_app_key_matches_limits_as_code(env, gateway, alias):
    spec = SPECS[alias]
    key = env[spec["env_var"]]
    r = gateway.request("GET", "/key/info", query={"key": key})
    assert r.status == 200, f"{alias} key {mask(key)} not found"
    info = r.body["info"]
    assert info["key_alias"] == alias
    assert {f: info[f] for f in LIMIT_FIELDS} == {f: spec[f] for f in LIMIT_FIELDS}


@pytest.mark.parametrize("alias", SPECS)
def test_app_alias_unique(env, gateway, alias):
    """Exactly one key carries the alias, and it is the key stored in .env."""
    r = gateway.request("GET", "/key/list",
                        query={"key_alias": alias, "return_full_object": "true"})
    assert r.status == 200
    keys = r.body["keys"]
    assert [k["key_alias"] for k in keys] == [alias], [k["key_alias"] for k in keys]
    expected_token = hashlib.sha256(env[SPECS[alias]["env_var"]].encode()).hexdigest()
    assert keys[0]["token"] == expected_token, f"{alias}: listed key is not the one in .env"


def test_parallel_budget_matches_ollama_capacity(env):
    total = sum(s["max_parallel_requests"] for s in SPECS.values())
    assert total == int(env.get("OLLAMA_NUM_PARALLEL", "4"))


@pytest.mark.llm
def test_model_allow_lists(env, gateway):
    rag, agent = env["SUPPORT_RAG_LLM_KEY"], env["ONBOARDING_AGENT_LLM_KEY"]
    assert gateway.chat(rag).status == 200
    assert gateway.embed(rag, "test").status == 200
    assert gateway.chat(agent).status == 200
    assert gateway.embed(agent, "test").status in (401, 403)
    r = gateway.request("GET", "/v1/models", key=agent)
    assert [m["id"] for m in r.body["data"]] == ["chat-default"]


@pytest.mark.llm
def test_rpm_limit(gateway, tmp_key):
    k = tmp_key("rpm", rpm_limit=2)
    assert [gateway.chat(k).status for _ in range(3)] == [200, 200, 429]


@pytest.mark.llm
def test_tpm_limit(gateway, tmp_key):
    k = tmp_key("tpm", tpm_limit=60)
    codes = []
    for _ in range(4):
        codes.append(gateway.chat(k, "用三句話介紹網路攝影機", max_tokens=30).status)
        if codes[-1] == 429:
            break
    # Only 200/429 allowed: one or more 200s, then exactly one terminating 429.
    assert set(codes) <= {200, 429}, codes
    assert codes[-1] == 429 and codes.count(429) == 1 and len(codes) >= 2, codes


def open_stream(gateway, key: str):
    """Start a long streaming chat and return the open response once the first
    content chunk has arrived, i.e. the request is provably in flight and
    holds one parallel slot until the stream ends."""
    req = urllib.request.Request(gateway.base + "/v1/chat/completions", method="POST",
                                 data=json.dumps({
                                     "model": "chat-default", "stream": True, "max_tokens": 400,
                                     "temperature": 0,
                                     "messages": [{"role": "user", "content":
                                                   "請詳細介紹網路攝影機的十個功能，每個功能寫一段。"}]}).encode())
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as e:
        return e.code, None
    for raw in resp:
        line = raw.decode().strip()
        if line.startswith("data:") and line != "data: [DONE]" and \
                json.loads(line[5:])["choices"][0]["delta"].get("content"):
            return resp.status, resp
    raise AssertionError("stream ended before first content chunk")


def drain(resp) -> None:
    for raw in resp:
        if raw.decode().strip() == "data: [DONE]":
            break
    resp.close()


@pytest.mark.llm
def test_parallel_limit(gateway, tmp_key):
    """Deterministic: hold N slots with open streams, so request N+1 must be 429;
    after the streams finish, a new request must be 200 again.

    The earlier version fired 4 requests at once and accepted any mix with
    a 200 and a 429, which depended on thread timing. Holding the slots with
    in-flight streams removes the race instead of loosening the assertion."""
    limit = 2
    k = tmp_key("parallel", max_parallel_requests=limit, rpm_limit=100)
    held, codes = [], []
    try:
        for _ in range(limit):                       # requests 1..N: occupy slots
            status, resp = open_stream(gateway, k)
            codes.append(status)
            if resp:
                held.append(resp)
        codes.append(gateway.chat(k).status)         # request N+1: over the limit
    finally:
        for resp in held:
            drain(resp)
    assert set(codes) <= {200, 429}, codes
    assert codes == [200] * limit + [429], codes

    time.sleep(1)  # fixed settle time for the async slot release after stream end
    assert gateway.chat(k).status == 200, "slot not released after streams finished"


@pytest.mark.llm
def test_limiter_counters_in_redis(gateway, tmp_key):
    k = tmp_key("redis", rpm_limit=100)
    assert gateway.chat(k).status == 200
    hashed = hashlib.sha256(k.encode()).hexdigest()
    keys = redis_cli("--scan", "--pattern", f"*{hashed}*").stdout.split()
    assert any(x.endswith(":requests") for x in keys), "no rpm counter for this key in Redis"


@pytest.mark.llm
def test_responses_not_cached_by_default(env, gateway):
    rag = env["SUPPORT_RAG_LLM_KEY"]
    a = gateway.chat(rag, "cache probe", max_tokens=5)
    b = gateway.chat(rag, "cache probe", max_tokens=5)
    assert a.status == b.status == 200
    assert a.body["id"] != b.body["id"]
    assert str(b.headers.get("x-litellm-cache-hit", "")).lower() != "true"


def test_bootstrap_rerun_keeps_env_and_masks_output():
    """1.5 pending: rerun is idempotent; output shows only sk-…last4, never full keys."""
    env_path = REPO / ".env"
    before = hashlib.sha256(env_path.read_bytes()).hexdigest()
    proc = subprocess.run([sys.executable, "-I", "scripts/bootstrap_keys.py"], cwd=REPO,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert hashlib.sha256(env_path.read_bytes()).hexdigest() == before

    env = load_env(env_path)
    output = proc.stdout + proc.stderr
    for alias, spec in SPECS.items():
        key = env[spec["env_var"]]
        assert key not in output, f"full key for {alias} leaked"
        assert key[3:-4] not in output, f"key body for {alias} leaked"
        assert f"key={mask(key)}" in output, f"{alias} not masked as sk-…last4"
    shown = re.findall(r"key=(\S+)", output)
    assert shown and all(re.fullmatch(r"sk-…[A-Za-z0-9_-]{4}", s) for s in shown), shown


def test_bootstrap_replaces_orphan_alias(gateway, tmp_path):
    bk = load_bootstrap()
    fake_env = tmp_path / ".env"
    fake_env.write_text("OTHER=keep\nTMP_KEY=\n", encoding="utf-8")
    bk.ENV_FILE = fake_env
    alias = f"{TMP_PREFIX}orphan"
    spec = {"env_var": "TMP_KEY", "models": ["chat-default"], "rpm_limit": 5,
            "tpm_limit": 500, "max_parallel_requests": 1}
    try:
        # Precondition: an orphan key with this alias really exists.
        orphan = gateway.request("POST", "/key/generate",
                                 body={"key_alias": alias, "models": ["chat-default"]})
        assert orphan.status == 200 and orphan.body.get("key"), f"orphan setup failed: {orphan.status}"
        orphan_key = orphan.body["key"]
        assert gateway.request("GET", "/key/info", query={"key": orphan_key}).status == 200

        gw = bk.Gateway(gateway.base, gateway.master_key)
        r1 = bk.apply_key(gw, alias, spec, bk.load_env(fake_env), rotate=False)
        k1 = bk.load_env(fake_env)["TMP_KEY"]
        r2 = bk.apply_key(gw, alias, spec, bk.load_env(fake_env), rotate=False)
        e = bk.load_env(fake_env)
        assert r1.startswith("created") and r2.startswith("updated")
        assert e["TMP_KEY"] == k1 and e["OTHER"] == "keep"
        # The orphan was deleted (not just shadowed) and replaced by a different key.
        assert k1 != orphan_key
        assert gateway.request("GET", "/key/info", query={"key": orphan_key}).status != 200
        listed = gateway.request("GET", "/key/list",
                                 query={"key_alias": alias, "return_full_object": "true"}).body["keys"]
        assert [x["token"] for x in listed] == [hashlib.sha256(k1.encode()).hexdigest()]
    finally:
        gateway.request("POST", "/key/delete", body={"key_aliases": [alias]})
