"""LiteLLM gateway (task 1.4)."""
import json
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


@pytest.mark.llm
def test_spend_log_increments(env, gateway):
    """1.4 pending: every request is persisted to Postgres (written async in batches)."""
    def count() -> int:
        return int(psql(env, 'select count(*) from "LiteLLM_SpendLogs"') or 0)

    before = count()
    assert gateway.chat(gateway.master_key).status == 200
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and count() <= before:
        time.sleep(1)
    assert count() > before
