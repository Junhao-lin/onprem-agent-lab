# 夜間模式總結

分支：`overnight`，從 `main` 的 `e25cac1` 建立。依規則沒有合併回 main，也沒有 push。

## 起點

```
$ git status
On branch main
nothing to commit, working tree clean

$ git log --oneline -15
e25cac1 docs: publish first gateway benchmark baseline with methodology notes
3805a70 test(loadtest): unit + end-to-end bench tests; hide loadtest-* keys in dashboard
935aaa2 feat(loadtest): add streaming gateway benchmark (TTFT, tok/s, p50/p95)
e7f9df1 docs: add 1.9 verification report
4fdc63b docs(readme): dashboard reload on Windows, LiteLLM metering/limiter limitations
08e2bdb test(platform): verify failure, TTFT and in-flight panels; pin LiteLLM limiter bug
6d66a03 fix(monitoring): in-flight excludes the scrape itself; document unmetered 401s; add --reload
804717c test(platform): cover dashboard provisioning, queries and design rules
8d01033 feat(monitoring): add platform overview dashboard as code
301b00b docs(readme): note unauthenticated /metrics must be blocked at the proxy
e65918b test(platform): poll for parallel slot release instead of fixed sleep
db0bc6f docs: add 1.8 verification report and 1.7 re-verification
2903b31 test(platform): cover monitoring stack
702e807 feat(monitoring): add Prometheus and Grafana with provisioning
ac86f58 feat(gateway): expose Prometheus metrics from LiteLLM
```

起點時，platform 與 monitoring 兩個 profile 的 7 個服務都是 healthy。

## 工具與做法

- **Codex CLI** 0.172.0 不在 PATH 上，`scripts/overnight/run_codex.py` 會自動找到 `~/.codex/packages/standalone/current/bin/codex.exe`。指令：`codex exec --sandbox read-only -c model_reasoning_effort="medium"`。
  - 輸出以 UTF-8 存檔，逾時 15 分鐘。
  - 寫入 repo 前會遮蔽 `.env` 中的所有秘密值，`sk-` token 則改成 `sk-…末4碼`。
- **pytest**：`scripts/overnight/run_pytest.py <項目>` 以 Python 寫出 UTF-8 的 `reports/raw/<項目>/pytest.txt`。

## 各項進度

| 項目 | 狀態 | Codex 最終判定 | 主要 commit |
|---|---|---|---|
| A. 1.9 補驗證（Playwright） | 完成 | 有條件通過，剩 1 項低嚴重度問題（修正已達 3 輪上限） | `ecdf601` `30cee1f` `ee96c5d` `5cfc7ad` `3fceecd` `ff82b8f` `b9c024d` |
| B. 1.10 補驗證 + 維運風險段落 | 完成 | **通過**（第 2 輪） | `1397bfc` `2fa201e` `138fbce` `d3c3da0` |
| C. LiteLLM issue 草稿 | 完成 | **通過**（第 3 輪） | `e2c7307` `d113a62` `0e5830d` `4feff3a` `9162188` `32aaf5c` |
| D. 正式流量 + 截圖 | 完成 | 有條件通過（第 3 輪；唯一的建議已修正） | `c77b4d5` `b378994` `c8167a4` `a9da907` `65dba36` |
| E. 1.11 README | 完成 | **通過**（第 3 輪） | `0e6a8de` `dc472d5` `218d258` `786f5f7` |

### A. 1.9 補驗證

- **`tests/e2e/test_grafana.py`**（22 項）：
  - 從 `.env` 讀帳密，透過登入表單登入，帳密不會出現在任何輸出中；
  - 以 kiosk 模式開啟 platform-overview，截圖存為 `reports/raw/1.9/platform-overview-kiosk.png`；
  - 測試會先自行產生兩個應用的流量、429 與 Qdrant 呼叫。
- **斷言**：
  - 頁面上沒有 No data 類文字；
  - stat 面板不是空值；
  - 時間序列圖例每一列都有數值，且至少一條序列的 Max > 0；
  - 沒有面板錯誤；
  - 面板之間不重疊，也沒有超出視窗。
- **檢查過程的發現**：
  - Qdrant 只對 points 類端點記錄指標，所以閒置時「Qdrant p95 REST latency」面板本來就沒有資料。
  - Failed 面板中的 `None` 序列，來自 1.9 調查時我刻意送出的格式錯誤請求。LiteLLM 把這類 400 的 `exception_status` 記成 `None`。
- **截圖觀察**：寫在 `reports/verification/1.9.md` 附錄 A。
- **Codex**：
  - 共審閱 4 次：3 輪「意見 → 修正」，再加 1 次最終確認。全文在附錄 B 到 E。
  - 必修項目（密鑰遮蔽）已修正。
- **完整套件**：143 passed, 1 xfailed（`reports/raw/1.9/pytest.txt`）。
- **剩下的問題**（低嚴重度，未修）：`test_stat_tile_has_value` 只檢查「不是 `–`」，沒有檢查是否為數字。

### B. 1.10 補驗證

- **重新實測退化**：新增 `loadtest/repro_degradation.py`，依序執行 fresh → c=8 超載 → c=2 ×2 → c=4 → c=1 → 重啟，共 2 個循環。原始資料在 `reports/raw/1.10/degradation/`。

  | 情境 | c=2 吞吐 (tok/s) |
  |---|---:|
  | 剛重啟 | 163.8 / 165.6 |
  | 超載之後 | 77.1–89.3（−46% 到 −53%） |
  | 再次重啟 | 165.7 / 165.3 |

  c=1 與 c=4 不受影響。cycle 2 剛超載後只有部分請求變慢：第一次 2/8、第二次 6/8。
