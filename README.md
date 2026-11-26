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
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile platform up -d
# 純 CPU：
# docker compose --profile platform up -d
docker compose ps   # 確認所有服務為 healthy；ollama-init 拉完模型後會 Exited (0)
```

## 服務與 Port

| 服務 | Profile | Host Port | 用途 |
|---|---|---|---|
| postgres | platform | —（僅內網） | LiteLLM 的 key / spend / log |
| redis | platform | —（僅內網） | LiteLLM 限流計數、快取（需密碼） |
| ollama | platform | —（僅內網） | 推論後端（OpenAI 相容 API :11434），應用不得直連 |
| ollama-init | platform | — | 一次性工作：拉取 `OLLAMA_CHAT_MODEL`、`OLLAMA_EMBED_MODEL` |
| litellm | platform | `127.0.0.1:4000` | LLM Gateway；應用唯一入口（OpenAI 相容），Admin UI 在 `/ui` |

應用一律呼叫 Gateway 的穩定別名，不直接指定後端模型：

| 別名 | 後端（目前） | 用途 |
|---|---|---|
| `chat-default` | Ollama `qwen2.5:7b-instruct` | 對話 / 生成 |
| `embed-default` | Ollama `bge-m3`（1024 維） | 向量化 |

## 應用 A：產品客服 RAG

TODO：章節切塊、hybrid search + rerank、附出處、低分拒答。

## 應用 B：新人教學 Agent

TODO：YAML 課程、Docker 沙盒檢查、MCP 工具。

## 可觀測性

TODO

## 測試與評測

TODO：pytest、壓測（TTFT / tokens/s / p95 / 並發）、RAG 評測集。

## 切換到 vLLM

TODO

## 安全性

- 所有密鑰只放 `.env`（已列入 `.gitignore`），版控中僅有 `.env.example`。

## 已知限制與 Roadmap

- [ ] Phase 1：平台（推論、Gateway、向量庫、監控、壓測）
- [ ] Phase 2：應用 A — 產品客服 RAG
- [ ] Phase 3：應用 B — 新人教學 Agent
