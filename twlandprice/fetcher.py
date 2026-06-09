"""內政部不動產實價登錄開放資料擷取模組。

提供自內政部「不動產成交案件實際資訊資料供應系統」下載批次 ZIP、
解壓縮並解析 CSV 的功能。中央未提供即時 API，僅提供批次 ZIP 下載
（每月 1、11、21 發布），本模組即針對該批次資料設計。

資料來源：https://plvr.land.moi.gov.tw/DownloadOpenData
"""

import argparse
import csv
import logging
import zipfile
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# 內政部開放資料下載端點。
_LATEST_URL = "https://plvr.land.moi.gov.tw/Download"
_SEASON_URL = "https://plvr.land.moi.gov.tw/DownloadSeason"
# 全國 CSV 格式批次檔名。
_DEFAULT_FILE_NAME = "lvr_landcsv.zip"
# 下載逾時秒數。
_TIMEOUT = 60
# 中文字元的 Unicode 範圍（用於判斷標頭列）。
_CJK_START = "一"
_CJK_END = "鿿"


def build_download_url(season: str | None = None,
                       file_name: str = _DEFAULT_FILE_NAME) -> str:
    """組出內政部批次資料下載網址。

    Args:
        season: 民國年與季別，格式如 ``113S1``（民國 113 年第 1 季）。
            為 ``None`` 時下載最新一期資料。
        file_name: 批次檔名，預設為全國 CSV 格式 ``lvr_landcsv.zip``。

    Returns:
        可供下載的完整 URL 字串。
    """
    if season:
        return f"{_SEASON_URL}?season={season}&type=zip&fileName={file_name}"
    return f"{_LATEST_URL}?type=zip&fileName={file_name}"


def download_opendata(dest: Path, season: str | None = None,
                      file_name: str = _DEFAULT_FILE_NAME) -> Path:
    """下載內政部實價登錄批次 ZIP。

    Args:
        dest: ZIP 檔案的存放路徑（含檔名）。
        season: 民國年與季別，``None`` 表示最新一期。
        file_name: 批次檔名。

    Returns:
        實際寫入的 ZIP 檔案路徑。

    Raises:
        requests.HTTPError: 下載回應狀態碼非 2xx 時拋出。
    """
    url = build_download_url(season, file_name)
    logger.info("開始下載實價登錄資料：%s", url)
    response = requests.get(url, timeout=_TIMEOUT, stream=True)
    response.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as fp:
        for chunk in response.iter_content(chunk_size=8192):
            fp.write(chunk)
    logger.info("下載完成，存於：%s（%d bytes）", dest, dest.stat().st_size)
    return dest


def extract_zip(zip_path: Path, dest_dir: Path) -> list[Path]:
    """解壓縮 ZIP，回傳其中所有 CSV 檔案路徑。

    Args:
        zip_path: 待解壓的 ZIP 檔路徑。
        dest_dir: 解壓目的地目錄。

    Returns:
        解壓後所有副檔名為 ``.csv`` 的檔案路徑清單（已排序）。

    Raises:
        zipfile.BadZipFile: ``zip_path`` 非有效 ZIP 檔時拋出。
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    csv_files: list[Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest_dir)
        for name in zf.namelist():
            if name.lower().endswith(".csv"):
                csv_files.append(dest_dir / name)
    logger.info("解壓完成，共 %d 個 CSV 檔", len(csv_files))
    return sorted(csv_files)


def _looks_like_english_header(row: list[str]) -> bool:
    """判斷某列是否為內政部 CSV 的英文欄名標頭列。

    內政部 CSV 第一列為中文欄名、第二列為英文欄名，第三列起才是資料。
    以「該列首欄不含任何中文字元」作為英文標頭的判準。

    Args:
        row: CSV 的一列（欄位字串清單）。

    Returns:
        該列為英文標頭時回傳 ``True``。
    """
    if not row or not row[0]:
        return False
    return all(not (_CJK_START <= ch <= _CJK_END) for ch in row[0])


def parse_land_csv(csv_path: Path) -> list[dict[str, str]]:
    """解析單一筆實價登錄 CSV，回傳記錄清單。

    內政部 CSV 採雙標頭格式（第一列中文欄名、第二列英文欄名）。本函式
    以中文欄名作為 key，並自動跳過英文標頭列與空白列。

    Args:
        csv_path: CSV 檔案路徑。

    Returns:
        每筆成交資料對應一個 dict（key 為中文欄名）。
    """
    with open(csv_path, encoding="utf-8-sig", newline="") as fp:
        reader = csv.reader(fp)
        try:
            headers = next(reader)
        except StopIteration:
            logger.warning("CSV 無內容：%s", csv_path)
            return []
        records: list[dict[str, str]] = []
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            if _looks_like_english_header(row):
                continue
            records.append(dict(zip(headers, row)))
    logger.info("解析 %s：%d 筆", csv_path.name, len(records))
    return records


def fetch_and_parse(workdir: Path, season: str | None = None,
                    file_name: str = _DEFAULT_FILE_NAME
                    ) -> dict[str, list[dict[str, str]]]:
    """完整流程：下載 → 解壓 → 解析。

    Args:
        workdir: 工作目錄，用於存放 ZIP 與解壓結果。
        season: 民國年與季別，``None`` 表示最新一期。
        file_name: 批次檔名。

    Returns:
        以 CSV 檔名為 key、解析後記錄清單為 value 的 dict。
    """
    workdir.mkdir(parents=True, exist_ok=True)
    zip_path = download_opendata(workdir / file_name, season, file_name)
    csv_files = extract_zip(zip_path, workdir / "extracted")
    result: dict[str, list[dict[str, str]]] = {}
    for csv_path in csv_files:
        result[csv_path.name] = parse_land_csv(csv_path)
    total = sum(len(records) for records in result.values())
    logger.info("全部完成：%d 個 CSV、共 %d 筆", len(result), total)
    return result


def _setup_logging() -> None:
    """設定 console 與檔案雙輸出的 logging。"""
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "fetcher.log", encoding="utf-8"),
        ],
    )


def main(argv: list[str] | None = None) -> int:
    """命令列進入點。

    Args:
        argv: 命令列參數（預設取自 ``sys.argv``）。

    Returns:
        程式結束碼，成功為 0。
    """
    parser = argparse.ArgumentParser(
        description="下載並解析內政部實價登錄批次資料")
    parser.add_argument("--season", default=None,
                        help="民國年與季別，如 113S1；省略則抓最新一期")
    parser.add_argument("--workdir", default="data",
                        help="工作目錄（預設 data）")
    parser.add_argument("--file-name", default=_DEFAULT_FILE_NAME,
                        help="批次檔名（預設 lvr_landcsv.zip）")
    args = parser.parse_args(argv)

    _setup_logging()
    result = fetch_and_parse(Path(args.workdir), args.season, args.file_name)
    for name, records in sorted(result.items()):
        print(f"{name}: {len(records)} 筆")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
