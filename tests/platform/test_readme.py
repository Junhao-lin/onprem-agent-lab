"""README (task 1.11): local links resolve, benchmark table matches the raw baseline data."""
import csv
import re

from conftest import REPO

README = (REPO / "README.md").read_text(encoding="utf-8")


def test_local_links_and_images_exist():
    targets = re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", README)
    local = [t for t in targets if not t.startswith(("http://", "https://", "mailto:"))]
    assert len(local) >= 10, local
    missing = [t for t in local if not (REPO / t).exists()]
    assert missing == [], missing


def test_screenshot_embedded_and_present():
    assert "![" in README and "docs/images/dashboard.png" in README
    png = REPO / "docs/images/dashboard.png"
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and png.stat().st_size > 50_000


def test_benchmark_table_matches_raw_baseline():
    """Every row of the README table equals reports/raw/1.10/baseline-restart/summary.csv."""
    raw = {int(r["concurrency"]): r for r in csv.DictReader(
        open(REPO / "reports/raw/1.10/baseline-restart/summary.csv", encoding="utf-8"))}
    rows = re.findall(r"^\| (\d+) \| ([\d.]+) s \| ([\d.]+) s \| ([\d.]+) s \| ([\d.]+) \| ([\d.]+) \|$",
                      README, re.M)
    assert [int(r[0]) for r in rows] == sorted(raw), rows
    for c, ttft50, ttft95, lat95, dec, thr in rows:
        r = raw[int(c)]
        assert ttft50 == f"{float(r['ttft_p50_s']):.3f}" and ttft95 == f"{float(r['ttft_p95_s']):.3f}", c
        assert lat95 == f"{float(r['latency_p95_s']):.2f}", c
        assert dec == f"{float(r['decode_tps_p50']):.1f}" and thr == f"{float(r['throughput_tps']):.1f}", c


def test_quick_start_covers_uv_not_on_path():
    assert "python -m uv sync" in README and "python -m uv run pytest" in README
    assert "不在 PATH" in README


def test_key_limits_table_matches_toml():
    import tomllib
    keys = tomllib.loads((REPO / "infra/litellm/virtual-keys.toml").read_text(encoding="utf-8"))["keys"]
    for alias, k in keys.items():
        row = re.search(rf"^\| `{alias}` \| ([^|]+) \| (\d+) \| (\d+)k \| (\d+) \|$", README, re.M)
        assert row, alias
        assert [m.strip() for m in row.group(1).split(",")] == k["models"]
        assert (int(row.group(2)), int(row.group(3)) * 1000, int(row.group(4))) == \
            (k["rpm_limit"], k["tpm_limit"], k["max_parallel_requests"])
