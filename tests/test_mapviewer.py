"""mapviewer 模組的單元測試。

以 storage 寫入的合成資料庫驗證價格資料組裝、地名正規化與離線 HTML
產生。render_map 測試以精簡假 TopoJSON 注入（避免載入完整圖資），另有
一項 main 端到端測試使用 repo 內的真實 assets。
"""

import datetime
from pathlib import Path

from twlandprice import mapviewer, storage

# 合成買賣記錄：縣市由 CSV 檔名前綴（a → 臺北市）決定。
_SALE_RECORDS = [
    {"鄉鎮市區": "大安區", "交易標的": "房地(土地+建物)",
     "交易年月日": datetime.date(2026, 5, 6),
     "單價元平方公尺": 300000, "總價元": 30000000},
    {"鄉鎮市區": "大安區", "交易標的": "土地",
     "交易年月日": datetime.date(2026, 5, 20),
     "單價元平方公尺": 100000, "總價元": 10000000},
    {"鄉鎮市區": "信義區", "交易標的": "房地(土地+建物)",
     "交易年月日": datetime.date(2026, 4, 1),
     "單價元平方公尺": 200000, "總價元": 20000000},
    {"鄉鎮市區": "信義區", "交易標的": "房地(土地+建物)",
     "交易年月日": None,
     "單價元平方公尺": "轉換失敗保留", "總價元": None},
]

# 精簡假 TopoJSON：render_map 僅將其當字串注入，不解析內容。
_FAKE_TOPO = ('{"type":"Topology","objects":{"counties":{},"towns":{},'
              '"villages":{},"nation":{}},"arcs":[]}')


def _make_db(tmp_path: Path):
    """建立含臺北市買賣資料的測試資料庫。"""
    conn = storage.connect(tmp_path / "land.db")
    storage.save_results(conn, {"a_lvr_land_a.csv": _SALE_RECORDS},
                         season="113S1")
    return conn


def test_normalize():
    """地名正規化：臺→台、去除前後空白。"""
    assert mapviewer._normalize("臺北市") == "台北市"
    assert mapviewer._normalize("臺東縣 ") == "台東縣"
    assert mapviewer._normalize("高雄市") == "高雄市"
    assert mapviewer._normalize("") == ""


def test_percentile():
    """百分位數：線性內插，端點與單一值。"""
    assert mapviewer._percentile([10], 0.95) == 10
    assert mapviewer._percentile([0, 100], 0.0) == 0
    assert mapviewer._percentile([0, 100], 1.0) == 100
    assert mapviewer._percentile([0, 10, 20, 30, 40], 0.5) == 20


def test_load_price_data_structure(tmp_path: Path):
    """熱力資料：含 counties／towns 兩層級，鍵經正規化。"""
    conn = _make_db(tmp_path)
    data = mapviewer.load_price_data(conn, "sale", "median")
    conn.close()

    assert data["metric"] == "median"
    assert data["table"] == "sale"
    assert data["tableLabel"] == "買賣"
    assert data["householdYear"]            # 戶數統計年（民國）
    # 縣市層：臺北市 → 正規化鍵 台北市
    counties = data["levels"]["counties"]["values"]
    assert "台北市" in counties
    assert counties["台北市"]["count"] == 4
    # 鄉鎮市區層：鍵為「縣市/鄉鎮市區」，臺→台
    towns = data["levels"]["towns"]["values"]
    assert "台北市/大安區" in towns
    assert "台北市/信義區" in towns
    daan = towns["台北市/大安區"]
    assert daan["count"] == 2
    assert daan["median"] == 200000


def test_load_price_data_four_metric_domains(tmp_path: Path):
    """每層級含四種指標的色階定義域（median/mean/count/rate）。"""
    conn = _make_db(tmp_path)
    data = mapviewer.load_price_data(conn, "sale", "median")
    conn.close()

    domains = data["levels"]["towns"]["domains"]
    assert set(domains) == {"median", "mean", "count", "rate"}
    # 大安區、信義區單價中位數皆 200000 → 兩端相同
    assert domains["median"] == [200000, 200000]


