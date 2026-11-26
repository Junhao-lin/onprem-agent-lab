# 夜間模式總結

分支：`overnight`，從 `main` 的 `e25cac1` 建立。依規則沒有合併回 main，也沒有 push。

## 起點

```
$ git status
On branch main
nothing to commit, working tree clean

$ git log --oneline -15
e25cac1 docs: publish first gateway benchmark baseline with methodology notes
3805a70 test(loadtest): unit + end-to-end bench tests; hide loadtest-* keys in dashboard
935aaa2 feat(loadtest): add streaming gateway benchmark (TTFT, tok/s, p50/p95)
e7f9df1 docs: add 1.9 verification report
4fdc63b docs(readme): dashboard reload on Windows, LiteLLM metering/limiter limitations
08e2bdb test(platform): verify failure, TTFT and in-flight panels; pin LiteLLM limiter bug
6d66a03 fix(monitoring): in-flight excludes the scrape itself; document unmetered 401s; add --reload
804717c test(platform): cover dashboard provisioning, queries and design rules
8d01033 feat(monitoring): add platform overview dashboard as code
301b00b docs(readme): note unauthenticated /metrics must be blocked at the proxy
e65918b test(platform): poll for parallel slot release instead of fixed sleep
db0bc6f docs: add 1.8 verification report and 1.7 re-verification
2903b31 test(platform): cover monitoring stack
702e807 feat(monitoring): add Prometheus and Grafana with provisioning
ac86f58 feat(gateway): expose Prometheus metrics from LiteLLM
```

起點時，platform 與 monitoring 兩個 profile 的 7 個服務都是 healthy。

## 工具與做法

- **Codex CLI** 0.172.0 不在 PATH 上，`scripts/overnight/run_codex.py` 會自動找到 `~/.codex/packages/standalone/current/bin/codex.exe`。指令：`codex exec --sandbox read-only -c model_reasoning_effort="medium"`。
  - 輸出以 UTF-8 存檔，逾時 15 分鐘。
  - 寫入 repo 前會遮蔽 `.env` 中的所有秘密值，`sk-` token 則改成 `sk-…末4碼`。
- **pytest**：`scripts/overnight/run_pytest.py <項目>` 以 Python 寫出 UTF-8 的 `reports/raw/<項目>/pytest.txt`。

## 各項進度

| 項目 | 狀態 | Codex 最終判定 | 主要 commit |
|---|---|---|---|
| A. 1.9 補驗證（Playwright） | 完成 | 有條件通過，剩 1 項低嚴重度問題（修正已達 3 輪上限） | `ecdf601` `30cee1f` `ee96c5d` `5cfc7ad` `3fceecd` `ff82b8f` `b9c024d` |
| B. 1.10 補驗證 + 維運風險段落 | 完成 | **通過**（第 2 輪） | `1397bfc` `2fa201e` `138fbce` `d3c3da0` |
| C. LiteLLM issue 草稿 | 未開始 | | |
| D. 正式流量 + 截圖 | 未開始 | | |
| E. 1.11 README | 未開始 | | |

### A. 1.9 補驗證

- **`tests/e2e/test_grafana.py`**（22 項）：
  - 從 `.env` 讀帳密，透過登入表單登入，帳密不會出現在任何輸出中；
  - 以 kiosk 模式開啟 platform-overview，截圖存為 `reports/raw/1.9/platform-overview-kiosk.png`；
  - 測試會先自行產生兩個應用的流量、429 與 Qdrant 呼叫。
- **斷言**：
  - 頁面上沒有 No data 類文字；
  - stat 面板不是空值；
  - 時間序列圖例每一列都有數值，且至少一條序列的 Max > 0；
  - 沒有面板錯誤；
  - 面板之間不重疊，也沒有超出視窗。
- **檢查過程的發現**：
  - Qdrant 只對 points 類端點記錄指標，所以閒置時「Qdrant p95 REST latency」面板本來就沒有資料。
  - Failed 面板中的 `None` 序列，來自 1.9 調查時我刻意送出的格式錯誤請求。LiteLLM 把這類 400 的 `exception_status` 記成 `None`。
- **截圖觀察**：寫在 `reports/verification/1.9.md` 附錄 A。
- **Codex**：
  - 共審閱 4 次：3 輪「意見 → 修正」，再加 1 次最終確認。全文在附錄 B 到 E。
  - 必修項目（密鑰遮蔽）已修正。
- **完整套件**：143 passed, 1 xfailed（`reports/raw/1.9/pytest.txt`）。
- **剩下的問題**（低嚴重度，未修）：`test_stat_tile_has_value` 只檢查「不是 `–`」，沒有檢查是否為數字。

### B. 1.10 補驗證

- **重新實測退化**：新增 `loadtest/repro_degradation.py`，依序執行 fresh → c=8 超載 → c=2 ×2 → c=4 → c=1 → 重啟，共 2 個循環。原始資料在 `reports/raw/1.10/degradation/`。

  | 情境 | c=2 吞吐 (tok/s) |
  |---|---:|
  | 剛重啟 | 163.8 / 165.6 |
  | 超載之後 | 77.1–89.3（−46% 到 −53%） |
  | 再次重啟 | 165.7 / 165.3 |

  c=1 與 c=4 不受影響。cycle 2 剛超載後只有部分請求變慢：第一次 2/8、第二次 6/8。
- **基準報告**新增獨立段落〈Operational risk〉，內容包含：
  - 退化前後的實測表；
  - 對正式環境的影響；
  - 4 個緩解選項，都尚未實作，留給你決定。

  Methodology 段落則改為引用這一段。
- **Codex 第 1 輪：有條件通過**，2 項必修：
  - **bench.py 的臨時 key 不能保證一定刪除。** 修正後會再查詢確認已刪除；刪除失敗時以結束碼 3 回報，也不會掩蓋原本的錯誤。
  - **「fully degraded」與原始資料不符。** 已改正。

  另外：
  - 補上原始資料：基準報告引用的 3 組原始輸出已存到 `reports/raw/1.10/`。
  - 新增測試：
    - 用假 SSE 伺服器驗證 TTFT 與 decode 公式，並做過突變檢查；
    - 驗證 summarize 的計算結果完全正確；
    - 驗證 key 清理在各種失敗情境下的行為。
  - `pyproject.toml` 加上 `xfail_strict = true`。
- **Codex 第 2 輪：通過**，沒有剩下的問題。
- **完整套件**：152 passed, 1 xfailed。

## 卡住的問題

（目前沒有）

## 需要你決定的事

1. **1.9 剩下的低嚴重度問題**：要不要把 stat 面板的檢查加強為「必須是數字加單位」？Scrape targets 面板顯示的是文字「all up」，需要另外處理。
2. **Qdrant p95 REST latency 的點很稀疏**，幾乎看不到。要不要在儀表板開啟 `showPoints`？
3. **Ollama 超載後退化的緩解方式**：見 `docs/benchmarks/2026-11-26-baseline.md` 的〈Operational risk〉。選項有：維持 Gateway 並發上限總和不超過槽位數（目前已是如此）、加偵測告警、排程重啟、換 vLLM 後重測。
4. **Failed 面板會出現 `None` 序列**（LiteLLM 把格式錯誤的 400 記成 `None`）。要不要在面板中把 `None` 重新命名，例如改成「other / unknown」？

## 明天早上該怎麼檢查

（全部項目完成後補上）
