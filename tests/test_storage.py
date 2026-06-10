"""storage 模組的單元測試。

涵蓋檔名解析、建表與寫入、批次替換語意、動態 schema 補欄與彙總。
"""

import datetime
from pathlib import Path

import pytest

from twlandprice import storage

# 清理後的買賣主表記錄範例（含 date / int / float / None 型別）。
_CLEANED_RECORDS = [
    {
        "鄉鎮市區": "大安區",
        "交易年月日": datetime.date(2026, 5, 6),
        "總價元": 12000000,
        "土地移轉總面積平方公尺": 6.13,
        "備註": None,
    },
    {
        "鄉鎮市區": "信義區",
        "交易年月日": datetime.date(2026, 4, 20),
        "總價元": 8500000,
        "土地移轉總面積平方公尺": 25.0,
        "備註": "親友間交易",
    },
]


def test_parse_csv_name_main_table():
    """主表檔名應解析出縣市與對應資料表。"""
    assert storage.parse_csv_name("a_lvr_land_a.csv") == \
        ("a", "臺北市", "sale")
    assert storage.parse_csv_name("b_lvr_land_c.csv") == \
        ("b", "臺中市", "rent")


def test_parse_csv_name_subtable():
    """子表檔名應加上對應後綴。"""
    assert storage.parse_csv_name("f_lvr_land_b_park.csv") == \
        ("f", "新北市", "presale_park")
    assert storage.parse_csv_name("e_lvr_land_a_land.csv") == \
        ("e", "高雄市", "sale_land")


def test_parse_csv_name_invalid():
    """不符合命名規則的檔名應拋出 ValueError。"""
    with pytest.raises(ValueError):
        storage.parse_csv_name("schema-main.csv")
    with pytest.raises(ValueError):
        storage.parse_csv_name("lvr_landcsv.zip")


def test_connect_creates_parent_dir(tmp_path: Path):
    """連線時應自動建立資料庫的上層目錄。"""
    db_path = tmp_path / "nested" / "land.db"
    conn = storage.connect(db_path)
    conn.close()
    assert db_path.exists()


def test_save_and_summarize(tmp_path: Path):
    """寫入後應可查回筆數，date 以 ISO 字串儲存。"""
    conn = storage.connect(tmp_path / "land.db")
    counts = storage.save_results(
        conn, {"a_lvr_land_a.csv": _CLEANED_RECORDS}, season="113S1")

    assert counts == {"sale": 2}
    assert storage.summarize(conn) == {"sale": 2}
    row = conn.execute(
        'SELECT 縣市代碼, 縣市, 季別, 交易年月日, 總價元, 備註 '
        'FROM sale WHERE 鄉鎮市區 = ?', ("大安區",)).fetchone()
    assert row == ("a", "臺北市", "113S1", "2026-05-06", 12000000, None)
    conn.close()


def test_save_batch_replace(tmp_path: Path):
    """同（縣市, 季別）重複匯入應替換而非重複累積。"""
    conn = storage.connect(tmp_path / "land.db")
    result = {"a_lvr_land_a.csv": _CLEANED_RECORDS}

    storage.save_results(conn, result, season="113S1")
    storage.save_results(conn, result, season="113S1")

    assert storage.summarize(conn) == {"sale": 2}
    conn.close()


def test_save_accumulates_across_seasons(tmp_path: Path):
    """不同季別與縣市的批次應跨期累積。"""
    conn = storage.connect(tmp_path / "land.db")
    storage.save_results(
        conn, {"a_lvr_land_a.csv": _CLEANED_RECORDS}, season="113S1")
    storage.save_results(
        conn, {"a_lvr_land_a.csv": _CLEANED_RECORDS}, season="113S2")
    storage.save_results(
        conn, {"f_lvr_land_a.csv": _CLEANED_RECORDS}, season="113S1")

    assert storage.summarize(conn) == {"sale": 6}
    seasons = {row[0] for row in
               conn.execute("SELECT DISTINCT 季別 FROM sale")}
    assert seasons == {"113S1", "113S2"}
    conn.close()


def test_save_adds_new_columns(tmp_path: Path):
    """後續批次出現新欄位時應自動補欄，舊資料為 NULL。"""
    conn = storage.connect(tmp_path / "land.db")
    storage.save_results(
        conn, {"a_lvr_land_a.csv": [{"鄉鎮市區": "大安區"}]},
        season="113S1")
    storage.save_results(
        conn, {"f_lvr_land_a.csv": [{"鄉鎮市區": "板橋區", "電梯": "有"}]},
        season="113S1")

    rows = dict(conn.execute("SELECT 鄉鎮市區, 電梯 FROM sale"))
    assert rows == {"大安區": None, "板橋區": "有"}
    conn.close()


def test_save_results_skips_unparsable_name(tmp_path: Path, caplog):
    """無法解析的檔名應記 warning 並略過，不中斷整批。"""
    conn = storage.connect(tmp_path / "land.db")
    result = {
        "a_lvr_land_a.csv": _CLEANED_RECORDS,
        "weird_file.csv": [{"欄": "值"}],
    }

    with caplog.at_level("WARNING", logger="twlandprice.storage"):
        counts = storage.save_results(conn, result)

    assert counts == {"sale": 2}
    assert any("weird_file.csv" in r.getMessage() for r in caplog.records)
    conn.close()


def test_save_empty_records(tmp_path: Path):
    """空記錄清單應回報 0 筆且不建表。"""
    conn = storage.connect(tmp_path / "land.db")
    counts = storage.save_results(conn, {"a_lvr_land_a.csv": []})

    assert counts == {"sale": 0}
    assert storage.summarize(conn) == {}
    conn.close()
