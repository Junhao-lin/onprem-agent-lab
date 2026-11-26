你是獨立驗證者，以唯讀方式審閱本 repo（D:\onprem-agent-lab，分支 overnight）中 1.9 的補驗證。不要修改任何檔案，不要執行會改變狀態的指令（不要跑 docker、pytest 或網路請求）；只閱讀檔案與 git 歷史。

## 範圍
- commit 範圍：`git diff e25cac1..30cee1f`（請用 `git log --oneline e25cac1..30cee1f` 與 `git diff e25cac1..30cee1f` 查看）
- 主要檔案：tests/e2e/test_grafana.py、pyproject.toml（playwright 依賴與 browser marker）、reports/verification/1.9.md 的「附錄 A」、scripts/overnight/*.py
- 證據：reports/raw/1.9/ 下的 pytest.txt（完整測試輸出）與 platform-overview-kiosk.png（儀表板截圖，請直接查看圖片）
- 參考：tests/platform/test_dashboards.py、tests/platform/conftest.py、infra/grafana/dashboards/platform-overview.json

## 驗收條件
1. tests/e2e/test_grafana.py 從 .env 讀 Grafana 帳密並透過登入表單登入，任何情況下不印出帳密（包括失敗時的錯誤訊息）。
2. 以 kiosk 模式開啟 platform-overview，截圖存到 reports/raw/1.9/。
3. 檢查沒有任何面板顯示 No data（包含 stat 的「–」與圖例的「No data in range」等同義形式）。
4. 測試自行產生需要的流量，不依賴先前測試的狀態；臨時資源（Qdrant collection）有清除。
5. pytest.txt 顯示完整套件通過（xfail 須為 strict 且有理由）。
6. 截圖本身：所有面板有資料、排版無重疊、應用配色固定（support-rag 藍、onboarding-agent 橘）、狀態色只用在錯誤/狀態。請親自看 png，比對附錄 A 的觀察是否屬實。
7. 1.9.md 原有內容未被修改，只在後面追加附錄。

## 請特別找出
- 弱斷言：會在面板其實沒資料、排版錯誤或登入失敗時仍然通過的檢查；選擇器若找不到元素是否會「空集合通過」。
- 測試之間的隱性依賴或不穩定因素（時間窗、Prometheus 抓取間隔、並發 429 的時序）。
- scripts/overnight/run_codex.py 的密鑰遮蔽是否可靠。

## 輸出要求
- 用繁體中文，精簡。格式：總結（通過/有條件通過/不通過）→ 逐條驗收結果 → 弱斷言與問題清單（每項附檔案:行號與建議修法，標明嚴重度：必修/建議）。
- 不得輸出任何密碼、API key 或 .env 的值；若需要提及，只寫變數名稱。
- 註明你沒有親自執行測試，結論來自閱讀程式碼與證據。
