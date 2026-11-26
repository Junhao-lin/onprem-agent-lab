# 項目 D 驗證報告：正式 key 流量與儀表板截圖

> 夜間模式：Codex 唯讀審閱證據，未親自執行。

- **範圍**：
  - `loadtest/app_traffic.py`
  - `scripts/screenshot_dashboard.py`
  - `docs/images/dashboard.png`
- **證據**：`reports/raw/D/`，內含：
  - `app-traffic.txt`：流量執行結果
  - `screenshot.txt`：截圖輸出與資料來源說明
  - `dashboard.png`：截圖副本
  - `pytest.txt`：完整套件
  - `codex-*`：prompt、回覆與 log

## 我親自看截圖的觀察

- **16 個面板都有資料**，包括 p95 TTFT（49.90 ms）與 p95 time to first token（兩個應用約 50 ms）。
- **配色與排版**：Error rate 0.0% 以綠色顯示。兩個應用各自固定一種顏色，版面沒有重疊。
- **時間軸使用瀏覽器時區（UTC+8）**：00:33–00:38 就是 app_traffic 的流量，也就是 16:33–16:38 UTC。左邊 00:28–00:31 那段是前一次完整 pytest 的尾巴。
- **Qdrant 面板的資料不是 app_traffic 產生的**。app_traffic 不會呼叫 Qdrant，因為 RAG 應用還沒做。面板上的資料來自 pytest 對臨時 collection 的 upsert 與 query。Collections 和 Vectors 顯示 0，是當下的真實值。

## 第 1 輪（commit `c77b4d5`）

### Codex 回覆（全文）

## 總結：有條件通過

流量報告、截圖輸出與套件結果支持多數驗收項目；但截圖的時間與報告時間對不上，且 Qdrant 面板的資料無法證明來自本次流量。另有測試斷言不足以驗證實際並發限制。

## 逐條驗收

1. **正式 key、限額、約 5 分鐘流量與錯誤狀況：有條件通過。**  
   `app-traffic.txt` 記錄執行 300 秒，兩個 app 各 75 回合，請求皆為 200，含串流請求及 TTFT。按 TOML 限額與預設 pacing 推算，RPM 在限制內；每個 app 的 worker 逐次呼叫請求，程式路徑也維持單一未完成回合。報告沒有 key 值，但它是工作目錄中的未追蹤檔案，不能由 `c77b4d5` 的提交歷史佐證。程式也沒有驗證 `--fraction` 為正數或不超過 1。

2. **Playwright kiosk 截圖：通過。**  
   腳本開啟 `?kiosk`，圖片沒有瀏覽器外框或 Grafana 導覽列；仍看得到 dashboard 上方的 App 與時間範圍控制項。`screenshot.txt` 記錄成功存檔。

3. **16 個面板有資料：有條件通過。**  
   我逐一檢視圖片：6 個總覽 stat、流量 2 個、延遲 2 個、token 2 個、Qdrant 4 個均有數值、圖線或數字圖例；包含 **p95 TTFT** 與 **p95 time to first token**。但部分面板只有零值或短暫資料，不能據此推定它們反映本次流量。特別是 Qdrant 流量、延遲圖只有短暫舊資料，Collections 與 Vectors 顯示 0。`app_traffic.py` 只呼叫 LiteLLM 的 chat 與 embeddings API，沒有直接呼叫 Qdrant；報告未說明這些 Qdrant 面板資料來源。另報告記錄截圖時間為 16:38 UTC，圖片時間軸約至 00:38，時間不一致，降低了資料與本次流量關聯的可信度。

4. **缺資料時不存檔及零值例外：有條件通過。**  
   腳本在有問題時不會把暫存截圖寫入目標路徑；報告也記錄第一次因錯誤面板全零而拒絕存檔。只對 `Failed requests / s by status` 豁免全零判定是合理且範圍明確的例外；它仍檢查圖例數值。限制是檢查主要依賴 Grafana DOM 結構和標題文字，且 stat 面板的 `0` 會被當成有資料；若目標路徑已有舊檔，失敗時舊檔也不會刪除，容易讓人誤認為本次成功產圖。

5. **不印出帳密或 key：通過。**  
   程式輸出不含帳密或 key；key 只用於 Authorization header，登入錯誤訊息也沒有輸出帳密。

6. **完整套件通過：通過（依報告）。**  
   `pytest.txt` 顯示 **155 passed、1 xfailed**，執行時間 301.09 秒。我沒有親自執行測試。

## 問題清單

- [reports/raw/D/screenshot.txt](/D:/onprem-agent-lab/reports/raw/D/screenshot.txt:1) — **必修**：報告的 UTC 截圖時間與圖片顯示時間軸不一致，需釐清時間區設定並補充 Qdrant 面板資料來源，否則無法確認所有面板資料都來自本次流量。
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
