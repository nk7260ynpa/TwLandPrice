"""內政部實價登錄記錄的欄位清理／正規化模組。

將 ``twlandprice.fetcher.parse_land_csv`` 解析出的原始字串記錄轉為適合
儲存與分析的型別：民國日期轉西元 ``datetime.date``、金額轉 ``int``、
面積轉 ``float``（修正前導小數點與浮點精度殘影）、中文樓層轉 ``int``、
複合欄位（交易筆棟數、租賃期間）拆解為衍生欄位、空字串轉 ``None``。
欄名（中文 key）維持不變，衍生欄位沿用官方「``原欄名-子欄名``」慣例
（如 ``建物現況格局-房``）並緊接原欄位之後。

以「欄名規則表」驅動，單一規則表涵蓋主表（買賣 a／預售 b／租賃 c）與
子表（``_land``／``_build``／``_park``）共六種表。明確不轉換的欄位：
``建物分層``（多值複合，如「一層 二層 三層 騎樓」）與``車位所在樓層``
（值域不規則，如「無固定樓層」），僅做空字串轉 ``None``。

容錯策略：空字串與全零日期視為缺值轉 ``None``；樓層特殊值（「全」、
多值等）屬預期值域，原樣保留；其餘轉換失敗的值保留原字串、不中斷
整批處理，並於 ``clean_records`` 結束時每欄彙總一行 warning log。
"""

import datetime
import functools
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 中文格式民國日期，如「96年11月16日」。
_CHINESE_DATE_RE = re.compile(r"^(\d{1,3})年(\d{1,2})月(\d{1,2})日$")
# 面積數值格式（拒絕 nan／inf／科學記號）。
_AREA_RE = re.compile(r"^-?(?:\d+\.?\d*|\.\d+)$")
# 交易筆棟數／租賃筆棟數，如「土地2建物0車位0」。
_COUNTS_RE = re.compile(r"^土地(\d+)建物(\d+)車位(\d+)$")
# 中文數字字元對應值。
_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}


def parse_roc_date(text: str) -> datetime.date | None:
    """解析純數字民國日期字串。

    Args:
        text: 6～7 碼民國年月日字串，如 ``1150506``（民國 115 年 5 月
            6 日）或含前導零的 ``0740528``。

    Returns:
        對應的西元 ``datetime.date``；空字串或全零（如 ``0000000``）
        視為缺值回傳 ``None``。

    Raises:
        ValueError: 非 6～7 碼數字，或月日無效（如 ``1150230``）。
    """
    text = text.strip()
    if not text or (text.isdigit() and int(text) == 0):
        return None
    if not text.isdigit() or not 6 <= len(text) <= 7:
        raise ValueError(f"無效的民國日期：{text!r}")
    year = int(text[:-4]) + 1911
    month = int(text[-4:-2])
    day = int(text[-2:])
    return datetime.date(year, month, day)


def parse_chinese_date(text: str) -> datetime.date | None:
    """解析中文格式民國日期字串。

    Args:
        text: 形如 ``96年11月16日`` 的民國日期字串。

    Returns:
        對應的西元 ``datetime.date``；空字串回傳 ``None``。

    Raises:
        ValueError: 格式不符或月日無效。
    """
    text = text.strip()
    if not text:
        return None
    match = _CHINESE_DATE_RE.match(text)
    if not match:
        raise ValueError(f"無效的中文民國日期：{text!r}")
    year, month, day = (int(group) for group in match.groups())
    return datetime.date(year + 1911, month, day)


def parse_int(text: str) -> int | None:
    """解析整數欄位（屋齡、持分分母／分子、格局數等）。

    Args:
        text: 整數字串。

    Returns:
        ``int``；空字串回傳 ``None``。

    Raises:
        ValueError: 非整數字串。
    """
    text = text.strip()
    if not text:
        return None
    return int(text)


def parse_amount(text: str) -> int | None:
    """解析金額欄位（總價元、總額元、車位價格等）。

    Args:
        text: 整數金額字串（新臺幣元）。

    Returns:
        ``int``；空字串回傳 ``None``。

    Raises:
        ValueError: 非整數字串。
    """
    return parse_int(text)


