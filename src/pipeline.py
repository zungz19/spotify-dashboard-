"""Điều phối toàn bộ pipeline:  thu thập (4 nguồn) -> raw -> staging -> mart -> CSV.

Mọi bước đều ghi nhật ký vào meta.update_log. Dữ liệu API đã tải được cache trong
data/raw/ nên lần chạy sau chỉ tải phần MỚI (bài mới lọt BXH, nghệ sĩ mới...).
"""
from __future__ import annotations

import json
import os
import time
import traceback

import pandas as pd

import config
from src import build_mart, clean, collect_deezer, collect_kworb, collect_musicbrainz, \
    collect_reccobeats, db
from src.utils import log, now_iso, now_utc, parse_int

ALL_STEPS = ["kworb", "reccobeats", "deezer", "musicbrainz", "clean", "mart"]


class PipelineBusy(RuntimeError):
    pass


def _acquire_lock():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if config.LOCK_PATH.exists() and time.time() - config.LOCK_PATH.stat().st_mtime < 2 * 3600:
        raise PipelineBusy("Pipeline đang chạy ở nơi khác (data/.pipeline.lock). Thử lại sau.")
    config.LOCK_PATH.write_text(now_iso())


def _release_lock():
    try:
        os.remove(config.LOCK_PATH)
    except FileNotFoundError:
        pass


def enrich_targets(con) -> pd.DataFrame:
    """Chọn các bài cần làm giàu dữ liệu: toàn bộ BXH Việt Nam + top N toàn cầu."""
    raw = db.query(con, "SELECT market, track_id, artist_main, title, total_streams FROM raw.kworb_totals")
    raw = raw[raw["track_id"].notna()].copy()
    raw["total"] = raw["total_streams"].map(parse_int)
    vn = raw[raw["market"] == "vn"]
    gl = raw[raw["market"] == "global"].sort_values("total", ascending=False).head(config.GLOBAL_ENRICH_LIMIT)
    t = pd.concat([vn, gl]).drop_duplicates("track_id")
    t = t[["track_id", "artist_main", "title"]].rename(columns={"track_id": "spotify_id"})
    t["artist_main"] = t["artist_main"].str.strip()
    return t


def run(mode: str = "full", steps: list[str] | None = None, progress=None) -> list[dict]:
    """mode: 'full' (chạy đầy đủ) | 'update' (dashboard gọi để lấy dữ liệu mới).
    progress: hàm callback(str) để dashboard hiển thị tiến trình."""
    steps = steps or ALL_STEPS
    run_id = now_utc().strftime("%Y%m%d-%H%M%S")
    say = progress or (lambda msg: None)
    results = []
    _acquire_lock()
    try:
        with db.connect() as con:
            for step in steps:
                started, t0 = now_iso(), time.time()
                say(f"Đang chạy bước: {step}")
                log.info("========== %s ==========", step.upper())
                status, detail = "success", {}
                try:
                    if step == "kworb":
                        detail = collect_kworb.collect(con)
                    elif step == "reccobeats":
                        detail = collect_reccobeats.collect(con, enrich_targets(con)["spotify_id"].tolist())
                    elif step == "deezer":
                        tg = enrich_targets(con)
                        rb = db.read_df(con, "raw.reccobeats_tracks")
                        tg = tg.merge(rb[["spotify_id", "isrc"]] if not rb.empty else
                                      pd.DataFrame(columns=["spotify_id", "isrc"]), on="spotify_id", how="left")
                        # Dashboard (mode="update") chỉ thử lại tối đa 50 album thiếu để cập nhật nhanh
                        detail = collect_deezer.collect(con, tg, album_limit=None if mode == "full" else 50)
                    elif step == "musicbrainz":
                        names = enrich_targets(con)["artist_main"].dropna().unique().tolist()
                        detail = collect_musicbrainz.collect(con, names)
                    elif step == "clean":
                        detail = clean.run(con)
                    elif step == "mart":
                        detail = build_mart.run(con)
                        detail["exported"] = len(build_mart.export_csv(con))
                    else:
                        raise ValueError(f"Bước không hợp lệ: {step}")
                except Exception as exc:  # ghi lỗi vào nhật ký rồi dừng
                    status, detail = "failed", {"error": f"{type(exc).__name__}: {exc}"}
                    log.error(traceback.format_exc())
                row = {"run_id": run_id, "mode": mode, "step": step, "started_at": started,
                       "finished_at": now_iso(), "duration_s": round(time.time() - t0, 1),
                       "status": status, "detail": json.dumps(detail, ensure_ascii=False, default=str)}
                db.log_update(con, row)
                results.append(row)
                if status == "failed":
                    say(f"Lỗi ở bước {step}: {detail['error']}")
                    break
    finally:
        _release_lock()
    return results


def last_success(con) -> str | None:
    if not db.table_exists(con, "meta.update_log"):
        return None
    r = con.execute("SELECT MAX(finished_at) FROM meta.update_log "
                    "WHERE step = 'mart' AND status = 'success'").fetchone()
    return r[0] if r else None
