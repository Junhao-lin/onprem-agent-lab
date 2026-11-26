"""Shared fixtures for platform tests.

Tests run on the host against the live compose stack:
  * the gateway via its 127.0.0.1 port,
  * internal-only services via a probe container on the backend network,
  * container state via `docker compose` / `docker inspect`.

Secrets are read from .env and never printed: assertion messages use
`mask()`; probe payloads go over stdin.
"""
from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
COMPOSE_FILES = ["-f", "docker-compose.yml", "-f", "docker-compose.gpu.yml"]
NETWORK = "oal-backend"
PROBE_IMAGE = "python:3.12.16-alpine3.24"
TMP_PREFIX = "pytest-tmp-"  # alias / collection prefix for disposable resources
PLATFORM_SERVICES = ["postgres", "redis", "ollama", "litellm", "qdrant", "prometheus", "grafana"]
PROFILES = ["--profile", "platform", "--profile", "monitoring"]


def mask(key: str) -> str:
    """Project-wide key mask: 'sk-' + '…' + last 4 chars."""
    return f"sk-…{key[-4:]}" if key and len(key) > 8 else "***"


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


# --------------------------------------------------------------------------
# subprocess helpers
# --------------------------------------------------------------------------
def run(cmd: list[str], *, input: str | None = None, check: bool = False,
        timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=REPO, input=input, capture_output=True, text=True,
                          encoding="utf-8", timeout=timeout, check=check)


def compose(*args: str, **kw) -> subprocess.CompletedProcess:
    return run(["docker", "compose", *COMPOSE_FILES, *PROFILES, *args], **kw)


def container_id(service: str) -> str:
    cid = compose("ps", "-a", "-q", service).stdout.strip()
    assert cid, f"no container for service {service!r}; is the stack up?"
    return cid.splitlines()[0]


def inspect(service: str) -> dict:
    out = run(["docker", "inspect", container_id(service)], check=True).stdout
    return json.loads(out)[0]


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------
@dataclass
class Resp:
    status: int
    body: object
    headers: dict


def http(method: str, url: str, *, headers: dict | None = None, body=None,
         timeout: int = 120) -> Resp:
    req = urllib.request.Request(url, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            status, raw, hdrs = r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        status, raw, hdrs = e.code, e.read(), dict(e.headers)
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        parsed = raw.decode(errors="replace")
    return Resp(status, parsed, {k.lower(): v for k, v in hdrs.items()})


class Gateway:
    """LiteLLM proxy on the host loopback port."""

    def __init__(self, base: str, master_key: str):
        self.base = base
        self.master_key = master_key

    def request(self, method: str, path: str, *, key: str | None = "master",
                body=None, query: dict | None = None, timeout: int = 120) -> Resp:
        if key == "master":
            key = self.master_key
        url = self.base + path + ("?" + urllib.parse.urlencode(query) if query else "")
        headers = {"Authorization": f"Bearer {key}"} if key is not None else {}
        return http(method, url, headers=headers, body=body, timeout=timeout)

    def chat(self, key: str, content: str = "hi", max_tokens: int = 1, **extra) -> Resp:
        return self.request("POST", "/v1/chat/completions", key=key, body={
            "model": "chat-default", "max_tokens": max_tokens, "temperature": 0,
            "messages": [{"role": "user", "content": content}], **extra})

    def embed(self, key: str, texts: list[str] | str) -> Resp:
        return self.request("POST", "/v1/embeddings", key=key,
                            body={"model": "embed-default", "input": texts})


def probe(requests: list[dict], timeout: int = 180) -> list[dict]:
    """Run HTTP requests from inside the backend network (see probe.py)."""
    script = REPO / "tests" / "platform" / "probe.py"
    # Payload (may contain secrets) goes via stdin, never argv/env.
    proc = run(["docker", "run", "--rm", "-i", "--network", NETWORK,
                "-v", f"{script}:/probe.py:ro", PROBE_IMAGE, "python", "-I", "/probe.py"],
               input=json.dumps(requests), timeout=timeout)
    assert proc.returncode == 0, f"probe failed: {proc.stderr[-500:]}"
    return json.loads(proc.stdout)


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def env() -> dict[str, str]:
    path = REPO / ".env"
    if not path.exists():
        pytest.exit(".env not found: cp .env.example .env and fill it in", returncode=2)
    return load_env(path)


@pytest.fixture(scope="session")
def stack_up(env):
    """Fail fast with one clear message if the platform is not running."""
    out = compose("ps", "--format", "json").stdout
    rows = [json.loads(line) for line in out.splitlines() if line.strip()]
    health = {r["Service"]: r.get("Health") or r.get("State") for r in rows}
    missing = [s for s in PLATFORM_SERVICES if health.get(s) != "healthy"]
    if missing:
        pytest.exit(f"platform not healthy: {missing} (got {health}); "
                    "run docker compose ... --profile platform --profile monitoring up -d", returncode=3)
    return health


@pytest.fixture(scope="session")
def gateway(env, stack_up) -> Gateway:
    return Gateway(f"http://127.0.0.1:{env.get('LITELLM_PORT', '4000')}", env["LITELLM_MASTER_KEY"])


@pytest.fixture(scope="session")
def probe_image():
    if run(["docker", "image", "inspect", PROBE_IMAGE]).returncode != 0:
        run(["docker", "pull", "-q", PROBE_IMAGE], check=True)
    return PROBE_IMAGE


@pytest.fixture
def tmp_key(gateway):
    """Factory for disposable virtual keys; all deleted after the test."""
    aliases: list[str] = []

    def make(name: str, **limits) -> str:
        alias = f"{TMP_PREFIX}{name}"
        r = gateway.request("POST", "/key/generate",
                            body={"key_alias": alias, "models": ["chat-default"], **limits})
        assert r.status == 200, f"/key/generate failed: {r.status}"
        aliases.append(alias)
        return r.body["key"]

    yield make
    if aliases:
        gateway.request("POST", "/key/delete", body={"key_aliases": aliases})


def psql(env: dict[str, str], sql: str) -> str:
    out = compose("exec", "-T", "postgres", "psql", "-U", env["POSTGRES_USER"],
                  "-d", env["POSTGRES_DB"], "-tAc", sql, check=True)
    return out.stdout.strip()


def redis_cli(*args: str, auth: bool = True) -> subprocess.CompletedProcess:
    pre = [] if auth else ["-e", "REDISCLI_AUTH="]
    return compose("exec", "-T", *pre, "redis", "redis-cli", *args)


def pytest_sessionfinish(session, exitstatus):
    """Best-effort sweep of disposable keys if a test crashed mid-way."""
    try:
        e = load_env(REPO / ".env")
        gw = Gateway(f"http://127.0.0.1:{e.get('LITELLM_PORT', '4000')}", e["LITELLM_MASTER_KEY"])
        r = gw.request("GET", "/key/list", query={"size": 100, "return_full_object": "true"})
        left = [k["key_alias"] for k in (r.body.get("keys", []) if isinstance(r.body, dict) else [])
                if str(k.get("key_alias") or "").startswith(TMP_PREFIX)]
        if left:
            gw.request("POST", "/key/delete", body={"key_aliases": left})
    except Exception:  # noqa: BLE001 - never fail the session on cleanup
        pass
