"""Browser check of the provisioned Grafana dashboard (task 1.9 follow-up).

Logs in through the real login form (credentials from .env, never printed),
opens platform-overview in kiosk mode, saves a screenshot under
reports/raw/1.9/latest/ (git-ignored; the committed reports/raw/1.9/
platform-overview-kiosk.png is the one reviewed in the 1.9 report and is
never overwritten) and asserts that every panel actually shows data:

  * no "No data" / "No data in range" text anywhere,
  * no stat tile showing the empty value (an en dash, U+2013),
  * every time-series legend row has numeric Mean/Max/Last and at least one
    series per panel has a non-zero Max,
  * no panel error indicator,
  * the panels do not overlap and stay inside the viewport.

The API-level checks live in tests/platform/test_dashboards.py; this test
covers what only a rendered page can show. It first generates its own
real-app traffic so the result does not depend on what ran earlier.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "platform"))
from conftest import REPO, TMP_PREFIX, env, gateway, probe, probe_image, stack_up  # noqa: E402,F401  (fixtures)
from test_dashboards import (SPECS_PARALLEL, grafana, hold_slots_then_overflow,  # noqa: E402,F401
                             twice_across_scrape)
from test_virtual_keys import drain, open_stream  # noqa: E402

playwright_api = pytest.importorskip("playwright.sync_api")

DASH = json.loads((REPO / "infra/grafana/dashboards/platform-overview.json").read_text(encoding="utf-8"))
PANELS = [p for p in DASH["panels"] if p["type"] != "row"]
STAT_TITLES = [p["title"] for p in PANELS if p["type"] == "stat"]
TS_TITLES = [p["title"] for p in PANELS if p["type"] == "timeseries"]
OUT_DIR = REPO / "reports/raw/1.9/latest"   # git-ignored: every run overwrites it
VIEWPORT = {"width": 1600, "height": 1700}       # whole dashboard fits without scrolling
EMPTY_TEXT = re.compile(r"\bno\s+data\b", re.I)   # "No data", "No data in range", ...
EMPTY_STAT = {"–", "-", "N/A", "NaN", ""}          # – = en dash, Grafana's empty value
NUMBER = re.compile(r"^-?\d+(\.\d+)?(e[-+]?\d+)?(?=(\s*[^\d\s]+)?$)")   # value + optional unit, nothing else

pytestmark = [pytest.mark.llm, pytest.mark.browser]


# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def app_traffic(env, gateway, grafana, probe_image):
    """Real-app traffic every panel needs, each observed across a scrape:
    streams from both apps (requests, latency, TTFT, tokens), one
    support-rag 429 (failed-requests panel, error rate) and Qdrant point
    upserts/queries (Prometheus scrapes of Qdrant are not counted as REST calls)."""
    for alias, var in (("support-rag", "SUPPORT_RAG_LLM_KEY"),
                       ("onboarding-agent", "ONBOARDING_AGENT_LLM_KEY")):
        def stream(key=env[var]):
            status, resp = open_stream(gateway, key)
            assert status == 200, f"{alias} stream: HTTP {status}"
            drain(resp)
        twice_across_scrape(
            grafana, stream,
            f'sum(litellm_llm_api_time_to_first_token_metric_count{{api_key_alias="{alias}"}})')

    slots = SPECS_PARALLEL["support-rag"]

    def overflow():
        assert hold_slots_then_overflow(gateway, env["SUPPORT_RAG_LLM_KEY"], slots) == [200] * slots + [429]
    twice_across_scrape(
        grafana, overflow,
        'sum(litellm_proxy_failed_requests_metric_total{api_key_alias="support-rag",exception_status="429"})')

    # Qdrant meters only point endpoints, so use a disposable collection.
    h = {"api-key": env["QDRANT_API_KEY"]}
    col = f"http://qdrant:6333/collections/{TMP_PREFIX.replace('-', '_')}e2e_{int(time.time())}"

    def qdrant_points():
        rs = probe([
            {"method": "PUT", "url": f"{col}/points?wait=true", "headers": h, "body": {"points": [
                {"id": i, "vector": [float(i), 1.0, 0.0, 0.5]} for i in range(1, 4)]}},
            {"method": "POST", "url": f"{col}/points/query", "headers": h,
             "body": {"query": [1.0, 1.0, 0.0, 0.5], "limit": 2}}])
        assert [r["status"] for r in rs] == [200, 200], [r["status"] for r in rs]
    failure: BaseException | None = None
    try:
        assert probe([{"method": "PUT", "url": col, "headers": h,
                       "body": {"vectors": {"size": 4, "distance": "Cosine"}}}])[0]["status"] == 200
        twice_across_scrape(grafana, qdrant_points, "sum(rest_responses_total)")
    except BaseException as e:
        failure = e
        raise
    finally:
        try:
            deleted = probe([{"method": "DELETE", "url": col, "headers": h}])[0]
            cleaned = deleted["status"] == 200 and deleted["body"].get("result") is True
            msg = f"temporary Qdrant collection not cleaned up: HTTP {deleted['status']}"
        except Exception as e:      # the cleanup call itself failed
            cleaned, msg = False, f"temporary Qdrant collection not cleaned up: {type(e).__name__}"
        if failure is not None:
            if not cleaned:
                failure.add_note(msg)       # keep the original error, report cleanup too
        else:
            assert cleaned, msg


@pytest.fixture(scope="module")
def dashboard_page(env, stack_up, app_traffic):
    base = f"http://127.0.0.1:{env.get('GRAFANA_PORT', '3000')}"
    with playwright_api.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT)
        try:
            page.goto(base + "/login")
            page.fill("input[name=user]", env["GRAFANA_ADMIN_USER"])
            page.fill("input[name=password]", env["GRAFANA_ADMIN_PASSWORD"])
            page.click("button[type=submit]")
            page.wait_for_url(lambda u: "/login" not in u, timeout=15_000)
        except Exception:
            browser.close()
            # Never let a Playwright call log carry the typed credentials.
            raise AssertionError("Grafana login via the form failed") from None

        page.goto(base + "/d/platform-overview?kiosk")
        page.wait_for_selector("[data-viz-panel-key]", timeout=30_000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2_000)            # let the last panels paint
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(OUT_DIR / "platform-overview-kiosk.png"))
        yield page
        browser.close()


def panel(page, title: str):
    return page.locator(f"[data-viz-panel-key]:has([data-testid='data-testid Panel header {title}'])")


# --------------------------------------------------------------------------
def test_login_kept_out_of_url_and_kiosk_hides_chrome(dashboard_page, env):
    assert "/d/platform-overview" in dashboard_page.url and "kiosk" in dashboard_page.url
    assert env["GRAFANA_ADMIN_PASSWORD"] not in dashboard_page.url
    # kiosk mode: no navigation sidebar / top search bar
    assert dashboard_page.locator("[data-testid='data-testid Nav menu']").count() == 0
    assert dashboard_page.get_by_placeholder(re.compile("Search")).count() == 0


def test_all_panels_rendered(dashboard_page):
    assert dashboard_page.locator("[data-viz-panel-key]").count() == len(PANELS)
    for p in PANELS:
        assert panel(dashboard_page, p["title"]).count() == 1, p["title"]


def test_no_panel_shows_no_data(dashboard_page):
    hits = dashboard_page.get_by_text(EMPTY_TEXT)
    offenders = [hits.nth(i).evaluate(
        "e => e.closest('[data-viz-panel-key]')?.querySelector('h2')?.textContent ?? '?'")
        for i in range(hits.count())]
    assert offenders == [], f"panels with 'No data': {offenders}"


@pytest.mark.parametrize("title", STAT_TITLES)
def test_stat_tile_has_value(dashboard_page, title):
    value = panel(dashboard_page, title).locator("[data-testid='data-testid panel content']").inner_text()
    lines = [s.strip() for s in value.splitlines() if s.strip()]
    assert lines and lines[-1] not in EMPTY_STAT, f"{title}: {lines}"


@pytest.mark.parametrize("title", TS_TITLES)
def test_timeseries_has_plotted_series(dashboard_page, title):
    pnl = panel(dashboard_page, title)
    assert pnl.locator(".uplot canvas").count() >= 1, f"{title}: no plot canvas"
    assert pnl.locator("[data-testid='data-testid viz-layout-legend'] [data-testid='series-icon']").count() >= 1, \
        f"{title}: legend has no series"
    # Legend table rows (Mean | Max | Last) are computed by Grafana from the
    # plotted points. Every series must carry numbers, and at least one series
    # must have a non-zero Max, i.e. something above the baseline was drawn.
    rows = pnl.locator("[data-testid='data-testid viz-layout-legend'] tbody tr")
    assert rows.count() >= 1, f"{title}: legend table has no rows"
    maxima = []
    for i in range(rows.count()):
        cells = [c.strip() for c in rows.nth(i).locator("td").all_inner_texts()]
        # cells: [colour swatch, name, Mean, Max, Last]
        assert len(cells) == 5 and cells[1], f"{title}: unexpected legend row {cells}"
        nums = [NUMBER.match(c) for c in cells[2:]]
        assert all(nums), f"{title}: series {cells[1]!r} has non-numeric legend values {cells[2:]}"
        maxima.append(float(nums[1].group()))
    assert max(maxima) > 0, f"{title}: every series is flat zero"


def test_no_panel_errors(dashboard_page):
    assert dashboard_page.locator("[data-testid='data-testid Panel status error']").count() == 0


def test_panels_do_not_overlap_and_fit_viewport(dashboard_page):
    boxes = [(p["title"], panel(dashboard_page, p["title"]).bounding_box()) for p in PANELS]
    for title, b in boxes:
        assert b and b["width"] > 0 and b["height"] > 0, title
        assert b["x"] >= 0 and b["x"] + b["width"] <= VIEWPORT["width"] + 1, f"{title} overflows horizontally"
        assert b["y"] >= 0 and b["y"] + b["height"] <= VIEWPORT["height"] + 1, f"{title} outside the screenshot"
    for i, (ta, a) in enumerate(boxes):
        for tb, b in boxes[i + 1:]:
            ix = min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"])
            iy = min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"])
            assert ix <= 1 or iy <= 1, f"{ta!r} overlaps {tb!r}"


def test_screenshot_saved(dashboard_page):
    shot = OUT_DIR / "platform-overview-kiosk.png"
    assert shot.exists() and shot.stat().st_size > 50_000
