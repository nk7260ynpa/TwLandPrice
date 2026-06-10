"""SQLite 實價登錄資料的統計分析模組。

以 ``storage`` 模組產出的 SQLite 資料庫為來源，提供三個維度的統計
報表：**地區**（縣市＋鄉鎮市區）、**時間**（月份）、**交易類型**
（交易標的）。指標為筆數、單價（元/平方公尺）中位數與平均、總價
中位數；中位數以 ``statistics`` 計算（SQLite 無內建）。

與 fetcher 解耦：直接讀資料庫，不需重新下載。cleaner 容錯保留的
字串值不納入數值統計，但仍計入筆數；日期欄非 ISO 格式（轉換失敗
保留原值）的記錄不納入月份分組。
"""

import argparse
import logging
import re
import sqlite3
import statistics
from pathlib import Path

logger = logging.getLogger(__name__)

# 各主表的日期欄與金額欄對應（rent 欄名與買賣／預售不同）。
_TABLE_CONFIG = {
    "sale": {"date": "交易年月日", "price": "單價元平方公尺",
             "total": "總價元"},
    "presale": {"date": "交易年月日", "price": "單價元平方公尺",
                "total": "總價元"},
    "rent": {"date": "租賃年月日", "price": "單價元平方公尺",
             "total": "總額元"},
}

# ISO 日期字串的年月前綴（storage 以 ISO 字串儲存 date）。
_ISO_MONTH_RE = re.compile(r"^(\d{4}-\d{2})-\d{2}$")


def _quote_identifier(name: str) -> str:
    """將表名／欄名安全地引號化，拒絕含雙引號的名稱。

    Args:
        name: 表名或欄名（可為中文）。

    Returns:
        以雙引號包覆的識別字。

    Raises:
        ValueError: 名稱含雙引號或 NUL 字元。
    """
    if '"' in name or "\x00" in name:
        raise ValueError(f"無效的識別字：{name!r}")
    return f'"{name}"'


def _numeric(values: list[object]) -> list[float]:
    """過濾出數值型別的值（排除 cleaner 容錯保留的字串與 None）。

    Args:
        values: 任意值清單。

    Returns:
        僅含 ``int``／``float`` 的清單。
    """
    return [v for v in values if isinstance(v, (int, float))]


def _summary(prices: list[object],
             totals: list[object]) -> dict[str, object]:
    """計算單價與總價的統計指標。

    Args:
        prices: 單價值清單（可含非數值）。
        totals: 總價值清單（可含非數值）。

    Returns:
        含``單價中位數``、``單價平均``、``總價中位數``的 dict，
        無數值資料的指標為 ``None``。
    """
    price_values = _numeric(prices)
    total_values = _numeric(totals)
    return {
        "單價中位數": round(statistics.median(price_values))
                      if price_values else None,
        "單價平均": round(statistics.mean(price_values))
                    if price_values else None,
        "總價中位數": round(statistics.median(total_values))
                      if total_values else None,
    }


def _fetch(conn: sqlite3.Connection, table: str,
           columns: list[str]) -> list[tuple]:
    """自資料表撈取指定欄位的全部資料。

    Args:
        conn: 資料庫連線。
        table: 主表名（``sale``／``presale``／``rent``）。
        columns: 欄位名稱清單。

    Returns:
        資料列 tuple 清單。
    """
    column_sql = ", ".join(_quote_identifier(c) for c in columns)
    return conn.execute(
        f"SELECT {column_sql} FROM {_quote_identifier(table)}").fetchall()


def district_stats(conn: sqlite3.Connection,
                   table: str = "sale") -> list[dict[str, object]]:
    """依縣市＋鄉鎮市區聚合統計。

    Args:
        conn: 資料庫連線。
        table: 主表名，預設 ``sale``。

    Returns:
        每區一筆統計 dict，依筆數遞減（同筆數依縣市、鄉鎮市區）排序。
    """
    config = _TABLE_CONFIG[table]
    rows = _fetch(conn, table,
                  ["縣市", "鄉鎮市區", config["price"], config["total"]])
    groups: dict[tuple[str, str], dict[str, list]] = {}
    for county, district, price, total in rows:
        group = groups.setdefault((county, district),
                                  {"prices": [], "totals": []})
        group["prices"].append(price)
        group["totals"].append(total)
    result = []
    for (county, district), group in groups.items():
        entry = {"縣市": county, "鄉鎮市區": district,
                 "筆數": len(group["prices"])}
        entry.update(_summary(group["prices"], group["totals"]))
        result.append(entry)
    result.sort(key=lambda e: (-e["筆數"], e["縣市"], e["鄉鎮市區"]))
    return result


