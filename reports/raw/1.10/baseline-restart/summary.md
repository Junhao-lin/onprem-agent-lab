# Gateway load test

## Environment

| | |
|---|---|
| timestamp_utc | 2026-11-26 13:20:30 |
| git_commit | e7f9df1 |
| gateway_model_alias | chat-default |
| backend_model | qwen2.5:7b-instruct |
| ollama_version | 0.40.18 |
| ollama_num_parallel | 4 (default) |
| gpu | NVIDIA GeForce RTX 4070 Ti, 12282 MiB |
| key | temporary loadtest-1795699229 (sk-…RNeg, no limits) |
| max_tokens | 256 |
| requests_per_level | max(8, 4 x concurrency) |
| prompts | loadtest/prompts.jsonl (8 prompts) |
| backend_restart_per_level | yes |

## Results

| Concurrency | OK / total | 429 | Other err | TTFT p50 | TTFT p95 | Latency p50 | Latency p95 | Decode tok/s p50 (per req) | Throughput tok/s (all) | Req/s |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 8 / 8 | 0 | 0 | 0.047 s | 0.056 s | 3.01 s | 3.04 s | 86.2 | 85.3 | 0.33 |
| 2 | 8 / 8 | 0 | 0 | 0.068 s | 0.086 s | 3.17 s | 3.23 s | 81.8 | 161.0 | 0.63 |
| 4 | 16 / 16 | 0 | 0 | 0.119 s | 0.132 s | 3.54 s | 3.61 s | 74.5 | 288.6 | 1.13 |
| 8 | 32 / 32 | 0 | 0 | 3.742 s | 3.823 s | 7.33 s | 7.47 s | 71.0 | 280.4 | 1.10 |
| 16 | 64 / 64 | 0 | 0 | 10.699 s | 10.769 s | 14.17 s | 14.25 s | 73.3 | 288.4 | 1.13 |

Definitions:
- **TTFT**: request sent → first content token received (client side, via gateway).
- **Latency**: request sent → stream finished.
- **Decode tok/s (per req)**: (output tokens − 1) / (latency − TTFT); generation speed one user sees.
- **Throughput tok/s (all)**: all output tokens in the level / wall-clock time of the level.
- Percentiles over successful requests only; 429 and other errors are counted separately.
