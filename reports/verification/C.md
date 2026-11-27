# 項目 C 驗證報告：LiteLLM 並發計數 bug 的 issue 草稿

> 夜間模式：Codex 唯讀審閱證據，未親自執行。

- **範圍**：
  - `docs/upstream/litellm-parallel-counter.md`：issue 草稿，**未送出**
  - `docs/upstream/repro_parallel_counter.py`
- **依決定維持現狀**：xfail(strict) 測試與 README 記錄都保留，沒有加入任何防護。
- **證據**：`reports/raw/C/`，內含：
  - `repro-output.txt`：重現腳本的實際輸出
  - `pytest.txt`：完整套件
  - `codex-*`：prompt、回覆與 log

## 第 1 輪（commit `e2c7307`）

### Codex 回覆（全文）

## 總結：有條件通過

草稿明確標示「Draft — not submitted」，包含重現步驟與版本資訊；現有輸出支持 **401 後計數每次 −1**，並顯示計數為 −2 時，三個串流請求都得到 200。完整套件紀錄為 **152 passed、1 xfailed，exit code 0**；xfail(strict=True) 與 README 的限制說明仍在。

但證據對 **400 導致 +1** 只提供間接支持，沒有證明 TTL 說法或「兩次 malformed request 後會 429」。腳本也依賴本 repo 的設定與服務，尚非獨立、可直接交給上游的重現案例。因此不宜視為每項主張都已由輸出驗證。

## 逐條驗收

1. **草稿、重現步驟、影響與版本：通過。** 草稿第 3 行標示未送出；第 38–53 行列步驟，第 123–132 行列 LiteLLM 版本、image digest、Python、Redis 等資訊。
2. **步驟與腳本一致、輸出支持主張：有條件通過。** 輸出支持三次 401 後計數由 0 降至 −3，以及計數 −2 時三個串流皆回 200（草稿第 67–75 行）。但腳本發送的是 `/v1/embeddings`，草稿步驟 4 寫「embedding requests」，標題與影響說明卻稱 chat；400 的 +1 是由 −3 變 −2 推得，沒有乾淨基線單獨驗證。
3. **可能原因標為推測、原始碼位置合理：有條件通過。** 標題及 Hypothesis 區塊清楚表明尚未 debugger 驗證；所列 limiter 與 managed-files hook 路徑看來相關。但「always decrements」及各錯誤所處 hook 順序尚未由附帶輸出證明，建議降低確定語氣並加上對應原始碼行號。
4. **維持現狀：通過。** `test_auth_rejection_does_not_skew_parallel_counter` 仍為 `xfail(strict=True)`；README 仍記錄限制。`pytest.txt` 記錄該 xfail、152 passed，exit code 0；未見此 commit 修改測試或 README，也未見防護或 gateway 行為變更。
5. **遮罩 key 與清理：有條件通過。** 腳本和輸出只顯示 key 末四碼，沒有完整 key。腳本以 `finally` 嘗試刪 key，但不驗證刪除成功；建立 key 後、進入 `try` 前若發生例外，也不會執行清理。
6. **完整套件通過：通過。** `reports/raw/C/pytest.txt` 記錄 153 項收集、152 passed、1 xfailed，exit code 0。

## 問題清單

