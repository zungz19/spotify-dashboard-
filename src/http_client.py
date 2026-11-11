"""Lớp gọi HTTP dùng chung: tự thử lại khi lỗi mạng / 429 / 5xx, giới hạn tốc độ
theo từng host và lưu bản gốc (landing) của mọi phản hồi JSON vào data/raw/."""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config
from src.utils import log

_session: requests.Session | None = None
_last_call: dict[str, float] = {}


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        retry = Retry(
            total=5,
            backoff_factor=1.5,                     # 1.5s, 3s, 6s, 12s...
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            respect_retry_after_header=True,
        )
        s.mount("https://", HTTPAdapter(max_retries=retry))
        s.headers.update({"User-Agent": config.USER_AGENT, "Accept-Language": "vi,en;q=0.8"})
        _session = s
    return _session


def _throttle(url: str) -> None:
    host = urlparse(url).netloc
    wait = config.RATE_LIMIT_SECONDS.get(host, 0.2)
    elapsed = time.monotonic() - _last_call.get(host, 0.0)
    if elapsed < wait:
        time.sleep(wait - elapsed)
    _last_call[host] = time.monotonic()


def get(url: str, params: dict | None = None, timeout: int = 30) -> requests.Response:
    _throttle(url)
    resp = session().get(url, params=params, timeout=timeout)
    return resp


def get_text(url: str, params: dict | None = None) -> str:
    resp = get(url, params)
    resp.raise_for_status()
    # Kworb không khai báo charset trong header -> requests đoán ISO-8859-1 và làm
    # vỡ chữ tiếng Việt ("TÃ¬m Em"). Ép đọc theo UTF-8.
    resp.encoding = "utf-8"
    return resp.text


def get_json(url: str, params: dict | None = None, allow_404: bool = False) -> dict | None:
    resp = get(url, params)
    if allow_404 and resp.status_code in (400, 404):
        return None
    resp.raise_for_status()
    return resp.json()


# ----------------------------------------------------------------------------
# Landing zone: lưu nguyên trạng phản hồi để (1) đối chiếu, (2) chạy lại không
# phải gọi API lần nữa (cache), (3) làm bằng chứng "dữ liệu tự thu thập".
# ----------------------------------------------------------------------------
def landing_path(source: str, key: str, ext: str = "json") -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in key)
    path = config.RAW_DIR / source / f"{safe}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def cached_json(source: str, key: str, fetch) -> dict | None:
    """Đọc JSON đã lưu nếu có, nếu chưa thì gọi `fetch()` rồi lưu lại."""
    path = landing_path(source, key)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("File cache hỏng, tải lại: %s", path.name)
    data = fetch()
    # Lưu cả kết quả rỗng ({"_empty": true}) để lần sau không gọi lại vô ích
    path.write_text(json.dumps(data if data is not None else {"_empty": True},
                               ensure_ascii=False), encoding="utf-8")
    return data


def is_empty(payload) -> bool:
    return payload is None or (isinstance(payload, dict) and payload.get("_empty"))
