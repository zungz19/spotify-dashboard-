"""TẦNG MART - ghép các nguồn đã làm sạch thành bảng phân tích + tạo biến phái sinh.

    mart.dim_track         : 1 dòng / bài hát (Spotify ID) - thông tin bài, nghệ sĩ, âm thanh
    mart.dim_artist        : 1 dòng / nghệ sĩ chính
    mart.fact_chart_totals : 1 dòng / (thị trường, bài) - số ngày trụ hạng, đỉnh, stream
    mart.fact_chart_daily  : 1 dòng / (thị trường, ngày, bài) - lịch sử BXH ngày đã thu thập
    mart.track_market      : bảng rộng = fact_chart_totals JOIN dim_track (dashboard dùng)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from src import db
from src.utils import detect_version, has_vietnamese_chars, log


def mood_quadrant(valence, energy):
    if pd.isna(valence) or pd.isna(energy):
        return None
    if valence >= 0.5:
        return "Vui - sôi động" if energy >= 0.5 else "Vui - nhẹ nhàng"
    return "Buồn - mạnh mẽ" if energy >= 0.5 else "Buồn - nhẹ nhàng (ballad)"


def _bucket(series, bins, labels):
    return pd.cut(series, bins=bins, labels=labels, right=False).astype("string")


COLLAB_TITLE_RE = r"(?i)\(\s*(?:feat\.?|ft\.?|with|w/)\s|\bfeat\.\s|\bft\.\s"


def build_dim_track(totals, tracks, feats, dz, artists, daily=None) -> pd.DataFrame:
    # Ưu tiên thông tin tên bài lấy từ BXH Việt Nam (nếu bài có ở cả 2 nơi)
    base = (totals.assign(_o=totals["market"].ne("vn"))
            .sort_values(["_o", "total_streams"], ascending=[True, False])
            .drop_duplicates("track_id")
            [["track_id", "artist_main", "artist_main_id", "title", "featured"]])
    # Trang tổng hợp của Kworb không ghi nghệ sĩ hợp tác -> lấy bổ sung từ BXH ngày
    if daily is not None and not daily.empty:
        fd = (daily[daily["featured"].notna()].sort_values("chart_date")
              .drop_duplicates("track_id", keep="last")[["track_id", "featured"]]
              .rename(columns={"featured": "_feat_daily"}))
        base = base.merge(fd, on="track_id", how="left")
        base["featured"] = base["featured"].astype(object).where(base["featured"].notna(), base["_feat_daily"])
        base = base.drop(columns="_feat_daily")
    tcols = ["spotify_id", "isrc", "duration_ms", "rb_artists"]
    tr = tracks.reindex(columns=tcols) if not tracks.empty else pd.DataFrame(columns=tcols)
    d = base.merge(tr, left_on="track_id", right_on="spotify_id", how="left").drop(columns="spotify_id")
    fcols = ["spotify_id"] + config.AUDIO_FEATURES + ["tempo", "loudness", "key", "mode"]
    d = d.merge(feats[fcols] if not feats.empty else pd.DataFrame(columns=fcols),
                left_on="track_id", right_on="spotify_id", how="left").drop(columns="spotify_id")
    dcols = ["spotify_id", "release_date", "explicit", "dz_bpm", "dz_rank", "genre_main",
             "genre_group", "label", "label_group", "record_type", "match_method"]
    d = d.merge(dz[dcols] if not dz.empty else pd.DataFrame(columns=dcols),
                left_on="track_id", right_on="spotify_id", how="left").drop(columns="spotify_id")
    d = d.merge(artists[["artist_main", "country", "region", "is_vietnamese", "origin_method",
                         "artist_type", "gender", "career_start_year"]],
                on="artist_main", how="left")

    d["duration_min"] = (pd.to_numeric(d["duration_ms"], errors="coerce") / 60000).round(2)
    feat = d["featured"].astype(object).where(d["featured"].notna(), "").astype(str)
    d["n_featured"] = feat.map(lambda s: len([x for x in s.split(";") if x.strip()]))
    # Số nghệ sĩ theo ReccoBeats (danh sách nghệ sĩ chính thức của bản thu trên Spotify)
    rb = d["rb_artists"].astype(object).where(d["rb_artists"].notna(), "").astype(str)
    d["n_artists"] = rb.map(lambda s: len([x for x in s.split(", ") if x.strip()]))
    title = d["title"].astype(object).where(d["title"].notna(), "").astype(str)
    artist = d["artist_main"].astype(object).where(d["artist_main"].notna(), "").astype(str)
    d["is_collab"] = ((d["n_featured"] > 0) | (d["n_artists"] > 1) | artist.str.contains(" & ")
                      | title.str.contains(COLLAB_TITLE_RE, regex=True))
    d = d.drop(columns="rb_artists")
    d["version_type"] = d["title"].map(detect_version)
    d["title_vietnamese"] = d["title"].map(has_vietnamese_chars)
    d["release_date"] = pd.to_datetime(d["release_date"], errors="coerce")
    d["release_year"] = d["release_date"].dt.year.astype("Int64")
    d["release_era"] = _bucket(d["release_year"].astype("float"), [0, 2015, 2020, 2023, 3000],
                               ["Trước 2015", "2015-2019", "2020-2022", "Từ 2023"])
    d["mood"] = [mood_quadrant(v, e) for v, e in zip(d["valence"], d["energy"])]
    d["tempo_bucket"] = _bucket(d["tempo"], [0, 90, 110, 130, 1000],
                                ["Chậm (<90)", "Vừa (90-110)", "Khá nhanh (110-130)", "Nhanh (>=130)"])
    d["duration_bucket"] = _bucket(d["duration_min"], [0, 2.5, 3, 3.5, 4, 4.5, 100],
                                   ["<2.5'", "2.5-3'", "3-3.5'", "3.5-4'", "4-4.5'", ">=4.5'"])
    d["mode_name"] = d["mode"].map({1: "Trưởng (major)", 0: "Thứ (minor)"})
    d["has_features"] = d["energy"].notna()
    d["has_deezer"] = d["match_method"].isin(["isrc", "search"])
    d["region"] = d["region"].fillna("Chưa xác định")
    return d


def build_fact_totals(totals: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    f = totals.copy()
    f["streams_per_day"] = (f["total_streams"] / f["days"]).round(0)
    f["t10_share"] = (f["t10"].fillna(0) / f["days"]).round(3)
    f["is_top10"] = f["peak"] <= 10

    # Bài vẫn đang có mặt trên BXH ngày mới nhất: số ngày trụ hạng CHƯA kết thúc
    # (dữ liệu bị "kiểm duyệt phải" - right-censored) -> không xếp vào nhóm "Lướt qua".
    f["still_charting"] = False
    if not daily.empty:
        latest = daily.groupby("market")["chart_date"].transform("max")
        cur = daily[daily["chart_date"] == latest][["market", "track_id"]].drop_duplicates()
        cur["_cur"] = True
        f = f.merge(cur, on=["market", "track_id"], how="left")
        f["still_charting"] = f["_cur"].fillna(False).astype(bool)
        f = f.drop(columns="_cur")

    # Phạm vi phân tích: toàn bộ BXH Việt Nam + N bài nhiều stream nhất toàn cầu (được làm giàu dữ liệu)
    stream_rank = f.groupby("market")["total_streams"].rank(ascending=False, method="first")
    f["in_scope"] = (f["market"] == "vn") | (stream_rank <= config.GLOBAL_ENRICH_LIMIT)
    f["days_pct"] = f.groupby("market")["days"].rank(pct=True).round(3)
    tiers = []
    for m, g in f[f["is_primary_version"] & f["in_scope"]].groupby("market"):
        q_hi = g["days"].quantile(config.LONG_RUN_QUANTILE)
        q_lo = g["days"].quantile(config.SHORT_RUN_QUANTILE)
        tiers.append({"market": m, "q_hi": q_hi, "q_lo": q_lo})
        log.info("Ngưỡng %s: Lướt qua <= %.0f ngày, Trụ lâu >= %.0f ngày", m, q_lo, q_hi)
    th = pd.DataFrame(tiers)
    f = f.merge(th, on="market", how="left")
    tier = np.select([f["days"] >= f["q_hi"], f["days"] <= f["q_lo"]], ["Trụ lâu", "Lướt qua"], "Trung bình")
    f["success_tier"] = tier
    censored = f["still_charting"] & (f["days"] < f["q_hi"])
    f.loc[censored, "success_tier"] = "Đang trên BXH"
    f["is_long_run"] = np.where(f["success_tier"] == "Đang trên BXH", np.nan,
                                (f["success_tier"] == "Trụ lâu").astype(float))
    f = f.rename(columns={"q_hi": "long_run_threshold", "q_lo": "short_run_threshold"})
    return f


def run(con) -> dict:
    log.info("=== XÂY MART ===")
    totals = db.read_df(con, "staging.chart_totals")
    daily = db.read_df(con, "staging.chart_daily")
    tracks = db.read_df(con, "staging.tracks")
    feats = db.read_df(con, "staging.audio_features")
    dz = db.read_df(con, "staging.deezer")
    artists = db.read_df(con, "staging.artists")

    dim = build_dim_track(totals, tracks, feats, dz, artists, daily)
    fact = build_fact_totals(totals, daily)
    fact_cols = ["market", "snapshot_date", "track_id", "days", "t10", "peak", "peak_times",
                 "peak_streams", "total_streams", "streams_per_day", "t10_share", "is_top10",
                 "still_charting", "days_pct", "long_run_threshold", "short_run_threshold",
                 "success_tier", "is_long_run", "n_versions", "is_primary_version", "in_scope"]
    fact = fact[fact_cols]
    wide = fact.merge(dim, on="track_id", how="left")

    if not daily.empty:
        fd = daily.merge(dim[["track_id", "region", "is_vietnamese", "mood", "genre_group"]],
                         on="track_id", how="left")
    else:
        fd = daily

    db.write_df(con, "mart.dim_track", dim)
    db.write_df(con, "mart.dim_artist", artists)
    db.write_df(con, "mart.fact_chart_totals", fact)
    db.write_df(con, "mart.fact_chart_daily", fd)
    db.write_df(con, "mart.track_market", wide)
    stats = {"dim_track": len(dim), "fact_chart_totals": len(fact), "fact_chart_daily": len(fd),
             "with_features": int(dim["has_features"].sum())}
    log.info("Mart: %s", stats)
    return stats


def export_csv(con) -> list[str]:
    """Xuất bảng mart + báo cáo làm sạch ra CSV (UTF-8 có BOM để Excel đọc đúng tiếng Việt)."""
    config.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for name in ["mart.track_market", "mart.dim_track", "mart.dim_artist", "mart.fact_chart_totals",
                 "mart.fact_chart_daily", "meta.cleaning_report", "meta.update_log"]:
        df = db.read_df(con, name)
        if df.empty:
            continue
        path = config.EXPORT_DIR / f"{name.replace('.', '__')}.csv"
        df.to_csv(path, index=False, encoding="utf-8-sig")
        out.append(path.name)
    return out
