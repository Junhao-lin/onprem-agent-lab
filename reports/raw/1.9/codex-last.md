## 總結：有條件通過

程式與 `pytest.txt` 支持大部分驗收項目，截圖也看得到各面板有資料、版面未見重疊，應用線條使用藍、橘固定色。不過，附錄 A 的數值與目前工作樹中的 PNG 不一致；Qdrant 清理結果也未驗證。另有密鑰遮蔽風險，建議修正後再視為完整通過。

## 逐條驗收結果

1. **登入與帳密保護：有條件通過。** 測試從 `.env` 取得帳密，透過登入表單提交；登入例外會以固定訊息取代 Playwright 錯誤細節，避免帳密出現在該錯誤中。[test_grafana.py:97](/D:/onprem-agent-lab/tests/e2e/test_grafana.py:97) 不過，`run_codex.py` 的遮蔽不完整，詳見下方。
2. **Kiosk 與截圖：通過。** 導向 kiosk URL，截圖寫至 `reports/raw/1.9/`。[test_grafana.py:108](/D:/onprem-agent-lab/tests/e2e/test_grafana.py:108)
3. **No data 檢查：部分通過。** 測試涵蓋「–」類 stat 空值與 `No data in range` 圖例文字，但全頁文字比對是精確匹配，可能漏掉其他同義或包有額外文字的空資料狀態。[test_grafana.py:41](/D:/onprem-agent-lab/tests/e2e/test_grafana.py:41)、[test_grafana.py:137](/D:/onprem-agent-lab/tests/e2e/test_grafana.py:137)
4. **自行產生流量與清理：有條件通過。** 流量由測試產生，且用 `finally` 刪除臨時 Qdrant collection；但未檢查 DELETE 回應，無法確認資源確實清除。[test_grafana.py:49](/D:/onprem-agent-lab/tests/e2e/test_grafana.py:49)、[test_grafana.py:83](/D:/onprem-agent-lab/tests/e2e/test_grafana.py:83)
5. **完整套件與 xfail：通過。** `pytest.txt` 記錄 143 passed、1 xfailed、exit code 0；該 xfail 為 strict，並附 LiteLLM 問題理由。
6. **截圖與附錄觀察：部分通過。** 我直接檢視了目前工作樹 PNG：面板有數值與圖例、未見重疊或截斷；應用曲線為藍、橘，429 為黃色，錯誤率為紅色。截圖仍有 Grafana 時間／刷新控制列。更重要的是，截圖顯示 Requests 47、Error rate 17.0%、p95 TTFT 488.75 ms，和附錄記載的 37、16.2%、492 ms 不一致；因此附錄數值觀察不能由這份 PNG 證實。
7. **1.9.md 僅追加附錄：通過。** Git 差異顯示既有內容未改，新增內容只在文件末尾附錄 A。

## 弱斷言與問題清單

- **必修｜密鑰遮蔽可能漏值** — [run_codex.py:38](/D:/onprem-agent-lab/scripts/overnight/run_codex.py:38)、[run_codex.py:67](/D:/onprem-agent-lab/scripts/overnight/run_codex.py:67)、[run_codex.py:84](/D:/onprem-agent-lab/scripts/overnight/run_codex.py:84)：只從 `.env` 擷取符合變數名稱且長度至少 6 的未解析原始值；引號、行尾註解或短值可能未被遮蔽。此外，Codex 直接以 `--output-last-message` 寫檔，遮蔽是在程序結束後才做，逾時或中斷可能留下未遮蔽內容。建議以正確解析後的所有秘密值遮蔽，並讓輸出先寫至記憶體／暫存，再遮蔽後落盤。
- **建議｜刪除失敗不會讓測試失敗** — [test_grafana.py:87](/D:/onprem-agent-lab/tests/e2e/test_grafana.py:87)：`finally` 有發送 DELETE，但不檢查回應狀態。建議驗證成功狀態，並在失敗時明確報告清理未完成。
- **建議｜截圖數值與附錄不符** — [1.9.md:119](/D:/onprem-agent-lab/reports/verification/1.9.md:119)：附錄觀察值與目前工作樹 PNG 不一致。請確認 PNG 是否在提交後被替換（工作樹顯示該檔已修改），並讓報告與欲驗證的截圖版本一致。
- **建議｜測試時序依賴抓取及並發狀態** — [test_dashboards.py:196](/D:/onprem-agent-lab/tests/platform/test_dashboards.py:196)、[test_dashboards.py:205](/D:/onprem-agent-lab/tests/platform/test_dashboards.py:205)：測試依賴 Prometheus 抓取觀察 counter 增長，且以持有並發槽位製造 429；抓取延遲、請求耗時或其他並發流量都可能影響結果。現有等待與重試有所緩解，但仍有環境時序敏感性。
- **建議｜幾何檢查未檢查頂端越界** — [test_grafana.py:166](/D:/onprem-agent-lab/tests/e2e/test_grafana.py:166)：檢查了左右與底部，但未要求 `y >= 0`。建議補上頂部邊界斷言。
- **弱斷言檢查結果：未發現所述空集合通過。** 面板計數及每個 JSON 面板標題都要求唯一匹配；stat 與時間序列斷言會對缺失元素觸發錯誤，不會因為空集合而成功。[test_grafana.py:131](/D:/onprem-agent-lab/tests/e2e/test_grafana.py:131)、[test_grafana.py:145](/D:/onprem-agent-lab/tests/e2e/test_grafana.py:145)

我沒有親自執行測試；以上結論來自閱讀程式碼、Git 歷史與測試輸出，並直接檢視目前工作樹中的 PNG。