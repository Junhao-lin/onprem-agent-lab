## 總結：有條件通過

我沒有親自執行測試、壓測或 Docker；僅閱讀工作樹、git 歷史及既有輸出。基準報告的主要數字與退化 CSV 相符，測量定義大致正確；但臨時 key 清理不是「一定刪除」，退化報告有一處與逐請求數據不符，基準表也缺少可核對的原始輸出。

## 逐條驗收

1. **指標定義：大致通過。** [bench.py](/D:/onprem-agent-lab/loadtest/bench.py:139) 以首個非空 `delta.content` 計 TTFT；[percentile](/D:/onprem-agent-lab/loadtest/bench.py:70) 用線性插值；[summarize](/D:/onprem-agent-lab/loadtest/bench.py:177) 對成功請求計 percentile，分開統計 429 與其他錯誤，整體吞吐以成功請求輸出 token 總數除以該級 wall time。decode tok/s 用 `(output_tokens - 1) / (latency - TTFT)`。此速率依賴回傳 usage，屬近似值；零值 decode 也不納入 p50。

2. **key 與結果目錄：有條件通過。** 預設建立 `loadtest-*` key、輸出遮罩值，結果目錄有 git-ignore 規則。但刪除呼叫的失敗狀態未檢查，且呼叫發生在 `try/finally` 中，無法保證刪除成功，也未覆蓋建立 key 後、進入 `try` 前的失敗路徑。測試只驗證成功執行後 key 不在列表中，未驗證例外與刪除失敗情況。

3. **基準報告：有條件通過。** c=4 的 288.6 tok/s、c=8 的 280.4、c=16 的 288.4，配合 TTFT 上升，支持「本次測試在 c=4 後吞吐持平、排隊增加」；報告也說明樣本量與單次測量限制。但被聲稱為來源的 `loadtest/results/` 已忽略且不在提交中，無法獨立核對基準表格的原始數字。超載後風險表則可由 raw CSV 核對。

4. **維運風險與原始數據：有條件通過。** 維運風險是獨立段落，且多數數字符合 `summary.csv`；抽查的 cycle 1 超載、cycle 1 退化、cycle 2 退化前兩步 requests CSV 也支持其 TTFT 與 decode 敘述。不過 cycle 2 的 `after-2` 不是「完全退化」：requests.csv 有 **6/8** 筆約 39 tok/s，另 **2/8** 約 84 tok/s。報告又稱根因未查明，接著斷言問題在 Ollama/llama.cpp 排程，超出「重啟 Ollama 後恢復」所能證明的範圍。

5. **pytest 記錄：通過。** `pytest.txt` 記載 144 passed、1 xfailed、exit code 0；xfail 附 LiteLLM bug 理由。但 repo 的 pytest 設定沒有 `xfail_strict`，記錄中的 `strict:` 只是理由文字，並非 strict 設定。

## 問題清單

- **必修 — [bench.py](/D:/onprem-agent-lab/loadtest/bench.py:343)、[bench.py](/D:/onprem-agent-lab/loadtest/bench.py:369)：** 建立 key 後，輸出目錄建立在 `try/finally` 外；刪除 API 的結果也未檢查。把可能失敗的操作納入清理保護範圍，並確認刪除回應成功；刪除失敗時明確報錯或記錄 alias，避免誤稱一定刪除。
- **必修 — [2026-11-26-baseline.md](/D:/onprem-agent-lab/docs/benchmarks/2026-11-26-baseline.md:91)：** cycle 2 `after-2` 寫「fully degraded」，但原始請求數據是 6/8 退化、2/8 正常。修正敘述。
- **建議 — [2026-11-26-baseline.md](/D:/onprem-agent-lab/docs/benchmarks/2026-11-26-baseline.md:96)：** 「問題在 Ollama / llama.cpp scheduling」與「根因未調查」不一致。改為只描述重啟 Ollama 後恢復，根因尚未確認。
- **建議 — [2026-11-26-baseline.md](/D:/onprem-agent-lab/docs/benchmarks/2026-11-26-baseline.md:3)：** 基準表來源指向未納入版本控制的 `loadtest/results/`，因此無法獨立驗證。保存相應的原始 `summary.csv`／`summary.md`（或其他可追溯輸出）於報告證據目錄。
- **建議 — [test_loadtest.py](/D:/onprem-agent-lab/tests/platform/test_loadtest.py:67)：** 弱斷言包括：只檢查 token 數大於零、latency 不小於 TTFT，沒有驗證 decode 速率公式及多數 summary 指標；key 清理只測正常路徑，未涵蓋例外或刪除失敗。補上精確計算斷言與清理失敗情境。
- **建議 — [pyproject.toml](/D:/onprem-agent-lab/pyproject.toml:20)：** pytest 設定未啟用 `xfail_strict`。若驗收要求 strict，設定 `xfail_strict = true`，避免已修復的 xfail 靜默保留。