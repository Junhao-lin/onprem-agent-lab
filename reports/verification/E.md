# 項目 E 驗證報告：1.11 README

> 夜間模式：Codex 唯讀審閱證據，未親自執行。

- **範圍**：`README.md` 全面改寫，以及新增的 `tests/platform/test_readme.py`。
- **證據**：`reports/evidence/E/`，包含 `pytest.txt` 與 Codex 的 prompt 和回覆（log 已移除：Agent 原始對話紀錄含本機使用者資訊，不進版控）。
- **Quick Start 在運行中的平台上實測過的部分**：
  - `docker compose ... config -q`；
  - `python scripts/bootstrap_keys.py`；
  - bash 的 curl 範例；
  - 修正後也實測了 PowerShell 的 `Invoke-RestMethod` 範例。
  - **沒有從零開始重建平台**：那需要 `down -v` 刪除資料，而夜間規則禁止這麼做。

## 第 1 輪（commit `0e6a8de`）

### Codex 回覆（全文）

## 總結：有條件通過

README 的架構、服務埠、key 限額、基準數字與已知限制大致符合 repo 證據；`reports/evidence/E/pytest.txt` 記錄完整套件 **162 passed、1 xfailed，5:02**。截圖本身與圖說大致相符。

Quick Start 的 Windows 驗證步驟無法照抄執行，且 README 含有遮罩 key 範例，不符合「不含任何 key 值」的驗收要求。修正這兩點後較適合通過。

## 逐條驗收

1. **Quick Start：部分不通過。** 前置需求、`.env`、Compose profile、key 建立和測試命令大致對得上 repo；`python -m uv` 說明也有列出。Linux/bash 的 curl 範例可用，但 Windows 說明只提 `curl.exe`，命令仍使用 bash 的 `. ./.env`、`set -a` 和 `$SUPPORT_RAG_LLM_KEY`，PowerShell 沒有可照做的等效步驟。
2. **架構：通過，有一處描述宜收斂。** 服務、內網 `oal-backend`、loopback 對外埠和 2+2 並發預算符合 compose 與 TOML。README 稱「一個應用無法佔滿 GPU」說得過滿：設定限制的是並發請求數，不是 GPU 資源；已知計數漂移也可能暫時放寬限制。
3. **測試方式：有條件通過。** 測試檔案名稱與大部分說明吻合。`pytest -m "not llm"` 會一併跳過標記為 `llm` 的 Grafana e2e 測試；README 只說跳過呼叫模型的測試，未說明這個影響。`test_monitoring.py` 的說明也省略了資料來源 provision／健康檢查等驗證項目。
4. **第一版壓測：通過。** README 表格數字與 `summary.csv`、基準報告一致；超載後 c=2 吞吐退化與重啟恢復的描述有基準報告支持，並保留了測試條件限制。
5. **已知限制：大致通過。** 已涵蓋未驗證的 `/metrics/`、401/400 指標行為、並發計數漂移、spend log 漏記、access log 中的完整 key、Ollama 退化及監控限制。Ollama 退化的基準資料包含局部發生情況，README 應避免讓讀者理解成每次超載都必然、立即發生。
6. **截圖：通過。** README 有嵌入 `docs/images/dashboard.png`。我直接檢視圖片：時間範圍是最近 10 分鐘、Grafana 深色儀表板，LLM 面板有兩個應用流量，錯誤率為零；Qdrant 有請求曲線但 collections/vectors 為零，與圖說及來源紀錄相符。
7. **密鑰與 pytest 證據：有條件通過。** 完整套件通過證據符合要求；但 README 安全段落中的 `sk-…NFWw` 是部分 key 值，建議移除或改為純佔位符。

## 問題清單

