# [Bug]: `max_parallel_requests` counter drifts on requests rejected before the LLM call (401 model-not-allowed: −1, 400 from a pre-call hook: +1)

> **Draft, not submitted.** Prepared from this repo's platform tests (task 1.9, re-measured 2026-11-27).
> Before filing:
> - search existing issues for "max_parallel_requests" / "parallel_request_limiter_v3";
> - re-run on the latest LiteLLM release;
> - replace the repo-specific harness below with the minimal setup.

## What happened?

A virtual key has `max_parallel_requests` set, and Redis is configured for the rate limiter.
Requests that fail **before the LLM call** change the key's parallel-request counter in Redis,
with no matching change in the other direction:

| Request (key allowed only `chat-default`, `max_parallel_requests: 2`) | HTTP | Counter change (observed) | Expected |
|---|---|---|---|
| `/v1/embeddings` or `/v1/chat/completions` for a model **not in the key's `models`** | 401 | **−1** per request | 0 |
| `/v1/chat/completions` whose `messages` is a list of strings | 400 | **+1** per request | 0 |
| normal chat completion, streaming or not | 200 | 0 | 0 |

The counter key is `{api_key:<sha256(key)>}:max_parallel_requests`. Its TTL is reset to the
limiter window (60 s) on every update (observed `ttl = 58–59s` after each step), so the drift
lasts as long as the key keeps sending requests at least once a minute.

### Impact (observed)

- **Limit bypass:** after three 401s the counter is −3. The key, limited to 2, then had
  **3 concurrent streams all accepted (200, 200, 200)** instead of `200, 200, 429`.
- **False 429:** after two malformed requests the counter is +2. The key's next ordinary request,
  with nothing in flight, was **rejected with 429**.
- Neither effect is visible in metrics (see *Related*). The 401s are not counted at all.

### Impact (inferred, not measured)

- If the limiter admits a request while `counter < limit`, a key with counter −N can run up to
  `limit + N` requests at once. We only measured N = 3 with 3 streams, not the upper bound.
- A client could therefore raise its own concurrency ceiling by sending requests for a model it
  is not allowed to use. This could happen by mistake (a misconfigured model name) or on purpose.

In our deployment the damage is bounded: the inference backend (Ollama, 4 slots) is the hard
limit, and the two app keys' limits sum to those 4 slots. Still, a per-key limit that a client
can raise defeats per-tenant isolation.

## Steps to reproduce

1. Run a LiteLLM proxy with Redis as the limiter store and two models, `chat-default` and
   `embed-default`. This repo uses `litellm_settings.cache: true` with
   `cache_params: {type: redis, mode: default_off}`, plus `router_settings.redis_host/port/password`.
2. Create a key that is allowed one model and limited to 2 parallel requests:
   ```bash
   curl -s localhost:4000/key/generate -H "Authorization: Bearer $MASTER" \
     -H 'Content-Type: application/json' \
     -d '{"models": ["chat-default"], "max_parallel_requests": 2}'
   ```
3. Read the counter, and its TTL, after each step:
   ```bash
   K="{api_key:$(printf %s "$KEY" | sha256sum | cut -d' ' -f1)}:max_parallel_requests"
   redis-cli get "$K"; redis-cli ttl "$K"
   ```
4. **Scenario A:**
   1. Send one allowed chat completion.
   2. Send two `/v1/embeddings` requests and one `/v1/chat/completions` request with
      `"model": "embed-default"`. Each returns 401.
   3. Open 3 streaming chat completions at the same time.
5. **Scenario B**, on a fresh key:
   1. Send one allowed chat completion.
   2. Send two chat completions with `"messages": ["not-an-object"]`. Each returns 400.
   3. Send one allowed chat completion.

**Verified only with this repo's harness.** [`repro_parallel_counter.py`](repro_parallel_counter.py)
does exactly these steps against this repo's Docker Compose stack:
- it needs the stack running and reads the master key from `.env`;
- it uses a separate disposable key per scenario and confirms each key is deleted afterwards;
- it prints masked keys only;
- it reads the counter only after two consecutive reads agree, because failure callbacks run asynchronously.

### Observed output (2026-11-27, raw file `reports/raw/C/repro-output.txt`)

