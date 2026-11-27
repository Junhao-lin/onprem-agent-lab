"""Repo / secret hygiene (tasks 1.1, 1.4, 1.5). No running stack needed."""
import re
import subprocess
import sys
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
    routed = re.findall(r"model:\s*(?:openai|ollama_chat)/(\S+)", cfg)
    assert env["OLLAMA_CHAT_MODEL"] in routed, (env["OLLAMA_CHAT_MODEL"], routed)
    assert env["OLLAMA_EMBED_MODEL"] in routed, (env["OLLAMA_EMBED_MODEL"], routed)


def test_chat_on_ollama_uses_native_provider():
    """While the backend is Ollama, chat must go through ollama_chat/ (UUID response ids),
    not openai/ on Ollama's /v1, whose "chatcmpl-<0..999>" ids collide on the spend-log
    primary key (reports/evidence/spendlog/FINDINGS.md)."""
    cfg = (REPO / "infra/litellm/config.yaml").read_text(encoding="utf-8")
    block = re.search(r"model_name:\s*chat-default\n(.*?)(?=\n\s*- model_name:|\Z)", cfg, re.S).group(1)
    model = re.search(r"^\s*model:\s*(\S+)", block, re.M).group(1)
    api_base = re.search(r"^\s*api_base:\s*(\S+)", block, re.M).group(1)
    if "ollama" in api_base:
        assert model.startswith("ollama_chat/"), model
        assert not api_base.rstrip("/").endswith("/v1"), api_base


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


# --- raw evidence is always masked before it is written (scripts/rawlog.py) -------------

def _rawlog():
    import importlib.util
    spec = importlib.util.spec_from_file_location("rawlog", REPO / "scripts/rawlog.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_write_raw_masks_secrets_and_sk_tokens(tmp_path):
    rawlog = _rawlog()
    fake = ["fake-password-1234567890", "fake-salt-abcdefghijkl"]
    out = tmp_path / "sub" / "out.txt"
    hits = rawlog.write_raw(out, "pw=fake-password-1234567890\r\nsalt=fake-salt-abcdefghijkl "
                                 "key=sk-ABCDEFGHijklmnop9876\n", fake)
    text = out.read_bytes().decode("utf-8")
    assert hits == 3
    assert not any(s in text for s in fake) and text.count("[REDACTED]") == 2
    assert "sk-…9876" in text and "ABCDEFGH" not in text
    assert "\r" not in text                                   # UTF-8 + LF


def test_write_raw_leaves_no_trailing_whitespace(tmp_path):
    out = tmp_path / "ws.txt"
    _rawlog().write_raw(out, "a  \r\nb\t\n\n=======  2 passed  \n\n\n")
    assert out.read_bytes() == b"a\nb\n\n=======  2 passed\n"


def test_tracked_text_files_pass_git_diff_check():
    """Same rules as `git diff --check`: no trailing whitespace, no blank lines at EOF
    (Markdown hard breaks use a trailing backslash instead of two spaces)."""
    files = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True,
                           check=True).stdout.decode("utf-8").split("\0")
    bad = []
    for rel in filter(None, files):
        p = REPO / rel
        if not p.is_file():
            continue
        data = p.read_bytes()
        if not data or b"\0" in data[:4096]:
            continue
        lines = data.decode("utf-8", "replace").replace("\r\n", "\n").split("\n")
        n = sum(1 for ln in lines if ln != ln.rstrip(" \t"))
        if n:
            bad.append(f"{rel}: {n} line(s) with trailing whitespace")
        if data.replace(b"\r\n", b"\n").endswith(b"\n\n"):
            bad.append(f"{rel}: blank line at EOF")
    assert bad == [], bad


def test_e2e_screenshot_goes_to_ignored_path():
    """The e2e run re-takes its screenshot every time: it must land in a git-ignored
    folder so the reviewed, committed 1.9 screenshot never changes."""
    src = (REPO / "tests/e2e/test_grafana.py").read_text(encoding="utf-8")
    out_dir = re.search(r'^OUT_DIR = REPO / "([^"]+)"', src, re.M).group(1)
    shot = f"{out_dir}/platform-overview-kiosk.png"
    reviewed = "reports/evidence/1.9/platform-overview-kiosk.png"
    assert shot != reviewed
    ignored = subprocess.run(["git", "check-ignore", "-q", shot], cwd=REPO)
    assert ignored.returncode == 0, f"{shot} is not git-ignored"
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", reviewed], cwd=REPO,
                             capture_output=True)
    assert tracked.returncode == 0, "the reviewed 1.9 screenshot must stay committed"


