## 總結：不通過

第 1 輪兩項必修已修正，且新輸出直接支持「兩次 400 後正常請求回 429」。但草稿仍有多項標示為 **observed** 的主張無法在指定的 `repro-output.txt` 找到對應證據，未符合驗收條件 2。

## 逐條驗收

1. **第 1 輪必修：通過。** 草稿列出 `/v1/embeddings` 和 `/v1/chat/completions` 兩種 401 端點，與腳本及輸出一致。B 情境在新 key 上記錄兩次 400、計數升至 +2，接著一般請求回 429。
2. **Observed 主張與推論：不通過。** 計數、TTL、HTTP 狀態及三個串流均回 200 等主張可在輸出找到；上限外推也標為推論。但草稿其他標示為觀察的主張——例如錯誤未計入 Prometheus、400 的 metric 標籤，以及部署影響上限——不在 `repro-output.txt` 中。可能原因雖標成 hypothesis，該段的原始碼描述也不是這份輸出所能佐證。
3. **重現步驟、影響、版本、未送出標示：通過。** 草稿有兩個情境的步驟、影響說明、LiteLLM 等版本資訊，並清楚標示未送出。
4. **腳本安全與計數讀取：有條件通過。** 腳本只輸出遮罩 key；`TempKey` 在正常離開及建立失敗路徑都會嘗試刪除，並以 `/key/list` 查核；計數採穩定值輪詢，不依賴固定等待。不過輸出沒有記錄刪除查核結果，故無法由指定證據確認本次兩把 key 確已刪除。
5. **維持現狀：通過。** `pytest.txt` 記錄 `xfail(strict=True)` 測試仍為 xfail、152 passed；README 仍記錄限制。`d113a62` 未修改測試或 README，亦未見加入防護。
6. **完整套件：通過。** `pytest.txt` 結尾記錄 152 passed、1 xfailed。

## 剩餘問題

- **必修｜[litellm-parallel-counter.md](/D:/onprem-agent-lab/docs/upstream/litellm-parallel-counter.md:31)**：metrics、部署影響等觀察主張沒有 `repro-output.txt` 對應行。請補上驗收範圍允許的直接證據，或移除／改標為推論。
- **建議｜[repro_parallel_counter.py](/D:/onprem-agent-lab/docs/upstream/repro_parallel_counter.py:144)**：刪除後雖會查詢確認，但輸出未記錄查核結果。建議印出成功確認，讓本次清理可由輸出核對。

仍有必修項，因此判定不通過。**我沒有親自執行任何東西；只閱讀檔案與 Git 歷史。**