"""Load test tooling (task 1.10): pure-function units + one small end-to-end run."""
import csv
import importlib.util
import json
import subprocess
import sys
import time

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


# --- metric definitions against a fake streaming server (no stack needed) ---
class _FakeSSE:
    """Minimal OpenAI-style SSE endpoint: role chunk at once, first content after
    `ttft` s, the rest after `decode` s, then a usage chunk and [DONE]."""

    def __init__(self, ttft=0.25, decode=0.40, completion_tokens=11):
        import http.server
        import threading
        cfg = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()

                def send(obj):
                    self.wfile.write(b"data: " + json.dumps(obj).encode() + b"\n\n")
                    self.wfile.flush()
                send({"choices": [{"delta": {"role": "assistant", "content": ""}}]})  # not a token
                time.sleep(cfg.ttft)
                send({"choices": [{"delta": {"content": "a"}}]})
                time.sleep(cfg.decode)
                send({"choices": [{"delta": {"content": "bcd"}}]})
                send({"choices": [], "usage": {"completion_tokens": cfg.completion_tokens, "prompt_tokens": 7}})
                self.wfile.write(b"data: [DONE]\n\n")

        self.ttft, self.decode, self.completion_tokens = ttft, decode, completion_tokens
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


def test_stream_once_metric_definitions():
    srv = _FakeSSE(ttft=0.25, decode=0.40, completion_tokens=11)
    try:
        r = bench.stream_once(srv.base, "sk-fake", "m", "p", 16, 1, 0, 10)
    finally:
        srv.close()
    assert r.ok and r.status == 200 and not r.error
    assert 0.24 <= r.ttft_s < 0.24 + 0.40, r.ttft_s          # first CONTENT chunk: after the role chunk, before the 2nd chunk
    assert r.latency_s >= r.ttft_s + 0.39
    assert (r.output_tokens, r.prompt_tokens) == (11, 7)
    assert r.decode_tps == pytest.approx(10 / (r.latency_s - r.ttft_s))
    assert 10 / 0.8 < r.decode_tps < 10 / 0.39                # ~10 tokens over the ~0.4 s decode gap


def test_summarize_throughput_and_percentiles_exact():
    R = bench.Result
    rs = [R(2, i, 200, True, ttft_s=t, latency_s=l, output_tokens=o, decode_tps=d)
          for i, (t, l, o, d) in enumerate([(0.1, 1.0, 100, 50.0), (0.2, 2.0, 200, 60.0),
                                            (0.3, 3.0, 300, 70.0)])]
    s = bench.summarize(2, rs, wall_s=4.0)
    assert s.throughput_tps == pytest.approx(600 / 4.0)
    assert s.req_per_s == pytest.approx(3 / 4.0)
    assert s.decode_tps_p50 == pytest.approx(60.0)
    assert s.ttft_p95_s == pytest.approx(0.29)
    assert s.latency_p50_s == pytest.approx(2.0)


# --- temporary key cleanup (no stack needed) ---------------------------------
class _FakeAdmin:
    def __init__(self, delete_status=200, left=()):
        self.calls, self.delete_status, self.left = [], delete_status, list(left)

    def __call__(self, base, key, method, path, body=None):
        self.calls.append((method, path.split("?")[0], body))
        if path == "/key/generate":
            return 200, {"key": "sk-fakefakefakeWXYZ"}
        if path == "/key/delete":
            return self.delete_status, {}
        if path.startswith("/key/list"):
            return 200, {"keys": self.left}
        raise AssertionError(path)


@pytest.mark.parametrize("admin,ok", [
    (_FakeAdmin(), True),
    (_FakeAdmin(delete_status=500), False),
    (_FakeAdmin(left=["still-here"]), False),
])
def test_delete_temp_key_confirms_deletion(monkeypatch, admin, ok):
    monkeypatch.setattr(bench, "api", admin)
    assert bench.delete_temp_key("http://x", "m", "loadtest-1") is ok


def test_delete_temp_key_never_raises(monkeypatch):
    def boom(*a, **k):
        raise OSError("connection refused")
    monkeypatch.setattr(bench, "api", boom)
    assert bench.delete_temp_key("http://x", "m", "loadtest-1") is False


def _stub_main(monkeypatch, admin, run_level):
    monkeypatch.setattr(bench, "api", admin)
    monkeypatch.setattr(bench, "load_env", lambda p: {"LITELLM_MASTER_KEY": "m"})
    monkeypatch.setattr(bench, "environment", lambda *a: {"timestamp_utc": "t"})
    monkeypatch.setattr(bench, "run_level", run_level)


def test_temp_key_deleted_when_a_level_crashes(monkeypatch, tmp_path):
    admin = _FakeAdmin()

    def crash(*a, **k):
        raise RuntimeError("level crashed")
    _stub_main(monkeypatch, admin, crash)
    with pytest.raises(RuntimeError, match="level crashed"):          # original error kept
        bench.main(["-c", "1", "--no-warmup", "--out", str(tmp_path / "o")])
    assert ("POST", "/key/delete", {"key_aliases": [admin.calls[0][2]["key_alias"]]}) in admin.calls


def test_failed_cleanup_is_reported(monkeypatch, tmp_path, capsys):
    admin = _FakeAdmin(delete_status=500)
    ok = bench.Result(1, 0, 200, True, ttft_s=0.1, latency_s=1.0, output_tokens=10, decode_tps=10.0)
    _stub_main(monkeypatch, admin, lambda *a, **k: ([ok], 1.0))
    rc = bench.main(["-c", "1", "--no-warmup", "--out", str(tmp_path / "o")])
    err = capsys.readouterr().err
    assert rc == 3 and "could not be deleted" in err and "loadtest-" in err
    assert "sk-fakefakefakeWXYZ" not in err


def test_app_traffic_stays_within_key_limits():
    """loadtest/app_traffic.py (dashboard demo traffic) must pace each app below its
    rpm_limit and keep at most one request in flight (< max_parallel_requests)."""
    import tomllib
    spec_t = importlib.util.spec_from_file_location("app_traffic", REPO / "loadtest/app_traffic.py")
    at = importlib.util.module_from_spec(spec_t)
    spec_t.loader.exec_module(at)
    specs = tomllib.loads((REPO / "infra/litellm/virtual-keys.toml").read_text(encoding="utf-8"))["keys"]
    fraction = 0.5                                        # the script's default
    rag = at.SupportRag("http://x", "support-rag", "k", specs["support-rag"], fraction / 2)
    tutor = at.Onboarding("http://x", "onboarding-agent", "k", specs["onboarding-agent"], fraction)
    # support-rag sends 2 requests per turn (embed + chat)
    assert 2 * 60 / rag.interval <= specs["support-rag"]["rpm_limit"] * fraction
    assert 60 / tutor.interval <= specs["onboarding-agent"]["rpm_limit"] * fraction
    assert all(s["max_parallel_requests"] >= 2 for s in specs.values())   # one worker per app