- **基準報告**新增獨立段落〈Operational risk〉，內容包含：
  - 退化前後的實測表；
  - 對正式環境的影響；
  - 4 個緩解選項，都尚未實作，留給你決定。

  Methodology 段落則改為引用這一段。
- **Codex 第 1 輪：有條件通過**，2 項必修：
  - **bench.py 的臨時 key 不能保證一定刪除。** 修正後會再查詢確認已刪除；刪除失敗時以結束碼 3 回報，也不會掩蓋原本的錯誤。
  - **「fully degraded」與原始資料不符。** 已改正。

  另外：
  - 補上原始資料：基準報告引用的 3 組原始輸出已存到 `reports/raw/1.10/`。
  - 新增測試：
    - 用假 SSE 伺服器驗證 TTFT 與 decode 公式，並做過突變檢查；
    - 驗證 summarize 的計算結果完全正確；
    - 驗證 key 清理在各種失敗情境下的行為。
  - `pyproject.toml` 加上 `xfail_strict = true`。
- **Codex 第 2 輪：通過**，沒有剩下的問題。
- **完整套件**：152 passed, 1 xfailed。

### C. LiteLLM 並發計數 bug 的 issue 草稿

- **issue 草稿**：`docs/upstream/litellm-parallel-counter.md`，**沒有送出**。
- **重現腳本**：`docs/upstream/repro_parallel_counter.py`，實際輸出存在 `reports/raw/C/repro-output.txt`。
- **重現了以下行為（LiteLLM 1.83.14）**：
  - 對 key 不允許的模型送出請求（`/v1/embeddings` 或 `/v1/chat/completions` 都一樣）：每次 401 讓計數 **−1**。
  - 計數到 −3 後，同時開 3 條串流都回 200，超過 key 的並發上限 2。
  - 格式錯誤的請求：每次 400 讓計數 **+1**。累積到 +2 之後，即使當下沒有任何請求在進行，下一個正常請求也會被回 **429**。
  - TTL 在每次更新時都重設為 60 秒。
  - 401 不會出現在 metrics；400 會被記錄，但 `exception_status` 是 `None`。
- **草稿內容**：
  - 「實測」和「推論」分開寫；
  - 原始碼位置有行號，逐字摘錄存在 `reports/raw/C/litellm-source-excerpts.txt`；
  - 版本資訊包含 image digest。
- **依指示維持現狀**：xfail(strict) 與 README 的記錄都保留，沒有加任何防護。
- **Codex**：
  - 第 1 輪：有條件通過。端點描述與腳本不一致；「誤判 429」沒有實測。兩項都已修正。
  - 第 2 輪：不通過。標為 observed 的 metrics 主張沒有證據。已補上證據並修正。
  - 第 3 輪：**通過**。

### D. 正式 key 流量與截圖

- **新增 `loadtest/app_traffic.py`**：
  - 使用兩把正式 key，速率控制在各自 rpm 上限的 50%，每個應用同一時間只有 1 個請求；
  - 混合串流 chat、非串流 chat 與 embeddings。
- **跑 5 分鐘的結果**：support-rag 75 回合、onboarding-agent 75 回合，全部回 200，TTFT p50 約 0.05 s。
- **新增 `scripts/screenshot_dashboard.py`**：用 Playwright 以 kiosk 模式截圖；只要有任何面板沒有資料，就不會存檔。
- **截圖 `docs/images/dashboard.png`**：16 個面板都有資料，包括 TTFT。我親自看過截圖。
- **截圖資料來源**（細節見 `reports/raw/D/screenshot.txt`）：
  - Qdrant 面板的資料來自 pytest，不是 app_traffic，因為 RAG 應用還沒做；
  - 時間軸是 UTC+8。
- **Codex**：
  - 第 1 輪：有條件通過。截圖時區與資料來源沒有說明，已補上。另外加了 `--fraction` 範圍檢查，也加了實際量測「同一時間在途請求數」的測試。
  - 第 2 輪：不通過。我把 Qdrant 資料歸到錯的那次 pytest 執行。已改用 Prometheus 的時間點，加上該次執行的遮蔽版輸出，證明正確的來源。
  - 第 3 輪：有條件通過。只剩行號引用有誤，已修正。
- **完整套件**：157 passed, 1 xfailed。

### E. 1.11 README

- **README 全面改寫**，包含：
  - 截圖；
  - 專案簡介；
  - mermaid 架構圖；
  - Quick Start：分 1–5 步，說明 `uv` 不在 PATH 時改用 `python -m uv`，並提供 bash 與 PowerShell 兩種驗證範例；
  - 服務、port 與 key 限額表；
  - 可觀測性；
  - 測試矩陣，含 e2e；
  - 第一版壓測結果與維運風險；
  - 安全性；
  - 已知限制，包括 LiteLLM 計數漂移、spend log 漏記、access log 中的完整 key；
  - Roadmap。
- **Quick Start 在運行中的平台上實測過的部分**：compose config、`bootstrap_keys.py`、bash curl、PowerShell `Invoke-RestMethod`。
  - **沒有從零開始重建平台**：那需要 `down -v` 刪除資料，夜間規則禁止。