FORBIDDEN_WORDS_FILE = REPO / ".local/forbidden-words.txt"   # git-ignored, local only


def _tracked_text_files():
    files = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True,
                           check=True).stdout.decode("utf-8").split("\0")
    for rel in filter(None, files):
        p = REPO / rel
        if p.is_file():
            data = p.read_bytes()
            text = data.decode("latin-1") if b"\0" in data[:4096] else data.decode("utf-8", "replace")
            yield rel, text


def test_forbidden_words_file_is_local_only():
    r = subprocess.run(["git", "check-ignore", "-q", ".local/forbidden-words.txt"], cwd=REPO)
    assert r.returncode == 0, ".local/ must be git-ignored"
    tracked = subprocess.run(["git", "ls-files", ".local"], cwd=REPO, capture_output=True, text=True).stdout
    assert tracked.strip() == ""


def test_no_forbidden_words_in_tracked_files():
    """Words listed in the local, git-ignored .local/forbidden-words.txt (e.g. a company
    name) must not appear in any tracked file's content or path. The list itself never
    enters the repo; failures name the file and the word's line number in the list, not the word."""
    if not FORBIDDEN_WORDS_FILE.exists():
        pytest.skip("no local .local/forbidden-words.txt on this machine")
    words = [w.strip() for w in FORBIDDEN_WORDS_FILE.read_text(encoding="utf-8").splitlines()
             if w.strip() and not w.lstrip().startswith("#")]
    assert words, "forbidden-words list is empty"
    hits = []
    for rel, text in _tracked_text_files():
        for i, w in enumerate(words, 1):
            n = text.lower().count(w.lower()) + rel.lower().count(w.lower())
            if n:
                hits.append(f"{rel}: word #{i} x{n}")
    assert hits == [], hits


def test_no_local_identity_in_tracked_files():
    """No tracked file carries this machine's user-profile path, account name or an
    e-mail address (same detectors as rawlog's masking, values taken at runtime)."""
    rawlog = _rawlog()
    hits = []
    for rel, text in _tracked_text_files():
        _, n = rawlog.redact_identity(text)
        if n:
            hits.append(f"{rel}: {n}")
    assert hits == [], hits


def test_rawlog_masks_local_identity(tmp_path):
    from pathlib import Path as _P
    rawlog = _rawlog()
    home, user = str(_P.home()), _P.home().name
    sample = (f"{home}\\x.txt {home.replace(chr(92), '/')}/y {home.replace(chr(92), chr(92) * 2)}\\\\z "
              f"user {user} mail " + "a.b" + "@" + "example.org" + " keep @pytest.fixture")
    out = tmp_path / "id.txt"
    rawlog.write_raw(out, sample, [])
    text = out.read_text(encoding="utf-8")
    assert user.lower() not in text.lower() and "@example.org" not in text
    assert text.count("<HOME>") == 3 and "<email>" in text and "@pytest.fixture" in text


def test_reports_raw_is_local_only():
    """reports/raw/ holds local raw output (incl. agent transcripts): ignored, nothing tracked."""
    r = subprocess.run(["git", "check-ignore", "-q", "reports/raw/x/codex.log"], cwd=REPO)
    assert r.returncode == 0, "reports/raw/ must be git-ignored"
    tracked = subprocess.run(["git", "ls-files", "reports/raw"], cwd=REPO, capture_output=True, text=True).stdout
    assert tracked.strip() == "", "files tracked under reports/raw/"


