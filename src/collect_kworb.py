"""NGUỒN 1 - Kworb: bảng xếp hạng Spotify (web scraping).

Mỗi lần chạy tải 2 loại trang cho mỗi thị trường:
  * <market>_daily.html         : BXH Top 200 của ngày gần nhất (snapshot -> dùng cho
                                  phần "BXH hôm nay" và lịch sử thứ hạng)
  * <market>_daily_totals.html  : tổng hợp mọi bài từng lọt BXH ngày (số ngày trụ hạng,
                                  đỉnh, tổng stream) -> biến mục tiêu "độ thành công"

HTML gốc được lưu vào data/raw/kworb/<ngày tải>/ ; bảng raw giữ nguyên dạng chuỗi.
"""
from __future__ import annotations

import re

import pandas as pd
from bs4 import BeautifulSoup

import config
from src import db, http_client
from src.utils import log, nfc, now_iso, now_utc  # noqa: F401

TRACK_RE = re.compile(r"track/([A-Za-z0-9]{22})")
ARTIST_RE = re.compile(r"artist/([A-Za-z0-9]{22})")
DATE_RE = re.compile(r"(\d{4})/(\d{2})/(\d{2})")
PEAK_TIMES_RE = re.compile(r"^(\S+)\s*(\(x\d+\))$")

HEADER_MAP = {
    "pos": "pos", "p+": "pos_change", "artist and title": "artist_title",
    "days": "days", "t10": "t10", "pk": "peak", "(x?)": "peak_times",
    "pkstreams": "peak_streams", "streams": "streams", "streams+": "streams_change",
    "7day": "streams_7day", "7day+": "streams_7day_change", "total": "total_streams",
}


def page_url(market: str, kind: str) -> str:
    return f"{config.KWORB_BASE}{market}_{kind}.html"


def fetch_page(market: str, kind: str) -> tuple[str, str]:
    """Tải trang và lưu bản HTML gốc. Trả về (html, đường dẫn file)."""
    html = http_client.get_text(page_url(market, kind))
    day = now_utc().strftime("%Y-%m-%d")
    path = config.RAW_DIR / "kworb" / day / f"{market}_{kind}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return html, path.relative_to(config.RAW_DIR).as_posix()


# ----------------------------------------------------------------------------
# Bóc tách HTML
# ----------------------------------------------------------------------------
def _normalize_headers(ths) -> list[str]:
    out = []
    for th in ths:
        text = (nfc(th.get_text(" ")) or "").strip()
        # Một số trang gộp "Pk (x?)" vào 1 ô tiêu đề -> tách làm 2 cột
        if text.lower().replace(" ", "") == "pk(x?)":
            out += ["peak", "peak_times"]
            continue
        key = text.lower()
        out.append(HEADER_MAP.get(key, re.sub(r"[^a-z0-9]+", "_", key).strip("_")))
    return out


def _raw(el) -> str:
    """Lấy chữ NGUYÊN TRẠNG (chưa chuẩn hóa Unicode) - việc chuẩn hóa để dành cho tầng staging."""
    return el.get_text(" ").strip()


def _parse_title_cell(td) -> dict:
    links = td.find_all("a", href=True)
    track_pos = next((i for i, a in enumerate(links) if TRACK_RE.search(a["href"])), None)
    full_text = _raw(td)
    rec = {"artist_title": full_text, "track_id": None, "title": None,
           "artist_main": None, "artist_main_id": None, "featured": None, "featured_ids": None}
    if track_pos is None:
        return rec          # giữ lại dòng lỗi ở tầng raw; tầng staging sẽ loại và đếm
    track_a = links[track_pos]
    rec["track_id"] = TRACK_RE.search(track_a["href"]).group(1)
    rec["title"] = _raw(track_a)
    before = [a for a in links[:track_pos] if ARTIST_RE.search(a["href"])]
    after = [a for a in links[track_pos + 1:] if ARTIST_RE.search(a["href"])]
    if before:
        rec["artist_main"] = " & ".join(_raw(a) for a in before)
        rec["artist_main_id"] = ARTIST_RE.search(before[0]["href"]).group(1)
    elif " - " in full_text:
        rec["artist_main"] = full_text.split(" - ")[0]
    if after:
        rec["featured"] = "; ".join(_raw(a) for a in after)
        rec["featured_ids"] = ";".join(ARTIST_RE.search(a["href"]).group(1) for a in after)
    return rec


def _page_dates(html: str) -> list[str]:
    head = html[: html.find("<table")] if "<table" in html else html[:5000]
    text = BeautifulSoup(head, "lxml").get_text(" ")
    return [f"{y}-{m}-{d}" for y, m, d in DATE_RE.findall(text)]