def monthly_trend(conn: sqlite3.Connection,
                  table: str = "sale") -> list[dict[str, object]]:
    """依月份聚合統計（時間趨勢）。

    日期欄非 ISO 格式（cleaner 轉換失敗保留原值或缺值）的記錄不納入。

    Args:
        conn: 資料庫連線。
        table: 主表名，預設 ``sale``。

    Returns:
        每月一筆統計 dict，依月份遞增排序。
    """
    config = _TABLE_CONFIG[table]
    rows = _fetch(conn, table,
                  [config["date"], config["price"], config["total"]])
    groups: dict[str, dict[str, list]] = {}
    for date_value, price, total in rows:
        match = _ISO_MONTH_RE.match(date_value) \
            if isinstance(date_value, str) else None
        if not match:
            continue
        group = groups.setdefault(match.group(1),
                                  {"prices": [], "totals": []})
        group["prices"].append(price)
        group["totals"].append(total)
    result = []
    for month in sorted(groups):
        group = groups[month]
        entry = {"月份": month, "筆數": len(group["prices"])}
        entry.update(_summary(group["prices"], group["totals"]))
        result.append(entry)
    return result


def type_stats(conn: sqlite3.Connection,
               table: str = "sale") -> list[dict[str, object]]:
    """依交易標的（交易類型）聚合統計。

    Args:
        conn: 資料庫連線。
        table: 主表名，預設 ``sale``。

    Returns:
        每類型一筆統計 dict，依筆數遞減（同筆數依名稱）排序。
    """
    config = _TABLE_CONFIG[table]
    rows = _fetch(conn, table,
                  ["交易標的", config["price"], config["total"]])
    groups: dict[str, dict[str, list]] = {}
    for kind, price, total in rows:
        group = groups.setdefault(kind or "（未填）",
                                  {"prices": [], "totals": []})
        group["prices"].append(price)
        group["totals"].append(total)
    result = []
    for kind, group in groups.items():
        entry = {"交易標的": kind, "筆數": len(group["prices"])}
        entry.update(_summary(group["prices"], group["totals"]))
        result.append(entry)
    result.sort(key=lambda e: (-e["筆數"], e["交易標的"]))
    return result


# 報表名稱 → 報表函式。
_REPORTS = {
    "district": district_stats,
    "monthly": monthly_trend,
    "type": type_stats,
}


def format_report(rows: list[dict[str, object]]) -> str:
    """將報表結果格式化為 TSV 文字（首行為欄名）。

    Args:
        rows: 報表函式的輸出。

    Returns:
        TSV 字串；無資料時回傳「（無資料）」。
    """
    if not rows:
        return "（無資料）"
    headers = list(rows[0])
    lines = ["\t".join(headers)]
    for row in rows:
        lines.append("\t".join(
            "-" if row[h] is None else str(row[h]) for h in headers))
    return "\n".join(lines)


def _setup_logging() -> None:
    """設定 console 與檔案雙輸出的 logging。"""
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "analyzer.log", encoding="utf-8"),
        ],
    )


def main(argv: list[str] | None = None) -> int:
    """命令列進入點。

    Args:
        argv: 命令列參數（預設取自 ``sys.argv``）。

    Returns:
        程式結束碼，成功為 0；資料庫不存在為 1。
    """
    parser = argparse.ArgumentParser(
        description="實價登錄 SQLite 資料統計分析")
    parser.add_argument("--db", default="data/twlandprice.db",
                        help="SQLite 資料庫路徑（預設 data/twlandprice.db）")
    parser.add_argument("--table", default="sale",
                        choices=sorted(_TABLE_CONFIG),
                        help="主表（預設 sale）")
    parser.add_argument("--report", default="district",
                        choices=sorted(_REPORTS),
                        help="報表維度（預設 district）")
    parser.add_argument("--top", type=int, default=10,
                        help="顯示前 N 筆，0 表示全部（預設 10）")
    args = parser.parse_args(argv)

    _setup_logging()
    db_path = Path(args.db)
    if not db_path.exists():
        logger.error("資料庫不存在：%s（請先以 --db 旗標擷取資料）", db_path)
        return 1
    conn = sqlite3.connect(db_path)
    try:
        rows = _REPORTS[args.report](conn, args.table)
    finally:
        conn.close()
    logger.info("報表 %s（%s）：共 %d 組", args.report, args.table, len(rows))
    if args.top > 0:
        rows = rows[:args.top]
    print(format_report(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
