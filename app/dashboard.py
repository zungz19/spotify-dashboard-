"""Dashboard động: Chọn nhạc cho thị trường Spotify Việt Nam (so với toàn cầu).

Chạy:  streamlit run app/dashboard.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import config  # noqa: E402
from app import charts  # noqa: E402
from src import analysis, db, pipeline  # noqa: E402

VN_TZ = timezone(timedelta(hours=7))
st.set_page_config(page_title="Chọn nhạc cho thị trường Việt Nam", page_icon="🎧", layout="wide")


def show(fig, key=None, select=False):
    """Hiển thị biểu đồ; nếu select=True trả về các điểm người dùng bấm chọn (lọc chéo)."""
    if select:
        ev = st.plotly_chart(fig, use_container_width=True, key=key, on_select="rerun",
                             selection_mode="points")
        try:
            return ev["selection"]["points"]
        except (KeyError, TypeError):
            return []
    st.plotly_chart(fig, use_container_width=True, key=key)
    return []


def to_vn_time(iso: str | None) -> str:
    if not iso:
        return "chưa có"
    try:
        t = datetime.fromisoformat(str(iso))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t.astimezone(VN_TZ).strftime("%H:%M %d/%m/%Y")
    except ValueError:
        return str(iso)


def hours_since(iso: str | None) -> float | None:
    if not iso:
        return None
    t = datetime.fromisoformat(str(iso))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600


# ----------------------------------------------------------------------------
# NẠP DỮ LIỆU (cache theo thời điểm file kho thay đổi -> tự làm mới sau mỗi lần cập nhật)
# ----------------------------------------------------------------------------
def db_version() -> float:
    return config.DB_PATH.stat().st_mtime if config.DB_PATH.exists() else 0.0


@st.cache_data(show_spinner="Đang nạp dữ liệu từ kho DuckDB...")
def load_data(version: float) -> dict:
    with db.connect() as con:
        out = {name: db.read_df(con, name) for name in
               ["mart.track_market", "mart.fact_chart_daily", "meta.cleaning_report", "meta.update_log",
                "raw.kworb_totals", "raw.reccobeats_features", "raw.deezer_tracks", "raw.musicbrainz_artists"]}
        out["last_success"] = pipeline.last_success(con)
    out["raw_counts"] = {k: len(v) for k, v in out.items() if k.startswith("raw.")}
    # "mart.track_market" -> "track_market", "meta.update_log" -> "update_log"
    return {k.split(".", 1)[-1]: v for k, v in out.items() if not k.startswith("raw.")}


# Tự động cập nhật chỉ chạy phần nhẹ (lấy BXH mới, khoảng 30-60 giây) để người xem không phải chờ lâu;
# nút "Cập nhật dữ liệu ngay" chạy đủ các bước, kể cả làm giàu dữ liệu cho bài mới.
AUTO_STEPS = ["kworb", "clean", "mart"]


def run_update(source: str):
    steps = AUTO_STEPS if source == "auto" else None
    label = ("Đang tự động lấy BXH mới từ Kworb..." if source == "auto" else
             "Đang cập nhật dữ liệu mới từ Kworb, ReccoBeats, Deezer, MusicBrainz...")
    with st.status(label, expanded=True) as status:
        try:
            res = pipeline.run(mode="update", steps=steps, progress=lambda m: status.write(m))
        except pipeline.PipelineBusy as exc:
            status.update(label=str(exc), state="error")
            return
        ok = all(r["status"] == "success" for r in res)
        status.update(label="Cập nhật xong" if ok else "Cập nhật lỗi - xem nhật ký ở tab Dữ liệu",
                      state="complete" if ok else "error")
    st.session_state["last_update_source"] = source
    st.cache_data.clear()
    st.rerun()


# ----------------------------------------------------------------------------
# SIDEBAR: trạng thái dữ liệu + cập nhật + bộ lọc
# ----------------------------------------------------------------------------
st.sidebar.markdown("## 🎧 Bảng điều khiển")

if not config.DB_PATH.exists():
    st.title("Chưa có dữ liệu")
    st.info("Hãy chạy `python run_pipeline.py` một lần để thu thập dữ liệu (khoảng 30-40 phút), "
            "hoặc bấm nút dưới đây để chạy ngay trong dashboard.")
    if st.button("▶️ Thu thập dữ liệu lần đầu", type="primary"):
        run_update("first-run")
    st.stop()

data = load_data(db_version())
tm_all = data["track_market"]
daily_all = data["fact_chart_daily"]
if tm_all.empty:
    st.error("Kho dữ liệu chưa có bảng mart.track_market. Hãy chạy `python run_pipeline.py`.")
    st.stop()

age = hours_since(data["last_success"])
latest_chart = pd.to_datetime(daily_all["chart_date"]).max() if not daily_all.empty else None
st.sidebar.caption(
    f"**BXH mới nhất:** {latest_chart:%d/%m/%Y}" if latest_chart is not None else "**BXH:** chưa có")
st.sidebar.caption(f"**Cập nhật lần cuối:** {to_vn_time(data['last_success'])}"
                   + (f" ({age:.1f} giờ trước)" if age is not None else ""))
if st.sidebar.button("🔄 Cập nhật dữ liệu ngay", use_container_width=True):
    run_update("manual")
auto = st.sidebar.toggle(f"Tự động cập nhật khi dữ liệu cũ hơn {config.REFRESH_HOURS} giờ", value=True)


@st.fragment(run_every=timedelta(minutes=config.AUTO_CHECK_MINUTES))
def auto_updater():
    """Chạy ngầm theo chu kỳ: nếu dữ liệu đã cũ thì tự gọi pipeline lấy BXH mới."""
    if not auto:
        return
    # Không thử lại liên tục nếu lần trước lỗi (ví dụ mất mạng): mỗi chu kỳ chỉ thử 1 lần
    last_try = st.session_state.get("last_auto_attempt")
    if last_try and hours_since(last_try) * 60 < config.AUTO_CHECK_MINUTES:
        return
    with db.connect() as con:
        last = pipeline.last_success(con)
    h = hours_since(last)
    if h is None or h >= config.REFRESH_HOURS:
        st.session_state["last_auto_attempt"] = datetime.now(timezone.utc).isoformat()
        run_update("auto")


auto_updater()

st.sidebar.divider()
st.sidebar.markdown("### 🔍 Bộ lọc")
market = st.sidebar.radio("Thị trường phân tích chính", list(config.MARKETS),
                          format_func=lambda m: config.MARKETS[m], horizontal=True)
years = tm_all["release_year"].dropna().astype(int)
if not years.empty:
    y0, y1 = int(years.min()), int(years.max())
    yr = st.sidebar.slider("Năm phát hành", y0, y1, (max(y0, 2018), y1))
else:
    yr = None
regions = sorted(tm_all["region"].dropna().unique())
sel_regions = st.sidebar.multiselect("Nguồn gốc nghệ sĩ", regions, default=regions)
genres = sorted(tm_all["genre_group"].dropna().unique())
sel_genres = st.sidebar.multiselect("Thể loại (để trống = tất cả)", genres)
only_original = st.sidebar.toggle("Chỉ bản gốc (bỏ remix, live, sped up...)", value=True)
min_n = st.sidebar.slider("Số bài tối thiểu mỗi nhóm khi tính tỷ lệ", 10, 60, 20, step=5)

def apply_filters(d):
    if yr:
        d = d[d["release_year"].between(yr[0], yr[1]) | d["release_year"].isna()]
    d = d[d["region"].isin(sel_regions)]
    if sel_genres:
        d = d[d["genre_group"].isin(sel_genres)]
    if only_original:
        d = d[d["version_type"] == "original"]
    return d


tm = apply_filters(analysis.analysis_base(tm_all))
# Số ngày trụ hạng có sẵn cho MỌI bài trên Kworb -> so sánh độ trụ hạng dùng toàn bộ BXH,
# tránh lệch do phía toàn cầu chỉ làm giàu dữ liệu cho các bài lớn nhất.
tm_long = apply_filters(analysis.analysis_base(tm_all, scope=False))
tm_m = tm[tm["market"] == market]
st.sidebar.info(f"Đang phân tích **{len(tm_m):,}** bài thuộc BXH {config.MARKETS[market]} "
                f"(tổng {len(tm):,} dòng bài × thị trường sau lọc).")

# ----------------------------------------------------------------------------
# HEADER + KPI
# ----------------------------------------------------------------------------
st.title("🎧 Chọn nhạc cho thị trường Spotify Việt Nam")
st.caption("Dữ liệu tự thu thập từ 4 nguồn: Kworb (BXH Spotify), ReccoBeats (đặc trưng âm thanh), "
           "Deezer (phát hành, thể loại, hãng đĩa), MusicBrainz (quốc gia nghệ sĩ). "
           "Tự cập nhật khi Spotify công bố BXH mới.")

vn = tm[tm["market"] == "vn"]
gl = tm[tm["market"] == "global"]
r_m = analysis.rated(tm_m)
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Bài từng lọt BXH " + config.MARKETS[market], f"{len(tm_m):,}")
if not vn.empty:
    share_vn = vn["region"].eq("Việt Nam").mean()
    share_vn_streams = vn.loc[vn["region"].eq("Việt Nam"), "total_streams"].sum() / max(vn["total_streams"].sum(), 1)
    k2.metric("Nhạc Việt / BXH VN (số bài)", f"{share_vn:.0%}", f"{share_vn_streams:.0%} theo lượt stream",
              delta_color="off")
k3.metric("Trung vị số ngày trụ hạng", f"{tm_m['days'].median():.0f} ngày" if len(tm_m) else "-")
if len(r_m):
    k4.metric("Ngưỡng 'Trụ lâu'", f"≥ {tm_m['long_run_threshold'].iloc[0]:.0f} ngày",
              f"{r_m['is_long_run'].mean():.0%} số bài đạt", delta_color="off")
if latest_chart is not None:
    today = daily_all[(daily_all["market"] == "vn") & (pd.to_datetime(daily_all["chart_date"]) == latest_chart)]
    top50 = today[today["pos"] <= 50]
    k5.metric("Bài Việt / Top 50 hôm nay", f"{int((top50['region'] == 'Việt Nam').sum())}/{len(top50)}")

tabs = st.tabs(["📈 BXH hôm nay", "🌏 Việt Nam vs Toàn cầu", "⏳ Yếu tố giúp trụ hạng",
                "🎯 Chọn nhạc", "🗂️ Dữ liệu & Pipeline"])

# ============================================================================
# TAB 1 - BXH HÔM NAY (dữ liệu động, cập nhật mỗi ngày)
# ============================================================================
with tabs[0]:
    if daily_all.empty:
        st.info("Chưa có BXH ngày. Bấm 'Cập nhật dữ liệu ngay'.")
    else:
        d_all = daily_all.copy()
        d_all["chart_date"] = pd.to_datetime(d_all["chart_date"])
        c1, c2 = st.columns([1, 1])
        mk = c1.radio("BXH", list(config.MARKETS), format_func=lambda m: config.MARKETS[m],
                      horizontal=True, key="daily_market")
        dates = sorted(d_all.loc[d_all["market"] == mk, "chart_date"].unique(), reverse=True)
        day = c2.selectbox("Ngày", dates, format_func=lambda x: pd.Timestamp(x).strftime("%d/%m/%Y"))
        today = d_all[(d_all["market"] == mk) & (d_all["chart_date"] == day)].sort_values("pos")

        a, b, c = st.columns(3)
        a.metric("Bài mới vào BXH", int((today["change_type"] == "Mới vào").sum()))
        b.metric("Bài Việt trong Top 200", int((today["region"] == "Việt Nam").sum()))
        if len(today):
            top1 = today.iloc[0]
            c.markdown(f"<div style='font-size:14px'>Hạng 1</div><div style='font-size:22px;font-weight:600;"
                       f"line-height:1.3'>{top1['title']}</div><div style='color:#52514e'>{top1['artist_main']} · "
                       f"{int(top1['streams']):,} stream</div>", unsafe_allow_html=True)

        left, right = st.columns([3, 2])
        with left:
            st.markdown("**Top 50**")
            view = today.head(50)[["pos", "change_type", "change_value", "title", "artist_main", "featured",
                                   "region", "streams", "days"]].copy()
            view["change_value"] = view["change_value"].map(lambda v: "" if pd.isna(v) else f"{int(v):+d}")
            view["featured"] = view["featured"].fillna("").astype(str)
            st.dataframe(view, hide_index=True, use_container_width=True, height=430, column_config={
                "pos": "Hạng", "change_type": "Biến động", "change_value": "±", "title": "Bài hát",
                "artist_main": "Nghệ sĩ", "featured": "Hợp tác", "region": "Nguồn gốc",
                "streams": st.column_config.NumberColumn("Stream trong ngày", format="%d"),
                "days": "Số ngày trên BXH"})
        with right:
            latest_both = d_all.groupby("market")["chart_date"].transform("max") == d_all["chart_date"]
            st.markdown("**Nguồn gốc nghệ sĩ trong Top 200 mới nhất**")
            show(charts.region_share_bar(d_all[latest_both], title=""), key="today_region")
            movers = today[today["change_type"] == "Tăng hạng"].nlargest(5, "change_value")
            st.markdown("**Tăng hạng mạnh nhất**")
            st.dataframe(movers[["pos", "change_value", "title", "artist_main"]], hide_index=True,
                         use_container_width=True,
                         column_config={"pos": "Hạng", "change_value": "Tăng", "title": "Bài", "artist_main": "Nghệ sĩ"})

        opts = (today.head(50)["title"].fillna("?").astype(str) + " — "
                + today.head(50)["artist_main"].fillna("?").astype(str)).tolist()
        pick = st.multiselect("Xem lịch sử thứ hạng của bài:", opts, default=opts[:3])
        hist = d_all[d_all["market"] == mk].copy()
        hist["label"] = hist["title"].fillna("?").astype(str) + " — " + hist["artist_main"].fillna("?").astype(str)
        show(charts.rank_history(hist[hist["label"].isin(pick)].sort_values("chart_date")), key="rank_hist")
        n_days = len(dates)
        st.caption(f"Đã thu thập {n_days} ngày BXH. Mỗi ngày pipeline chạy sẽ thêm một điểm vào lịch sử.")

# ============================================================================
# TAB 2 - VIỆT NAM vs TOÀN CẦU
# ============================================================================
with tabs[1]:
    st.subheader("Khán giả Việt Nam nghe gì khác thế giới?")
    w = st.radio("Tính tỷ trọng theo", ["Số bài", "Tổng lượt stream"], horizontal=True)
    show(charts.region_share_bar(tm, "total_streams" if w == "Tổng lượt stream" else None,
                                 title="Nguồn gốc nghệ sĩ trên BXH mỗi thị trường"), key="vs_region")
    c1, c2 = st.columns(2)
    with c1:
        show(charts.longevity_ecdf(tm_long), key="vs_ecdf")
        st.caption("Tính trên mọi bài từng lọt BXH của mỗi thị trường.")
    with c2:
        show(charts.grouped_share(tm[tm["mood"].notna()], "mood", "Tâm trạng bài hát",
                                  order=analysis.CATEGORY_ORDER["mood"]), key="vs_mood")
    feat_tm = tm[tm["has_features"].astype(bool)]
    eff = analysis.feature_effects(feat_tm, "market", "vn", "global")
    c1, c2 = st.columns([3, 2])
    with c1:
        show(charts.feature_effect_dots(eff, "Việt Nam", "Toàn cầu",
                                        "Đặc trưng âm thanh: BXH Việt Nam so với toàn cầu"), key="vs_eff")
    with c2:
        f = st.selectbox("Xem phân phối đặc trưng", config.NUMERIC_FEATURES,
                         format_func=lambda x: config.FEATURE_LABELS[x], key="vs_feat")
        show(charts.feature_box(feat_tm, f), key="vs_box")
    show(charts.grouped_share(tm[tm["genre_group"].notna()], "genre_group", "Thể loại (theo Deezer)", top=8),
         key="vs_genre")

# ============================================================================
# TAB 3 - YẾU TỐ GIÚP TRỤ HẠNG (trong thị trường đã chọn)
# ============================================================================
with tabs[2]:
    st.subheader(f"Điều gì giúp một bài trụ lâu trên BXH {config.MARKETS[market]}?")
    if len(r_m) == 0:
        st.warning("Không có dữ liệu cho bộ lọc hiện tại.")
    else:
        st.caption(f"'Trụ lâu' = số ngày trên BXH thuộc top 25% của thị trường "
                   f"(≥ {tm_m['long_run_threshold'].iloc[0]:.0f} ngày). Bài còn đang trên BXH mà chưa đạt ngưỡng "
                   "được loại khỏi phép tính vì chưa biết kết cục. Thanh lỗi = khoảng tin cậy 95%.")
        dim = st.selectbox("Phân tích theo", list(analysis.DIMENSIONS), format_func=analysis.DIMENSIONS.get)
        t = analysis.success_rate_by(tm_m, dim, min_n=min_n)
        pts = show(charts.success_rate_bar(t, f"Tỷ lệ 'Trụ lâu' theo {analysis.DIMENSIONS[dim].lower()}"),
                   key=f"rate_{dim}", select=True)
        chosen = [p.get("x") for p in pts if p.get("x") is not None]
        if chosen:
            src = tm_m.copy()
            src["_cat"] = src[dim].astype(str).replace({"True": "Có", "False": "Không"})
            sub = src[src["_cat"].isin(chosen)].nlargest(30, "days")
            st.markdown(f"**Các bài thuộc nhóm {', '.join(map(str, chosen))}** (bấm vào cột khác để đổi)")
            st.dataframe(sub[["title", "artist_main", "region", "days", "peak", "total_streams", "success_tier"]],
                         hide_index=True, use_container_width=True, column_config={
                             "title": "Bài", "artist_main": "Nghệ sĩ", "region": "Nguồn gốc",
                             "days": "Số ngày", "peak": "Hạng cao nhất",
                             "total_streams": st.column_config.NumberColumn("Tổng stream", format="%d"),
                             "success_tier": "Nhóm"})
        else:
            st.caption("👆 Bấm vào một cột để xem danh sách bài hát của nhóm đó.")

        c1, c2 = st.columns(2)
        feat_m = tm_m[tm_m["has_features"].astype(bool)]
        with c1:
            show(charts.rate_heatmap(analysis.rate_grid(feat_m, min_n=max(5, min_n // 2)),
                                     "Vùng 'năng lượng × cảm xúc' dễ trụ hạng"), key="heat")
        with c2:
            eff_t = analysis.feature_effects(feat_m, "success_tier", "Trụ lâu", "Lướt qua")
            show(charts.feature_effect_dots(eff_t, "Trụ lâu", "Lướt qua",
                                            "Bài trụ lâu khác bài lướt qua ở đâu?"), key="eff_tier")

# ============================================================================
# TAB 4 - CHỌN NHẠC: khuyến nghị + công cụ chấm điểm bài hát
# ============================================================================
with tabs[3]:
    st.subheader(f"Khuyến nghị chọn nhạc cho BXH {config.MARKETS[market]}")
    recs = analysis.recommendations(tm_m, min_n=min_n)
    if not recs:
        st.info("Không đủ dữ liệu để đưa ra khuyến nghị với bộ lọc hiện tại.")
    cols = st.columns(2)
    for i, r in enumerate(recs[:6]):
        with cols[i % 2].container(border=True):
            badge = "✅ Khác biệt rõ (khoảng tin cậy không chồng nhau)" if r["robust"] else "⚠️ Chênh lệch chưa chắc chắn"
            st.markdown(f"**{r['label']}** · {badge}")
            st.markdown(f"Nên ưu tiên: **{r['best']}** — {r['best_rate']:.0%} trụ lâu "
                        f"(gấp {r['best_lift']:.1f} lần mức chung {r['base_rate']:.0%}, n={r['best_n']})  \n"
                        f"Cân nhắc kỹ: **{r['worst']}** — {r['worst_rate']:.0%} (n={r['worst_n']})")

    st.divider()
    st.subheader("🎯 Chấm điểm một bài hát trước khi phát hành / chọn đưa vào playlist")
    st.caption("So bài hát với các bài đã từng lọt BXH: tìm 25 bài có 'chất âm thanh' giống nhất và xem bao nhiêu "
               "bài trong số đó trụ lâu. Đây là gợi ý dựa trên dữ liệu quá khứ, không phải dự báo chắc chắn.")
    feat_m = tm_m[tm_m["has_features"].astype(bool)]
    mode = st.radio("Cách nhập", ["Chọn một bài có sẵn", "Tự nhập thông số"], horizontal=True)
    song = None
    if mode == "Chọn một bài có sẵn":
        pool = tm[tm["has_features"].astype(bool)].drop_duplicates("track_id").sort_values("total_streams", ascending=False)
        labels = (pool["title"].fillna("?").astype(str) + " — "
                  + pool["artist_main"].fillna("?").astype(str)).tolist()
        if labels:
            idx = st.selectbox("Bài hát (có thể là bài của thị trường khác)", range(len(labels)),
                               format_func=lambda i: labels[i])
            song = pool.iloc[idx][analysis.FIT_FEATURES + ["track_id"]].to_dict()
    else:
        c = st.columns(4)
        song = {
            "danceability": c[0].slider("Tính khiêu vũ", 0.0, 1.0, 0.6),
            "energy": c[1].slider("Năng lượng", 0.0, 1.0, 0.5),
            "valence": c[2].slider("Cảm xúc tích cực", 0.0, 1.0, 0.4),
            "acousticness": c[3].slider("Độ mộc", 0.0, 1.0, 0.3),
            "speechiness": c[0].slider("Tỷ lệ lời nói/rap", 0.0, 1.0, 0.06),
            "tempo": c[1].slider("Nhịp (BPM)", 60, 200, 110),
            "duration_min": c[2].slider("Thời lượng (phút)", 1.5, 6.0, 3.4, step=0.1),
        }
    if song:
        res = analysis.song_fit(feat_m, song)
        if not res:
            st.warning("Không đủ bài có đặc trưng âm thanh để so sánh.")
        else:
            a, b, c = st.columns(3)
            a.metric("Tỷ lệ trụ lâu của 25 bài giống nhất", f"{res['fit_rate']:.0%}",
                     f"{res['fit_rate'] - res['base_rate']:+.0%} so với mức chung")
            b.metric("Mức chung của thị trường", f"{res['base_rate']:.0%}")
            verdict = ("Rất phù hợp" if res["lift"] >= 1.4 else "Phù hợp" if res["lift"] >= 1.1
                       else "Trung tính" if res["lift"] >= 0.9 else "Rủi ro cao")
            c.metric("Đánh giá", verdict, f"gấp {res['lift']:.2f} lần", delta_color="off")
            c1, c2 = st.columns([2, 3])
            with c1:
                show(charts.fit_percentiles(res["percentiles"], song, res["long_profile"]), key="fit_pct")
            with c2:
                nn = res["neighbors"]
                st.markdown("**Các bài có chất âm thanh giống nhất**")
                st.dataframe(nn[["title", "artist_main", "region", "days", "success_tier"]], hide_index=True,
                             use_container_width=True, height=340,
                             column_config={"title": "Bài", "artist_main": "Nghệ sĩ", "region": "Nguồn gốc",
                                            "days": "Số ngày", "success_tier": "Kết quả"})

# ============================================================================
# TAB 5 - DỮ LIỆU & PIPELINE
# ============================================================================
with tabs[4]:
    st.subheader("Kiến trúc pipeline")
    arch = ROOT / "docs" / "architecture.png"
    if arch.exists():
        st.image(str(arch), use_container_width=True)
    rc = data["raw_counts"]
    st.markdown("**Nguồn dữ liệu đã thu thập**")
    st.dataframe(pd.DataFrame([
        {"Nguồn": "Kworb (scraping)", "Nội dung": "BXH Spotify ngày + tổng hợp, VN & toàn cầu",
         "Số bản ghi thô": rc.get("raw.kworb_totals", 0) + len(daily_all)},
        {"Nguồn": "ReccoBeats API", "Nội dung": "Đặc trưng âm thanh theo Spotify ID",
         "Số bản ghi thô": rc.get("raw.reccobeats_features", 0)},
        {"Nguồn": "Deezer API", "Nội dung": "Ngày phát hành, thể loại, hãng đĩa, explicit",
         "Số bản ghi thô": rc.get("raw.deezer_tracks", 0)},
        {"Nguồn": "MusicBrainz API", "Nội dung": "Quốc gia, loại nghệ sĩ",
         "Số bản ghi thô": rc.get("raw.musicbrainz_artists", 0)},
    ]), hide_index=True, use_container_width=True)

    st.markdown("**Báo cáo làm sạch dữ liệu**")
    st.dataframe(data["cleaning_report"], hide_index=True, use_container_width=True, column_config={
        "table_name": "Bảng", "step": "Quy tắc", "rows_before": "Trước", "rows_after": "Sau",
        "rows_affected": "Bị ảnh hưởng", "note": "Ghi chú"})

    st.markdown("**Nhật ký cập nhật (meta.update_log)**")
    logdf = data["update_log"].sort_values("started_at", ascending=False).head(60).copy()
    if not logdf.empty:
        logdf["started_at"] = logdf["started_at"].map(to_vn_time)
    st.dataframe(logdf[["run_id", "mode", "step", "started_at", "duration_s", "status", "detail"]]
                 if not logdf.empty else logdf, hide_index=True, use_container_width=True)

    st.markdown("**Tải dữ liệu (CSV)**")
    dl = st.columns(3)
    dl[0].download_button("Bảng phân tích (track_market)", tm_all.to_csv(index=False).encode("utf-8-sig"),
                          "track_market.csv", "text/csv")
    dl[1].download_button("Lịch sử BXH ngày", daily_all.to_csv(index=False).encode("utf-8-sig"),
                          "chart_daily.csv", "text/csv")
    dl[2].download_button("Báo cáo làm sạch", data["cleaning_report"].to_csv(index=False).encode("utf-8-sig"),
                          "cleaning_report.csv", "text/csv")
