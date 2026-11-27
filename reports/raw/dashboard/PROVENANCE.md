# docs/images/dashboard.png：資料來源（2026-11-27）

| | UTC | UTC+8（圖上時間軸） |
|---|---|---|
| `app_traffic.py --duration 600` 開始 | 07:22:08 | 15:22:08 |
| 截圖時間範圍（`--range 7m`） | 07:23:32–07:30:32 | 15:23:32–15:30:32 |
| `app_traffic.py` 結束 | 07:32:07 | 15:32:07 |

- 截圖範圍的起點比流量開始晚 84 秒。面板的 rate 視窗（`$__rate_interval`，約 1 分鐘）不會回看到流量開始之前。
- 範圍內沒有執行會連線 gateway 的測試或壓測：最後一次完整 pytest 在 07:05 左右結束，下一次在截圖之後才開始。流量期間只跑過不連線任何服務的離線測試，例如 test_readme、test_repo_hygiene 的空白與路徑檢查。
- `app-traffic.txt`：兩個應用各 150 輪，全部 HTTP 200。
- `screenshot.txt`：16 個面板。只有兩個 Qdrant 時間序列面板因 `--allow-idle-qdrant` 被豁免，其餘都通過「有資料」檢查。
- `window-traffic.txt`：以截圖時刻為終點、7 分鐘視窗查詢 Prometheus。
  - 只有 `onboarding-agent` 約 105 筆、`support-rag` 約 210 筆，合計與圖上的 Requests 315 一致；
  - 沒有失敗紀錄，也沒有 Qdrant REST 呼叫。
  - 查詢在截圖後約 2 秒執行，兩者的時間窗只差這 2 秒。
- 取代的舊圖（commit `fa6116e` 起）：10 分鐘範圍的左側含有一次完整 pytest 的尾段（p95 latency 最大 9.50 s、TTFT 488 ms），Qdrant 資料也來自測試。
