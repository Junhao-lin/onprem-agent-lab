# Gateway load test

## Environment

| | |
|---|---|
| timestamp_utc | 2026-11-27 06:57:34 |
| git_commit | 4d59b37 |
| gateway_model_alias | chat-default |
| backend_model | qwen2.5:7b-instruct |
| ollama_version | 0.40.18 |
| ollama_num_parallel | 4 (default) |
| gpu | NVIDIA GeForce RTX 4070 Ti, 12282 MiB |
| key | temporary loadtest-1795762653 (sk-…hbgA, no limits) |
| max_tokens | 256 |
| requests_per_level | max(8, 4 x concurrency) |
| prompts | loadtest/prompts.jsonl (8 prompts) |
| backend_restart_per_level | no |

## Results

| Concurrency | OK / total | 429 | Other err | TTFT p50 | TTFT p95 | Latency p50 | Latency p95 | Decode tok/s p50 (per req) | Throughput tok/s (all) | Req/s |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 8 / 8 | 0 | 0 | 0.028 s | 0.031 s | 3.01 s | 3.10 s | 85.5 | 85.1 | 0.33 |

Definitions:
- **TTFT**: request sent → first content token received (client side, via gateway).
- **Latency**: request sent → stream finished.
- **Decode tok/s (per req)**: (output tokens − 1) / (latency − TTFT); generation speed one user sees.
- **Throughput tok/s (all)**: all output tokens in the level / wall-clock time of the level.
- Percentiles over successful requests only; 429 and other errors are counted separately.
