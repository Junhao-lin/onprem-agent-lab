"""Capture the Grafana platform-overview dashboard (kiosk mode) for the README.

    python -m uv run python scripts/screenshot_dashboard.py [--range 10m] [--out docs/images/dashboard.png]

Logs in with GRAFANA_ADMIN_USER / GRAFANA_ADMIN_PASSWORD from .env (never
printed), opens /d/platform-overview?kiosk with the given time range, and only
saves the screenshot if every panel shows data: no "No data" text, no empty
stat value, every time-series legend row numeric, and a non-zero Max in each
time-series panel except the error panel (zero errors is a valid reading). Generate traffic first, e.g. `python loadtest/app_traffic.py`.
Exit code 1 (and no file written) if a panel is empty.
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
VIEWPORT = {"width": 1600, "height": 1700}
EMPTY_TEXT = re.compile(r"\bno\s+data\b", re.I)
EMPTY_STAT = {"–", "-", "N/A", "NaN", ""}
ZERO_OK = {"Failed requests / s by status"}   # zero errors is valid data, not "no data"
NUMBER = re.compile(r"^-?\d+(\.\d+)?(e[-+]?\d+)?(?=(\s*[^\d\s]+)?$)")


def load_env() -> dict[str, str]:
    env = {}
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def problems(page) -> list[str]:
    found = []
    for i in range(page.get_by_text(EMPTY_TEXT).count()):
        title = page.get_by_text(EMPTY_TEXT).nth(i).evaluate(
            "e => e.closest('[data-viz-panel-key]')?.querySelector('h2')?.textContent ?? '?'")
        found.append(f"{title}: 'No data'")
    panels = page.locator("[data-viz-panel-key]")
    for i in range(panels.count()):
        p = panels.nth(i)
        title = p.locator("h2").first.inner_text().strip()
        legend = p.locator("[data-testid='data-testid viz-layout-legend'] tbody tr")
        if legend.count():                                    # time series
            maxima = []
            for j in range(legend.count()):
                cells = [c.strip() for c in legend.nth(j).locator("td").all_inner_texts()]
                nums = [NUMBER.match(c) for c in cells[2:]]
                if len(cells) != 5 or not all(nums):
                    found.append(f"{title}: legend row {cells}")
                else:
                    maxima.append(float(nums[1].group()))
            # Error panels may legitimately be all zero under in-limit traffic.
            if maxima and max(maxima) <= 0 and title not in ZERO_OK:
                found.append(f"{title}: all series flat zero")
        else:                                                 # stat
            text = p.locator("[data-testid='data-testid panel content']").inner_text()
            lines = [s.strip() for s in text.splitlines() if s.strip()]
            if not lines or lines[-1] in EMPTY_STAT:
                found.append(f"{title}: empty stat {lines}")
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--range", default="10m", help="time range ending now (default 10m)")
    ap.add_argument("--out", type=Path, default=REPO / "docs/images/dashboard.png")
    args = ap.parse_args()
    env = load_env()
    base = f"http://127.0.0.1:{env.get('GRAFANA_PORT', '3000')}"

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT)
        try:
            page.goto(base + "/login")
            page.fill("input[name=user]", env["GRAFANA_ADMIN_USER"])
            page.fill("input[name=password]", env["GRAFANA_ADMIN_PASSWORD"])
            page.click("button[type=submit]")
            page.wait_for_url(lambda u: "/login" not in u, timeout=15_000)
        except Exception:
            browser.close()
            print("ERROR: Grafana login failed", file=sys.stderr)
            return 2
        page.goto(f"{base}/d/platform-overview?kiosk&from=now-{args.range}&to=now&refresh=")
        page.wait_for_selector("[data-viz-panel-key]", timeout=30_000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2_000)
        issues = problems(page)
        n = page.locator("[data-viz-panel-key]").count()
        with tempfile.TemporaryDirectory() as tmp:
            shot = Path(tmp) / "dashboard.png"
            page.screenshot(path=str(shot))
            browser.close()
            if issues:
                print(f"NOT saved: {len(issues)} panel(s) without data:", *issues, sep="\n  ")
                return 1
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_bytes(shot.read_bytes())
    print(f"saved {args.out.relative_to(REPO)}: {n} panels, all with data (range now-{args.range})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
