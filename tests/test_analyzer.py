"""analyzer 模組的單元測試。

以 storage 寫入的合成資料庫驗證三種報表的聚合、排序與容錯行為。
"""

import datetime
from pathlib import Path

from twlandprice import analyzer, storage

# 合成的清理後買賣記錄：含日期缺值與轉換失敗保留的字串單價。
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

_RENT_RECORDS = [
    {"鄉鎮市區": "萬華區", "交易標的": "租賃房屋",
     "租賃年月日": datetime.date(2026, 4, 12),
     "單價元平方公尺": 800, "總額元": 25000},
    {"鄉鎮市區": "萬華區", "交易標的": "租賃房屋",
     "租賃年月日": datetime.date(2026, 5, 1),
     "單價元平方公尺": 1000, "總額元": 30000},
]


def _make_db(tmp_path: Path):
    """建立含買賣與租賃合成資料的測試資料庫。"""
    conn = storage.connect(tmp_path / "land.db")
    storage.save_results(conn, {
        "a_lvr_land_a.csv": _SALE_RECORDS,
        "a_lvr_land_c.csv": _RENT_RECORDS,
    }, season="113S1")
    return conn


def test_district_stats(tmp_path: Path):
    """地區報表：筆數含全部記錄，數值統計排除字串值。"""
    conn = _make_db(tmp_path)
    rows = analyzer.district_stats(conn, "sale")
    conn.close()

    assert len(rows) == 2
    daan = next(r for r in rows if r["鄉鎮市區"] == "大安區")
    xinyi = next(r for r in rows if r["鄉鎮市區"] == "信義區")
    assert daan["縣市"] == "臺北市"
    assert daan["筆數"] == 2
    assert daan["單價中位數"] == 200000
    assert daan["單價平均"] == 200000
    assert daan["總價中位數"] == 20000000
    # 字串單價不入統計，但計入筆數。
    assert xinyi["筆數"] == 2
    assert xinyi["單價中位數"] == 200000


def test_district_stats_sorted_by_count(tmp_path: Path):
    """地區報表應依筆數遞減、同筆數依名稱排序。"""
    conn = _make_db(tmp_path)
    rows = analyzer.district_stats(conn, "sale")
    conn.close()

    assert [r["鄉鎮市區"] for r in rows] == ["信義區", "大安區"]


def test_monthly_trend(tmp_path: Path):
    """月份報表：依月份遞增，無效日期記錄不納入。"""
    conn = _make_db(tmp_path)
    rows = analyzer.monthly_trend(conn, "sale")
    conn.close()

    assert [r["月份"] for r in rows] == ["2026-04", "2026-05"]
    april, may = rows
    assert april["筆數"] == 1
    assert may["筆數"] == 2
    assert may["單價中位數"] == 200000


def test_type_stats(tmp_path: Path):
    """交易類型報表：依筆數遞減排序。"""
    conn = _make_db(tmp_path)
    rows = analyzer.type_stats(conn, "sale")
    conn.close()

    assert rows[0]["交易標的"] == "房地(土地+建物)"
    assert rows[0]["筆數"] == 3
    assert rows[1] == {"交易標的": "土地", "筆數": 1,
                       "單價中位數": 100000, "單價平均": 100000,
                       "總價中位數": 10000000}


def test_rent_table_uses_own_columns(tmp_path: Path):
    """rent 表應使用租賃年月日與總額元欄位。"""
    conn = _make_db(tmp_path)
    rows = analyzer.monthly_trend(conn, "rent")
    conn.close()

    assert [r["月份"] for r in rows] == ["2026-04", "2026-05"]
    assert rows[0]["總價中位數"] == 25000


def test_format_report():
    """格式化輸出：TSV 首行為欄名，None 顯示為 -。"""
    text = analyzer.format_report(
        [{"月份": "2026-04", "筆數": 1, "單價中位數": None}])

    lines = text.splitlines()
    assert lines[0] == "月份\t筆數\t單價中位數"
    assert lines[1] == "2026-04\t1\t-"
    assert analyzer.format_report([]) == "（無資料）"


def test_main_prints_report(tmp_path: Path, capsys):
    """CLI 應輸出指定報表。"""
    conn = _make_db(tmp_path)
    conn.close()

    exit_code = analyzer.main(
        ["--db", str(tmp_path / "land.db"), "--report", "district"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "大安區" in output
    assert "信義區" in output


def test_main_missing_db(tmp_path: Path):
    """資料庫不存在時應回傳 1。"""
    assert analyzer.main(["--db", str(tmp_path / "none.db")]) == 1
