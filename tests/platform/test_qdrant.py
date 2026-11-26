"""Qdrant vector store (task 1.6). Qdrant has no host port: all calls go
through the in-network probe."""
import time

import pytest

from conftest import TMP_PREFIX, probe

Q = "http://qdrant:6333"


def test_health_open_data_locked(env, probe_image):
    r = probe([
        {"url": f"{Q}/readyz"},
        {"url": f"{Q}/collections"},
        {"url": f"{Q}/collections", "headers": {"api-key": "wrong-key"}},
        {"url": f"{Q}/", "headers": {"api-key": env["QDRANT_API_KEY"]}},
    ])
    assert [x["status"] for x in r] == [200, 401, 401, 200], [x["status"] for x in r]
    assert r[3]["body"]["version"] == "1.20.2"


@pytest.mark.llm
def test_end_to_end_gateway_embedding_roundtrip(env, gateway, probe_image):
    docs = {1: "如何開啟攝影機的夜視功能？在設定 > 影像 > 紅外線模式選擇自動。",
            2: "攝影機恢復原廠設定：按住 Reset 鍵 10 秒直到指示燈閃爍。",
            3: "NVR 錄影保存天數取決於硬碟容量與錄影解析度。"}
    r = gateway.embed(env["SUPPORT_RAG_LLM_KEY"], list(docs.values()) + ["晚上畫面太暗怎麼辦"])
    assert r.status == 200
    vecs = [d["embedding"] for d in sorted(r.body["data"], key=lambda d: d["index"])]
    doc_vecs, query_vec = vecs[:3], vecs[3]

    name = f"{TMP_PREFIX.replace('-', '_')}{int(time.time() * 1000)}"
    h = {"api-key": env["QDRANT_API_KEY"]}
    col = f"{Q}/collections/{name}"
    try:
        r = probe([
            {"method": "PUT", "url": col, "headers": h, "body": {
                "vectors": {"dense": {"size": 1024, "distance": "Cosine"}},
                "sparse_vectors": {"sparse": {}}}},
            {"method": "PUT", "url": f"{col}/points?wait=true", "headers": h, "body": {"points": [
                {"id": i, "vector": {"dense": v}, "payload": {"text": t}}
                for (i, t), v in zip(docs.items(), doc_vecs)]}},
            {"method": "POST", "url": f"{col}/points/query", "headers": h, "body": {
                "query": query_vec, "using": "dense", "limit": 3}},
        ])
        assert [x["status"] for x in r] == [200, 200, 200], r
        ranking = [p["id"] for p in r[2]["body"]["result"]["points"]]
        assert ranking[0] == 1, ranking  # night-vision doc answers "screen too dark at night"
    finally:
        probe([{"method": "DELETE", "url": col, "headers": h}])
    left = probe([{"url": f"{Q}/collections", "headers": h}])[0]["body"]["result"]["collections"]
    assert not [c["name"] for c in left if c["name"] == name]
