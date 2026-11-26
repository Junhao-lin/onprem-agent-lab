你是獨立驗證者，以唯讀方式審閱本 repo（分支 overnight）的 1.10「壓測工具與基準報告」。不要修改任何檔案，不要執行 docker、pytest、壓測或網路請求；只閱讀檔案與 git 歷史。

## 範圍
- 1.10 原始工作：`git show 935aaa2 3805a70 e25cac1`（bench.py、測試、基準報告、README 壓測段落）
- 夜間補充：`git show 1397bfc`（把「超載後吞吐持續退化、需重啟才恢復」提升為獨立的維運風險段落，新增 loadtest/repro_degradation.py）
- 主要檔案：loadtest/bench.py、loadtest/repro_degradation.py、loadtest/prompts.jsonl、tests/platform/test_loadtest.py、docs/benchmarks/2026-11-26-baseline.md、README.md 的「壓測」段落、tests/platform/test_dashboards.py 與 infra/grafana/build_dashboards.py 中排除 loadtest-* 的改動
- 證據：reports/raw/1.10/pytest.txt（完整套件輸出）、reports/raw/1.10/degradation/（summary.md、summary.csv、各步驟 requests.csv、environment.json、log）

## 驗收條件
1. bench.py 量測 TTFT、總延遲、每請求 decode tok/s、整體吞吐、p50/p95、429 與其他錯誤分開計數，定義正確（看程式碼確認計算方式，例如 TTFT 是否為第一個 content token、percentile 算法、吞吐的分母）。
2. 預設使用臨時無限額 key（loadtest-*），結束時一定刪除（含例外路徑）；輸出只有遮罩後的 key（sk-…末4碼）；結果目錄不進版控。
3. 基準報告的表格數字與其聲稱的來源一致；結論（c=4 飽和、之後只增加排隊）有數據支持；限制與方法說明誠實。
4. 「維運風險」段落是獨立段落，附退化前後的實測數字，且數字與 reports/raw/1.10/degradation/ 下的原始檔一致（請抽查 summary.csv 與至少兩個步驟的 requests.csv）；對原因的描述沒有超出證據。
5. pytest.txt 顯示完整套件通過（xfail 須 strict 且有理由）。

## 請特別找出
- 弱斷言：test_loadtest.py 中即使 bench 算錯或沒刪 key 也會通過的檢查。
- 報告中與原始數據不符、或過度推論的敘述。
- 任何可能洩漏完整 key 的輸出路徑。

## 輸出要求
- 繁體中文、精簡：總結（通過/有條件通過/不通過）→ 逐條驗收 → 問題清單（檔案:行號、嚴重度 必修/建議、建議修法）。
- 不得輸出任何密碼、API key 或 .env 的值。
- 註明你沒有親自執行測試或壓測。
