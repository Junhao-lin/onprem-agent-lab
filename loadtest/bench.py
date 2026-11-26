"""Gateway load test: TTFT, tokens/s, latency percentiles across concurrency levels.

Every request streams through the LiteLLM gateway, so TTFT is measured from
the client's point of view (gateway + queueing + prefill).

    python loadtest/bench.py                              # default sweep 1,2,4,8,16
    python loadtest/bench.py -c 1,4 -n 8 --max-tokens 64  # quick run
    python loadtest/bench.py --key-env SUPPORT_RAG_LLM_KEY  # through an app's limits
    python loadtest/bench.py --restart-backend         # comparable levels (see below)

Backend state matters: with Ollama 0.40.18, after a level that oversubscribes
OLLAMA_NUM_PARALLEL (e.g. c=8 on 4 slots), a following c=2 level drops from
~154 to ~84 tok/s total until Ollama restarts (measured; c=1 and c=4 are not
affected). --restart-backend restarts Ollama and warms up before every level
so each level starts from the same state.

Key handling: by default a temporary virtual key ("loadtest-<ts>", no rpm/tpm/
parallel limits, chat-default only) is created with the master key and deleted
afterwards, so the sweep measures platform capacity rather than an app quota.
Keys are never printed (masked as sk-…last4).

Output: loadtest/results/<UTC timestamp>/ (git-ignored)
    requests.csv   one row per request
    summary.csv    one row per concurrency level
    summary.md     human-readable report incl. environment
Stdlib only (Python 3.11+).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import json
import math
import os
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROMPTS_FILE = Path(__file__).resolve().parent / "prompts.jsonl"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def mask(key: str) -> str:
    return f"sk-…{key[-4:]}" if key and len(key) > 8 else "***"


def percentile(values: list[float], p: float) -> float | None:
    """Linear-interpolated percentile (same as numpy's default). None if empty."""
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def api(base: str, key: str, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(base + path, method=method)
    req.add_header("Authorization", f"Bearer {key}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


# --------------------------------------------------------------------------
# one streaming request
# --------------------------------------------------------------------------
@dataclass
class Result:
    concurrency: int
    seq: int
    status: int
    ok: bool
    ttft_s: float | None = None
    latency_s: float | None = None
    output_tokens: int | None = None
    prompt_tokens: int | None = None
    decode_tps: float | None = None   # (output_tokens - 1) / (latency - ttft)
    error: str = ""
    started_at: float = field(default=0.0, repr=False)


def stream_once(base: str, key: str, model: str, prompt: str, max_tokens: int,
                concurrency: int, seq: int, timeout: float) -> Result:
    body = {"model": model, "stream": True, "max_tokens": max_tokens, "temperature": 0,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(base + "/v1/chat/completions", method="POST",
                                 data=json.dumps(body).encode())
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    t0 = time.perf_counter()
    res = Result(concurrency, seq, 0, False, started_at=time.time())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            res.status = resp.status
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                if line == "data: [DONE]":
                    break
                chunk = json.loads(line[5:])
                if chunk.get("usage"):
                    res.output_tokens = chunk["usage"].get("completion_tokens")
                    res.prompt_tokens = chunk["usage"].get("prompt_tokens")
                choices = chunk.get("choices") or []
                if res.ttft_s is None and choices and choices[0].get("delta", {}).get("content"):
                    res.ttft_s = time.perf_counter() - t0
        res.latency_s = time.perf_counter() - t0
        res.ok = res.status == 200 and res.ttft_s is not None
        if res.ok and res.output_tokens and res.output_tokens > 1 and res.latency_s > res.ttft_s:
            res.decode_tps = (res.output_tokens - 1) / (res.latency_s - res.ttft_s)
        if not res.ok and not res.error:
            res.error = "no content received"
    except urllib.error.HTTPError as e:
        res.status, res.latency_s = e.code, time.perf_counter() - t0
        res.error = f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001 - record and keep going
        res.latency_s = time.perf_counter() - t0
        res.error = f"{type(e).__name__}: {e}"[:200]
    return res


# --------------------------------------------------------------------------
# a concurrency level
# --------------------------------------------------------------------------
@dataclass
class LevelSummary:
    concurrency: int
    requests: int
    ok: int
    http_429: int
    other_errors: int
    wall_s: float
    req_per_s: float
    ttft_p50_s: float | None
    ttft_p95_s: float | None
    latency_p50_s: float | None
    latency_p95_s: float | None
    decode_tps_p50: float | None      # per-request generation speed
    output_tokens_total: int
    throughput_tps: float             # all output tokens / wall time


def summarize(concurrency: int, results: list[Result], wall_s: float) -> LevelSummary:
    ok = [r for r in results if r.ok]
    out_tokens = sum(r.output_tokens or 0 for r in ok)
    return LevelSummary(
        concurrency=concurrency,
        requests=len(results),
        ok=len(ok),
        http_429=sum(1 for r in results if r.status == 429),
        other_errors=sum(1 for r in results if not r.ok and r.status != 429),
        wall_s=wall_s,
        req_per_s=len(ok) / wall_s if wall_s > 0 else 0.0,
        ttft_p50_s=percentile([r.ttft_s for r in ok], 50),
        ttft_p95_s=percentile([r.ttft_s for r in ok], 95),
        latency_p50_s=percentile([r.latency_s for r in ok], 50),
        latency_p95_s=percentile([r.latency_s for r in ok], 95),
        decode_tps_p50=percentile([r.decode_tps for r in ok if r.decode_tps], 50),
        output_tokens_total=out_tokens,
        throughput_tps=out_tokens / wall_s if wall_s > 0 else 0.0,
    )


def run_level(base: str, key: str, model: str, prompts: list[str], concurrency: int,
              n_requests: int, max_tokens: int, timeout: float) -> tuple[list[Result], float]:
    """Closed loop: `concurrency` workers each pull the next request until n are done."""
    counter = iter(range(n_requests))
    lock = threading.Lock()
    results: list[Result] = []

    def worker():
        while True:
            with lock:
                seq = next(counter, None)
            if seq is None:
                return
            r = stream_once(base, key, model, prompts[seq % len(prompts)], max_tokens,
                            concurrency, seq, timeout)
            with lock:
                results.append(r)

    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=concurrency) as pool:
        for f in [pool.submit(worker) for _ in range(concurrency)]:
            f.result()
    return sorted(results, key=lambda r: r.seq), time.perf_counter() - t0


# --------------------------------------------------------------------------
# environment & reporting
# --------------------------------------------------------------------------
def environment(env: dict[str, str], model: str, key_label: str, args) -> dict[str, str]:
    def sh(cmd: list[str]) -> str:
        try:
            return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                                  timeout=30).stdout.strip()
        except Exception:  # noqa: BLE001
            return ""
    gpu = sh(["docker", "compose", "exec", "-T", "ollama", "nvidia-smi",
              "--query-gpu=name,memory.total", "--format=csv,noheader"])
    ollama_ver = sh(["docker", "compose", "exec", "-T", "ollama", "ollama", "--version"])
    return {
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "git_commit": sh(["git", "rev-parse", "--short", "HEAD"]),
        "gateway_model_alias": model,
        "backend_model": env.get("OLLAMA_CHAT_MODEL", "?"),
        "ollama_version": ollama_ver.splitlines()[-1].split()[-1] if ollama_ver else "?",
        "ollama_num_parallel": env.get("OLLAMA_NUM_PARALLEL", "4 (default)"),
        "gpu": gpu or "n/a (CPU or not visible)",
        "key": key_label,
        "max_tokens": str(args.max_tokens),
        "requests_per_level": str(args.requests) if args.requests else "max(8, 4 x concurrency)",
        "prompts": f"{PROMPTS_FILE.relative_to(REPO).as_posix()} ({len(load_prompts())} prompts)",
        "backend_restart_per_level": "yes" if args.restart_backend else "no",
    }


def restart_backend(timeout: float = 120) -> None:
    """Restart the Ollama container and wait until its healthcheck passes."""
    base = ["docker", "compose", "--profile", "platform"]
    subprocess.run(base + ["restart", "ollama"], cwd=REPO, capture_output=True, check=True,
                   timeout=timeout)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        h = subprocess.run(base + ["ps", "ollama", "--format", "{{.Health}}"], cwd=REPO,
                           capture_output=True, text=True).stdout.strip()
        if h == "healthy":
            return
        time.sleep(2)
    raise RuntimeError("ollama did not become healthy after restart")


def fmt(v, digits=2, unit=""):
    return "–" if v is None else f"{v:.{digits}f}{unit}"


def render_markdown(meta: dict[str, str], summaries: list[LevelSummary]) -> str:
    lines = ["# Gateway load test", "", "## Environment", "", "| | |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in meta.items()]
    lines += ["", "## Results", "",
              "| Concurrency | OK / total | 429 | Other err | TTFT p50 | TTFT p95 | Latency p50 | "
              "Latency p95 | Decode tok/s p50 (per req) | Throughput tok/s (all) | Req/s |",
              "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for s in summaries:
        lines.append(
            f"| {s.concurrency} | {s.ok} / {s.requests} | {s.http_429} | {s.other_errors} | "
            f"{fmt(s.ttft_p50_s, 3, ' s')} | {fmt(s.ttft_p95_s, 3, ' s')} | "
            f"{fmt(s.latency_p50_s, 2, ' s')} | {fmt(s.latency_p95_s, 2, ' s')} | "
            f"{fmt(s.decode_tps_p50, 1)} | {fmt(s.throughput_tps, 1)} | {fmt(s.req_per_s, 2)} |")
    lines += ["", "Definitions:",
              "- **TTFT**: request sent → first content token received (client side, via gateway).",
              "- **Latency**: request sent → stream finished.",
              "- **Decode tok/s (per req)**: (output tokens − 1) / (latency − TTFT); generation speed one user sees.",
              "- **Throughput tok/s (all)**: all output tokens in the level / wall-clock time of the level.",
              "- Percentiles over successful requests only; 429 and other errors are counted separately.", ""]
    return "\n".join(lines)


def load_prompts() -> list[str]:
    return [json.loads(line)["prompt"] for line in PROMPTS_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()]


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-c", "--concurrency", default="1,2,4,8,16",
                    help="comma-separated concurrency levels (default 1,2,4,8,16)")
    ap.add_argument("-n", "--requests", type=int, default=0,
                    help="requests per level (default max(8, 4 x concurrency))")
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--model", default="chat-default")
    ap.add_argument("--key-env", default="",
                    help="use this .env variable's key instead of a temporary unlimited key")
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--no-warmup", action="store_true")
    ap.add_argument("--restart-backend", action="store_true",
                    help="restart Ollama + warm up before each level (comparable levels)")
    ap.add_argument("--out", type=Path, default=None, help="output dir (default results/<ts>)")
    args = ap.parse_args(argv)

    env = load_env(REPO / ".env")
    base = os.environ.get("LITELLM_URL", f"http://127.0.0.1:{env.get('LITELLM_PORT', '4000')}")
    master = env.get("LITELLM_MASTER_KEY", "")
    levels = [int(x) for x in args.concurrency.split(",") if x.strip()]
    prompts = load_prompts()

    temp_alias = None
    if args.key_env:
        key = env.get(args.key_env, "")
        if not key:
            print(f"ERROR: {args.key_env} not set in .env", file=sys.stderr)
            return 2
        key_label = f"{args.key_env} ({mask(key)}, app limits apply)"
    else:
        temp_alias = f"loadtest-{int(time.time())}"
        status, body = api(base, master, "POST", "/key/generate",
                           {"key_alias": temp_alias, "models": [args.model],
                            "metadata": {"managed_by": "loadtest/bench.py"}})
        if status != 200:
            print(f"ERROR: could not create temporary key (HTTP {status})", file=sys.stderr)
            return 2
        key = body["key"]
        key_label = f"temporary {temp_alias} ({mask(key)}, no limits)"

    out = args.out or RESULTS_DIR / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, exist_ok=True)
    summaries: list[LevelSummary] = []
    all_results: list[Result] = []
    try:
        meta = environment(env, args.model, key_label, args)
        print(f"key: {key_label}\noutput: {out}")
        def warmup():
            w = stream_once(base, key, args.model, prompts[0], 16, 0, -1, args.timeout)
            print(f"warmup: HTTP {w.status} ttft={fmt(w.ttft_s, 3, 's')}")

        if not args.no_warmup and not args.restart_backend:
            warmup()
        for c in levels:
            if args.restart_backend:
                restart_backend()
                warmup()
            n = args.requests or max(8, 4 * c)
            results, wall = run_level(base, key, args.model, prompts, c, n, args.max_tokens, args.timeout)
            s = summarize(c, results, wall)
            summaries.append(s)
            all_results += results
            print(f"c={c:<3} ok={s.ok}/{s.requests} 429={s.http_429} err={s.other_errors} "
                  f"ttft p50/p95={fmt(s.ttft_p50_s, 3)}/{fmt(s.ttft_p95_s, 3)}s "
                  f"lat p95={fmt(s.latency_p95_s)}s decode p50={fmt(s.decode_tps_p50, 1)} tok/s "
                  f"throughput={fmt(s.throughput_tps, 1)} tok/s")
    finally:
        if temp_alias:
            api(base, master, "POST", "/key/delete", {"key_aliases": [temp_alias]})

    with open(out / "requests.csv", "w", newline="", encoding="utf-8") as f:
        cols = [k for k in asdict(Result(0, 0, 0, False)) if k != "started_at"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(asdict(r) for r in all_results)
    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(summaries[0]).keys()) if summaries else [])
        w.writeheader()
        w.writerows(asdict(s) for s in summaries)
    (out / "summary.md").write_text(render_markdown(meta, summaries), encoding="utf-8", newline="\n")
    (out / "environment.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                                          encoding="utf-8", newline="\n")
    print(f"wrote {out / 'summary.md'}")
    failed = any(s.other_errors for s in summaries)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
