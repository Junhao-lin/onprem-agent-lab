"""Spend-log hypothesis test: are streaming chat requests missing from LiteLLM_SpendLogs?

    python -I reports/raw/spendlog/spendlog_probe.py [N] | python -I scripts/rawlog.py reports/raw/spendlog/<run>.txt

Uses a temporary key (alias pytest-tmp-spendlog-<ts>) so every row is attributable,
sends N non-streaming chats, N streaming chats (fully drained) and N embeddings, each
group with its own `user` value, then polls LiteLLM_SpendLogs for up to 180 s.
Prints counts only (no key material); the key is deleted and the deletion confirmed.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))
from bootstrap_keys import Gateway, load_env  # noqa: E402

BASE = "http://127.0.0.1:4000"
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.gpu.yml",
           "--profile", "platform", "--profile", "monitoring"]


def sql(query: str) -> list[list[str]]:
    r = subprocess.run([*COMPOSE, "exec", "-T", "postgres", "sh", "-c",
                        'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA -F "|" -v ON_ERROR_STOP=1'],
                       cwd=REPO, input=query.encode(), capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode()[-300:]
    return [l.split("|") for l in r.stdout.decode().splitlines() if l.strip()]


def call(key: str, path: str, body: dict, stream: bool = False) -> tuple[int, str]:
    req = urllib.request.Request(BASE + path, method="POST", data=json.dumps(body).encode())
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            call_id = r.headers.get("x-litellm-call-id", "")
            resp_id = ""
            if stream:
                for raw in r:
                    line = raw.decode().strip()
                    if line == "data: [DONE]":
                        break
                    if line.startswith("data: ") and not resp_id:
                        resp_id = json.loads(line[6:]).get("id", "")
            else:
                resp_id = json.loads(r.read()).get("id", "")
            return r.status, call_id, resp_id
    except urllib.error.HTTPError as e:
        return e.code, "", ""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    env = load_env(REPO / ".env")
    gw = Gateway(BASE, env["LITELLM_MASTER_KEY"])
    alias = f"pytest-tmp-spendlog-{int(time.time())}"
    status, body = gw.request("POST", "/key/generate", body={
        "key_alias": alias, "models": ["chat-default", "embed-default"]})
    assert status == 200, status
    key = body["key"]
    hashed = hashlib.sha256(key.encode()).hexdigest()
    print(f"run {time.strftime('%Y-%m-%d %H:%M:%S')} temp key alias {alias}; N={n} per group")
    sent: dict[str, list] = {"nonstream": [], "stream": [], "embed": []}
    try:
        for i in range(n):
            msg = [{"role": "user", "content": f"Say the number {i}."}]
            sent["nonstream"].append(call(key, "/v1/chat/completions", {
                "model": "chat-default", "max_tokens": 8, "temperature": 0, "messages": msg,
                "user": "spend-nonstream"}))
            sent["stream"].append(call(key, "/v1/chat/completions", {
                "model": "chat-default", "max_tokens": 8, "temperature": 0, "messages": msg,
                "stream": True, "user": "spend-stream"}, stream=True))
            sent["embed"].append(call(key, "/v1/embeddings", {
                "model": "embed-default", "input": f"text {i}", "user": "spend-embed"}))
        t_sent = time.time()
        for g, res in sent.items():
            print(f"sent {g:<9}: statuses {sorted({r[0] for r in res})}, {sum(r[0] == 200 for r in res)} ok")
        # Which response ids already had a row BEFORE this run started?
        chat_ids = [r[2] for g in ("nonstream", "stream") for r in sent[g] if r[0] == 200]
        pre = set()
        if chat_ids:
            inlist = ",".join("'" + c.replace("'", "") + "'" for c in chat_ids)
            pre = {r[0] for r in sql(f"select request_id from \"LiteLLM_SpendLogs\" where request_id in "
                                     f"({inlist}) and api_key <> '{hashed}';")}
        print(f"chat response ids: {len(chat_ids)} ({len(set(chat_ids))} distinct); "
              f"already present in the table from earlier requests: {len(pre & set(chat_ids))}")
        print("chat response id samples:", sorted(set(chat_ids))[:6])

        q = (f"select coalesce(end_user,'') , call_type, count(*) from \"LiteLLM_SpendLogs\" "
             f"where api_key = '{hashed}' group by 1, 2 order by 1, 2;")
        last = None
        while time.time() - t_sent < 180:
            rows = sql(q)
            if rows != last:
                print(f"+{time.time() - t_sent:5.0f}s rows: {rows}")
                last = rows
            if sum(int(r[2]) for r in rows) >= 3 * n:
                break
            time.sleep(5)
        # Prediction of the collision hypothesis: a chat gets a row of its own exactly when
        # its response id was not already taken.
        own = {r[0] for r in sql(f"select request_id from \"LiteLLM_SpendLogs\" where api_key = '{hashed}' "
                                 f"and call_type = 'acompletion';")}
        fresh = set(chat_ids) - pre
        print(f"chat ids NOT taken before: {len(fresh)} -> logged for this key: {len(fresh & own)}")
        print(f"chat ids already taken:    {len(pre & set(chat_ids))} -> logged for this key: {len(pre & own)}")
        embeds = [r[1] for r in sent["embed"] if r[0] == 200 and r[1]]
        if embeds:
            inlist = ",".join("'" + c.replace("'", "") + "'" for c in embeds)
            found = sql(f"select count(*) from \"LiteLLM_SpendLogs\" where request_id in ({inlist});")
            print(f"embeddings by x-litellm-call-id (uuid): {found[0][0]}/{len(embeds)} rows")
        # sample of what a row looks like for each group (no secrets: only shape)
        shape = sql(f"select coalesce(end_user,''), call_type, status, (completion_tokens > 0), "
                    f"left(request_id, 9) from \"LiteLLM_SpendLogs\" where api_key = '{hashed}' "
                    f"order by \"startTime\" limit 6;")
        print("row shape (end_user, call_type, status, has_completion_tokens, request_id prefix):", shape)
    finally:
        gw.request("POST", "/key/delete", body={"key_aliases": [alias]})
        st, listed = gw.request("GET", "/key/list", query={"key_alias": alias})
        print(f"cleanup: {alias} deleted = {st == 200 and not listed.get('keys')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
