"""清理後實價登錄記錄的 SQLite 儲存模組。

將 ``cleaner.clean_records`` 清理後的記錄寫入 SQLite 資料庫，支援
跨期（多季）累積與後續查詢分析。採標準函式庫 ``sqlite3``，不引入
新依賴；單檔資料庫適合 Docker volume 掛載。

儲存設計：

- **一表種一資料表**：依 CSV 檔名解析縣市代碼與表種，主表對應
  ``sale``（買賣 a）／``presale``（預售 b）／``rent``（租賃 c），
  子表加 ``_land``／``_build``／``_park`` 後綴（如 ``sale_land``）。
  中文欄名直接作為欄位名。
- **metadata 欄位**：每筆記錄附加 ``縣市代碼``、``縣市``、``季別``
  三欄，置於最前，支援跨期累積查詢。
- **批次替換語意**：同（縣市, 季別）的批次重複匯入時，先刪除舊批次
  再寫入，重跑不產生重複資料。
- **動態 schema**：依記錄的 key 建表；後續批次出現新欄位時以
  ``ALTER TABLE`` 補欄，舊資料該欄為 NULL。
- ``datetime.date`` 以 ISO 字串（``YYYY-MM-DD``）儲存。
"""

import datetime
import logging
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# 資料 CSV 檔名規則：{縣市代碼}_lvr_land_{表種}.csv。
_CSV_NAME_RE = re.compile(
    r"^([a-z])_lvr_land_([abc](?:_land|_build|_park)?)\.csv$")

# 主表表種代碼 → 資料表名。
_TABLE_NAMES = {"a": "sale", "b": "presale", "c": "rent"}

# 內政部實價登錄檔名的縣市代碼（同身分證字號縣市碼；l/r/s 為已合併
# 縣市，現行批次資料不再出現）。
_COUNTY_NAMES = {
    "a": "臺北市", "b": "臺中市", "c": "基隆市", "d": "臺南市",
    "e": "高雄市", "f": "新北市", "g": "宜蘭縣", "h": "桃園市",
    "i": "嘉義市", "j": "新竹縣", "k": "苗栗縣", "m": "南投縣",
    "n": "彰化縣", "o": "新竹市", "p": "雲林縣", "q": "嘉義縣",
    "t": "屏東縣", "u": "花蓮縣", "v": "臺東縣", "w": "金門縣",
    "x": "澎湖縣", "z": "連江縣",
}

# 每筆記錄附加的 metadata 欄位（置於最前）。
_META_COLUMNS = ("縣市代碼", "縣市", "季別")

# 未指定季別（抓最新一期）時的批次標記。
DEFAULT_SEASON = "latest"


def parse_csv_name(file_name: str) -> tuple[str, str, str]:
    """解析資料 CSV 檔名，取得縣市與對應資料表。

    Args:
        file_name: CSV 檔名，如 ``a_lvr_land_a.csv``、
            ``f_lvr_land_b_park.csv``。

    Returns:
        ``(縣市代碼, 縣市名稱, 資料表名)``；未知縣市代碼時名稱以
        代碼代替。

    Raises:
        ValueError: 檔名不符合資料 CSV 命名規則。
    """
    match = _CSV_NAME_RE.match(file_name)
    if not match:
        raise ValueError(f"無法解析的檔名：{file_name!r}")
    county_code, kind = match.groups()
    base, _, suffix = kind.partition("_")
    table = _TABLE_NAMES[base] + (f"_{suffix}" if suffix else "")
    county = _COUNTY_NAMES.get(county_code, county_code)
    return (county_code, county, table)


