# 地圖內嵌資源（assets）

`mapviewer.py` 產生離線地價熱力圖時，會把本目錄的資源全部內嵌進輸出的單一
HTML，使其無網路也能開啟（僅 OpenStreetMap 街道底圖需要網路）。

## 檔案

| 檔案 | 來源 | 版本 | 授權 |
| --- | --- | --- | --- |
| `villages-10t.json.gz` | [taiwan-atlas](https://github.com/dkng/taiwan-atlas)（資料源：內政部國土測繪中心） | 下載於 2026-06-11 | 政府資料開放授權／CC BY 4.0 |
| `leaflet.js`、`leaflet.css` | [Leaflet](https://leafletjs.com/) | 1.9.4 | BSD-2-Clause |
| `topojson-client.min.js` | [topojson-client](https://github.com/topojson/topojson-client) | 3.1.0 | ISC |

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
