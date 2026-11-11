"""NGUỒN 3 - Deezer API (không cần key): ngày phát hành, thể loại, hãng đĩa, nhãn
explicit, BPM, thứ hạng Deezer.

Cách ghép với dữ liệu Spotify:
  1. Ưu tiên tra theo mã ISRC (mã quốc tế duy nhất của 1 bản thu) -> khớp chính xác.
  2. Nếu không có ISRC / Deezer không có ISRC đó: tìm theo "nghệ sĩ + tên bài" rồi
     chấm điểm độ giống tên (fuzzy matching), chỉ nhận khi điểm >= 0.85.
"""
from __future__ import annotations

import json
import time
from difflib import SequenceMatcher

import pandas as pd
import requests

import config
from src import db, http_client
from src.utils import log, match_key

MIN_MATCH_SCORE = 0.85


def _call(path: str, params: dict | None = None) -> dict | None:
    """Gọi Deezer; Deezer báo lỗi bằng HTTP 200 + {"error": {...}} nên phải tự xử lý."""
    for attempt in range(4):
        data = http_client.get_json(f"{config.DEEZER_BASE}/{path}", params, allow_404=True)
        if not data:
            return None
        err = data.get("error") if isinstance(data, dict) else None
        if not err:
            return data
        if err.get("code") == 4:              # Quota limit exceeded -> nghỉ rồi thử lại
            time.sleep(5 * (attempt + 1))
            continue
        return None                           # 800 = không tìm thấy, ...
    return None


