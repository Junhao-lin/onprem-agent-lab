# 看儀表板與跑測試時的注意事項

以下是 Prometheus／Grafana 與 LiteLLM 指標本身的特性，不是 bug。讀數看起來奇怪時，可以先對照這裡。

## 儀表板讀數

- **新序列的第一個樣本看不到**：Prometheus 的 `rate()`／`increase()` 算不到新序列的第一個樣本。某個應用第一次出現某種流量時（例如第一次串流），對應的面板要到下一次抓取後才有資料。
- **In-flight 可能短暫顯示 1**：`In-flight now` 已經扣掉 Prometheus 抓取 `/metrics` 的那個請求。但如果剛好有健康檢查同時進行，仍可能短暫顯示 1。
- **Qdrant 閒置時沒有延遲資料**：Qdrant 只對 points 類端點記錄指標，所以閒置時「Qdrant p95 REST latency」面板沒有資料。
- **p95 曲線有斷點**：流量是一陣一陣的時候，兩次請求之間沒有資料，`histogram_quantile` 算出 NaN，所以曲線會中斷。

## 測試

- **重啟 LiteLLM 後約 15 分鐘內，儀表板相關測試可能誤判**：重啟後，Prometheus 中的 counter 會歸零。接下來約 15 分鐘內，測試輔助函式 `instant()` 會取到舊序列的值，所以 dashboard 與 e2e 測試可能失敗。舊序列離開查詢的時間範圍後就會恢復。