def test_load_price_data_rate(tmp_path: Path):
    """交易率＝筆數 ÷ 戶數 × 1000（每千戶），戶數取自 households.json。"""
    conn = _make_db(tmp_path)
    data = mapviewer.load_price_data(conn, "sale", "median")
    conn.close()

    households = mapviewer._load_households()["households"]
    daan = data["levels"]["towns"]["values"]["台北市/大安區"]
    expected = round(2 / households["台北市/大安區"] * 1000, 3)
    assert daan["households"] == households["台北市/大安區"]
    assert daan["rate"] == expected
    assert daan["rate"] > 0


def test_load_price_data_mean_metric(tmp_path: Path):
    """metric=mean 時「單價」模式採平均（字串單價不計入）。"""
    conn = _make_db(tmp_path)
    data = mapviewer.load_price_data(conn, "sale", "mean")
    conn.close()

    assert data["metric"] == "mean"
    daan = data["levels"]["towns"]["values"]["台北市/大安區"]
    assert daan["mean"] == 200000


def test_render_map_injects_resources(tmp_path: Path):
    """render_map 應內嵌 Leaflet、資料並替換所有佔位符。"""
    conn = _make_db(tmp_path)
    data = mapviewer.load_price_data(conn, "sale", "median")
    conn.close()

    html = mapviewer.render_map(data, topojson_data=_FAKE_TOPO)

    # 佔位符全部被替換
    for token in ["@@LEAFLET_CSS@@", "@@LEAFLET_JS@@", "@@TOPOJSON_JS@@",
                  "@@TOPO_DATA@@", "@@PRICE_DATA@@", "@@TITLE@@",
                  "@@TABLE_LABEL@@", "@@NO_DATA_FILL@@"]:
        assert token not in html
    # 內嵌資源與資料
    assert "window.__TOPO__" in html
    assert "window.__PRICES__" in html
    assert _FAKE_TOPO in html
    assert "L.map" in html                 # 內嵌的 Leaflet
    assert "topojson" in html              # 內嵌的 topojson-client
    assert "台北市/大安區" in html          # 注入的熱力資料鍵
    assert "台灣地價熱力圖（買賣）" in html
    # 三種熱力呈現方式的切換鈕
    assert 'id="metricSeg"' in html
    assert 'data-metric="count"' in html   # 交易量
    assert 'data-metric="rate"' in html    # 交易率
    assert "交易量" in html and "交易率" in html


def test_render_map_no_script_break(tmp_path: Path):
    """內嵌資源不得含未跳脫的 </script>（會提前關閉腳本）。"""
    conn = _make_db(tmp_path)
    data = mapviewer.load_price_data(conn, "sale", "median")
    conn.close()

    html = mapviewer.render_map(data, topojson_data=_FAKE_TOPO)
    # 正確的 HTML 應只有模板自身的 </script> 收尾標籤，數量等於 <script 開標籤
    assert html.count("<script") == html.count("</script>")


def test_write_map(tmp_path: Path):
    """write_map 寫出檔案並回傳路徑。"""
    conn = _make_db(tmp_path)
    out = tmp_path / "sub" / "map.html"
    result = mapviewer.write_map(conn, out, "sale", "median")
    conn.close()

    assert result == out
    assert out.exists()
    assert "window.__PRICES__" in out.read_text(encoding="utf-8")


def test_main_end_to_end(tmp_path: Path):
    """CLI 以真實 assets 產出離線地圖檔，回傳 0。"""
    conn = _make_db(tmp_path)
    conn.close()
    out = tmp_path / "map_sale.html"

    exit_code = mapviewer.main(
        ["--db", str(tmp_path / "land.db"), "--output", str(out)])

    assert exit_code == 0
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    # 真實圖資內含 7,701 村里之一的屬性鍵
    assert "VILLNAME" in text
    assert "window.__TOPO__" in text


def test_main_missing_db(tmp_path: Path):
    """資料庫不存在時應回傳 1。"""
    assert mapviewer.main(["--db", str(tmp_path / "none.db")]) == 1


def test_main_missing_table(tmp_path: Path):
    """資料表不存在時應回傳 1。"""
    conn = storage.connect(tmp_path / "empty.db")
    conn.close()
    assert mapviewer.main(
        ["--db", str(tmp_path / "empty.db"), "--table", "rent"]) == 1
