# Gateway load test

## Environment

| | |
|---|---|
| timestamp_utc | 2026-11-26 15:35:47 |
| git_commit | b6a611a |
| gateway_model_alias | chat-default |
| backend_model | qwen2.5:7b-instruct |
| ollama_version | 0.40.18 |
| ollama_num_parallel | 4 (default) |
| gpu | NVIDIA GeForce RTX 4070 Ti, 12282 MiB |
| key | temporary loadtest-1795707346 (sk-…dEXQ, no limits) |
| max_tokens | 256 |
| requests_per_level | max(8, 4 x concurrency) |
| prompts | loadtest/prompts.jsonl (8 prompts) |
| backend_restart_per_level | no |

## Results

| Concurrency | OK / total | 429 | Other err | TTFT p50 | TTFT p95 | Latency p50 | Latency p95 | Decode tok/s p50 (per req) | Throughput tok/s (all) | Req/s |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 | 32 / 32 | 0 | 0 | 3.502 s | 3.531 s | 6.88 s | 6.91 s | 75.4 | 297.1 | 1.16 |

Definitions:
- **TTFT**: request sent → first content token received (client side, via gateway).
- **Latency**: request sent → stream finished.
- **Decode tok/s (per req)**: (output tokens − 1) / (latency − TTFT); generation speed one user sees.
- **Throughput tok/s (all)**: all output tokens in the level / wall-clock time of the level.
- Percentiles over successful requests only; 429 and other errors are counted separately.
