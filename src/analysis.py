"""Các phép phân tích dùng chung cho dashboard và báo cáo (thuần pandas/numpy)."""
from __future__ import annotations

import numpy as np
import pandas as pd

import config

TIERS = ["Lướt qua", "Trung bình", "Trụ lâu"]

DIMENSIONS = {
    "mood": "Tâm trạng (cảm xúc × năng lượng)",
    "tempo_bucket": "Nhịp độ",
    "duration_bucket": "Thời lượng",
    "region": "Nguồn gốc nghệ sĩ",
    "is_collab": "Có hợp tác (feat.)",
    "explicit": "Nhãn Explicit",
    "genre_group": "Thể loại (Deezer)",
    "release_era": "Thời kỳ phát hành",
    "label_group": "Loại hãng đĩa",
    "artist_type": "Cá nhân / Nhóm",
    "title_vietnamese": "Tên bài tiếng Việt",
    "mode_name": "Giọng trưởng / thứ",
    "version_type": "Phiên bản",
}

CATEGORY_ORDER = {
    "tempo_bucket": ["Chậm (<90)", "Vừa (90-110)", "Khá nhanh (110-130)", "Nhanh (>=130)"],
    "duration_bucket": ["<2.5'", "2.5-3'", "3-3.5'", "3.5-4'", "4-4.5'", ">=4.5'"],
    "release_era": ["Trước 2015", "2015-2019", "2020-2022", "Từ 2023"],
    "mood": ["Buồn - nhẹ nhàng (ballad)", "Buồn - mạnh mẽ", "Vui - nhẹ nhàng", "Vui - sôi động"],
}


def analysis_base(tm: pd.DataFrame, market: str | None = None, scope: bool = True) -> pd.DataFrame:
    """Bản chính của mỗi bài (bỏ bản trùng). scope=True: chỉ phạm vi được làm giàu dữ liệu;
    scope=False: mọi bài từng lọt BXH (dùng khi chỉ cần số ngày trụ hạng từ Kworb)."""
    keep = tm["is_primary_version"].astype(bool)
    if scope:
        keep &= tm["in_scope"].astype(bool)
    d = tm[keep]
    if market:
        d = d[d["market"] == market]
    return d


def rated(d: pd.DataFrame) -> pd.DataFrame:
    """Chỉ những bài đã biết kết cục (loại bài còn đang trên BXH và chưa đủ ngưỡng)."""
    return d[d["is_long_run"].notna()]


def wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return c - h, c + h


def success_rate_by(d: pd.DataFrame, col: str, min_n: int = 15) -> pd.DataFrame:
    """Tỷ lệ 'Trụ lâu' theo từng nhóm của `col`, kèm khoảng tin cậy 95% (Wilson) và lift."""
    r = rated(d)
    r = r[r[col].notna()]
    if r.empty:
        return pd.DataFrame(columns=["category", "n", "n_long", "rate", "lo", "hi", "lift"])
    base = r["is_long_run"].mean()
    g = r.groupby(r[col].astype(str))["is_long_run"].agg(["count", "sum"]).reset_index()
    g.columns = ["category", "n", "n_long"]
    g = g[g["n"] >= min_n].copy()
    g["rate"] = g["n_long"] / g["n"]
    ci = [wilson(k, n) for k, n in zip(g["n_long"], g["n"])]
    g["lo"] = [c[0] for c in ci]
    g["hi"] = [c[1] for c in ci]
    g["lift"] = g["rate"] / base if base else np.nan
    g["base_rate"] = base
    order = CATEGORY_ORDER.get(col)
    if order:
        g["_o"] = g["category"].map({c: i for i, c in enumerate(order)}).fillna(99)
        g = g.sort_values("_o").drop(columns="_o")
    else:
        g = g.sort_values("rate", ascending=False)
    g["category"] = g["category"].replace({"True": "Có", "False": "Không"})
    return g.reset_index(drop=True)


def feature_effects(d: pd.DataFrame, group_col: str, a, b, features=None) -> pd.DataFrame:
    """So sánh trung bình từng đặc trưng giữa 2 nhóm: chênh lệch chuẩn hóa (Cohen's d) + KTC 95%."""
    features = features or config.NUMERIC_FEATURES
    A, B = d[d[group_col] == a], d[d[group_col] == b]
    rows = []
    for f in features:
        x, y = A[f].dropna().astype(float), B[f].dropna().astype(float)
        if len(x) < 5 or len(y) < 5:
            continue
        sp = np.sqrt(((len(x) - 1) * x.var() + (len(y) - 1) * y.var()) / (len(x) + len(y) - 2))
        dval = (x.mean() - y.mean()) / sp if sp else 0.0
        se = np.sqrt((len(x) + len(y)) / (len(x) * len(y)) + dval ** 2 / (2 * (len(x) + len(y))))
        rows.append({"feature": f, "label": config.FEATURE_LABELS.get(f, f),
                     "mean_a": x.mean(), "mean_b": y.mean(), "median_a": x.median(), "median_b": y.median(),
                     "n_a": len(x), "n_b": len(y), "d": dval, "lo": dval - 1.96 * se, "hi": dval + 1.96 * se})
    out = pd.DataFrame(rows)
    if not out.empty:
        out["significant"] = (out["lo"] > 0) | (out["hi"] < 0)
        out = out.sort_values("d")
    return out


