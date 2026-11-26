"""Container state, exposure and wiring (tasks 1.2, 1.3, 1.6)."""
import pytest

from conftest import PLATFORM_SERVICES, compose, inspect, redis_cli, psql, probe

# Only the gateway and Grafana may be published, and only on loopback.
HOST_EXPOSED = {"litellm": {"4000/tcp"}, "grafana": {"3000/tcp"}}
NAMED_VOLUMES = {
    "postgres": "/var/lib/postgresql/data",
    "redis": "/data",
    "ollama": "/root/.ollama",
    "qdrant": "/qdrant/storage",
    "prometheus": "/prometheus",
    "grafana": "/var/lib/grafana",
}


@pytest.mark.parametrize("service", PLATFORM_SERVICES)
def test_healthy(stack_up, service):
    assert stack_up[service] == "healthy"


def test_ollama_init_exited_zero(stack_up):
    """1.3 pending: model pull job finished successfully."""
    state = inspect("ollama-init")["State"]
    assert state["Status"] == "exited" and state["ExitCode"] == 0, state


@pytest.mark.parametrize("service", PLATFORM_SERVICES)
def test_host_port_exposure(stack_up, service):
    """1.2/1.3/1.6 pending: internal services publish nothing; gateway only on 127.0.0.1."""
    bindings = inspect(service)["NetworkSettings"]["Ports"] or {}
    published = {port: hb for port, hb in bindings.items() if hb}
    assert set(published) == HOST_EXPOSED.get(service, set()), published
    for port, host_bindings in published.items():
        assert all(b["HostIp"] == "127.0.0.1" for b in host_bindings), (port, host_bindings)


@pytest.mark.parametrize("service,target", NAMED_VOLUMES.items())
def test_named_volume(stack_up, service, target):
    """1.2 pending: data lives in named volumes, not the container layer."""
    mounts = {m["Destination"]: m for m in inspect(service)["Mounts"]}
    assert target in mounts, list(mounts)
    assert mounts[target]["Type"] == "volume" and mounts[target]["Name"], mounts[target]


def test_qdrant_telemetry_disabled(stack_up):
    """1.6 pending: check the container env, not log text."""
    env = dict(e.split("=", 1) for e in inspect("qdrant")["Config"]["Env"])
    assert env.get("QDRANT__TELEMETRY_DISABLED") == "true"


def test_redis_rejects_unauthenticated(stack_up):
    out = redis_cli("ping", auth=False)
    assert "NOAUTH" in out.stdout + out.stderr, out.stdout


def test_redis_accepts_authenticated(stack_up):
    assert redis_cli("ping").stdout.strip() == "PONG"


def test_postgres_query(env, stack_up):
    assert psql(env, "select 1") == "1"


def pinned_tag(image_repo: str) -> str:
    images = compose("config", "--images").stdout.split()
    tags = [i.rsplit(":", 1)[1] for i in images if i.rsplit(":", 1)[0] == image_repo]
    assert len(set(tags)) == 1, f"{image_repo}: expected one pinned tag, got {tags}"
    return tags[0]


def test_internal_services_reachable_in_network(stack_up, probe_image):
    r = probe([{"url": "http://ollama:11434/api/version"},
               {"url": "http://qdrant:6333/readyz"}])
    assert [x["status"] for x in r] == [200, 200], r
    # Running Ollama must be the version pinned in docker-compose.yml.
    assert r[0]["body"] == {"version": pinned_tag("ollama/ollama")}, r[0]["body"]
    assert r[1]["body"] == "all shards are ready", r[1]["body"]


def test_redis_password_not_in_command(stack_up, env):
    """Password is read from env at runtime, not baked into the container command."""
    assert env["REDIS_PASSWORD"] not in " ".join(inspect("redis")["Config"]["Cmd"])
