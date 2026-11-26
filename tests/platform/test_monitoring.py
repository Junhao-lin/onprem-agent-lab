"""Prometheus + Grafana (task 1.8).

Prometheus is internal-only, so it is queried through the in-network probe.
Grafana is on 127.0.0.1 and is called directly with the admin credentials.
"""
import base64
import hashlib
import re
import time
import urllib.parse

import pytest

from conftest import REPO, compose, http, inspect, probe

PROM = "http://prometheus:9090"
EXPECTED_JOBS = {"prometheus", "litellm", "qdrant"}


def prom(path: str, **query) -> dict:
    url = PROM + path + ("?" + urllib.parse.urlencode(query) if query else "")
    r = probe([{"url": url}])[0]
    assert r["status"] == 200, r
    return r["body"]


def wait_for(fn, timeout: float = 45, interval: float = 3):
    """Poll a state that only changes on the next scrape (15s interval)."""
    deadline = time.monotonic() + timeout
    while True:
        value = fn()
        if value or time.monotonic() > deadline:
            return value
        time.sleep(interval)


@pytest.fixture(scope="module")
def grafana(env):
    base = f"http://127.0.0.1:{env.get('GRAFANA_PORT', '3000')}"
    token = base64.b64encode(f"{env['GRAFANA_ADMIN_USER']}:{env['GRAFANA_ADMIN_PASSWORD']}".encode()).decode()
    auth = {"Authorization": f"Basic {token}"}

    def call(path, authed=True):
        return http("GET", base + path, headers=auth if authed else None, timeout=30)
    return call


# --- Prometheus -----------------------------------------------------------
def test_all_scrape_targets_up(stack_up, probe_image):
    def targets_up():
        active = prom("/api/v1/targets", state="active")["data"]["activeTargets"]
        status = {t["labels"]["job"]: (t["health"], t["lastError"]) for t in active}
        return status if set(status) == EXPECTED_JOBS and \
            all(h == "up" and not err for h, err in status.values()) else None

    status = wait_for(targets_up)
    assert status, prom("/api/v1/targets", state="active")["data"]["activeTargets"]


def test_qdrant_scrape_uses_secret_file(env, stack_up):
    """Qdrant /metrics needs the API key: provided as a compose secret file
    (copied into the container from .env), never inline in prometheus.yml."""
    cfg = (REPO / "infra/prometheus/prometheus.yml").read_text(encoding="utf-8")
    assert "credentials_file: /run/secrets/qdrant_api_key" in cfg
    assert not re.search(r"^\s*(credentials|password|bearer_token):", cfg, re.MULTILINE)
    # Compare hashes only; the key itself is never printed.
    out = compose("exec", "-T", "prometheus", "sha256sum", "/run/secrets/qdrant_api_key")
    assert out.returncode == 0, out.stderr
    assert out.stdout.split()[0] == hashlib.sha256(env["QDRANT_API_KEY"].encode()).hexdigest()


@pytest.mark.llm
def test_gateway_metrics_labelled_per_app(env, gateway, probe_image):
    """A request with the support-rag key shows up in Prometheus under its alias."""
    q = 'sum(litellm_proxy_total_requests_metric_total{api_key_alias="support-rag",status_code="200"})'

    def current() -> float:
        res = prom("/api/v1/query", query=q)["data"]["result"]
        return float(res[0]["value"][1]) if res else 0.0

    before = current()
    assert gateway.chat(env["SUPPORT_RAG_LLM_KEY"]).status == 200
    after = wait_for(lambda: current() > before and current())
    assert after and after > before, (before, after)


# --- Grafana --------------------------------------------------------------
def test_grafana_health(stack_up, grafana):
    r = grafana("/api/health", authed=False)
    assert r.status == 200 and r.body["database"] == "ok", r.body
    assert r.body["version"] == inspect("grafana")["Config"]["Image"].rsplit(":", 1)[1]


def test_grafana_requires_login(stack_up, grafana):
    assert grafana("/api/datasources", authed=False).status == 401


def test_grafana_datasource_provisioned(stack_up, grafana):
    r = grafana("/api/datasources")
    assert r.status == 200
    assert [(d["uid"], d["type"], d["url"], d["isDefault"], d["readOnly"]) for d in r.body] == \
        [("prometheus", "prometheus", "http://prometheus:9090", True, True)], r.body


def test_grafana_datasource_healthy(stack_up, grafana):
    r = grafana("/api/datasources/uid/prometheus/health")
    assert r.status == 200 and r.body["status"] == "OK", r.body


def test_grafana_phone_home_disabled(stack_up):
    env = dict(e.split("=", 1) for e in inspect("grafana")["Config"]["Env"])
    for k in ("GF_ANALYTICS_REPORTING_ENABLED", "GF_ANALYTICS_CHECK_FOR_UPDATES",
              "GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES", "GF_NEWS_NEWS_FEED_ENABLED",
              "GF_AUTH_ANONYMOUS_ENABLED", "GF_USERS_ALLOW_SIGN_UP"):
        assert env.get(k) == "false", k