- **新增 `tests/platform/test_readme.py`**（8 項），檢查：
  - 連結與截圖都存在；
  - 指令中的 script、compose 檔、profile、pytest 路徑與 marker 都真實存在且正確；
  - 不含真實 key 的材料；
  - 基準表與維運風險的數字和原始資料一致；
  - 限額表和 toml 一致。

  做過 4 種突變檢查。
- **Codex**：
  - 第 1 輪：有條件通過。PowerShell 步驟缺漏；README 中有真實 key 的末 4 碼。兩項都已修正。
  - 第 2 輪：不通過。marker 斷言偏弱，已修正。
  - 第 3 輪：**通過**。
- **完整套件**：165 passed, 1 xfailed。

## 卡住的問題

1. **LiteLLM 的 spend log 寫入問題，原因不明**（`reports/raw/incidents/spendlog-stall.txt`）：
   - **寫入曾中斷**：16:18 到約 16:27 UTC 之間的請求都沒有寫入 `LiteLLM_SpendLogs`，資料遺失，不是延遲寫入。我重啟了 litellm 單一服務，之後才自行恢復。
   - **一直漏記**：即使在正常的時候，chat completion 也大量漏記。app_traffic 的 5 分鐘內：

     | 請求 | 送出 | 有寫入的列數 |
     |---|---:|---:|
     | support-rag chat | 75 | 16 |
     | onboarding-agent chat | 75 | 8 |
     | embeddings | 75 | 70 |

     Prometheus 的指標有正確計入這些請求。
   - **影響**：`test_spend_log_increments` 曾經連續失敗，後來恢復。
   - **沒有往下查**：要查必須調高 LiteLLM 的 log level，這會改動設定，需要你決定。
2. **我的 LiteLLM 重啟造成約 15 分鐘的測試誤判**：Prometheus counter 歸零後，新舊序列有一段時間並存，測試輔助函式 `instant()` 取到舊序列的值，導致 e2e/dashboard 測試出現 22 個 error。舊序列離開時間窗後自行恢復。要不要讓 `instant()` 能處理 counter reset，留給你決定（1.9 的修正已達 3 輪上限）。

## 需要你決定的事

0. **【安全，優先】`POSTGRES_PASSWORD` 與 `REDIS_PASSWORD` 的明文進了本地 commit `0e5830d`**（檔案 `reports/raw/C/pytest.txt`）。
   - **原因**：某次執行有大量 error，pytest 的長 traceback 印出了整個 `env` fixture。
   - **範圍**：分支只在本地，沒有 push。掃描了全部 55 個 commit，只有這一個 blob 受影響。
   - **已做**：
     - `4feff3a` 已移除該檔案中的密碼；
     - 加了兩道防護：`env` fixture 的 repr 只顯示變數名稱、pytest 輸出寫檔前先遮蔽密鑰。兩者都有測試。
   - **沒有做**（規則禁止）：改寫歷史、修改 `.env`。
   - **請你決定**：
     - 是否輪換這兩組密碼（需要改 `.env` 並重建 postgres/redis 的認證）；
     - 合併或 push 之前，是否要清理 `overnight` 的分支歷史，例如 squash 或 filter。
   - 另外，我在定位這個問題時，有一次輸出沒有遮蔽完整，這兩組密碼因此出現在本次對話的工具輸出中。它們沒有寫進 repo，但這也是建議輪換的理由之一。
0b. **【安全】`bootstrap_keys.py` 與測試用 `GET /key/info?key=<完整 key>` 查詢 key**，所以 LiteLLM 容器的 access log 裡有完整的應用 key（`docker compose logs litellm` 看得到）。要不要改用不會把 key 放進 URL 的查詢方式，再輪換應用 key？

1. **1.9 剩下的低嚴重度問題**：要不要把 stat 面板的檢查加強為「必須是數字加單位」？Scrape targets 面板顯示的是文字「all up」，需要另外處理。
2. **Qdrant p95 REST latency 的點很稀疏**，幾乎看不到。要不要在儀表板開啟 `showPoints`？
3. **Ollama 超載後退化的緩解方式**：見 `docs/benchmarks/2026-11-26-baseline.md` 的〈Operational risk〉。選項有：維持 Gateway 並發上限總和不超過槽位數（目前已是如此）、加偵測告警、排程重啟、換 vLLM 後重測。
4. **LiteLLM spend log 漏記**（見〈卡住的問題〉1）：要不要調高 log level 追查，或改成以 Prometheus 指標作為用量的主要來源？
5. **讓 `app_traffic.py` 也呼叫 Qdrant**：這樣截圖中的 Qdrant 面板就會反映應用流量。比較適合等 Phase 2 的 RAG 應用完成後再做。
6. **Failed 面板會出現 `None` 序列**（LiteLLM 把格式錯誤的 400 記成 `None`）。要不要在面板中把 `None` 重新命名，例如改成「other / unknown」？

## 規則遵守情況

- **分支與 commit**：
  - 所有 commit 都在 `overnight` 分支上，從 `e25cac1` 開始；完整清單用 `git log --oneline main..overnight` 查看。
  - `main` 仍停在 `e25cac1`。
  - 沒有 push：分支沒有設定 upstream。
  - 沒有改寫任何既有 commit。
