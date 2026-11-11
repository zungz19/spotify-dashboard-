"""TẦNG STAGING - làm sạch, ép kiểu, kiểm tra chéo giữa các nguồn.

Mỗi quy tắc làm sạch được ghi lại (số dòng trước/sau/bị ảnh hưởng) vào
meta.cleaning_report để trình bày trong báo cáo và trên dashboard.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

import config
from src import db
from src.utils import has_vietnamese_chars, log, match_key, nfc, parse_int, now_utc


class Report:
    """Gom các bước làm sạch: bảng, quy tắc, số dòng trước, sau, số dòng bị ảnh hưởng."""

    def __init__(self):
        self.rows: list[dict] = []

    def add(self, table, step, before, after, affected=None, note=""):
        affected = before - after if affected is None else affected
        self.rows.append({"table_name": table, "step": step, "rows_before": int(before),
                          "rows_after": int(after), "rows_affected": int(affected), "note": note})
        if affected:
            log.info("  [%s] %s: %d dòng", table, step, affected)


def _text_cols(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = df[c].map(lambda v: nfc(v) if isinstance(v, str) else None)
    return df


# ----------------------------------------------------------------------------
# 1. Bảng xếp hạng tổng hợp (Kworb totals)
# ----------------------------------------------------------------------------
def clean_chart_totals(raw: pd.DataFrame, rep: Report) -> pd.DataFrame:
    T = "chart_totals"
    df = raw.copy()
    n0 = len(df)
    rep.add(T, "Dữ liệu thô từ Kworb (VN + toàn cầu)", n0, n0, 0)

    df = df[df["track_id"].notna() & df["track_id"].str.fullmatch(r"[A-Za-z0-9]{22}", na=False)]
    rep.add(T, "Bỏ dòng không có Spotify track ID hợp lệ", n0, len(df))

    df = _text_cols(df, ["artist_main", "title", "featured", "artist_title"])
    changed = int((raw.loc[df.index, "title"].fillna("") != df["title"].fillna("")).sum())
    rep.add(T, "Chuẩn hóa Unicode NFC + bỏ khoảng trắng thừa ở tên bài/nghệ sĩ",
            len(df), len(df), changed, "Ký tự tiếng Việt dạng tổ hợp -> dựng sẵn")

    for c in ["days", "t10", "peak", "peak_streams", "total_streams"]:
        df[c] = df[c].map(parse_int).astype("Int64")
    df["peak_times"] = df["peak_times"].map(parse_int).astype("Int64")
    n = len(df)
    df = df[df["days"].notna() & df["total_streams"].notna() & df["peak"].notna()]
    rep.add(T, "Chuyển chuỗi '1,139,605' / '(x802)' sang số; bỏ dòng không đọc được số", n, len(df))

    n = len(df)
    bad = (df["days"] <= 0) | (df["peak"] < 1) | (df["peak"] > 200) | \
          (df["t10"].fillna(0) > df["days"]) | (df["peak_streams"].fillna(0) > df["total_streams"])
    df = df[~bad]
    rep.add(T, "Kiểm tra logic: 1<=đỉnh<=200, ngày top10 <= số ngày, stream đỉnh <= tổng", n, len(df))

    n = len(df)
    df = df.sort_values("total_streams", ascending=False).drop_duplicates(["market", "track_id"])
    rep.add(T, "Khử trùng lặp (thị trường, track_id)", n, len(df))

    # Cùng 1 bài nhưng nhiều Spotify ID (bản single / bản trong album / bản tái phát hành)
    df["song_key"] = df["artist_main"].map(match_key) + " || " + df["title"].map(match_key)
    df["n_versions"] = df.groupby(["market", "song_key"])["track_id"].transform("count")
    df["is_primary_version"] = ~df.duplicated(["market", "song_key"], keep="first")  # đã sắp theo stream
    rep.add(T, "Đánh dấu bài trùng tên khác ID (giữ bản nhiều stream nhất làm bản chính)",
            len(df), len(df), int((~df["is_primary_version"]).sum()),
            "Không xóa, chỉ loại khỏi phân tích bằng cờ is_primary_version")

    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"], errors="coerce").dt.date
    keep = ["market", "snapshot_date", "track_id", "artist_main", "artist_main_id", "title",
            "featured", "featured_ids", "days", "t10", "peak", "peak_times", "peak_streams",
            "total_streams", "song_key", "n_versions", "is_primary_version"]
    return df[keep].reset_index(drop=True)


# ----------------------------------------------------------------------------
# 2. BXH theo ngày (snapshot)
# ----------------------------------------------------------------------------
def clean_chart_daily(raw: pd.DataFrame, rep: Report) -> pd.DataFrame:
    T = "chart_daily"
    if raw.empty:
        return raw
    df = raw.copy()
    n0 = len(df)
    df = df[df["track_id"].notna()]
    df = _text_cols(df, ["artist_main", "title", "featured"])
    for c in ["pos", "days", "peak", "streams", "streams_change", "streams_7day",
              "streams_7day_change", "total_streams"]:
        df[c] = df[c].map(parse_int).astype("Int64")
    df["chart_date"] = pd.to_datetime(df["chart_date"], errors="coerce")
    df = df[df["pos"].notna() & df["chart_date"].notna()]
    rep.add(T, "Ép kiểu số/ngày, bỏ dòng thiếu vị trí hoặc ngày", n0, len(df))

    chg = df["pos_change"].fillna("").str.strip().str.upper()
    df["change_type"] = np.select(
        [chg.eq("NEW"), chg.str.startswith("RE"), chg.eq("="), chg.str.startswith("+"), chg.str.startswith("-")],
        ["Mới vào", "Quay lại", "Giữ hạng", "Tăng hạng", "Giảm hạng"], default="Khác")
    df["change_value"] = df["pos_change"].map(parse_int).astype("Int64")
    n = len(df)
    df = df.sort_values("fetched_at").drop_duplicates(["market", "chart_date", "track_id"], keep="last")
    rep.add(T, "Khử trùng lặp (thị trường, ngày, track_id) khi chạy nhiều lần/ngày", n, len(df))
    keep = ["market", "chart_date", "pos", "change_type", "change_value", "track_id",
            "artist_main", "title", "featured", "days", "peak", "streams", "streams_change",
            "streams_7day", "total_streams"]
    return df[keep].reset_index(drop=True)


# ----------------------------------------------------------------------------
# 3. ReccoBeats: thông tin bài + đặc trưng âm thanh
# ----------------------------------------------------------------------------
ISRC_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$")
RANGES = {f: (0.0, 1.0) for f in config.AUDIO_FEATURES}
RANGES.update({"tempo": (30.0, 250.0), "loudness": (-60.0, 5.0)})


def clean_reccobeats(tracks: pd.DataFrame, feats: pd.DataFrame, rep: Report):
    T = "audio_features"
    t = tracks.copy()
    if not t.empty:
        t["isrc_clean"] = t["isrc"].fillna("").str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
        bad_isrc = ~t["isrc_clean"].str.match(ISRC_RE)
        rep.add("tracks", "Chuẩn hóa ISRC (bỏ gạch nối, viết hoa) và bỏ mã sai định dạng",
                len(t), len(t), int(bad_isrc.sum()), "ISRC sai -> NULL, sẽ ghép Deezer theo tên")
        t["isrc"] = t["isrc_clean"].where(~bad_isrc)
        t["duration_ms"] = pd.to_numeric(t["duration_ms"], errors="coerce")
        t = t.drop(columns="isrc_clean").drop_duplicates("spotify_id")

    f = feats.copy()
    if f.empty:
        return t, f
    n0 = len(f)
    f = f.drop_duplicates("spotify_id")
    for c in config.AUDIO_FEATURES + ["tempo", "loudness", "key", "mode"]:
        f[c] = pd.to_numeric(f[c], errors="coerce")
    out_of_range = 0
    for c, (lo, hi) in RANGES.items():
        bad = f[c].notna() & ((f[c] < lo) | (f[c] > hi))
        out_of_range += int(bad.sum())
        f.loc[bad, c] = np.nan
    rep.add(T, "Giá trị ngoài miền hợp lệ -> NULL (0-1, tempo 30-250 BPM, loudness -60..5 dB)",
            n0, len(f), out_of_range, "tempo = 0 nghĩa là không đo được nhịp")
    f.loc[~f["key"].between(-1, 11), "key"] = np.nan
    f.loc[f["key"] == -1, "key"] = np.nan
    f.loc[~f["mode"].isin([0, 1]), "mode"] = np.nan
    n = len(f)
    f = f[f[config.AUDIO_FEATURES].notna().sum(axis=1) >= 5]
    rep.add(T, "Bỏ bài thiếu quá nhiều đặc trưng (< 5/7 chỉ số)", n, len(f))
    return t, f.reset_index(drop=True)


# ----------------------------------------------------------------------------
# 4. Deezer: phát hành, thể loại, hãng đĩa
# ----------------------------------------------------------------------------
MAJOR_LABEL_RE = re.compile(
    r"sony|universal|umg|warner|columbia|atlantic|republic|interscope|rca|def jam|capitol|"
    r"island|epic|geffen|parlophone|polydor|virgin|emi|elektra|hybe|big hit|sm entertainment|"
    r"jyp|yg entertainment", re.I)

GENRE_GROUPS = {
    "Pop": "Pop", "Rap/Hip Hop": "Rap/Hip-hop", "R&B": "R&B/Soul", "Soul & Funk": "R&B/Soul",
    "Dance": "Dance/Electronic", "Electro": "Dance/Electronic", "Techno/House": "Dance/Electronic",
    "Rock": "Rock/Alternative", "Alternative": "Rock/Alternative", "Indie Pop/Folk": "Indie/Folk",
    "Folk": "Indie/Folk", "Asian Music": "Nhạc châu Á", "K-Pop": "Nhạc châu Á",
    "J-Pop": "Nhạc châu Á", "Latin Music": "Latin", "Reggaeton": "Latin",
    "Films/Games": "Nhạc phim/Game", "Country": "Country", "Jazz": "Khác", "Classical": "Khác",
}


def _parse_date(s: pd.Series) -> pd.Series:
    s = s.astype("string").str.strip().replace({"0000-00-00": pd.NA, "": pd.NA})
    return pd.to_datetime(s, errors="coerce", format="mixed")


def clean_deezer(dz: pd.DataFrame, albums: pd.DataFrame, rb_tracks: pd.DataFrame, rep: Report):
    T = "deezer"
    if dz.empty:
        return dz
    df = dz.copy()
    n0 = len(df)
    rep.add(T, "Kết quả ghép Deezer theo ISRC", n0, n0, int((df["match_method"] == "isrc").sum()))
    rep.add(T, "Kết quả ghép Deezer theo tên (fuzzy >= 0.85)", n0, n0, int((df["match_method"] == "search").sum()))
    rep.add(T, "Không ghép được với Deezer", n0, n0, int((df["match_method"] == "none").sum()))
    df = df[df["deezer_id"].notna()].copy()

    # Kiểm tra chéo thời lượng: Deezer vs ReccoBeats (Spotify). Ghép theo tên mà lệch > 15s
    # thì nhiều khả năng ghép nhầm phiên bản (remix, live...) -> loại.
    if not rb_tracks.empty:
        df = df.merge(rb_tracks[["spotify_id", "duration_ms"]], on="spotify_id", how="left")
        diff = (pd.to_numeric(df["dz_duration_s"], errors="coerce") - df["duration_ms"] / 1000).abs()
        wrong = (df["match_method"] == "search") & (diff > 15)
        n = len(df)
        df = df[~wrong]
        rep.add(T, "Loại ghép nhầm: ghép theo tên nhưng thời lượng lệch > 15 giây", n, len(df))
        df = df.drop(columns="duration_ms")

    al = albums.copy()
    if not al.empty:
        al["album_id"] = pd.to_numeric(al["album_id"], errors="coerce")
        df["album_id"] = pd.to_numeric(df["album_id"], errors="coerce")
        df = df.merge(al, on="album_id", how="left")
    else:
        for c in ["genres", "label", "album_release_date", "record_type"]:
            df[c] = None

    df["release_date"] = _parse_date(df["dz_release_date"])
    fallback = df["release_date"].isna()
    df.loc[fallback, "release_date"] = _parse_date(df.loc[fallback, "album_release_date"])
    rep.add(T, "Thiếu ngày phát hành của bài -> lấy ngày phát hành album", len(df), len(df),
            int(fallback.sum()) - int(df["release_date"].isna().sum()))
    this_year = now_utc().year
    bad_year = df["release_date"].dt.year.lt(1950) | df["release_date"].dt.year.gt(this_year)
    df.loc[bad_year, "release_date"] = pd.NaT
    rep.add(T, "Ngày phát hành vô lý (trước 1950 / sau năm hiện tại) -> NULL", len(df), len(df), int(bad_year.sum()))

    df["dz_bpm"] = pd.to_numeric(df["dz_bpm"], errors="coerce")
    zero_bpm = df["dz_bpm"].fillna(0) <= 0
    df.loc[zero_bpm, "dz_bpm"] = np.nan
    rep.add(T, "BPM = 0 trên Deezer (chưa phân tích) -> NULL", len(df), len(df), int(zero_bpm.sum()))

    df["explicit"] = df["explicit_lyrics"].map(
        lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else bool(v))
    df["genre_main"] = df["genres"].fillna("").str.split("|").str[0].replace("", None)
    df["genre_group"] = df["genre_main"].map(GENRE_GROUPS).fillna(
        df["genre_main"].where(df["genre_main"].isna(), "Khác"))
    df["label"] = df["label"].map(lambda v: nfc(v) if isinstance(v, str) else None)
    df["label_group"] = np.where(df["label"].isna(), None,
                                 np.where(df["label"].fillna("").str.contains(MAJOR_LABEL_RE),
                                          "Hãng lớn (major)", "Độc lập / hãng nhỏ"))
    keep = ["spotify_id", "deezer_id", "match_method", "match_score", "release_date", "explicit",
            "dz_bpm", "dz_rank", "genre_main", "genre_group", "label", "label_group", "record_type"]
    return df[keep].drop_duplicates("spotify_id").reset_index(drop=True)


# ----------------------------------------------------------------------------
# 5. Nghệ sĩ: ghép MusicBrainz + suy luận từ tên bài tiếng Việt
# ----------------------------------------------------------------------------
AREA_TO_COUNTRY = {"vietnam": "VN", "viet nam": "VN", "south korea": "KR", "korea": "KR",
                   "united states": "US", "united kingdom": "GB", "england": "GB", "canada": "CA",
                   "japan": "JP", "china": "CN", "taiwan": "TW", "thailand": "TH",
                   "australia": "AU", "philippines": "PH", "indonesia": "ID"}
REGIONS = {"VN": "Việt Nam", "KR": "Hàn Quốc", "US": "Âu - Mỹ", "GB": "Âu - Mỹ", "CA": "Âu - Mỹ",
           "AU": "Âu - Mỹ", "IE": "Âu - Mỹ", "NZ": "Âu - Mỹ", "SE": "Âu - Mỹ", "NO": "Âu - Mỹ",
           "DE": "Âu - Mỹ", "FR": "Âu - Mỹ", "NL": "Âu - Mỹ", "JP": "Nhật Bản", "CN": "Hoa ngữ",
           "TW": "Hoa ngữ", "HK": "Hoa ngữ", "TH": "Đông Nam Á khác", "PH": "Đông Nam Á khác",
           "ID": "Đông Nam Á khác", "MY": "Đông Nam Á khác", "SG": "Đông Nam Á khác",
           "PR": "Latin", "CO": "Latin", "MX": "Latin", "AR": "Latin", "BR": "Latin", "ES": "Latin"}


def build_artists(totals: pd.DataFrame, mb: pd.DataFrame, rep: Report) -> pd.DataFrame:
    T = "artists"
    g = totals.groupby("artist_main").agg(
        n_tracks=("track_id", "nunique"),
        vn_title_share=("title", lambda s: float(np.mean([has_vietnamese_chars(x) for x in s]))),
        on_vn_chart=("market", lambda s: bool((s == "vn").any())),
    ).reset_index()
    g["name_has_vn"] = g["artist_main"].map(has_vietnamese_chars)
    if not mb.empty:
        g = g.merge(mb, left_on="artist_main", right_on="query_name", how="left")
    else:
        for c in ["mb_id", "mb_country", "mb_area", "mb_type", "mb_gender", "mb_begin"]:
            g[c] = None

    g["country"] = g["mb_country"]
    area_c = g["mb_area"].fillna("").str.lower().map(AREA_TO_COUNTRY)
    filled = g["country"].isna() & area_c.notna()
    g.loc[filled, "country"] = area_c[filled]
    rep.add(T, "Thiếu mã quốc gia MusicBrainz -> suy từ tên khu vực (area)", len(g), len(g), int(filled.sum()))

    heuristic_vn = (g["vn_title_share"] >= 0.5) | g["name_has_vn"]
    g["origin_method"] = np.where(g["country"].notna(), "MusicBrainz",
                                  np.where(heuristic_vn, "Suy luận từ tên bài tiếng Việt", "Chưa xác định"))
    g.loc[g["country"].isna() & heuristic_vn, "country"] = "VN"
    rep.add(T, "Nghệ sĩ không có trên MusicBrainz -> suy luận là VN nếu >= 50% tên bài có dấu tiếng Việt",
            len(g), len(g), int((g["origin_method"] == "Suy luận từ tên bài tiếng Việt").sum()))

    both = g["mb_country"].notna()
    if both.any():
        agree = ((g.loc[both, "mb_country"] == "VN") == heuristic_vn[both]).mean()
        rep.add(T, "Kiểm chứng: tỷ lệ khớp giữa MusicBrainz và quy tắc tên tiếng Việt",
                len(g), len(g), int(both.sum()), f"Khớp {agree:.1%} trên {int(both.sum())} nghệ sĩ có cả 2 nguồn")

    # Trùng tên: MusicBrainz đôi khi khớp nghệ sĩ Việt với một nghệ sĩ nước ngoài cùng tên
    # (MONO -> Nhật, Khói -> Mexico...). Nghệ sĩ có mặt trên BXH Việt Nam mà phần lớn tên bài
    # bằng tiếng Việt (hoặc tên có dấu tiếng Việt) thì ưu tiên kết luận là nghệ sĩ Việt.
    conflict = g["on_vn_chart"] & heuristic_vn & g["country"].notna() & g["country"].ne("VN")
    g.loc[conflict, "country"] = "VN"
    g.loc[conflict, "origin_method"] = "Sửa trùng tên (tên bài tiếng Việt)"
    rep.add(T, "Sửa khớp nhầm trùng tên: MusicBrainz ra nước ngoài nhưng tên bài tiếng Việt -> VN",
            len(g), len(g), int(conflict.sum()))

    g["is_vietnamese"] = g["country"].eq("VN")
    g["region"] = g["country"].map(REGIONS).fillna(
        pd.Series(np.where(g["country"].isna(), "Chưa xác định", "Khác"), index=g.index))
    g["artist_type"] = g["mb_type"].map({"Person": "Cá nhân", "Group": "Nhóm/Ban nhạc",
                                         "Orchestra": "Nhóm/Ban nhạc", "Choir": "Nhóm/Ban nhạc"})
    g["gender"] = g["mb_gender"].map({"Male": "Nam", "Female": "Nữ", "Non-binary": "Khác"})
    g["career_start_year"] = pd.to_numeric(g["mb_begin"].astype("string").str[:4], errors="coerce").astype("Int64")
    keep = ["artist_main", "n_tracks", "on_vn_chart", "country", "region", "is_vietnamese",
            "origin_method", "artist_type", "gender", "career_start_year", "vn_title_share"]
    return g[keep]


# ----------------------------------------------------------------------------
def run(con) -> dict:
    log.info("=== LÀM SẠCH (staging) ===")
    rep = Report()
    totals = clean_chart_totals(db.read_df(con, "raw.kworb_totals"), rep)
    daily = clean_chart_daily(db.read_df(con, "raw.kworb_chart_daily"), rep)
    rb_t, rb_f = clean_reccobeats(db.read_df(con, "raw.reccobeats_tracks"),
                                  db.read_df(con, "raw.reccobeats_features"), rep)
    dz = clean_deezer(db.read_df(con, "raw.deezer_tracks"), db.read_df(con, "raw.deezer_albums"), rb_t, rep)
    artists = build_artists(totals, db.read_df(con, "raw.musicbrainz_artists"), rep)

    db.write_df(con, "staging.chart_totals", totals)
    db.write_df(con, "staging.chart_daily", daily)
    db.write_df(con, "staging.tracks", rb_t)
    db.write_df(con, "staging.audio_features", rb_f)
    db.write_df(con, "staging.deezer", dz)
    db.write_df(con, "staging.artists", artists)
    db.save_cleaning_report(con, rep.rows)
    return {"chart_totals": len(totals), "chart_daily": len(daily), "audio_features": len(rb_f),
            "deezer": len(dz), "artists": len(artists)}
