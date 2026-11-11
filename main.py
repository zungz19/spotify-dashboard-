"""Điểm vào cho Streamlit Cloud (app trực tuyến được cấu hình chạy file main.py).

Dashboard thật nằm ở app/dashboard.py; file này chỉ gọi lại nó.
Chạy trên máy:  streamlit run app/dashboard.py   (hoặc streamlit run main.py)
"""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "app" / "dashboard.py"), run_name="__main__")
