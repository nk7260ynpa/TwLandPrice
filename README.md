# TwLandPrice

台灣地價視覺化。

## 專案架構

```
TwLandPrice/
├── twlandprice/          # 主程式套件
│   ├── __init__.py
│   ├── fetcher.py        # 下載 → 解壓 → 解析內政部實價登錄批次資料
│   └── cleaner.py        # 欄位清理／正規化（日期、金額、面積、樓層等）
├── tests/                # 單元測試
│   ├── test_fetcher.py
│   └── test_cleaner.py
├── docker/               # Docker 環境
│   ├── Dockerfile
│   ├── build.sh          # 建立 image
│   └── docker-compose.yaml
├── logs/                 # 執行 log（內容不納入版控）
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

## 待辦事項

目前完成資料擷取與清理層，後續規劃如下：

- [x] **資料清理**：正規化欄位（日期、金額、面積單位等）。
  `建物分層` 多值複合欄暫保留原字串，待分析需求明確後再拆解。
- [ ] **資料儲存**：將清理後的資料寫入資料庫，支援跨期累積與查詢。
- [ ] **資料分析**：依地區、時間、交易類型等維度進行統計分析。
- [ ] **視覺化**：以地圖與圖表呈現台灣地價分布與趨勢。

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