- **必修｜`docs/upstream/litellm-parallel-counter.md:1, 15–17, 51–53`**：標題及表格稱為 chat，但腳本實際用 embedding endpoint 驗證 401。統一描述為 embedding，或改腳本與輸出，確保用的是同一類請求。
- **必修｜`docs/upstream/litellm-parallel-counter.md:29–31`**：輸出只記錄一次 malformed request 後 +1，沒有驗證兩次 malformed request 後下一個正常請求會 429。將此列為推論，或補上相應實測證據。
- **建議｜`docs/upstream/litellm-parallel-counter.md:19–20`**：raw output 沒有顯示 TTL 或其刷新方式。補上 Redis TTL 讀值／可核查的來源，否則刪除這項具體主張。
- **建議｜`docs/upstream/litellm-parallel-counter.md:40–56`、`docs/upstream/repro_parallel_counter.py:23–40, 55–59`**：重現流程依賴 repo 的 `.env`、Docker Compose、模型別名、Redis 服務與本機設定；不便讓上游獨立重現。補充最小獨立設定及必要環境條件，或清楚標示目前只是 repo 內重現。
- **建議｜`docs/upstream/repro_parallel_counter.py:63–64`**：固定等待 0.5 秒後讀計數，依賴非同步 callback 在該時間內完成，可能造成偶發誤判。改為有上限的輪詢，直到計數穩定或逾時。
- **建議｜`docs/upstream/repro_parallel_counter.py:99–108, 124–125`**：清理只做一次刪除且不檢查結果；若刪除失敗，臨時 key 可能殘留。把產生 key 後的所有可能失敗路徑納入 `try/finally`，並確認刪除結果；避免直接刪除可能與他人衝突的固定 alias。
- **建議｜`docs/upstream/litellm-parallel-counter.md:24–28, 80–99`**：負計數下的超額併發有觀察支持，但「加 N 個併發名額」及 hook 時序仍是推論。將推論與直接觀測分開表述，並提供引用原始碼的行號或連結。

我沒有親自執行任何東西；只讀取指定檔案與 git 歷史。

### 依第 1 輪意見所做的修正

| Codex 意見 | 處理 |
|---|---|
| 必修：標題寫 chat，腳本卻用 embeddings 端點驗證 401 | 腳本 A 情境同時測兩種端點：2 次 `/v1/embeddings` 加 1 次 `/v1/chat/completions`（`model: embed-default`），每次都是 −1。草稿表格改寫為兩個端點都適用 |
| 必修：「兩次 400 後會誤判 429」沒有實測 | 新增 B 情境，在新的 key 上實測：兩次 400 → 計數 +2 → 下一個一般請求（沒有其他請求在進行）回 **429** |
| 建議：TTL 說法沒有證據 | 每一步都讀取 Redis TTL，輸出顯示每次更新後都重設為 58–59 秒 |
| 建議：重現環境依賴本 repo | 草稿明確標示「Verified only with this repo's harness」，並列出最小設定步驟（curl 與 redis-cli）；送出前的待辦清單也加入「換成最小設定」 |
| 建議：固定等 0.5 秒才讀計數 | 改為輪詢：連續兩次讀到相同值才採用，最多等 5 秒 |
| 建議：清理不完整、alias 固定 | 新增 `TempKey`：<br>• 每個情境的 alias 都不同（含毫秒時間戳）<br>• 建立 key 失敗也會清理<br>• 刪除後以 `/key/list` 確認，失敗時警告，但不拋出例外 |
| 建議：推論與觀測混在一起、缺原始碼行號 | 〈Impact〉拆成「observed」與「inferred, not measured」兩部分；〈Possible cause〉先列原始碼事實並附行號（limiter v3 第 1277、1593–1604、1761、1783–1796 行；`auth_checks.py:2786`；`managed_files.py:632`；`utils.py:1433`），再列假設 |

重新執行腳本，結果在 `reports/raw/C/repro-output.txt`：LiteLLM 1.83.14，A、B 兩個情境都重現。

修正後的完整套件：152 passed, 1 xfailed。


## 第 2 輪（commit `d113a62`）

> 夜間模式：Codex 唯讀審閱證據，未親自執行。

### Codex 回覆（全文）

## 總結：不通過

第 1 輪兩項必修已修正，且新輸出直接支持「兩次 400 後正常請求回 429」。但草稿仍有多項標示為 **observed** 的主張無法在指定的 `repro-output.txt` 找到對應證據，未符合驗收條件 2。

## 逐條驗收