def rate_grid(d: pd.DataFrame, x="energy", y="valence", bins=5, min_n=8) -> pd.DataFrame:
    """Lưới 2 chiều: tỷ lệ trụ lâu trong từng ô (energy × valence)."""
    r = rated(d).dropna(subset=[x, y]).copy()
    edges = np.linspace(0, 1, bins + 1)
    labels = [f"{edges[i]:.1f}-{edges[i + 1]:.1f}" for i in range(bins)]
    r["xb"] = pd.cut(r[x], edges, labels=labels, include_lowest=True)
    r["yb"] = pd.cut(r[y], edges, labels=labels, include_lowest=True)
    g = r.groupby(["xb", "yb"], observed=False)["is_long_run"].agg(["count", "mean"]).reset_index()
    g.loc[g["count"] < min_n, "mean"] = np.nan
    return g


def share_table(d: pd.DataFrame, col: str, by: str = "market", weight: str | None = None) -> pd.DataFrame:
    """Tỷ trọng các nhóm của `col` trong từng `by` (theo số bài hoặc theo tổng stream)."""
    x = d[d[col].notna()].copy()
    x["_w"] = x[weight].astype(float) if weight else 1.0
    g = x.groupby([by, col])["_w"].sum().reset_index()
    g["share"] = g["_w"] / g.groupby(by)["_w"].transform("sum")
    return g.rename(columns={"_w": "value"})


def recommendations(d: pd.DataFrame, dims=None, min_n: int = 25) -> list[dict]:
    """Sinh khuyến nghị 'chọn nhạc': với mỗi chiều, nhóm có tỷ lệ trụ lâu cao nhất / thấp nhất."""
    dims = dims or ["mood", "duration_bucket", "tempo_bucket", "is_collab", "region",
                    "genre_group", "explicit", "title_vietnamese"]
    recs = []
    for col in dims:
        t = success_rate_by(d, col, min_n=min_n)
        # Nhóm gom chung ("Khác", "Chưa xác định") không phải lựa chọn có thể hành động -> bỏ khỏi khuyến nghị
        t = t[~t["category"].isin(["Khác", "Chưa xác định"])].reset_index(drop=True)
        if len(t) < 2:
            continue
        best, worst = t.loc[t["rate"].idxmax()], t.loc[t["rate"].idxmin()]
        # Chỉ khuyến nghị khi khoảng tin cậy của nhóm tốt nhất và kém nhất không chồng nhau
        robust = best["lo"] > worst["hi"]
        recs.append({"dimension": col, "label": DIMENSIONS.get(col, col),
                     "best": best["category"], "best_rate": best["rate"], "best_n": int(best["n"]),
                     "best_lift": best["lift"], "worst": worst["category"], "worst_rate": worst["rate"],
                     "worst_n": int(worst["n"]), "base_rate": best["base_rate"],
                     "gap": best["rate"] - worst["rate"], "robust": bool(robust)})
    return sorted(recs, key=lambda r: (not r["robust"], -r["gap"]))


# ----------------------------------------------------------------------------
# Công cụ "Chọn nhạc": chấm điểm độ phù hợp của một bài với thị trường
# ----------------------------------------------------------------------------
FIT_FEATURES = ["danceability", "energy", "valence", "acousticness", "speechiness", "tempo", "duration_min"]


def song_fit(d: pd.DataFrame, song: dict, k: int = 25) -> dict:
    """So bài `song` (dict đặc trưng) với các bài đã biết kết cục trong thị trường `d`.

    - Tìm k bài giống nhất (khoảng cách Euclid trên đặc trưng đã chuẩn hóa z-score).
    - Điểm phù hợp = tỷ lệ bài 'Trụ lâu' trong k láng giềng, so với tỷ lệ chung.
    - Vị trí phân vị của từng đặc trưng so với nhóm 'Trụ lâu'.
    """
    r = rated(d).dropna(subset=FIT_FEATURES)
    if len(r) < k:
        return {}
    X = r[FIT_FEATURES].astype(float)
    mu, sd = X.mean(), X.std().replace(0, 1)
    Z = (X - mu) / sd
    z = (pd.Series({f: float(song[f]) for f in FIT_FEATURES}) - mu) / sd
    dist = np.sqrt(((Z - z) ** 2).sum(axis=1))
    if song.get("track_id") is not None:
        dist = dist[r["track_id"] != song["track_id"]]
    nn = r.loc[dist.nsmallest(k).index].assign(distance=dist.nsmallest(k).values)
    base = r["is_long_run"].mean()
    rate = nn["is_long_run"].mean()
    long = r[r["is_long_run"] == 1]
    pct = {f: float((long[f] < song[f]).mean()) for f in FIT_FEATURES}
    return {"fit_rate": rate, "base_rate": base, "lift": rate / base if base else np.nan,
            "neighbors": nn, "percentiles": pct, "long_profile": long[FIT_FEATURES].median()}
