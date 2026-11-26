"""Generate Grafana dashboards as code.

    python infra/grafana/build_dashboards.py           # write JSON
    python infra/grafana/build_dashboards.py --reload  # write JSON + tell Grafana to reload
    python infra/grafana/build_dashboards.py --check   # exit 1 if JSON is stale

Grafana's file watcher does not see changes through Windows/WSL bind
mounts (verified: neither fs events nor updateIntervalSeconds polling
fire), so --reload calls POST /api/admin/provisioning/dashboards/reload
with the admin credentials from .env.

Design rules (kept here so every panel follows them):
  * Each app has ONE fixed colour everywhere (colour follows the entity,
    never its rank or the current filter). Validated for Grafana's dark
    surface #181b1f: CVD dE 27.5, normal dE 33.3, contrast >= 3:1.
  * Status colours are reserved for state (errors, health) and never used
    for an app series.
  * One y-axis per panel: different measures go to separate panels.
  * Legends always shown with the app name, so identity is never colour-only.
Stdlib only.
"""
from __future__ import annotations

import base64
import json
import sys
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "dashboards"
DS = {"type": "prometheus", "uid": "prometheus"}

# Fixed app colours (categorical slots 1, 2 - dark-mode steps).
APP_COLORS = {"support-rag": "#338ced", "onboarding-agent": "#e76624"}
# Reserved status colours.
GOOD, WARNING, SERIOUS, CRITICAL = "#0aac23", "#fbb315", "#f18a59", "#dc3c3d"
NEUTRAL = "#9c9c9c"

APP = 'api_key_alias=~"$app"'
REQ = "litellm_proxy_total_requests_metric_total"
FAIL = "litellm_proxy_failed_requests_metric_total"
LAT = "litellm_request_total_latency_metric_bucket"
TTFT = "litellm_llm_api_time_to_first_token_metric_bucket"


# --------------------------------------------------------------------------
# panel builders
# --------------------------------------------------------------------------
class Layout:
    def __init__(self):
        self.y = 0
        self.x = 0
        self.row_h = 0
        self.next_id = 1

    def place(self, w: int, h: int) -> dict:
        if self.x + w > 24:
            self.x, self.y = 0, self.y + self.row_h
            self.row_h = 0
        pos = {"x": self.x, "y": self.y, "w": w, "h": h}
        self.x += w
        self.row_h = max(self.row_h, h)
        return pos

    def newline(self):
        if self.x:
            self.x, self.y, self.row_h = 0, self.y + self.row_h, 0

    def pid(self) -> int:
        self.next_id += 1
        return self.next_id - 1


def target(expr: str, legend: str = "", ref: str = "A", instant: bool = False) -> dict:
    t = {"datasource": DS, "expr": expr, "refId": ref, "legendFormat": legend or "__auto",
         "range": not instant, "instant": instant}
    return t


def app_color_overrides() -> list[dict]:
    return [{"matcher": {"id": "byName", "options": name},
             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}]}
            for name, color in APP_COLORS.items()]


def row(lay: Layout, title: str) -> dict:
    lay.newline()
    p = {"type": "row", "title": title, "id": lay.pid(), "collapsed": False, "panels": [],
         "gridPos": {"x": 0, "y": lay.y, "w": 24, "h": 1}}
    lay.y += 1
    return p


def stat(lay: Layout, title: str, expr: str, unit: str, description: str,
         thresholds: list[tuple[float | None, str]] | None = None,
         mappings: list[dict] | None = None, decimals: int | None = None, w: int = 4) -> dict:
    steps = [{"value": v, "color": c} for v, c in (thresholds or [(None, NEUTRAL)])]
    defaults = {"unit": unit, "thresholds": {"mode": "absolute", "steps": steps},
                "color": {"mode": "thresholds"}, "mappings": mappings or [],
                "noValue": "–"}
    if decimals is not None:
        defaults["decimals"] = decimals
    return {
        "type": "stat", "title": title, "description": description, "id": lay.pid(),
        "datasource": DS, "gridPos": lay.place(w, 4),
        "targets": [target(expr, instant=True)],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "colorMode": "value", "graphMode": "none", "textMode": "value",
                    "justifyMode": "center", "orientation": "auto"},
    }


