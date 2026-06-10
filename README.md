# TwLandPrice

台灣地價視覺化。

## 專案架構

```
TwLandPrice/
├── twlandprice/          # 主程式套件
│   ├── __init__.py
│   ├── fetcher.py        # 下載 → 解壓 → 解析內政部實價登錄批次資料
│   ├── cleaner.py        # 欄位清理／正規化（日期、金額、面積、樓層等）
│   ├── storage.py        # 清理後資料寫入 SQLite（跨期累積與查詢）
│   ├── analyzer.py       # 統計分析（縣市／地區／月份／交易類型報表）
│   └── visualizer.py     # HTML 視覺化報告（縣市方格地圖＋圖表）
├── tests/                # 單元測試
│   ├── test_fetcher.py
│   ├── test_cleaner.py
│   ├── test_storage.py
│   ├── test_analyzer.py
│   └── test_visualizer.py
├── docker/               # Docker 環境
│   ├── Dockerfile
│   ├── build.sh          # 建立 image
│   └── docker-compose.yaml
├── logs/                 # 執行 log（內容不納入版控）
├── plans/                # 開發計畫文件（Claude Code plan mode 產出）
├── requirements.txt
├── pytest.ini
├── run.sh                # 啟動主程式 / 測試
├── .gitlab-ci.yml        # GitLab CI/CD：main 更新自動鏡像到 GitHub
└── README.md
```

## 資料來源

內政部不動產成交案件實際資訊資料供應系統（實價登錄）：

- 下載頁：<https://plvr.land.moi.gov.tw/DownloadOpenData>
- 批次資料每月 1、11、21 發布；中央**無即時 API**，採 ZIP 批次下載。
- 內容涵蓋不動產買賣、預售屋買賣與不動產租賃成交案件。

## 使用方式

所有程式於 Docker container 內執行。

### 建立 image

```bash
docker/build.sh
```

### 執行擷取（下載 → 解壓 → 解析）

```bash
./run.sh                      # 最新一期
./run.sh --season 113S1       # 指定民國 113 年第 1 季
./run.sh --clean              # 解析後執行欄位正規化
./run.sh --season 113S1 --db data/twlandprice.db   # 清理後寫入 SQLite
```

### 執行統計分析（需先以 `--db` 入庫）

```bash
./run.sh analyze                                   # 買賣依地區（預設前 10）
./run.sh analyze --report monthly --table rent     # 租賃月份趨勢
./run.sh analyze --report type --top 0             # 交易類型（全部）
```

### 產生視覺化報告（需先以 `--db` 入庫）

```bash
./run.sh visualize                                 # 買賣報告 → output/report_sale.html
./run.sh visualize --table rent                    # 租賃報告 → output/report_rent.html
```

### 執行單元測試

```bash
./run.sh pytest
# 或
docker compose -f docker/docker-compose.yaml run --rm app pytest
```

## 主要模組：`twlandprice.fetcher`

| 函式 | 說明 |
| --- | --- |
| `build_download_url` | 組出內政部批次資料下載網址 |
| `download_opendata` | 下載批次 ZIP |
| `extract_zip` | 解壓並列出其中的 CSV |
| `parse_land_csv` | 解析雙標頭 CSV（以中文欄名為 key） |
| `fetch_and_parse` | 完整流程：下載 → 解壓 → 解析（排除 `schema-*.csv`） |

> 內政部 CSV 採雙標頭格式（第一列中文欄名、第二列英文欄名），
> `parse_land_csv` 會以中文欄名為 key 並自動跳過英文標頭列；
> 主表與 `_land`／`_build`／`_park` 子表皆可正確解析。
> ZIP 內的 `schema-*.csv` 為欄位定義說明檔，不列入解析。

## 主要模組：`twlandprice.cleaner`

| 函式 | 說明 |
| --- | --- |
| `parse_roc_date` / `parse_chinese_date` | 民國日期（`1150506`、`88年7月13日`）轉西元 `datetime.date` |
| `parse_amount` / `parse_int` | 金額與整數欄位轉 `int` |
| `parse_area` | 面積轉 `float`（修正前導小數點與浮點精度殘影） |
| `parse_floor` | 樓層轉 `int`（`二十三層`→23、`地下二層`→-2；特殊值保留原字串） |
| `parse_transaction_counts` | 拆解「交易筆棟數」（`土地2建物0車位0`→三個整數） |
| `parse_lease_period` | 拆解「租賃期間」為起迄兩個日期 |
| `clean_record` / `clean_records` | 整筆／整批清理（中文 key 不變，複合欄位另增衍生欄位） |

> 清理時空字串轉為 `None`；轉換失敗的值保留原字串並彙總一行 warning log。
> 衍生欄位沿用官方「`原欄名-子欄名`」慣例（如 `交易筆棟數-土地`）。
> `建物分層` 與 `車位所在樓層` 值域複雜，僅保留原字串。

