"""Grafana dashboards as code (task 1.9).

Queries run through Grafana's /api/ds/query, so Grafana itself expands
$__range / $__rate_interval exactly as the panels do; only the $app
template variable is substituted here.
"""
import base64
import json
import re
import subprocess
import sys
import time
import urllib.parse

import pytest

from conftest import REPO, http, probe

sys.path.insert(0, str(REPO / "infra" / "grafana"))
import build_dashboards as bd  # noqa: E402

DASH = json.loads((REPO / "infra/grafana/dashboards/platform-overview.json").read_text(encoding="utf-8"))
PANELS = [p for p in DASH["panels"] if p["type"] != "row"]
APP_VAR = next(v for v in DASH["templating"]["list"] if v["name"] == "app")
REAL_APPS = list(bd.APP_COLORS)
STATUS = {bd.GOOD, bd.WARNING, bd.SERIOUS, bd.CRITICAL}


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
    assert len([p for p in r.body["dashboard"]["panels"] if p["type"] != "row"]) == len(PANELS)


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
    assert not [n for n in names if n.startswith("pytest-tmp-") or n == "None"], names


# --- app variable ---------------------------------------------------------------
def test_app_variable_hides_test_and_master_traffic(stack_up, probe_image):
    values = probe([{"url": "http://prometheus:9090/api/v1/label/api_key_alias/values?"
                            + urllib.parse.urlencode({"match[]": bd.REQ})}])[0]["body"]["data"]
    pattern = re.compile(APP_VAR["regex"].strip("/"))
    kept = sorted(v for v in values if pattern.search(v))
    assert set(kept) <= set(REAL_APPS), kept
    for v in ["pytest-tmp-rpm", "None", "pytest-tmp-parallel"]:
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
