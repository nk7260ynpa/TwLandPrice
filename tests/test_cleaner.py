"""cleaner 模組的單元測試。

涵蓋各值解析函式的邊界情況，以及記錄層 API（衍生欄位、容錯保留
原值、失敗彙總 log）。
"""

import datetime
import logging

import pytest

from twlandprice import cleaner

# 買賣主表（a 表）代表性記錄。
_SALE_RECORD = {
    "鄉鎮市區": "大安區",
    "交易標的": "房地(土地+建物)",
    "交易年月日": "1150506",
    "交易筆棟數": "土地2建物1車位1",
    "移轉層次": "十二層",
    "總樓層數": "二十三層",
    "建築完成年月": "0740528",
    "土地移轉總面積平方公尺": ".40",
    "建物移轉總面積平方公尺": "81.42999999999999",
    "建物現況格局-房": "3",
    "總價元": "12000000",
    "單價元平方公尺": "316797",
    "備註": "",
    "編號": "RPPNMLMKNHLGFDA57DA",
}

# 租賃主表（c 表）代表性記錄。
_RENT_RECORD = {
    "租賃年月日": "1150412",
    "租賃筆棟數": "土地0建物1車位0",
    "租賃期間": "1150412~1160531",
    "租賃層次": "全",
    "總樓層數": "10",
    "總額元": "25000",
}

# 建物子表（_build）代表性記錄。
_BUILD_RECORD = {
    "編號": "RPPNMLLKNHLGFAO68EA",
    "屋齡": "27",
    "建物移轉面積平方公尺": "15.39",
    "建築完成日期": "88年7月13日",
    "總層數": "七層",
    "建物分層": "一層 二層 三層 騎樓",
    "移轉情形": "全筆移轉",
}


def test_parse_roc_date():
    """7 碼與 6 碼民國日期應轉為西元 date。"""
    assert cleaner.parse_roc_date("1150506") == datetime.date(2026, 5, 6)
    assert cleaner.parse_roc_date("0740528") == datetime.date(1985, 5, 28)
    assert cleaner.parse_roc_date("990101") == datetime.date(2010, 1, 1)


def test_parse_roc_date_missing():
    """空字串與全零字串視為缺值。"""
    assert cleaner.parse_roc_date("") is None
    assert cleaner.parse_roc_date("0000000") is None


def test_parse_roc_date_invalid():
    """無效月日與非數字應拋出 ValueError。"""
    with pytest.raises(ValueError):
        cleaner.parse_roc_date("1150230")
    with pytest.raises(ValueError):
        cleaner.parse_roc_date("abc1234")
    with pytest.raises(ValueError):
        cleaner.parse_roc_date("11505061")


def test_parse_chinese_date():
    """中文格式民國日期應轉為西元 date。"""
    assert cleaner.parse_chinese_date("96年11月16日") == \
        datetime.date(2007, 11, 16)
    assert cleaner.parse_chinese_date("88年7月13日") == \
        datetime.date(1999, 7, 13)
    assert cleaner.parse_chinese_date("") is None
    with pytest.raises(ValueError):
        cleaner.parse_chinese_date("96年13月1日")


def test_parse_amount():
    """金額應轉為 int，空字串為 None。"""
    assert cleaner.parse_amount("12000000") == 12000000
    assert cleaner.parse_amount("0") == 0
    assert cleaner.parse_amount("") is None
    with pytest.raises(ValueError):
        cleaner.parse_amount("1.5")


def test_parse_area():
    """面積應轉為 float，修正前導小數點與精度殘影。"""
    assert cleaner.parse_area("6.13") == 6.13
    assert cleaner.parse_area(".40") == 0.4
    assert cleaner.parse_area("0.0") == 0.0
    assert cleaner.parse_area("81.42999999999999") == 81.43
    assert cleaner.parse_area("") is None
    with pytest.raises(ValueError):
        cleaner.parse_area("abc")
    with pytest.raises(ValueError):
        cleaner.parse_area("1e5")


def test_parse_floor_numeric():
    """中文與阿拉伯數字樓層應轉為 int。"""
    assert cleaner.parse_floor("五層") == 5
    assert cleaner.parse_floor("十層") == 10
    assert cleaner.parse_floor("二十三層") == 23
    assert cleaner.parse_floor("一百零一層") == 101
    assert cleaner.parse_floor("10") == 10


def test_parse_floor_basement():
    """「地下」前綴應轉為負數。"""
    assert cleaner.parse_floor("地下二層") == -2
    assert cleaner.parse_floor("地下層") == -1


def test_parse_floor_special():
    """特殊值原樣保留，空字串為 None。"""
    assert cleaner.parse_floor("全") == "全"
    assert cleaner.parse_floor("十層，十一層") == "十層，十一層"
    assert cleaner.parse_floor("電梯樓梯間") == "電梯樓梯間"
    assert cleaner.parse_floor("") is None


