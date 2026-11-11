"""Kết nối kho dữ liệu DuckDB (1 file data/warehouse.duckdb, chia 4 schema).

    raw      : dữ liệu thô đọc từ landing (giữ nguyên dạng chuỗi như trên nguồn)
    staging  : dữ liệu đã làm sạch, ép kiểu, khử trùng lặp
    mart     : bảng phân tích (dim/fact) phục vụ dashboard
    meta     : nhật ký cập nhật + báo cáo làm sạch
"""
from __future__ import annotations

from contextlib import contextmanager

import duckdb
import pandas as pd

import config

SCHEMAS = ("raw", "staging", "mart", "meta")


@contextmanager
def connect():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(config.DB_PATH))
    try:
        for s in SCHEMAS:
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {s}")
        yield con
    finally:
        con.close()


def table_exists(con, name: str) -> bool:
    schema, table = name.split(".")
    n = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = ?",
        [schema, table],
    ).fetchone()[0]
    return n > 0


def write_df(con, name: str, df: pd.DataFrame, mode: str = "replace") -> int:
    """Ghi DataFrame vào bảng `schema.table`. mode = 'replace' | 'append'."""
    df = df.copy()
    for c in df.columns:
        # Cột toàn NULL kiểu object: DuckDB sẽ đoán thành INTEGER -> ép về chuỗi (VARCHAR)
        if df[c].dtype == object and df[c].isna().all():
            df[c] = df[c].astype("string")
    con.register("_incoming_df", df)
    try:
        if mode == "append" and table_exists(con, name):
            con.execute(f"INSERT INTO {name} BY NAME SELECT * FROM _incoming_df")
        else:
            con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _incoming_df")
    finally:
        con.unregister("_incoming_df")
    return len(df)


def read_df(con, name: str) -> pd.DataFrame:
    if not table_exists(con, name):
        return pd.DataFrame()
    df = con.execute(f"SELECT * FROM {name}").df()
    for c in df.columns:
        if df[c].isna().all():          # cột rỗng hoàn toàn -> kiểu object để xử lý chuỗi an toàn
            df[c] = df[c].astype(object)
    return df


def query(con, sql: str, params: list | None = None) -> pd.DataFrame:
    return con.execute(sql, params or []).df()


# ----------------------------------------------------------------------------
# Nhật ký cập nhật (meta.update_log) và báo cáo làm sạch (meta.cleaning_report)
# ----------------------------------------------------------------------------
def log_update(con, row: dict) -> None:
    write_df(con, "meta.update_log", pd.DataFrame([row]), mode="append")


def save_cleaning_report(con, rows: list[dict]) -> None:
    if rows:
        write_df(con, "meta.cleaning_report", pd.DataFrame(rows), mode="replace")
