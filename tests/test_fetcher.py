"""fetcher 模組的單元測試。

測試不依賴實際網路：下載相關測試以 mock 取代 ``requests.get``。
"""

import io
import zipfile
from pathlib import Path
from unittest import mock

from twlandprice import cleaner, fetcher

# 內政部雙標頭 CSV 範例（第一列中文欄名、第二列英文欄名，其後為資料）。
_SAMPLE_CSV = (
    "鄉鎮市區,交易標的,土地位置建物門牌,總價元\n"
    "The villages and towns urban district,transaction sign,"
    "land sector position building sector house number plate,total price NTD\n"
    "大安區,房地(土地+建物),臺北市大安區○○路,12000000\n"
    "信義區,房地(土地+建物),臺北市信義區△△路,8500000\n"
)

# 子表（_park）範例：首欄為英數編號，英文標頭列含空欄。
_SAMPLE_SUBTABLE_CSV = (
    "編號,車位類別,車位價格,車位面積平方公尺,車位所在樓層\n"
    "Serial number,berth category,berth price,berth area square meter,\n"
    "RPTNMLQKMHLGFJE66CB,一樓平面,1500000,13.74,一樓\n"
    "RPQOMLTLMHLGFDC68CB,坡道平面,800000,25.00,地下一層\n"
)

# 欄位定義說明檔（schema-*.csv）範例：單標頭、非成交資料。
_SAMPLE_SCHEMA_CSV = (
    "name,title\n"
    "鄉鎮市區,鄉鎮市區\n"
    "交易標的,交易標的\n"
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


def test_parse_land_csv_subtable(tmp_path: Path):
    """子表首欄為英數編號的資料列不應被誤判為英文標頭跳過。"""
    csv_path = tmp_path / "e_lvr_land_b_park.csv"
    csv_path.write_text(_SAMPLE_SUBTABLE_CSV, encoding="utf-8")

    records = fetcher.parse_land_csv(csv_path)

    assert len(records) == 2
    assert records[0]["編號"] == "RPTNMLQKMHLGFJE66CB"
    assert records[0]["車位類別"] == "一樓平面"
    assert records[1]["車位價格"] == "800000"


def test_parse_land_csv_without_english_header(tmp_path: Path):
    """缺英文標頭列時，第一列資料不應被跳過。"""
    csv_path = tmp_path / "no_eng_header.csv"
    csv_path.write_text(
        "鄉鎮市區,總價元\n大安區,12000000\n信義區,8500000\n",
        encoding="utf-8")

    records = fetcher.parse_land_csv(csv_path)

    assert len(records) == 2
    assert records[0]["鄉鎮市區"] == "大安區"


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
    """整合流程：mock 下載後應正確解壓並解析，並排除 schema 檔。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a_lvr_land_a.csv", _SAMPLE_CSV)
        zf.writestr("e_lvr_land_b_park.csv", _SAMPLE_SUBTABLE_CSV)
        zf.writestr("schema-main.csv", _SAMPLE_SCHEMA_CSV)

    fake_response = mock.Mock()
    fake_response.iter_content.return_value = [buf.getvalue()]
    fake_response.raise_for_status.return_value = None

    with mock.patch.object(fetcher.requests, "get",
                           return_value=fake_response):
        result = fetcher.fetch_and_parse(tmp_path)

    assert "a_lvr_land_a.csv" in result
    assert len(result["a_lvr_land_a.csv"]) == 2
    assert len(result["e_lvr_land_b_park.csv"]) == 2
    assert "schema-main.csv" not in result


def _make_zip_response() -> mock.Mock:
    """組出含單一主表 CSV 的 mock 下載回應。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a_lvr_land_a.csv", _SAMPLE_CSV)
    fake_response = mock.Mock()
    fake_response.iter_content.return_value = [buf.getvalue()]
    fake_response.raise_for_status.return_value = None
    return fake_response


def test_main_with_clean_flag(tmp_path: Path):
    """--clean 旗標應對解析結果執行欄位清理。"""
    with mock.patch.object(fetcher.requests, "get",
                           return_value=_make_zip_response()), \
         mock.patch.object(fetcher.cleaner, "clean_records",
                           side_effect=cleaner.clean_records) as mock_clean:
        exit_code = fetcher.main(["--workdir", str(tmp_path), "--clean"])

    assert exit_code == 0
    assert mock_clean.call_count == 1


def test_main_without_clean_flag(tmp_path: Path):
    """無 --clean 時不應執行清理（預設行為不變）。"""
    with mock.patch.object(fetcher.requests, "get",
                           return_value=_make_zip_response()), \
         mock.patch.object(fetcher.cleaner, "clean_records") as mock_clean:
        exit_code = fetcher.main(["--workdir", str(tmp_path)])

    assert exit_code == 0
    mock_clean.assert_not_called()