- **沒有做的事**：
  - 沒有修改 `.env`，也沒有修改 git 設定；
  - 沒有執行 `down -v`、`volume rm`、`prune` 等會刪除資料的指令。
  - 唯一的服務操作是**重啟 litellm 一次**，以及壓測腳本在設計上會重啟 ollama。
- **既有報告**：1.1–1.8 的驗證報告未修改。1.9 只在後面追加附錄 A–E。
- **沒有開始 Phase 2。**
- **違規：密碼進了 commit**。`POSTGRES_PASSWORD` 與 `REDIS_PASSWORD` 進入 commit `0e5830d`，違反「密鑰不進版控」。處理方式見〈需要你決定的事〉第 0 項。

## 明天早上該怎麼檢查

1. **先看安全事項**：〈需要你決定的事〉的 0 與 0b，決定是否輪換密碼，以及是否在合併前清理分支歷史。
2. **看變更**：
   ```bash
   git log --oneline main..overnight
   git diff --stat main..overnight
   ```
3. **看結論**：每一項都在 `reports/verification/` 下：
   - 1.9：附錄 A–E；
   - 1.10.md、C.md、D.md、E.md。

   原始證據在 `reports/raw/<項目>/`，包括 `pytest.txt`、Codex 的 prompt、回覆與 log、截圖、壓測原始資料。
4. **看圖**：
   - `docs/images/dashboard.png`：README 截圖；
   - `reports/raw/1.9/platform-overview-kiosk.png`：e2e 測試的截圖。
5. **自己重跑**（平台要先啟動）：
   ```bash
   python -m uv sync && python -m uv run playwright install chromium
   python -m uv run pytest            # 預期 165 passed, 1 xfailed，約 5 分鐘
   ```
   - 跑完後 `reports/raw/1.9/platform-overview-kiosk.png` 會被 e2e 測試重新產生，工作樹會顯示修改，這是正常的。
   - 如果剛重啟過 LiteLLM，dashboard 與 e2e 測試約有 15 分鐘會誤判，見〈卡住的問題〉2。
6. **讀新文件**：
   - `README.md`；
   - `docs/benchmarks/2026-11-26-baseline.md` 的〈Operational risk〉；
   - `docs/upstream/litellm-parallel-counter.md`：issue 草稿，尚未送出。
7. **確認沒問題後再合併**：例如 `git switch main && git merge --ff-only overnight`。如果要清理歷史，要在 merge 或 push 之前做。

## 早上處理（2026-11-27）

依你早上的決定處理，仍在 `overnight` 分支，沒有合併、沒有 push。

### 1. key 外洩源頭：改用 header 傳 key
- `scripts/bootstrap_keys.py`：`Gateway.request` 新增 `bearer` 參數，`key_info()` 改成用該 key 本身放在 `Authorization` header 呼叫 `GET /key/info`（不帶 `?key=`，LiteLLM 會回傳發出請求的 key 的資訊）。
- `tests/platform/test_virtual_keys.py`：3 處 `/key/info?key=` 改為 header。repo 中已沒有任何把 key 放進 URL 的呼叫（`/key/list?key_alias=` 只帶 alias）。
- 新測試 `tests/platform/test_container_logs.py`：
  - 加上 `run_last` marker，`tests/platform/conftest.py` 的 `pytest_collection_modifyitems` 會把它排到整個 session 最後，另有測試確認排序；
  - 掃描 `docker compose logs litellm`：不得出現兩把應用 key 與 master key 的完整值、不得有 `sk-` 開頭的長 token、不得有 `key=sk-`；
  - 失敗訊息只列變數名稱與數量，不會印出 log 內容。
- 驗證：改動前的 log 上這個測試**失敗**（找到 2 把應用 key 等），證明它抓得到；舊 log 要等第 2 項重建容器後才會清掉。
- README：移除「完整 key 出現在 access log」這條已知限制，改寫進〈安全性〉，測試表加上新檔案。

### 2. 換掉密碼與 key
- 新腳本 `scripts/rotate_service_passwords.py`（全程只印步驟與結果，不印任何值；密碼只經 stdin 與 `.env`）：
  - Postgres：`ALTER USER ... PASSWORD` 經 stdin 送進 psql，再寫入 `.env`；接著用容器自己的 IP 走 TCP（pg_hba 的 scram-sha-256 規則，loopback 是 trust 所以不用）驗證**新密碼可登入、舊密碼被拒**。
  - Redis：先寫 `.env`，`up -d --force-recreate redis` 讓 requirepass 讀到新值；驗證**新密碼 PONG、舊密碼被拒**。
  - 重建 litellm（`DATABASE_URL` 與 `REDIS_PASSWORD` 都在它的環境變數裡），等全部服務 healthy。Postgres 也被 compose 重建（它的 `POSTGRES_PASSWORD` 環境變數變了）；資料在 named volume，既有資料庫不會重新初始化。
  - 開發時踩到：Python 在 Windows 以文字模式寫 stdin 會把 LF 變成 CRLF，shell 的 `read` 會把多出來的 CR 當成密碼的一部分；改成以 bytes 寫 stdin。先用「正確密碼 True／錯誤密碼 False」試跑驗證函式才動手，因此沒有在錯誤狀態下改密碼。
