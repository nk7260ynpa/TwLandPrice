"""互動式台灣鄉鎮市區地價熱力圖（離線單檔）。

以 ``storage`` 產出的 SQLite 為來源，將每個鄉鎮市區依單價中位數（或
平均）上色（白→深紅），套疊在 taiwan-atlas 的真實地理邊界上，輸出
可離線開啟的單一 HTML。Leaflet 程式庫、村里界 TopoJSON 與價格資料
全部內嵌於輸出檔內，無網路也能開啟、縮放、搜尋村里；僅 OpenStreetMap
街道底圖需要網路（可關閉）。

地圖支援縣市／鄉鎮市區／村里三層級切換：縣市層依縣市單價上色、鄉鎮
與村里層依鄉鎮市區單價上色（村里繼承所屬鄉鎮市區的價格）。實價登錄
的縣市名使用「臺」、taiwan-atlas 使用「台」，故 join 前統一正規化。

圖資來源：內政部國土測繪中心（經 taiwan-atlas 封裝）。本模組純標準
函式庫，不引入新依賴。
"""

import argparse
import gzip
import json
import logging
import sqlite3
from pathlib import Path

from twlandprice import analyzer

logger = logging.getLogger(__name__)

# 內嵌資源目錄（vendored Leaflet／topojson-client 與村里界 TopoJSON）。
_ASSETS_DIR = Path(__file__).parent / "assets"

# 各主表的中文標籤（與 visualizer 一致）。
_TABLE_LABELS = {"sale": "買賣", "presale": "預售屋", "rent": "租賃"}

# 上色指標 → analyzer 報表的欄位名。
_METRIC_FIELDS = {"median": "單價中位數", "mean": "單價平均"}

# 無資料區塊的填色。
_NO_DATA_FILL = "#cfd6df"


def _normalize(name: str) -> str:
    """正規化地名以利跨資料源比對（臺→台、去除前後空白）。

    Args:
        name: 縣市或鄉鎮市區名稱。

    Returns:
        正規化後的名稱。
    """
    return (name or "").replace("臺", "台").strip()


def _percentile(sorted_values: list[float], q: float) -> float:
    """計算已排序數列的百分位數（線性內插，純標準函式庫）。

    Args:
        sorted_values: 由小到大排序的數值清單（不可為空）。
        q: 百分位（0～1）。

    Returns:
        對應百分位的數值。
    """
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = q * (len(sorted_values) - 1)
    low = int(pos)
    frac = pos - low
    if low + 1 < len(sorted_values):
        return sorted_values[low] * (1 - frac) + sorted_values[low + 1] * frac
    return float(sorted_values[low])


def _level_payload(rows: list[dict[str, object]], key_fields: list[str],
                   metric: str) -> dict[str, object]:
    """將 analyzer 報表轉為前端可用的單一層級資料（值字典＋色階定義域）。

    Args:
        rows: ``analyzer`` 報表輸出（每區一筆 dict）。
        key_fields: 組成查找鍵的欄位（如 ``["縣市"]`` 或
            ``["縣市", "鄉鎮市區"]``），值會經正規化後以 ``/`` 串接。
        metric: 上色指標（``median`` 或 ``mean``）。

    Returns:
        含 ``domain``（第 5 與第 95 百分位，兩端離群值會被截到端點）與
        ``values``（查找鍵 → 統計 dict）的 dict。
    """
    field = _METRIC_FIELDS[metric]
    values: dict[str, dict[str, object]] = {}
    metric_values: list[float] = []
    for row in rows:
        key = "/".join(_normalize(str(row[f])) for f in key_fields)
        values[key] = {
            "n": row["筆數"],
            "median": row["單價中位數"],
            "mean": row["單價平均"],
            "total": row["總價中位數"],
        }
        value = row.get(field)
        if isinstance(value, (int, float)):
            metric_values.append(float(value))
    if metric_values:
        metric_values.sort()
        domain = [_percentile(metric_values, 0.05),
                  _percentile(metric_values, 0.95)]
    else:
        domain = [0, 1]
    return {"domain": domain, "values": values}


