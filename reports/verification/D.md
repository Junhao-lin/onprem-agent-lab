# 項目 D 驗證報告：正式 key 流量與儀表板截圖

> 夜間模式：Codex 唯讀審閱證據，未親自執行。

- **範圍**：
  - `loadtest/app_traffic.py`
  - `scripts/screenshot_dashboard.py`
  - `docs/images/dashboard.png`
- **證據**：`reports/evidence/D/`，內含：
  - `app-traffic.txt`：流量執行結果
  - `screenshot.txt`：截圖輸出與資料來源說明
  - `dashboard.png`：截圖副本
  - `pytest.txt`：完整套件
  - `codex-*`：prompt 與回覆（log 已移除：Agent 原始對話紀錄含本機使用者資訊，不進版控）

## 我親自看截圖的觀察

- **16 個面板都有資料**，包括 p95 TTFT（49.90 ms）與 p95 time to first token（兩個應用約 50 ms）。
- **配色與排版**：Error rate 0.0% 以綠色顯示。兩個應用各自固定一種顏色，版面沒有重疊。
- **時間軸使用瀏覽器時區（UTC+8）**：00:33–00:38 就是 app_traffic 的流量，也就是 16:33–16:38 UTC。左邊 00:28–00:31 那段，是 00:26:55 開始、跑了 3 分 07 秒的那次完整 pytest 的尾巴（第 2 輪後更正：原本沒有指明是哪一次執行）。
- **Qdrant 面板的資料不是 app_traffic 產生的**。app_traffic 不會呼叫 Qdrant，因為 RAG 應用還沒做。時間範圍內唯一一次 Qdrant 活動在 00:30:15（Prometheus 查詢結果在 `qdrant-activity.txt`），對應 00:26:55 那次 pytest 中的 `test_qdrant` roundtrip。Collections 和 Vectors 顯示 0，是當下的真實值。

## 第 1 輪（commit `c77b4d5`）

### Codex 回覆（全文）

## 總結：有條件通過

流量報告、截圖輸出與套件結果支持多數驗收項目；但截圖的時間與報告時間對不上，且 Qdrant 面板的資料無法證明來自本次流量。另有測試斷言不足以驗證實際並發限制。

## 逐條驗收

1. **正式 key、限額、約 5 分鐘流量與錯誤狀況：有條件通過。**\
   `app-traffic.txt` 記錄執行 300 秒，兩個 app 各 75 回合，請求皆為 200，含串流請求及 TTFT。按 TOML 限額與預設 pacing 推算，RPM 在限制內；每個 app 的 worker 逐次呼叫請求，程式路徑也維持單一未完成回合。報告沒有 key 值，但它是工作目錄中的未追蹤檔案，不能由 `c77b4d5` 的提交歷史佐證。程式也沒有驗證 `--fraction` 為正數或不超過 1。

2. **Playwright kiosk 截圖：通過。**\
   腳本開啟 `?kiosk`，圖片沒有瀏覽器外框或 Grafana 導覽列；仍看得到 dashboard 上方的 App 與時間範圍控制項。`screenshot.txt` 記錄成功存檔。

3. **16 個面板有資料：有條件通過。**\
   我逐一檢視圖片：6 個總覽 stat、流量 2 個、延遲 2 個、token 2 個、Qdrant 4 個均有數值、圖線或數字圖例；包含 **p95 TTFT** 與 **p95 time to first token**。但部分面板只有零值或短暫資料，不能據此推定它們反映本次流量。特別是 Qdrant 流量、延遲圖只有短暫舊資料，Collections 與 Vectors 顯示 0。`app_traffic.py` 只呼叫 LiteLLM 的 chat 與 embeddings API，沒有直接呼叫 Qdrant；報告未說明這些 Qdrant 面板資料來源。另報告記錄截圖時間為 16:38 UTC，圖片時間軸約至 00:38，時間不一致，降低了資料與本次流量關聯的可信度。

4. **缺資料時不存檔及零值例外：有條件通過。**\
   腳本在有問題時不會把暫存截圖寫入目標路徑；報告也記錄第一次因錯誤面板全零而拒絕存檔。只對 `Failed requests / s by status` 豁免全零判定是合理且範圍明確的例外；它仍檢查圖例數值。限制是檢查主要依賴 Grafana DOM 結構和標題文字，且 stat 面板的 `0` 會被當成有資料；若目標路徑已有舊檔，失敗時舊檔也不會刪除，容易讓人誤認為本次成功產圖。

5. **不印出帳密或 key：通過。**\
   程式輸出不含帳密或 key；key 只用於 Authorization header，登入錯誤訊息也沒有輸出帳密。

6. **完整套件通過：通過（依報告）。**\
   `pytest.txt` 顯示 **155 passed、1 xfailed**，執行時間 301.09 秒。我沒有親自執行測試。

