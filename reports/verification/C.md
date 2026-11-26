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
