"""實價登錄統計結果的 HTML 視覺化模組。

以 ``analyzer`` 統計結果產生**單檔 HTML 報告**（內嵌 SVG），純標準
函式庫實作：瀏覽器原生渲染中文，免去 matplotlib 的 CJK 字型安裝
問題，且不引入新依賴。

報告內容：

- **台灣縣市方格地圖**（tile grid map）：22 縣市以近似地理位置的
  格狀排列，顏色深淺呈現單價中位數——不需地理邊界資料即可呈現
  地價分布。
- **鄉鎮市區橫條圖**：成交量前 15 區的單價中位數。
- **月份趨勢折線圖**：單價中位數與筆數兩條時間序列。
- **交易類型橫條圖**：各交易標的筆數。
"""

import argparse
import datetime
import html
import logging
import sqlite3
from pathlib import Path

from twlandprice import analyzer

logger = logging.getLogger(__name__)

# 主表代碼 → 報告標題用名稱。
_TABLE_LABELS = {"sale": "買賣", "presale": "預售屋", "rent": "租賃"}

# 台灣 22 縣市的方格地圖座標（column, row），近似地理相對位置。
_COUNTY_GRID = {
    "連江縣": (0, 0), "臺北市": (2, 0), "基隆市": (3, 0),
    "金門縣": (0, 1), "桃園市": (1, 1), "新北市": (2, 1), "宜蘭縣": (3, 1),
    "新竹市": (0, 2), "新竹縣": (1, 2), "苗栗縣": (2, 2),
    "臺中市": (1, 3), "南投縣": (2, 3), "花蓮縣": (3, 3),
    "彰化縣": (0, 4), "雲林縣": (1, 4), "嘉義縣": (2, 4), "臺東縣": (3, 4),
    "澎湖縣": (0, 5), "嘉義市": (1, 5), "臺南市": (2, 5),
    "高雄市": (1, 6), "屏東縣": (2, 6),
}

# 方格地圖的格子尺寸與間距（px）。
_CELL_W, _CELL_H, _GAP = 110, 64, 8

# 無資料縣市的格子底色。
_EMPTY_FILL = "#e0e0e0"

_CSS = """
body { font-family: "Noto Sans TC", "Microsoft JhengHei", sans-serif;
       margin: 24px auto; max-width: 880px; color: #333; }
h1 { font-size: 24px; }
h2 { font-size: 18px; margin-top: 32px;
     border-left: 4px solid #a50f15; padding-left: 8px; }
.meta { color: #777; font-size: 13px; }
svg { display: block; }
svg text { font-family: inherit; }
"""


def _color_scale(t: float) -> str:
    """將 0～1 的正規化值轉為白→深紅漸層色。

    Args:
        t: 正規化值，0 為最低（近白）、1 為最高（深紅）。

    Returns:
        ``#rrggbb`` 色碼字串。
    """
    t = min(max(t, 0.0), 1.0)
    red = round(255 + (165 - 255) * t)
    green = round(245 + (15 - 245) * t)
    blue = round(240 + (21 - 240) * t)
    return f"#{red:02x}{green:02x}{blue:02x}"


def _format_number(value: object) -> str:
    """將數值格式化為千分位字串，非數值以「—」表示。

    Args:
        value: 統計指標值。

    Returns:
        格式化後字串。
    """
    if isinstance(value, (int, float)):
        return f"{value:,.0f}"
    return "—"


