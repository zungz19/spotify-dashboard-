"""NGUỒN 4 - MusicBrainz API: quốc gia, loại nghệ sĩ (cá nhân / nhóm), giới tính,
năm bắt đầu hoạt động. Dùng để xác định nghệ sĩ Việt Nam hay quốc tế (Hàn, Âu-Mỹ...).

MusicBrainz giới hạn 1 request/giây nên chỉ tra nghệ sĩ chính của các bài được làm giàu
dữ liệu (BXH Việt Nam + top toàn cầu): lần đầu khoảng 20-30 phút, các lần sau dùng cache.
"""
from __future__ import annotations

import pandas as pd

import config
from src import db, http_client
from src.utils import log, match_key


def _search_artist(name: str) -> dict | None:
    return http_client.get_json(
        f"{config.MUSICBRAINZ_BASE}/artist",
        {"query": f'artist:"{name}"', "fmt": "json", "limit": 5},
        allow_404=True,
    )


def _pick(name: str, payload: dict | None) -> dict | None:
    """Chọn kết quả khớp: điểm >= MB_MIN_SCORE và tên (hoặc tên sắp xếp/alias) trùng khóa."""
    if not payload:
        return None
    key = match_key(name)
    for a in payload.get("artists", []):
        names = [a.get("name"), a.get("sort-name")] + [x.get("name") for x in a.get("aliases") or []]
        if int(a.get("score", 0)) >= config.MB_MIN_SCORE and key in {match_key(n) for n in names if n}:
            return a
    return None


def collect(con, artist_names: list[str]) -> dict:
    names = sorted({n for n in artist_names if isinstance(n, str) and n.strip()})
    todo = [n for n in names if not http_client.landing_path("musicbrainz/artist", n).exists()]
    log.info("MusicBrainz: cần tra %d / %d nghệ sĩ (~%d phút)", len(todo), len(names),
             round(len(todo) * config.RATE_LIMIT_SECONDS.get("musicbrainz.org", 1.1) / 60))
    for i, n in enumerate(todo, 1):
        http_client.cached_json("musicbrainz/artist", n, lambda n=n: _search_artist(n))
        if i % 50 == 0:
            log.info("  ... MusicBrainz %d/%d", i, len(todo))
    return build_raw_table(con, names)


def build_raw_table(con, names: list[str]) -> dict:
    rows = []
    for n in names:
        p = http_client.landing_path("musicbrainz/artist", n)
        if not p.exists():
            continue
        payload = http_client.cached_json("musicbrainz/artist", n, lambda: None)
        a = None if http_client.is_empty(payload) else _pick(n, payload)
        rows.append({
            "query_name": n,
            "mb_id": a.get("id") if a else None,
            "mb_name": a.get("name") if a else None,
            "mb_score": int(a.get("score", 0)) if a else None,
            "mb_country": a.get("country") if a else None,
            "mb_area": (a.get("area") or {}).get("name") if a else None,
            "mb_begin_area": (a.get("begin-area") or {}).get("name") if a else None,
            "mb_type": a.get("type") if a else None,
            "mb_gender": a.get("gender") if a else None,
            "mb_begin": (a.get("life-span") or {}).get("begin") if a else None,
            "mb_disambiguation": a.get("disambiguation") if a else None,
        })
    df = pd.DataFrame(rows)
    db.write_df(con, "raw.musicbrainz_artists", df)
    matched = int(df["mb_id"].notna().sum()) if len(df) else 0
    log.info("MusicBrainz: khớp được %d / %d nghệ sĩ", matched, len(df))
    return {"artists": len(df), "matched": matched}
