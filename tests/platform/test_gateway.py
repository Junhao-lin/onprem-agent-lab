"""LiteLLM gateway (task 1.4)."""
import hashlib
import json
import re
import time
import urllib.request

import pytest

from conftest import psql


def test_readiness(gateway):
    r = gateway.request("GET", "/health/readiness", key=None)
    assert r.status == 200
    assert r.body["db"] == "connected", r.body
    assert r.body["cache"] == "redis", r.body  # limiter counters backed by Redis (1.5 fix)


@pytest.mark.parametrize("key", [None, "sk-wrong-key-for-test"])
def test_rejects_missing_or_wrong_key(gateway, key):
    assert gateway.request("GET", "/v1/models", key=key).status == 401


def test_model_list_is_aliases_only(gateway):
    r = gateway.request("GET", "/v1/models")
    assert r.status == 200
    assert sorted(m["id"] for m in r.body["data"]) == ["chat-default", "embed-default"]


@pytest.mark.llm
def test_chat_returns_usage(gateway):
    r = gateway.chat(gateway.master_key, "用一句繁體中文說：你好", max_tokens=30)
    assert r.status == 200
    assert r.body["choices"][0]["message"]["content"].strip()
    assert r.body["usage"]["total_tokens"] > 0


@pytest.mark.llm
def test_chat_streaming(gateway):
    req = urllib.request.Request(gateway.base + "/v1/chat/completions", method="POST",
                                 data=json.dumps({"model": "chat-default", "stream": True,
                                                  "max_tokens": 20,
                                                  "messages": [{"role": "user", "content": "數到五"}]}).encode())
    req.add_header("Authorization", f"Bearer {gateway.master_key}")
    req.add_header("Content-Type", "application/json")
    chunks, done = 0, False
    with urllib.request.urlopen(req, timeout=120) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if line == "data: [DONE]":
                done = True
                break
            if line.startswith("data:") and json.loads(line[5:])["choices"][0]["delta"].get("content"):
                chunks += 1
    assert done and chunks > 1, (done, chunks)


@pytest.mark.llm
def test_embedding_dim_1024(gateway):
    """1.3 pending: bge-m3 dimension."""
    r = gateway.embed(gateway.master_key, "攝影機夜視功能")
    assert r.status == 200
    assert len(r.body["data"][0]["embedding"]) == 1024


def _chat_response_id(gateway, key: str, stream: bool, i: int) -> str:
    """Send one chat and return the response id (for a stream: the first chunk's id,
    which is what LiteLLM stores as the spend-log request_id)."""
    req = urllib.request.Request(gateway.base + "/v1/chat/completions", method="POST", data=json.dumps({
        "model": "chat-default", "max_tokens": 3, "temperature": 0, "stream": stream,
        "messages": [{"role": "user", "content": f"Say {i}."}]}).encode())
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as r:
        assert r.status == 200
        if not stream:
            return json.loads(r.read())["id"]
        first = ""
        for raw in r:
            line = raw.decode().strip()
            if line == "data: [DONE]":
                break
            if line.startswith("data: ") and not first:
                first = json.loads(line[6:])["id"]
        return first


@pytest.mark.llm
def test_every_chat_has_its_own_spend_log_row(env, gateway, tmp_key):
    """Every chat (streaming and not) is persisted to LiteLLM_SpendLogs under its own id.

    The earlier check ("total row count went up") passed even though most chats were
    silently dropped: with Ollama's OpenAI-compatible /v1, response ids are only
    "chatcmpl-<0..999>", LiteLLM uses the id as the spend-log primary key and inserts
    with skip_duplicates. Fixed by the ollama_chat provider (UUID ids); see
    reports/raw/spendlog/FINDINGS.md. A disposable key makes the rows attributable."""
    key = tmp_key("spendlog")
    hashed = hashlib.sha256(key.encode()).hexdigest()
    ids = [_chat_response_id(gateway, key, stream, i) for i in range(3) for stream in (False, True)]
    assert all(ids) and len(set(ids)) == len(ids), "response ids missing or not unique"
    short = [i for i in ids if re.fullmatch(r"chatcmpl-\d{1,4}", i)]
    assert short == [], f"short Ollama /v1 ids would collide in the spend log: {short}"

    def logged() -> set[str]:
        out = psql(env, f'select request_id from "LiteLLM_SpendLogs" '
                        f"where api_key = '{hashed}' and call_type = 'acompletion'")
        return set(out.split())

    deadline = time.monotonic() + 60          # spend logs are flushed asynchronously in batches
    while time.monotonic() < deadline and not set(ids) <= logged():
        time.sleep(2)
    rows = logged()
    missing = [i for i in ids if i not in rows]
    assert missing == [], f"{len(missing)}/{len(ids)} chats have no spend-log row"
    assert rows == set(ids)                   # and nothing else was logged for this key
