"""Các hàm tiện ích dùng chung: chuẩn hóa chữ, nhận diện tiếng Việt, đọc số..."""
from __future__ import annotations

import logging
import re
import unicodedata
import sys
from datetime import datetime, timezone

# Console Windows đôi khi không in được tiếng Việt -> ép UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pipeline")


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def now_iso() -> str:
    return now_utc().isoformat()


def nfc(text) -> str | None:
    """Chuẩn hóa Unicode về dạng NFC.

    Cùng một chữ "ệ" có thể được lưu bằng 1 ký tự dựng sẵn hoặc 2-3 ký tự tổ hợp
    (e + dấu mũ + dấu nặng). Nếu không chuẩn hóa, "Chuyện" và "Chuyện" bị coi là
    hai chuỗi khác nhau khi so khớp / gom nhóm.
    """
    if text is None:
        return None
    text = unicodedata.normalize("NFC", str(text))
    text = text.replace(" ", " ")          # khoảng trắng không ngắt dòng
    text = re.sub(r"[​-‏﻿]", "", text)  # ký tự vô hình
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


# Các chữ cái chỉ có trong tiếng Việt (không có trong tiếng Pháp / Tây Ban Nha...)
_VN_SPECIFIC = set("ăâđêôơưĂÂĐÊÔƠƯ")
_VN_TONES = set(
    "ạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ"
    "ẠẢẤẦẨẪẬẮẰẲẴẶẸẺẼẾỀỂỄỆỈỊỌỎỐỒỔỖỘỚỜỞỠỢỤỦỨỪỬỮỰỲỴỶỸ"
)


def has_vietnamese_chars(text) -> bool:
    """True nếu chuỗi chứa ký tự đặc trưng tiếng Việt (ă â đ ê ô ơ ư hoặc dấu thanh)."""
    if not text:
        return False
    text = unicodedata.normalize("NFC", str(text))
    return any(ch in _VN_SPECIFIC or ch in _VN_TONES for ch in text)


def strip_accents(text) -> str:
    if text is None:
        return ""
    text = unicodedata.normalize("NFD", str(text))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.replace("đ", "d").replace("Đ", "D")


def match_key(text) -> str:
    """Khóa so khớp: bỏ dấu, chữ thường, bỏ ký tự đặc biệt và phần (feat...)."""
    text = strip_accents(nfc(text) or "").lower()
    text = re.sub(r"\((feat|ft|with|w/)[^)]*\)", " ", text)
    text = re.sub(r"\[(feat|ft|with)[^\]]*\]", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_NUM_RE = re.compile(r"[-+]?\d[\d,\.]*")


def parse_int(value) -> int | None:
    """'1,139,605' -> 1139605 ; '+3' -> 3 ; '-24,911' -> -24911 ; '=' / 'NEW' / '' -> None."""
    if value is None:
        return None
    s = str(value).strip().replace("−", "-")
    m = _NUM_RE.search(s)
    if not m:
        return None
    digits = m.group(0).replace(",", "")
    try:
        return int(float(digits))
    except ValueError:
        return None


VERSION_PATTERNS = {
    "remix": r"\bremix\b|\bmix\b|\bedit\b",
    "live": r"\blive\b",
    "acoustic": r"\bacoustic\b|\bunplugged\b",
    "speed_change": r"sped up|speed up|slowed|nightcore|reverb",
    "lofi": r"lo-?fi",
    "instrumental": r"\binstrumental\b|\bbeat\b|\bkaraoke\b",
    "remake": r"\bcover\b|\bremake\b|\bversion\b|\bver\.",
}


def detect_version(title) -> str:
    """Phân loại phiên bản bài hát dựa trên tên (remix, live, acoustic, sped up...)."""
    t = strip_accents(title or "").lower()
    for name, pat in VERSION_PATTERNS.items():
        if re.search(pat, t):
            return name
    return "original"