1. **第 1 輪必修：通過。** 草稿列出 `/v1/embeddings` 和 `/v1/chat/completions` 兩種 401 端點，與腳本及輸出一致。B 情境在新 key 上記錄兩次 400、計數升至 +2，接著一般請求回 429。
2. **Observed 主張與推論：不通過。** 計數、TTL、HTTP 狀態及三個串流均回 200 等主張可在輸出找到；上限外推也標為推論。但草稿其他標示為觀察的主張——例如錯誤未計入 Prometheus、400 的 metric 標籤，以及部署影響上限——不在 `repro-output.txt` 中。可能原因雖標成 hypothesis，該段的原始碼描述也不是這份輸出所能佐證。
3. **重現步驟、影響、版本、未送出標示：通過。** 草稿有兩個情境的步驟、影響說明、LiteLLM 等版本資訊，並清楚標示未送出。
4. **腳本安全與計數讀取：有條件通過。** 腳本只輸出遮罩 key；`TempKey` 在正常離開及建立失敗路徑都會嘗試刪除，並以 `/key/list` 查核；計數採穩定值輪詢，不依賴固定等待。不過輸出沒有記錄刪除查核結果，故無法由指定證據確認本次兩把 key 確已刪除。
5. **維持現狀：通過。** `pytest.txt` 記錄 `xfail(strict=True)` 測試仍為 xfail、152 passed；README 仍記錄限制。`d113a62` 未修改測試或 README，亦未見加入防護。
6. **完整套件：通過。** `pytest.txt` 結尾記錄 152 passed、1 xfailed。

## 剩餘問題

- **必修｜[litellm-parallel-counter.md](/D:/onprem-agent-lab/docs/upstream/litellm-parallel-counter.md:31)**：metrics、部署影響等觀察主張沒有 `repro-output.txt` 對應行。請補上驗收範圍允許的直接證據，或移除／改標為推論。
- **建議｜[repro_parallel_counter.py](/D:/onprem-agent-lab/docs/upstream/repro_parallel_counter.py:144)**：刪除後雖會查詢確認，但輸出未記錄查核結果。建議印出成功確認，讓本次清理可由輸出核對。

仍有必修項，因此判定不通過。**我沒有親自執行任何東西；只閱讀檔案與 Git 歷史。**

### 依第 2 輪意見所做的修正（`0e5830d`）