def parse_chart_html(html: str) -> tuple[pd.DataFrame, str | None]:
    """Trả về (bảng các dòng dạng chuỗi, ngày dữ liệu của trang)."""
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    if not tables:
        raise ValueError("Không tìm thấy bảng nào trong trang Kworb")
    table = max(tables, key=lambda t: len(t.find_all("tr")))
    head_row = table.find("thead").find("tr") if table.find("thead") else table.find("tr")
    headers = _normalize_headers(head_row.find_all("th"))

    if "artist_title" not in headers:
        raise ValueError(f"Không thấy cột 'Artist and Title' trong tiêu đề: {headers}")
    title_idx = headers.index("artist_title")   # các cột trước nó không bị tách đôi

    rows = []
    body_rows = table.find("tbody").find_all("tr") if table.find("tbody") else table.find_all("tr")[1:]
    for tr in body_rows:
        tds = tr.find_all("td")
        if len(tds) <= title_idx:
            continue
        values: list = []
        for i, td in enumerate(tds):
            if i == title_idx:
                values.append("__TITLE__")
                continue
            text = _raw(td)
            m = PEAK_TIMES_RE.match(text)
            if m and "peak_times" in headers:
                values += [m.group(1), m.group(2)]     # "1 (x802)" -> "1", "(x802)"
            else:
                values.append(text)
        if len(values) != len(headers):
            raise ValueError(
                f"Số ô ({len(values)}) khác số cột tiêu đề ({len(headers)}): {headers} | {values}. "
                "Có thể Kworb đã đổi giao diện - hãy gửi file HTML trong data/raw/kworb/ để sửa parser."
            )
        rec = {h: v for h, v in zip(headers, values) if v != "__TITLE__"}
        rec.update(_parse_title_cell(tds[title_idx]))
        rows.append(rec)

    dates = _page_dates(html)
    page_date = max(dates) if dates else None
    return pd.DataFrame(rows), page_date


# ----------------------------------------------------------------------------
# Chạy thu thập
# ----------------------------------------------------------------------------
DAILY_COLS = ["market", "chart_date", "pos", "pos_change", "artist_title", "artist_main",
              "artist_main_id", "title", "featured", "featured_ids", "track_id", "days",
              "peak", "peak_times", "streams", "streams_change", "streams_7day",
              "streams_7day_change", "total_streams", "fetched_at", "source_file"]
TOTALS_COLS = ["market", "snapshot_date", "artist_title", "artist_main", "artist_main_id",
               "title", "featured", "featured_ids", "track_id", "days", "t10", "peak",
               "peak_times", "peak_streams", "total_streams", "fetched_at", "source_file"]


def _conform(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols].astype("string")


def collect(con, markets: list[str] | None = None) -> dict:
    """Tải BXH ngày + tổng hợp cho từng thị trường, ghi vào raw.kworb_*."""
    markets = markets or list(config.MARKETS)
    stats = {"daily_new_rows": 0, "totals_rows": 0, "new_chart_dates": []}
    fetched_at = now_iso()
    totals_frames = []

    for market in markets:
        # --- BXH ngày (snapshot, nối dần theo thời gian) ---
        html, src = fetch_page(market, "daily")
        df, chart_date = parse_chart_html(html)
        if not chart_date:
            chart_date = now_utc().strftime("%Y-%m-%d")
            log.warning("Không đọc được ngày trên trang %s_daily, dùng ngày hôm nay (UTC)", market)
        df["market"], df["chart_date"], df["fetched_at"], df["source_file"] = market, chart_date, fetched_at, src
        df = _conform(df, DAILY_COLS)
        already = 0
        if db.table_exists(con, "raw.kworb_chart_daily"):
            already = con.execute(
                "SELECT COUNT(*) FROM raw.kworb_chart_daily WHERE market = ? AND chart_date = ?",
                [market, chart_date],
            ).fetchone()[0]
        if already == 0:
            db.write_df(con, "raw.kworb_chart_daily", df, mode="append")
            stats["daily_new_rows"] += len(df)
            stats["new_chart_dates"].append(f"{market}:{chart_date}")
            log.info("Kworb %-6s BXH ngày %s: %d bài (mới)", market, chart_date, len(df))
        else:
            log.info("Kworb %-6s BXH ngày %s: đã có, bỏ qua", market, chart_date)

        # --- Tổng hợp toàn thời gian (thay bằng bản mới nhất) ---
        html, src = fetch_page(market, "daily_totals")
        tdf, snap_date = parse_chart_html(html)
        snap_date = snap_date or now_utc().strftime("%Y-%m-%d")
        tdf["market"], tdf["snapshot_date"], tdf["fetched_at"], tdf["source_file"] = market, snap_date, fetched_at, src
        totals_frames.append(_conform(tdf, TOTALS_COLS))
        log.info("Kworb %-6s tổng hợp (đến %s): %d bài", market, snap_date, len(tdf))

    totals = pd.concat(totals_frames, ignore_index=True)
    if set(markets) != set(config.MARKETS) and db.table_exists(con, "raw.kworb_totals"):
        keep = db.query(con, "SELECT * FROM raw.kworb_totals")
        keep = keep[~keep["market"].isin(markets)].astype("string")
        totals = pd.concat([keep, totals], ignore_index=True)
    db.write_df(con, "raw.kworb_totals", totals, mode="replace")
    stats["totals_rows"] = len(totals)
    return stats
