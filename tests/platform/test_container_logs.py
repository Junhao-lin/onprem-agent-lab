"""Key hygiene in container logs (follow-up to the overnight review).

LiteLLM's access log records every request line, so a key passed as ``?key=``
ends up in ``docker compose logs``. Keys must only travel in headers or bodies.
This runs last, after the rest of the session has exercised the gateway.
"""
import re

import pytest

from conftest import compose

# A LiteLLM virtual/master key: "sk-" followed by a long token.
KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{16,}")
APP_KEY_VARS = ("SUPPORT_RAG_LLM_KEY", "ONBOARDING_AGENT_LLM_KEY", "LITELLM_MASTER_KEY")


def litellm_log() -> str:
    r = compose("logs", "--no-color", "--no-log-prefix", "litellm", check=True)
    return r.stdout + r.stderr


@pytest.mark.run_last
def test_litellm_log_contains_no_keys(env, stack_up):
    log = litellm_log()
    size = len(log)
    assert size > 1000, "log unexpectedly empty - is this the right container?"
    # Report only variable names / counts, never the matched text.
    leaked = [v for v in APP_KEY_VARS if env.get(v) and env[v] in log]
    assert leaked == [], f"full key of {leaked} found in litellm log"
    n = len(KEY_PATTERN.findall(log))
    assert n == 0, f"{n} key-shaped token(s) (sk-...) found in litellm log"
    in_query = log.count("key=sk-")  # counted, so a failure never echoes the log text
    assert in_query == 0, f"{in_query} request line(s) carry a key in the URL"


def test_run_last_tests_are_sorted_last(request):
    items = request.session.items
    flags = [i.get_closest_marker("run_last") is not None for i in items]
    assert flags == sorted(flags), "a run_last test is not at the end of the session"
