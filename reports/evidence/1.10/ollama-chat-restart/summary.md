# Gateway load test

## Environment

| | |
|---|---|
| timestamp_utc | 2026-11-27 06:28:06 |
| git_commit | 83906da |
| gateway_model_alias | chat-default |
| backend_model | qwen2.5:7b-instruct |
| ollama_version | 0.40.18 |
| ollama_num_parallel | 4 (default) |
| gpu | NVIDIA GeForce RTX 4070 Ti, 12282 MiB |
| key | temporary loadtest-1795760885 (sk-…cUzg, no limits) |
| max_tokens | 256 |
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

Definitions:
- **TTFT**: request sent → first content token received (client side, via gateway).
- **Latency**: request sent → stream finished.
- **Decode tok/s (per req)**: (output tokens − 1) / (latency − TTFT); generation speed one user sees.
- **Throughput tok/s (all)**: all output tokens in the level / wall-clock time of the level.
- Percentiles over successful requests only; 429 and other errors are counted separately.
