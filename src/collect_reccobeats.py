"""NGUỒN 2 - ReccoBeats API: thông tin bài hát (ISRC, thời lượng) và đặc trưng âm thanh
(danceability, energy, valence...) tra theo Spotify ID.

Từ 11/2024 Spotify đã đóng endpoint audio-features với ứng dụng mới, ReccoBeats là
nguồn thay thế miễn phí, không cần API key.
Mỗi bài được lưu 2 file JSON trong data/raw/reccobeats/{track,features}/<spotify_id>.json
"""
from __future__ import annotations

import json
import re

import pandas as pd
import requests

import config
from src import db, http_client
from src.utils import log

SID_RE = re.compile(r"track/([A-Za-z0-9]{22})")
FEATURE_KEYS = ["acousticness", "danceability", "energy", "instrumentalness", "key",
                "liveness", "loudness", "mode", "speechiness", "tempo", "valence"]


def _sid(item: dict) -> str | None:
    m = SID_RE.search(item.get("href") or "")
    return m.group(1) if m else None


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _missing(kind: str, ids: list[str]) -> list[str]:
    return [i for i in ids if not http_client.landing_path(f"reccobeats/{kind}", i).exists()]


def _save(kind: str, sid: str, payload) -> None:
    path = http_client.landing_path(f"reccobeats/{kind}", sid)
    path.write_text(json.dumps(payload if payload else {"_empty": True}, ensure_ascii=False),
                    encoding="utf-8")


def _get_batch(endpoint: str, batch: list[str]) -> dict[str, dict]:
    """Gọi endpoint nhận nhiều ID; nếu bị từ chối (400) thì chia đôi lô và thử lại."""
    data = http_client.get_json(f"{config.RECCOBEATS_BASE}/{endpoint}", {"ids": ",".join(batch)},
                                allow_404=True)
    if data is None and len(batch) > 1:
        half = len(batch) // 2
        return {**_get_batch(endpoint, batch[:half]), **_get_batch(endpoint, batch[half:])}
    content = (data or {}).get("content", [])
    found = {sid: item for item in content if (sid := _sid(item))}
    if content and not found:
        # API trả dữ liệu nhưng không có link Spotify để ghép -> định dạng đã đổi, dừng lại để sửa
        sample = http_client.landing_path("reccobeats", "_debug_sample")
        sample.write_text(json.dumps(data, ensure_ascii=False, indent=1)[:20000], encoding="utf-8")
        raise RuntimeError(f"ReccoBeats trả về định dạng lạ, đã lưu mẫu ở {sample}. Hãy gửi file này để sửa code.")
    return found


def _fetch_tracks(ids: list[str]) -> None:
    todo = _missing("track", ids)
    log.info("ReccoBeats: cần tra %d / %d bài (phần còn lại đã có trong cache)", len(todo), len(ids))
    for n, batch in enumerate(_chunks(todo, config.RECCOBEATS_BATCH), 1):
        found = _get_batch("track", batch)
        for sid in batch:
            _save("track", sid, found.get(sid))
        if n % 10 == 0:
            log.info("  ... đã tra %d lô", n)


def _fetch_features(ids: list[str]) -> None:
    """Thử endpoint lấy nhiều bài 1 lần; nếu không được thì gọi từng bài theo ReccoBeats ID."""
    todo = _missing("features", ids)
    log.info("ReccoBeats audio features: cần tra %d bài", len(todo))
    for batch in _chunks(todo, config.RECCOBEATS_BATCH):
        found: dict[str, dict] = {}
        try:
            found = _get_batch("audio-features", batch)
        except (requests.RequestException, RuntimeError) as exc:
            log.warning("Endpoint nhiều bài lỗi (%s) -> chuyển sang gọi từng bài", exc)
        for sid in batch:
            if sid not in found:
                track = _load("track", sid)
                rb_id = (track or {}).get("id")
                if rb_id:
                    item = http_client.get_json(
                        f"{config.RECCOBEATS_BASE}/track/{rb_id}/audio-features", allow_404=True)
                    if item:
                        found[sid] = item
            _save("features", sid, found.get(sid))


def _load(kind: str, sid: str):
    path = http_client.landing_path(f"reccobeats/{kind}", sid)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return None if http_client.is_empty(payload) else payload


def build_raw_tables(con, ids: list[str]) -> dict:
    """Đọc lại toàn bộ file JSON đã lưu -> raw.reccobeats_tracks, raw.reccobeats_features."""
    t_rows, f_rows = [], []
    for sid in ids:
        t = _load("track", sid)
        if t:
            t_rows.append({
                "spotify_id": sid, "rb_id": t.get("id"), "rb_title": t.get("trackTitle"),
                "rb_artists": ", ".join(a.get("name", "") for a in t.get("artists") or []),
                "duration_ms": t.get("durationMs"), "isrc": t.get("isrc"),
                "rb_popularity": t.get("popularity"),
                "available_countries": t.get("availableCountries"),
            })
        f = _load("features", sid)
        if f:
            row = {"spotify_id": sid}
            row.update({k: f.get(k) for k in FEATURE_KEYS})
            f_rows.append(row)
    tracks = pd.DataFrame(t_rows, columns=["spotify_id", "rb_id", "rb_title", "rb_artists",
                                           "duration_ms", "isrc", "rb_popularity",
                                           "available_countries"])
    feats = pd.DataFrame(f_rows, columns=["spotify_id"] + FEATURE_KEYS)
    db.write_df(con, "raw.reccobeats_tracks", tracks)
    db.write_df(con, "raw.reccobeats_features", feats)
    return {"tracks": len(tracks), "features": len(feats), "requested": len(ids)}


def collect(con, ids: list[str]) -> dict:
    ids = sorted(set(ids))
    _fetch_tracks(ids)
    _fetch_features(ids)
    stats = build_raw_tables(con, ids)
    log.info("ReccoBeats: %d/%d bài có thông tin, %d có đặc trưng âm thanh",
             stats["tracks"], stats["requested"], stats["features"])
    return stats