## 主要模組：`twlandprice.storage`

| 函式 | 說明 |
| --- | --- |
| `connect` | 開啟（必要時建立）SQLite 資料庫連線 |
| `parse_csv_name` | 解析 CSV 檔名為（縣市代碼, 縣市, 資料表名） |
| `save_records` / `save_results` | 寫入單檔／整批清理後記錄（批次替換語意） |
| `summarize` | 統計各資料表總筆數 |

> 採標準函式庫 `sqlite3`，一表種一資料表：`sale`（買賣）／`presale`（預售）／
> `rent`（租賃），子表加 `_land`／`_build`／`_park` 後綴；中文欄名直接作為欄位名，
> 並附加 `縣市代碼`、`縣市`、`季別` metadata 欄。
> 同（縣市, 季別）批次重複匯入採**先刪後寫**，重跑不產生重複資料；
> 新欄位自動以 `ALTER TABLE` 補上；`datetime.date` 以 ISO 字串儲存。

## 主要模組：`twlandprice.analyzer`

| 函式 | 說明 |
| --- | --- |
| `county_stats` | 依縣市聚合（筆數遞減排序） |
| `district_stats` | 依縣市＋鄉鎮市區聚合（筆數遞減排序） |
| `monthly_trend` | 依月份聚合（時間趨勢，月份遞增排序） |
| `type_stats` | 依交易標的（交易類型）聚合 |
| `format_report` | 報表結果格式化為 TSV 文字 |
| `main` | CLI：`--db`／`--table`／`--report`／`--top` |

> 指標：筆數、單價（元/平方公尺）中位數與平均、總價中位數
> （rent 表自動改用 `租賃年月日`／`總額元`）。
> cleaner 容錯保留的字串值不納入數值統計，但計入筆數；
> 日期非 ISO 格式的記錄不納入月份分組。

## 主要模組：`twlandprice.visualizer`

| 函式 | 說明 |
| --- | --- |
| `svg_tile_map` | 台灣 22 縣市方格地圖（顏色深淺＝單價中位數） |
| `svg_hbar_chart` / `svg_line_chart` | 橫條圖／折線圖 SVG 產生器 |
| `render_report` / `write_report` | 組裝／輸出完整 HTML 報告 |
| `main` | CLI：`--db`／`--table`／`--output` |

> 純標準函式庫產生**單檔 HTML**（內嵌 SVG），瀏覽器原生渲染中文，
> 不需 matplotlib 與 CJK 字型。地圖採方格地圖（tile grid map）近似
> 地理位置呈現縣市分布，不需地理邊界資料。
> 報告內容：縣市地價地圖、成交量前 15 區單價橫條圖、月份趨勢折線圖
> （單價＋筆數）、交易類型橫條圖；輸出至 `output/`（不納入版控）。

## 待辦事項

資料管線四層（擷取 → 清理 → 儲存 → 分析／視覺化）皆已完成：

- [x] **資料清理**：正規化欄位（日期、金額、面積單位等）。
  `建物分層` 多值複合欄暫保留原字串，待分析需求明確後再拆解。
- [x] **資料儲存**：將清理後的資料寫入資料庫，支援跨期累積與查詢。
  採 SQLite 單檔資料庫（`--db PATH`）；跨期累積以季別為批次單位。
- [x] **資料分析**：依地區、時間、交易類型等維度進行統計分析。
  `./run.sh analyze`；指標為筆數、單價中位數／平均、總價中位數。
- [x] **視覺化**：以地圖與圖表呈現台灣地價分布與趨勢。
  `./run.sh visualize` 產生單檔 HTML 報告（縣市方格地圖＋圖表）。

## 版本控制與遠端

本專案採雙遠端結構，以自架 GitLab 為主、GitHub 為鏡像：

| 遠端 | 位址 | 角色 |
| --- | --- | --- |
| `origin` | `ssh://git@localhost:2222/nk7260ynpa/TwLandPrice.git` | 主要遠端（GitLab） |
| `github` | `git@github.com:nk7260ynpa/TwLandPrice.git` | 鏡像（GitHub） |

## GitLab → GitHub 自動同步

`.gitlab-ci.yml` 定義 `sync-to-github` 工作：每當有 commit 進入 `main`
（含其他分支 merge 進 `main`）即觸發，將 `main` 分支與標籤推送到 GitHub，
使兩邊程式碼保持一致。

設定需求：

1. **Runner**：GitLab 專案需有可用的 Runner。
2. **CI/CD 變數 `GITHUB_SSH_KEY`**：對 GitHub repo 具 push 權限的 SSH 私鑰
   （File 型）。
3. **網路**：Runner 需能對外連線至 `github.com`（SSH，22 埠）。