- [README.md:134](/D:/onprem-agent-lab/README.md:134) — **必修**：Windows 驗證範例仍是 bash 語法，無法在 PowerShell 照做。補上使用 PowerShell 讀取 `.env` 變數並呼叫 `curl.exe` 的完整命令，或明確提供 Git Bash 步驟。
- [README.md:316](/D:/onprem-agent-lab/README.md:316) — **必修**：含有遮罩 key 的具體尾碼。改成 `sk-…<末4碼>` 等不含實際尾碼的佔位文字。
- [README.md:75](/D:/onprem-agent-lab/README.md:75) — **建議**：「無法佔滿 GPU」是對並發上限的過度推論。改成「單一 key 的並發請求上限為 2」等可由設定直接支持的描述。
- [README.md:255](/D:/onprem-agent-lab/README.md:255) — **建議**：補充 `-m "not llm"` 也會跳過標記為 `llm` 的 Grafana e2e 測試，避免讀者誤以為只略過模型呼叫。
- [tests/platform/test_readme.py:11](/D:/onprem-agent-lab/tests/platform/test_readme.py:11) — **建議**：連結斷言只檢查至少 10 個 Markdown 連結及其目標存在，無法驗證 Quick Start 指令、錨點或描述正確。
- [tests/platform/test_readme.py:19](/D:/onprem-agent-lab/tests/platform/test_readme.py:19) — **建議**：截圖斷言只查找 `![` 和路徑字串，未確認它們構成同一個嵌入式圖片連結，也未驗證圖說是否符合圖片內容。
- [tests/platform/test_readme.py:26](/D:/onprem-agent-lab/tests/platform/test_readme.py:26) — **建議**：基準斷言只比對五個表格欄位的指定精度；沒有檢查基準條件、文字結論或營運風險是否與報告一致。
- [tests/platform/test_readme.py:37](/D:/onprem-agent-lab/tests/platform/test_readme.py:37) — **建議**：Quick Start 測試只確認兩段文字出現，不能偵測 Windows shell 命令無法執行等實質問題。

本次只閱讀檔案、git 歷史與現有圖片／報告，**沒有親自執行任何命令、測試、腳本或容器操作，也沒有讀取 `.env`**。

### 依第 1 輪意見所做的修正

| Codex 意見 | 處理 |
|---|---|
| 必修：Windows 驗證範例仍是 bash 語法 | 分成兩段：<br>• **bash**（Linux、macOS、Git Bash）<br>• **PowerShell**：讀取 `.env`，再用 `Invoke-RestMethod` 呼叫<br>兩段都在本機實測：回 `chat-default`、10 tokens。另外說明範例提示詞刻意只用 ASCII 的原因（Git Bash 會把命令列中的中文轉碼） |
| 必修：安全性段落的 `sk-…NFWw` 是真實 key 的末 4 碼 | 改成虛構的 `sk-…AbCd`。新增測試：README 中任何 `sk-…XXXX` 都不得是 `.env` 中真實 key 的末 4 碼，也不得出現任何密鑰值 |
| 建議：「無法佔滿 GPU」說得過滿 | 改成「單一 key 同時最多 2 個請求，另一個應用至少保有 2 個槽位；這是請求數上限，不是 GPU 資源配額，計數漂移時可能暫時失準」 |
| 建議：`-m "not llm"` 也會跳過 e2e | 已在註解中說明 |
| 建議：`test_monitoring.py` 的說明漏了項目 | 補上「資料來源已 provision 且健康」 |
| 建議：退化不一定每次都立即發生 | 改成「兩輪實測中…；退化不一定立即出現，有一輪剛超載時只有部分請求變慢」 |
| 建議：`test_readme.py` 斷言偏弱 | 加強為 8 項：<br>• 圖片必須以 `![…](docs/images/dashboard.png)` 嵌入<br>• README 中提到的所有 script 路徑、`-f` compose 檔、`--profile`、pytest 路徑與 marker 都必須真實存在<br>• Quick Start 有 1–5 步、`python -m uv` 的替代寫法，以及 bash 與 PowerShell 兩種範例<br>• 不得含真實 key 的材料<br>• 基準表的數值與條件（max_tokens、模型）必須和原始資料一致<br>• 維運風險的百分比與 tok/s 範圍，必須和退化原始資料逐輪計算的結果一致<br>• key 限額表必須和 toml 一致<br>突變檢查：把 profile 打錯、把 script 名稱打錯，都會讓測試失敗。Codex 提到的「圖說是否符合圖片內容」無法自動化，由人工看圖確認（見項目 D） |