def test_rawlog_cli_masks_real_env_values(tmp_path):
    """The shell-pipeline form (`cmd | python -I scripts/rawlog.py FILE`) masks every .env
    secret. Secrets go in over stdin, never argv; failures report counts only."""
    rawlog = _rawlog()
    secrets = rawlog.secret_values()
    assert len(secrets) >= 8                                  # every SECRET_VARS entry is covered
    assert all(secret_values()[k] in secrets for k in secret_values()), "a SECRET_VARS value is not masked"
    out = tmp_path / "cli.txt"
    payload = ("traceback: " + " | ".join(secrets) + "\n").encode("utf-8")
    r = subprocess.run([sys.executable, "-I", str(REPO / "scripts/rawlog.py"), str(out)],
                       input=payload, capture_output=True, timeout=60)
    assert r.returncode == 0
    text = out.read_text(encoding="utf-8")
    leaked = sum(s in text for s in secrets)
    assert leaked == 0, f"{leaked} secret value(s) survived the CLI"
    assert text.count("[REDACTED]") >= len(secrets)


# Files under scripts/, loadtest/ and docs/ that may write a file without rawlog, and why.
DIRECT_WRITE_ALLOWED = {
    "scripts/rawlog.py": "the masked writer itself",
    "scripts/bootstrap_keys.py": "writes .env (the secret store), never evidence",
    "scripts/screenshot_dashboard.py": "PNG screenshot (binary image)",
}


def _direct_writes(path):
    """Calls that write a file without rawlog: .write_text/.write_bytes, or open() with
    a w/a/x mode (positional or mode=)."""
    import ast
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr in ("write_text", "write_bytes"):
            found.append((node.lineno, f.attr))
        elif (isinstance(f, ast.Name) and f.id == "open") or (isinstance(f, ast.Attribute) and f.attr == "open"):
            modes = [a for a in node.args[1:2]] + [k.value for k in node.keywords if k.arg == "mode"]
            if any(isinstance(m, ast.Constant) and isinstance(m.value, str) and set(m.value) & set("wax")
                   for m in modes):
                found.append((node.lineno, "open"))
    return found


def test_raw_writers_go_through_rawlog():
    files = [p for d in ("scripts", "loadtest", "docs") for p in (REPO / d).rglob("*.py")]
    assert len(files) >= 8
    offenders = {}
    for p in files:
        rel = p.relative_to(REPO).as_posix()
        hits = _direct_writes(p)
        if hits and rel not in DIRECT_WRITE_ALLOWED:
            offenders[rel] = hits
    assert offenders == {}, f"write evidence via scripts/rawlog.py write_raw instead: {offenders}"
    # the known evidence writers really use it
    for rel in ("scripts/overnight/run_pytest.py", "scripts/overnight/run_codex.py",
                "loadtest/bench.py", "loadtest/repro_degradation.py"):
        assert "write_raw(" in (REPO / rel).read_text(encoding="utf-8"), rel


def test_direct_write_detector_catches_each_form(tmp_path):
    p = tmp_path / "w.py"
    p.write_text("from pathlib import Path\nPath('a').write_text('x')\nopen('b', 'w')\n"
                 "open('c', mode='a')\nimport io\nio.open('d', 'wb')\nopen('e')\nopen('f', 'r')\n",
                 encoding="utf-8")
    assert [h[0] for h in _direct_writes(p)] == [2, 3, 4, 6]


def test_reports_contain_no_secrets_or_unmasked_keys():
    """Everything under reports/ (tracked or not): no .env secret value, and no sk- token
    except the fake keys that the test sources themselves define."""
    rawlog = _rawlog()
    secrets = rawlog.secret_values()
    fake_literals = set()
    for t in (REPO / "tests").rglob("*.py"):
        fake_literals |= set(rawlog.SK_TOKEN.findall(t.read_text(encoding="utf-8")))
    files = [p for p in (REPO / "reports").rglob("*") if p.is_file()]
    assert len(files) > 20
    with_secret, with_key = [], []
    for p in files:
        data = p.read_bytes()
        if b"\0" in data[:4096]:                              # binary (PNG screenshots)
            continue
        text = data.decode("utf-8", "replace")
        if any(s in text for s in secrets):
            with_secret.append(p.relative_to(REPO).as_posix())
        if set(rawlog.SK_TOKEN.findall(text)) - fake_literals:
            with_key.append(p.relative_to(REPO).as_posix())
    assert with_secret == [], f"files with an .env secret value: {with_secret}"
    assert with_key == [], f"files with an unmasked sk- token: {with_key}"
