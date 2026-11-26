# [Bug]: `max_parallel_requests` counter drifts on requests rejected before the call (401 model-not-allowed: −1, 400 in pre-call hook: +1)

> **Draft — not submitted.** Prepared from this repo's platform tests (task 1.9).
> Before filing: search existing issues for "max_parallel_requests" / "parallel_request_limiter_v3",
> re-run the repro on the latest LiteLLM release, and drop the repo-specific paths.

## What happened?

With a virtual key that has `max_parallel_requests` set and Redis configured for the rate limiter,
requests that fail **before the LLM call** move the key's parallel-request counter in Redis
without a matching opposite move:

| Request | HTTP | Counter change | Expected |
|---|---|---|---|
| chat to a model **not in the key's `models` list** | 401 | **−1** per request | 0 |
| chat with malformed `messages` (a string instead of an object) | 400 | **+1** per request | 0 |
| normal successful chat | 200 | 0 (+1 then −1) | 0 |

The counter key is `{api_key:<sha256(key)>}:max_parallel_requests` with a TTL equal to the
limiter window (60 s), refreshed on each update, so the drift persists while traffic continues.

### Impact

- **Limit bypass (−1 drift):** after N "model not allowed" 401s, the key can run
  `max_parallel_requests + N` requests concurrently until the counter key expires. A client that
  sends a few requests for a disallowed model (by mistake or deliberately) raises its own
  concurrency ceiling. Observed (step 5 below): a key limited to 2 with its counter at −2 held
  3 streams with no 429.
- **False 429s (+1 drift):** each malformed request that fails inside a pre-call hook leaks one
  slot. With `max_parallel_requests: 2`, two such requests make the next legitimate request
  return 429 until the window expires.
- Metrics are not affected (see "Related" below), so the drift is invisible on dashboards.

In our deployment the impact is bounded: the inference backend (Ollama, 4 slots) is the hard
limit, and both app keys sum to those 4 slots. But a per-key limit that a client can raise by
sending bad requests defeats the purpose of per-tenant isolation.

## Steps to reproduce

1. LiteLLM proxy with Redis for rate limiting (here: `litellm_settings.cache: true`,
   `cache_params.type: redis`, `mode: default_off`; `router_settings.redis_*`), two models
   `chat-default` and `embed-default`.
2. Create a key allowed only one model and limited to 2 parallel requests:
   ```bash
   curl -s localhost:4000/key/generate -H "Authorization: Bearer $MASTER" \
     -H 'Content-Type: application/json' \
     -d '{"models": ["chat-default"], "max_parallel_requests": 2}'
   ```
3. Read the counter after each step:
   `redis-cli get "{api_key:$(printf %s "$KEY" | sha256sum | cut -d' ' -f1)}:max_parallel_requests"`
4. Send one allowed chat completion (200), then three embedding requests to the disallowed
   `embed-default` (401 each), then one chat completion whose `messages` is `["not-an-object"]`
   (400), then another allowed chat completion.

A script that does exactly this against this repo's stack is
[`repro_parallel_counter.py`](repro_parallel_counter.py) (prints masked keys only).

### Observed output

Run on 2026-11-26 against LiteLLM 1.83.14 (raw file in this repo: `reports/raw/C/repro-output.txt`):

```
key pytest-tmp-repro-counter (sk-…jrQQ): models=['chat-default'], max_parallel_requests=2

0. fresh key                                               HTTP -    counter = (nil)
1. allowed chat completion (expect counter back to 0)      HTTP 200  counter = 0
2.1 model not allowed for key -> 401 (expect unchanged)    HTTP 401  counter = -1
2.2 model not allowed for key -> 401 (expect unchanged)    HTTP 401  counter = -2
2.3 model not allowed for key -> 401 (expect unchanged)    HTTP 401  counter = -3
3. malformed messages -> 400 (expect unchanged)            HTTP 400  counter = -2
4. allowed chat completion again                           HTTP 200  counter = -2

5. impact: open 3 concurrent streams on a key limited to 2 (counter now -2)
   statuses: [200, 200, 200]  (a correct limiter answers the 3rd with 429)
6. after the streams finished                              HTTP -    counter = -2
```

The last step shows the impact directly. The key is limited to 2 parallel requests, but with its counter at −2 a third concurrent stream is accepted (200) instead of rejected (429).

## Likely cause (from reading the 1.83.14 source, not verified with a debugger)

`litellm/proxy/hooks/parallel_request_limiter_v3.py`:

- `async_pre_call_hook` increments the parallel counter when the request passes auth.
- `async_log_failure_event` **always** decrements it ("Decrement max parallel requests counter
  for the API Key", `increment_value=-1`) when `user_api_key_hash` is present in the logging
  metadata.

Hypothesis:

- The 401 "key not allowed to access model" is raised during auth, **before** the limiter's
  pre-call hook increments, but the failure is still logged with the key hash, so the failure
  callback decrements a counter that was never incremented → −1.
- The 400 from a malformed `messages` list is raised by a **later** pre-call hook
  (`litellm_enterprise/proxy/hooks/managed_files.py`, `get_file_ids_from_messages` →
  `AttributeError: 'str' object has no attribute 'get'`), i.e. after the limiter incremented,
  and that path does not reach `async_log_failure_event` → +1 never undone.

A fix would pair increment and decrement explicitly (e.g. only decrement if this request
incremented, tracked in request metadata), rather than decrementing on every failure.

## Relevant log output

The 400 case (excerpt):

```
File ".../litellm/proxy/utils.py", line 1433, in pre_call_hook
    response = await _callback.async_pre_call_hook(
File ".../litellm_enterprise/proxy/hooks/managed_files.py", line 632, in get_file_ids_from_messages
    if message.get("role") == "user":
AttributeError: 'str' object has no attribute 'get'
INFO: ... "POST /v1/chat/completions HTTP/1.1" 400 Bad Request
```

## Related observations (same version, possibly separate issues)

- Auth-stage 401s (wrong key, model not allowed) are **not counted** in any Prometheus metric
  (`litellm_proxy_failed_requests_metric_total` unchanged).
- The malformed-request 400 above **is** counted in `litellm_proxy_failed_requests_metric_total`,
  but with `exception_status="None"` and `exception_class="AttributeError"` instead of `400`.
- A malformed request should arguably be rejected with a validation error before reaching
  `managed_files.py`; the `AttributeError` there is itself a bug.

## Versions

| | |
|---|---|
| LiteLLM | 1.83.14 (`ghcr.io/berriai/litellm-database:main-v1.83.14-stable`, digest `sha256:da4ab06d9d57da205263877425544d6df8e78147737b0dd8dc1e9e93a6d8ac2e`) |
| Python in image | 3.13.13 |
| Redis | `redis:7-alpine` (password auth) |
| Postgres | `postgres:16-alpine` |
| Backend | Ollama 0.40.18 via `openai/` provider (backend is irrelevant: both failures happen before the call) |
| Host | Windows 11 + Docker Desktop (WSL2) |

## How this repo tracks it

- `tests/platform/test_dashboards.py::test_auth_rejection_does_not_skew_parallel_counter` is
  `xfail(strict=True)`: it turns into a failure once an upgrade fixes the bug, prompting us to
  remove the xfail and the README note.
- Tests that check parallel limits use a key that never receives auth-rejected requests.
- README "已知限制" documents the risk; no mitigation in place (decision: keep as-is for now).