def connect(db_path: Path) -> sqlite3.Connection:
    """開啟（必要時建立）SQLite 資料庫連線。

    Args:
        db_path: 資料庫檔案路徑，上層目錄不存在時自動建立。

    Returns:
        ``sqlite3.Connection`` 連線物件。
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path)


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


def _to_db_value(value: object) -> object:
    """將清理後的值轉為 SQLite 可儲存的型別。

    Args:
        value: ``clean_records`` 輸出的值。

    Returns:
        ``datetime.date`` 轉 ISO 字串，其餘原樣回傳。
    """
    if isinstance(value, datetime.date):
        return value.isoformat()
    return value


def _ensure_table(conn: sqlite3.Connection, table: str,
                  columns: list[str]) -> None:
    """確保資料表存在且涵蓋所有欄位，缺欄時以 ALTER TABLE 補上。

    Args:
        conn: 資料庫連線。
        table: 資料表名。
        columns: 需要存在的欄位名稱清單。
    """
    quoted_table = _quote_identifier(table)
    quoted_columns = ", ".join(_quote_identifier(c) for c in columns)
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {quoted_table} ({quoted_columns})")
    existing = {row[1] for row in
                conn.execute(f"PRAGMA table_info({quoted_table})")}
    for column in columns:
        if column not in existing:
            conn.execute(f"ALTER TABLE {quoted_table} "
                         f"ADD COLUMN {_quote_identifier(column)}")
            logger.info("資料表 %s 新增欄位：%s", table, column)


def save_records(conn: sqlite3.Connection, file_name: str,
                 records: list[dict[str, object]],
                 season: str = DEFAULT_SEASON) -> tuple[str, int]:
    """寫入單一 CSV 的清理後記錄（批次替換）。

    同（縣市, 季別）的既有資料會先刪除再寫入，重複匯入不產生重複。
    ``records`` 為空時不動作（不建表、不刪舊批次）。

    Args:
        conn: 資料庫連線。
        file_name: 來源 CSV 檔名（用於解析縣市與資料表）。
        records: ``clean_records`` 清理後的記錄清單。
        season: 批次季別標記，如 ``113S1``；抓最新一期時用預設值。

    Returns:
        ``(資料表名, 寫入筆數)``。

    Raises:
        ValueError: ``file_name`` 不符合資料 CSV 命名規則。
    """
    county_code, county, table = parse_csv_name(file_name)
    if not records:
        return (table, 0)

    data_columns: dict[str, None] = {}
    for record in records:
        for key in record:
            data_columns.setdefault(key, None)
    columns = list(_META_COLUMNS) + list(data_columns)
    _ensure_table(conn, table, columns)

    quoted_table = _quote_identifier(table)
    conn.execute(
        f"DELETE FROM {quoted_table} WHERE 縣市代碼 = ? AND 季別 = ?",
        (county_code, season))
    column_sql = ", ".join(_quote_identifier(c) for c in columns)
    placeholders = ", ".join("?" for _ in columns)
    rows = [(county_code, county, season)
            + tuple(_to_db_value(record.get(c)) for c in data_columns)
            for record in records]
    conn.executemany(
        f"INSERT INTO {quoted_table} ({column_sql}) VALUES ({placeholders})",
        rows)
    return (table, len(rows))


def save_results(conn: sqlite3.Connection,
                 result: dict[str, list[dict[str, object]]],
                 season: str = DEFAULT_SEASON) -> dict[str, int]:
    """寫入 ``fetch_and_parse``（清理後）的全部結果並 commit。

    Args:
        conn: 資料庫連線。
        result: 以 CSV 檔名為 key 的清理後記錄 dict。
        season: 批次季別標記。

    Returns:
        以資料表名為 key 的寫入筆數彙總；無法解析檔名的項目記
        warning 後略過。
    """
    counts: dict[str, int] = {}
    for file_name in sorted(result):
        try:
            table, count = save_records(conn, file_name,
                                        result[file_name], season)
        except ValueError:
            logger.warning("略過無法解析的檔名：%s", file_name)
            continue
        counts[table] = counts.get(table, 0) + count
    conn.commit()
    total = sum(counts.values())
    logger.info("資料庫寫入完成：%d 個資料表、共 %d 筆（季別：%s）",
                len(counts), total, season)
    return counts


def summarize(conn: sqlite3.Connection) -> dict[str, int]:
    """統計資料庫中各資料表的總筆數。

    Args:
        conn: 資料庫連線。

    Returns:
        以資料表名為 key 的總筆數 dict（含歷次累積的全部批次）。
    """
    tables = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "ORDER BY name")]
    return {table: conn.execute(
        f"SELECT COUNT(*) FROM {_quote_identifier(table)}").fetchone()[0]
        for table in tables}