def load_price_data(conn: sqlite3.Connection, table: str = "sale",
                    metric: str = "median") -> dict[str, object]:
    """自資料庫建立地圖所需的縣市與鄉鎮市區價格資料。

    Args:
        conn: 資料庫連線。
        table: 主表名，預設 ``sale``。
        metric: 上色指標（``median`` 或 ``mean``），預設 ``median``。

    Returns:
        含 ``metric``、``table`` 與 ``levels``（``counties``／``towns``
        兩層級的 domain 與 values）的 dict，可直接 ``json.dumps``。
    """
    counties = analyzer.county_stats(conn, table)
    towns = analyzer.district_stats(conn, table)
    return {
        "metric": metric,
        "table": table,
        "tableLabel": _TABLE_LABELS.get(table, table),
        "levels": {
            "counties": _level_payload(counties, ["縣市"], metric),
            "towns": _level_payload(towns, ["縣市", "鄉鎮市區"], metric),
        },
    }


def _load_asset_text(name: str) -> str:
    """讀取 ``assets/`` 內的文字資源。

    Args:
        name: 檔名。

    Returns:
        檔案內容字串。
    """
    return (_ASSETS_DIR / name).read_text(encoding="utf-8")


def _load_topojson() -> str:
    """讀取並解壓村里界 TopoJSON，回傳原始 JSON 字串。

    Returns:
        TopoJSON 的 JSON 字串（未再經 parse／序列化，保留原樣）。
    """
    with gzip.open(_ASSETS_DIR / "villages-10t.json.gz", "rt",
                   encoding="utf-8") as handle:
        return handle.read()


def render_map(price_data: dict[str, object],
               topojson_data: str | None = None) -> str:
    """組裝離線地價熱力圖的完整 HTML。

    Args:
        price_data: ``load_price_data`` 的輸出。
        topojson_data: 村里界 TopoJSON 的 JSON 字串；``None`` 時自
            ``assets/`` 載入。注入測試可傳入精簡圖資以加速。

    Returns:
        自含的 HTML 字串（內嵌 Leaflet、TopoJSON 與價格資料）。
    """
    if topojson_data is None:
        topojson_data = _load_topojson()
    table_label = price_data.get("tableLabel", price_data.get("table", ""))
    metric_label = "單價中位數" if price_data.get("metric") == "median" \
        else "單價平均"
    return (_HTML_TEMPLATE
            .replace("@@LEAFLET_CSS@@", _load_asset_text("leaflet.css"))
            .replace("@@LEAFLET_JS@@", _load_asset_text("leaflet.js"))
            .replace("@@TOPOJSON_JS@@",
                     _load_asset_text("topojson-client.min.js"))
            .replace("@@TOPO_DATA@@", topojson_data)
            .replace("@@PRICE_DATA@@",
                     json.dumps(price_data, ensure_ascii=False))
            .replace("@@TITLE@@", f"台灣地價熱力圖（{table_label}）")
            .replace("@@METRIC_LABEL@@", metric_label)
            .replace("@@TABLE_LABEL@@", table_label)
            .replace("@@NO_DATA_FILL@@", _NO_DATA_FILL))


def write_map(conn: sqlite3.Connection, output: Path, table: str = "sale",
              metric: str = "median") -> Path:
    """產生地價熱力圖並寫入檔案（上層目錄不存在時自動建立）。

    Args:
        conn: 資料庫連線。
        output: 輸出 HTML 檔案路徑。
        table: 主表名，預設 ``sale``。
        metric: 上色指標，預設 ``median``。

    Returns:
        實際寫入的檔案路徑。
    """
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    price_data = load_price_data(conn, table, metric)
    output.write_text(render_map(price_data), encoding="utf-8")
    logger.info("地價熱力圖已輸出：%s", output)
    return output


def _setup_logging() -> None:
    """設定 console 與檔案雙輸出的 logging。"""
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "mapviewer.log", encoding="utf-8"),
        ],
    )


