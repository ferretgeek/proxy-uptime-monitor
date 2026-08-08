from __future__ import annotations

import ipaddress
import re
from collections import Counter
from typing import Any, Iterable


COUNTRIES: dict[str, str] = {
    "AU": "澳大利亚",
    "BR": "巴西",
    "CA": "加拿大",
    "CH": "瑞士",
    "CN": "中国大陆",
    "DE": "德国",
    "ES": "西班牙",
    "FI": "芬兰",
    "FR": "法国",
    "GB": "英国",
    "HK": "中国香港",
    "ID": "印度尼西亚",
    "IN": "印度",
    "IT": "意大利",
    "JP": "日本",
    "KR": "韩国",
    "MO": "中国澳门",
    "MY": "马来西亚",
    "NL": "荷兰",
    "NO": "挪威",
    "NZ": "新西兰",
    "PH": "菲律宾",
    "PL": "波兰",
    "RU": "俄罗斯",
    "SE": "瑞典",
    "SG": "新加坡",
    "TH": "泰国",
    "TR": "土耳其",
    "TW": "中国台湾",
    "UA": "乌克兰",
    "US": "美国",
    "VN": "越南",
    "ZZ": "未知地区",
}


ALIASES: dict[str, tuple[str, ...]] = {
    "AU": ("澳大利亚", "澳洲", "australia", "sydney", "悉尼"),
    "BR": ("巴西", "brazil", "sao paulo", "圣保罗"),
    "CA": ("加拿大", "canada", "toronto", "多伦多"),
    "CH": ("瑞士", "switzerland", "zurich", "苏黎世"),
    "CN": ("中国大陆", "大陆", "china", "beijing", "shanghai", "北京", "上海"),
    "DE": ("德国", "germany", "frankfurt", "法兰克福"),
    "ES": ("西班牙", "spain", "madrid", "马德里"),
    "FI": ("芬兰", "finland", "helsinki", "赫尔辛基"),
    "FR": ("法国", "france", "paris", "巴黎"),
    "GB": ("英国", "uk", "united kingdom", "london", "伦敦"),
    "HK": ("香港", "hong kong", "hongkong", "hkg"),
    "ID": ("印度尼西亚", "印尼", "indonesia", "jakarta", "雅加达"),
    "IN": ("印度", "india", "mumbai", "孟买"),
    "IT": ("意大利", "italy", "milan", "米兰"),
    "JP": ("日本", "japan", "tokyo", "osaka", "东京", "大阪"),
    "KR": ("韩国", "南韩", "korea", "seoul", "首尔"),
    "MO": ("澳门", "macao", "macau"),
    "MY": ("马来西亚", "大马", "malaysia", "kuala lumpur", "吉隆坡"),
    "NL": ("荷兰", "netherlands", "amsterdam", "阿姆斯特丹"),
    "NO": ("挪威", "norway", "oslo", "奥斯陆"),
    "NZ": ("新西兰", "纽西兰", "new zealand", "auckland", "奥克兰"),
    "PH": ("菲律宾", "philippines", "manila", "马尼拉"),
    "PL": ("波兰", "poland", "warsaw", "华沙"),
    "RU": ("俄罗斯", "俄国", "russia", "moscow", "莫斯科"),
    "SE": ("瑞典", "sweden", "stockholm", "斯德哥尔摩"),
    "SG": ("新加坡", "狮城", "singapore", "singaporean"),
    "TH": ("泰国", "thailand", "bangkok", "曼谷"),
    "TR": ("土耳其", "turkey", "türkiye", "istanbul", "伊斯坦布尔"),
    "TW": ("台湾", "taiwan", "taipei", "台北"),
    "UA": ("乌克兰", "ukraine", "kyiv", "基辅"),
    "US": (
        "美国",
        "美國",
        "united states",
        "usa",
        "los angeles",
        "new york",
        "san jose",
        "洛杉矶",
        "纽约",
        "圣何塞",
    ),
    "VN": ("越南", "vietnam", "hanoi", "河内"),
}


def normalize_country_code(value: str | None) -> str:
    code = (value or "ZZ").strip().upper()
    return code if code in COUNTRIES else "ZZ"


def normalize_detected_country_code(value: str | None) -> str | None:
    code = (value or "").strip().upper()
    return code if re.fullmatch(r"[A-Z]{2}", code) and code != "ZZ" else None


