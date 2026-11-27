# Gateway load test

## Environment

| | |
|---|---|
| timestamp_utc | 2026-11-26 13:10:43 |
| git_commit | e7f9df1 |
| gateway_model_alias | chat-default |
| backend_model | qwen2.5:7b-instruct |
| ollama_version | 0.40.18 |
| ollama_num_parallel | 4 (default) |
| gpu | NVIDIA GeForce RTX 4070 Ti, 12282 MiB |
| key | temporary loadtest-1795698642 (sk-…sn7A, no limits) |
| max_tokens | 256 |
| requests_per_level | max(8, 4 x concurrency) |
| prompts | loadtest/prompts.jsonl (8 prompts) |

## Results

| Concurrency | OK / total | 429 | Other err | TTFT p50 | TTFT p95 | Latency p50 | Latency p95 | Decode tok/s p50 (per req) | Throughput tok/s (all) | Req/s |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 8 / 8 | 0 | 0 | 0.058 s | 0.080 s | 3.04 s | 3.08 s | 85.3 | 84.1 | 0.33 |
| 2 | 8 / 8 | 0 | 0 | 0.076 s | 0.104 s | 3.28 s | 3.32 s | 79.7 | 156.0 | 0.61 |
| 4 | 16 / 16 | 0 | 0 | 0.140 s | 5.324 s | 3.71 s | 8.92 s | 71.3 | 204.5 | 0.80 |
| 8 | 32 / 32 | 0 | 0 | 3.755 s | 3.823 s | 7.40 s | 7.96 s | 70.0 | 271.8 | 1.06 |
| 16 | 64 / 64 | 0 | 0 | 11.102 s | 11.457 s | 14.74 s | 15.18 s | 69.9 | 276.0 | 1.08 |

Definitions:
- **TTFT**: request sent → first content token received (client side, via gateway).
- **Latency**: request sent → stream finished.
- **Decode tok/s (per req)**: (output tokens − 1) / (latency − TTFT); generation speed one user sees.
- **Throughput tok/s (all)**: all output tokens in the level / wall-clock time of the level.
- Percentiles over successful requests only; 429 and other errors are counted separately.