def main(argv: list[str] | None = None) -> int:
    """命令列進入點。

    Args:
        argv: 命令列參數（預設取自 ``sys.argv``）。

    Returns:
        程式結束碼，成功為 0；資料庫或資料表不存在為 1。
    """
    parser = argparse.ArgumentParser(
        description="實價登錄 SQLite 資料互動式地價熱力圖（離線單檔 HTML）")
    parser.add_argument("--db", default="data/twlandprice.db",
                        help="SQLite 資料庫路徑（預設 data/twlandprice.db）")
    parser.add_argument("--table", default="sale",
                        choices=sorted(_TABLE_LABELS),
                        help="主表（預設 sale）")
    parser.add_argument("--metric", default="median",
                        choices=sorted(_METRIC_FIELDS),
                        help="上色指標：median 中位數／mean 平均（預設 median）")
    parser.add_argument("--output", default=None, metavar="PATH",
                        help="輸出 HTML 路徑（預設 output/map_{table}.html）")
    args = parser.parse_args(argv)

    _setup_logging()
    db_path = Path(args.db)
    if not db_path.exists():
        logger.error("資料庫不存在：%s（請先以 --db 旗標擷取資料）", db_path)
        return 1
    output = Path(args.output) if args.output \
        else Path("output") / f"map_{args.table}.html"
    conn = sqlite3.connect(db_path)
    try:
        write_map(conn, output, args.table, args.metric)
    except sqlite3.OperationalError as error:
        logger.error("無法產生地圖（資料表 %s 不存在？）：%s",
                     args.table, error)
        return 1
    finally:
        conn.close()
    print(f"已輸出地價熱力圖：{output}")
    return 0


