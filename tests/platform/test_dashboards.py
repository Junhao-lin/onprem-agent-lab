"""Grafana dashboards as code (task 1.9).

Queries run through Grafana's /api/ds/query, so Grafana itself expands
$__range / $__rate_interval exactly as the panels do; only the $app
template variable is substituted here.
"""
import base64
import hashlib
import json
import tomllib
import re
import subprocess
import sys
import time
import urllib.parse

import pytest

from conftest import REPO, http, probe, redis_cli

sys.path.insert(0, str(REPO / "infra" / "grafana"))
import build_dashboards as bd  # noqa: E402

DASH = json.loads((REPO / "infra/grafana/dashboards/platform-overview.json").read_text(encoding="utf-8"))
PANELS = [p for p in DASH["panels"] if p["type"] != "row"]
APP_VAR = next(v for v in DASH["templating"]["list"] if v["name"] == "app")
REAL_APPS = list(bd.APP_COLORS)
STATUS = {bd.GOOD, bd.WARNING, bd.SERIOUS, bd.CRITICAL}
SPECS_PARALLEL = {a: s["max_parallel_requests"] for a, s in tomllib.loads(
    (REPO / "infra/litellm/virtual-keys.toml").read_text(encoding="utf-8"))["keys"].items()}


@pytest.fixture(scope="module")
def grafana(env):
    base = f"http://127.0.0.1:{env.get('GRAFANA_PORT', '3000')}"
    token = base64.b64encode(f"{env['GRAFANA_ADMIN_USER']}:{env['GRAFANA_ADMIN_PASSWORD']}".encode()).decode()
    headers = {"Authorization": f"Basic {token}"}

    def call(method, path, body=None):
        return http(method, base + path, headers=headers, body=body, timeout=60)
    return call


def ds_query(grafana, expr: str, minutes: int = 60) -> dict:
    expr = expr.replace("$app", "|".join(REAL_APPS))
    now = int(time.time() * 1000)
    r = grafana("POST", "/api/ds/query", {
        "from": str(now - minutes * 60_000), "to": str(now),
        "queries": [{"refId": "A", "datasource": bd.DS, "expr": expr,
                     "range": True, "instant": False, "intervalMs": 15000, "maxDataPoints": 200}]})
    assert r.status == 200, (expr, r.status, r.body)
    return r.body["results"]["A"]


