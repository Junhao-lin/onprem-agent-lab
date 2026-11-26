你是獨立驗證者，以唯讀方式審閱本 repo（分支 overnight）的項目 D：用正式 key 跑一般流量後，以 Playwright kiosk 模式截圖存成 docs/images/dashboard.png。不要修改檔案，不要執行 docker、pytest、腳本或網路請求；只閱讀檔案與 git 歷史。

## 範圍
- `git show c77b4d5`
- 檔案：loadtest/app_traffic.py、scripts/screenshot_dashboard.py、tests/platform/test_loadtest.py（test_app_traffic_stays_within_key_limits）、infra/litellm/virtual-keys.toml
- 證據：reports/raw/D/app-traffic.txt（流量執行結果）、reports/raw/D/screenshot.txt（截圖腳本輸出）、docs/images/dashboard.png（請直接看圖）、reports/raw/D/pytest.txt（完整套件）

## 驗收條件
1. 流量使用 support-rag 與 onboarding-agent 的正式 key，在各自限額內（rpm、並發）跑約 5 分鐘，包含串流請求；結果沒有 429 或其他錯誤。
2. 截圖用 Playwright kiosk 模式，只有 Grafana 畫面（沒有瀏覽器外框、Grafana 導覽列）。
3. 所有面板（含 p95 TTFT 與 p95 time to first token）都有資料；請看圖逐一確認 16 個面板。
4. 截圖腳本在面板缺資料時不會存檔；對錯誤面板「全為 0 視為有資料」的例外是否合理、是否過寬。
5. 腳本不印出帳密或 key。
6. pytest.txt 顯示完整套件通過。

## 請特別找出
- 截圖中的資料是否確實來自這次流量（時間範圍、Qdrant 面板資料的來源），以及報告中是否誠實說明。
- 弱斷言或過度寬鬆的檢查。

## 輸出要求
- 繁體中文、精簡：總結（通過/有條件通過/不通過）→ 逐條驗收 → 問題清單（檔案:行號、嚴重度 必修/建議）。
- 不得輸出任何密碼、API key 或 .env 的值。
- 註明你沒有親自執行任何東西。
