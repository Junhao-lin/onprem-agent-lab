# onprem-agent-lab

地端 LLM 平台與其上的兩個應用：攝影機產品客服 RAG、新人教學 Agent。

> 🚧 開發中 — 目前進度：Phase 1（平台）

## 目錄

1. [專案簡介](#專案簡介)
2. [為什麼地端](#為什麼地端)
3. [架構](#架構)
4. [Quick Start](#quick-start)
5. [服務與 Port](#服務與-port)
6. [應用 A：產品客服 RAG](#應用-a產品客服-rag)
7. [應用 B：新人教學 Agent](#應用-b新人教學-agent)
8. [可觀測性](#可觀測性)
9. [測試與評測](#測試與評測)
10. [切換到 vLLM](#切換到-vllm)
11. [安全性](#安全性)
12. [已知限制與 Roadmap](#已知限制與-roadmap)

## 專案簡介

TODO

## 為什麼地端

TODO：資料不出網、成本可控、推論後端可替換。

## 架構

TODO：架構圖。

- **推論**：Ollama（OpenAI 相容 API），可替換為 vLLM
- **Gateway**：LiteLLM Proxy + PostgreSQL + Redis；每個應用一把 virtual key，設 rpm / tpm / 並發上限
- **向量庫**：Qdrant
- **監控**：Prometheus + Grafana

## Quick Start

前置需求：Docker（含 Compose v2）、NVIDIA GPU + Container Toolkit（可選）。

```bash
cp .env.example .env   # 填入所有 change-me
# 有 NVIDIA GPU：
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile platform --profile monitoring up -d
# 純 CPU（拿掉 gpu override）；只要平台不要監控則拿掉 --profile monitoring：
# docker compose --profile platform --profile monitoring up -d
docker compose ps   # 確認所有服務為 healthy；ollama-init 拉完模型後會 Exited (0)

# 建立／更新各應用的 virtual key（寫入 .env，可重複執行）
python scripts/bootstrap_keys.py
```

## 服務與 Port

| 服務 | Profile | Host Port | 用途 |
|---|---|---|---|
| postgres | platform | —（僅內網） | LiteLLM 的 key / spend / log |
| redis | platform | —（僅內網） | LiteLLM 限流計數、快取（需密碼） |
| ollama | platform | —（僅內網） | 推論後端（OpenAI 相容 API :11434），應用不得直連 |
| ollama-init | platform | — | 一次性工作：拉取 `OLLAMA_CHAT_MODEL`、`OLLAMA_EMBED_MODEL` |
| litellm | platform | `127.0.0.1:4000` | LLM Gateway；應用唯一入口（OpenAI 相容），Admin UI 在 `/ui` |
| qdrant | platform | —（僅內網；除錯時見下方） | 向量庫（REST :6333、gRPC :6334）；需 `api-key`；telemetry 關閉 |
| prometheus | monitoring | —（僅內網；除錯時見下方） | 抓取 litellm、qdrant 指標；保留 15 天 |
| grafana | monitoring | `127.0.0.1:3000` | 儀表板；帳密取自 `.env`，資料來源自動 provision，回報／更新檢查關閉 |

**除錯用：暫時開放內部服務的 port**

預設只有 LiteLLM（`127.0.0.1:4000`）與 Grafana（`127.0.0.1:3000`）對 host 開放。需要從 host 檢查 Qdrant（例如開 `/dashboard`）或 Prometheus UI 時，
加上 `docker-compose.debug.yml`，port 會綁在 `127.0.0.1`，可用 `.env` 的 `QDRANT_HTTP_PORT`、`QDRANT_GRPC_PORT`、`PROMETHEUS_PORT` 改號：

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.debug.yml --profile platform up -d qdrant
# 除錯完關閉：拿掉 debug override 再 up 一次
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile platform up -d qdrant
```

應用一律呼叫 Gateway 的穩定別名，不直接指定後端模型：

| 別名 | 後端（目前） | 用途 |
|---|---|---|
| `chat-default` | Ollama `qwen2.5:7b-instruct` | 對話 / 生成 |
| `embed-default` | Ollama `bge-m3`（1024 維） | 向量化 |

### 每個應用一把 virtual key

限額定義在 [`infra/litellm/virtual-keys.toml`](infra/litellm/virtual-keys.toml)（limits as code），
由 `scripts/bootstrap_keys.py` 套用；key 值只寫進 `.env`。

| Key alias | 可用模型 | rpm | tpm | 並發 |
|---|---|---|---|---|
| `support-rag` | chat-default, embed-default | 60 | 100k | 2 |
| `onboarding-agent` | chat-default | 30 | 60k | 2 |

- 兩個應用的並發上限加總 = Ollama `OLLAMA_NUM_PARALLEL`（4），一個應用無法佔滿推論資源；超額請求在 Gateway 直接回 429。
- 限流計數存在 Redis（跨 worker／replica 共享）。為此啟用了 LiteLLM 的 Redis cache，但設 `mode: default_off`，**LLM 回應不會被快取**，除非請求明確帶 `cache: {"use-cache": true}`。

## 應用 A：產品客服 RAG

TODO：章節切塊、hybrid search + rerank、附出處、低分拒答。

## 應用 B：新人教學 Agent

TODO：YAML 課程、Docker 沙盒檢查、MCP 工具。

## 可觀測性

- **LiteLLM** 開啟 `prometheus` callback（免費版即可），`/metrics/` 提供請求數、tokens、延遲、TTFT、進行中請求等，皆帶 `api_key_alias` label，可依應用拆分。
- **Qdrant** `/metrics` 需 API key：Prometheus 以 compose secret（值取自 `.env` 的 `QDRANT_API_KEY`）掛成 `/run/secrets/qdrant_api_key`，設定檔只寫 `credentials_file`。
- **Grafana** 資料來源由 `infra/grafana/provisioning/` 自動建立（唯讀）；儀表板 JSON 放 `infra/grafana/dashboards/`（1.9）。
- Ollama 本身不提供 Prometheus 指標；推論端指標待換 vLLM 後補齊。

TODO：儀表板截圖

## 測試與評測

### 平台測試（pytest）

需要平台與監控已啟動（`--profile platform --profile monitoring`）且 `.env` 已填好、已跑過 `bootstrap_keys.py`。

```bash
pip install uv            # 若尚未安裝；或 python -m uv ...
uv sync                   # 建立 .venv，安裝 pytest
uv run pytest tests/platform            # 全部（約 15 秒）
uv run pytest tests/platform -m "not llm"   # 跳過會呼叫模型的測試
```

| 檔案 | 驗證內容 |
|---|---|
| `test_repo_hygiene.py` | `.env`／壓測結果不進版控、tracked 檔案無密鑰值、`.sh` 為 LF、image 皆釘版本、`.env` 與 gateway 模型名一致 |
| `test_containers.py` | 服務 healthy、ollama-init exit 0、**只有 gateway 對 host 開 port 且綁 127.0.0.1**、named volume、Redis 未認證被拒、Qdrant telemetry 關閉（檢查容器環境變數） |
| `test_gateway.py` | readiness（db + redis）、錯誤 key 401、模型清單只有別名、chat／串流／embedding 1024 維、spend log 寫入 |
| `test_virtual_keys.py` | key 限額與 `virtual-keys.toml` 一致、模型白名單、rpm／tpm／並發觸發 429、限流計數在 Redis、回應不被快取、bootstrap 冪等且輸出只含 `sk-…末4碼` |
| `test_monitoring.py` | Prometheus 三個 target 皆 up、Qdrant 抓取用 secret 檔、gateway 請求依 `api_key_alias` 出現在 Prometheus、Grafana 需登入、資料來源 provision 且健康、回報功能關閉 |
| `test_qdrant.py` | 健康檢查免驗證、無 key／錯誤 key 401、經 gateway 產生 embedding → 寫入 → 查詢的端到端流程 |

設計重點：
- 內部服務沒有 host port，測試透過臨時 probe 容器（`python:3.12.16-alpine3.24`）在 `oal-backend` 網路內發 HTTP；請求內容（含密鑰）經 stdin 傳入，不出現在命令列。
- 限流測試使用臨時 key（`pytest-tmp-` 前綴，極小限額），測完刪除；應用的正式 key 只讀不改。
- 測試一律以 Python 撰寫，避免 shell 引號差異。

### 壓測與 RAG 評測

TODO：壓測（TTFT / tokens/s / p95 / 並發）、RAG 評測集。

## 切換到 vLLM

TODO

## 安全性

- 所有密鑰只放 `.env`（已列入 `.gitignore`），版控中僅有 `.env.example`。
- 設定檔（`infra/litellm/config.yaml` 等）只以 `os.environ/...` 引用密鑰，不寫明文。
- 腳本輸出的 key 一律遮罩為 **`sk-` + `…` + 末 4 碼**（例：`sk-…NFWw`）：前 3 碼固定為 `sk-` 無辨識度，末 4 碼足以區分不同 key，且為業界常見做法；完整 key 只寫入 `.env`。
- 只有 Gateway 與 Grafana 對 host 開放且只綁 `127.0.0.1`；Postgres、Redis、Ollama、Qdrant、Prometheus 預設不對 host 開 port（除錯 override 見〈服務與 Port〉）。
- LiteLLM `/metrics/` 不需驗證（Prometheus 無須持有 master key），因此只能從內網與本機 loopback 存取。
- Qdrant 所有資料／collection API 需 `api-key`；僅健康檢查（`/healthz`、`/readyz`、`/livez`）免驗證。

## 已知限制與 Roadmap

**已知限制**

- LiteLLM `/metrics/` 目前免驗證（僅內網與 `127.0.0.1` 可達）。之後加入 Nginx 等反向代理對外時，**必須在代理層阻擋外部存取 `/metrics`**。
- Ollama 不提供 Prometheus 指標；推論端（GPU、佇列）指標待換 vLLM 後補齊。

**Roadmap**

- [ ] Phase 1：平台（推論、Gateway、向量庫、監控、壓測）
- [ ] Phase 2：應用 A — 產品客服 RAG
- [ ] Phase 3：應用 B — 新人教學 Agent
