# 資料清理模組（cleaner.py）實作規劃

## Context

`fetch_and_parse` 回傳的記錄所有值皆為原始字串（民國日期 `1150506`、中文日期
`96年11月16日`、前導小數點面積 `.40`、精度殘影 `81.42999999999999`、複合欄
`土地2建物0車位0`、中文樓層 `二十三層`、空字串），後續儲存與分析無法直接使用。
本工作對應 GitLab issue #4 與 README 待辦「資料清理」。

**已確認決策**：完整版範圍（日期／金額／面積／筆棟數／空值／中文樓層／租賃期間／
精度修正）；保留中文 key 只轉值；獨立模組 + fetcher CLI `--clean` 旗標，預設行為不變；
純標準函式庫，不引入新依賴。

**既有追蹤項目（沿用、不再新建）**：issue #4、分支 `4-clean-normalize-fields`
（本地已在此分支）、Draft MR !4（`Closes #4`）。

## 修改檔案

| 檔案 | 動作 |
| --- | --- |
| `twlandprice/cleaner.py` | 新增（核心模組） |
| `tests/test_cleaner.py` | 新增 |
| `twlandprice/fetcher.py` | `main()` 加 `--clean` 旗標與後處理（`fetch_and_parse` 簽名不動） |
| `tests/test_fetcher.py` | 補 `--clean` 整合測試與無旗標迴歸測試 |
| `README.md` | 架構樹、使用方式、cleaner 模組表、待辦勾選 |

## cleaner.py 設計

### 值解析函式（純函式，繁中 docstring，Google style）

- `parse_roc_date(text) -> date | None`：`1150506`→2026-05-06；`0740528`（7 碼前導零）
  與 6 碼 `990101` 皆支援（`year=int(text[:-4])+1911`）；`""`/`"0000000"`→None；
  無效月日／非數字→`ValueError`。
- `parse_chinese_date(text) -> date | None`：`96年11月16日`→2007-11-16
  （regex `^(\d{1,3})年(\d{1,2})月(\d{1,2})日$`）；`""`→None；無效→`ValueError`。
- `parse_amount(text) -> int | None`：`""`→None；非整數→`ValueError`。
- `parse_area(text) -> float | None`：regex 驗格式（拒 nan/inf/科學記號）→
  `round(float(text), 2)`（官方精度 2 位，可還原 `81.42999999999999`→81.43、
  `.40`→0.4）；`""`→None。
- `parse_int(text) -> int | None`：屋齡、持分分母／分子、格局-房／廳／衛。
- `parse_floor(text) -> int | str | None`（寬鬆）：純阿拉伯數字→int（租賃表實際有
  `10`）；去尾碼 `層`／`樓`；`地下層`→-1、`地下二層`→-2；中文數字轉換
  （見演算法）；`全`、多值（`十層，十一層`）、`電梯樓梯間` 等特殊值→原樣回傳
  str（屬預期值域，不警告）；`""`→None。
- `parse_transaction_counts(text) -> tuple[int,int,int] | None`：regex
  `^土地(\d+)建物(\d+)車位(\d+)$`；`""`→None；不符→`ValueError`。
- `parse_lease_period(text) -> tuple[date|None, date|None] | None`：以 `~` 切分，
  兩側各走 `parse_roc_date`；`""`→None；無 `~`→`ValueError`。

中文數字轉 int（支援至三位數）：`result=0; current=0`；逐字元——數字字→`current=digit`、
`十`→`result+=(current or 1)*10; current=0`、`百`→`result+=(current or 1)*100; current=0`、
`零`→continue、其他→失敗；回傳 `result+current`。驗證：二十三→23、十→10、一百零一→101。

### 規則表（單一規則表涵蓋 6 種表，已確認同名欄語意一致）

三層比對，**命中即停**：展開 → 精確 → 子字串 → 預設（空字串→None，其餘原樣）。

1. `_EXPAND_RULES`（精確欄名→衍生欄位，原欄保留原字串）：`交易筆棟數`、
   `租賃筆棟數`、`租賃期間`。