## 問題清單

- [reports/evidence/D/screenshot.txt](/D:/onprem-agent-lab/reports/evidence/D/screenshot.txt:1) — **必修**：報告的 UTC 截圖時間與圖片顯示時間軸不一致，需釐清時間區設定並補充 Qdrant 面板資料來源，否則無法確認所有面板資料都來自本次流量。
- [scripts/screenshot_dashboard.py](/D:/onprem-agent-lab/scripts/screenshot_dashboard.py:64) — **建議**：stat 檢查把 `0` 視為資料。對 Collections、Vectors 這類面板而言，零值可能代表空集合，而非證明近期流量；可加上與新鮮度或查詢時間相關的檢查。
- [scripts/screenshot_dashboard.py](/D:/onprem-agent-lab/scripts/screenshot_dashboard.py:102) — **建議**：失敗時不寫入新檔，但不處理目標路徑既有截圖；舊圖可能被誤當成此次產物。
- [loadtest/app_traffic.py](/D:/onprem-agent-lab/loadtest/app_traffic.py:145) — **建議**：未驗證 `--fraction` 範圍；不合法輸入可能讓 pacing 超出設定限額。
- [tests/platform/test_loadtest.py](/D:/onprem-agent-lab/tests/platform/test_loadtest.py:25) — **建議**：測試只檢查 TOML 並發限額至少為 2，沒有實際斷言請求同時在途數量不超限；目前「並發限制」驗證偏弱。

**我沒有親自執行任何東西**；僅閱讀檔案與 git 歷史，並查看指定圖片。

### 依第 1 輪意見所做的修正

| Codex 意見 | 處理 |
|---|---|
| 必修：截圖時間與 UTC 對不上；Qdrant 面板資料來源沒有說明 | 已查證本機時區是 UTC+8，儀表板設定使用瀏覽器時區，所以圖上的 00:38 就是 16:38 UTC，兩者一致。`screenshot.txt` 補上〈provenance〉一節，逐一說明每類面板的資料來源，包括 Qdrant 資料來自 pytest，以及 Collections/Vectors 為 0 的原因。README 的截圖說明也會寫明這點 |
| 建議：`app-traffic.txt` 沒有進版控 | Codex 這點有誤：`git ls-files` 顯示該檔已在 `c77b4d5` 中 |
| 建議：stat 面板把 0 視為有資料 | 不改。0 是有效的讀數，例如 In-flight、Collections。「不是空值」的檢查是為了抓 `–`，也就是查詢根本沒有結果的情況。是否要求 Qdrant 面板必須有新近資料，要等 RAG 應用完成後才有意義，列為待辦 |
| 建議：截圖失敗時，舊檔可能被誤認為這次的結果 | 失敗時會印出 `NOTE: … is an OLDER capture (<時間>), left unchanged` |
| 建議：沒有檢查 `--fraction` 的範圍 | 只接受 (0, 1] 的值，超出範圍時以結束碼 2 結束。新增一項測試 |
| 建議：沒有實際驗證同時進行的請求數 | 新增測試：用假的 gateway 讓兩個應用的迴圈高速跑 1.5 秒，記錄每把 key 同時進行中的請求數上限，斷言每把 key 都是 **1**，且所有請求都回 200 |

修正後的完整套件：157 passed, 1 xfailed（`reports/evidence/D/pytest.txt`）。


## 第 2 輪（commit `b378994`、`c8167a4`）

> 夜間模式：Codex 唯讀審閱證據，未親自執行。

### Codex 回覆（全文）

## 總結：不通過

**第 1 輪兩項必修都有修正，但 Qdrant 資料來源的時間證據仍不一致。** 圖片中的時間軸與 UTC+8 換算相符；然而，聲稱來自 pytest 的 Qdrant 資料點早於留存的完整套件執行時間，無法由指定證據支持。

## 逐條驗收

1. **第 1 輪必修：未完全通過。** `screenshot.txt` 說明瀏覽器時區為 UTC+8，圖上 00:33–00:38 對應 16:33–16:38 UTC，與流量時段一致；也說明了 LLM、Qdrant、Collections/Vectors 各面板的資料來源。但它將約 00:30 的 Qdrant 點歸因於 pytest，`pytest.txt` 記錄的完整套件則在 01:00:37 才開始。`c77b4d5` 時間為 00:53:05，進一步顯示所述 pytest 時段與圖上時間點對不上。

2. **正式 key 流量、限額、串流、錯誤及單一在途請求：通過（依證據）。** `app-traffic.txt` 記錄兩個 app 各 75 回合，所有請求均為 200，且包含串流請求與 TTFT。程式加入 `--fraction` 範圍檢查；新測試按 Authorization key 量測在途請求峰值，斷言每把 key 峰值為 1。證據未顯示帳密或 key 值。

