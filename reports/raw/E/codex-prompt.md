你是獨立驗證者，以唯讀方式審閱本 repo（分支 overnight）的項目 E：1.11 README。不要修改檔案，不要執行 docker、pytest、腳本或網路請求；只閱讀檔案與 git 歷史。不要讀取 .env。

## 範圍
- `git show 0e6a8de`（README.md 全面改寫、tests/platform/test_readme.py）
- 對照用：docker-compose*.yml、.env.example、infra/litellm/*.yaml/*.toml、scripts/bootstrap_keys.py、loadtest/*.py、scripts/screenshot_dashboard.py、tests/、docs/benchmarks/2026-11-26-baseline.md、docs/upstream/litellm-parallel-counter.md、reports/raw/1.10/baseline-restart/summary.csv、reports/raw/incidents/spendlog-stall.txt、pyproject.toml
- 證據：reports/raw/E/pytest.txt（完整套件）、docs/images/dashboard.png（直接看圖）

## 驗收條件
README 必須包含且內容正確：
1. Quick start：前置需求、.env 設定、啟動、key 建立、驗證、測試；含「uv 不在 PATH 時用 python -m uv」的說明。每個指令與 repo 實際檔案、參數、profile、檔名一致（請逐一對照）。
2. 架構：元件、資料流、對外 port 與內網、並發預算，與 compose 與設定檔一致。
3. 測試方式：如何執行、各測試檔驗證什麼，與 tests/ 實際內容一致。
4. 第一版壓測結果：數字與 reports/raw/1.10/baseline-restart/summary.csv、基準報告一致；維運風險描述與基準報告一致。
5. 已知限制：與現有證據一致，沒有誇大或缺漏重要項目。
6. 截圖：嵌入 docs/images/dashboard.png，說明文字與圖一致。
7. 沒有任何密碼或 key 的值；pytest.txt 顯示完整套件通過。

## 請特別找出
- README 中與實際程式或設定不符的指令、檔名、數字、行為描述（例如「約 N 分鐘」、測試數量、預設值）。
- 新使用者照做會卡住的地方（Windows / Linux 差異、缺少的步驟）。
- test_readme.py 的弱斷言。

## 輸出要求
- 繁體中文、精簡：總結（通過/有條件通過/不通過）→ 逐條驗收 → 問題清單（檔案:行號、嚴重度 必修/建議、建議修法）。
- 不得輸出任何密碼、API key 或 .env 的值。
- 註明你沒有親自執行任何東西。