- `bootstrap_keys.py --rotate`：兩把應用 key 換新（新的末 4 碼 `5dmg`、`pmKw`），舊 key 已刪除。驗證：舊 key 呼叫 `/v1/models` 回 **401**、新 key 回 **200**；`.env` 中只有這 4 個變數改變，其餘全部不變。
- `docker compose up -d --force-recreate litellm` 重建容器，舊 log 已清掉（沒有使用 `down -v`，沒有刪除 volume）。
- 重建後的 litellm log 跑過完整測試：`test_litellm_log_contains_no_keys` **通過**。
- 完整 pytest：**172 passed, 1 xfailed**（`reports/raw/morning/pytest.txt`，在第 3 項的改動之後執行，涵蓋第 1～3 項）。過程：
  - 第 1 次：`1 failed, 22 errors`，全部是重建 litellm 後 Prometheus counter 歸零的已知副作用（約 15 分鐘）。
  - 第 2 次（過了 15 分鐘）：剩 `test_in_flight_reads_zero_when_idle` 失敗，而且單獨重跑也穩定失敗。查到是**測試本身的時間 bug**，不是平台問題：
    - 它用 range query 的最後一步讀面板值，但 step 對齊在 15 秒格線上，最後一步可能落在它等待的那次新 scrape **之前**，於是讀到前一個測試的串流（即時 gauge 在測試前 7 秒已回到閒置）。重建 litellm 改變了 scrape 的相位，所以昨晚通過、今天穩定失敗。
    - 另外「等待新 scrape」其實沒有在等：它把 instant query 的 `value[0]`（評估時間，永遠是現在）當成 scrape 時間。
    - 修正：用 `timestamp()` 取得真正的 scrape 時間，並在那個時間點以 instant query 評估面板。反向驗證：握著一個長串流時，面板讀到 1（測試仍抓得到真的 in-flight）。commit `f117c21`。
- 改動前的 `.env` 備份在 scratchpad（repo 外），確認一切正常後會刪除。

### 3. 清理歷史與原始輸出遮罩
- 改寫範圍只有 `main..overnight`；`main` 仍是 `e25cac1`，沒有變動。
- 方法：`git filter-branch --index-filter`，在每個 commit 中，若 `reports/raw/C/pytest.txt` 是含密碼的那個 blob，就換成 `4feff3a` 中已遮罩的版本（同一次測試的輸出，只是遮罩過）。實際只有原本的 `0e5830d` 含有它。改寫後分支最新的 tree 與改寫前完全相同（diff 為空），只有 commit hash 改變。
- 刪除了 filter-branch 留下的備份 ref `refs/original/refs/heads/overnight`（它仍指向舊歷史）。另外，改寫時暫存工作區用的 stash 也會指到舊歷史，已 pop 掉。
- **掃描結果**（逐一檢查每個 commit 的所有 blob 與 commit 訊息，比對舊與新的全部密鑰值；腳本只印變數名稱與路徑）：
  - `main..overnight`：**沒有**任何舊密碼或完整 key。
  - 所有 ref（`--all`）：也**沒有**。
  - 另以 `sk-` 樣式掃描：只有 4 個 `sk-` 字串，都是測試原始碼裡自己定義的假 key（例如 401 測試用的錯誤 key），不是真實 key。
- 仍需注意：舊物件還在本機的 reflog 裡，直到 reflog 過期或執行 `git gc` 才會真正消失。這屬於刪除資料，我沒有執行。舊密碼與舊 key 已全部失效（第 2 項），所以風險只剩「看得到已作廢的值」。要立刻清掉的話：`git reflog expire --expire=now --all && git gc --prune=now`。
- **原始輸出一律先遮罩再寫檔**：
  - 新模組 `scripts/rawlog.py`：`write_raw(path, text)` 先把所有 `.env` 密鑰值換成 `[REDACTED]`、`sk-` token 換成 `sk-…末4碼`，再以 UTF-8／LF 寫檔；另有 CLI 形式 `<指令> | python -I scripts/rawlog.py <檔案>`，取代 shell 的 `>` 與 `tee`。
  - 改用它的寫檔程式：`scripts/overnight/run_pytest.py`、`run_codex.py`（含先前沒有遮罩的 `codex-prompt.md`）、`loadtest/bench.py`、`loadtest/repro_degradation.py`。
  - 新測試（`tests/platform/test_repo_hygiene.py`）：
    - `write_raw` 的遮罩單元測試（含 CRLF → LF）；
    - CLI 實測：把 `.env` 的所有真實密鑰值經 stdin 送進去，輸出檔中一個都不剩（失敗時只報數量）；
    - AST 靜態檢查：`scripts/`、`loadtest/`、`docs/` 底下任何 `write_text`／`write_bytes`／`open(..., "w"/"a"/"x")` 都必須經過 rawlog，例外清單附理由（rawlog 本身、寫 `.env` 的 bootstrap、寫 PNG 的截圖腳本）；另有測試確認偵測器抓得到每一種寫法；
    - 掃描 `reports/` 底下所有檔案（含未追蹤的）：沒有任何 `.env` 密鑰值，也沒有未遮罩的 `sk-` token（測試原始碼自己定義的假 key 除外）。
  - README〈安全性〉與測試表已更新。