def test_parse_transaction_counts():
    """筆棟數應拆解為三個整數。"""
    assert cleaner.parse_transaction_counts("土地2建物0車位0") == (2, 0, 0)
    assert cleaner.parse_transaction_counts("土地12建物1車位1") == (12, 1, 1)
    assert cleaner.parse_transaction_counts("") is None
    with pytest.raises(ValueError):
        cleaner.parse_transaction_counts("土地2建物0")


def test_parse_lease_period():
    """租賃期間應拆解為起迄日期，單側可缺。"""
    assert cleaner.parse_lease_period("1150412~1150519") == \
        (datetime.date(2026, 4, 12), datetime.date(2026, 5, 19))
    assert cleaner.parse_lease_period("1150401~1200331") == \
        (datetime.date(2026, 4, 1), datetime.date(2031, 3, 31))
    assert cleaner.parse_lease_period("1150412~") == \
        (datetime.date(2026, 4, 12), None)
    assert cleaner.parse_lease_period("") is None
    with pytest.raises(ValueError):
        cleaner.parse_lease_period("11504121150519")


def test_clean_record_sale():
    """買賣主表整筆清理：型別轉換與筆棟數衍生欄位。"""
    cleaned = cleaner.clean_record(_SALE_RECORD)

    assert cleaned["交易年月日"] == datetime.date(2026, 5, 6)
    assert cleaned["建築完成年月"] == datetime.date(1985, 5, 28)
    assert cleaned["移轉層次"] == 12
    assert cleaned["總樓層數"] == 23
    assert cleaned["土地移轉總面積平方公尺"] == 0.4
    assert cleaned["建物移轉總面積平方公尺"] == 81.43
    assert cleaned["建物現況格局-房"] == 3
    assert cleaned["總價元"] == 12000000
    assert cleaned["單價元平方公尺"] == 316797
    assert cleaned["備註"] is None
    assert cleaned["鄉鎮市區"] == "大安區"
    assert cleaned["編號"] == "RPPNMLMKNHLGFDA57DA"
    # 原欄保留原字串，衍生欄位為拆解後的整數。
    assert cleaned["交易筆棟數"] == "土地2建物1車位1"
    assert cleaned["交易筆棟數-土地"] == 2
    assert cleaned["交易筆棟數-建物"] == 1
    assert cleaned["交易筆棟數-車位"] == 1


def test_clean_record_derived_key_order():
    """衍生欄位應緊接原欄位之後。"""
    keys = list(cleaner.clean_record(_SALE_RECORD))
    index = keys.index("交易筆棟數")
    assert keys[index + 1:index + 4] == [
        "交易筆棟數-土地", "交易筆棟數-建物", "交易筆棟數-車位"]


def test_clean_record_rent():
    """租賃主表：租賃期間衍生欄位、阿拉伯數字樓層、特殊層次。"""
    cleaned = cleaner.clean_record(_RENT_RECORD)

    assert cleaned["租賃年月日"] == datetime.date(2026, 4, 12)
    assert cleaned["租賃期間"] == "1150412~1160531"
    assert cleaned["租賃期間-起"] == datetime.date(2026, 4, 12)
    assert cleaned["租賃期間-迄"] == datetime.date(2027, 5, 31)
    assert cleaned["租賃筆棟數-建物"] == 1
    assert cleaned["租賃層次"] == "全"
    assert cleaned["總樓層數"] == 10
    assert cleaned["總額元"] == 25000


def test_clean_record_build_subtable():
    """建物子表：中文日期、中文層數，建物分層保留原字串。"""
    cleaned = cleaner.clean_record(_BUILD_RECORD)

    assert cleaned["屋齡"] == 27
    assert cleaned["建物移轉面積平方公尺"] == 15.39
    assert cleaned["建築完成日期"] == datetime.date(1999, 7, 13)
    assert cleaned["總層數"] == 7
    assert cleaned["建物分層"] == "一層 二層 三層 騎樓"
    assert cleaned["移轉情形"] == "全筆移轉"


def test_clean_record_keeps_invalid_value():
    """轉換失敗的值應保留原字串並計入統計。"""
    stats = cleaner.CleanStats()
    cleaned = cleaner.clean_record({"總價元": "面議"}, stats)

    assert cleaned["總價元"] == "面議"
    assert stats.failures == {"總價元": 1}
    assert stats.samples == {"總價元": "面議"}


def test_clean_records_aggregated_warning(caplog):
    """整批清理時，同一欄位的失敗應彙總為一行 warning。"""
    records = [{"總價元": "面議"}, {"總價元": "未知"}]

    with caplog.at_level(logging.WARNING, logger="twlandprice.cleaner"):
        cleaned = cleaner.clean_records(records)

    assert cleaned[0]["總價元"] == "面議"
    assert cleaned[1]["總價元"] == "未知"
    warnings = [r for r in caplog.records if "總價元" in r.getMessage()]
    assert len(warnings) == 1
    assert "2 筆" in warnings[0].getMessage()


def test_clean_records_empty():
    """空清單應回傳空清單。"""
    assert cleaner.clean_records([]) == []
