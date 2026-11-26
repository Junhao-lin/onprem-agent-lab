"""Draft verification for task 1.6 (Qdrant + API key). Never prints secrets.

End-to-end: embeds text through the LiteLLM gateway (support-rag key),
upserts into a temporary Qdrant collection, searches, restarts Qdrant to
check persistence, then deletes the collection. To be rewritten as pytest
in task 1.7.

    python -I tests/platform/_drafts/verify_1_6.py
"""
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parents[3]
env = {}
for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k] = v
QDRANT = f"http://127.0.0.1:{env.get('QDRANT_HTTP_PORT', '6333')}"
GATEWAY = f"http://127.0.0.1:{env.get('LITELLM_PORT', '4000')}"
QKEY = env["QDRANT_API_KEY"]
COLLECTION = f"verify_tmp_{int(time.time())}"
results = []


def http(method, url, headers=None, body=None, timeout=60):
    req = urllib.request.Request(url, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw[:1] in (b"{", b"[") else raw.decode(errors="replace"))
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200].decode(errors="replace")
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        return 0, str(e)


def q(method, path, body=None, key=QKEY):
    headers = {"api-key": key} if key is not None else {}
    return http(method, QDRANT + path, headers, body)


def embed(texts):
    s, b = http("POST", GATEWAY + "/v1/embeddings",
                {"Authorization": f"Bearer {env['SUPPORT_RAG_LLM_KEY']}"},
                {"model": "embed-default", "input": texts})
    assert s == 200, (s, b)
    return [d["embedding"] for d in sorted(b["data"], key=lambda d: d["index"])]


def check(name, ok, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def compose(*args):
    return subprocess.run(["docker", "compose", *args], cwd=REPO, capture_output=True, text=True)


DOCS = [
    (1, "如何開啟攝影機的夜視功能？在設定 > 影像 > 紅外線模式選擇自動。"),
    (2, "攝影機恢復原廠設定：按住 Reset 鍵 10 秒直到指示燈閃爍。"),
    (3, "NVR 錄影保存天數取決於硬碟容量與錄影解析度。"),
]

try:
    # --- 1. health probes open, data API locked ---------------------------
    s, _ = q("GET", "/readyz", key=None)
    check("/readyz 200 without key", s == 200, f"got {s}")
    s, _ = q("GET", "/collections", key=None)
    check("no api-key -> 401", s == 401, f"got {s}")
    s, _ = q("GET", "/collections", key="wrong-key")
    check("wrong api-key -> 401/403", s in (401, 403), f"got {s}")
    s, b = q("GET", "/")
    ver = b.get("version") if isinstance(b, dict) else None
    check("version is pinned 1.20.2", ver == "1.20.2", f"version={ver}")

    # --- 2. create collection (dense 1024 cosine + sparse slot for hybrid) -
    s, b = q("PUT", f"/collections/{COLLECTION}", {
        "vectors": {"dense": {"size": 1024, "distance": "Cosine"}},
        "sparse_vectors": {"sparse": {}},
    })
    check("create collection (dense 1024 + sparse)", s == 200, f"got {s} {'' if s == 200 else b}")

    # --- 3. end-to-end: gateway embeddings -> upsert -> search ------------
    vecs = embed([t for _, t in DOCS])
    s, b = q("PUT", f"/collections/{COLLECTION}/points?wait=true", {"points": [
        {"id": i, "vector": {"dense": v}, "payload": {"text": t}}
        for (i, t), v in zip(DOCS, vecs)]})
    check("upsert 3 points with bge-m3 vectors", s == 200, f"got {s}")
    qv = embed(["晚上畫面太暗怎麼辦"])[0]
    s, b = q("POST", f"/collections/{COLLECTION}/points/query",
             {"query": qv, "using": "dense", "limit": 3, "with_payload": False})
    pts = b.get("result", {}).get("points", []) if isinstance(b, dict) else []
    top = pts[0]["id"] if pts else None
    check("semantic search: night-vision doc ranked first", top == 1,
          f"ranking={[(p['id'], round(p['score'], 3)) for p in pts]}")

    # --- 4. persistence across restart ------------------------------------
    compose("restart", "qdrant")
    for _ in range(30):
        if q("GET", "/readyz", key=None)[0] == 200:
            break
        time.sleep(1)
    s, b = q("POST", f"/collections/{COLLECTION}/points/count", {"exact": True})
    n = b.get("result", {}).get("count") if isinstance(b, dict) else None
    check("collection + points survive restart", s == 200 and n == 3, f"count={n}")

    # --- 5. network exposure ----------------------------------------------
    for port in ("6333", "6334"):
        out = compose("port", "qdrant", port).stdout.strip()
        check(f"{port} bound to 127.0.0.1 only", out.startswith("127.0.0.1:"), out)
    with socket.create_connection(("127.0.0.1", int(env.get("QDRANT_GRPC_PORT", "6334"))), timeout=3):
        check("gRPC port accepts TCP", True)

    # --- 6. config hygiene ------------------------------------------------
    logs = compose("logs", "qdrant").stdout.lower()
    check("telemetry reporting disabled", "telemetry reporting disabled" in logs,
          "found in logs" if "telemetry reporting disabled" in logs else "not found in logs")
    compose_txt = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    check("no Qdrant key value in docker-compose.yml", QKEY not in compose_txt)
finally:
    s, _ = q("DELETE", f"/collections/{COLLECTION}")
    s2, b = q("GET", "/collections")
    left = [c["name"] for c in b.get("result", {}).get("collections", [])
            if c["name"].startswith("verify_tmp_")] if isinstance(b, dict) else ["?"]
    print(f"cleanup: delete={s}, verify_tmp_ collections left={left}")

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