def parse_area(text: str) -> float | None:
    """解析面積欄位，並修正前導小數點與浮點精度殘影。

    內政部面積精度為小數 2 位，原始資料偶見 ``.40``（缺整數部分）與
    ``81.42999999999999``（上游浮點 repr 殘影），統一以
    ``round(value, 2)`` 正規化。

    Args:
        text: 面積數值字串（平方公尺）。

    Returns:
        ``float``（小數 2 位）；空字串回傳 ``None``。

    Raises:
        ValueError: 非合法十進位數值（含 nan／inf／科學記號）。
    """
    text = text.strip()
    if not text:
        return None
    if not _AREA_RE.match(text):
        raise ValueError(f"無效的面積數值：{text!r}")
    return round(float(text), 2)


def _parse_chinese_numeral(text: str) -> int | None:
    """中文數字轉整數（支援至三位數），無法解析時回傳 ``None``。

    Args:
        text: 中文數字字串，如 ``二十三``、``一百零一``。

    Returns:
        對應整數；含非中文數字字元或結果為 0 時回傳 ``None``。
    """
    result = 0
    current = 0
    for ch in text:
        if ch in _CN_DIGITS:
            current = _CN_DIGITS[ch]
        elif ch == "十":
            result += (current or 1) * 10
            current = 0
        elif ch == "百":
            result += (current or 1) * 100
            current = 0
        elif ch == "零":
            continue
        else:
            return None
    return (result + current) or None


def parse_floor(text: str) -> int | str | None:
    """寬鬆解析樓層欄位（移轉層次、總樓層數等）。

    支援阿拉伯數字（``10``）與中文數字（``二十三層``、``一百零一層``），
    「地下」前綴轉負數（``地下二層``→-2、``地下層``→-1）。「全」、
    多值（``十層，十一層``）、``電梯樓梯間`` 等特殊值屬預期值域，
    原樣回傳字串、不視為錯誤。

    Args:
        text: 樓層字串。

    Returns:
        ``int``（樓層數，地下為負）；無法轉換的特殊值原樣回傳 ``str``；
        空字串回傳 ``None``。
    """
    raw = text.strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    value = raw
    negative = value.startswith("地下")
    if negative:
        value = value[2:]
    if value.endswith(("層", "樓")):
        value = value[:-1]
    if negative and not value:
        return -1
    number = _parse_chinese_numeral(value) if value else None
    if number is None and value.isdigit():
        number = int(value)
    if number is None:
        return raw
    return -number if negative else number


def parse_transaction_counts(text: str) -> tuple[int, int, int] | None:
    """拆解「交易筆棟數／租賃筆棟數」複合欄位。

    Args:
        text: 形如 ``土地2建物0車位0`` 的字串。

    Returns:
        ``(土地, 建物, 車位)`` 三個整數；空字串回傳 ``None``。

    Raises:
        ValueError: 格式不符。
    """
    text = text.strip()
    if not text:
        return None
    match = _COUNTS_RE.match(text)
    if not match:
        raise ValueError(f"無效的筆棟數：{text!r}")
    land, build, park = (int(group) for group in match.groups())
    return (land, build, park)


def parse_lease_period(
        text: str) -> tuple[datetime.date | None, datetime.date | None] | None:
    """拆解「租賃期間」為起迄兩個日期。

    Args:
        text: 形如 ``1150412~1150519`` 的民國日期區間字串；單側可為空
            （如 ``1150412~``）。

    Returns:
        ``(起日, 迄日)``，單側缺值為 ``None``；整欄空字串回傳 ``None``。

    Raises:
        ValueError: 缺少 ``~`` 分隔符，或任一側日期無效。
    """
    text = text.strip()
    if not text:
        return None
    if "~" not in text:
        raise ValueError(f"無效的租賃期間：{text!r}")
    start_text, _, end_text = text.partition("~")
    return (parse_roc_date(start_text), parse_roc_date(end_text))


@dataclass
class CleanStats:
    """清理過程的轉換失敗統計。

    Attributes:
        failures: 欄名 → 轉換失敗次數。
        samples: 欄名 → 首個失敗的原始值樣本。
    """
    failures: dict[str, int] = field(default_factory=dict)
    samples: dict[str, str] = field(default_factory=dict)

    def record(self, field_name: str, value: str) -> None:
        """記錄一筆轉換失敗。

        Args:
            field_name: 欄位名稱。
            value: 轉換失敗的原始值。
        """
        self.failures[field_name] = self.failures.get(field_name, 0) + 1
        self.samples.setdefault(field_name, value)


_Converter = Callable[[str], object]