### 4. spend log 限時調查（30 分鐘，實際約 10 分鐘，03:39–03:49 UTC）
- **假設「串流請求沒有寫入 spend log」不成立**：串流與非串流的 chat 都會漏記，條件相同。
- **原因已找到並驗證：request_id 碰撞。**
  - Ollama 的 OpenAI 相容 API 回傳的 id 是 `chatcmpl-<數字>`，DB 中 880 筆 chat 紀錄的數字落在 0–997，全部不同。
  - LiteLLM 拿 provider 的 id 當 `LiteLLM_SpendLogs` 的主鍵（`get_spend_logs_id()`），並用 `create_many(skip_duplicates=True)` 寫入，所以 id 重複的紀錄會被**靜默丟掉**。
  - id 空間已用掉約 88%，所以新的 chat 大約只有 12% 會被記錄。embedding 沒有 provider id，改用 UUID，所以不受影響。
- **驗證**（臨時 key，結束後刪除並確認）：20 筆 chat 中，id 原本沒被用過的 5 筆 → **5/5 有紀錄**；id 已存在的 15 筆 → **0/15**；embedding 10/10。預測與結果完全一致。
- 沒有調高 log level（不需要），沒有改設定，也沒有刪除 DB 資料。
- 昨晚「約 10 分鐘完全沒有寫入」沒有重現，可能同因，**未驗證**。
- 證據：`reports/raw/spendlog/`（`FINDINGS.md`、`spendlog_probe.py`、`run1-baseline.txt`、`run2-collision.txt`，輸出經 `scripts/rawlog.py` 寫檔）。README 的已知限制已改寫成確認後的原因。
- **需要你決定**：
  1. 要不要把 LiteLLM 的 provider 改成 `ollama_chat/`（預期會改用 UUID，**尚未驗證**，是設定變更）；或等第二階段換 vLLM（id 為 UUID）。
  2. 要不要寫成 LiteLLM 的 issue 草稿。
  3. 要不要把 `test_spend_log_increments`（目前只檢查總筆數增加，是弱斷言，抓不到這個問題）改成「這一筆請求自己的紀錄存在」。在目前環境它會失敗，或者標成 `xfail(strict)`。

### 早上處理的總結
- 完整測試：**172 passed, 1 xfailed**（`reports/raw/morning/pytest.txt`）。
- `main` 仍是 `e25cac1`，沒有合併、沒有 push。
- `.env` 只改了 4 個值：`POSTGRES_PASSWORD`、`REDIS_PASSWORD`、兩把應用 key，其餘不變。全程沒有印出任何值。
- 沒有使用 `down -v`，沒有刪除任何 volume。
- 改動前的 `.env` 備份（只在 scratchpad，不在 repo）已刪除，裡面都是已作廢的值。
- 早上檢查方式：
  - `git log --oneline main..overnight`
  - `python -m uv run pytest`：預期 172 passed, 1 xfailed。剛重建 litellm 後的 15 分鐘內，dashboard 與 e2e 測試會誤判。
  - `docker compose logs litellm | findstr sk-`：預期沒有輸出。

### 5. spend log 修正：改用 `ollama_chat/`（有效，已採用）
- **驗證**：
  - 先在 litellm 容器內用 SDK 試：非串流的 id 變成 `chatcmpl-<UUID>`。
  - 再改 proxy 設定：`chat-default` 改為 `ollama_chat/qwen2.5:7b-instruct`，`api_base` 改為 `http://ollama:11434`（Ollama 原生 `/api/chat`）。embedding 維持 `openai/bge-m3`，它本來就是 UUID。
  - 用臨時 key 每組送 20 筆：非串流 chat **20/20**、串流 chat **20/20**、embedding 20/20 都有 spend log 紀錄（`reports/raw/spendlog/run3-ollama-chat.txt`）。
- **測試加嚴**：
  - `test_spend_log_increments` 改寫為 `test_every_chat_has_its_own_spend_log_row`：臨時 key 送 3 筆非串流加 3 筆串流，每一個 response id 都必須在 spend log 中有這把 key 自己的紀錄，而且沒有多餘的。
  - 反向驗證：暫時還原成 `openai/` 時，這個測試會失敗（抓到 6 個 `chatcmpl-<短數字>` id）。
  - 另加 `test_chat_on_ollama_uses_native_provider`：只要 chat 的後端是 Ollama，就不得走 `/v1`。
- **完整 pytest：173 passed, 1 xfailed**（`reports/raw/morning-ollama-chat/pytest.txt`；等 litellm 重啟滿 15 分鐘後才執行）。
- **副作用（已寫進 README 已知限制）**：
  - 走 `ollama_chat/` 時，串流回應中**每個 chunk 的 id 都不同**（實測 22 個 chunk 有 21 個 id），不符合 OpenAI 規格；只依 id 合併 chunk 的 client 會出錯。
  - 換成 vLLM 後改回 `openai/`，就能同時解決這個問題與 spend log 碰撞。
- **需要你知道的事**：
  - 〈壓測與基準結果〉的數字是改用 `ollama_chat/` 之前、經 `/v1` 量測的，沒有重新量測。README 已註明。要不要重跑基準，由你決定。
  - 表中舊的 880 筆 `chatcmpl-<數字>` 紀錄保留，沒有刪除；之前漏記的 chat 無法補回。
- 依你的指示，因為改用 `ollama_chat/` 有效，所以**沒有**寫 docs/upstream 的 issue 草稿。
- commit：`5927ff7`（設定、測試與文件），以及本段總結。

