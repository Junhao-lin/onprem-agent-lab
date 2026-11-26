你是獨立驗證者，以唯讀方式審閱本 repo（分支 overnight）的項目 C：LiteLLM 並發計數 bug 的 issue 草稿。不要修改檔案，不要執行 docker、pytest、腳本或網路請求；只閱讀檔案與 git 歷史。

## 範圍
- `git show e2c7307`
- 檔案：docs/upstream/litellm-parallel-counter.md（issue 草稿）、docs/upstream/repro_parallel_counter.py（重現腳本）
- 相關既有證據：reports/verification/1.9.md「問題 1」的附帶發現、tests/platform/test_dashboards.py 中的 `test_auth_rejection_does_not_skew_parallel_counter`（xfail strict）、README.md「已知限制」
- 證據：reports/raw/C/repro-output.txt（重現腳本實際輸出）、reports/raw/C/pytest.txt（完整套件）

## 驗收條件
1. 草稿包含：重現步驟、影響範圍、版本資訊（LiteLLM 版本與 image digest、Redis、Python 等），且明確標示「草稿、未送出」。
2. 重現步驟與腳本一致，腳本輸出（repro-output.txt）支持草稿中的每一個主張（-1、+1、超出並發上限）。
3. 「可能原因」段落標示為推測，沒有把未驗證的內容寫成事實；引用的原始碼位置合理。
4. 維持現狀：xfail 測試與 README 記錄仍在，沒有加入任何防護或改變 gateway 行為。
5. 腳本與草稿不會洩漏完整 key（只印遮罩），臨時 key 會被刪除（含例外路徑）。
6. pytest.txt 顯示完整套件通過。

## 請特別找出
- 草稿中與證據不符或過度推論之處；上游維護者可能會質疑的地方（例如重現環境是否過度依賴本 repo）。
- 重現腳本的弱點（例如計數讀取時機、TTL 過期造成的誤判、臨時 key 殘留）。

## 輸出要求
- 繁體中文、精簡：總結（通過/有條件通過/不通過）→ 逐條驗收 → 問題清單（檔案:行號、嚴重度 必修/建議、建議修法）。
- 不得輸出任何密碼、API key 或 .env 的值。
- 註明你沒有親自執行任何東西。
