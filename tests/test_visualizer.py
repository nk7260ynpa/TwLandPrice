"""visualizer 模組的單元測試。

以 storage 寫入的合成資料庫驗證 SVG 產生器與 HTML 報告組裝。
"""

import datetime
from pathlib import Path

from twlandprice import storage, visualizer

_SALE_RECORDS = [
    {"鄉鎮市區": "大安區", "交易標的": "房地(土地+建物)",
     "交易年月日": datetime.date(2026, 5, 6),
     "單價元平方公尺": 300000, "總價元": 30000000},
    {"鄉鎮市區": "信義區", "交易標的": "土地",
     "交易年月日": datetime.date(2026, 4, 1),
     "單價元平方公尺": 200000, "總價元": 20000000},
]


def _make_db(tmp_path: Path):
    """建立含臺北市與新北市買賣資料的測試資料庫。"""
    conn = storage.connect(tmp_path / "land.db")
    storage.save_results(conn, {
        "a_lvr_land_a.csv": _SALE_RECORDS,
        "f_lvr_land_a.csv": [{
            "鄉鎮市區": "板橋區", "交易標的": "房地(土地+建物)",
            "交易年月日": datetime.date(2026, 5, 10),
            "單價元平方公尺": 150000, "總價元": 15000000,
        }],
    }, season="113S1")
    return conn


def test_svg_tile_map_colors_data_and_empty():
    """方格地圖：有資料縣市著色、無資料縣市灰色。"""
    counties = [
        {"縣市": "臺北市", "筆數": 2, "單價中位數": 250000},
        {"縣市": "新北市", "筆數": 1, "單價中位數": 150000},
    ]
    svg = visualizer.svg_tile_map(counties)

    assert svg.startswith("<svg")
    assert "臺北市" in svg
    assert "250,000" in svg
    # 全部 22 縣市都有格子；無資料者用灰色與「—」。
    assert svg.count("<rect") == 22
    assert visualizer._EMPTY_FILL in svg
    assert "—" in svg


def test_svg_tile_map_empty():
    """全部縣市皆無數值時應回傳無資料段落。"""
    assert visualizer.svg_tile_map([]) == "<p>（無資料）</p>"


def test_svg_hbar_chart():
    """橫條圖：條寬與數值成比例，略過非數值記錄。"""
    rows = [
        {"鄉鎮市區": "大安區", "單價中位數": 300000},
        {"鄉鎮市區": "信義區", "單價中位數": 150000},
        {"鄉鎮市區": "未知區", "單價中位數": None},
    ]
    svg = visualizer.svg_hbar_chart(rows, "鄉鎮市區", "單價中位數")

    assert svg.count("<rect") == 2
    assert "大安區" in svg
    assert "未知區" not in svg
    assert 'width="420"' in svg
    assert 'width="210"' in svg


def test_svg_line_chart():
    """折線圖：每點一個圓點，多點時有折線。"""
    rows = [
        {"月份": "2026-04", "筆數": 10},
        {"月份": "2026-05", "筆數": 20},
        {"月份": "2026-06", "筆數": 15},
    ]
    svg = visualizer.svg_line_chart(rows, "月份", "筆數")

    assert svg.count("<circle") == 3
    assert "<polyline" in svg
    assert "2026-04" in svg


def test_svg_line_chart_single_point():
    """單一資料點時不畫折線、只畫圓點。"""
    svg = visualizer.svg_line_chart(
        [{"月份": "2026-04", "筆數": 10}], "月份", "筆數")

    assert svg.count("<circle") == 1
    assert "<polyline" not in svg


def test_render_report_sections(tmp_path: Path):
    """完整報告應包含各章節與內嵌 SVG。"""
    conn = _make_db(tmp_path)
    report = visualizer.render_report(conn, "sale")
    conn.close()

    assert "台灣地價視覺化報告（買賣）" in report
    assert "縣市地價分布" in report
    assert "成交量前 15 鄉鎮市區" in report
    assert "月份趨勢" in report
    assert "交易類型" in report
    assert report.count("<svg") == 5
    assert "資料筆數：3" in report


def test_write_report(tmp_path: Path):
    """寫檔時應自動建立上層目錄。"""
    conn = _make_db(tmp_path)
    output = visualizer.write_report(
        conn, tmp_path / "out" / "report.html")
    conn.close()

    assert output.exists()
    assert "<!DOCTYPE html>" in output.read_text(encoding="utf-8")


def test_main_writes_report(tmp_path: Path, capsys):
    """CLI 應輸出報告檔案。"""
    conn = _make_db(tmp_path)
    conn.close()
    output = tmp_path / "report.html"

    exit_code = visualizer.main(["--db", str(tmp_path / "land.db"),
                                 "--output", str(output)])

    assert exit_code == 0
    assert output.exists()
    assert str(output) in capsys.readouterr().out


def test_main_missing_db(tmp_path: Path):
    """資料庫不存在時應回傳 1。"""
    assert visualizer.main(["--db", str(tmp_path / "none.db")]) == 1


def test_main_missing_table(tmp_path: Path):
    """資料表不存在（如未入庫的 presale）時應回傳 1。"""
    conn = _make_db(tmp_path)
    conn.close()

    exit_code = visualizer.main(["--db", str(tmp_path / "land.db"),
                                 "--table", "presale",
                                 "--output", str(tmp_path / "p.html")])

    assert exit_code == 1
