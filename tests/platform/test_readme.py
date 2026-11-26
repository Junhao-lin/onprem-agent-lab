"""README (task 1.11): links, screenshot, commands and numbers stay true to the repo."""
import csv
import re
import tomllib

from conftest import REPO

README = (REPO / "README.md").read_text(encoding="utf-8")
CODE_BLOCKS = re.findall(r"```(?:bash|powershell)\n(.*?)```", README, re.S)
COMPOSE = "\n".join((REPO / f).read_text(encoding="utf-8")
                    for f in ("docker-compose.yml", "docker-compose.gpu.yml", "docker-compose.debug.yml"))


def test_local_links_and_images_exist():
    targets = re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", README)
    local = [t for t in targets if not t.startswith(("http://", "https://", "mailto:"))]
    assert len(local) >= 10, local
    missing = [t for t in local if not (REPO / t).exists()]
    assert missing == [], missing


def test_screenshot_embedded_and_present():
    assert re.search(r"!\[[^\]]+\]\(docs/images/dashboard\.png\)", README), "image not embedded"
    png = REPO / "docs/images/dashboard.png"
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and png.stat().st_size > 50_000


def test_commands_reference_real_files_profiles_and_markers():
    """Every script, compose file, profile, test path and marker used in a README
    command block exists, so copy-pasting a command cannot hit a stale name."""
    assert len(CODE_BLOCKS) >= 8
    cmds = "\n".join(CODE_BLOCKS)
    # script paths anywhere in the README (code blocks and inline code)
    scripts = set(re.findall(r"\b((?:scripts|loadtest|infra|tests)/[\w/.-]+\.py)\b", README))
    assert {"scripts/bootstrap_keys.py", "loadtest/bench.py", "loadtest/app_traffic.py"} <= scripts
    assert [s for s in scripts if not (REPO / s).is_file()] == []
    files = set(re.findall(r"-f (\S+\.yml)", cmds))
    assert files and [f for f in files if not (REPO / f).is_file()] == []
    profiles = set(re.findall(r"--profile (\w+)", cmds))
    assert profiles == {"platform", "monitoring"}
    assert all(re.search(rf"profiles:\s*\[[^\]]*\b{p}\b", COMPOSE) or
               re.search(rf"profiles:\s*\n\s*-\s*{p}\b", COMPOSE) for p in profiles), profiles
    paths = set(re.findall(r"pytest (tests/[\w/]+)", cmds))
    assert paths and [p for p in paths if not (REPO / p).exists()] == []
    markers = set(re.findall(r'-m "not (\w+)"', cmds))
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    declared = {m.split(":")[0] for m in pyproject["tool"]["pytest"]["ini_options"]["markers"]}
    assert markers and markers <= declared


def test_quick_start_steps_and_uv_fallback():
    steps = re.findall(r"^\*\*(\d)\. ", README, re.M)
    assert steps == ["1", "2", "3", "4", "5"], steps
    assert "不在 PATH" in README and "python -m uv sync" in README and "python -m uv run pytest" in README
    assert any("Invoke-RestMethod" in b for b in CODE_BLOCKS), "no PowerShell variant of the smoke test"
    assert any("curl -s http://127.0.0.1:4000/v1/chat/completions" in b for b in CODE_BLOCKS)


def test_no_real_key_material(env):
    """Masked examples must not be the real keys' last 4 characters."""
    real_tails = {v[-4:] for k, v in env.items() if v.startswith("sk-") and len(v) > 8}
    shown = set(re.findall(r"sk-…([A-Za-z0-9_-]{4})", README))
    assert not (shown & real_tails), "README shows the tail of a real key"
    secret_names = ("PASSWORD", "KEY", "SALT", "SECRET", "TOKEN")
    leaked = [k for k, v in env.items() if any(n in k for n in secret_names) and len(v) >= 8 and v in README]
    assert leaked == [], leaked


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
    # conditions stated next to the table match the raw run
    env = __import__("json").loads((REPO / "reports/raw/1.10/baseline-restart/environment.json").read_text(encoding="utf-8"))
    assert f"max_tokens {env['max_tokens']}" in README and env["backend_model"] in README


def test_ops_risk_numbers_match_degradation_data():
    rows = list(csv.DictReader(open(REPO / "reports/raw/1.10/degradation/summary.csv", encoding="utf-8")))
    tps = {(r["cycle"], r["step"]): float(r["throughput_tps"]) for r in rows}
    cycles = sorted({c for c, _ in tps})
    drops, degraded, partial = [], [], []
    for c in cycles:                       # each run against the fresh reference of its own cycle
        for step in ("after-1", "after-2"):
            t = tps[(c, step)]
            # The README range covers clearly degraded runs; a partial onset (still >= 60 %
            # of fresh throughput) is described separately in words.
            if t < 0.6 * tps[(c, "fresh")]:
                degraded.append(t)
                drops.append(round(100 * (1 - t / tps[(c, "fresh")])))
            else:
                partial.append(t)
    assert len(degraded) >= 3 and len(partial) <= 1, tps
    if partial:
        assert "部分請求" in README
    assert f"{min(drops)}–{max(drops)}%" in README, drops
    assert f"{min(degraded):.0f}–{max(degraded):.0f} tok/s" in README, degraded


def test_key_limits_table_matches_toml():
    keys = tomllib.loads((REPO / "infra/litellm/virtual-keys.toml").read_text(encoding="utf-8"))["keys"]
    for alias, k in keys.items():
        row = re.search(rf"^\| `{alias}` \| ([^|]+) \| (\d+) \| (\d+)k \| (\d+) \|$", README, re.M)
        assert row, alias
        assert [m.strip() for m in row.group(1).split(",")] == k["models"]
        assert (int(row.group(2)), int(row.group(3)) * 1000, int(row.group(4))) == \
            (k["rpm_limit"], k["tpm_limit"], k["max_parallel_requests"])