## 第 2 輪（commit `dc472d5`）

> 夜間模式：Codex 唯讀審閱證據，未親自執行。

### Codex 回覆（全文）

## 總結：不通過

第 1 輪兩項必修已修正；README 的內容與引用資料大致吻合，pytest 證據也記錄完整套件通過。不過，`test_readme.py` 只檢查 marker「有宣告」，錯用另一個已宣告的 marker 仍可能通過，未符合第 3 項驗收。

## 逐條驗收

1. **通過**：`dc472d5` 加入 PowerShell `.env` 載入與 `Invoke-RestMethod` 範例；README 的遮罩示例使用虛構尾碼，未見真實 key 尾碼。
2. **通過**：README 包含 Quick Start（含 `python -m uv`）、架構、測試方式、第一版壓測、已知限制及截圖。compose、基準資料、`reports/evidence/1.10/` 與截圖內容相符。PowerShell 範例符合 `.env.example` 的格式；我未親自執行驗證。
3. **未通過**：檔名與 profile 有存在性檢查，基準數字也有對照原始資料；但 marker 斷言僅要求 README 中的 marker 存在於 `pyproject.toml`。若把 `not llm` 改成其他已宣告 marker，檢查仍可能通過。
4. **通過**：`reports/evidence/E/pytest.txt` 記錄 **165 passed、1 xfailed**。

## 剩餘問題

- [tests/platform/test_readme.py:45](/D:/onprem-agent-lab/tests/platform/test_readme.py:45) — **必修**：marker 斷言需驗證預期的 `llm` marker，或驗證命令語意，才能抓出錯用其他有效 marker 的情況。

我沒有親自執行任何東西，也沒有讀取 `.env`。

### 依第 2 輪意見所做的修正

| Codex 意見 | 處理 |
|---|---|
| 必修：marker 斷言只檢查「有宣告」，換成另一個已宣告的 marker 仍會通過 | 斷言改為：<br>• README 指令中的 marker 必須**正好是** `llm`<br>• 該行註解必須寫「跳過會呼叫模型的測試」<br>• `pyproject.toml` 中 `llm` marker 的說明必須包含「calls a model」<br>• `tests/e2e/test_grafana.py` 必須真的標了 `llm`<br>**突變檢查**：把 `not llm` 改成 `not browser`（這也是已宣告的 marker），測試失敗 |


## 第 3 輪（commit `218d258`）

> 夜間模式：Codex 唯讀審閱證據，未親自執行。

### Codex 回覆（全文）

## 總結：通過

第 2 輪必修已修正；指定檔案與證據符合驗收條件，沒有剩餘必修問題。

## 逐條驗收

1. **Marker 回歸檢查：通過。** `test_readme.py` 現在要求 README 的 `-m "not …"` 使用 `llm`，並核對其說明、`pyproject.toml` 中 `llm` 的定義及 Grafana e2e 的標記。因此改成已宣告的 `browser` 會觸發測試失敗。
2. **README 內容與 repo 一致：通過。** README 包含 Quick Start（含 `python -m uv`）、架構、測試方式、第一版壓測結果、已知限制與截圖；安全段落使用遮罩示例，未見真實 key 材料。
3. **完整套件證據：通過。** `reports/evidence/E/pytest.txt` 記錄 `165 passed, 1 xfailed`，退出碼為 0。

## 剩餘問題

- 無必修或建議項。

我沒有親自執行測試、腳本、Docker 或網路請求，也沒有讀取 `.env`；僅閱讀指定檔案與 Git 歷史。

### 結論

**項目 E（1.11 README）驗證通過。** 修正後的完整套件：165 passed, 1 xfailed。