def timeseries(lay: Layout, title: str, targets: list[dict], unit: str, description: str,
               overrides: list[dict] | None = None, w: int = 12, h: int = 8,
               stack: bool = False, min0: bool = True) -> dict:
    custom = {"drawStyle": "line", "lineWidth": 2, "fillOpacity": 0, "pointSize": 8,
              "showPoints": "never", "spanNulls": False, "axisPlacement": "auto",
              "stacking": {"mode": "normal" if stack else "none", "group": "A"}}
    if stack:
        custom["fillOpacity"] = 60
        custom["lineWidth"] = 1
    defaults = {"unit": unit, "custom": custom, "color": {"mode": "fixed", "fixedColor": NEUTRAL},
                "noValue": "No data in range"}
    if min0:
        defaults["min"] = 0
    return {
        "type": "timeseries", "title": title, "description": description, "id": lay.pid(),
        "datasource": DS, "gridPos": lay.place(w, h), "targets": targets,
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "options": {"legend": {"showLegend": True, "displayMode": "table", "placement": "bottom",
                               "calcs": ["mean", "max", "lastNotNull"]},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
    }


def p95(metric: str, by: str = "", window: str = "$__rate_interval") -> str:
    group = f"le, {by}" if by else "le"
    return f"histogram_quantile(0.95, sum by ({group}) (rate({metric}{{{APP}}}[{window}])))"


# --------------------------------------------------------------------------
# dashboard
# --------------------------------------------------------------------------
def platform_overview() -> dict:
    lay = Layout()
    panels: list[dict] = []
    status_overrides = [
        {"matcher": {"id": "byRegexp", "options": "^429$"},
         "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": WARNING}},
                        {"id": "displayName", "value": "429 rate limited"}]},
        {"matcher": {"id": "byRegexp", "options": "^40[13]$"},
         "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": SERIOUS}},
                        {"id": "displayName", "value": "${__field.labels.exception_status} auth / not allowed"}]},
        {"matcher": {"id": "byRegexp", "options": "^5\\d\\d$"},
         "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": CRITICAL}},
                        {"id": "displayName", "value": "${__field.labels.exception_status} server error"}]},
    ]

    panels.append(row(lay, "Overview (selected time range)"))
    panels += [
        stat(lay, "Requests", f"sum(increase({REQ}{{{APP}}}[$__range]))", "short",
             "Gateway requests from the selected apps in the time range.", decimals=0),
        stat(lay, "Error rate",
             f"(sum(increase({FAIL}{{{APP}}}[$__range])) or vector(0))"
             f" / sum(increase({REQ}{{{APP}}}[$__range]))",
             "percentunit", "Failed / total gateway requests, including 429 rate limits. "
             "Note: LiteLLM 1.83 does not meter requests rejected during authentication "
             "(401 bad key / model not allowed), so they are not counted here.",
             thresholds=[(None, GOOD), (0.01, WARNING), (0.05, CRITICAL)], decimals=1),
        stat(lay, "p95 latency", p95(LAT, window="$__range"), "s",
             "95th percentile end-to-end request latency at the gateway.", decimals=2),
        stat(lay, "p95 TTFT", p95(TTFT, window="$__range"), "s",
             "95th percentile time to first token. Streaming requests only.", decimals=2),
        # The gauge counts every HTTP request on the worker, including the
        # Prometheus scrape of /metrics itself, so it reads >= 1 at scrape time.
        # Subtract that one scrape per gateway instance.
        stat(lay, "In-flight now",
             'clamp_min(sum(litellm_in_flight_requests) - count(up{job="litellm"} == 1), 0)', "short",
             "HTTP requests being processed by the gateway (all keys), excluding the "
             "Prometheus scrape itself. A concurrent health check can briefly add 1.", decimals=0),
        stat(lay, "Scrape targets", "min(up)", "short",
             "Whether Prometheus can scrape every target (prometheus, litellm, qdrant).",
             thresholds=[(None, CRITICAL), (1, GOOD)],
             mappings=[{"type": "value", "options": {
                 "0": {"text": "✕ target down", "index": 0},
                 "1": {"text": "✓ all up", "index": 1}}}]),
    ]

    panels.append(row(lay, "Traffic per app"))
    panels += [
        timeseries(lay, "Requests / s by app",
                   [target(f"sum by (api_key_alias) (rate({REQ}{{{APP}}}[$__rate_interval]))",
                           "{{api_key_alias}}")],
                   "reqps", "Request rate per virtual key.", app_color_overrides()),
        timeseries(lay, "Failed requests / s by status",
                   [target(f"sum by (exception_status) (rate({FAIL}{{{APP}}}[$__rate_interval]))",
                           "{{exception_status}}")],
                   "reqps", "Gateway failures by HTTP status. 429 = rate limit (expected under "
                   "load), 5xx = backend errors. Requests rejected during authentication "
                   "(401 bad key / model not allowed) are not metered by LiteLLM 1.83.",
                   status_overrides, stack=True),
    ]

    panels.append(row(lay, "Latency per app"))
    panels += [
        timeseries(lay, "p95 request latency",
                   [target(p95(LAT, "api_key_alias"), "{{api_key_alias}}")],
                   "s", "95th percentile end-to-end latency per app.", app_color_overrides()),
        timeseries(lay, "p95 time to first token",
                   [target(p95(TTFT, "api_key_alias"), "{{api_key_alias}}")],
                   "s", "95th percentile TTFT per app. Only streaming requests report TTFT.",
                   app_color_overrides()),
    ]

    panels.append(row(lay, "Tokens per app"))
    panels += [
        timeseries(lay, "Output tokens / s",
                   [target(f"sum by (api_key_alias) (rate(litellm_output_tokens_metric_total{{{APP}}}"
                           "[$__rate_interval]))", "{{api_key_alias}}")],
                   "short", "Generated tokens per second (counts against tpm limits).",
                   app_color_overrides()),
        timeseries(lay, "Input tokens / s",
                   [target(f"sum by (api_key_alias) (rate(litellm_input_tokens_metric_total{{{APP}}}"
                           "[$__rate_interval]))", "{{api_key_alias}}")],
                   "short", "Prompt tokens per second (RAG context drives this up).",
                   app_color_overrides()),
    ]

    panels.append(row(lay, "Vector store (Qdrant)"))
    panels += [
        timeseries(lay, "Qdrant REST requests / s",
                   [target("sum by (endpoint) (rate(rest_responses_total[$__rate_interval]))",
                           "{{endpoint}}")],
                   "reqps", "Qdrant REST calls by endpoint (all clients).", w=9),
        timeseries(lay, "Qdrant p95 REST latency",
                   [target("histogram_quantile(0.95, sum by (le) "
                           "(rate(rest_responses_duration_seconds_bucket[$__rate_interval])))",
                           "p95")],
                   "s", "95th percentile Qdrant REST response time.", w=9),
        stat(lay, "Collections", "max(collections_total)", "short",
             "Number of Qdrant collections.", decimals=0, w=3),
        stat(lay, "Vectors", "max(collections_vector_total)", "short",
             "Total stored vectors across collections.", decimals=0, w=3),
    ]

    return {
        "uid": "platform-overview",
        "title": "Platform overview",
        "description": "LLM gateway traffic, errors, latency and tokens per app; Qdrant health.",
        "tags": ["onprem-agent-lab", "platform"],
        "timezone": "browser",
        "editable": False,
        "graphTooltip": 1,  # shared crosshair
        "refresh": "30s",
        "time": {"from": "now-1h", "to": "now"},
        "schemaVersion": 39,
        "version": 1,
        "templating": {"list": [{
            "type": "query", "name": "app", "label": "App",
            "datasource": DS,
            "query": {"query": f"label_values({REQ}, api_key_alias)", "refId": "app"},
            "definition": f"label_values({REQ}, api_key_alias)",
            # Real apps only: hide test keys (pytest-tmp-*) and master-key traffic (None).
            "regex": "/^(?!pytest-tmp-|None$).+$/",
            "includeAll": True, "multi": True, "allValue": None,
            "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
            "refresh": 2, "sort": 1,
        }]},
        "annotations": {"list": []},
        "panels": panels,
    }


DASHBOARDS = {"platform-overview.json": platform_overview}


def render() -> dict[str, str]:
    return {name: json.dumps(fn(), indent=2, ensure_ascii=False) + "\n"
            for name, fn in DASHBOARDS.items()}


def reload_grafana() -> None:
    env = {}
    for line in (OUT.parents[2] / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    token = base64.b64encode(f"{env['GRAFANA_ADMIN_USER']}:{env['GRAFANA_ADMIN_PASSWORD']}".encode()).decode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{env.get('GRAFANA_PORT', '3000')}/api/admin/provisioning/dashboards/reload",
        method="POST", headers={"Authorization": f"Basic {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"grafana reload: HTTP {r.status}")


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for name, text in render().items():
        path = OUT / name
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {path.relative_to(OUT.parent.parent.parent)}")
    if stale:
        print(f"stale dashboards (run build_dashboards.py): {stale}", file=sys.stderr)
        return 1
    if "--reload" in sys.argv and not check:
        reload_grafana()
    return 0


if __name__ == "__main__":
    sys.exit(main())