2. `_EXACT_RULES`：日期 4 欄（`交易年月日`/`租賃年月日`/`建築完成年月`→roc、
   `建築完成日期`→chinese）；金額 6 欄（`總價元`/`總額元`/`單價元平方公尺`/
   `車位總價元`/`車位總額元`/`車位價格`）；樓層 4 欄（`移轉層次`/`租賃層次`/
   `總樓層數`/`總層數`）；整數 6 欄（格局-房/廳/衛、`屋齡`、持分分母/分子）。
3. `_SUBSTRING_RULES`：`("面積", parse_area)`——涵蓋全部面積欄（含無「平方公尺」
   後綴的 `主建物面積`/`附屬建物面積`/`陽台面積`）。

效能：`clean_records` 以首筆 keys 預建 column plan（每欄決定一次規則），逐筆查表。

**明確不轉換**（docstring 註明）：`建物分層`（多值複合 `一層 二層 三層 騎樓`，保留
原字串）、`車位所在樓層`（值域不規則 `無固定樓層`/`地下五樓含以下`）、其餘文字欄
僅空字串→None。

### 衍生欄位命名（沿用官方 `-` 子欄位慣例，插在原欄之後）

| 原欄（保留原字串） | 衍生欄位 |
| --- | --- |
| `交易筆棟數`／`租賃筆棟數` | `…-土地`、`…-建物`、`…-車位`（int\|None） |
| `租賃期間` | `租賃期間-起`、`租賃期間-迄`（date\|None） |

### 容錯策略

- 空字串／`0000000` → None，不記。
- 樓層特殊值 → 原字串，不記。
- 嚴格解析器 `ValueError` → **保留原字串**（不丟資訊），`CleanStats`
  （dataclass：`failures: dict[欄名,次數]`、`samples: dict[欄名,首個樣本]`）計數，
  `clean_records` 結束時每欄一行 `logger.warning`（不逐筆灌 log、不中斷整批）。

### 記錄層 API

- `clean_record(record, stats=None) -> dict[str, object]`
- `clean_records(records) -> list[dict[str, object]]`（彙總 warning）

## fetcher.py 改動（最小）

- `main()` 加 `parser.add_argument("--clean", action="store_true", ...)`。
- `fetch_and_parse` 之後：`if args.clean: result = {name: cleaner.clean_records(r) for ...}`。
- 輸出維持 `print(f"{name}: {len(records)} 筆")`，`--clean` 時行尾加註；
  失敗統計走既有 logging（console + logs/fetcher.log）。

## 測試（tests/test_cleaner.py，沿用現有 pytest 風格）

各解析函式邊界：前導零 7 碼、6 碼日期、`0000000`、無效日 `1150230`、`.40`、
`81.42999999999999`→81.43、`一百零一層`→101、阿拉伯數字 `10`、`地下層`→-1、
`全`→原樣、多值樓層→原樣、`1150412~`→(date, None)、無 `~`→ValueError、
`土地12建物1車位1`→(12,1,1)。

記錄層：買賣／租賃／build 子表整筆型別斷言；衍生欄緊接原欄（key 順序）；
轉失敗保留原值；`caplog` 斷言彙總 warning 每欄一行；空清單→[]。

fetcher 整合：mock 網路後 `main(["--clean"])` 值型別正確；無旗標時值仍為 str（迴歸）。

## 驗證

1. Docker 內 `./run.sh pytest`：既有 9 項 + 新測試全綠。
2. 以本地 `data/extracted/*.csv` 實資料抽驗：`parse_land_csv` + `clean_records`
   跑 a 主表、c 租賃表、build 子表各一，檢查型別與失敗彙總 log 合理。
3. 端到端：`./run.sh --clean`（或 mock 模式跳過，視網路）。

## 收尾（GitLab 流程）

1. Commit（繁中 Conventional Commits）→ push `4-clean-normalize-fields`。
2. 更新 MR !4：勾選工作項目、補驗證章節、解除 Draft（gitlab skill raw PUT）。
3. 合併與否由使用者決定（合併後 `Closes #4` 自動關 issue、CI 鏡像 GitHub）。
4. 更新專案記憶 `data-cleaning-task.md` 狀態。
