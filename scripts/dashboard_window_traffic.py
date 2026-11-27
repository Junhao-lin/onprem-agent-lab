"""Which traffic is inside a dashboard screenshot's time range? (evidence for docs/images/dashboard.png)

    python -I scripts/dashboard_window_traffic.py --range 7m [--at <unix ts>] | python -I scripts/rawlog.py OUT

Queries Prometheus (inside the compose network, via `docker compose exec prometheus
wget`) for the increase of every LiteLLM request/failure counter per api_key_alias
and status, and of Qdrant REST calls, over the window [at - range, at]. Prints one
line per series with a non-zero increase plus a verdict: the window holds only the
production app keys' traffic (support-rag, onboarding-agent) with no failures.
No credentials are needed or printed. Exit code 1 if anything else is in the window.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP_ALIASES = {"support-rag", "onboarding-agent"}


def query(expr: str, at: float) -> list[dict]:
    url = "http://localhost:9090/api/v1/query?" + urllib.parse.urlencode({"query": expr, "time": f"{at:.3f}"})
    out = subprocess.run(["docker", "compose", "exec", "-T", "prometheus", "wget", "-qO-", url],
                         cwd=REPO, capture_output=True, text=True, timeout=60, check=True).stdout
    body = json.loads(out)
    assert body["status"] == "success", body
    return body["data"]["result"]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--range", default="7m", help="window length, Prometheus duration (default 7m)")
    ap.add_argument("--at", type=float, default=None, help="window end, unix seconds (default now)")
    args = ap.parse_args()
    at = args.at or time.time()
    end = datetime.fromtimestamp(at, timezone.utc)
    print(f"window: last {args.range} before {end:%Y-%m-%d %H:%M:%S} UTC "
          f"({datetime.fromtimestamp(at).astimezone():%H:%M:%S %z} local)")

    other, failures, app_total = [], [], 0.0
    checks = [
        ("requests", f"sum by (api_key_alias) (increase(litellm_proxy_total_requests_metric_total[{args.range}]))"),
        ("failed", f"sum by (api_key_alias, exception_status) "
                   f"(increase(litellm_proxy_failed_requests_metric_total[{args.range}]))"),
        ("qdrant_rest", f"sum by (endpoint) (increase(rest_responses_total[{args.range}]))"),
    ]
    for name, expr in checks:
        rows = query(expr, at)
        print(f"\n[{name}] {expr}")
        shown = 0
        for r in sorted(rows, key=lambda r: sorted(r["metric"].items())):
            v = float(r["value"][1])
            if v < 0.5:                      # increase() extrapolates; < 0.5 means no event
                continue
            shown += 1
            labels = ", ".join(f"{k}={v2}" for k, v2 in sorted(r["metric"].items())) or "(no labels)"
            print(f"  {labels}: {v:.1f}")
            alias = r["metric"].get("api_key_alias")
            if name == "requests":
                if alias in APP_ALIASES:
                    app_total += v
                else:
                    other.append(f"requests from {alias}")
            elif name == "failed":
                failures.append(f"{alias} {r['metric'].get('exception_status')}")
            else:
                other.append(f"qdrant {r['metric'].get('endpoint')}")
        if not shown:
            print("  (nothing)")

    ok = not other and not failures and app_total > 0
    print(f"\nverdict: {'ONLY production app traffic, no failures' if ok else 'NOT clean'}"
          f" (app requests ~{app_total:.0f}; other: {other or 'none'}; failures: {failures or 'none'})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