### 6. 用 `ollama_chat/` 重跑 1.10 基準壓測
- **執行方式**：
  - 指令是 `python loadtest/bench.py --restart-backend`，並發 1/2/4/8/16，每一級開始前都重啟 Ollama 並暖機。
  - 使用臨時 key `loadtest-1795760885`。結束後已刪除並確認：腳本結束碼為 0，刪除失敗時會是 3。
  - 原始資料在 `reports/raw/1.10/ollama-chat-restart/`。
- **報告**：
  - 新增 `docs/benchmarks/2026-11-27-ollama-chat.md`，內含完整結果與「provider 變更前後比較」。
  - 舊的 `2026-11-26-baseline.md` 開頭加註「目前數字以新報告為準」，原內容未改。
  - README 的基準表已換成新數字，並附上結論。
- **比較**（舊為 `/v1`，新為 `ollama_chat`）：
  - **總吞吐**與**每請求 tok/s**：每一級都在 10% 以內，但一致偏低 1–6.5%，沒有任一級變高。
  - 可能原因（未驗證）：
    - gateway 要把 Ollama 原生的 NDJSON 串流逐 chunk 轉成 OpenAI 格式；
    - 測試機的狀態不同。
  - 區分方法：在內網直接對 Ollama 的 `/v1` 與 `/api/chat` 量 decode 速度，繞過 gateway。這次沒有做。
  - **TTFT p95**：
    - 並發 2 為 −12.5%、並發 4 為 +10.8%，超過 10%。
    - 但兩者方向相反，絕對值只有 −11 ms 與 +15 ms。每級只有 8／16 筆，p95 幾乎就是最慢的那一筆，同一級的 p50 只差 +2% 與 +1%。判斷為雜訊。
    - 並發 16 的 TTFT +7%，來自 decode 變慢造成的排隊時間。
  - **結論：已用新設定重測，結果一致**。飽和點仍是並發 4，容量規劃與 key 的並發上限不變。
- **測試**：
  - `test_benchmark_table_matches_raw_baseline` 改為比對新的原始資料。
  - 新增 `test_provider_comparison_matches_both_raw_runs`：比較表的新舊數字與 Δ 都必須和兩份 `summary.csv` 一致。反向驗證：改錯報告中一個 Δ 時，測試會失敗。
- **完整 pytest：174 passed, 1 xfailed**（`reports/raw/bench-ollama-chat/pytest.txt`）。
  - 第一次跑有 1 個失敗：README 表格已換成新數字，但測試仍比對舊資料。修正測試後通過。
- **沒有重跑**：`repro_degradation.py`（超載後的 c=2 退化）。README 已註明這部分仍是 `/v1` 的數字。要不要重跑，由你決定。

### 7. 用 `ollama_chat/` 重跑 `repro_degradation.py`，並修改結論措辭
- **重跑**：
  - 指令是 `python -I loadtest/repro_degradation.py`，共 2 輪、每輪 7 步。
  - 每一步都是獨立的 `bench.py` 執行，各用一把臨時 key，全部已刪除，步驟 log 中沒有刪除失敗的紀錄。
  - 原始資料在 `reports/raw/1.10/degradation-ollama-chat/`。
- **結果**：退化仍然重現，而且比舊設定更一致。

  | | `/v1`（舊） | `ollama_chat/`（目前） |
  |---|---|---|
  | 超載後 c=2 總吞吐 | 下降 46–53%（約 165 → 77–89 tok/s） | 下降 52–53%（約 159–161 → 75–77 tok/s） |
  | 退化出現方式 | 有一輪剛超載時只有部分請求變慢 | 兩輪都是超載後立即全部變慢 |

  - 其他現象與舊設定相同：TTFT 正常；並發 1 與並發 4 不受影響；只重啟 Ollama 就恢復。
  - 結論：這個問題與 gateway 走哪一個 Ollama API 無關，符合「狀態在 Ollama process 內」的判斷。
- **文件**：
  - `docs/benchmarks/2026-11-27-ollama-chat.md` 原本的「Not re-run」段落，改為新舊並列的退化表（14 步）與解讀。
  - README 的維運風險改為並列兩種設定的數字。
  - 舊基準報告的開頭註記也一併更新。
- **措辭**：依你的指示，README 與報告都不再寫「結果一致」，改為：

  > 差異在 10% 以內、飽和點仍為並發 4；但新設定每一級吞吐皆略低 1–6.5%，方向一致，推測為 LiteLLM 轉換 Ollama 原生串流格式的開銷，尚未驗證（每種設定各只跑一輪）

  - 報告是英文，所以這句原文放在 Conclusion，後面附英文翻譯。
  - 上面第 6 段的「結果一致」是當時的紀錄，保留不改。
- **測試**：
  - `test_ops_risk_numbers_match_degradation_data` 改為對兩份資料參數化。README 中每一種設定的下降區間、tok/s 區間，以及有沒有「部分請求」，都必須和各自的原始資料一致。
  - 新增 `test_degradation_comparison_matches_both_raw_runs`：報告中並列表的 14 列都必須和兩份 `summary.csv` 一致。
  - 比較測試改為檢查 README 與報告都含有上面這句結論，而且都不再出現「結果一致」或 "results are consistent"。
  - 反向驗證：改錯 README 的下降區間，或改錯表格的一格時，對應的測試都會失敗。
- **完整 pytest：176 passed, 1 xfailed**（`reports/raw/degradation-ollama-chat/pytest.txt`）。