# ---------------------------------------------------------------------------
# HTML 模板：以 @@TOKEN@@ 佔位，render_map 以 str.replace 注入內嵌資源與資料。
# 前端為純 Leaflet 應用，圖資以 topojson-client 在瀏覽器端轉為 GeoJSON。
# ---------------------------------------------------------------------------
_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>@@TITLE@@</title>
<style>
@@LEAFLET_CSS@@
</style>
<style>
  :root {
    --panel-bg: #1c2430;
    --panel-bg-2: #232e3d;
    --panel-border: #344256;
    --text: #e8edf4;
    --text-dim: #9fb0c3;
    --accent: #4da3ff;
    --accent-soft: rgba(77, 163, 255, 0.16);
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    font-family: "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", sans-serif;
    background: #0e131a;
    color: var(--text);
    overflow: hidden;
  }
  #map { position: absolute; inset: 0; background: #dfe8ef; }
  #map.no-streets { background: #aeb9c4; }

  .panel {
    position: absolute;
    top: 16px;
    left: 16px;
    z-index: 1000;
    width: 300px;
    background: var(--panel-bg);
    border: 1px solid var(--panel-border);
    border-radius: 14px;
    box-shadow: 0 12px 32px rgba(5, 10, 18, 0.45);
    display: flex;
    flex-direction: column;
    max-height: calc(100% - 32px);
  }
  .panel-header { padding: 14px 16px 10px 16px; }
  .panel-header h1 { font-size: 16px; font-weight: 700; margin: 0; letter-spacing: 0.04em; }
  .panel-header .sub { font-size: 11px; color: var(--text-dim); margin-top: 3px; }
  .panel-body {
    padding: 0 16px 14px 16px;
    display: flex;
    flex-direction: column;
    gap: 14px;
    overflow-y: auto;
  }
  .section-label {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.12em;
    color: var(--text-dim);
    margin-bottom: 6px;
  }

  .seg {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 4px;
    background: var(--panel-bg-2);
    border: 1px solid var(--panel-border);
    border-radius: 9px;
    padding: 4px;
  }
  .seg button {
    appearance: none; border: none; background: transparent;
    color: var(--text-dim); font: inherit; font-size: 13px; font-weight: 600;
    padding: 7px 0; border-radius: 6px; cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }
  .seg button:hover { color: var(--text); }
  .seg button.active { background: var(--accent); color: #0b1828; }

  .toggle-row {
    display: flex; align-items: center; justify-content: space-between;
    gap: 10px; padding: 9px 12px;
    background: var(--panel-bg-2); border: 1px solid var(--panel-border);
    border-radius: 9px;
  }
  .toggle-row + .toggle-row { margin-top: 6px; }
  .toggle-row .label { font-size: 13px; font-weight: 600; }
  .toggle-row .hint { font-size: 11px; color: var(--text-dim); margin-top: 1px; }
  .switch { position: relative; width: 40px; height: 22px; flex: none; }
  .switch input { position: absolute; opacity: 0; width: 100%; height: 100%; margin: 0; cursor: pointer; }
  .switch .track { position: absolute; inset: 0; background: #3a4a5f; border-radius: 999px; transition: background 0.15s; pointer-events: none; }
  .switch .knob { position: absolute; top: 3px; left: 3px; width: 16px; height: 16px; background: #dce5ee; border-radius: 50%; transition: transform 0.15s; pointer-events: none; }
  .switch input:checked ~ .track { background: var(--accent); }
  .switch input:checked ~ .knob { transform: translateX(18px); }

  .slider-row { display: flex; flex-direction: column; gap: 6px; }
  .slider-row .slider-top { display: flex; justify-content: space-between; font-size: 13px; font-weight: 600; }
  .slider-row .slider-top .val { color: var(--accent); font-variant-numeric: tabular-nums; }
  input[type="range"] { width: 100%; accent-color: var(--accent); cursor: pointer; }

  .search-wrap { position: relative; }
  .search-wrap input[type="text"] {
    width: 100%; background: var(--panel-bg-2); border: 1px solid var(--panel-border);
    border-radius: 9px; color: var(--text); font: inherit; font-size: 13px;
    padding: 9px 12px; outline: none;
  }
  .search-wrap input[type="text"]:focus { border-color: var(--accent); }
  .search-wrap input[type="text"]::placeholder { color: #6e8095; }
  .search-results {
    margin-top: 6px; background: var(--panel-bg-2); border: 1px solid var(--panel-border);
    border-radius: 9px; overflow: hidden; display: none; max-height: 220px; overflow-y: auto;
  }
  .search-results.open { display: block; }
  .search-results button {
    display: block; width: 100%; text-align: left; appearance: none;
    background: transparent; border: none; color: var(--text); font: inherit;
    font-size: 13px; padding: 8px 12px; cursor: pointer;
  }
  .search-results button:hover { background: var(--accent-soft); }
  .search-results .crumb { color: var(--text-dim); font-size: 11px; margin-right: 6px; }
  .search-results .empty { padding: 10px 12px; font-size: 12px; color: var(--text-dim); }

  /* 色階圖例 */
  .legend { display: flex; flex-direction: column; gap: 6px; }
  .legend .bar {
    height: 12px; border-radius: 4px;
    background: linear-gradient(to right, #fff5f0, #a50f15);
    border: 1px solid var(--panel-border);
  }
  .legend .ticks { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-dim); font-variant-numeric: tabular-nums; }
  .legend .nodata { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text-dim); }
  .legend .nodata .sw { width: 12px; height: 12px; border-radius: 3px; background: #cfd6df; border: 1px solid var(--panel-border); }

  .loading {
    position: absolute; inset: 0; z-index: 2000; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 14px;
    background: rgba(10, 15, 22, 0.72); backdrop-filter: blur(3px); transition: opacity 0.3s;
  }
  .loading.hidden { opacity: 0; pointer-events: none; }
  .spinner { width: 36px; height: 36px; border: 3px solid rgba(255,255,255,0.18); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.9s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .loading .msg { font-size: 13px; color: var(--text-dim); }
  .loading .err { max-width: 420px; font-size: 13px; color: #ffb4ab; text-align: center; line-height: 1.6; padding: 0 20px; }

  .hoverbox {
    position: absolute; top: 16px; right: 16px; z-index: 1000;
    background: var(--panel-bg); border: 1px solid var(--panel-border);
    border-radius: 12px; box-shadow: 0 10px 26px rgba(5, 10, 18, 0.4);
    padding: 12px 16px; min-width: 200px; pointer-events: none;
  }
  .hoverbox .crumbs { font-size: 12px; color: var(--text-dim); }
  .hoverbox .name { font-size: 19px; font-weight: 700; margin-top: 2px; }
  .hoverbox .idle { font-size: 12px; color: var(--text-dim); }
  .hoverbox .price { margin-top: 8px; font-size: 12px; color: var(--text-dim); line-height: 1.7; }
  .hoverbox .price b { color: var(--text); font-weight: 600; font-variant-numeric: tabular-nums; }
  .hoverbox .price .big { color: var(--accent); font-size: 16px; }

  .stats { font-size: 11px; color: var(--text-dim); line-height: 1.7; }
  .stats b { color: var(--text); font-weight: 600; font-variant-numeric: tabular-nums; }

  .leaflet-container { font: inherit; }
  .credit {
    position: absolute; bottom: 4px; left: 8px; z-index: 900;
    font-size: 10px; color: rgba(20, 35, 50, 0.6); pointer-events: none;
  }
  #map.no-streets ~ .credit { color: rgba(230, 238, 245, 0.5); }

  @media (max-width: 640px) {
    .panel { width: calc(100% - 32px); max-height: 46%; }
    .hoverbox { top: auto; bottom: 16px; right: 16px; left: auto; min-width: 0; }
  }
</style>
</head>
<body>

<div id="map"></div>

<div class="panel">
  <div class="panel-header">
    <h1>台灣地價熱力圖</h1>
    <div class="sub">@@TABLE_LABEL@@ ・ 依@@METRIC_LABEL@@上色（元/m²）</div>
  </div>
  <div class="panel-body">

    <div>
      <div class="section-label">行政區層級</div>
      <div class="seg" id="levelSeg">
        <button type="button" data-level="counties">縣市</button>
        <button type="button" data-level="towns" class="active">鄉鎮市區</button>
        <button type="button" data-level="villages">村里</button>
      </div>
    </div>

    <div>
      <div class="section-label">單價 元/平方公尺</div>
      <div class="legend">
        <div class="bar"></div>
        <div class="ticks"><span id="legendLo">—</span><span id="legendHi">—</span></div>
        <div class="nodata"><span class="sw"></span>無成交資料</div>
      </div>
    </div>

    <div>
      <div class="section-label">底圖</div>
      <div class="toggle-row">
        <div>
          <div class="label">顯示街道</div>
          <div class="hint">OpenStreetMap（需網路）</div>
        </div>
        <label class="switch">
          <input type="checkbox" id="streetToggle">
          <span class="track"></span>
          <span class="knob"></span>
        </label>
      </div>
      <div class="toggle-row">
        <div>
          <div class="label">行政區邊界</div>
          <div class="hint">關掉只看街道圖</div>
        </div>
        <label class="switch">
          <input type="checkbox" id="adminToggle" checked>
          <span class="track"></span>
          <span class="knob"></span>
        </label>
      </div>
    </div>

    <div class="slider-row">
      <div class="slider-top">
        <span>區塊填色透明度</span>
        <span class="val" id="opacityVal">75%</span>
      </div>
      <input type="range" id="opacitySlider" min="0" max="100" step="5" value="75">
    </div>

    <div>
      <div class="section-label">搜尋村里</div>
      <div class="search-wrap">
        <input type="text" id="searchInput" placeholder="例如：永和里、大安區、信義…" autocomplete="off">
        <div class="search-results" id="searchResults"></div>
      </div>
    </div>

    <div class="stats" id="stats">資料載入中…</div>
  </div>
</div>

<div class="hoverbox" id="hoverbox">
  <div class="idle">將滑鼠移到地圖上的區域</div>
</div>

<div class="loading" id="loading">
  <div class="spinner"></div>
  <div class="msg" id="loadingMsg">正在建立全台村里圖層…</div>
</div>

<div class="credit">村里界圖資：內政部國土測繪中心（taiwan-atlas）｜底圖 © OpenStreetMap 貢獻者</div>

<script>window.__TOPO__ = @@TOPO_DATA@@;</script>
<script>window.__PRICES__ = @@PRICE_DATA@@;</script>
<script>
@@TOPOJSON_JS@@
</script>
<script>
@@LEAFLET_JS@@
</script>
<script>
(function () {
  'use strict';

  var topo = window.__TOPO__;
  var PRICES = window.__PRICES__;

  // ---------- 地圖 ----------
  var map = L.map('map', {
    center: [23.7, 120.96],
    zoom: 8,
    minZoom: 7,
    maxZoom: 18,
    zoomControl: false,
    preferCanvas: true,
    maxBounds: [[20.4, 116.6], [27.5, 124.6]],
    maxBoundsViscosity: 0.6
  });
  L.control.zoom({ position: 'bottomright' }).addTo(map);

  var canvasRenderer = L.canvas({ padding: 0.4 });
  var streetLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '© OpenStreetMap'
  });
  document.getElementById('map').classList.add('no-streets');

  // ---------- 狀態 ----------
  var state = { level: 'towns', fillOpacity: 0.75, adminVisible: true };
  var geoCache = {};      // level -> GeoJSON FeatureCollection
  var layerCache = {};    // level -> L.geoJSON
  var meshLayers = [];
  var currentLayer = null;
  var hoveredPath = null;
  var searchIndex = [];

  // ---------- 地名與屬性 ----------
  function norm(s) { return (s || '').replace(/臺/g, '台').trim(); }
  function prop(p, names) {
    for (var i = 0; i < names.length; i++) {
      if (p && p[names[i]] != null && p[names[i]] !== '') return p[names[i]];
    }
    return '';
  }
  function countyName(p) { return prop(p, ['COUNTYNAME']); }
  function townName(p)   { return prop(p, ['TOWNNAME']); }
  function villName(p)   { return prop(p, ['VILLNAME', 'name']); }

  function featureLabel(level, p) {
    if (level === 'counties') return { crumbs: '縣市', name: countyName(p) || '（未命名）' };
    if (level === 'towns')    return { crumbs: countyName(p), name: townName(p) || '（未命名）' };
    return { crumbs: countyName(p) + ' ' + townName(p), name: villName(p) || '（未命名）' };
  }

  // ---------- 價格查找與色階 ----------
  // 縣市層用 counties；鄉鎮與村里層皆用 towns（村里繼承所屬鄉鎮市區）。
  function lookupRecord(level, p) {
    if (level === 'counties') {
      return PRICES.levels.counties.values[norm(countyName(p))] || null;
    }
    var key = norm(countyName(p)) + '/' + norm(townName(p));
    return PRICES.levels.towns.values[key] || null;
  }
  function activeDomain(level) {
    return (level === 'counties' ? PRICES.levels.counties : PRICES.levels.towns).domain;
  }
  function colorScale(t) {
    t = Math.max(0, Math.min(1, t));
    var r = Math.round(255 + (165 - 255) * t);
    var g = Math.round(245 + (15 - 245) * t);
    var b = Math.round(240 + (21 - 240) * t);
    return 'rgb(' + r + ',' + g + ',' + b + ')';
  }
  function fillFor(level, p) {
    var rec = lookupRecord(level, p);
    var v = rec ? rec[PRICES.metric] : null;
    if (v == null) return '@@NO_DATA_FILL@@';
    var d = activeDomain(level);
    var t = d[1] <= d[0] ? 0.5 : (v - d[0]) / (d[1] - d[0]);
    return colorScale(t);
  }

  // ---------- 樣式 ----------
  function baseStyle(feature) {
    return {
      renderer: canvasRenderer,
      color: 'rgba(255,255,255,0.85)',
      weight: state.level === 'villages' ? 0.4 : (state.level === 'towns' ? 0.7 : 1.1),
      fillColor: fillFor(state.level, feature.properties),
      fillOpacity: state.fillOpacity,
      opacity: 1
    };
  }
  function hoverStyle() {
    return { color: '#0b1828', weight: 2.2, fillOpacity: Math.min(1, state.fillOpacity + 0.2) };
  }

  // ---------- 懸停資訊 ----------
  var hoverbox = document.getElementById('hoverbox');
  function fmt(v) { return (v == null) ? '—' : Number(v).toLocaleString('en-US'); }
  function setHover(level, p) {
    if (!p) { hoverbox.innerHTML = '<div class="idle">將滑鼠移到地圖上的區域</div>'; return; }
    var lab = featureLabel(level, p);
    var rec = lookupRecord(level, p);
    var price;
    if (rec) {
      price = '<div class="price">'
        + PRICES.tableLabel + '：<b>' + fmt(rec.n) + '</b> 筆<br>'
        + '單價中位數 <b class="big">' + fmt(rec.median) + '</b> 元/m²<br>'
        + '單價平均 <b>' + fmt(rec.mean) + '</b> ・ 總價中位數 <b>' + fmt(rec.total) + '</b> 元'
        + '</div>';
    } else {
      price = '<div class="price">無成交資料</div>';
    }
    hoverbox.innerHTML =
      '<div class="crumbs">' + (lab.crumbs || '&nbsp;') + '</div>' +
      '<div class="name">' + lab.name + '</div>' + price;
  }

  // ---------- 圖層 ----------
  function getGeo(level) {
    if (!geoCache[level]) geoCache[level] = topojson.feature(topo, topo.objects[level]);
    return geoCache[level];
  }
  function buildLayer(level) {
    return L.geoJSON(getGeo(level), {
      renderer: canvasRenderer,
      style: baseStyle,
      onEachFeature: function (feature, layer) {
        layer.on({
          mouseover: function () {
            if (hoveredPath && hoveredPath !== layer) hoveredPath.setStyle(baseStyle(hoveredPath.feature));
            hoveredPath = layer;
            layer.setStyle(hoverStyle());
            setHover(level, feature.properties);
          },
          mouseout: function () {
            if (hoveredPath === layer) {
              layer.setStyle(baseStyle(feature));
              hoveredPath = null;
              setHover(level, null);
            }
          },
          click: function () {
            map.fitBounds(layer.getBounds(), { padding: [60, 60], maxZoom: level === 'villages' ? 15 : 12 });
          }
        });
      }
    });
  }
  function buildMeshes(level) {
    meshLayers.forEach(function (l) { map.removeLayer(l); });
    meshLayers = [];
    if (!state.adminVisible) return;
    function addMesh(objName, style) {
      if (!topo.objects[objName]) return;
      var mesh = topojson.mesh(topo, topo.objects[objName], function (a, b) { return a !== b; });
      var l = L.geoJSON(mesh, { renderer: canvasRenderer, style: style, interactive: false }).addTo(map);
      meshLayers.push(l);
    }
    if (level === 'villages') {
      addMesh('towns', { color: 'rgba(40,55,75,0.55)', weight: 1.1 });
      addMesh('counties', { color: 'rgba(15,25,40,0.9)', weight: 1.8 });
    } else if (level === 'towns') {
      addMesh('counties', { color: 'rgba(15,25,40,0.9)', weight: 1.6 });
    }
  }
  function updateLegend(level) {
    var d = activeDomain(level);
    document.getElementById('legendLo').textContent = Number(Math.round(d[0])).toLocaleString('en-US');
    document.getElementById('legendHi').textContent = Number(Math.round(d[1])).toLocaleString('en-US');
  }
  function showLevel(level) {
    state.level = level;
    if (currentLayer) { map.removeLayer(currentLayer); currentLayer = null; }
    hoveredPath = null;
    setHover(level, null);
    updateLegend(level);
    if (state.adminVisible) {
      if (!layerCache[level]) layerCache[level] = buildLayer(level);
      currentLayer = layerCache[level];
      currentLayer.setStyle(baseStyle);
      currentLayer.addTo(map);
    }
    buildMeshes(level);
  }

  // ---------- 控制項 ----------
  document.getElementById('levelSeg').addEventListener('click', function (e) {
    var btn = e.target.closest('button[data-level]');
    if (!btn) return;
    this.querySelectorAll('button').forEach(function (b) { b.classList.remove('active'); });
    btn.classList.add('active');
    showLevel(btn.dataset.level);
  });
  document.getElementById('streetToggle').addEventListener('change', function () {
    if (this.checked) {
      streetLayer.addTo(map); streetLayer.bringToBack();
      document.getElementById('map').classList.remove('no-streets');
    } else {
      map.removeLayer(streetLayer);
      document.getElementById('map').classList.add('no-streets');
    }
  });
  document.getElementById('adminToggle').addEventListener('change', function () {
    state.adminVisible = this.checked;
    showLevel(state.level);
  });
  var opacityVal = document.getElementById('opacityVal');
  document.getElementById('opacitySlider').addEventListener('input', function () {
    state.fillOpacity = this.value / 100;
    opacityVal.textContent = this.value + '%';
    if (currentLayer) currentLayer.setStyle(baseStyle);
  });

  // ---------- 搜尋 ----------
  var searchInput = document.getElementById('searchInput');
  var searchResults = document.getElementById('searchResults');
  function buildSearchIndex() {
    searchIndex = getGeo('villages').features.map(function (f) {
      var p = f.properties;
      return {
        county: countyName(p), town: townName(p), vill: villName(p),
        full: countyName(p) + townName(p) + villName(p), feature: f
      };
    });
  }
  function zoomToFeature(f) {
    var tmp = L.geoJSON(f);
    map.fitBounds(tmp.getBounds(), { padding: [60, 60], maxZoom: 15 });
    setHover('villages', f.properties);
  }
  searchInput.addEventListener('input', function () {
    var q = this.value.trim();
    searchResults.innerHTML = '';
    if (q.length < 1) { searchResults.classList.remove('open'); return; }
    var matches = [];
    for (var i = 0; i < searchIndex.length && matches.length < 20; i++) {
      if (searchIndex[i].full.indexOf(q) !== -1) matches.push(searchIndex[i]);
    }
    if (matches.length === 0) {
      searchResults.innerHTML = '<div class="empty">找不到符合「' + q.replace(/</g, '&lt;') + '」的村里</div>';
    } else {
      matches.forEach(function (m) {
        var b = document.createElement('button');
        b.type = 'button';
        b.innerHTML = '<span class="crumb">' + m.county + ' ' + m.town + '</span>' + m.vill;
        b.addEventListener('click', function () {
          searchResults.classList.remove('open');
          searchInput.value = m.county + m.town + m.vill;
          zoomToFeature(m.feature);
        });
        searchResults.appendChild(b);
      });
    }
    searchResults.classList.add('open');
  });
  document.addEventListener('click', function (e) {
    if (!e.target.closest('.search-wrap')) searchResults.classList.remove('open');
  });

  // ---------- 啟動 ----------
  var loading = document.getElementById('loading');
  var loadingMsg = document.getElementById('loadingMsg');
  setTimeout(function () {
    try {
      showLevel('towns');
      buildSearchIndex();
      var nVill = getGeo('villages').features.length;
      var nTown = topo.objects.towns ? topojson.feature(topo, topo.objects.towns).features.length : 0;
      var nCounty = topo.objects.counties ? topojson.feature(topo, topo.objects.counties).features.length : 0;
      var withData = Object.keys(PRICES.levels.towns.values).length;
      document.getElementById('stats').innerHTML =
        '共 <b>' + nCounty + '</b> 縣市 ・ <b>' + nTown + '</b> 鄉鎮市區 ・ <b>' + nVill + '</b> 村里<br>' +
        '其中 <b>' + withData + '</b> 個鄉鎮市區有' + PRICES.tableLabel + '成交資料<br>' +
        '點擊區塊放大；滑鼠移上去看單價';
      loading.classList.add('hidden');
      setTimeout(function () { if (loading.parentNode) loading.parentNode.removeChild(loading); }, 350);
    } catch (err) {
      loadingMsg.textContent = '';
      loading.querySelector('.spinner').style.display = 'none';
      loading.insertAdjacentHTML('beforeend', '<div class="err">圖層建立失敗：' + err.message + '</div>');
    }
  }, 30);
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
