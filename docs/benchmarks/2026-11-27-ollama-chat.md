# Re-run after the provider change: `ollama_chat/` (2026-11-27)

Same sweep as the [2026-11-26 baseline](2026-11-26-baseline.md), re-run after `chat-default` was
switched from LiteLLM's `openai/` provider (Ollama's OpenAI-compatible `/v1`) to `ollama_chat/`
(Ollama's native `/api/chat`). The switch fixed the spend-log gaps
(`reports/raw/spendlog/FINDINGS.md`). Only the gateway-to-Ollama path changed. Ollama, the model,
the GPU, `OLLAMA_NUM_PARALLEL` and the load script are the same.

- Command: `python loadtest/bench.py --restart-backend`, with a temporary key (`loadtest-*`, no limits)
  that was deleted afterwards. The script checks the deletion and would exit with code 3 if it failed.
  It exited with 0.
- Raw files: `reports/raw/1.10/ollama-chat-restart/`. The old run is in `reports/raw/1.10/baseline-restart/`.

## Environment

| | |
|---|---|
| timestamp_utc | 2026-11-27 06:28:06 |
| git_commit | 83906da |
| gateway_model_alias | chat-default → `ollama_chat/qwen2.5:7b-instruct`, `api_base http://ollama:11434` |
| backend_model | qwen2.5:7b-instruct |
| ollama_version | 0.40.18 |
| ollama_num_parallel | 4 (default) |
| gpu | NVIDIA GeForce RTX 4070 Ti, 12282 MiB |
| key | temporary loadtest-1795760885 (sk-…cUzg, no limits; deleted) |
| max_tokens | 256 (all 128 answers hit the cap) |
| requests_per_level | max(8, 4 x concurrency) |
| prompts | loadtest/prompts.jsonl (8 prompts) |
| backend_restart_per_level | yes |

## Results

| Concurrency | OK / total | 429 | Other err | TTFT p50 | TTFT p95 | Latency p50 | Latency p95 | Decode tok/s p50 (per req) | Throughput tok/s (all) | Req/s |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 8 / 8 | 0 | 0 | 0.039 s | 0.054 s | 3.13 s | 3.15 s | 82.5 | 81.7 | 0.32 |
| 2 | 8 / 8 | 0 | 0 | 0.070 s | 0.075 s | 3.37 s | 3.37 s | 77.3 | 152.1 | 0.59 |
| 4 | 16 / 16 | 0 | 0 | 0.121 s | 0.147 s | 3.70 s | 3.78 s | 71.1 | 275.5 | 1.08 |
| 8 | 32 / 32 | 0 | 0 | 3.742 s | 3.780 s | 7.36 s | 7.41 s | 70.3 | 277.5 | 1.08 |
| 16 | 64 / 64 | 0 | 0 | 11.458 s | 11.569 s | 15.18 s | 15.24 s | 68.5 | 269.8 | 1.05 |

The shape is unchanged. Throughput still saturates at c = 4 = `OLLAMA_NUM_PARALLEL`: 82 → 152 → 276
tok/s, then flat at 270–278. Beyond 4, extra concurrency only adds queueing: TTFT p95 is 3.8 s at
c = 8 and 11.6 s at c = 16. The gateway limits (2 + 2 = 4 parallel) remain correct.

## Provider change: before vs after

"Old" is `openai/` via `/v1` (2026-11-26, `baseline-restart/`). "New" is `ollama_chat/` via
`/api/chat` (this run). Δ = (new − old) / old.

| c | TTFT p95 old | TTFT p95 new | Δ | Decode tok/s per req old | new | Δ | Throughput tok/s old | new | Δ |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.056 s | 0.054 s | −3.3 % | 86.2 | 82.5 | −4.4 % | 85.3 | 81.7 | −4.3 % |
| 2 | 0.086 s | 0.075 s | **−12.5 %** | 81.8 | 77.3 | −5.5 % | 161.0 | 152.1 | −5.6 % |
| 4 | 0.132 s | 0.147 s | **+10.8 %** | 74.5 | 71.1 | −4.5 % | 288.6 | 275.5 | −4.5 % |
| 8 | 3.823 s | 3.780 s | −1.1 % | 71.0 | 70.3 | −1.0 % | 280.4 | 277.5 | −1.0 % |
| 16 | 10.769 s | 11.569 s | +7.4 % | 73.3 | 68.5 | −6.5 % | 288.4 | 269.8 | −6.4 % |

**Throughput and per-request decode speed: within 10 %, but consistently lower.** Every level is
1–6.5 % lower, and none is higher. One run per level cannot separate this from run-to-run variance
on a shared desktop. But because the drop shows up at every level, it may be a real, small
cost of the new path. Possible causes (not verified):

1. **More work per chunk in the gateway.** With `ollama_chat/`, LiteLLM parses Ollama's native
   NDJSON stream and builds a new OpenAI-style chunk for each token. The fresh id on every chunk,
   the known side effect in the README, shows the chunks are rebuilt. Under `/v1`, Ollama already
   sent OpenAI-format chunks. About 0.1 s more per 256-token answer (≈ 0.5 ms per token) would
   explain the −4 to −6 %.
2. **Machine state.** The run happened on a different day, with other GPU clients on the desktop
   (16 % GPU use before the run).

A cheap way to tell these apart: measure decode speed directly against Ollama `/v1` and `/api/chat`
from inside the network, without the gateway. This was not done.

**TTFT p95: two cells exceed 10 %, in opposite directions.** At c = 2 it is −12.5 %, and at c = 4
it is +10.8 %. In absolute terms these are −11 ms and +15 ms. With 8 or 16 requests per level,
p95 is essentially the slowest request, so a single request moves it. TTFT p50 at c = 2 and c = 4 changed by
only +2 % and +1 %. Read as noise, not as an effect of the provider. At c = 16, TTFT is +7 %. That
follows from the slower decoding: queued requests wait for whole generations, and those
take about 7 % longer (latency p50 +7.1 %).

**Conclusion: re-measured with the new setting, results are consistent.** Throughput and
per-request speed are within 10 % of the old numbers at every level, with a small systematic
drop of about 1–6 %. TTFT changes are milliseconds of noise below saturation. Saturation point
and capacity planning are unchanged.

## Not re-run

- `loadtest/repro_degradation.py` (the c = 2 degradation after an overload). That state lives in
  the Ollama process, so the provider change should not affect it, but this was not verified.
  Its numbers in the baseline report are still from `/v1`.

## Caveats

Same as the baseline: shared desktop machine, one repetition per level, small samples, and
output fixed at `max_tokens=256`.