| Codex 意見 | 處理 |
|---|---|
| 必修：「標記為 observed 的主張」（metrics、部署限制）在 repro-output.txt 中找不到 | 腳本在每個情境結束時，從 gateway 的 `/metrics/` 讀出該臨時 key 的 `litellm_proxy_failed_requests_metric_total`：<br>• A 情境（401）：**沒有任何序列**<br>• B 情境（400）：`exception_status="None"`、`AttributeError` = 2.0；429 = 1.0<br>草稿中的部署限制段落改標為「Deployment context (from this repo's configuration, not measured here)」，並指向 `docker-compose.yml` 與 `virtual-keys.toml`。「計數值本身沒有被匯出」限定為「只檢查了 `/metrics/`」 |
| 原始碼描述沒有證據 | 引用的 LiteLLM 原始碼行逐字存到 `reports/raw/C/litellm-source-excerpts.txt`，草稿也標明了出處 |
| 建議：輸出沒有記錄刪除確認的結果 | 每個情境結束時印出 `cleanup: <alias> deleted (confirmed via /key/list)` |

重跑腳本後的新輸出在 `reports/raw/C/repro-output.txt`。A、B 兩個情境都重現，兩把臨時 key 都已確認刪除。

### 完整套件：與本項無關的失敗

修正第 2 輪後的完整套件（`reports/raw/C/pytest.txt`）**沒有全數通過**：

1. **`test_spend_log_increments` 失敗。** LiteLLM 自 16:18:05 UTC 起不再寫入 `LiteLLM_SpendLogs`，原因不明。
   - 重啟 litellm 服務之後仍未恢復。
   - Postgres 仍可寫入。
   - 證據與已排除的原因記錄在 `reports/raw/incidents/spendlog-stall.txt`。
   - 項目 C 只改了 `docs/upstream/` 與 `reports/`，沒有改 gateway 設定或行為。
   - 這件事已列為**卡住、需要使用者決定**的事項。
2. **e2e 與 dashboard 相關測試共 22 個 error、1 個 failure。** 這是上面重啟 LiteLLM 的副作用：
   - 重啟後，Prometheus 中的 LiteLLM counter 歸零（例如 185 → 1）。
   - 測試輔助函式 `instant()` 查詢 15 分鐘時間窗，這段時間內新舊序列並存，函式取到舊序列的最後一個值，「counter 增加」的判斷因此失敗。
   - 舊序列離開時間窗後會自行恢復。之後會重跑確認，見下文。

### 後續：重跑結果與安全事件

- **舊序列離開 15 分鐘時間窗後重跑完整套件**：1 failed（`test_no_secret_values_in_tracked_files`）、151 passed。e2e 與 dashboard 測試全部恢復，`test_spend_log_increments` 也再次通過（spend log 已自行恢復寫入，細節見 incident 檔）。
- **安全事件**：失敗的那一項正確抓到 `0e5830d` 中的 `reports/raw/C/pytest.txt` 含有 `POSTGRES_PASSWORD` 與 `REDIS_PASSWORD` 的明文。
  - 原因：前一次執行有 22 個 error，pytest 的長 traceback 把 `env` fixture 整個 dict 印出來了。
  - 掃描全部 55 個 commit 的所有 blob，受影響的只有這一個。
  - 依夜間規則**沒有改寫歷史**。`4feff3a` 已替換這個檔案，並從兩處防止再發生：
    - `env` fixture 改成 `MaskedEnv`，repr 只顯示變數名稱；
    - `run_pytest.py` 寫檔前遮蔽所有密鑰。

    兩處都有測試，也做過突變檢查。
  - 是否輪換這兩組密碼、是否在 push 前清理分支歷史，留給使用者決定。
- **最終完整套件**：154 passed, 1 xfailed（`reports/raw/C/pytest.txt`；wrapper 只遮蔽了一處，是測試 id 中的假 key）。


## 第 3 輪（commit `0e5830d`、`4feff3a`、`9162188`）

> 夜間模式：Codex 唯讀審閱證據，未親自執行。

### Codex 回覆（全文）

## 總結：通過

第 2 輪必修已修正；指定證據支持草稿中的實測主張，安全事件處理與完整套件紀錄也符合驗收條件。**我沒有親自執行任何東西，只閱讀檔案與 Git 歷史。**

## 逐條驗收

1. **第 2 輪必修：通過。** 草稿中標為 observed 的計數、TTL、HTTP 狀態、並發串流與 metrics 主張，都能在 `repro-output.txt` 找到相應記錄；部署內容標為設定背景、註明未實測；原始碼敘述有逐字摘錄可核對。
2. **草稿與腳本：通過。** 草稿包含重現步驟、影響範圍、版本資訊，並標明未送出。腳本只印遮罩 key，輸出也記錄兩把臨時 key 已透過 `/key/list` 確認刪除。
3. **維持現狀：通過。** `test_auth_rejection_does_not_skew_parallel_counter` 仍為 `xfail(strict=True)`；README 仍記錄限制，未見加入防護。
4. **安全事件：通過。** `4feff3a` 加入 `MaskedEnv`、pytest 輸出遮蔽及對應測試；`pytest.txt` 記錄追蹤檔密鑰掃描通過。安全事件記錄說明未改寫歷史，並明確將密碼輪換與 push 前清理歷史留待使用者決定。
5. **完整套件：通過。** `pytest.txt` 記錄 **154 passed、1 xfailed**，exit code 0。incident 記錄另記錄 spend log 曾中斷及後續恢復，沒有把該事件隱去。

## 剩餘問題

- **建議｜`reports/verification/C.md:67–70`**：安全事件已記錄需由使用者決定是否輪換兩組密碼、是否在 push 前清理分支歷史；決策尚未完成。這是待辦，不構成驗收不通過。
- 工作樹另有未提交變更與未追蹤檔案；本次僅核對指定範圍，未將其納入項目 C 的通過判定。

### 結論

**項目 C 驗證通過。**

剩下的建議是兩件需要使用者決定的事：是否輪換密碼、是否清理分支歷史。這兩件已列入 `reports/overnight-summary.md`。

Codex log 中有 5 處被遮蔽：遮蔽規則把原始碼裡 `sk-change-me` 之類的佔位字串也替換成 `sk-…末4碼` 的格式。這只影響 log 的顯示，log 裡沒有任何密鑰。