# --- as-code hygiene --------------------------------------------------------
def test_committed_json_matches_generator():
    proc = subprocess.run([sys.executable, "-I", "infra/grafana/build_dashboards.py", "--check"],
                          cwd=REPO, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_dashboard_provisioned(stack_up, grafana):
    r = grafana("GET", "/api/dashboards/uid/platform-overview")
    assert r.status == 200, r.status
    meta = r.body["meta"]
    assert meta["provisioned"] is True and meta["folderTitle"] == "onprem-agent-lab", meta
    assert r.body["dashboard"]["title"] == DASH["title"]
    loaded = {p["title"]: [t["expr"] for t in p.get("targets", [])]
              for p in r.body["dashboard"]["panels"] if p["type"] != "row"}
    committed = {p["title"]: [t["expr"] for t in p["targets"]] for p in PANELS}
    assert loaded == committed, ("Grafana serves a stale dashboard; run "
                                 "python infra/grafana/build_dashboards.py --reload")


# --- every query is valid PromQL through Grafana ------------------------------
@pytest.mark.parametrize("panel", PANELS, ids=lambda p: p["title"])
def test_panel_queries_execute(stack_up, grafana, panel):
    for t in panel["targets"]:
        res = ds_query(grafana, t["expr"])
        assert res.get("status", 200) == 200 and not res.get("error"), (t["expr"], res.get("error"))


@pytest.mark.llm
def test_per_app_panel_shows_live_traffic(env, gateway, grafana):
    """A NEW support-rag request is counted (counter increases through Grafana),
    and the panel shows support-rag as its own series without test/master traffic."""
    panel = next(p for p in PANELS if p["title"] == "Requests / s by app")
    counter = f'sum({bd.REQ}{{api_key_alias="support-rag"}})'

    def latest(expr) -> float:
        frames = ds_query(grafana, expr, minutes=15).get("frames", [])
        vals = [v for f in frames for v in f["data"]["values"][1] if v is not None] if frames else []
        return vals[-1] if vals else 0.0

    before = latest(counter)
    assert gateway.chat(env["SUPPORT_RAG_LLM_KEY"]).status == 200
    deadline = time.monotonic() + 45
    after = latest(counter)
    while after <= before and time.monotonic() < deadline:
        time.sleep(3)
        after = latest(counter)
    assert after > before, f"new request not visible via Grafana: {before} -> {after}"

    def series_names():
        frames = ds_query(grafana, panel["targets"][0]["expr"], minutes=15).get("frames", [])
        names = set()
        for f in frames:
            for field in f["schema"]["fields"]:
                if field.get("labels", {}).get("api_key_alias"):
                    names.add(field["labels"]["api_key_alias"])
        return names

    deadline = time.monotonic() + 45
    names = series_names()
    while "support-rag" not in names and time.monotonic() < deadline:
        time.sleep(3)
        names = series_names()
    assert "support-rag" in names, names
    assert not [n for n in names if n.startswith(("pytest-tmp-", "loadtest-")) or n == "None"], names


# --- app variable ---------------------------------------------------------------
def test_app_variable_hides_test_and_master_traffic(stack_up, probe_image):
    values = probe([{"url": "http://prometheus:9090/api/v1/label/api_key_alias/values?"
                            + urllib.parse.urlencode({"match[]": bd.REQ})}])[0]["body"]["data"]
    pattern = re.compile(APP_VAR["regex"].strip("/"))
    kept = sorted(v for v in values if pattern.search(v))
    assert set(kept) <= set(REAL_APPS), kept
    for v in ["pytest-tmp-rpm", "None", "pytest-tmp-parallel", "loadtest-1795698642"]:
        assert not pattern.search(v), v
    for v in REAL_APPS:
        assert pattern.search(v), v


# --- design rules ---------------------------------------------------------------
PER_APP = [p for p in PANELS if p["type"] == "timeseries"
           and any("{{api_key_alias}}" in t["legendFormat"] for t in p["targets"])]


def test_per_app_panels_exist():
    assert len(PER_APP) >= 5, [p["title"] for p in PER_APP]


@pytest.mark.parametrize("panel", PER_APP, ids=lambda p: p["title"])
def test_app_colors_fixed_per_entity(panel):
    """Colour follows the app: same fixed colour in every per-app panel."""
    got = {o["matcher"]["options"]: o["properties"][0]["value"]["fixedColor"]
           for o in panel["fieldConfig"]["overrides"] if o["matcher"]["id"] == "byName"}
    assert got == bd.APP_COLORS, got


def test_app_colors_never_status_colors():
    assert not set(bd.APP_COLORS.values()) & STATUS


@pytest.mark.parametrize("panel", [p for p in PANELS if p["type"] == "timeseries"], ids=lambda p: p["title"])
def test_single_axis_and_legend(panel):
    """No dual y-axis; legend always visible so identity is never colour-only."""
    for o in panel["fieldConfig"]["overrides"]:
        for prop in o["properties"]:
            assert prop["id"] not in ("custom.axisPlacement", "unit"), (panel["title"], prop)
    assert panel["fieldConfig"]["defaults"]["custom"]["axisPlacement"] == "auto"
    assert panel["options"]["legend"]["showLegend"] is True


def test_error_panel_uses_reserved_status_colors():
    panel = next(p for p in PANELS if p["title"] == "Failed requests / s by status")
    colors = {o["properties"][0]["value"]["fixedColor"] for o in panel["fieldConfig"]["overrides"]}
    assert colors <= STATUS and bd.WARNING in colors and bd.CRITICAL in colors, colors


# --- 1.9 visual-review follow-ups ---------------------------------------------
def instant(grafana, expr: str) -> float:
    """Latest value of an expression via Grafana (0.0 if no data).
    An empty result comes back as a frame with a schema but no value columns."""
    vals = []
    for f in ds_query(grafana, expr, minutes=15).get("frames", []):
        cols = f.get("data", {}).get("values", [])
        if len(cols) >= 2:
            vals += [v for v in cols[1] if v is not None]
    return vals[-1] if vals else 0.0


def instant_at(grafana, expr: str, ts: float) -> float:
    """Value of an expression evaluated at one timestamp, through Grafana's datasource."""
    ms = int(ts * 1000)
    r = grafana("POST", "/api/ds/query", {
        "from": str(ms), "to": str(ms),
        "queries": [{"refId": "A", "datasource": bd.DS, "expr": expr.replace("$app", "|".join(REAL_APPS)),
                     "range": False, "instant": True}]})
    assert r.status == 200, (expr, r.status, r.body)
    vals = [v for f in r.body["results"]["A"].get("frames", [])
            for v in (f.get("data", {}).get("values", [[], []]) + [[]])[1] if v is not None]
    assert len(vals) == 1, (expr, vals)
    return vals[0]


def panel_expr(title: str) -> str:
    return next(p for p in PANELS if p["title"] == title)["targets"][0]["expr"]


def wait_increase(grafana, expr: str, before: float, timeout: float = 45) -> float:
    deadline, after = time.monotonic() + timeout, instant(grafana, expr)
    while after <= before and time.monotonic() < deadline:
        time.sleep(3)
        after = instant(grafana, expr)
    return after


def twice_across_scrape(grafana, action, counter: str) -> None:
    """Run `action` twice with a scrape in between. rate()/increase() cannot see
    the first sample of a brand-new series, so panels need two observed points."""
    for _ in range(2):
        before = instant(grafana, counter)
        action()
        assert wait_increase(grafana, counter, before) > before, f"not scraped: {counter}"


def hold_slots_then_overflow(gateway, key: str, slots: int) -> list[int]:
    from test_virtual_keys import drain, open_stream

    held, codes = [], []
    try:
        for _ in range(slots):
            status, resp = open_stream(gateway, key)
            codes.append(status)
            if resp:
                held.append(resp)
        codes.append(gateway.chat(key).status)
    finally:
        for resp in held:
            drain(resp)
    return codes


@pytest.mark.llm
def test_real_app_error_shows_in_failure_panels(env, gateway, grafana):
    """A metered error from a REAL app key (not pytest-tmp-*) reaches the panels.

    Auth-stage 401s are not metered (test_auth_rejections_are_not_metered), so the
    error is a 429 from support-rag's own parallel limit: hold 2 slots, send a 3rd.
    support-rag is used because no test sends it auth-rejected requests, which
    skew the limiter counter (see test_auth_rejection_does_not_skew_parallel_counter)."""
    key = env["SUPPORT_RAG_LLM_KEY"]
    slots = SPECS_PARALLEL["support-rag"]
    counter = f'sum({bd.FAIL}{{api_key_alias="support-rag",exception_status="429"}})'

    def overflow():
        assert hold_slots_then_overflow(gateway, key, slots) == [200] * slots + [429]
    twice_across_scrape(grafana, overflow, counter)

    frames = ds_query(grafana, panel_expr("Failed requests / s by status"), minutes=15).get("frames", [])
    statuses = {fld.get("labels", {}).get("exception_status") for f in frames for fld in f["schema"]["fields"]}
    assert "429" in statuses, statuses
    assert instant(grafana, panel_expr("Error rate").replace("$__range", "15m")) > 0


@pytest.mark.llm
def test_app_streaming_shows_in_ttft_panels(env, gateway, grafana):
    """TTFT is only reported for streaming requests: support-rag streams fill the panels."""
    from test_virtual_keys import drain, open_stream

    counter = 'sum(litellm_llm_api_time_to_first_token_metric_count{api_key_alias="support-rag"})'

    def stream():
        status, resp = open_stream(gateway, env["SUPPORT_RAG_LLM_KEY"])
        assert status == 200
        drain(resp)
    twice_across_scrape(grafana, stream, counter)

    frames = ds_query(grafana, panel_expr("p95 time to first token"), minutes=15).get("frames", [])
    aliases = {fld.get("labels", {}).get("api_key_alias") for f in frames for fld in f["schema"]["fields"]}
    assert "support-rag" in aliases, aliases
    assert instant(grafana, panel_expr("p95 TTFT").replace("$__range", "15m")) > 0


def test_in_flight_reads_zero_when_idle(grafana, probe_image):
    """Raw gauge counts the scrape itself (>= 1); the panel must read 0 when idle.
    Waits for a scrape that happens after this test starts sending nothing, then
    evaluates the panel expression AT that scrape. (A range query's last step is
    aligned to the step grid and can fall before the fresh scrape, so it would
    still see the previous test's streams - that made this test timing-dependent.)"""
    def last_sample() -> tuple[float, float]:
        """(scrape timestamp, value) of the newest sample. An instant query's own
        value[0] is the evaluation time, so the scrape time comes from timestamp()."""
        r = probe([{"url": "http://prometheus:9090/api/v1/query?query=timestamp(litellm_in_flight_requests)"},
                   {"url": "http://prometheus:9090/api/v1/query?query=litellm_in_flight_requests"}])
        ts, val = (x["body"]["data"]["result"] for x in r)
        return (float(ts[0]["value"][1]), float(val[0]["value"][1])) if ts and val else (0.0, 0.0)

    t0 = time.time()
    deadline = time.monotonic() + 40
    while last_sample()[0] <= t0 + 1 and time.monotonic() < deadline:
        time.sleep(2)
    ts, raw = last_sample()
    assert ts > t0, "no fresh scrape observed"
    assert raw >= 1  # the scrape itself
    assert instant_at(grafana, panel_expr("In-flight now"), ts) == 0


@pytest.mark.llm
def test_auth_rejections_are_not_metered(gateway, tmp_key):
    """Characterisation of LiteLLM 1.83: 401s from the auth stage change no metric.
    Documented in the dashboard; if an upgrade starts metering them, this fails
    and the panel descriptions must be updated. Uses a disposable key."""
    k = tmp_key("authmeter")  # chat-default only

    def snapshot() -> dict:
        txt = http("GET", gateway.base + "/metrics/").body
        return {line.rsplit(" ", 1)[0]: line.rsplit(" ", 1)[1] for line in txt.splitlines()
                if line.startswith(("litellm_proxy_failed_requests_metric_total{",
                                    "litellm_proxy_total_requests_metric_total{"))}

    before = snapshot()
    assert gateway.embed(k, "t").status == 401                         # model not allowed
    assert gateway.request("GET", "/v1/models", key="sk-not-a-real-key").status == 401
    time.sleep(1)
    assert snapshot() == before


def parallel_counter(key: str) -> int:
    v = redis_cli("get", "{api_key:%s}:max_parallel_requests" % hashlib.sha256(key.encode()).hexdigest())
    return int(v.stdout.strip() or 0)


@pytest.mark.llm
@pytest.mark.xfail(strict=True, reason="LiteLLM 1.83 bug: a 401 'model not allowed' decrements the "
                   "parallel-request counter without incrementing it, so an app can temporarily "
                   "raise its own concurrency ceiling. strict: alerts us when an upgrade fixes it.")
def test_auth_rejection_does_not_skew_parallel_counter(gateway, tmp_key):
    k = tmp_key("skew", max_parallel_requests=2)
    assert gateway.chat(k).status == 200
    base = parallel_counter(k)
    for _ in range(3):
        assert gateway.embed(k, "t").status == 401
    assert parallel_counter(k) == base
