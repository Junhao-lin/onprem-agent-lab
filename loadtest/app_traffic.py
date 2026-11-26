"""Steady, within-limits traffic from the real app keys (dashboard demo / screenshots).

    python -I loadtest/app_traffic.py [--duration 300] [--fraction 0.5]

Unlike bench.py (one temporary unlimited key, closed loop), this uses the two
production virtual keys from .env and paces each app to `fraction` of its
rpm_limit from infra/litellm/virtual-keys.toml, one request in flight per app
(below max_parallel_requests), so the gateway should never answer 429.

Mix per app (shapes, not real app logic yet):
  support-rag       embed the question (embed-default), then a streamed answer
                    (chat-default); every 4th answer non-streamed
  onboarding-agent  streamed tutor reply; every 3rd reply non-streamed
Streaming requests ask for usage (stream_options.include_usage) so LiteLLM
records TTFT and tokens. Exit code 1 if any request was not HTTP 200.
Keys are never printed.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ONBOARDING_PROMPTS = [
    "用三句話說明 git rebase 和 git merge 的差異。",
    "新人第一天要設定哪些開發環境？列出五項。",
    "解釋什麼是 code review，以及提交 PR 前要檢查什麼。",
    "請出一題關於 Docker volume 的選擇題並附答案。",
    "什麼是 CI？舉一個在 PR 上自動執行的檢查。",
]


def load_env() -> dict[str, str]:
    env = {}
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


class App:
    def __init__(self, base: str, alias: str, key: str, spec: dict, fraction: float):
        self.base, self.alias, self.key = base, alias, key
        self.interval = 60.0 / (spec["rpm_limit"] * fraction)   # seconds between request starts
        self.statuses: Counter[str] = Counter()
        self.ttft: list[float] = []
        self.n = 0

    def _req(self, path: str, body: dict):
        req = urllib.request.Request(self.base + path, method="POST", data=json.dumps(body).encode())
        req.add_header("Authorization", f"Bearer {self.key}")
        req.add_header("Content-Type", "application/json")
        return urllib.request.urlopen(req, timeout=120)

    def _record(self, kind: str, fn) -> None:
        try:
            status = fn()
        except urllib.error.HTTPError as e:
            status = e.code
        except Exception as e:  # network error / timeout
            status = type(e).__name__
        self.statuses[f"{kind} {status}"] += 1

    def chat(self, prompt: str, stream: bool, max_tokens: int = 160) -> None:
        body = {"model": "chat-default", "max_tokens": max_tokens, "stream": stream,
                "messages": [{"role": "user", "content": prompt}]}
        if stream:
            body["stream_options"] = {"include_usage": True}

        def run():
            t0 = time.perf_counter()
            with self._req("/v1/chat/completions", body) as r:
                if stream:
                    first = None
                    for raw in r:
                        line = raw.decode("utf-8", "replace").strip()
                        if first is None and line.startswith("data:") and line != "data: [DONE]":
                            choices = json.loads(line[5:]).get("choices") or [{}]
                            if choices[0].get("delta", {}).get("content"):
                                first = time.perf_counter() - t0
                    if first is not None:
                        self.ttft.append(first)
                else:
                    r.read()
                return r.status
        self._record("stream" if stream else "chat", run)

    def embed(self, text: str) -> None:
        def run():
            with self._req("/v1/embeddings", {"model": "embed-default", "input": text}) as r:
                r.read()
                return r.status
        self._record("embed", run)

    def one(self, prompts: list[str]) -> None:
        raise NotImplementedError

    def loop(self, prompts: list[str], deadline: float, offset: float) -> None:
        nxt = time.monotonic() + offset
        while True:
            now = time.monotonic()
            if nxt >= deadline:
                return
            if nxt > now:
                time.sleep(nxt - now)
            self.one(prompts)
            self.n += 1
            nxt += self.interval


class SupportRag(App):
    def one(self, prompts):
        q = prompts[self.n % len(prompts)]
        self.embed(q)
        self.chat(f"根據產品手冊回答：{q}", stream=self.n % 4 != 3)


class Onboarding(App):
    def one(self, prompts):
        self.chat(ONBOARDING_PROMPTS[self.n % len(ONBOARDING_PROMPTS)], stream=self.n % 3 != 2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--duration", type=float, default=300, help="seconds (default 300)")
    ap.add_argument("--fraction", type=float, default=0.5,
                    help="share of each key's rpm_limit to use; support-rag does 2 calls per turn (default 0.5)")
    args = ap.parse_args()
    if not 0 < args.fraction <= 1:
        ap.error("--fraction must be in (0, 1]: more would exceed the keys' rpm_limit")
    if args.duration <= 0:
        ap.error("--duration must be positive")

    env = load_env()
    specs = tomllib.loads((REPO / "infra/litellm/virtual-keys.toml").read_text(encoding="utf-8"))["keys"]
    base = f"http://127.0.0.1:{env.get('LITELLM_PORT', '4000')}"
    # support-rag sends 2 requests per turn (embed + chat), so halve its turn rate.
    rag = SupportRag(base, "support-rag", env[specs["support-rag"]["env_var"]], specs["support-rag"],
                     args.fraction / 2)
    tutor = Onboarding(base, "onboarding-agent", env[specs["onboarding-agent"]["env_var"]],
                       specs["onboarding-agent"], args.fraction)
    prompts = [json.loads(line)["prompt"] for line in
               (HERE / "prompts.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    deadline = time.monotonic() + args.duration
    print(f"app traffic for {args.duration:.0f}s: support-rag every {rag.interval:.1f}s (embed + chat), "
          f"onboarding-agent every {tutor.interval:.1f}s", flush=True)
    threads = [threading.Thread(target=rag.loop, args=(prompts, deadline, 0.0)),
               threading.Thread(target=tutor.loop, args=(prompts, deadline, 1.0))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok = True
    for app in (rag, tutor):
        bad = {k: v for k, v in app.statuses.items() if not k.endswith(" 200")}
        ok &= not bad
        ttft = f"TTFT p50 {statistics.median(app.ttft):.3f}s" if app.ttft else "no TTFT"
        print(f"{app.alias:<17} turns {app.n:>3}  {dict(sorted(app.statuses.items()))}  {ttft}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