3. **Kiosk 截圖及 16 個面板：通過。** 我直接檢視 `docs/images/dashboard.png`：畫面為 Grafana kiosk，沒有瀏覽器外框，16 個面板均有數值、曲線或圖例，包含 TTFT。Qdrant 的圖線有資料，但其 pytest 歸因受第 1 項時間矛盾影響。

4. **完整套件：通過（依留存結果）。** `pytest.txt` 顯示 157 passed、1 xfailed，退出碼 0。檔案內容未見密碼、API key 或 `.env` 值。

## 剩餘問題

- [reports/evidence/D/screenshot.txt](/D:/onprem-agent-lab/reports/evidence/D/screenshot.txt:15) — **必修**：Qdrant 資料點約在 00:30，但所列完整套件執行於 01:00:37 開始。需以可核對的執行證據說明 Qdrant 點的實際來源與時間。
- [reports/verification/D.md](/D:/onprem-agent-lab/reports/verification/D.md:20) — **建議**：目前報告沿用「00:28–00:31 是 pytest 尾段」的說法；應在 provenance 澄清後同步修正。此項本身非額外必修，但與上述必修相連。

**我沒有親自執行任何東西；只閱讀檔案與 Git 歷史，並直接查看圖片。**

### 依第 2 輪意見所做的修正

| Codex 意見 | 處理 |
|---|---|
| 必修：Qdrant 點約在 00:30，但我引用的 pytest 在 01:00:37 才開始 | Codex 說得對，我引用錯了執行紀錄。實際產生這些點的是 00:26:55 開始的那次完整套件，也就是項目 C 第 2 輪修正時跑的那次。補上兩項可核對的證據：<br>• **該次輸出的遮蔽版副本**（`pytest-C-run-0026-redacted.txt`）：原檔在 `0e5830d`，因洩漏密碼已被替換；遮蔽後掃描，確認不含任何密鑰<br>• **Prometheus 查出的 Qdrant 活動時間點**（`qdrant-activity.txt`）：範圍內只有 00:30:15 這一次，和 `test_qdrant` 在那次執行中的位置（第 139 行，約 83%）吻合<br>同一次執行中 e2e 測試出錯，所以 Qdrant 呼叫只來自 `test_qdrant` |
| 建議：同步修正報告 | 上方〈我親自看截圖的觀察〉已更正 |


## 第 3 輪（commit `a9da907`）

> 夜間模式：Codex 唯讀審閱證據，未親自執行。

### Codex 回覆（全文）

## 總結：有條件通過

第 2 輪必修的時間矛盾已用新增證據釐清：Qdrant 活動點、遮蔽版測試紀錄中的 `test_qdrant` 位置，以及截圖時間軸彼此吻合。尚有一處測試行號誤引，建議更正；依現有證據，這不構成不通過。

## 逐條驗收

1. **Qdrant 時間與來源：通過（依留存證據）。** 活動紀錄列出 00:30:15 UTC+8 的資料點；遮蔽版紀錄顯示測試於 00:26:55 開始、總長 3 分 07 秒，Qdrant roundtrip 約在執行進度 83%；截圖時間軸涵蓋該點。截圖文字所稱的測試「第 139 行」有誤，實際測試在第 142 行。
2. **面板資料來源說明：通過。** 截圖說明 LLM 面板來自正式 key 流量，Qdrant 面板來自測試，Collections 與 Vectors 為 0；與圖中資料相符。
3. **正式流量與截圖：通過（依留存證據）。** 流量紀錄為 300 秒、兩個 app 各 75 回合，含串流請求，列出的請求皆為 200。圖為 Grafana kiosk；我直接檢視了 16 個面板，包含 TTFT，均有數值、曲線或圖例。
4. **遮蔽與完整套件：通過（依留存證據）。** 遮蔽版輸出可見密碼欄位已遮蔽，未見密鑰值；`pytest.txt` 顯示 157 passed、1 xfailed，退出碼 0。該檔目前在工作目錄有未提交變更，結果依目前留存內容判讀。

## 剩餘問題

- `reports/evidence/D/screenshot.txt:23` — **建議**：把「line 139」改為實際測試所在的 line 142；測試名稱及 83% 進度在遮蔽版紀錄中可核對。此建議不構成不通過。

我沒有親自執行任何東西；僅閱讀檔案與 Git 歷史，並直接查看圖片。

### 處理（第 3 輪修正）

行號差異的原因：遮蔽版副本開頭多了 3 行說明，所以原始檔的第 139 行變成第 142 行。`screenshot.txt` 已改為同時標明兩邊的行號，e2e 出錯那兩行的行號也一併更正（15、1156）。

修正後的完整套件：157 passed, 1 xfailed。

**項目 D 結論：有條件通過**，剩下的唯一建議已修正。修正輪數已用完，所以沒有再送 Codex 確認。
