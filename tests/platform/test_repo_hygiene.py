"""Repo / secret hygiene (tasks 1.1, 1.4, 1.5). No running stack needed."""
import re
import subprocess
import tomllib

import pytest

from conftest import REPO, load_env, run

SECRET_VARS = ["POSTGRES_PASSWORD", "REDIS_PASSWORD", "LITELLM_MASTER_KEY", "LITELLM_SALT_KEY",
               "QDRANT_API_KEY", "GRAFANA_ADMIN_PASSWORD", "SUPPORT_RAG_LLM_KEY",
               "ONBOARDING_AGENT_LLM_KEY"]


def tracked_files() -> list[str]:
    return run(["git", "ls-files"], check=True).stdout.splitlines()


def secret_values() -> dict[str, str]:
    env = load_env(REPO / ".env")
    return {k: env[k] for k in SECRET_VARS if len(env.get(k, "")) >= 8}


@pytest.mark.parametrize("path", [".env", ".env.local", "loadtest/results/run.csv",
                                  "loadtest/results/sub/report.md"])
def test_ignored(path):
    assert run(["git", "check-ignore", "-q", path]).returncode == 0, f"{path} is not git-ignored"


def test_env_not_tracked():
    assert not [f for f in tracked_files() if re.fullmatch(r"(.*/)?\.env(\..+)?", f)
                and not f.endswith(".env.example")]


def test_env_example_tracked_and_placeholder_only():
    assert ".env.example" in tracked_files()
    example = load_env(REPO / ".env.example")
    for k in SECRET_VARS:
        assert example.get(k, "") in ("", "change-me", "sk-change-me"), f"{k} has a non-placeholder value"


def test_loadtest_results_untracked():
    """1.1 pending: benchmark output must never be committed."""
    tracked = [f for f in tracked_files() if f.startswith("loadtest/results/")]
    assert tracked == ["loadtest/results/.gitkeep"], tracked


def test_no_secret_values_in_tracked_files():
    secrets = secret_values()
    assert secrets, ".env has no secrets to check against"
    leaks = []
    for f in tracked_files():
        p = REPO / f
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        leaks += [f"{k} in {f}" for k, v in secrets.items() if v in text]
    assert not leaks, leaks


def test_shell_scripts_are_lf():
    out = run(["git", "ls-files", "--eol", "*.sh"], check=True).stdout.splitlines()
    assert out, "no tracked .sh files"
    bad = [line for line in out if not line.startswith("i/lf")]
    assert not bad, bad


def test_virtual_keys_toml_has_no_key_values():
    text = (REPO / "infra/litellm/virtual-keys.toml").read_text(encoding="utf-8")
    assert not re.search(r"sk-[A-Za-z0-9_-]{8,}", text)
    spec = tomllib.loads(text)["keys"]
    assert set(spec) == {"support-rag", "onboarding-agent"}


def test_model_names_in_sync():
    """.env OLLAMA_*_MODEL must match what the gateway config routes to."""
    env = load_env(REPO / ".env")
    cfg = (REPO / "infra/litellm/config.yaml").read_text(encoding="utf-8")
    routed = re.findall(r"model:\s*openai/(\S+)", cfg)
    assert env["OLLAMA_CHAT_MODEL"] in routed, (env["OLLAMA_CHAT_MODEL"], routed)
    assert env["OLLAMA_EMBED_MODEL"] in routed, (env["OLLAMA_EMBED_MODEL"], routed)


def test_compose_images_pinned():
    cfg = subprocess.run(["docker", "compose", "-f", "docker-compose.yml", "--profile", "platform", "--profile", "monitoring",
                          "config", "--images"], cwd=REPO, capture_output=True, text=True, check=True)
    images = cfg.stdout.split()
    assert images
    unpinned = [i for i in images if ":" not in i.split("/")[-1] or i.endswith(":latest")]
    assert not unpinned, unpinned


def test_env_fixture_repr_hides_values(env):
    """pytest prints fixture arguments in long tracebacks via repr(): never the values."""
    from _pytest._io.saferepr import saferepr
    secret = env["POSTGRES_PASSWORD"]
    assert secret not in repr(env) and secret not in str(env) and secret not in saferepr(env)
    assert "POSTGRES_PASSWORD" in repr(env)                  # names stay useful for debugging


def test_pytest_wrapper_redacts_secrets():
    """reports/raw/*/pytest.txt is written by scripts/overnight/run_pytest.py: it must redact."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_codex", REPO / "scripts/overnight/run_codex.py")
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    secrets = rc.secret_values()
    text, hits = rc.redact("tb: env = " + " ".join(secrets) + " key='sk-abcdefghijkl1234'", secrets)
    assert hits >= len(secrets) and not any(s in text for s in secrets) and "sk-…1234" in text
