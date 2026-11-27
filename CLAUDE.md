# onprem-agent-lab：給 Claude 的專案規則

## 溝通

- 一律用繁體中文回覆。程式碼、指令、檔名、錯誤訊息原文維持英文。

## 常駐規則

- 每完成一個小步驟就 git commit。
- 密鑰一律放 `.env`，不進版控。
- 不得印出密碼或 key；需要提到 key 時只顯示 `sk-…末4碼`。
- 不得執行 `docker compose down -v`、`docker volume rm`、`docker system prune`，或任何刪除資料的指令（重啟單一服務可以）。
- 不得修改 git 設定。
- 需要使用者決定的事不要自己猜，記下來留給使用者。

## 專案慣例

- 測試一律用 Python（pytest）撰寫，不用 shell script。
- 原始輸出寫到本機的 `reports/raw/`，這個目錄不進版控。寫檔一律經 `scripts/rawlog.py` 遮罩：密鑰、`sk-` token，以及本機身分資訊（使用者目錄路徑、帳號名稱、email）。
- 報告引用的證據遮罩後放在 `reports/evidence/`。Agent 的原始對話紀錄只留在本機。
- 禁用字清單（例如公司名稱）放在本機的 `.local/forbidden-words.txt`，不進版控；repo 中不得出現清單上的字或本機身分資訊。`tests/platform/test_repo_hygiene.py` 會檢查。