def svg_tile_map(counties: list[dict[str, object]],
                 value_key: str = "單價中位數") -> str:
    """產生台灣縣市方格地圖 SVG，顏色深淺呈現指標高低。

    Args:
        counties: ``analyzer.county_stats`` 的輸出。
        value_key: 著色依據的指標欄位，預設單價中位數。

    Returns:
        SVG 字串；所有縣市皆無數值資料時回傳「（無資料）」段落。
    """
    by_county = {entry["縣市"]: entry for entry in counties}
    values = [entry[value_key] for entry in counties
              if isinstance(entry[value_key], (int, float))]
    if not values:
        return "<p>（無資料）</p>"
    low, high = min(values), max(values)

    max_col = max(col for col, _ in _COUNTY_GRID.values())
    max_row = max(row for _, row in _COUNTY_GRID.values())
    width = _GAP + (max_col + 1) * (_CELL_W + _GAP)
    height = _GAP + (max_row + 1) * (_CELL_H + _GAP)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" '
             f'width="{width}" height="{height}">']
    for county, (col, row) in _COUNTY_GRID.items():
        x = _GAP + col * (_CELL_W + _GAP)
        y = _GAP + row * (_CELL_H + _GAP)
        value = by_county.get(county, {}).get(value_key)
        if isinstance(value, (int, float)):
            ratio = (value - low) / (high - low) if high > low else 1.0
            fill = _color_scale(ratio)
            text_color = "#ffffff" if ratio > 0.55 else "#333333"
        else:
            fill = _EMPTY_FILL
            text_color = "#999999"
        parts.append(
            f'<rect x="{x}" y="{y}" width="{_CELL_W}" height="{_CELL_H}" '
            f'rx="6" fill="{fill}"/>')
        parts.append(
            f'<text x="{x + _CELL_W / 2:g}" y="{y + 26}" '
            f'text-anchor="middle" font-size="14" fill="{text_color}">'
            f'{html.escape(county)}</text>')
        parts.append(
            f'<text x="{x + _CELL_W / 2:g}" y="{y + 48}" '
            f'text-anchor="middle" font-size="12" fill="{text_color}">'
            f'{_format_number(value)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def svg_hbar_chart(rows: list[dict[str, object]], label_key: str,
                   value_key: str) -> str:
    """產生橫條圖 SVG。

    Args:
        rows: 報表記錄清單。
        label_key: 條目標籤欄位名。
        value_key: 數值欄位名（非數值的記錄略過）。

    Returns:
        SVG 字串；無數值資料時回傳「（無資料）」段落。
    """
    data = [(str(row[label_key]), row[value_key]) for row in rows
            if isinstance(row[value_key], (int, float))]
    if not data:
        return "<p>（無資料）</p>"
    peak = max(value for _, value in data)

    bar_h, gap, label_w, chart_w = 22, 6, 170, 420
    width = label_w + chart_w + 110
    height = gap + len(data) * (bar_h + gap)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" '
             f'width="{width}" height="{height}">']
    for index, (label, value) in enumerate(data):
        y = gap + index * (bar_h + gap)
        bar_w = round(chart_w * value / peak) if peak else 0
        parts.append(
            f'<text x="{label_w - 8}" y="{y + 16}" text-anchor="end" '
            f'font-size="13">{html.escape(label)}</text>')
        parts.append(
            f'<rect x="{label_w}" y="{y}" width="{bar_w}" '
            f'height="{bar_h}" fill="#c0392b"/>')
        parts.append(
            f'<text x="{label_w + bar_w + 8}" y="{y + 16}" '
            f'font-size="12" fill="#555">{_format_number(value)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def svg_line_chart(rows: list[dict[str, object]], x_key: str,
                   y_key: str) -> str:
    """產生折線圖 SVG（單一序列）。

    Args:
        rows: 報表記錄清單（依 x 軸順序排列）。
        x_key: x 軸標籤欄位名。
        y_key: 數值欄位名（非數值的記錄略過）。

    Returns:
        SVG 字串；無數值資料時回傳「（無資料）」段落。
    """
    data = [(str(row[x_key]), row[y_key]) for row in rows
            if isinstance(row[y_key], (int, float))]
    if not data:
        return "<p>（無資料）</p>"
    values = [value for _, value in data]
    low, high = min(values), max(values)

    pad_l, pad_r, pad_t, pad_b = 70, 20, 16, 36
    plot_w, plot_h = 560, 180
    width = pad_l + plot_w + pad_r
    height = pad_t + plot_h + pad_b
    step = plot_w / max(len(data) - 1, 1)

    def y_pos(value: float) -> float:
        if high > low:
            return pad_t + plot_h * (1 - (value - low) / (high - low))
        return pad_t + plot_h / 2

    points = [(pad_l + index * step, y_pos(value))
              for index, (_, value) in enumerate(data)]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" '
             f'width="{width}" height="{height}">']
    parts.append(
        f'<text x="{pad_l - 8}" y="{y_pos(high) + 4:g}" text-anchor="end" '
        f'font-size="11" fill="#777">{_format_number(high)}</text>')
    parts.append(
        f'<text x="{pad_l - 8}" y="{y_pos(low) + 4:g}" text-anchor="end" '
        f'font-size="11" fill="#777">{_format_number(low)}</text>')
    if len(points) > 1:
        path = " ".join(f"{x:g},{y:g}" for x, y in points)
        parts.append(f'<polyline points="{path}" fill="none" '
                     f'stroke="#c0392b" stroke-width="2"/>')
    label_every = max(len(data) // 12, 1)
    for index, ((label, _), (x, y)) in enumerate(zip(data, points)):
        parts.append(f'<circle cx="{x:g}" cy="{y:g}" r="3" '
                     f'fill="#c0392b"/>')
        if index % label_every == 0:
            parts.append(
                f'<text x="{x:g}" y="{height - 12}" text-anchor="middle" '
                f'font-size="11" fill="#777">{html.escape(label)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def render_report(conn: sqlite3.Connection, table: str = "sale") -> str:
    """產生完整 HTML 視覺化報告。

    Args:
        conn: 資料庫連線。
        table: 主表名，預設 ``sale``。

    Returns:
        完整 HTML 文件字串。

    Raises:
        sqlite3.OperationalError: 資料庫中無對應資料表。
    """
    counties = analyzer.county_stats(conn, table)
    districts = analyzer.district_stats(conn, table)
    months = analyzer.monthly_trend(conn, table)
    kinds = analyzer.type_stats(conn, table)
    total = sum(entry["筆數"] for entry in counties)
    label = _TABLE_LABELS.get(table, table)
    generated = datetime.datetime.now().isoformat(timespec="seconds")

    sections = [
        "<!DOCTYPE html>",
        '<html lang="zh-Hant"><head><meta charset="utf-8">',
        f"<title>台灣地價視覺化報告（{label}）</title>",
        f"<style>{_CSS}</style></head><body>",
        f"<h1>台灣地價視覺化報告（{label}）</h1>",
        f'<p class="meta">產生時間：{generated}｜資料筆數：{total:,}</p>',
        "<h2>縣市地價分布（單價中位數，元/平方公尺）</h2>",
        svg_tile_map(counties),
        "<h2>成交量前 15 鄉鎮市區（單價中位數，元/平方公尺）</h2>",
        svg_hbar_chart(districts[:15], "鄉鎮市區", "單價中位數"),
        "<h2>月份趨勢（單價中位數，元/平方公尺）</h2>",
        svg_line_chart(months, "月份", "單價中位數"),
        "<h2>月份趨勢（筆數）</h2>",
        svg_line_chart(months, "月份", "筆數"),
        "<h2>交易類型（筆數）</h2>",
        svg_hbar_chart(kinds, "交易標的", "筆數"),
        "</body></html>",
    ]
    return "\n".join(sections)


def write_report(conn: sqlite3.Connection, output: Path,
                 table: str = "sale") -> Path:
    """產生報告並寫入檔案（上層目錄不存在時自動建立）。

    Args:
        conn: 資料庫連線。
        output: 輸出 HTML 檔案路徑。
        table: 主表名，預設 ``sale``。

    Returns:
        實際寫入的檔案路徑。
    """
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(conn, table), encoding="utf-8")
    logger.info("視覺化報告已輸出：%s", output)
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
            logging.FileHandler(log_dir / "visualizer.log",
                                encoding="utf-8"),
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
        description="實價登錄 SQLite 資料 HTML 視覺化報告")
    parser.add_argument("--db", default="data/twlandprice.db",
                        help="SQLite 資料庫路徑（預設 data/twlandprice.db）")
    parser.add_argument("--table", default="sale",
                        choices=sorted(_TABLE_LABELS),
                        help="主表（預設 sale）")
    parser.add_argument("--output", default=None, metavar="PATH",
                        help="輸出 HTML 路徑（預設 output/report_{table}.html）")
    args = parser.parse_args(argv)

    _setup_logging()
    db_path = Path(args.db)
    if not db_path.exists():
        logger.error("資料庫不存在：%s（請先以 --db 旗標擷取資料）", db_path)
        return 1
    output = Path(args.output) if args.output \
        else Path("output") / f"report_{args.table}.html"
    conn = sqlite3.connect(db_path)
    try:
        write_report(conn, output, args.table)
    except sqlite3.OperationalError as error:
        logger.error("無法產生報告（資料表 %s 不存在？）：%s",
                     args.table, error)
        return 1
    finally:
        conn.close()
    print(f"已輸出視覺化報告：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
