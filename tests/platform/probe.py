"""In-network HTTP probe.

Runs inside a throwaway container attached to the compose backend network so
tests can reach services that have no host port (Qdrant, Ollama, ...).

Input (stdin): JSON list of requests
    [{"method": "GET", "url": "http://qdrant:6333/readyz",
      "headers": {...}, "body": {...} | null, "timeout": 30}, ...]
Output (stdout): JSON list of {"status": int, "body": <json or str>}
    status 0 means a connection-level error (body holds the message).

Requests run sequentially, so later ones can rely on earlier side effects.
Secrets travel only via stdin, never via argv or env.
"""
import json
import sys
import urllib.error
import urllib.request


def run(spec: dict) -> dict:
    req = urllib.request.Request(spec["url"], method=spec.get("method", "GET"))
    for k, v in (spec.get("headers") or {}).items():
        req.add_header(k, v)
    data = None
    if spec.get("body") is not None:
        data = json.dumps(spec["body"]).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=spec.get("timeout", 30)) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except Exception as e:  # noqa: BLE001 - report any connection failure
        return {"status": 0, "body": f"{type(e).__name__}: {e}"}
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = raw.decode(errors="replace")[:500]
    return {"status": status, "body": body}


if __name__ == "__main__":
    print(json.dumps([run(s) for s in json.load(sys.stdin)]))
