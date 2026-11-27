"""Reproduce the Ollama 0.40.18 post-oversubscription slowdown (ops risk in the baseline report).

    python -I loadtest/repro_degradation.py [--out DIR] [--cycles 2]

Sequence, each step a separate bench.py run with its own temporary key:
  1. fresh       restart Ollama + warm-up, then c=2         (reference)
  2. overload    c=8 (more streams than OLLAMA_NUM_PARALLEL=4), no restart
  3. after-1     c=2, no restart
  4. after-2     c=2 again, no restart                       (does it persist?)
  5. c4-after    c=4, no restart                             (are other levels affected?)
  6. c1-after    c=1, no restart
  7. restarted   restart Ollama + warm-up, then c=2         (recovery)
Steps 1-7 repeat `--cycles` times. Writes per-step bench output plus
summary.md / summary.csv with one row per step.
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "scripts"))
from bench import csv_text  # noqa: E402
from rawlog import write_raw  # noqa: E402  (every output file is masked before writing)
STEPS = [  # name, concurrency, restart before
    ("fresh", 2, True),
    ("overload", 8, False),
    ("after-1", 2, False),
    ("after-2", 2, False),
    ("c4-after", 4, False),
    ("c1-after", 1, False),
    ("restarted", 2, True),
]
COLS = ["cycle", "step", "concurrency", "ok", "requests", "ttft_p95_s", "latency_p50_s",
        "decode_tps_p50", "throughput_tps"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path,
                    default=HERE / "results" / ("degradation-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")))
    ap.add_argument("--cycles", type=int, default=2)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    rows = []
    for cycle in range(1, args.cycles + 1):
        for name, c, restart in STEPS:
            step_out = args.out / f"cycle{cycle}-{name}"
            cmd = [sys.executable, "-I", str(HERE / "bench.py"), "-c", str(c), "--out", str(step_out)]
            if restart:
                cmd.append("--restart-backend")
            print(f"[cycle {cycle}] {name}: c={c}{' (restart)' if restart else ''}", flush=True)
            proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8")
            write_raw(args.out / f"cycle{cycle}-{name}.log", proc.stdout + proc.stderr)
            if proc.returncode != 0:
                print(proc.stdout[-2000:] + proc.stderr[-2000:])
                return proc.returncode
            with open(step_out / "summary.csv", encoding="utf-8") as f:
                s = next(csv.DictReader(f))
            rows.append({"cycle": cycle, "step": name, **{k: s[k] for k in COLS[2:]}})
            r = rows[-1]
            print(f"    throughput {float(r['throughput_tps']):.1f} tok/s, "
                  f"decode p50 {float(r['decode_tps_p50']):.1f} tok/s/req, TTFT p95 {float(r['ttft_p95_s']):.3f} s",
                  flush=True)

    write_raw(args.out / "summary.csv", csv_text(COLS, rows))
    lines = ["| Cycle | Step | c | OK | TTFT p95 | Latency p50 | Decode tok/s p50 (per req) | Throughput tok/s (all) |",
             "|---:|---|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        lines.append(f"| {r['cycle']} | {r['step']} | {r['concurrency']} | {r['ok']}/{r['requests']} | "
                     f"{float(r['ttft_p95_s']):.3f} s | {float(r['latency_p50_s']):.2f} s | "
                     f"{float(r['decode_tps_p50']):.1f} | {float(r['throughput_tps']):.1f} |")
    write_raw(args.out / "summary.md", "\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