def similarity(a: str, b: str) -> float:
    a, b = match_key(a), match_key(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _search(artist: str, title: str) -> tuple[dict | None, float]:
    q = f'artist:"{artist}" track:"{title}"'
    data = _call("search", {"q": q, "limit": 10}) or {}
    candidates = data.get("data") or []
    if not candidates:  # thử tìm tự do nếu tìm theo trường không ra
        data = _call("search", {"q": f"{artist} {title}", "limit": 10}) or {}
        candidates = data.get("data") or []
    best, best_score = None, 0.0
    for c in candidates:
        s = 0.6 * similarity(title, c.get("title", "")) + \
            0.4 * similarity(artist, (c.get("artist") or {}).get("name", ""))
        if s > best_score:
            best, best_score = c, s
    return best, best_score


def _match_track(sid: str, isrc: str | None, artist: str, title: str) -> dict:
    if isrc:
        t = _call(f"track/isrc:{isrc}")
        if t and t.get("id"):
            return {"match_method": "isrc", "match_score": 1.0, "track": t}
    cand, score = _search(artist, title)
    if cand and score >= MIN_MATCH_SCORE:
        t = _call(f"track/{cand['id']}") or cand
        return {"match_method": "search", "match_score": round(score, 3), "track": t}
    return {"match_method": "none", "match_score": round(score, 3), "track": None,
            "best_candidate": cand}


def collect(con, tracks: pd.DataFrame, album_limit: int | None = None) -> dict:
    """tracks: DataFrame có cột spotify_id, isrc, artist_main, title."""
    todo = [r for r in tracks.itertuples(index=False)
            if not http_client.landing_path("deezer/track", r.spotify_id).exists()]
    log.info("Deezer: cần ghép %d / %d bài", len(todo), len(tracks))
    for n, r in enumerate(todo, 1):
        isrc = r.isrc if isinstance(r.isrc, str) and r.isrc else None
        res = _match_track(r.spotify_id, isrc, r.artist_main or "", r.title or "")
        res.update({"spotify_id": r.spotify_id, "query_artist": r.artist_main, "query_title": r.title})
        http_client.landing_path("deezer/track", r.spotify_id).write_text(
            json.dumps(res, ensure_ascii=False), encoding="utf-8")
        if n % 200 == 0:
            log.info("  ... Deezer %d/%d", n, len(todo))

    # Album -> thể loại, hãng đĩa (mỗi album chỉ gọi 1 lần)
    album_ids = set()
    for sid in tracks["spotify_id"]:
        res = _load_track(sid)
        t = (res or {}).get("track") or {}
        aid = (t.get("album") or {}).get("id")
        if aid:
            album_ids.add(str(aid))
    todo_albums = [a for a in sorted(album_ids)
                   if not http_client.landing_path("deezer/album", a).exists()]
    if album_limit is not None and len(todo_albums) > album_limit:
        # Chế độ cập nhật nhanh (dashboard): chỉ thử lại một phần album còn thiếu mỗi lần
        log.info("Deezer album: còn thiếu %d album, lần này chỉ tra %d", len(todo_albums), album_limit)
        todo_albums = todo_albums[:album_limit]
    log.info("Deezer album: cần tra %d / %d album", len(todo_albums), len(album_ids))
    failed, streak = 0, 0
    for n, aid in enumerate(todo_albums, 1):
        try:
            data = _call(f"album/{aid}")
        except requests.RequestException as exc:
            # Một số album bị Deezer chặn (403, thường do bản quyền theo khu vực): bỏ qua,
            # KHÔNG lưu cache để lần chạy sau thử lại.
            failed, streak = failed + 1, streak + 1
            log.warning("Bỏ qua album %s: %s", aid, str(exc)[:80])
            if streak >= 25:
                log.warning("Deezer từ chối 25 album liên tiếp - có thể đang bị chặn tạm thời. "
                            "Dừng tra album, chạy lại sau để tra tiếp phần còn thiếu.")
                break
            time.sleep(2)
            continue
        streak = 0
        http_client.landing_path("deezer/album", aid).write_text(
            json.dumps(data if data else {"_empty": True}, ensure_ascii=False), encoding="utf-8")
        if n % 500 == 0:
            log.info("  ... album %d/%d", n, len(todo_albums))
    if failed:
        log.warning("Deezer album: %d album lỗi, đã bỏ qua", failed)

    return build_raw_tables(con, tracks["spotify_id"].tolist())


def _load_track(sid: str):
    p = http_client.landing_path("deezer/track", sid)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def build_raw_tables(con, ids: list[str]) -> dict:
    rows, album_rows, seen_albums = [], [], set()
    for sid in ids:
        res = _load_track(sid)
        if not res:
            continue
        t = res.get("track") or {}
        album = t.get("album") or {}
        rows.append({
            "spotify_id": sid, "match_method": res.get("match_method"),
            "match_score": res.get("match_score"), "deezer_id": t.get("id"),
            "dz_title": t.get("title"), "dz_artist": (t.get("artist") or {}).get("name"),
            "dz_isrc": t.get("isrc"), "dz_duration_s": t.get("duration"),
            "explicit_lyrics": t.get("explicit_lyrics"), "dz_rank": t.get("rank"),
            "dz_bpm": t.get("bpm"), "dz_gain": t.get("gain"),
            "dz_release_date": t.get("release_date"), "album_id": album.get("id"),
            "n_contributors": len(t.get("contributors") or []) or None,
        })
        aid = album.get("id")
        if aid and aid not in seen_albums:
            seen_albums.add(aid)
            p = http_client.landing_path("deezer/album", str(aid))
            a = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
            if a and not http_client.is_empty(a):
                album_rows.append({
                    "album_id": aid, "album_title": a.get("title"),
                    "genres": "|".join(g.get("name", "") for g in (a.get("genres") or {}).get("data", [])),
                    "label": a.get("label"), "album_release_date": a.get("release_date"),
                    "record_type": a.get("record_type"), "nb_tracks": a.get("nb_tracks"),
                })
    tracks = pd.DataFrame(rows)
    albums = pd.DataFrame(album_rows, columns=["album_id", "album_title", "genres", "label",
                                               "album_release_date", "record_type", "nb_tracks"])
    db.write_df(con, "raw.deezer_tracks", tracks)
    db.write_df(con, "raw.deezer_albums", albums)
    by = tracks["match_method"].value_counts().to_dict() if len(tracks) else {}
    log.info("Deezer: %s | %d album", by, len(albums))
    return {"tracks": len(tracks), "albums": len(albums), **{f"match_{k}": v for k, v in by.items()}}