### 8. Codex 完整驗證「不通過」的處理
Codex 確認的部分：歷史中沒有密碼與完整 key、LiteLLM log 乾淨、spend log 正確、壓測數字與 CSV 相符。以下 5 項是它判定不通過的原因：

1. **1.9 截圖被測試覆寫**（commit `cee002a`）
   - 已用 `git restore` 還原成 commit 的版本。
   - e2e 測試的截圖改存到 git 忽略的 `reports/raw/1.9/latest/`，版控只保留驗證當時的那張。
   - 我親自看過版控中那張圖，數值與 1.9 報告附錄 A 一致：Requests 156、Error rate 16.8%、p95 latency 8.89 s、p95 TTFT 479.00 ms、In-flight 0、Collections 1、Vectors 3。附錄 A 已補註此事。
   - 新增測試 `test_e2e_screenshot_goes_to_ignored_path`。
   - 跑完 e2e 後，`git status` 沒有出現這張圖。
2. **測試數量差異**
   - Codex 跑的是 `pytest tests/platform`，結果 154 passed + 1 xfailed，共 155 個。我先前回報的 176 passed 是完整套件，多了 `tests/e2e` 的 22 個 Playwright 測試：154 + 22 = 176。
   - 兩邊都沒有錯，只是路徑不同。
   - README 的〈測試〉加了各路徑的測試數量與指令，並由 `test_readme_test_counts_match_collection` 與 `pytest --collect-only` 比對。
   - 本次新增 8 個測試後，`tests/platform` 是 163 個，`tests/e2e` 是 22 個，合計 185 個。
3. **`docs/images/dashboard.png` 混入測試流量**（commit `2818f89`）
   - 舊圖的 10 分鐘範圍左側，包含一次完整 pytest 的尾段：p95 latency 9.50 s、TTFT 488 ms。Qdrant 的資料也來自測試。
   - 重拍的做法：
     - 先跑 10 分鐘 `app_traffic.py`，只用兩把正式 key，150 + 150 輪全部回 200；
     - 期間不跑任何會連線 gateway 的測試；
     - 截取完全落在流量期間的 7 分鐘：2026-11-27 15:23:32–15:30:32（UTC+8）。
   - 新增 `scripts/dashboard_window_traffic.py`，用 Prometheus 查同一時間窗。結果只有 `onboarding-agent` 約 105 筆、`support-rag` 約 210 筆，沒有失敗，也沒有 Qdrant 呼叫。
   - 新圖：Requests 315、Error rate 0.0%、p95 latency 3.83 s、p95 TTFT 48.73 ms。
   - Qdrant 面板沒有資料，因為還沒有應用呼叫 Qdrant。為此 `screenshot_dashboard.py` 加了 `--allow-idle-qdrant`，只豁免 Qdrant 面板，並會列出被豁免的面板。
   - README 圖說寫明時間範圍與流量來源。證據在 `reports/raw/dashboard/`。
4. **`git diff --check main..overnight`**（commit `6396033`）
   - 去掉 25 個檔案的行尾空白與檔尾空行，都是原始 log 與報告，只動空白。
   - D.md 與 Codex D 摘要中的 Markdown 強制換行，從兩個空格改成行尾 `\`，渲染結果相同。
   - `D/pytest-C-run-0026-redacted.txt` 被判為「衝突標記」是誤報：那行是 pytest 的摘要行 `======= 2 failed ...`。處理方式是在 `.gitattributes` 對 `reports/raw/**` 設定 `conflict-marker-size=32`，不改原始輸出。
   - `rawlog.write_raw` 今後會自動去除行尾空白。
   - 新增 `test_tracked_text_files_pass_git_diff_check`，檢查所有追蹤中的文字檔。
   - 現在 `git diff --check main..overnight` 沒有任何輸出。
5. **benchmark Markdown 與 raw CSV 自動比對**：已有，並補齊。測試都在 `tests/platform/test_readme.py`：
   - 已有：
     - `test_benchmark_table_matches_raw_baseline`：README 基準表 vs 目前那次壓測的 `summary.csv`；
     - `test_provider_comparison_matches_both_raw_runs`：新舊比較表與 Δ vs 兩份 `summary.csv`；
     - `test_ops_risk_numbers_match_degradation_data[...]`：README 維運風險的區間 vs 兩份退化資料；
     - `test_degradation_comparison_matches_both_raw_runs`：退化並列表 vs 兩份退化資料。
   - 本次新增：
     - `test_benchmark_report_results_match_raw_summary[2026-11-26-baseline.md / 2026-11-27-ollama-chat.md]`：兩份報告的 Results 表逐列等於原始 `summary.md`；
     - `test_baseline_degradation_and_back_to_back_tables_match_raw`：舊報告的退化表與 back-to-back 表 vs CSV。
   - 反向驗證：在這三張表各改錯一格，對應的測試都會失敗。
- **測試結果**（分路徑執行）：
  - `tests/platform`：**162 passed, 1 xfailed**（`reports/raw/codex-fix-platform/pytest.txt`）。
  - `tests/e2e`：**22 passed**（`reports/raw/codex-fix-e2e/pytest.txt`）。
  - 合計 184 passed, 1 xfailed。
- 跑完測試後 `git status` 乾淨：e2e 截圖只寫進被忽略的 `latest/`。