# 展開規則：精確欄名 → (衍生子欄名, 拆解函式)。原欄保留原字串。
_EXPAND_RULES: dict[str, tuple[tuple[str, ...], _Converter]] = {
    "交易筆棟數": (("土地", "建物", "車位"), parse_transaction_counts),
    "租賃筆棟數": (("土地", "建物", "車位"), parse_transaction_counts),
    "租賃期間": (("起", "迄"), parse_lease_period),
}

# 精確欄名規則：欄名 → 轉換函式。
_EXACT_RULES: dict[str, _Converter] = {
    # 日期欄。
    "交易年月日": parse_roc_date,
    "租賃年月日": parse_roc_date,
    "建築完成年月": parse_roc_date,
    "建築完成日期": parse_chinese_date,
    # 金額欄（「單價元平方公尺」等不符後綴規則，故採精確比對）。
    "總價元": parse_amount,
    "總額元": parse_amount,
    "單價元平方公尺": parse_amount,
    "車位總價元": parse_amount,
    "車位總額元": parse_amount,
    "車位價格": parse_amount,
    # 樓層欄（寬鬆解析，特殊值原樣保留）。
    "移轉層次": parse_floor,
    "租賃層次": parse_floor,
    "總樓層數": parse_floor,
    "總層數": parse_floor,
    # 一般整數欄。
    "建物現況格局-房": parse_int,
    "建物現況格局-廳": parse_int,
    "建物現況格局-衛": parse_int,
    "屋齡": parse_int,
    "權利人持分分母": parse_int,
    "權利人持分分子": parse_int,
}

# 子字串規則（依序比對）：「面積」涵蓋全部面積欄，含無「平方公尺」
# 後綴的「主建物面積」「附屬建物面積」「陽台面積」。
_SUBSTRING_RULES: list[tuple[str, _Converter]] = [
    ("面積", parse_area),
]


@functools.lru_cache(maxsize=None)
def _resolve_rule(key: str) -> tuple[str, object]:
    """決定欄位的清理規則，依「展開 → 精確 → 子字串 → 預設」順序。

    結果以欄名為 key 快取，整批清理時每欄僅需解析一次。

    Args:
        key: 欄位名稱。

    Returns:
        ``(規則種類, 處理器)``，種類為 ``expand``／``convert``／
        ``default``。
    """
    if key in _EXPAND_RULES:
        return ("expand", _EXPAND_RULES[key])
    if key in _EXACT_RULES:
        return ("convert", _EXACT_RULES[key])
    for substring, converter in _SUBSTRING_RULES:
        if substring in key:
            return ("convert", converter)
    return ("default", None)


def clean_record(record: dict[str, str],
                 stats: CleanStats | None = None) -> dict[str, object]:
    """清理單筆記錄，回傳值已正規化的新 dict（中文 key 不變）。

    Args:
        record: ``parse_land_csv`` 解析出的原始字串記錄。
        stats: 轉換失敗統計；``None`` 時不統計。

    Returns:
        值型別為 ``str | int | float | datetime.date | None`` 的新記錄，
        複合欄位的衍生欄位（如 ``交易筆棟數-土地``）緊接原欄位之後。
    """
    cleaned: dict[str, object] = {}
    for key, value in record.items():
        kind, handler = _resolve_rule(key)
        if kind == "expand":
            suffixes, parser = handler
            cleaned[key] = value.strip() or None
            try:
                parsed = parser(value)
            except ValueError:
                if stats is not None:
                    stats.record(key, value)
                parsed = None
            items = parsed if parsed is not None else (None,) * len(suffixes)
            for suffix, item in zip(suffixes, items):
                cleaned[f"{key}-{suffix}"] = item
        elif kind == "convert":
            try:
                cleaned[key] = handler(value)
            except ValueError:
                if stats is not None:
                    stats.record(key, value)
                cleaned[key] = value
        else:
            cleaned[key] = value.strip() or None
    return cleaned


def clean_records(records: list[dict[str, str]]) -> list[dict[str, object]]:
    """清理整批記錄，並彙總記錄轉換失敗的 warning log。

    Args:
        records: 原始字串記錄清單。

    Returns:
        清理後的記錄清單；轉換失敗的值保留原字串，每個欄位彙總一行
        warning log（含失敗筆數與首個樣本值）。
    """
    stats = CleanStats()
    cleaned = [clean_record(record, stats) for record in records]
    for field_name, count in stats.failures.items():
        logger.warning("欄位「%s」有 %d 筆無法轉換，保留原值（樣本：%r）",
                       field_name, count, stats.samples[field_name])
    return cleaned
