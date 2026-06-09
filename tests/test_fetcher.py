"""fetcher 模組的單元測試。

測試不依賴實際網路：下載相關測試以 mock 取代 ``requests.get``。
"""

import io
import zipfile
from pathlib import Path
from unittest import mock

from twlandprice import fetcher

# 內政部雙標頭 CSV 範例（第一列中文欄名、第二列英文欄名，其後為資料）。
_SAMPLE_CSV = (
    "鄉鎮市區,交易標的,土地位置建物門牌,總價元\n"
    "The villages and towns urban district,transaction sign,"
    "land sector position building sector house number plate,total price NTD\n"
    "大安區,房地(土地+建物),臺北市大安區○○路,12000000\n"
    "信義區,房地(土地+建物),臺北市信義區△△路,8500000\n"
)


def test_build_download_url_latest():
    """無 season 時應組出最新一期下載網址。"""
    url = fetcher.build_download_url()
    assert "DownloadSeason" not in url
    assert "fileName=lvr_landcsv.zip" in url


def test_build_download_url_season():
    """指定 season 時應組出歷史季下載網址。"""
    url = fetcher.build_download_url(season="113S1")
    assert "DownloadSeason" in url
    assert "season=113S1" in url


def test_parse_land_csv(tmp_path: Path):
    """應以中文欄名為 key 解析資料，並跳過英文標頭列。"""
    csv_path = tmp_path / "a_lvr_land_a.csv"
    csv_path.write_text(_SAMPLE_CSV, encoding="utf-8")

    records = fetcher.parse_land_csv(csv_path)

    assert len(records) == 2
    assert records[0]["鄉鎮市區"] == "大安區"
    assert records[0]["總價元"] == "12000000"
    assert records[1]["鄉鎮市區"] == "信義區"


def test_parse_land_csv_empty(tmp_path: Path):
    """空 CSV 應回傳空清單。"""
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("", encoding="utf-8")

    assert fetcher.parse_land_csv(csv_path) == []


def test_extract_zip(tmp_path: Path):
    """應解壓並只回傳 CSV 檔案路徑。"""
    zip_path = tmp_path / "lvr.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("a_lvr_land_a.csv", _SAMPLE_CSV)
        zf.writestr("manifest.txt", "ignore me")
    out_dir = tmp_path / "out"

    csv_files = fetcher.extract_zip(zip_path, out_dir)

    assert len(csv_files) == 1
    assert csv_files[0].name == "a_lvr_land_a.csv"
    assert csv_files[0].exists()


def test_download_opendata(tmp_path: Path):
    """download 應將回應內容寫入目的檔（mock 網路）。"""
    fake_response = mock.Mock()
    fake_response.iter_content.return_value = [b"hello", b"world"]
    fake_response.raise_for_status.return_value = None
    dest = tmp_path / "sub" / "lvr.zip"

    with mock.patch.object(fetcher.requests, "get",
                           return_value=fake_response) as mock_get:
        result = fetcher.download_opendata(dest)

    mock_get.assert_called_once()
    assert result == dest
    assert dest.read_bytes() == b"helloworld"


def test_fetch_and_parse(tmp_path: Path):
    """整合流程：mock 下載後應正確解壓並解析。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a_lvr_land_a.csv", _SAMPLE_CSV)

    fake_response = mock.Mock()
    fake_response.iter_content.return_value = [buf.getvalue()]
    fake_response.raise_for_status.return_value = None

    with mock.patch.object(fetcher.requests, "get",
                           return_value=fake_response):
        result = fetcher.fetch_and_parse(tmp_path)

    assert "a_lvr_land_a.csv" in result
    assert len(result["a_lvr_land_a.csv"]) == 2
