# 地圖內嵌資源（assets）

`mapviewer.py` 產生離線地價熱力圖時，會把本目錄的資源全部內嵌進輸出的單一
HTML，使其無網路也能開啟（僅 OpenStreetMap 街道底圖需要網路）。

## 檔案

| 檔案 | 來源 | 版本 | 授權 |
| --- | --- | --- | --- |
| `villages-10t.json.gz` | [taiwan-atlas](https://github.com/dkng/taiwan-atlas)（資料源：內政部國土測繪中心） | 下載於 2026-06-11 | 政府資料開放授權／CC BY 4.0 |
| `households.json` | 內政部戶政司 RS-OpenData `ODRP019`（戶數、人口數按戶別及性別） | 民國 114 年 | 政府資料開放授權 |
| `leaflet.js`、`leaflet.css` | [Leaflet](https://leafletjs.com/) | 1.9.4 | BSD-2-Clause |
| `topojson-client.min.js` | [topojson-client](https://github.com/topojson/topojson-client) | 3.1.0 | ISC |

`households.json` 為各鄉鎮市區總戶數（共同生活戶＋共同事業戶＋單獨生活戶），
鍵為正規化「縣市/鄉鎮市區」（臺→台），供地圖計算**交易率**（成交筆數 ÷ 戶數
× 1000，每千戶成交筆數）。原始資料為村里層，以村里代碼前 8 碼（＝鄉鎮市區
代碼，對齊 taiwan-atlas `TOWNCODE`）聚合。

`villages-10t.json` 為 TopoJSON，含 `counties`（22）、`towns`（368）、
`villages`（7,701）、`nation`（1）四個物件；原始約 4.2 MB，以 `gzip -9`
壓縮為約 0.8 MB 存放，`mapviewer` 於產生時以標準函式庫 `gzip` 解壓。

## 重新下載

```bash
curl -L -o /tmp/villages-10t.json https://cdn.jsdelivr.net/npm/taiwan-atlas/villages-10t.json
gzip -9 -c /tmp/villages-10t.json > villages-10t.json.gz
curl -L -o leaflet.js  https://unpkg.com/leaflet@1.9.4/dist/leaflet.js
curl -L -o leaflet.css https://unpkg.com/leaflet@1.9.4/dist/leaflet.css
curl -L -o topojson-client.min.js https://unpkg.com/topojson-client@3.1.0/dist/topojson-client.min.js
```

戶數（`households.json`）取自戶政司 RS-OpenData，分頁抓取後依鄉鎮市區聚合：

```bash
# 民國年（yyy），例：114
for p in 1 2 3 4; do
  curl -L "https://www.ris.gov.tw/rs-opendata/api/v1/datastore/ODRP019/114?page=${p}"
done
# 逐村里加總 household_ordinary_total＋household_business_total＋household_single_total，
# 依 district_code 前 8 碼聚合到鄉鎮市區（對應 taiwan-atlas TOWNCODE）。
```
