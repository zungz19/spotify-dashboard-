"""Chạy pipeline từ dòng lệnh.

    python run_pipeline.py                      # chạy đầy đủ 6 bước (lần đầu ~30-40 phút)
    python run_pipeline.py --steps kworb clean mart   # chỉ lấy BXH mới + dựng lại bảng
    python run_pipeline.py --steps clean mart   # dựng lại staging/mart từ dữ liệu đã có (không cần mạng)
"""
import argparse
import sys

from src import pipeline

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Pipeline dữ liệu BXH Spotify Việt Nam vs Toàn cầu")
    ap.add_argument("--steps", nargs="+", choices=pipeline.ALL_STEPS, default=pipeline.ALL_STEPS)
    ap.add_argument("--mode", default="full", choices=["full", "update"])
    args = ap.parse_args()

    results = pipeline.run(mode=args.mode, steps=args.steps)
    print("\nTÓM TẮT:")
    for r in results:
        print(f"  {r['step']:<12} {r['status']:<8} {r['duration_s']:>7}s  {r['detail'][:150]}")
    sys.exit(0 if all(r["status"] == "success" for r in results) else 1)