```
run 2026-11-27 00:04:24 against http://127.0.0.1:4000
litellm version: 1.83.14

=== A: requests for a model the key is not allowed to use (401) ===
key pytest-tmp-repro-a-1795709064835 (sk-…W2Lw): models=['chat-default'], max_parallel_requests=2
A0. fresh key                                                  HTTP -    counter = (nil) ttl = -2s
A1. allowed chat completion (expect 0)                         HTTP 200  counter = 0     ttl = 59s
A2.1 /v1/embeddings, model not allowed -> 401 (expect 0)       HTTP 401  counter = -1    ttl = 59s
A2.2 /v1/embeddings, model not allowed -> 401 (expect 0)       HTTP 401  counter = -2    ttl = 59s
A3. /v1/chat/completions, model not allowed -> 401 (expect 0)  HTTP 401  counter = -3    ttl = 59s
A4. impact: open 3 concurrent streams on this key (limit 2)
    statuses: [200, 200, 200]  (a correct limiter answers the 3rd with 429)
A5. after the streams finished                                 HTTP -    counter = -3    ttl = 56s

=== B: malformed request rejected in a pre-call hook (400) ===
key pytest-tmp-repro-b-1795709072484 (sk-…Uz1w): models=['chat-default'], max_parallel_requests=2
B0. fresh key                                                  HTTP -    counter = (nil) ttl = -2s
B1. allowed chat completion (expect 0)                         HTTP 200  counter = 0     ttl = 59s
B2.1 messages is a list of strings -> 400 (expect 0)           HTTP 400  counter = 1     ttl = 58s
B2.2 messages is a list of strings -> 400 (expect 0)           HTTP 400  counter = 2     ttl = 58s
B3. impact: one allowed chat, nothing in flight (expect 200)   HTTP 429  counter = 2     ttl = 59s
```

## Possible cause: hypothesis from reading the 1.83.14 source, not verified with a debugger

Paths are under `site-packages/litellm/`. Line numbers refer to the 1.83.14 image.

What the source shows:

- `proxy/hooks/parallel_request_limiter_v3.py`:
  - `async_pre_call_hook` (line 1277) checks the limits and increments the counters.
  - The success path decrements the parallel counter (`increment_value=-1`, around line 1593–1604).
  - `async_log_failure_event` (line 1761) decrements it whenever the logging metadata contains
    `user_api_key_hash` (lines 1783–1796). Nothing there checks whether this request ever incremented the counter.
- `proxy/auth/auth_checks.py:2786` raises the "… not allowed to access model" `ProxyException`
  during auth.
- The 400 is raised in `litellm_enterprise/proxy/hooks/managed_files.py:632`
  (`get_file_ids_from_messages`, `AttributeError: 'str' object has no attribute 'get'`). The
  trace below shows it reached through `proxy/utils.py:1433` (`pre_call_hook` iterating callbacks).

Hypothesis, consistent with the observations but not traced:

- **401:** rejected in auth, before the limiter's pre-call hook increments. The failure is still
  logged with the key hash, so `async_log_failure_event` decrements a counter that was never
  incremented → −1.
- **400:** raised by a callback that runs after the limiter's pre-call hook has incremented. That
  path never reaches `async_log_failure_event` (or another decrement), so the +1 stays.

A fix would pair the increment and the decrement explicitly. For example, record in the request
metadata that this request incremented the counter, and decrement only in that case, on every
exit path, including exceptions in later pre-call hooks.

## Relevant log output (400 case, excerpt)

```
File ".../litellm/proxy/utils.py", line 1433, in pre_call_hook
    response = await _callback.async_pre_call_hook(
File ".../litellm_enterprise/proxy/hooks/managed_files.py", line 632, in get_file_ids_from_messages
    if message.get("role") == "user":
AttributeError: 'str' object has no attribute 'get'
INFO: ... "POST /v1/chat/completions HTTP/1.1" 400 Bad Request
```

## Related observations (same version, possibly separate issues)

- Auth-stage 401s (wrong key, model not allowed) are **not counted** in any Prometheus metric:
  `litellm_proxy_failed_requests_metric_total` does not change. Pinned in this repo by
  `tests/platform/test_dashboards.py::test_auth_rejections_are_not_metered`.
- The malformed-request 400 **is** counted in `litellm_proxy_failed_requests_metric_total`, but
  with `exception_status="None"` and `exception_class="AttributeError"` instead of `400`.
- A malformed `messages` list should probably fail request validation before it reaches
  `managed_files.py`. The `AttributeError` there looks like a bug of its own.

## Versions

| | |
|---|---|
| LiteLLM | 1.83.14 (`ghcr.io/berriai/litellm-database:main-v1.83.14-stable`, digest `sha256:da4ab06d9d57da205263877425544d6df8e78147737b0dd8dc1e9e93a6d8ac2e`), reported by `/health/readiness` |
| Python in image | 3.13.13 |
| Redis | `redis:7-alpine` (password auth) |
| Postgres | `postgres:16-alpine` |
| Backend | Ollama 0.40.18 via the `openai/` provider. The backend should not matter, since both failures happen before the call. |
| Host | Windows 11 + Docker Desktop (WSL2) |

## How this repo handles it (no mitigation, by decision)

- `tests/platform/test_dashboards.py::test_auth_rejection_does_not_skew_parallel_counter` is
  marked `xfail(strict=True)`. Once an upgrade fixes the bug, the test fails, as a reminder to
  remove the xfail and the README note.
- Tests that check parallel limits use a key that never receives auth-rejected requests.
- The README section "已知限制" documents the risk. No gateway-side protection was added.
