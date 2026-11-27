## 總結：有條件通過

README 的架構、服務埠、key 限額、基準數字與已知限制大致符合 repo 證據；`reports/raw/E/pytest.txt` 記錄完整套件 **162 passed、1 xfailed，5:02**。截圖本身與圖說大致相符。

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