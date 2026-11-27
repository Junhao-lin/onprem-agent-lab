# README 儀表板截圖：資料來源與重拍方式

[`docs/images/dashboard.png`](images/dashboard.png) 是 README 摘要中的截圖。

## 這張圖的資料來源

- **時間範圍**：2026-11-27 15:23:32–15:30:32（UTC+8），共 7 分鐘。時間軸使用瀏覽器時區（UTC+8）。
- **流量來源**：只有 `loadtest/app_traffic.py` 用兩把正式 key（`support-rag`、`onboarding-agent`）送出的一般流量。
  - 速率在各自限額內，150 + 150 輪全部回 200。
  - 這段流量從 15:22:08 起跑 10 分鐘，截圖範圍完全落在其中。
- **範圍內沒有測試、壓測或 master key 的流量**，也沒有失敗的請求。依據是截圖當下對 Prometheus 的查詢結果。所以錯誤率是 0.0%，p95 延遲反映一般 chat 回應的長度。
- **Qdrant 面板沒有資料**：RAG 應用尚未實作，沒有應用呼叫 Qdrant。Collections／Vectors 為 0 是實際值。
- 證據在 [`reports/evidence/dashboard/`](../reports/evidence/dashboard/)，包括流量輸出、截圖輸出，以及時間窗內的流量查詢。

## 重拍步驟

```bash
python loadtest/app_traffic.py --duration 600                  # 正式 key 的一般流量；期間不要跑測試或壓測
# 約 8 分鐘後（另開一個終端機）截圖，截圖範圍要完全落在流量期間：
python -m uv run python scripts/screenshot_dashboard.py --range 7m --allow-idle-qdrant
python scripts/dashboard_window_traffic.py --range 7m          # 確認範圍內只有正式 key，而且沒有失敗
```

- `screenshot_dashboard.py` 用 Playwright 的 kiosk 模式截圖。只要有任何面板沒有資料，就不會寫入 `docs/images/dashboard.png`。
- `--allow-idle-qdrant` 只豁免 Qdrant 面板，並會列出被豁免的面板名稱。
- `dashboard_window_traffic.py` 會查詢 Prometheus。範圍內若有正式 key 以外的流量、任何失敗或 Qdrant 呼叫，就以結束碼 1 回報。
