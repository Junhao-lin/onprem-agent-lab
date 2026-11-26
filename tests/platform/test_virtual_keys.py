"""Per-app virtual keys and limits (task 1.5).

Limit enforcement is proven with disposable keys (tmp_key fixture) that have
tiny limits; the real app keys are only read, never modified.
"""
import concurrent.futures as cf
import hashlib
import importlib.util
import re
import subprocess
import sys
import tomllib

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
def test_app_alias_unique(gateway, alias):
    r = gateway.request("GET", "/key/list", query={"key_alias": alias})
    assert len(r.body["keys"]) == 1


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
    assert codes[0] == 200 and codes[-1] == 429, codes


@pytest.mark.llm
def test_parallel_limit(gateway, tmp_key):
    k = tmp_key("parallel", max_parallel_requests=1)
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(pool.map(lambda _: gateway.chat(k, "寫一段 50 字的產品介紹", max_tokens=64).status,
                              range(4)))
    assert 200 in codes and 429 in codes, codes


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
        gateway.request("POST", "/key/generate", body={"key_alias": alias, "models": ["chat-default"]})
        gw = bk.Gateway(gateway.base, gateway.master_key)
        r1 = bk.apply_key(gw, alias, spec, bk.load_env(fake_env), rotate=False)
        k1 = bk.load_env(fake_env)["TMP_KEY"]
        r2 = bk.apply_key(gw, alias, spec, bk.load_env(fake_env), rotate=False)
        e = bk.load_env(fake_env)
        assert r1.startswith("created") and r2.startswith("updated")
        assert e["TMP_KEY"] == k1 and e["OTHER"] == "keep"
        assert len(gateway.request("GET", "/key/list", query={"key_alias": alias}).body["keys"]) == 1
    finally:
        gateway.request("POST", "/key/delete", body={"key_aliases": [alias]})
