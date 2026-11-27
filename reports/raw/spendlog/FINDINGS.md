# Spend log 漏記：調查結果（2026-11-27，限時 30 分鐘，實際約 10 分鐘）

## 結論

**假設「串流請求沒有寫入 spend log」不成立。** 串流與非串流的 chat completion 都會漏記，條件完全相同。

**原因已找到並驗證：request_id 碰撞。**

1. Ollama 的 OpenAI 相容 API 回傳的 response `id` 是 `chatcmpl-<數字>`，數字只有 3 位數左右的範圍。DB 中 880 筆 chat 紀錄的 id 全部是這個格式，數字分布在 0–997，880 筆全部不同。
2. LiteLLM 1.83.14 直接拿 provider 回傳的 `id` 當 `LiteLLM_SpendLogs` 的主鍵 `request_id`。只有沒有 `id` 時才用自己的 `litellm_call_id`（UUID）：
   - 原始碼 `litellm/proxy/spend_tracking/spend_tracking_utils.py` 的 `get_spend_logs_id()`：`response_obj.get("id") or kwargs.get("litellm_call_id")`。
3. 寫入時用 `create_many(..., skip_duplicates=True)`（`litellm/proxy/utils.py` 約第 4853 行），**主鍵重複的紀錄會被靜默丟掉**，不會有錯誤或 log。
4. 所以，id 空間（約 1000 個）被用掉越多，新的 chat 越容易碰撞：
   - 目前已用掉約 88%，新的 chat 大約只有 12% 會被記錄；
   - 用滿之後，chat 幾乎都不會被記錄。
   - 這也解釋了為什麼昨晚表剛開始累積時記錄比例較高（16:00 那一小時 97 筆），之後越來越低。
5. Embedding 不受影響：Ollama 的 embedding 回應沒有 `id`，LiteLLM 改用 UUID。

## 驗證（`spendlog_probe.py`，使用臨時 key，結束後刪除並確認）

- `run1-baseline.txt`：每組 5 筆。
  - 非串流 chat：0/5 有紀錄；
  - 串流 chat：0/5；
  - embedding：5/5。
- `run2-collision.txt`：每組 10 筆，記下每個回應的 `id`，並在送出前比對 DB 中是否已有這個 id。

  | chat 回應 id（共 20 筆） | 本 key 有紀錄 |
  |---|---|
  | 表中原本沒有的：5 筆 | **5 / 5** |
  | 表中已存在的：15 筆 | **0 / 15** |
  | embedding（UUID） | 10 / 10 |

  預測與結果完全一致，串流與非串流都是如此。

## 沒有做的事

- 沒有調高 LiteLLM 的 log level：不需要，所以也沒有要還原的設定。
- 沒有修改任何設定、沒有刪除 DB 資料。

## 尚未驗證

- 昨晚「約 10 分鐘完全沒有寫入」：
  - 可能是同一原因，例如那段時間的請求剛好都碰撞，或幾乎只有 chat；
  - 也可能是另一個問題。
  - 這次沒有重現。

## 影響

- 依 DB spend 計算的費用、預算與用量報表（LiteLLM UI 與 `/spend/*`）會嚴重低估 chat 用量。
- Prometheus 指標與 Grafana 儀表板不受影響：它們不經過 spend log。
- `tests/platform/test_gateway.py::test_spend_log_increments` 是弱斷言，抓不到這個問題：
  - 它只檢查送出 1 筆 chat 後「總筆數有增加」；
  - 其他請求寫入的紀錄也會讓它通過。

## 可能的處理方式（需要你決定）

1. **LiteLLM 改用 `ollama_chat/` provider**（不經 Ollama 的 OpenAI 相容 API）。
   - 預期 LiteLLM 會自己產生 UUID 形式的 id。
   - 尚未驗證，而且是設定變更，會改變 provider 的行為。
2. **等第二階段換 vLLM**：vLLM 的 id 是 `chatcmpl-<uuid>`，碰撞機率可以忽略。
3. **向 LiteLLM 回報**：用 provider 的 id 當主鍵，再加上 `skip_duplicates`，會靜默丟資料。可以和 parallel counter 一起整理成 issue 草稿。
4. **測試**：
   - 把 `test_spend_log_increments` 改成「這一筆請求自己的紀錄存在」（以 response id 與 key 比對）。
   - 在目前環境下它會失敗，或者要標成 `xfail(strict)` 追蹤。
