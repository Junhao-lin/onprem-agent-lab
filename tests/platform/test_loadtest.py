"""Load test tooling (task 1.10): pure-function units + one small end-to-end run."""
import csv
import importlib.util
import json
import subprocess
import sys

import pytest

from conftest import REPO, run

spec = importlib.util.spec_from_file_location("bench", REPO / "loadtest/bench.py")
bench = importlib.util.module_from_spec(spec)
sys.modules["bench"] = bench  # dataclasses resolve their module via sys.modules
spec.loader.exec_module(bench)


# --- units (no stack needed) ----------------------------------------------
@pytest.mark.parametrize("values,p,expected", [
    ([], 50, None),
    ([3.0], 95, 3.0),
    ([1, 2, 3, 4], 50, 2.5),
    ([1, 2, 3, 4, 5], 95, 4.8),          # numpy default (linear) gives 4.8
    ([5, 1, 4, 2, 3], 0, 1),
    ([5, 1, 4, 2, 3], 100, 5),
])
def test_percentile(values, p, expected):
    got = bench.percentile(values, p)
    assert got == pytest.approx(expected) if expected is not None else got is None


def test_summarize_counts_and_rates():
    R = bench.Result
    results = [
        R(4, 0, 200, True, ttft_s=0.1, latency_s=1.0, output_tokens=10, decode_tps=10.0),
        R(4, 1, 200, True, ttft_s=0.3, latency_s=2.0, output_tokens=30, decode_tps=17.0),
        R(4, 2, 429, False, latency_s=0.01, error="HTTP 429"),
        R(4, 3, 500, False, latency_s=0.02, error="HTTP 500"),
    ]
    s = bench.summarize(4, results, wall_s=2.0)
    assert (s.requests, s.ok, s.http_429, s.other_errors) == (4, 2, 1, 1)
    assert s.output_tokens_total == 40 and s.throughput_tps == pytest.approx(20.0)
    assert s.req_per_s == pytest.approx(1.0)
    assert s.ttft_p50_s == pytest.approx(0.2)          # failures excluded from percentiles
    assert s.latency_p95_s == pytest.approx(1.95)


def test_mask_matches_project_format():
    assert bench.mask("sk-abcdefghijklmnopWXYZ") == "sk-…WXYZ"


def test_prompts_file_valid():
    prompts = bench.load_prompts()
    assert len(prompts) >= 4 and all(p.strip() for p in prompts)
    assert len(set(prompts)) == len(prompts)


# --- end-to-end (small) -----------------------------------------------------
@pytest.mark.llm
def test_bench_end_to_end(gateway, tmp_path):
    out = tmp_path / "run"
    proc = subprocess.run([sys.executable, "-I", "loadtest/bench.py", "-c", "1,2", "-n", "4",
                           "--max-tokens", "32", "--no-warmup", "--out", str(out)],
                          cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    rows = list(csv.DictReader(open(out / "requests.csv", encoding="utf-8")))
    assert len(rows) == 8 and all(r["status"] == "200" and r["ok"] == "True" for r in rows)
    assert all(float(r["ttft_s"]) > 0 and int(r["output_tokens"]) > 0 for r in rows)
    assert all(float(r["latency_s"]) >= float(r["ttft_s"]) for r in rows)

    summary = list(csv.DictReader(open(out / "summary.csv", encoding="utf-8")))
    assert [int(s["concurrency"]) for s in summary] == [1, 2]
    assert all(int(s["ok"]) == 4 for s in summary)

    md = (out / "summary.md").read_text(encoding="utf-8")
    assert "| Concurrency |" in md and "## Environment" in md
    meta = json.loads((out / "environment.json").read_text(encoding="utf-8"))
    assert meta["gateway_model_alias"] == "chat-default" and meta["git_commit"]

    # temporary key: masked in output, deleted afterwards
    assert "sk-…" in proc.stdout
    alias = next(line.split()[2] for line in proc.stdout.splitlines() if line.startswith("key: temporary"))
    assert gateway.request("GET", "/key/list", query={"key_alias": alias}).body["keys"] == []


def test_results_dir_never_tracked():
    """1.1 rule re-checked for the real output location."""
    assert run(["git", "check-ignore", "-q", "loadtest/results/20260101T000000Z/summary.md"]).returncode == 0


def test_repro_degradation_plan():
    """The ops-risk repro must bracket the overload with restarted references."""
    spec_r = importlib.util.spec_from_file_location("repro_degradation", REPO / "loadtest/repro_degradation.py")
    repro = importlib.util.module_from_spec(spec_r)
    spec_r.loader.exec_module(repro)
    steps = {name: (c, restart) for name, c, restart in repro.STEPS}
    assert repro.STEPS[0][0] == "fresh" and repro.STEPS[-1][0] == "restarted"
    assert steps["fresh"] == (2, True) and steps["restarted"] == (2, True)
    assert steps["overload"][0] > 4 and not steps["overload"][1]          # > OLLAMA_NUM_PARALLEL
    assert all(not r for n, (c, r) in steps.items() if n not in ("fresh", "restarted"))