def mask_public_ip(value: str | None) -> str | None:
    try:
        address = ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None
    if not address.is_global:
        return None
    if address.version == 4:
        parts = address.compressed.split(".")
        return f"{parts[0]}.{parts[1]}.*.*"
    parts = address.compressed.split(":")
    return ":".join(parts[:3]) + ":*"


CITY_NAMES: dict[str, str] = {
    "amsterdam": "阿姆斯特丹",
    "bangkok": "曼谷",
    "chicago": "芝加哥",
    "dallas": "达拉斯",
    "frankfurt": "法兰克福",
    "hong kong": "香港",
    "los angeles": "洛杉矶",
    "miami": "迈阿密",
    "new york": "纽约",
    "osaka": "大阪",
    "paris": "巴黎",
    "phoenix": "菲尼克斯",
    "san francisco": "旧金山",
    "san jose": "圣何塞",
    "seattle": "西雅图",
    "seoul": "首尔",
    "singapore": "新加坡",
    "sydney": "悉尼",
    "taipei": "台北",
    "tokyo": "东京",
    "toronto": "多伦多",
}


def _clean_location_label(value: Any) -> str:
    label = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or "")).strip()
    return re.sub(r"\s+", " ", label)[:80]


def resolve_exit_location(
    exit_ip: str | None,
    observations: Iterable[dict[str, Any]],
) -> dict[str, Any] | None:
    masked_ip = mask_public_ip(exit_ip)
    if not masked_ip:
        return None
    normalized: list[dict[str, str]] = []
    for observation in observations:
        code = normalize_detected_country_code(observation.get("country_code"))
        if not code:
            continue
        normalized.append(
            {
                "country_code": code,
                "country": _clean_location_label(observation.get("country")),
                "region": _clean_location_label(observation.get("region")),
                "city": _clean_location_label(observation.get("city")),
            }
        )
    if not normalized:
        return None
    counts = Counter(item["country_code"] for item in normalized)
    country_code, provider_count = counts.most_common(1)[0]
    # 多来源识别至少需要两个独立来源同意。单一来源不覆盖已有地区，
    # 避免某个免费数据库短暂错误造成整页国旗跳变。
    if provider_count < 2:
        return None
    matching = [
        item for item in normalized if item["country_code"] == country_code
    ]
    provider_country = next(
        (item["country"] for item in matching if item["country"]), ""
    )
    country_name = COUNTRIES.get(country_code, provider_country or country_code)
    cities = [item["city"] for item in matching if item["city"]]
    city = Counter(value.casefold() for value in cities).most_common(1)[0][0] if cities else ""
    if city:
        city = next(value for value in cities if value.casefold() == city)
        city = CITY_NAMES.get(city.casefold(), city)
    regions = [item["region"] for item in matching if item["region"]]
    region = regions[0] if regions else ""
    detail = city or region
    if detail.casefold() == country_name.casefold():
        detail = ""
    return {
        "country_code": country_code,
        "region_name": f"{country_name} · {detail}" if detail else country_name,
        "exit_ip_mask": masked_ip,
        "provider_count": provider_count,
    }


def infer_location(*parts: str | None) -> tuple[str, str]:
    text = " ".join(part or "" for part in parts).lower()
    normalized = re.sub(r"[_|/()[\]{}]+", " ", text)
    for code, aliases in ALIASES.items():
        if any(alias.lower() in normalized for alias in aliases):
            return code, COUNTRIES[code]
    tokens = {
        token.upper()
        for token in re.findall(r"(?<![a-z0-9])[a-z]{2}(?![a-z0-9])", normalized)
    }
    for code in COUNTRIES:
        if code != "ZZ" and code in tokens:
            return code, COUNTRIES[code]
    return "ZZ", COUNTRIES["ZZ"]


def country_options(codes: Iterable[str]) -> list[dict[str, str]]:
    normalized = {
        normalize_detected_country_code(code) or "ZZ" for code in codes
    }
    ordered = sorted(
        normalized,
        key=lambda code: (code == "ZZ", COUNTRIES.get(code, code)),
    )
    return [
        {"code": code, "name": COUNTRIES.get(code, code)}
        for code in ordered
    ]
